from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_db import PortalDatabase
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID
from packages.tools.scheduled_monitor.monitor import ScheduledMonitorConfig
from packages.tools.scheduled_monitor.monitor import ScheduledMonitorScheduler


class ScheduledMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(db_path)
        self.database.register_user("owner@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _configure_monitor(self) -> None:
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "searchPrompt": "Criminal defense law conferences and nearby holiday reminders",
                    "cadence": "daily",
                    "timeOfDay": "09:00",
                    "timezone": "UTC",
                    "deliveryChannel": "email",
                    "emailAddress": "owner@example.com",
                }
            },
        )
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=MONITOR_FEATURE_ID,
            feature_name="Scheduled Web Monitor",
            is_active=True,
        )

    def test_scheduler_dedupes_runs_and_notifications(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(**kwargs) -> None:
            delivered_messages.append(
                {
                    "to": str(kwargs.get("to_email") or ""),
                    "subject": str(kwargs.get("subject") or ""),
                    "text": str(kwargs.get("text_body") or ""),
                }
            )

        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "summary": "Found one relevant update.",
                    "items": [
                        {
                            "id": "event-123",
                            "title": "Criminal Defense Summit 2026 registration opened",
                            "summary": "Registration is now open for the annual summit.",
                            "why_it_matters": "The client asked for relevant conference opportunities.",
                            "event_date": "2026-09-18",
                            "source_name": "Bar Association",
                            "source_url": "https://example.com/events/summit",
                            "urgency": "medium",
                        }
                    ],
                }
            ),
            request_id="req_123",
            response_id="resp_123",
            model="gpt-5.5",
        )

        scheduler = ScheduledMonitorScheduler(
            self.database,
            config=ScheduledMonitorConfig(
                enabled=True,
                poll_seconds=60,
                model="gpt-5.5",
                search_context_size="medium",
                max_output_tokens=1200,
                max_items_per_run=5,
            ),
        )

        with mock.patch.dict(
            os.environ,
            {
                "PORTAL_SMTP_HOST": "smtp.example.com",
                "PORTAL_SMTP_FROM_EMAIL": "alerts@example.com",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            return_value=fake_response,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            first_summary = scheduler.run_pending(now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
            second_summary = scheduler.run_pending(now=datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc))
            third_summary = scheduler.run_pending(now=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(first_summary["ran"])
        self.assertEqual(first_summary["targets"], 1)
        self.assertEqual(first_summary["runs"][0]["status"], "completed")
        self.assertEqual(first_summary["runs"][0]["notificationsSent"], 1)
        self.assertEqual(len(delivered_messages), 1)
        self.assertEqual(delivered_messages[0]["to"], "owner@example.com")
        self.assertIn("Criminal Defense Summit 2026 registration opened", delivered_messages[0]["text"])

        self.assertFalse(second_summary["ran"])
        self.assertEqual(second_summary["runs"][0]["reason"], "already_ran")
        self.assertEqual(len(delivered_messages), 1)

        self.assertTrue(third_summary["ran"])
        self.assertEqual(third_summary["runs"][0]["status"], "duplicate_matches")
        self.assertEqual(third_summary["runs"][0]["notificationsSent"], 0)
        self.assertEqual(len(delivered_messages), 1)

        first_run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-10T09:00:00+00:00",
        )
        second_run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-11T09:00:00+00:00",
        )
        notification = self.database.get_feature_monitor_notification(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            item_key="event-123",
        )

        self.assertIsNotNone(first_run)
        self.assertEqual(first_run["notificationsSent"], 1)
        self.assertIsNotNone(second_run)
        self.assertEqual(second_run["status"], "duplicate_matches")
        self.assertIsNotNone(notification)
        self.assertEqual(notification["deliveryTarget"], "owner@example.com")


if __name__ == "__main__":
    unittest.main()
