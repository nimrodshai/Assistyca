from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_auth.server import create_server
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID
from packages.infrastructure.whatsapp_messaging import extract_inbound_events
from packages.infrastructure.whatsapp_messaging import send_whatsapp_message



class PortalManualRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        # The approval store must live in the temp dir too, or every run of
        # this class shares portal/portal-whatsapp/user-1.json and inherits
        # approvals left behind by earlier runs.
        self.env_patcher = mock.patch.dict(
            os.environ,
            {"PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp")},
            clear=False,
        )
        self.env_patcher.start()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.server.database.register_user("owner@example.com")
        self.server.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "watchItems": ["Criminal defense law conferences"],
                    "intervalDays": 1,
                    "deliveryChannel": "email",
                }
            },
        )
        self.server.database.set_feature_activation(
            "owner@example.com",
            feature_id=MONITOR_FEATURE_ID,
            feature_name="Scheduled Web Monitor",
            is_active=True,
            activated_at="2026-07-09T09:00:00+00:00",
        )
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, result = self.server.store.verify_code("owner@example.com", code)
        assert ok and result is not None
        self.session_token = result["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def _request(self, method: str, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method=method,
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body

    def test_delete_run_marks_active_manual_run_cancelled(self) -> None:
        request_started = threading.Event()
        post_result: dict[str, object] = {}

        def fake_run_for_email(_scheduler, email: str, *, now=None, cancel_check=None):
            self.assertEqual(email, "owner@example.com")
            request_started.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                if callable(cancel_check) and cancel_check():
                    return {
                        "ok": True,
                        "run": {
                            "status": "cancelled",
                            "scheduledFor": "2026-07-13T12:00:00+00:00",
                            "findingsCount": 0,
                            "notificationsSent": 0,
                            "run": {
                                "metadata": {
                                    "cancelled": True,
                                },
                            },
                        },
                    }
                time.sleep(0.01)
            return {
                "ok": False,
                "error": "cancel_timeout",
                "message": "Cancellation was never received.",
            }

        def send_post() -> None:
            try:
                status, body = self._request(
                    "POST",
                    f"/api/features/{MONITOR_FEATURE_ID}/run",
                    {"runRequestId": "manual-run-1"},
                )
                post_result["status"] = status
                post_result["body"] = body
            except Exception as exc:  # pragma: no cover - test failure surface
                post_result["error"] = exc

        with mock.patch(
            "packages.infrastructure.portal_auth.server.ScheduledMonitorScheduler.run_for_email",
            new=fake_run_for_email,
        ):
            post_thread = threading.Thread(target=send_post, daemon=True)
            post_thread.start()
            self.assertTrue(request_started.wait(timeout=1))

            cancel_status, cancel_body = self._request(
                "DELETE",
                f"/api/features/{MONITOR_FEATURE_ID}/run",
                {"runRequestId": "manual-run-1"},
            )

            post_thread.join(timeout=2)

        if "error" in post_result:
            raise post_result["error"]  # type: ignore[misc]

        self.assertEqual(cancel_status, 200)
        self.assertTrue(cancel_body["ok"])
        self.assertEqual(post_result["status"], 200)
        self.assertEqual(post_result["body"]["run"]["status"], "cancelled")
        self.assertIn("cancelled", str(post_result["body"]["message"]).lower())

class WhatsAppSendFormattingTests(unittest.TestCase):
    def test_send_whatsapp_message_formats_hello_world_template_error(self) -> None:
        error_body = json.dumps(
            {
                "error": {
                    "message": "(#131058) Hello World templates can only be sent from the Public Test Numbers",
                    "code": 131058,
                    "type": "OAuthException",
                }
            }
        ).encode("utf-8")
        http_error = urllib_error.HTTPError(
            url="https://graph.facebook.com/v20.0/12345/messages",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(error_body),
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_messaging.urllib_request.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaises(RuntimeError) as context:
                send_whatsapp_message(
                    access_token="test-token",
                    phone_number_id="12345",
                    api_version="v20.0",
                    recipient_wa_id="15551234567",
                    template={
                        "name": "hello_world",
                        "language": {
                            "code": "en_US",
                        },
                    },
                )

        self.assertIn("hello_world template", str(context.exception))
        self.assertIn("Public Test Numbers", str(context.exception))


class WhatsAppWebhookSignatureTests(unittest.TestCase):
    """The webhook must fail closed when no app secret is configured."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patcher = mock.patch.dict(
            os.environ,
            {"PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp")},
            clear=False,
        )
        self.env_patcher.start()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def _post_webhook(self, headers: dict[str, str] | None = None) -> int:
        request = urllib_request.Request(
            f"{self.base_url}/webhooks/whatsapp",
            data=json.dumps({"entry": []}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib_error.HTTPError as exc:
            return exc.code

    def test_unsigned_webhook_is_rejected_when_no_app_secret_is_configured(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_APP_SECRET": ""}, clear=False):
            self.assertEqual(self._post_webhook(), 403)

    def test_webhook_with_bogus_signature_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "test-secret"}, clear=False):
            self.assertEqual(self._post_webhook({"X-Hub-Signature-256": "sha256=deadbeef"}), 403)


class WhatsAppSendResultTests(unittest.TestCase):
    """send_whatsapp_message must never invent a provider message id."""

    def _fake_response(self, payload: dict[str, object]):
        body = json.dumps(payload).encode("utf-8")

        class _Response(io.BytesIO):
            status = 200

            def __enter__(self_inner):  # noqa: N805 - context manager protocol
                return self_inner

            def __exit__(self_inner, *args):  # noqa: N805 - context manager protocol
                return False

        return _Response(body)

    def _send(self, payload: dict[str, object]) -> str:
        with mock.patch(
            "packages.infrastructure.whatsapp_messaging.urllib_request.urlopen",
            return_value=self._fake_response(payload),
        ):
            return send_whatsapp_message(
                access_token="token",
                phone_number_id="12345",
                recipient_wa_id="15551234567",
                message_text="hello",
                api_version="v21.0",
            )

    def test_returns_provider_message_id_on_success(self) -> None:
        self.assertEqual(self._send({"messages": [{"id": "wamid.real-1"}]}), "wamid.real-1")

    def test_raises_when_response_has_no_messages_array(self) -> None:
        with self.assertRaises(RuntimeError):
            self._send({"messaging_product": "whatsapp"})

    def test_raises_when_response_carries_an_error_object(self) -> None:
        with self.assertRaises(RuntimeError):
            self._send({"error": {"message": "Invalid parameter", "code": 100}})


class StaticFileExposureTests(unittest.TestCase):
    """The repository root must not be browsable over HTTP."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _status(self, path: str) -> int:
        try:
            with urllib_request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status
        except urllib_error.HTTPError as exc:
            return exc.code

    def test_private_paths_are_not_served(self) -> None:
        for path in (
            "/portal/portal.db",
            "/portal/portal-whatsapp/user-1.json",
            "/portal/billing.sample.json",
            "/scripts/run_portal_server.local.sh",
            "/scripts/run_portal_server.py",
            "/packages/infrastructure/portal_db.py",
            "/clients/Dor/client.yaml",
            "/AGENTS.md",
            "/requirements.txt",
            "/.git/config",
            "/render.yaml",
        ):
            with self.subTest(path=path):
                self.assertEqual(self._status(path), 404)

    def test_public_assets_are_still_served(self) -> None:
        for path in ("/", "/admin", "/portal/admin.js", "/portal/admin.css", "/privacy.html"):
            with self.subTest(path=path):
                self.assertEqual(self._status(path), 200)


class NotificationsApiTests(unittest.TestCase):
    """The in-app feed is the single delivery surface, so it must be scoped tightly."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.tokens: dict[str, str] = {}
        for email in ("owner@example.com", "other@example.com"):
            self.server.database.register_user(email)
            code, _ = self.server.store.issue_challenge(email)
            ok, _, result = self.server.store.verify_code(email, code)
            assert ok and result is not None
            self.tokens[email] = result["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _user_id(self, email: str) -> int:
        return int((self.server.database.get_user(email) or {})["id"])

    def _request(self, method: str, path: str, email: str, payload=None):
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.tokens[email]}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_feed_returns_only_the_callers_notifications(self) -> None:
        self.server.database.save_notification(
            user_id=self._user_id("owner@example.com"), title="Mine", body="visible"
        )
        self.server.database.save_notification(
            user_id=self._user_id("other@example.com"), title="Theirs", body="hidden"
        )

        status, payload = self._request("GET", "/api/notifications", "owner@example.com")

        self.assertEqual(status, 200)
        self.assertEqual([item["title"] for item in payload["notifications"]], ["Mine"])
        self.assertEqual(payload["unreadCount"], 1)

    def test_feed_requires_authentication(self) -> None:
        request = urllib_request.Request(f"{self.base_url}/api/notifications", method="GET")
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                status = response.status
        except urllib_error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 401)

    def test_marking_read_updates_the_unread_count(self) -> None:
        notification = self.server.database.save_notification(
            user_id=self._user_id("owner@example.com"), title="Mine"
        )

        status, payload = self._request(
            "POST", "/api/notifications/read", "owner@example.com", {"id": notification["id"]}
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["notification"]["read"])
        self.assertEqual(payload["unreadCount"], 0)

    def test_cannot_mark_another_users_notification_read(self) -> None:
        notification = self.server.database.save_notification(
            user_id=self._user_id("other@example.com"), title="Theirs"
        )

        status, payload = self._request(
            "POST", "/api/notifications/read", "owner@example.com", {"id": notification["id"]}
        )

        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])
        # And it is genuinely untouched.
        self.assertEqual(
            self.server.database.count_unread_notifications(user_id=self._user_id("other@example.com")),
            1,
        )

    def test_read_all_clears_only_the_callers_feed(self) -> None:
        owner_id = self._user_id("owner@example.com")
        other_id = self._user_id("other@example.com")
        for index in range(3):
            self.server.database.save_notification(user_id=owner_id, title=f"Mine {index}")
        self.server.database.save_notification(user_id=other_id, title="Theirs")

        status, payload = self._request("POST", "/api/notifications/read-all", "owner@example.com", {})

        self.assertEqual(status, 200)
        self.assertEqual(payload["updated"], 3)
        self.assertEqual(payload["unreadCount"], 0)
        self.assertEqual(self.server.database.count_unread_notifications(user_id=other_id), 1)

    def test_notifications_cannot_be_deleted(self) -> None:
        """The feed is a record: a notification is read or unread, never removed."""

        owner_id = self._user_id("owner@example.com")
        notification = self.server.database.save_notification(user_id=owner_id, title="Mine")

        request = urllib_request.Request(
            f"{self.base_url}/api/notifications/{notification['id']}",
            method="DELETE",
            headers={"Authorization": f"Bearer {self.tokens['owner@example.com']}"},
        )
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                status = response.status
        except urllib_error.HTTPError as exc:
            status = exc.code

        self.assertEqual(status, 404)
        self.assertEqual(len(self.server.database.list_notifications(user_id=owner_id)), 1)
        self.assertFalse(hasattr(self.server.database, "delete_notification"))

    def test_feed_returns_one_page_at_a_time(self) -> None:
        owner_id = self._user_id("owner@example.com")
        for index in range(25):
            self.server.database.save_notification(user_id=owner_id, title=f"Note {index:02d}")

        status, payload = self._request("GET", "/api/notifications", "owner@example.com")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["notifications"]), 20)
        self.assertTrue(payload["hasMore"])
        # Newest first, so the page starts at the last one written.
        self.assertEqual(payload["notifications"][0]["title"], "Note 24")
        self.assertEqual(payload["nextBeforeId"], payload["notifications"][-1]["id"])

    def test_paging_walks_back_through_the_whole_feed(self) -> None:
        owner_id = self._user_id("owner@example.com")
        for index in range(25):
            self.server.database.save_notification(user_id=owner_id, title=f"Note {index:02d}")

        _, first = self._request("GET", "/api/notifications", "owner@example.com")
        _, second = self._request(
            "GET", f"/api/notifications?beforeId={first['nextBeforeId']}", "owner@example.com"
        )

        self.assertEqual(len(second["notifications"]), 5)
        self.assertFalse(second["hasMore"])
        self.assertEqual(second["nextBeforeId"], 0)
        titles = [item["title"] for item in first["notifications"] + second["notifications"]]
        # Every notification is reachable, and none is served twice.
        self.assertEqual(len(set(titles)), 25)
        self.assertEqual(titles[-1], "Note 00")

    def test_search_matches_title_and_body_in_any_order(self) -> None:
        owner_id = self._user_id("owner@example.com")
        self.server.database.save_notification(
            user_id=owner_id, title="Meeting summary ready", body="No meetings found in this range."
        )
        self.server.database.save_notification(
            user_id=owner_id, title="Receipt bundle ready", body="Your receipts are ready to download."
        )

        _, payload = self._request(
            "GET", "/api/notifications?search=ready%20MEETING", "owner@example.com"
        )

        self.assertEqual([item["title"] for item in payload["notifications"]], ["Meeting summary ready"])
        self.assertEqual(payload["search"], "ready MEETING")

    def test_search_finds_a_body_only_match(self) -> None:
        owner_id = self._user_id("owner@example.com")
        self.server.database.save_notification(
            user_id=owner_id, title="Receipt bundle ready", body="Saved to Receipts/Jul2026."
        )

        _, payload = self._request("GET", "/api/notifications?search=jul2026", "owner@example.com")

        self.assertEqual([item["title"] for item in payload["notifications"]], ["Receipt bundle ready"])

    def test_search_stays_inside_the_callers_feed(self) -> None:
        self.server.database.save_notification(
            user_id=self._user_id("other@example.com"), title="Meeting summary ready"
        )

        _, payload = self._request("GET", "/api/notifications?search=meeting", "owner@example.com")

        self.assertEqual(payload["notifications"], [])

    def test_search_pages_like_the_feed(self) -> None:
        owner_id = self._user_id("owner@example.com")
        for index in range(22):
            self.server.database.save_notification(user_id=owner_id, title=f"Meeting {index:02d}")
        self.server.database.save_notification(user_id=owner_id, title="Receipt bundle ready")

        _, first = self._request("GET", "/api/notifications?search=meeting", "owner@example.com")
        _, second = self._request(
            "GET",
            f"/api/notifications?search=meeting&beforeId={first['nextBeforeId']}",
            "owner@example.com",
        )

        self.assertEqual(len(first["notifications"]), 20)
        self.assertTrue(first["hasMore"])
        self.assertEqual(len(second["notifications"]), 2)
        self.assertFalse(second["hasMore"])
        titles = [item["title"] for item in first["notifications"] + second["notifications"]]
        self.assertNotIn("Receipt bundle ready", titles)


class WhatsAppStatusWebhookTests(unittest.TestCase):
    """Meta's delivery statuses for what Assistyca sent: an owner alert, a scheduled message."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        # The Assistyca number is the only number anyone writes to, and the
        # only one statuses come back for.
        self.env_patcher = mock.patch.dict(os.environ, {"ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "12345"}, clear=False)
        self.env_patcher.start()
        # Webhook signature verification fails closed, so these routing tests would
        # otherwise all 403 for want of a WHATSAPP_APP_SECRET. What they exercise is
        # status routing, not authentication; the fail-closed behaviour has its own
        # tests in WhatsAppWebhookSignatureTests.
        self.signature_patcher = mock.patch(
            "packages.infrastructure.portal_auth.server.verify_whatsapp_signature",
            return_value=True,
        )
        self.signature_patcher.start()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.server.database.register_user("owner@example.com")
        self.server.database.save_whatsapp_connection(
            "owner@example.com",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.signature_patcher.stop()
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_whatsapp_status_webhook_marks_latest_owner_alert_delivered(self) -> None:
        self.server.database.update_whatsapp_connection_metadata(
            email="owner@example.com",
            metadata_updates={
                "lastOwnerNotificationStatus": "requested",
                "lastOwnerNotificationMessageId": "wamid.sample-1",
            },
        )

        request = urllib_request.Request(
            f"{self.base_url}/webhooks/whatsapp",
            data=json.dumps(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {
                                            "phone_number_id": "12345",
                                        },
                                        "statuses": [
                                            {
                                                "id": "wamid.sample-1",
                                                "status": "delivered",
                                                "recipient_id": "15551234567",
                                                "timestamp": "1720861200",
                                            }
                                        ],
                                    }
                                }
                            ]
                        }
                    ]
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
            },
        )

        with urllib_request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status

        self.assertEqual(status, 200)
        self.assertEqual(body["receivedStatuses"], 1)
        self.assertEqual(body["results"][0]["type"], "status")
        connection = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(connection)
        metadata = connection["metadata"]
        self.assertEqual(metadata["lastOwnerNotificationStatus"], "delivered")
        self.assertEqual(metadata["lastOwnerNotificationMessageId"], "wamid.sample-1")

    def test_whatsapp_status_webhook_records_platform_owner_alert_without_latest_id(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/webhooks/whatsapp",
            data=json.dumps(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {
                                            "phone_number_id": "12345",
                                        },
                                        "statuses": [
                                            {
                                                "id": "wamid.reengagement-owner-1",
                                                "status": "failed",
                                                "recipient_id": "15551234567",
                                                "timestamp": "1720861200",
                                                "errors": [
                                                    {
                                                        "code": 131047,
                                                        "title": "Re-engagement message",
                                                        "error_data": {
                                                            "details": "Message failed outside the customer service window.",
                                                        },
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                }
                            ]
                        }
                    ]
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
            },
        )

        with urllib_request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status

        self.assertEqual(status, 200)
        self.assertEqual(body["receivedStatuses"], 1)
        self.assertEqual(body["results"][0]["type"], "status_owner_alert")
        self.assertEqual(body["results"][0]["route"], "platform_owner_alert")
        self.assertEqual(body["results"][0]["status"], "failed")

        connection = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(connection)
        metadata = connection["metadata"]
        self.assertEqual(metadata["lastOwnerNotificationStatus"], "failed")
        self.assertEqual(metadata["lastOwnerNotificationMessageId"], "wamid.reengagement-owner-1")
        self.assertIn("131047", metadata["lastOwnerNotificationError"])

    def test_whatsapp_status_webhook_updates_scheduled_action(self) -> None:
        user = self.server.database.get_user("owner@example.com") or {}
        action = self.server.database.create_scheduled_action(
            user_id=int(user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "Track me"},
        )
        self.server.database.claim_scheduled_action(int(action["id"]))
        self.server.database.finish_scheduled_action(
            action_id=int(action["id"]),
            status="sent",
            provider_message_id="wamid.scheduled-webhook-1",
        )

        scheduled_request = urllib_request.Request(
            f"{self.base_url}/webhooks/whatsapp",
            data=json.dumps(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "12345"},
                                        "statuses": [
                                            {
                                                "id": "wamid.scheduled-webhook-1",
                                                "status": "failed",
                                                "recipient_id": "15551234567",
                                                "timestamp": "1720861200",
                                                "errors": [
                                                    {
                                                        "code": 131047,
                                                        "title": "Re-engagement message",
                                                        "error_data": {
                                                            "details": "Message failed outside the customer service window.",
                                                        },
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                }
                            ]
                        }
                    ]
                }
            ).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        with urllib_request.urlopen(scheduled_request, timeout=5) as response:
            scheduled_body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(scheduled_body["results"][0]["type"], "scheduled_action_status")
        saved_action = self.server.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved_action["status"], "failed")
        self.assertIn("131047", saved_action["lastError"])


if __name__ == "__main__":
    unittest.main()
