from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from unittest import mock

from packages.infrastructure.calendar_summary import CalendarAuthorizationError
from packages.infrastructure.calendar_summary import CalendarSummaryRunner
from packages.infrastructure.calendar_summary import build_calendar_summary
from packages.infrastructure.calendar_summary import normalize_calendar_event
from packages.infrastructure.calendar_summary import parse_calendar_date_range
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class CalendarSummaryTests(unittest.TestCase):
    def test_next_week_is_a_monday_to_sunday_interval(self) -> None:
        date_range = parse_calendar_date_range(
            "next week",
            timezone_name="UTC",
            now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(date_range.start.isoformat(), "2026-08-31T00:00:00+00:00")
        self.assertEqual(date_range.end.isoformat(), "2026-09-07T00:00:00+00:00")

    def test_runner_fetches_primary_calendar_and_builds_summary(self) -> None:
        requests: list[object] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            requests.append(request)
            self.assertEqual(timeout, 20)
            return _FakeResponse({
                "items": [{
                    "id": "event-1",
                    "summary": "Planning session",
                    "location": "Room 4",
                    "start": {"dateTime": "2026-08-31T10:00:00+03:00"},
                    "end": {"dateTime": "2026-08-31T11:00:00+03:00"},
                    "description": "Review the launch checklist.",
                }],
            })

        result = CalendarSummaryRunner(opener=opener).run(
            "token-that-stays-out-of-the-summary",
            time_window="next week",
            timezone_name="Asia/Jerusalem",
            now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(result["eventCount"], 1)
        self.assertIn("Planning session", result["message"])
        self.assertIn("Room 4", result["message"])
        request = requests[0]
        self.assertIn("/calendars/primary/events?", request.full_url)  # type: ignore[attr-defined]
        self.assertEqual(request.headers["Authorization"], "Bearer token-that-stays-out-of-the-summary")  # type: ignore[attr-defined]
        self.assertNotIn("token-that-stays-out-of-the-summary", result["message"])

    def test_empty_calendar_is_explicit(self) -> None:
        date_range = parse_calendar_date_range(
            "today",
            timezone_name="UTC",
            now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )
        self.assertIn("No meetings found", build_calendar_summary([], date_range))

    def test_invalid_date_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "couldn’t understand"):
            parse_calendar_date_range("sometime later", timezone_name="UTC")

    def test_unauthorized_calendar_response_is_actionable(self) -> None:
        def opener(_request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib_error.HTTPError(
                "https://www.googleapis.com",
                401,
                "Unauthorized",
                {},
                None,
            )

        with self.assertRaises(CalendarAuthorizationError):
            CalendarSummaryRunner(opener=opener).run("expired-token", time_window="today")

    def test_event_normalization_keeps_only_safe_summary_fields(self) -> None:
        event = normalize_calendar_event({
            "summary": "Standup",
            "start": {"date": "2026-08-31"},
            "end": {"date": "2026-09-01"},
            "description": "A short note",
        })
        assert event is not None
        self.assertEqual(event["title"], "Standup")
        self.assertTrue(event["allDay"])
        self.assertEqual(event["description"], "A short note")


class CalendarSummaryEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.server = create_server(
            "127.0.0.1",
            0,
            root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
            ),
        )
        if self.server.credential_vault is None:
            self.server.server_close()
            self.temp_dir.cleanup()
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")
        self.server.database.register_user("owner@example.com")
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="calendar",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt("calendar-token"),  # type: ignore[union-attr]
            secret_hint="••••oken",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
        )
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_calendar_proposal_run_uses_encrypted_connection_and_returns_chat_message(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "calendar-summary",
                "fields": {
                    "calendar": "Connected calendar",
                    "timeWindow": "next week",
                    "deliveryChannel": "portal",
                },
                "timezone": "UTC",
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        fake_result = {
            "message": "Meeting summary · Aug 31–Sep 6, 2026\\n\\n1 meeting:\\n• Mon, Aug 31 · 10:00 AM–11:00 AM — Planning session",
            "summary": "Meeting summary · Aug 31–Sep 6, 2026",
            "eventCount": 1,
            "dateRange": {"display": "Aug 31–Sep 6, 2026"},
        }
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
            return_value=fake_result,
        ) as run:
            with urllib_request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["eventCount"], 1)
        self.assertIn("Planning session", payload["message"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "calendar-token")

    def test_calendar_proposal_run_rejects_external_delivery_until_supported(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "calendar-summary",
                "fields": {
                    "timeWindow": "next week",
                    "deliveryChannel": "email",
                },
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 409)
        self.assertIn("This meeting summary runner currently delivers into this chat", context.exception.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
