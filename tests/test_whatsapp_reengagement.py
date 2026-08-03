from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
            access_token="test-token",
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

    def test_update_whatsapp_connection_metadata_merges_new_health_fields(self) -> None:
        self._connect_whatsapp()

        updated = self.database.update_whatsapp_connection_metadata(
            email="owner@example.com",
            metadata_updates={
                "lastInboundAt": "2026-07-13T09:15:00+00:00",
                "lastOwnerNotificationStatus": "sent",
            },
        )

        self.assertIsNotNone(updated)
        metadata = updated["metadata"]
        self.assertEqual(metadata["assistant"]["tone_guidance"], "Warm and practical.")
        self.assertEqual(metadata["lastInboundAt"], "2026-07-13T09:15:00+00:00")
        self.assertEqual(metadata["lastOwnerNotificationStatus"], "sent")

    def test_scheduler_sends_one_reengagement_message_for_dormant_conversation(self) -> None:
        self._connect_whatsapp()
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            REENGAGEMENT_FEATURE_ID,
            metadata={
                "settings": {
                    "model": "gpt-5.4",
                }
            },
        )
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

        fake_response = SimpleNamespace(
            output_text="Hi Maya, just checking in in case you still need help with this.",
            request_id="req_123",
            response_id="resp_123",
            model="gpt-5.4",
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_reengagement.call_openai_response",
            return_value=fake_response,
        ) as mock_openai_response:
            summary = scheduler.run_pending(now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(summary["ran"])
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("just checking in", sent_messages[0])
        self.assertIn("Maya Cohen", sent_messages[0])
        self.assertEqual(mock_openai_response.call_args.kwargs["model"], "gpt-5.4")

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

    def test_scheduler_includes_manual_import_without_sender_wa_id(self) -> None:
        self._connect_whatsapp()
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=REENGAGEMENT_FEATURE_ID,
            feature_name="WhatsApp Re-engagement Assistant",
            is_active=True,
        )
        self.database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="manual-maya-cohen",
            direction="outbound",
            text="Sure, I will send the quote today.",
            sender_name="Maya Cohen",
            sender_wa_id="",
            message_id="manual-import-old-1",
            message_type="text",
            message_at="2025-12-01T09:05:00+00:00",
            metadata={"source": "manual_import"},
        )

        sent_messages: list[str] = []

        scheduler = WhatsAppReengagementScheduler(
            self.database,
            send_owner_message=lambda _connection, message_text: sent_messages.append(message_text) or "owner-1",
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

        with mock.patch(
            "packages.infrastructure.whatsapp_reengagement.call_openai_response",
            side_effect=RuntimeError("offline"),
        ):
            summary = scheduler.run_pending(now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(summary["ran"])
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Maya Cohen", sent_messages[0])

    def test_scheduler_uses_saved_inactivity_and_latest_100_messages(self) -> None:
        self._connect_whatsapp()
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            REENGAGEMENT_FEATURE_ID,
            metadata={
                "settings": {
                    "model": "gpt-5.4",
                    "intervalDays": 1,
                    "scheduleTimeLocal": "12:00",
                    "scheduleTimezone": "UTC",
                    "inactivityValue": 5,
                    "inactivityUnit": "minutes",
                    "maxContextMessages": 100,
                }
            },
        )
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=REENGAGEMENT_FEATURE_ID,
            feature_name="WhatsApp Re-engagement Assistant",
            is_active=True,
        )
        first_message_at = datetime(2026, 7, 13, 10, 6, tzinfo=timezone.utc)
        for index in range(105):
            self.database.save_whatsapp_message(
                email="owner@example.com",
                conversation_id="15550002222",
                direction="inbound" if index % 2 == 0 else "outbound",
                text=f"message-{index + 1:03d}",
                sender_name="Maya Cohen",
                sender_wa_id="15550002222",
                message_id=f"wamid.context-{index + 1}",
                message_type="text",
                message_at=(first_message_at + timedelta(minutes=index)).isoformat(),
            )

        sent_messages: list[str] = []
        fake_response = SimpleNamespace(
            output_text="Hi Maya, just checking in on this.",
            request_id="req_context",
            response_id="resp_context",
            model="gpt-5.4",
        )

        scheduler = WhatsAppReengagementScheduler(
            self.database,
            send_owner_message=lambda _connection, message_text: sent_messages.append(message_text) or "owner-context",
            config=WhatsAppReengagementConfig(
                enabled=True,
                timezone_name="UTC",
                schedule_weekday=6,
                schedule_hour=9,
                schedule_minute=0,
                inactivity_months=6,
                poll_seconds=60,
                model="gpt-5.5",
                max_context_messages=100,
            ),
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_reengagement.call_openai_response",
            return_value=fake_response,
        ) as mock_openai_response:
            summary = scheduler.run_pending(now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(summary["ran"])
        self.assertEqual(len(sent_messages), 1)
        prompt = mock_openai_response.call_args.kwargs["prompt"]
        self.assertNotIn("message-001", prompt)
        self.assertIn("message-006", prompt)
        self.assertIn("message-105", prompt)

    def test_demo_run_drafts_without_sending_or_marking_notified(self) -> None:
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            REENGAGEMENT_FEATURE_ID,
            metadata={
                "settings": {
                    "model": "gpt-5.4",
                    "inactivityValue": 1,
                    "inactivityUnit": "months",
                }
            },
        )
        self.database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="15550003333",
            direction="inbound",
            text="Can you remind me what we discussed about pricing?",
            sender_name="Dani Levi",
            sender_wa_id="15550003333",
            message_id="wamid.demo-old-1",
            message_type="text",
            message_at="2026-05-01T09:00:00+00:00",
        )

        fake_response = SimpleNamespace(
            output_text="Hi Dani, just checking in in case the pricing question is still relevant.",
            request_id="req_demo",
            response_id="resp_demo",
            model="gpt-5.4",
        )
        scheduler = WhatsAppReengagementScheduler(
            self.database,
            send_owner_message=lambda _connection, _message_text: (_ for _ in ()).throw(AssertionError("demo sent")),
            config=WhatsAppReengagementConfig(
                enabled=True,
                timezone_name="UTC",
                poll_seconds=60,
                model="gpt-5.5",
            ),
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_reengagement.call_openai_response",
            return_value=fake_response,
        ):
            result = scheduler.run_demo_for_email(
                "owner@example.com",
                now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["demo"])
        candidates = result["run"]["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["senderName"], "Dani Levi")
        self.assertIn("pricing question", candidates[0]["draftText"])

        conversation = self.database.get_whatsapp_conversation(
            "15550003333",
            email="owner@example.com",
        )
        self.assertFalse(conversation["lastReengagementNotifiedAt"])
        self.assertIsNone(
            self.database.get_latest_whatsapp_reengagement_run(
                user_id=int(conversation["userId"]),
                feature_id=REENGAGEMENT_FEATURE_ID,
            )
        )


if __name__ == "__main__":
    unittest.main()
