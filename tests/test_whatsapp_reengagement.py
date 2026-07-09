from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path

from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.whatsapp_reengagement import REENGAGEMENT_FEATURE_ID
from packages.infrastructure.whatsapp_reengagement import WhatsAppReengagementConfig
from packages.infrastructure.whatsapp_reengagement import WhatsAppReengagementScheduler


class WhatsAppReengagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(db_path)
        self.database.register_user("owner@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _connect_whatsapp(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
            metadata={
                "assistant": {
                    "tone_guidance": "Warm and practical.",
                    "business_notes": "Keep it concise and helpful.",
                }
            },
        )

    def test_save_whatsapp_message_tracks_conversation_history(self) -> None:
        self.database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="15550001111",
            direction="inbound",
            text="Hi, can you send me the quote again?",
            sender_name="Maya Cohen",
            sender_wa_id="15550001111",
            message_id="wamid.inbound-1",
            message_type="text",
            message_at="2026-01-01T10:00:00+00:00",
        )
        self.database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="15550001111",
            direction="outbound",
            text="Sure, I’ll send it over now.",
            sender_name="Maya Cohen",
            sender_wa_id="15550001111",
            message_id="wamid.outbound-1",
            message_type="text",
            message_at="2026-01-01T10:05:00+00:00",
        )

        conversation = self.database.get_whatsapp_conversation(
            "15550001111",
            email="owner@example.com",
        )
        messages = self.database.list_whatsapp_conversation_messages(
            "15550001111",
            email="owner@example.com",
        )

        self.assertIsNotNone(conversation)
        self.assertEqual(conversation["senderName"], "Maya Cohen")
        self.assertEqual(conversation["lastMessageDirection"], "outbound")
        self.assertEqual(conversation["lastMessageText"], "Sure, I’ll send it over now.")
        self.assertEqual(len(messages), 2)
        self.assertEqual([message["direction"] for message in messages], ["inbound", "outbound"])

    def test_scheduler_sends_one_reengagement_message_for_dormant_conversation(self) -> None:
        self._connect_whatsapp()
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=REENGAGEMENT_FEATURE_ID,
            feature_name="WhatsApp Re-engagement Assistant",
            is_active=True,
        )
        self.database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="15550001111",
            direction="inbound",
            text="Thanks, I’ll think about it and get back to you.",
            sender_name="Maya Cohen",
            sender_wa_id="15550001111",
            message_id="wamid.old-1",
            message_type="text",
            message_at="2025-12-01T09:00:00+00:00",
        )

        sent_messages: list[str] = []

        def fake_send_owner_message(connection: dict[str, object], message_text: str) -> str:
            sent_messages.append(message_text)
            self.assertEqual(connection["email"], "owner@example.com")
            return f"owner-{len(sent_messages)}"

        scheduler = WhatsAppReengagementScheduler(
            self.database,
            send_owner_message=fake_send_owner_message,
            config=WhatsAppReengagementConfig(
                enabled=True,
                timezone_name="UTC",
                schedule_weekday=6,
                schedule_hour=9,
                schedule_minute=0,
                inactivity_months=6,
                poll_seconds=60,
                model="gpt-5.5",
            ),
        )

        summary = scheduler.run_pending(now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(summary["ran"])
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("This client wasn't reached in a long time", sent_messages[0])
        self.assertIn("Maya Cohen", sent_messages[0])

        conversation = self.database.get_whatsapp_conversation(
            "15550001111",
            email="owner@example.com",
        )
        self.assertTrue(conversation["lastReengagementNotifiedAt"])
        self.assertEqual(
            conversation["lastReengagementNotifiedForMessageAt"],
            "2025-12-01T09:00:00+00:00",
        )

        second_summary = scheduler.run_pending(now=datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc))
        self.assertFalse(second_summary["ran"])
        self.assertEqual(len(sent_messages), 1)


if __name__ == "__main__":
    unittest.main()
