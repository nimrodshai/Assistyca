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
from packages.tools.scheduled_monitor.monitor import resolve_next_monitor_slot


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
                    "model": "gpt-5.4",
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
                "OPENAI_API_KEY": "test-key",
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
        self.assertEqual(len(delivered_messages), 2)
        self.assertEqual(delivered_messages[0]["to"], "owner@example.com")
        self.assertEqual(delivered_messages[0]["subject"], "Quick monitor update: 1 new match")
        self.assertIn("Criminal Defense Summit 2026 registration opened", delivered_messages[0]["text"])

        self.assertFalse(second_summary["ran"])
        self.assertEqual(second_summary["runs"][0]["reason"], "not_due")
        self.assertEqual(len(delivered_messages), 2)

        self.assertTrue(third_summary["ran"])
        self.assertEqual(third_summary["runs"][0]["status"], "duplicate_matches")
        self.assertEqual(third_summary["runs"][0]["notificationsSent"], 0)
        self.assertEqual(len(delivered_messages), 2)
        self.assertEqual(delivered_messages[1]["subject"], "Quick monitor update: nothing new yet")
        self.assertIn("Nothing new to send right now.", delivered_messages[1]["text"])
        self.assertIn("I already shared the useful matches earlier.", delivered_messages[1]["text"])

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
        self.assertTrue(second_run["metadata"]["noResultsNotificationSent"])
        self.assertIsNotNone(notification)
        self.assertEqual(notification["deliveryTarget"], "owner@example.com")

    def test_manual_run_uses_same_pipeline_without_shifting_due_schedule(self) -> None:
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "model": "gpt-5.4-nano",
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
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            return_value=fake_response,
        ) as mock_openai_response, mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            manual_result = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc))
            self.assertIsNone(self.database.get_latest_feature_monitor_run(user_id=1, feature_id=MONITOR_FEATURE_ID))
            first_scheduled_summary = scheduler.run_pending(now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(manual_result["ok"])
        self.assertEqual(manual_result["run"]["status"], "completed")
        self.assertEqual(manual_result["run"]["notificationsSent"], 1)
        self.assertEqual(len(delivered_messages), 2)
        self.assertEqual(delivered_messages[0]["subject"], "Quick monitor update: 1 new match")
        self.assertIn("Criminal Defense Summit 2026 registration opened", delivered_messages[0]["text"])
        self.assertEqual(mock_openai_response.call_args.kwargs["model"], "gpt-5.4-nano")
        self.assertEqual(mock_openai_response.call_args.kwargs["temperature"], 0)

        self.assertTrue(first_scheduled_summary["ran"])
        self.assertEqual(first_scheduled_summary["runs"][0]["status"], "duplicate_matches")
        self.assertEqual(first_scheduled_summary["runs"][0]["scheduledFor"], "2026-07-08T09:00:00+00:00")
        self.assertEqual(len(delivered_messages), 2)
        self.assertEqual(delivered_messages[1]["subject"], "Quick monitor update: nothing new yet")
        self.assertIn("Nothing new to send right now.", delivered_messages[1]["text"])

        scheduled_run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-08T09:00:00+00:00",
        )

        self.assertIsNotNone(scheduled_run)
        self.assertEqual(scheduled_run["status"], "duplicate_matches")
        self.assertTrue(scheduled_run["metadata"]["noResultsNotificationSent"])

    def test_saved_settings_timestamp_resets_next_scheduled_run(self) -> None:
        next_slot = resolve_next_monitor_slot(
            now=datetime(2026, 7, 6, 9, 30, tzinfo=timezone.utc),
            settings={"intervalDays": 3},
            activated_at="2026-07-01T09:00:00+00:00",
            settings_saved_at="2026-07-03T10:00:00+00:00",
            last_scheduled_for="",
        )

        self.assertEqual(next_slot.isoformat(), "2026-07-06T10:00:00+00:00")

    def test_saved_schedule_time_uses_selected_local_time(self) -> None:
        next_slot = resolve_next_monitor_slot(
            now=datetime(2026, 7, 6, 5, 30, tzinfo=timezone.utc),
            settings={
                "intervalDays": 3,
                "scheduleTimeLocal": "09:15",
                "scheduleTimezone": "Asia/Jerusalem",
            },
            activated_at="2026-07-01T09:00:00+00:00",
            settings_saved_at="2026-07-03T10:00:00+00:00",
            last_scheduled_for="",
        )

        self.assertEqual(next_slot.isoformat(), "2026-07-06T06:15:00+00:00")

    def test_selected_schedule_time_stays_on_same_local_hour_across_dst(self) -> None:
        next_slot = resolve_next_monitor_slot(
            now=datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc),
            settings={
                "intervalDays": 1,
                "scheduleTimeLocal": "09:00",
                "scheduleTimezone": "America/New_York",
            },
            activated_at="2026-03-07T14:00:00+00:00",
            settings_saved_at="",
            last_scheduled_for="2026-03-08T13:00:00+00:00",
        )

        self.assertEqual(next_slot.isoformat(), "2026-03-10T13:00:00+00:00")

    def test_monitor_run_claim_prevents_duplicate_scheduled_slots(self) -> None:
        first_claim = self.database.claim_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-10T09:00:00+00:00",
            metadata={"claimedBy": "first"},
        )
        second_claim = self.database.claim_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-10T09:00:00+00:00",
            metadata={"claimedBy": "second"},
        )

        self.assertIsNotNone(first_claim)
        self.assertEqual(first_claim["status"], "running")
        self.assertIsNone(second_claim)

    def test_scheduler_sends_no_results_update_when_nothing_new_is_found(self) -> None:
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
                    "summary": "No relevant updates were found.",
                    "items": [],
                }
            ),
            request_id="req_empty",
            response_id="resp_empty",
            model="gpt-5.4",
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
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            return_value=fake_response,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            summary = scheduler.run_pending(now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(summary["ran"])
        self.assertEqual(summary["runs"][0]["status"], "no_matches")
        self.assertEqual(summary["runs"][0]["notificationsSent"], 0)
        self.assertEqual(len(delivered_messages), 1)
        self.assertEqual(delivered_messages[0]["to"], "owner@example.com")
        self.assertEqual(delivered_messages[0]["subject"], "Quick monitor update: nothing new yet")
        self.assertIn("Here's what I checked:", delivered_messages[0]["text"])
        self.assertIn("Criminal defense law conferences", delivered_messages[0]["text"])
        self.assertIn("Nothing new worth sending right now.", delivered_messages[0]["text"])

        run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-10T09:00:00+00:00",
        )
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "no_matches")
        self.assertTrue(run["metadata"]["noResultsNotificationSent"])

    def test_manual_rerun_marks_empty_search_as_inconsistent_when_recent_results_exist(self) -> None:
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

        first_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "summary": "Found relevant updates.",
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
            request_id="req_first",
            response_id="resp_first",
            model="gpt-5.5",
        )
        second_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "summary": "No relevant updates were found.",
                    "items": [],
                }
            ),
            request_id="req_second",
            response_id="resp_second",
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
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            side_effect=[first_response, second_response],
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            first_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
            second_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc))

        self.assertTrue(first_run["ok"])
        self.assertEqual(first_run["run"]["status"], "completed")
        self.assertTrue(second_run["ok"])
        self.assertEqual(second_run["run"]["status"], "inconsistent_results")
        self.assertEqual(second_run["run"]["notificationsSent"], 0)
        self.assertEqual(len(delivered_messages), 1)
        self.assertFalse(second_run["run"]["run"]["metadata"]["noResultsNotificationSent"])
        self.assertEqual(second_run["run"]["run"]["metadata"]["recentResultsCount"], 1)
        self.assertEqual(second_run["run"]["run"]["metadata"]["recentResultsMinutesAgo"], 30)
        self.assertEqual(second_run["run"]["run"]["metadata"]["liveSearchStatus"], "no_matches")

    def test_manual_rerun_keeps_duplicate_matches_status_when_live_search_repeats_results(self) -> None:
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

        repeated_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "summary": "Found relevant updates.",
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
            request_id="req_repeat",
            response_id="resp_repeat",
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
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            side_effect=[repeated_response, repeated_response],
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            first_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
            second_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc))

        self.assertTrue(first_run["ok"])
        self.assertEqual(first_run["run"]["status"], "completed")
        self.assertTrue(second_run["ok"])
        self.assertEqual(second_run["run"]["status"], "duplicate_matches")
        self.assertEqual(second_run["run"]["notificationsSent"], 0)
        self.assertEqual(len(delivered_messages), 2)
        self.assertEqual(delivered_messages[1]["subject"], "Quick monitor update: nothing new yet")
        self.assertIn("Nothing new to send right now.", delivered_messages[1]["text"])
        self.assertTrue(second_run["run"]["run"]["metadata"]["noResultsNotificationSent"])
        self.assertEqual(second_run["run"]["run"]["metadata"]["liveSearchStatus"], "duplicate_matches")

    def test_manual_run_cancellation_skips_delivery(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []
        cancellation_requested = False

        def fake_send_email_notification(**kwargs) -> None:
            delivered_messages.append(
                {
                    "to": str(kwargs.get("to_email") or ""),
                    "subject": str(kwargs.get("subject") or ""),
                    "text": str(kwargs.get("text_body") or ""),
                }
            )

        def fake_openai_response(**kwargs) -> SimpleNamespace:
            nonlocal cancellation_requested
            cancellation_requested = True
            return SimpleNamespace(
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
                request_id="req_cancelled",
                response_id="resp_cancelled",
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
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            side_effect=fake_openai_response,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            result = scheduler.run_for_email(
                "owner@example.com",
                now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
                cancel_check=lambda: cancellation_requested,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["run"]["status"], "cancelled")
        self.assertEqual(result["run"]["notificationsSent"], 0)
        self.assertEqual(result["run"]["findingsCount"], 1)
        self.assertEqual(delivered_messages, [])
        self.assertTrue(result["run"]["run"]["metadata"]["cancelled"])
        self.assertIsNone(self.database.get_latest_feature_monitor_run(user_id=1, feature_id=MONITOR_FEATURE_ID))

    def test_manual_run_uses_saved_business_profile_and_renders_editor_button(self) -> None:
        self._configure_monitor()
        self.database.update_user_profile(
            "owner@example.com",
            profile={
                "businessSummary": "Boutique AI lab that submits papers and sends speakers to industry events.",
                "customerNotes": "Research leads and developer advocates.",
                "assistantGuidance": "Prioritize paper deadlines, CFPs, and travel planning dates.",
            },
        )
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(**kwargs) -> None:
            delivered_messages.append(
                {
                    "to": str(kwargs.get("to_email") or ""),
                    "subject": str(kwargs.get("subject") or ""),
                    "text": str(kwargs.get("text_body") or ""),
                    "html": str(kwargs.get("html_body") or ""),
                }
            )

        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "summary": "Found one relevant update.",
                    "items": [
                        {
                            "id": "event-123",
                            "title": "SEDE 2026 paper submission deadline is July 15, 2026",
                            "summary": "The CFP lists July 15, 2026 as the paper submission deadline.",
                            "why_it_matters": "Your team submits papers and needs lead time for review and travel coordination.",
                            "matched_watch_item": "paper deadlines",
                            "event_date": "2026-07-15",
                            "source_name": "ISCA",
                            "source_url": "https://www.isca-hq.org/SEDE/CFP.html",
                            "urgency": "high",
                        }
                    ],
                }
            ),
            request_id="req_profile",
            response_id="resp_profile",
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
                "PUBLIC_BASE_URL": "https://portal.example.com",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            return_value=fake_response,
        ) as mock_openai_response, mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            result = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(result["ok"])
        prompt = mock_openai_response.call_args.kwargs["prompt"]
        self.assertIn("About the client or business: Boutique AI lab that submits papers and sends speakers to industry events.", prompt)
        self.assertIn("Typical customers and requests: Research leads and developer advocates.", prompt)
        self.assertIn("Always keep in mind: Prioritize paper deadlines, CFPs, and travel planning dates.", prompt)
        self.assertIn('"matched_watch_item": "the exact saved watch-list entry this result best matches"', prompt)
        self.assertEqual(delivered_messages[0]["to"], "owner@example.com")
        self.assertIn("Open tool editor", delivered_messages[0]["html"])
        self.assertIn(
            "https://portal.example.com/portal/#features/scheduled-web-monitor-notifier/editor",
            delivered_messages[0]["html"],
        )
        self.assertIn("Why this matters for your business", delivered_messages[0]["html"])

    def test_results_email_sorts_items_and_humanizes_dates(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(**kwargs) -> None:
            delivered_messages.append(
                {
                    "to": str(kwargs.get("to_email") or ""),
                    "subject": str(kwargs.get("subject") or ""),
                    "text": str(kwargs.get("text_body") or ""),
                    "html": str(kwargs.get("html_body") or ""),
                }
            )

        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "summary": "Found a couple of relevant updates.",
                    "items": [
                        {
                            "id": "event-devday",
                            "title": "OpenAI DevDay 2026 announced for September 29, 2026",
                            "summary": "The event date is listed for September 29, 2026 in San Francisco.",
                            "why_it_matters": "This affects travel and staffing plans for conference attendance.",
                            "matched_watch_item": "conferences about ai and development",
                            "event_date": "2026-09-29",
                            "source_name": "OpenAI DevDay",
                            "source_url": "https://devday.openai.com/",
                            "urgency": "medium",
                        },
                        {
                            "id": "event-sede",
                            "title": "SEDE 2026 paper submission deadline is July 15, 2026",
                            "summary": "The CFP lists July 15, 2026 as the paper submission deadline.",
                            "why_it_matters": "Your team needs immediate writing and review time before the deadline.",
                            "matched_watch_item": "conference paper deadlines",
                            "event_date": "2026-07-15",
                            "source_name": "ISCA",
                            "source_url": "https://www.isca-hq.org/SEDE/CFP.html",
                            "urgency": "high",
                        },
                    ],
                }
            ),
            request_id="req_sorted",
            response_id="resp_sorted",
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
                "PUBLIC_BASE_URL": "https://portal.example.com",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            return_value=fake_response,
        ), mock.patch(
            "packages.tools.scheduled_monitor.monitor.send_email_notification",
            side_effect=fake_send_email_notification,
        ):
            result = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(result["ok"])
        text_body = delivered_messages[0]["text"]
        html_body = delivered_messages[0]["html"]
        self.assertLess(
            text_body.find("SEDE 2026 paper submission deadline is July 15, 2026"),
            text_body.find("OpenAI DevDay 2026 announced for September 29, 2026"),
        )
        self.assertIn("Search: conference paper deadlines", text_body)
        self.assertIn("When: July 15, 2026 (in 2 days)", text_body)
        self.assertIn("Search: conference paper deadlines", html_body)
        self.assertNotIn("High priority", html_body)
        self.assertIn("July 15, 2026 (in 2 days)", html_body)
        self.assertLess(
            html_body.find("SEDE 2026 paper submission deadline is July 15, 2026"),
            html_body.find("OpenAI DevDay 2026 announced for September 29, 2026"),
        )
        self.assertIn(">View source<", html_body)


if __name__ == "__main__":
    unittest.main()
