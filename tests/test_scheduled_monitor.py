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
                    "watchItems": [
                        "Criminal defense law conferences",
                        "Nearby holiday reminders",
                    ],
                    "intervalDays": 1,
                    "deliveryChannel": "email",
                }
            },
        )
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=MONITOR_FEATURE_ID,
            feature_name="Scheduled Web Monitor",
            is_active=True,
            activated_at="2026-07-09T09:00:00+00:00",
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
        self.assertEqual(second_summary["runs"][0]["reason"], "not_due")
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

    def test_manual_run_uses_same_pipeline_without_shifting_due_schedule(self) -> None:
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "watchItems": [
                        "Criminal defense law conferences",
                    ],
                    "intervalDays": 7,
                    "deliveryChannel": "email",
                }
            },
        )
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=MONITOR_FEATURE_ID,
            feature_name="Scheduled Web Monitor",
            is_active=True,
            activated_at="2026-07-01T09:00:00+00:00",
        )
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
            manual_result = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc))
            self.assertIsNone(self.database.get_latest_feature_monitor_run(user_id=1, feature_id=MONITOR_FEATURE_ID))
            first_scheduled_summary = scheduler.run_pending(now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(manual_result["ok"])
        self.assertEqual(manual_result["run"]["status"], "completed")
        self.assertEqual(manual_result["run"]["notificationsSent"], 1)
        self.assertEqual(len(delivered_messages), 1)

        self.assertTrue(first_scheduled_summary["ran"])
        self.assertEqual(first_scheduled_summary["runs"][0]["status"], "duplicate_matches")
        self.assertEqual(first_scheduled_summary["runs"][0]["scheduledFor"], "2026-07-08T09:00:00+00:00")
        self.assertEqual(len(delivered_messages), 1)

        scheduled_run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-08T09:00:00+00:00",
        )

        self.assertIsNotNone(scheduled_run)
        self.assertEqual(scheduled_run["status"], "duplicate_matches")


if __name__ == "__main__":
    unittest.main()
