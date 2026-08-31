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
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from unittest import mock

from packages.infrastructure.calendar_summary import CalendarAuthorizationError
from packages.infrastructure.calendar_summary import CalendarListUnavailableError
from packages.infrastructure.calendar_summary import CalendarNotSharedError
from packages.infrastructure.calendar_summary import CalendarSummaryRunner
from packages.infrastructure.calendar_summary import build_calendar_summary
from packages.infrastructure.calendar_summary import describe_availability
from packages.infrastructure.calendar_summary import normalize_calendar_event
from packages.infrastructure.calendar_summary import parse_calendar_date_range
from packages.infrastructure.calendar_summary import parse_calendar_ids
from packages.infrastructure.calendar_summary import resolve_calendar_ids
from packages.infrastructure.gmail_summary import GmailDigestRunner
from packages.infrastructure.portal_auth.server import CALENDAR_SELECTION_METADATA_KEY
from packages.infrastructure.portal_auth.server import GOOGLE_CALENDAR_LIST_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_TOKEN_URL
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


# Patching urlopen on the server module patches urllib.request globally, so a
# blanket patch also swallows these tests' own requests to the portal under
# test. Only the provider token and revoke endpoints are stubbed; everything
# else goes to the real opener.
_PROVIDER_HOSTS = ("oauth2.googleapis.com", "accounts.google.com", "login.microsoftonline.com")


def _provider_endpoint_patch(responder, target="packages.infrastructure.portal_auth.server.urllib_request.urlopen"):
    real_urlopen = urllib_request.urlopen

    def routed(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        if any(host in url for host in _PROVIDER_HOSTS):
            return responder(request, timeout=timeout)
        return real_urlopen(request, timeout=timeout, **kwargs)

    return mock.patch(target, side_effect=routed)


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

    def test_a_period_written_in_plain_words_is_read(self) -> None:
        # The field holds what the person said, not an entry from a list, so
        # the part of a day, a weekday, a rolling count and a written-out date
        # all have to land on the right days.
        monday = datetime(2026, 8, 31, 9, tzinfo=timezone.utc)
        cases = {
            "tomorrow morning": ("2026-09-01", "2026-09-01"),
            "this afternoon": ("2026-08-31", "2026-08-31"),
            "tonight": ("2026-08-31", "2026-08-31"),
            "thursday": ("2026-09-03", "2026-09-03"),
            "next thursday": ("2026-09-10", "2026-09-10"),
            "last thursday": ("2026-08-27", "2026-08-27"),
            "this weekend": ("2026-09-05", "2026-09-06"),
            "the next 3 days": ("2026-08-31", "2026-09-02"),
            "the next couple of days": ("2026-08-31", "2026-09-01"),
            "the last 7 days": ("2026-08-25", "2026-08-31"),
            "september 3": ("2026-09-03", "2026-09-03"),
            "3 september": ("2026-09-03", "2026-09-03"),
            "the 15th": ("2026-09-15", "2026-09-15"),
            "2026-09-04": ("2026-09-04", "2026-09-04"),
            "in september": ("2026-09-01", "2026-09-30"),
        }
        for value, (start, end) in cases.items():
            with self.subTest(value=value):
                date_range = parse_calendar_date_range(value, timezone_name="UTC", now=monday)
                self.assertEqual(date_range.label, f"{start} to {end}")
                self.assertFalse(date_range.assumed)

    def test_a_period_buried_in_a_sentence_is_still_found(self) -> None:
        # The field is meant to hold the period on its own, but a sentence
        # lands in it often enough that the days in it should still be read.
        date_range = parse_calendar_date_range(
            "am I available tomorrow morning?",
            timezone_name="UTC",
            now=datetime(2026, 8, 31, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(date_range.label, "2026-09-01 to 2026-09-01")
        self.assertFalse(date_range.assumed)

    def test_a_range_written_back_to_front_is_read_rather_than_refused(self) -> None:
        date_range = parse_calendar_date_range(
            "2026-09-05 to 2026-09-01",
            timezone_name="UTC",
            now=datetime(2026, 8, 31, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(date_range.label, "2026-09-01 to 2026-09-05")

    def test_words_that_name_no_period_read_the_week_ahead_and_say_so(self) -> None:
        # A question about the diary is better answered with the days it read
        # named out loud than refused over its phrasing.
        date_range = parse_calendar_date_range(
            "sometime later",
            timezone_name="UTC",
            now=datetime(2026, 8, 31, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(date_range.label, "2026-08-31 to 2026-09-06")
        self.assertTrue(date_range.assumed)
        availability = describe_availability([], date_range, timezone_name="UTC")
        self.assertIn("dateRangeAssumed", availability)

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

    def test_calendar_tags_become_calendar_ids(self) -> None:
        # Every tag that is not an address means the connected account's own
        # calendar, whatever the portal happened to label it.
        self.assertEqual(parse_calendar_ids(""), ["primary"])
        self.assertEqual(parse_calendar_ids("Connected calendar"), ["primary"])
        self.assertEqual(parse_calendar_ids("Google Calendar (owner@example.com)"), ["primary"])
        self.assertEqual(
            parse_calendar_ids("Google Calendar, Alex@Example.com, alex@example.com"),
            ["primary", "alex@example.com"],
        )
        self.assertEqual(parse_calendar_ids(["Google Calendar", "dana@example.org"]), ["primary", "dana@example.org"])

    def test_a_question_about_my_calendar_reads_every_calendar_the_account_chose(self) -> None:
        # "What is on my calendar" names no calendar, so it reads all of them.
        self.assertEqual(
            resolve_calendar_ids(
                "Connected calendar",
                account_calendar_ids=["primary", "family@group.calendar.google.com"],
            ),
            ["primary", "family@group.calendar.google.com"],
        )
        # An action that named calendars asked a narrower question and keeps it.
        self.assertEqual(
            resolve_calendar_ids(
                "dana@example.org",
                account_calendar_ids=["primary", "family@group.calendar.google.com"],
            ),
            ["dana@example.org"],
        )
        # Nothing chosen yet still reads the account's own calendar.
        self.assertEqual(resolve_calendar_ids("Connected calendar", account_calendar_ids=[]), ["primary"])
        self.assertEqual(resolve_calendar_ids(""), ["primary"])

    def test_calendar_id_is_never_a_url_or_a_path(self) -> None:
        self.assertEqual(parse_calendar_ids("https://example.com/../secrets"), ["primary"])
        self.assertEqual(parse_calendar_ids("primary/events?key=1"), ["primary"])

    def test_extra_calendars_are_merged_and_deduplicated(self) -> None:
        requested: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            requested.append(request.full_url)
            shared = {
                "id": "event-shared",
                "summary": "Launch review",
                "start": {"dateTime": "2026-08-31T09:00:00+00:00"},
                "end": {"dateTime": "2026-08-31T10:00:00+00:00"},
            }
            if "/calendars/primary/events?" in request.full_url:
                return _FakeResponse({"items": [shared]})
            return _FakeResponse({
                "items": [
                    shared,
                    {
                        "id": "event-2",
                        "summary": "Site visit",
                        "start": {"dateTime": "2026-08-31T08:00:00+00:00"},
                        "end": {"dateTime": "2026-08-31T08:30:00+00:00"},
                    },
                ],
            })

        result = CalendarSummaryRunner(opener=opener).run(
            "calendar-token",
            calendar_ids="Google Calendar, dana@example.org",
            time_window="next week",
            timezone_name="UTC",
            now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(result["calendars"], ["primary", "dana@example.org"])
        self.assertEqual(result["eventCount"], 2)
        self.assertEqual(result["skippedCalendars"], [])
        # The meeting on both calendars is reported once, and the earlier one
        # leads even though it came from the second calendar read.
        self.assertEqual(result["message"].count("Launch review"), 1)
        self.assertLess(result["message"].index("Site visit"), result["message"].index("Launch review"))
        self.assertIn("/calendars/dana%40example.org/events?", requested[1])

    def test_unshared_extra_calendar_is_named_without_losing_the_others(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            if "/calendars/primary/events?" in request.full_url:
                return _FakeResponse({
                    "items": [{
                        "id": "event-1",
                        "summary": "Planning session",
                        "start": {"dateTime": "2026-08-31T10:00:00+00:00"},
                        "end": {"dateTime": "2026-08-31T11:00:00+00:00"},
                    }],
                })
            raise urllib_error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        result = CalendarSummaryRunner(opener=opener).run(
            "calendar-token",
            calendar_ids="Google Calendar, dana@example.org",
            time_window="next week",
            timezone_name="UTC",
            now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(result["eventCount"], 1)
        self.assertIn("Planning session", result["message"])
        self.assertEqual([entry["calendar"] for entry in result["skippedCalendars"]], ["dana@example.org"])
        self.assertIn("dana@example.org", result["message"])
        self.assertIn("share their calendar", result["message"])

    def test_extra_calendar_permission_error_leaves_the_connection_alone(self) -> None:
        # A 403 on an extra calendar is a sharing problem with that calendar.
        # Only the connected account's own calendar means the credential broke.
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib_error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

        with self.assertRaises(CalendarAuthorizationError):
            CalendarSummaryRunner(opener=opener).run("calendar-token", time_window="today")

        runner = CalendarSummaryRunner(opener=opener)
        date_range = parse_calendar_date_range(
            "today",
            timezone_name="UTC",
            now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )
        with self.assertRaises(CalendarNotSharedError):
            runner.fetch_events("calendar-token", calendar_id="dana@example.org", date_range=date_range)

    def test_calendar_list_names_every_readable_calendar_in_the_account(self) -> None:
        requests: list[object] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            requests.append(request)
            return _FakeResponse({
                "items": [
                    {
                        "id": "owner@example.com",
                        "summary": "owner@example.com",
                        "summaryOverride": "Alex Rivera",
                        "primary": True,
                        "accessRole": "owner",
                        "backgroundColor": "#9FE1E7",
                    },
                    {
                        "id": "c_family@group.calendar.google.com",
                        "summary": "Family",
                        "accessRole": "reader",
                        # Not a colour the portal can put in a style, so this
                        # calendar comes back without one rather than with it.
                        "backgroundColor": "tomato",
                    },
                    # Busy blocks with no titles are nothing an action could
                    # summarize, so this one is never offered.
                    {
                        "id": "c_busy@group.calendar.google.com",
                        "summary": "Room booking",
                        "accessRole": "freeBusyReader",
                    },
                ],
            })

        calendars = CalendarSummaryRunner(opener=opener).fetch_calendar_list("calendar-token")

        self.assertEqual(
            calendars,
            [
                {
                    "id": "primary",
                    "label": "Alex Rivera",
                    "primary": True,
                    "accessRole": "owner",
                    "color": "#9fe1e7",
                },
                {
                    "id": "c_family@group.calendar.google.com",
                    "label": "Family",
                    "primary": False,
                    "accessRole": "reader",
                    "color": "",
                },
            ],
        )
        self.assertIn("/users/me/calendarList?", requests[0].full_url)  # type: ignore[attr-defined]
        self.assertEqual(requests[0].headers["Authorization"], "Bearer calendar-token")  # type: ignore[attr-defined]

    def test_calendar_list_without_its_grant_asks_for_a_reconnect(self) -> None:
        # A connection made before the portal asked to see the account's list of
        # calendars still summarizes; only the picker needs the reconnect.
        def opener(_request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib_error.HTTPError("https://www.googleapis.com", 403, "Forbidden", {}, None)

        with self.assertRaises(CalendarListUnavailableError) as context:
            CalendarSummaryRunner(opener=opener).fetch_calendar_list("events-only-token")

        self.assertEqual(context.exception.code, "calendar_list_scope_missing")

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


class GmailDigestTests(unittest.TestCase):
    def test_runner_lists_messages_and_builds_digest(self) -> None:
        requests: list[object] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            requests.append(request)
            self.assertEqual(timeout, 20)
            if request.full_url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):  # type: ignore[attr-defined]
                return _FakeResponse({
                    "messages": [{"id": "msg-1", "threadId": "thread-1"}],
                    "resultSizeEstimate": 1,
                })
            self.assertIn("/messages/msg-1?", request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({
                "id": "msg-1",
                "threadId": "thread-1",
                "snippet": "Please review the proposal by Friday.",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Maya <maya@example.com>"},
                        {"name": "Subject", "value": "Proposal review"},
                        {"name": "Date", "value": "Thu, 27 Aug 2026 08:15:00 +0000"},
                    ],
                },
            })

        result = GmailDigestRunner(opener=opener).run("gmail-token", query="in:inbox newer_than:1d")

        self.assertEqual(result["messageCount"], 1)
        self.assertIn("Proposal review", result["message"])
        self.assertIn("Maya", result["message"])
        self.assertIn("Please review", result["message"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer gmail-token")  # type: ignore[attr-defined]
        self.assertNotIn("gmail-token", result["message"])

    def test_runner_saves_receipt_image_attachments(self) -> None:
        requests: list[object] = []
        image_bytes = b"small-receipt-image"
        image_data = base64.urlsafe_b64encode(image_bytes).decode("ascii").rstrip("=")

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            requests.append(request)
            self.assertEqual(timeout, 20)
            if request.full_url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):  # type: ignore[attr-defined]
                return _FakeResponse({
                    "messages": [{"id": "msg-1", "threadId": "thread-1"}],
                    "resultSizeEstimate": 1,
                })
            if "/attachments/att-1" in request.full_url:  # type: ignore[attr-defined]
                return _FakeResponse({"data": image_data, "size": len(image_bytes)})
            self.assertIn("/messages/msg-1?", request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({
                "id": "msg-1",
                "threadId": "thread-1",
                "snippet": "Total USD 19.95",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Store <receipts@example.com>"},
                        {"name": "Subject", "value": "Receipt"},
                        {"name": "Date", "value": "Thu, 27 Aug 2026 08:15:00 +0000"},
                    ],
                    "parts": [{
                        "filename": "receipt.png",
                        "mimeType": "image/png",
                        "body": {"attachmentId": "att-1", "size": len(image_bytes)},
                    }],
                },
            })

        with tempfile.TemporaryDirectory() as temp_dir:
            result = GmailDigestRunner(opener=opener).run(
                "gmail-token",
                query="receipt after:2026/08/01 before:2026/09/01",
                include_attachments=True,
                attachment_output_dir=Path(temp_dir),
                attachment_url_prefix="/output/agent_receipts/owner/Receipts/Aug2026/attachments",
            )

            attachment = result["items"][0]["attachments"][0]
            attachment_path = Path(attachment["path"])
            self.assertTrue(attachment_path.exists())
            self.assertEqual(attachment_path.read_bytes(), image_bytes)
            self.assertEqual(attachment["mimeType"], "image/png")
            self.assertTrue(attachment["url"].endswith("/attachments/msg-1-01-receipt.png"))
            self.assertEqual(len(requests), 3)


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
                agent_output_dir=Path(self.temp_dir.name) / "agent_outputs",
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
        connection = self.server.database.list_platform_connections("owner@example.com")[0]
        self.assertEqual(connection["connectionStatus"], "connected")
        self.assertEqual(connection["metadata"]["validationStatus"], "verified")

    def test_calendar_proposal_run_reads_every_tagged_calendar(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "calendar-summary",
                "fields": {
                    "calendar": "Google Calendar, dana@example.org",
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
            "message": "Meeting summary · Aug 31–Sep 6, 2026",
            "summary": "Meeting summary · Aug 31–Sep 6, 2026",
            "eventCount": 2,
            "calendars": ["primary", "dana@example.org"],
            "skippedCalendars": [{"calendar": "dana@example.org", "message": "I couldn’t read dana@example.org."}],
            "dateRange": {"display": "Aug 31–Sep 6, 2026"},
        }
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
            return_value=fake_result,
        ) as run:
            with urllib_request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(run.call_args.kwargs["calendar_ids"], ["primary", "dana@example.org"])
        self.assertEqual(payload["calendars"], ["primary", "dana@example.org"])
        self.assertEqual(payload["skippedCalendars"][0]["calendar"], "dana@example.org")

    def test_calendar_proposal_run_refreshes_oauth_calendar_token(self) -> None:
        self.server.config.google_oauth_client_id = "google-client-id.apps.googleusercontent.com"
        self.server.config.google_oauth_client_secret = "google-client-secret"
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="calendar",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": "google_calendar_refresh_token",
                "provider": "google_calendar",
                "refreshToken": "saved-refresh-token",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            metadata={"provider": "google_calendar", "validationStatus": "verified"},
        )
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "calendar-summary",
                "fields": {
                    "calendar": "Connected calendar",
                    "timeWindow": "today",
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

        def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
            self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
            fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(fields["grant_type"], ["refresh_token"])
            self.assertEqual(fields["refresh_token"], ["saved-refresh-token"])
            return _FakeResponse({"access_token": "fresh-google-access-token"})

        fake_result = {
            "message": "Meeting summary · Aug 25, 2026",
            "summary": "Meeting summary · Aug 25, 2026",
            "eventCount": 0,
            "dateRange": {"display": "Aug 25, 2026"},
        }
        with _provider_endpoint_patch(fake_urlopen):
            with mock.patch(
                "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
                return_value=fake_result,
            ) as run:
                with urllib_request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "fresh-google-access-token")
        connection = self.server.database.list_platform_connections("owner@example.com")[0]
        self.assertEqual(connection["metadata"]["credentialSource"], "google_oauth_refresh_token")

    def test_email_digest_proposal_run_refreshes_gmail_token_and_returns_digest(self) -> None:
        self.server.config.google_oauth_client_id = "google-client-id.apps.googleusercontent.com"
        self.server.config.google_oauth_client_secret = "google-client-secret"
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": GOOGLE_OAUTH_SECRET_TYPE,
                "provider": "google",
                "refreshToken": "saved-gmail-refresh-token",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "email-digest",
                "fields": {
                    "mailbox": "Gmail",
                    "deliveryChannel": "portal",
                },
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )

        def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
            self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
            fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(fields["grant_type"], ["refresh_token"])
            self.assertEqual(fields["refresh_token"], ["saved-gmail-refresh-token"])
            return _FakeResponse({"access_token": "fresh-gmail-access-token"})

        fake_result = {
            "message": "Gmail digest\n\n1 recent message:\n1. Proposal review - Maya",
            "summary": "Gmail digest - 1 message",
            "messageCount": 1,
            "items": [{"subject": "Proposal review"}],
        }
        with _provider_endpoint_patch(fake_urlopen):
            with mock.patch(
                "packages.infrastructure.portal_auth.server.GmailDigestRunner.run",
                return_value=fake_result,
            ) as run:
                with urllib_request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["messageCount"], 1)
        self.assertIn("Proposal review", payload["message"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "fresh-gmail-access-token")
        connection = [
            item for item in self.server.database.list_platform_connections("owner@example.com")
            if item["platform"] == "email"
        ][0]
        self.assertEqual(connection["metadata"]["credentialSource"], "google_oauth_refresh_token")

    def test_custom_receipt_proposal_run_uses_gmail_month_query(self) -> None:
        self.server.config.google_oauth_client_id = "google-client-id.apps.googleusercontent.com"
        self.server.config.google_oauth_client_secret = "google-client-secret"
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": GOOGLE_OAUTH_SECRET_TYPE,
                "provider": "google",
                "refreshToken": "saved-gmail-refresh-token",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "custom",
                "fields": {
                    "result": "Pull all receipts for August 2026",
                    "manualRunMonth": "2026-08",
                    "outputFolder": "Receipts/Aug2026/",
                    "deliveryChannel": "portal",
                },
                "deliveryChannel": "portal",
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )

        def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
            self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
            fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(fields["grant_type"], ["refresh_token"])
            self.assertEqual(fields["refresh_token"], ["saved-gmail-refresh-token"])
            return _FakeResponse({"access_token": "fresh-gmail-access-token"})

        fake_result = {
            "message": "Gmail digest\n\n1 recent message:\n1. Receipt - Store",
            "summary": "Gmail digest - 1 message",
            "messageCount": 1,
            "items": [{
                "id": "msg-1",
                "threadId": "thread-1",
                "from": "Store <receipts@example.com>",
                "subject": "Receipt - Store",
                "date": "Thu, 27 Aug 2026 08:15:00 +0000",
                "snippet": "Total USD 19.95",
            }],
        }
        with _provider_endpoint_patch(fake_urlopen):
            with mock.patch(
                "packages.infrastructure.portal_auth.server.GmailDigestRunner.run",
                return_value=fake_result,
            ) as run:
                with urllib_request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["messageCount"], 1)
        # The notification offers the download; the counts live in the PDF.
        self.assertIn("ready to download", payload["message"])
        self.assertIn("Receipt search", payload["summary"])
        # The query is described in words now, because the same action can run
        # against a Gmail or an Outlook mailbox.
        self.assertIn("2026-08-01", payload["query"])
        self.assertIn("2026-09-01", payload["query"])
        self.assertIn("receipt", payload["query"])
        self.assertEqual(payload["outputFolder"], "Receipts/Aug2026/")
        self.assertEqual(payload["receiptCount"], 1)
        self.assertIn("receipt-report.pdf", payload["resultUrl"])
        self.assertEqual(payload["hrefLabel"], "Open PDF")
        self.assertTrue(Path(payload["artifacts"]["pdf"]["path"]).exists())
        self.assertTrue(Path(payload["artifacts"]["excel"]["path"]).exists())
        # Receipts are private financial documents, so the download is only
        # served to the session that owns them.
        download = urllib_request.Request(
            f"{self.base_url}{payload['resultUrl']}",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with urllib_request.urlopen(download, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(4), b"%PDF")
        with self.assertRaises(urllib_error.HTTPError) as unauthenticated:
            urllib_request.urlopen(f"{self.base_url}{payload['resultUrl']}", timeout=5)
        self.assertEqual(unauthenticated.exception.code, 404)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "fresh-gmail-access-token")
        self.assertEqual(run.call_args.kwargs["query"].describe(), payload["query"])
        self.assertTrue(run.call_args.kwargs["include_attachments"])
        self.assertIn("Receipts/Aug2026/attachments", str(run.call_args.kwargs["attachment_output_dir"]))

    def test_calendar_proposal_run_marks_rejected_credential_as_needing_attention(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "calendar-summary",
                "fields": {"timeWindow": "next week", "deliveryChannel": "portal"},
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
            side_effect=CalendarAuthorizationError("Calendar access needs attention."),
        ):
            with self.assertRaises(urllib_error.HTTPError) as context:
                urllib_request.urlopen(request, timeout=5)

        self.assertEqual(context.exception.code, 409)
        self.assertIn("needs attention", context.exception.read().decode("utf-8"))
        connection = self.server.database.list_platform_connections("owner@example.com")[0]
        self.assertEqual(connection["connectionStatus"], "needs_attention")
        self.assertEqual(connection["metadata"]["validationStatus"], "failed")

    def _get_calendar_sources(self) -> dict[str, object]:
        request = urllib_request.Request(
            f"{self.base_url}/api/platform-connections/calendars",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_calendar_sources_list_the_calendars_inside_each_connection(self) -> None:
        listed = [
            {"id": "primary", "label": "Alex Rivera", "primary": True, "accessRole": "owner"},
            {
                "id": "c_family@group.calendar.google.com",
                "label": "Family",
                "primary": False,
                "accessRole": "reader",
            },
        ]
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.fetch_calendar_list",
            return_value=listed,
        ) as fetch:
            payload = self._get_calendar_sources()

        self.assertTrue(payload["ok"])
        source = payload["sources"][0]  # type: ignore[index]
        self.assertEqual(source["platform"], "calendar")
        self.assertEqual(source["label"], "Google Calendar")
        self.assertEqual(source["status"], "ok")
        self.assertEqual([calendar["label"] for calendar in source["calendars"]], ["Alex Rivera", "Family"])
        self.assertEqual(fetch.call_args.args[0], "calendar-token")
        # The credential behind the list never leaves the server.
        self.assertNotIn("calendar-token", json.dumps(payload))

    def test_calendar_sources_ask_for_a_reconnect_rather_than_looking_empty(self) -> None:
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.fetch_calendar_list",
            side_effect=CalendarListUnavailableError(),
        ):
            payload = self._get_calendar_sources()

        source = payload["sources"][0]  # type: ignore[index]
        self.assertEqual(source["status"], "needs_reconnect")
        self.assertEqual(source["calendars"], [])
        self.assertIn("Reconnect Google Calendar", source["message"])

    def test_calendar_sources_need_a_session(self) -> None:
        request = urllib_request.Request(f"{self.base_url}/api/platform-connections/calendars")
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request, timeout=5)

        self.assertEqual(context.exception.code, 401)

    def _set_chosen_calendars(self, calendars: list[dict[str, str]], *, granted_list_scope: bool = True) -> None:
        metadata: dict[str, object] = {CALENDAR_SELECTION_METADATA_KEY: calendars}
        if granted_list_scope:
            metadata["grantedScope"] = GOOGLE_CALENDAR_LIST_OAUTH_SCOPE
        self.server.database.update_platform_connection_status(
            "owner@example.com",
            platform="calendar",
            connection_status="connected",
            metadata_updates=metadata,
        )

    def _post_chosen_calendars(self, payload: dict[str, object]) -> dict[str, object]:
        request = urllib_request.Request(
            f"{self.base_url}/api/platform-connections/calendars",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _run_calendar_question(self, calendar_field: str) -> mock.MagicMock:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "calendar-summary",
                "fields": {
                    "calendar": calendar_field,
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
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
            return_value={
                "message": "Meeting summary · Aug 31–Sep 6, 2026",
                "summary": "Meeting summary · Aug 31–Sep 6, 2026",
                "eventCount": 0,
                "dateRange": {"display": "Aug 31–Sep 6, 2026"},
            },
        ) as run:
            with urllib_request.urlopen(request, timeout=5) as response:
                response.read()
        return run

    def test_a_calendar_question_reads_every_calendar_the_account_chose(self) -> None:
        self._set_chosen_calendars([
            {"id": "primary", "label": "My calendar"},
            {"id": "family@group.calendar.google.com", "label": "Family"},
        ])

        run = self._run_calendar_question("Connected calendar")

        self.assertEqual(
            run.call_args.kwargs["calendar_ids"],
            ["primary", "family@group.calendar.google.com"],
        )

    def test_an_action_that_named_a_calendar_keeps_reading_only_that_one(self) -> None:
        self._set_chosen_calendars([
            {"id": "primary", "label": "My calendar"},
            {"id": "family@group.calendar.google.com", "label": "Family"},
        ])

        run = self._run_calendar_question("dana@example.org")

        self.assertEqual(run.call_args.kwargs["calendar_ids"], ["dana@example.org"])

    def test_a_connection_never_asked_discovers_its_calendars_once_and_remembers_them(self) -> None:
        self.server.database.update_platform_connection_status(
            "owner@example.com",
            platform="calendar",
            connection_status="connected",
            metadata_updates={"grantedScope": GOOGLE_CALENDAR_LIST_OAUTH_SCOPE},
        )
        listed = [
            {"id": "primary", "label": "Alex Rivera", "primary": True, "accessRole": "owner"},
            {
                "id": "c_family@group.calendar.google.com",
                "label": "Family",
                "primary": False,
                "accessRole": "reader",
            },
        ]
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.fetch_calendar_list",
            return_value=listed,
        ) as fetch:
            run = self._run_calendar_question("Connected calendar")

        fetch.assert_called_once()
        self.assertEqual(
            run.call_args.kwargs["calendar_ids"],
            ["primary", "c_family@group.calendar.google.com"],
        )
        connection = self.server.database.list_platform_connections("owner@example.com")[0]
        self.assertEqual(
            [entry["id"] for entry in connection["metadata"][CALENDAR_SELECTION_METADATA_KEY]],
            ["primary", "c_family@group.calendar.google.com"],
        )

    def test_a_connection_without_the_list_grant_reads_its_own_calendar_without_asking(self) -> None:
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.fetch_calendar_list",
        ) as fetch:
            run = self._run_calendar_question("Connected calendar")

        fetch.assert_not_called()
        self.assertEqual(run.call_args.kwargs["calendar_ids"], ["primary"])

    def test_chosen_calendars_are_saved_on_the_connection(self) -> None:
        payload = self._post_chosen_calendars({
            "calendarIds": ["primary", "family@group.calendar.google.com"],
        })

        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["selectedCalendarIds"],
            ["primary", "family@group.calendar.google.com"],
        )
        connection = self.server.database.list_platform_connections("owner@example.com")[0]
        self.assertEqual(
            [entry["id"] for entry in connection["metadata"][CALENDAR_SELECTION_METADATA_KEY]],
            ["primary", "family@group.calendar.google.com"],
        )
        # Choosing calendars says nothing about the credential's health.
        self.assertEqual(connection["connectionStatus"], "connected")

    def test_choosing_no_calendar_is_refused_rather_than_read_as_all_of_them(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as context:
            self._post_chosen_calendars({"calendarIds": []})

        self.assertEqual(context.exception.code, 400)

    def test_calendar_sources_offer_every_calendar_until_the_account_has_chosen(self) -> None:
        listed = [
            {"id": "primary", "label": "Alex Rivera", "primary": True, "accessRole": "owner"},
            {
                "id": "c_family@group.calendar.google.com",
                "label": "Family",
                "primary": False,
                "accessRole": "reader",
            },
        ]
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.fetch_calendar_list",
            return_value=listed,
        ):
            payload = self._get_calendar_sources()

        source = payload["sources"][0]  # type: ignore[index]
        self.assertEqual(
            source["selectedCalendarIds"],
            ["primary", "c_family@group.calendar.google.com"],
        )

        self._set_chosen_calendars([{"id": "primary", "label": "Alex Rivera"}])
        with mock.patch(
            "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.fetch_calendar_list",
            return_value=listed,
        ):
            payload = self._get_calendar_sources()

        source = payload["sources"][0]  # type: ignore[index]
        self.assertEqual(source["selectedCalendarIds"], ["primary"])
        self.assertEqual([entry["label"] for entry in source["selectedCalendars"]], ["Alex Rivera"])

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
        self.assertIn("This meeting summary runner currently delivers into Notifications", context.exception.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
