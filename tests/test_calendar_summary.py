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
from packages.infrastructure.calendar_summary import CalendarSummaryRunner
from packages.infrastructure.calendar_summary import build_calendar_summary
from packages.infrastructure.calendar_summary import normalize_calendar_event
from packages.infrastructure.calendar_summary import parse_calendar_date_range
from packages.infrastructure.gmail_summary import GmailDigestRunner
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
