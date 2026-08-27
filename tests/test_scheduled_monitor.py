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
from packages.tools.scheduled_monitor.monitor import DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID
from packages.tools.scheduled_monitor.monitor import ScheduledMonitorConfig
from packages.tools.scheduled_monitor.monitor import ScheduledMonitorScheduler
from packages.tools.scheduled_monitor.monitor import build_monitor_prompt
from packages.tools.scheduled_monitor.monitor import normalize_monitor_settings
from packages.tools.scheduled_monitor.monitor import resolve_next_monitor_slot


class ScheduledMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(db_path)
        self.database.register_user("owner@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_monitor_search_context_is_high(self) -> None:
        self.assertEqual(DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE, "high")

    def test_monitor_prompt_guides_broad_local_event_search(self) -> None:
        prompt = build_monitor_prompt(
            target={"prompt": {}},
            settings={
                "watchItems": [
                    "fun events to do with kids · Location: HaSharon and central Israel · Date range: August",
                ],
            },
            scheduled_for=datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc),
            last_successful_run_at="2026-08-23T05:49:00+00:00",
            max_items=5,
        )

        self.assertIn("new to this monitor", prompt)
        self.assertIn("synonyms", prompt)
        self.assertIn("local-language terms", prompt)
        self.assertIn("רעננה", prompt)
        self.assertIn("תל אביב", prompt)
        self.assertIn("current year", prompt)

    def test_manual_prompt_requests_best_matches_without_new_filter(self) -> None:
        prompt = build_monitor_prompt(
            target={"prompt": {}},
            settings={"watchItems": ["family events in September"]},
            scheduled_for=datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc),
            last_successful_run_at="2026-08-23T06:00:00+00:00",
            max_items=5,
            manual_run=True,
        )

        self.assertIn("user-requested manual run", prompt)
        self.assertIn("even if they were sent before", prompt)
        self.assertIn("Do not filter results by whether they are new", prompt)

    def test_search_requires_web_search_and_structured_output(self) -> None:
        self._configure_monitor()
        response = SimpleNamespace(
            output_text=json.dumps({"summary": "No useful results.", "items": []}),
            request_id="request-structured",
            response_id="response-structured",
            model="gpt-5.4",
            raw_response={"status": "completed"},
        )
        scheduler = ScheduledMonitorScheduler(
            self.database,
            config=ScheduledMonitorConfig(max_output_tokens=1200),
        )
        with mock.patch(
            "packages.tools.scheduled_monitor.monitor.call_openai_response",
            return_value=response,
        ) as call_openai:
            target = scheduler._build_target_for_email("owner@example.com")
            self.assertIsNotNone(target)
            scheduler._run_search(
                target=target or {},
                settings=normalize_monitor_settings((target or {}).get("settings")),
                scheduled_for=datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc),
                manual_run=True,
            )

        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"type": "web_search", "search_context_size": "high"}])
        self.assertEqual(kwargs["reasoning"], {"effort": "low"})
        self.assertEqual(kwargs["extra_payload"]["tool_choice"], "required")
        response_format = kwargs["extra_payload"]["text"]["format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["strict"])
        self.assertEqual(response_format["schema"]["required"], ["summary", "items"])

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
                    "manualOnly": False,
                    "runMode": "recurring",
                    "intervalDays": 1,
                    "deliveryChannel": "portal",
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

        def fake_send_email_notification(*args, **kwargs):
            # Monitor findings now go to the in-app notification feed. The recorded
            # shape is kept so the existing subject/body assertions still apply.
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
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
        self.assertEqual(delivered_messages[0]["subject"], "Quick monitor update: 1 new match")
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
        self.assertFalse(second_run["metadata"]["noResultsNotificationSent"])
        self.assertTrue(second_run["metadata"]["noResultsDeliverySkipped"])
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
                    "manualOnly": False,
                    "runMode": "recurring",
                    "intervalDays": 7,
                    "deliveryChannel": "portal",
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

        def fake_send_email_notification(*args, **kwargs):
            # Monitor findings now go to the in-app notification feed. The recorded
            # shape is kept so the existing subject/body assertions still apply.
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
            side_effect=fake_send_email_notification,
        ):
            manual_result = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc))
            self.assertIsNone(self.database.get_latest_feature_monitor_run(user_id=1, feature_id=MONITOR_FEATURE_ID))
            first_scheduled_summary = scheduler.run_pending(now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(manual_result["ok"])
        self.assertEqual(manual_result["run"]["status"], "completed")
        self.assertEqual(manual_result["run"]["notificationsSent"], 1)
        self.assertEqual(len(delivered_messages), 1)
        self.assertEqual(delivered_messages[0]["subject"], "Monitor summary: 1 best match")
        self.assertIn("Criminal Defense Summit 2026 registration opened", delivered_messages[0]["text"])
        self.assertEqual(mock_openai_response.call_args.kwargs["model"], "gpt-5.4-nano")
        self.assertNotIn("temperature", mock_openai_response.call_args.kwargs)

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
        self.assertFalse(scheduled_run["metadata"]["noResultsNotificationSent"])
        self.assertTrue(scheduled_run["metadata"]["noResultsDeliverySkipped"])

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

    def test_minute_interval_monitor_runs_after_requested_minutes(self) -> None:
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "watchItems": ["Kid-friendly events in August around HaSharon and central Israel"],
                    "manualOnly": False,
                    "runMode": "recurring",
                    "intervalMinutes": 5,
                    "intervalDays": 1,
                    "deliveryChannel": "portal",
                }
            },
        )
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=MONITOR_FEATURE_ID,
            feature_name="Scheduled Web Monitor",
            is_active=True,
            activated_at="2026-08-22T20:00:00+00:00",
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

        fake_response = SimpleNamespace(
            output_text=json.dumps({
                "summary": "No relevant events found yet.",
                "items": [],
            }),
            request_id="req_minutes",
            response_id="resp_minutes",
            model="gpt-5.5",
        )
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(*args, **kwargs):
            delivered_messages.append({
                "to": "owner@example.com",
                "subject": str(kwargs.get("title") or ""),
                "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
            })
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
            side_effect=fake_send_email_notification,
        ):
            too_early = scheduler.run_pending(now=datetime(2026, 8, 22, 20, 4, tzinfo=timezone.utc))
            due = scheduler.run_pending(now=datetime(2026, 8, 22, 20, 5, tzinfo=timezone.utc))

        self.assertFalse(too_early["ran"])
        self.assertEqual(too_early["runs"][0]["reason"], "not_due")
        self.assertTrue(due["ran"])
        self.assertEqual(due["runs"][0]["scheduledFor"], "2026-08-22T20:05:00+00:00")
        self.assertEqual(due["runs"][0]["status"], "no_matches")
        self.assertEqual(delivered_messages, [])

        run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-08-22T20:05:00+00:00",
        )
        self.assertIsNotNone(run)
        self.assertFalse(run["metadata"]["noResultsNotificationSent"])
        self.assertTrue(run["metadata"]["noResultsDeliverySkipped"])

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

    def test_scheduler_records_no_results_without_notifying_empty_updates(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(*args, **kwargs):
            # Monitor findings now go to the in-app notification feed. The recorded
            # shape is kept so the existing subject/body assertions still apply.
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
            side_effect=fake_send_email_notification,
        ):
            summary = scheduler.run_pending(now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(summary["ran"])
        self.assertEqual(summary["runs"][0]["status"], "no_matches")
        self.assertEqual(summary["runs"][0]["notificationsSent"], 0)
        self.assertEqual(delivered_messages, [])

        run = self.database.get_feature_monitor_run(
            user_id=1,
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for="2026-07-10T09:00:00+00:00",
        )
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "no_matches")
        self.assertFalse(run["metadata"]["noResultsNotificationSent"])
        self.assertTrue(run["metadata"]["noResultsDeliverySkipped"])

    def test_manual_rerun_marks_empty_search_as_inconsistent_when_recent_results_exist(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(*args, **kwargs):
            # Monitor findings now go to the in-app notification feed. The recorded
            # shape is kept so the existing subject/body assertions still apply.
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
            side_effect=fake_send_email_notification,
        ):
            first_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
            second_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc))

        self.assertTrue(first_run["ok"])
        self.assertEqual(first_run["run"]["status"], "completed")
        self.assertTrue(second_run["ok"])
        self.assertEqual(second_run["run"]["status"], "no_matches")
        self.assertEqual(second_run["run"]["notificationsSent"], 0)
        self.assertEqual(len(delivered_messages), 2)
        self.assertTrue(second_run["run"]["run"]["metadata"]["noResultsNotificationSent"])
        self.assertEqual(second_run["run"]["run"]["metadata"]["recentResultsCount"], 1)
        self.assertEqual(second_run["run"]["run"]["metadata"]["recentResultsMinutesAgo"], 30)
        self.assertEqual(second_run["run"]["run"]["metadata"]["liveSearchStatus"], "no_matches")

    def test_manual_rerun_keeps_duplicate_matches_status_when_live_search_repeats_results(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(*args, **kwargs):
            # Monitor findings now go to the in-app notification feed. The recorded
            # shape is kept so the existing subject/body assertions still apply.
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
            side_effect=fake_send_email_notification,
        ):
            first_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
            second_run = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc))

        self.assertTrue(first_run["ok"])
        self.assertEqual(first_run["run"]["status"], "completed")
        self.assertTrue(second_run["ok"])
        self.assertEqual(second_run["run"]["status"], "completed")
        self.assertEqual(second_run["run"]["notificationsSent"], 1)
        self.assertEqual(len(delivered_messages), 2)
        self.assertEqual(delivered_messages[1]["subject"], "Monitor summary: 1 best match")
        self.assertIn("Here is the best match for your watch list.", delivered_messages[1]["text"])
        self.assertFalse(second_run["run"]["run"]["metadata"]["noResultsNotificationSent"])
        self.assertEqual(second_run["run"]["run"]["metadata"]["resultPolicy"], "best_matches")

    def test_manual_only_monitor_never_runs_from_background_scheduler(self) -> None:
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "watchItems": ["family events"],
                    "manualOnly": True,
                    "runMode": "manual",
                    "intervalDays": 1,
                    "deliveryChannel": "portal",
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

        self.assertTrue(normalize_monitor_settings({"manualOnly": True})["manualOnly"])
        self.assertTrue(normalize_monitor_settings({"manualOnly": False})["manualOnly"])
        self.assertFalse(normalize_monitor_settings({"manualOnly": False, "runMode": "recurring"})["manualOnly"])
        self.assertIsNone(
            resolve_next_monitor_slot(
                now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
                settings={"manualOnly": True, "intervalDays": 1},
                activated_at="2026-07-09T09:00:00+00:00",
                last_scheduled_for="",
            )
        )

        scheduler = ScheduledMonitorScheduler(self.database)
        with mock.patch("packages.tools.scheduled_monitor.monitor.call_openai_response") as mock_openai_response:
            summary = scheduler.run_pending(now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))

        self.assertFalse(summary["ran"])
        self.assertEqual(summary["runs"][0]["reason"], "manual_only")
        mock_openai_response.assert_not_called()

    def test_manual_run_cancellation_skips_delivery(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []
        cancellation_requested = False

        def fake_send_email_notification(*args, **kwargs):
            # Monitor findings now go to the in-app notification feed. The recorded
            # shape is kept so the existing subject/body assertions still apply.
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
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

        def fake_send_email_notification(*args, **kwargs):
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                    "html": "",
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
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
        # The editor link now rides on the notification as its result URL.
        self.assertEqual(
            delivered_messages[0]["resultUrl"],
            "https://portal.example.com/portal/#features/scheduled-web-monitor-notifier/editor",
        )
        self.assertIn("Why this matters for your business", delivered_messages[0]["text"])

    def test_results_notification_sorts_items_and_humanizes_dates(self) -> None:
        self._configure_monitor()
        delivered_messages: list[dict[str, str]] = []

        def fake_send_email_notification(*args, **kwargs):
            delivered_messages.append(
                {
                    "to": "owner@example.com",
                    "subject": str(kwargs.get("title") or ""),
                    "text": str(kwargs.get("body") or ""),
                "resultUrl": str(kwargs.get("result_url") or ""),
                    "resultUrl": str(kwargs.get("result_url") or ""),
                    "html": "",
                }
            )
            return {"id": len(delivered_messages)}

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
            "packages.tools.scheduled_monitor.monitor.deliver_portal_notification",
            side_effect=fake_send_email_notification,
        ):
            result = scheduler.run_for_email("owner@example.com", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

        self.assertTrue(result["ok"])
        # HTML email bodies are gone; the notification carries the same text.
        text_body = delivered_messages[0]["text"]
        self.assertLess(
            text_body.find("SEDE 2026 paper submission deadline is July 15, 2026"),
            text_body.find("OpenAI DevDay 2026 announced for September 29, 2026"),
        )
        self.assertIn("Search: conference paper deadlines", text_body)
        self.assertIn("When: July 15, 2026 (in 2 days)", text_body)
        self.assertNotIn("High priority", text_body)


if __name__ == "__main__":
    unittest.main()
