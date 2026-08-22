from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.notification_delivery import send_whatsapp_notification
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler


class ScheduledActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_claim_scheduled_action_is_atomic(self) -> None:
        action = self.database.create_scheduled_action(
            user_id=int(self.user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "It's 12:40."},
        )

        claimed = self.database.claim_scheduled_action(int(action["id"]))
        second_claim = self.database.claim_scheduled_action(int(action["id"]))

        self.assertIsNotNone(claimed)
        self.assertIsNone(second_claim)
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attemptCount"], 1)

    def test_scheduler_sends_due_whatsapp_template_with_platform_credentials(self) -> None:
        action = self.database.create_scheduled_action(
            user_id=int(self.user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name="Asia/Jerusalem",
            payload={
                "messageText": "It's 12:40.",
                "recipientWaId": "972507322341",
            },
        )
        scheduler = ScheduledActionScheduler(
            self.database,
            config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
        )

        with mock.patch(
            "packages.infrastructure.scheduled_actions.send_whatsapp_notification",
            return_value="wamid.test",
        ) as send_whatsapp:
            summary = scheduler.run_pending(now=datetime.now(timezone.utc))

        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(saved["status"], "sent")
        self.assertEqual(saved["providerMessageId"], "wamid.test")
        send_whatsapp.assert_called_once_with(
            recipient_wa_id="972507322341",
            message_text="It's 12:40.",
            template_name="notification_message",
            template_language="en_US",
        )

    def test_whatsapp_template_notification_uses_platform_environment(self) -> None:
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
                    "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "platform-phone",
                },
                clear=True,
            ),
            mock.patch(
                "packages.infrastructure.notification_delivery.send_whatsapp_message",
                return_value="wamid.template",
            ) as send_message,
        ):
            result = send_whatsapp_notification(
                recipient_wa_id="972507322341",
                message_text="It's 12:40.",
                template_name="notification_message",
                template_language="en_US",
            )

        self.assertEqual(result, "wamid.template")
        send_message.assert_called_once_with(
            access_token="platform-token",
            phone_number_id="platform-phone",
            api_version="v20.0",
            recipient_wa_id="972507322341",
            message_text=None,
            template={
                "name": "notification_message",
                "language": {"code": "en_US"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {
                                "type": "text",
                                "text": "It's 12:40.",
                            }
                        ],
                    }
                ],
            },
        )

    def test_delivery_status_updates_saved_action_and_does_not_regress(self) -> None:
        action = self.database.create_scheduled_action(
            user_id=int(self.user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "Status check"},
        )
        self.database.claim_scheduled_action(int(action["id"]))
        self.database.finish_scheduled_action(
            action_id=int(action["id"]),
            status="sent",
            provider_message_id="wamid.scheduled-status-1",
        )

        delivered = self.database.update_scheduled_action_delivery_status(
            provider_message_id="wamid.scheduled-status-1",
            status="delivered",
            event_at="2026-08-21T11:00:00+00:00",
        )
        regressed = self.database.update_scheduled_action_delivery_status(
            provider_message_id="wamid.scheduled-status-1",
            status="sent",
            event_at="2026-08-21T10:59:00+00:00",
        )

        self.assertIsNotNone(delivered)
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(delivered["payload"]["deliveryStatus"], "delivered")
        self.assertEqual(regressed["status"], "delivered")

    def test_delivery_failure_keeps_provider_error_for_action_details(self) -> None:
        action = self.database.create_scheduled_action(
            user_id=int(self.user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "Failure check"},
        )
        self.database.claim_scheduled_action(int(action["id"]))
        self.database.finish_scheduled_action(
            action_id=int(action["id"]),
            status="sent",
            provider_message_id="wamid.scheduled-failure-1",
        )

        failed = self.database.update_scheduled_action_delivery_status(
            provider_message_id="wamid.scheduled-failure-1",
            status="failed",
            last_error="131047 Message failed outside the customer service window.",
        )

        self.assertIsNotNone(failed)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("131047", failed["lastError"])
        self.assertEqual(failed["payload"]["deliveryStatus"], "failed")


class ScheduledActionApiTests(unittest.TestCase):
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
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, error, result = self.server.store.verify_code("owner@example.com", code)
        self.assertTrue(ok, error)
        self.session_token = str((result or {}).get("token") or "")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_action_history_requires_authentication(self) -> None:
        request = urllib_request.Request(f"{self.base_url}/api/scheduled-actions", method="GET")
        with self.assertRaises(urllib_error.HTTPError) as raised:
            urllib_request.urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 401)

    def test_action_creation_uses_platform_credentials_without_workspace_token(self) -> None:
        self.server.database.save_whatsapp_connection(
            "owner@example.com",
            owner_wa_id="972507322341",
            connection_status="connected",
        )
        request = urllib_request.Request(
            f"{self.base_url}/api/scheduled-actions",
            data=json.dumps(
                {
                    "actionType": "send_message",
                    "channel": "whatsapp",
                    "recipientRef": "owner",
                    "runAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "timezone": "Asia/Jerusalem",
                    "messageText": "Server-owned credentials",
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )

        with (
            mock.patch.dict(
                "os.environ",
                {
                    "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
                    "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "platform-phone",
                },
                clear=False,
            ),
            urllib_request.urlopen(request, timeout=5) as response,
        ):
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"]["payload"]["messageText"], "Server-owned credentials")
        stored = self.server.database.get_scheduled_action(int(payload["action"]["id"])) or {}
        self.assertEqual(stored["payload"]["recipientWaId"], "972507322341")
        self.assertNotIn("recipientWaId", payload["action"]["payload"])

    def test_active_action_can_be_cancelled_from_api(self) -> None:
        user = self.server.database.get_user("owner@example.com") or {}
        action = self.server.database.create_scheduled_action(
            user_id=int(user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "Visible", "recipientWaId": "972500000000"},
        )

        request = urllib_request.Request(
            f"{self.base_url}/api/scheduled-actions/{action['id']}",
            method="DELETE",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"]["status"], "cancelled")
        self.assertEqual(payload["action"]["lastError"], "Cancelled from the Actions panel.")
        self.assertNotIn("recipientWaId", payload["action"]["payload"])
        stored = self.server.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(stored["status"], "cancelled")
        self.assertEqual(stored["payload"]["recipientWaId"], "972500000000")

    def test_completed_action_cannot_be_cancelled_from_api(self) -> None:
        user = self.server.database.get_user("owner@example.com") or {}
        action = self.server.database.create_scheduled_action(
            user_id=int(user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "Done"},
        )
        self.server.database.finish_scheduled_action(
            action_id=int(action["id"]),
            status="sent",
            provider_message_id="wamid.done",
        )

        request = urllib_request.Request(
            f"{self.base_url}/api/scheduled-actions/{action['id']}",
            method="DELETE",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with self.assertRaises(urllib_error.HTTPError) as raised:
            urllib_request.urlopen(request, timeout=5)

        self.assertEqual(raised.exception.code, 409)
        payload = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "scheduled_action_not_active")

    def test_action_history_returns_only_signed_in_users_actions(self) -> None:
        user = self.server.database.get_user("owner@example.com") or {}
        other_user = self.server.database.register_user("other@example.com")
        expected = self.server.database.create_scheduled_action(
            user_id=int(user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "Visible", "recipientWaId": "972500000000"},
        )
        self.server.database.create_scheduled_action(
            user_id=int(other_user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            timezone_name="UTC",
            payload={"messageText": "Hidden"},
        )

        request = urllib_request.Request(
            f"{self.base_url}/api/scheduled-actions?limit=25",
            method="GET",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual([action["id"] for action in payload["actions"]], [expected["id"]])
        self.assertEqual(payload["actions"][0]["payload"]["messageText"], "Visible")
        self.assertNotIn("recipientWaId", payload["actions"][0]["payload"])


if __name__ == "__main__":
    unittest.main()
