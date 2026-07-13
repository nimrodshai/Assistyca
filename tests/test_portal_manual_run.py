from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID


WHATSAPP_REPLY_ASSISTANT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"


class PortalManualRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
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


class PortalWhatsAppSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
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
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
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
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib_error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def test_feature_sample_endpoint_sends_owner_alert_and_updates_health_metadata(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_ACCESS_TOKEN": "test-token"}, clear=False):
            with mock.patch(
                "packages.infrastructure.portal_auth.server.PortalWhatsAppService.send_sample_owner_message",
                return_value=("wamid.sample-1", "Sample reply alert from Assistyca"),
            ):
                status, body = self._request(
                    "POST",
                    f"/api/features/{WHATSAPP_REPLY_ASSISTANT_FEATURE_ID}/sample",
                    {},
                )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["ownerMessageId"], "wamid.sample-1")
        self.assertEqual(body["connection"]["metadata"]["lastOwnerNotificationStatus"], "requested")
        self.assertEqual(body["connection"]["metadata"]["lastOwnerNotificationMessageId"], "wamid.sample-1")
        self.assertIn("confirms delivery", str(body["message"]).lower())

    def test_feature_sample_endpoint_requires_live_send_configuration(self) -> None:
        status, body = self._request(
            "POST",
            f"/api/features/{WHATSAPP_REPLY_ASSISTANT_FEATURE_ID}/sample",
            {},
        )

        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "setup_required")
        self.assertIn("working backend access token", str(body["message"]).lower())

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


if __name__ == "__main__":
    unittest.main()
