from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from unittest import mock

from packages.infrastructure.portal_db import PortalDatabase
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

    def test_scheduler_sends_due_whatsapp_message_with_saved_connection(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            phone_number_id="phone-123",
            access_token="token-123",
            owner_wa_id="972507322341",
            connection_status="connected",
        )
        action = self.database.create_scheduled_action(
            user_id=int(self.user["id"]),
            action_type="send_message",
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name="Asia/Jerusalem",
            payload={"messageText": "It's 12:40."},
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
            phone_number_id="phone-123",
            access_token="token-123",
            recipient_wa_id="972507322341",
            message_text="It's 12:40.",
        )


if __name__ == "__main__":
    unittest.main()
