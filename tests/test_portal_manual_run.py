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
from packages.infrastructure.portal_auth.server import describe_manual_reengagement_demo_run
from packages.infrastructure.portal_auth.server import parse_whatsapp_export_messages
from packages.infrastructure.portal_auth.server import parse_whatsapp_export_timestamp
from packages.infrastructure.whatsapp_reengagement import REENGAGEMENT_FEATURE_ID
from packages.infrastructure.whatsapp_portal_service import PortalWhatsAppService
from packages.infrastructure.whatsapp_portal_service import build_portal_service_from_connection
from packages.infrastructure.whatsapp_portal_service import build_portal_runtime_config
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID
from packages.tools.whatsapp_reply_approval.server import BackendStore
from packages.tools.whatsapp_reply_approval.server import OWNER_REVIEW_ACTION_TEXT
from packages.tools.whatsapp_reply_approval.server import OWNER_REVIEW_INTRO_TEXT
from packages.tools.whatsapp_reply_approval.server import extract_inbound_events
from packages.tools.whatsapp_reply_approval.server import parse_owner_command_text
from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message


WHATSAPP_REPLY_ASSISTANT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"


class PortalManualRunDescriptionTests(unittest.TestCase):
    def test_reengagement_demo_description_keeps_findings_on_delivery_failure(self) -> None:
        message = describe_manual_reengagement_demo_run(
            {
                "status": "delivery_failed",
                "candidatesCount": 2,
                "notificationsSent": 0,
                "ownerWaId": "972507322341",
                "deliveryMode": "none",
                "deliveryErrors": ["Action not available because account is restricted."],
            }
        )

        self.assertIn("generated follow-up drafts", message)
        self.assertIn("Owner delivery failed", message)
        self.assertIn("review the findings in the portal", message)


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

    def test_portal_approval_skip_endpoint_is_account_scoped(self) -> None:
        connection = self.server.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            access_token="test-token",
            connection_status="connected",
        )
        service = build_portal_service_from_connection(
            root=self.root,
            connection=connection,
            base_url=self.base_url,
            store_cache=self.server.whatsapp_stores,
            store_lock=self.server.whatsapp_store_lock,
        )
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="Maya Cohen",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.portal-skip",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )
        self.server.database.map_whatsapp_approval(
            approval["approval_id"],
            user_id=int(connection["userId"]),
            phone_number_id="12345",
        )

        status, body = self._request(
            "POST",
            f"/api/approvals/{approval['approval_id']}/skip",
            {},
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["approval"]["status"], "skipped")

    def test_delete_reengagement_demo_run_marks_active_run_cancelled(self) -> None:
        request_started = threading.Event()
        post_result: dict[str, object] = {}

        def fake_run_demo_for_email(_scheduler, email: str, *, now=None, cancel_check=None):
            self.assertEqual(email, "owner@example.com")
            request_started.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                if callable(cancel_check) and cancel_check():
                    return {
                        "ok": True,
                        "demo": True,
                        "run": {
                            "status": "cancelled",
                            "scheduledFor": "2026-07-13T12:00:00+00:00",
                            "candidatesCount": 0,
                            "notificationsSent": 0,
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
                    f"/api/features/{REENGAGEMENT_FEATURE_ID}/run",
                    {"runRequestId": "demo-run-1"},
                )
                post_result["status"] = status
                post_result["body"] = body
            except Exception as exc:  # pragma: no cover - test failure surface
                post_result["error"] = exc

        with mock.patch(
            "packages.infrastructure.portal_auth.server.WhatsAppReengagementScheduler.run_demo_for_email",
            new=fake_run_demo_for_email,
        ):
            post_thread = threading.Thread(target=send_post, daemon=True)
            post_thread.start()
            self.assertTrue(request_started.wait(timeout=1))

            cancel_status, cancel_body = self._request(
                "DELETE",
                f"/api/features/{REENGAGEMENT_FEATURE_ID}/run",
                {"runRequestId": "demo-run-1"},
            )

            post_thread.join(timeout=2)

        if "error" in post_result:
            raise post_result["error"]  # type: ignore[misc]

        self.assertEqual(cancel_status, 200)
        self.assertTrue(cancel_body["ok"])
        self.assertEqual(post_result["status"], 200)
        self.assertEqual(post_result["body"]["run"]["status"], "cancelled")
        self.assertIn("cancelled", str(post_result["body"]["message"]).lower())

    def test_reengagement_demo_description_names_mock_delivery(self) -> None:
        message = describe_manual_reengagement_demo_run(
            {
                "status": "no_candidates",
                "candidatesCount": 0,
                "notificationsSent": 1,
                "ownerWaId": "972507322341",
                "deliveryMode": "mock",
            }
        )

        self.assertIn("simulated", message)
        self.assertIn("+972507322341", message)
        self.assertIn("Live WhatsApp delivery is not configured", message)


class PortalWhatsAppTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name) / "whatsapp-store.json"
        self.env_patcher = mock.patch.dict(
            os.environ,
            {"WHATSAPP_ACCESS_TOKEN": "test-token"},
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def _build_service(
        self,
        *,
        templates: dict[str, object] | None = None,
        delivery_settings: dict[str, object] | None = None,
    ) -> PortalWhatsAppService:
        config = build_portal_runtime_config(
            client_id="portal-user-1",
            client_name="Portal User",
            base_url="https://example.com",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            data_path=self.data_path,
            templates=templates,
        )
        config.access_token = "test-token"
        if delivery_settings is None:
            delivery_settings = {"deliveryChannels": ["whatsapp"]}
        return PortalWhatsAppService(config, BackendStore(self.data_path), delivery_settings=delivery_settings)

    def test_build_portal_runtime_config_reads_sample_template_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_SAMPLE_TEMPLATE_NAME": "assistyca_sample_alert",
                "WHATSAPP_SAMPLE_TEMPLATE_LANGUAGE": "he",
            },
            clear=False,
        ):
            config = build_portal_runtime_config(
                client_id="portal-user-1",
                client_name="Portal User",
                base_url="https://example.com",
                phone_number_id="12345",
                owner_wa_id="15551234567",
                data_path=self.data_path,
            )

        self.assertEqual(
            config.templates["sample_owner"],
            {
                "name": "assistyca_sample_alert",
                "language": "he",
            },
        )

    def test_build_portal_runtime_config_normalizes_local_israeli_owner_phone(self) -> None:
        config = build_portal_runtime_config(
            client_id="portal-user-1",
            client_name="Portal User",
            base_url="https://example.com",
            phone_number_id="12345",
            owner_wa_id="0507322341",
            data_path=self.data_path,
        )

        self.assertEqual(config.owner_wa_id, "972507322341")

    def test_build_portal_runtime_config_reads_reply_assistant_template_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_NAME": "new_reply_for_review",
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_LANGUAGE": "en",
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_INDEX": "0",
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_TYPE": "quick_reply",
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_ACTION": "generate",
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_URL_MODE": "path",
            },
            clear=False,
        ):
            config = build_portal_runtime_config(
                client_id="portal-user-1",
                client_name="Portal User",
                base_url="https://example.com",
                phone_number_id="12345",
                owner_wa_id="15551234567",
                data_path=self.data_path,
            )

        self.assertEqual(
            config.templates["owner_notification"],
            {
                "name": "new_reply_for_review",
                "language": "en",
                "button_index": "0",
                "button_type": "quick_reply",
                "button_action": "generate",
                "url_mode": "path",
            },
        )

    def test_build_portal_runtime_config_reads_reengagement_report_template_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_NAME": "reengagement_report_prompt",
                "WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_LANGUAGE": "en",
                "WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_BUTTON_INDEX": "1",
                "WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_BUTTON_ACTION": "details",
            },
            clear=False,
        ):
            config = build_portal_runtime_config(
                client_id="portal-user-1",
                client_name="Portal User",
                base_url="https://example.com",
                phone_number_id="12345",
                owner_wa_id="15551234567",
                data_path=self.data_path,
            )

        self.assertEqual(config.templates["reengagement_report"]["name"], "reengagement_report_prompt")
        self.assertEqual(config.templates["reengagement_report"]["language"], "en")
        self.assertEqual(config.templates["reengagement_report"]["button_index"], "1")
        self.assertEqual(config.templates["reengagement_report"]["button_action"], "details")

    def test_build_portal_runtime_config_accepts_legacy_owner_notification_template_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_NAME": "legacy_reply_alert",
                "WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_LANGUAGE": "en",
                "WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_BUTTON_INDEX": "0",
                "WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_URL_MODE": "path",
            },
            clear=False,
        ):
            config = build_portal_runtime_config(
                client_id="portal-user-1",
                client_name="Portal User",
                base_url="https://example.com",
                phone_number_id="12345",
                owner_wa_id="15551234567",
                data_path=self.data_path,
            )

        self.assertEqual(
            config.templates["owner_notification"],
            {
                "name": "legacy_reply_alert",
                "language": "en",
                "button_index": "0",
                "button_type": "url",
                "button_action": "generate",
                "url_mode": "path",
            },
        )

    def test_build_portal_runtime_config_defaults_to_reply_assistant_template_sequence(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config = build_portal_runtime_config(
                client_id="portal-user-1",
                client_name="Portal User",
                base_url="https://example.com",
                phone_number_id="12345",
                owner_wa_id="15551234567",
                data_path=self.data_path,
            )

        self.assertEqual(
            config.templates["owner_notification"],
            {
                "name": "",
                "first_name": "whatsapp_reply_assistant_1",
                "repeat_name": "whatsapp_reply_assistant_2",
                "language": "en",
                "button_index": "0",
                "button_type": "quick_reply",
                "button_action": "generate",
                "disable_button_index": "1",
                "disable_button_action": "disable_contact",
                "url_mode": "path",
            },
        )

    def test_build_portal_runtime_config_prefers_quick_reply_when_variant_templates_are_set(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_REPLY_ASSISTANT_TEMPLATE_NAME": "legacy_reply_alert",
                "WHATSAPP_REPLY_ASSISTANT_FIRST_TEMPLATE_NAME": "whatsapp_reply_assistant_1",
                "WHATSAPP_REPLY_ASSISTANT_REPEAT_TEMPLATE_NAME": "whatsapp_reply_assistant_2",
            },
            clear=True,
        ):
            config = build_portal_runtime_config(
                client_id="portal-user-1",
                client_name="Portal User",
                base_url="https://example.com",
                phone_number_id="12345",
                owner_wa_id="15551234567",
                data_path=self.data_path,
            )

        self.assertEqual(config.templates["owner_notification"]["button_type"], "quick_reply")
        self.assertEqual(config.templates["owner_notification"]["first_name"], "whatsapp_reply_assistant_1")
        self.assertEqual(config.templates["owner_notification"]["repeat_name"], "whatsapp_reply_assistant_2")

    def _build_notified_service(self):
        """A service wired to a real database, as the portal builds it."""

        database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        database.register_user("owner@example.com")
        user_id = int((database.get_user("owner@example.com") or {})["id"])
        service = self._build_service()
        service.database = database
        service.user_id = user_id
        return service, database, user_id

    def test_owner_notification_lands_in_the_portal_feed(self) -> None:
        service, database, user_id = self._build_notified_service()
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.inbound-1",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
        ) as mocked_send:
            message_id = service.notify_owner_about_approval(approval)

        # The owner alert never leaves the portal now.
        mocked_send.assert_not_called()
        self.assertTrue(message_id.startswith("portal-notification-"))

        notifications = database.list_notifications(user_id=user_id)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["kind"], "reply_approval")
        self.assertIn("John Doe", notifications[0]["title"])
        self.assertIn("Can you help tomorrow?", notifications[0]["body"])
        self.assertEqual(notifications[0]["actionId"], approval["approval_id"])
        self.assertFalse(notifications[0]["read"])

        stored_approval = service.store.get_approval(approval["approval_id"])
        self.assertEqual(stored_approval.get("owner_notification_delivery_channels"), ["portal"])
        self.assertEqual(stored_approval.get("owner_state"), "pending")
        # The public review page is gone, so no URL is recorded.
        self.assertEqual(stored_approval.get("owner_notification_review_url"), "")

    def test_repeat_notification_for_the_same_approval_is_deduped(self) -> None:
        service, database, user_id = self._build_notified_service()
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.inbound-dedupe",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )

        service.notify_owner_about_approval(approval)
        service.notify_owner_about_approval(approval)

        self.assertEqual(len(database.list_notifications(user_id=user_id)), 1)

    def test_notification_failure_is_raised_rather_than_reported_as_sent(self) -> None:
        service, _database, _user_id = self._build_notified_service()
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.inbound-fail",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.deliver_portal_notification",
            side_effect=RuntimeError("notification store down"),
        ):
            with self.assertRaises(RuntimeError):
                service.notify_owner_about_approval(approval)

    def test_owner_quick_reply_generate_sends_hot_review_prompt(self) -> None:
        service = self._build_service()
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.inbound-1",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )
        service.store.append_approval_message_id(approval["approval_id"], "wamid.template-quick-reply")

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            side_effect=[
                "wamid.hot-review-intro",
                "wamid.hot-review-reply",
                "wamid.hot-review-actions",
            ],
        ) as mocked_send:
            result = service.handle_owner_event(
                {
                    "thread_id": "15551234567",
                    "sender_name": "Owner",
                    "sender_wa_id": "15551234567",
                    "message_text": "Sure!",
                    "message_type": "interactive",
                    "source_message_id": "wamid.owner-sure",
                    "reply_to_message_id": "wamid.template-quick-reply",
                    "interactive_reply": {
                        "id": f"approval:{approval['approval_id']}:generate",
                        "title": "Sure!",
                        "type": "button_reply",
                    },
                    "raw_payload": {"object": "whatsapp_business_account"},
                }
            )

        self.assertEqual(result["action"], "show_suggestion")
        self.assertEqual(
            result["message_ids"],
            [
                "wamid.hot-review-intro",
                "wamid.hot-review-reply",
                "wamid.hot-review-actions",
            ],
        )
        self.assertEqual(mocked_send.call_count, 3)
        self.assertEqual(mocked_send.call_args_list[0].kwargs["message_text"], OWNER_REVIEW_INTRO_TEXT)
        self.assertIsNone(mocked_send.call_args_list[0].kwargs["interactive"])
        self.assertEqual(
            mocked_send.call_args_list[1].kwargs["message_text"],
            approval["suggested_reply"],
        )
        self.assertNotIn("Suggested reply:", mocked_send.call_args_list[1].kwargs["message_text"])
        self.assertIsNone(mocked_send.call_args_list[1].kwargs["interactive"])
        self.assertIsNone(mocked_send.call_args_list[2].kwargs["message_text"])
        self.assertIsNone(mocked_send.call_args_list[2].kwargs["template"])
        self.assertEqual(mocked_send.call_args_list[2].kwargs["interactive"]["type"], "button")
        self.assertEqual(
            mocked_send.call_args_list[2].kwargs["interactive"]["body"]["text"],
            OWNER_REVIEW_ACTION_TEXT,
        )
        button_ids = [
            button["reply"]["id"]
            for button in mocked_send.call_args_list[2].kwargs["interactive"]["action"]["buttons"]
        ]
        self.assertIn(f"approval:{approval['approval_id']}:send", button_ids)
        updated = service.store.get_approval(approval["approval_id"])
        self.assertEqual(updated["owner_state"], "reviewing")
        self.assertEqual(updated["owner_review_intro_message_id"], "wamid.hot-review-intro")
        self.assertEqual(updated["owner_review_reply_message_id"], "wamid.hot-review-reply")
        self.assertEqual(updated["owner_review_message_id"], "wamid.hot-review-actions")
        self.assertEqual(updated["owner_review_text"], approval["suggested_reply"])

    def test_reengagement_report_uses_template_and_stores_pending_details(self) -> None:
        service = self._build_service(
            templates={
                "reengagement_report": {
                    "name": "reengagement_report_prompt",
                    "language": "en",
                    "button_index": "0",
                    "button_action": "send",
                },
            },
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.reengagement-prompt",
        ) as mocked_send:
            delivery = service.send_reengagement_report(
                {
                    "reengagementReport": {
                        "demo": True,
                        "candidatesCount": 2,
                        "scheduledFor": "2026-08-04T20:00:00+00:00",
                    }
                },
                "Full generated report details",
            )

        self.assertEqual(delivery["messageId"], "wamid.reengagement-prompt")
        self.assertEqual(delivery["deliveryMode"], "template_prompt")
        report = service.find_reengagement_report(delivery["reportId"])
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["status"], "prompt_sent")
        self.assertEqual(report["messageText"], "Full generated report details")
        self.assertEqual(report["promptMessageId"], "wamid.reengagement-prompt")
        template = mocked_send.call_args.kwargs["template"]
        self.assertEqual(template["name"], "reengagement_report_prompt")
        self.assertEqual(
            template["components"][0]["parameters"][0]["text"],
            "we found 2 people who have not been reached in a long time",
        )
        payload = template["components"][1]["parameters"][0]["payload"]
        self.assertEqual(payload, f"reengagement:{delivery['reportId']}:send")
        self.assertIsNone(mocked_send.call_args.kwargs["message_text"])
        self.assertIsNone(mocked_send.call_args.kwargs["interactive"])

    def test_reengagement_template_reply_sends_stored_report_details(self) -> None:
        service = self._build_service(
            templates={
                "reengagement_report": {
                    "name": "reengagement_report_prompt",
                    "language": "en",
                    "button_index": "0",
                    "button_action": "send",
                },
            },
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.reengagement-prompt",
        ):
            delivery = service.send_reengagement_report(
                {"reengagementReport": {"demo": True, "candidatesCount": 1}},
                "Full generated report details",
            )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.reengagement-details",
        ) as mocked_send:
            result = service.handle_owner_event(
                {
                    "thread_id": "15551234567",
                    "sender_name": "Owner",
                    "sender_wa_id": "15551234567",
                    "message_text": "Send details",
                    "message_type": "interactive",
                    "source_message_id": "wamid.owner-send-details",
                    "reply_to_message_id": "wamid.reengagement-prompt",
                    "interactive_reply": {
                        "id": f"reengagement:{delivery['reportId']}:send",
                        "title": "Send details",
                        "type": "button_reply",
                    },
                    "raw_payload": {"object": "whatsapp_business_account"},
                }
            )

        self.assertEqual(result["action"], "reengagement_report_sent")
        self.assertEqual(result["message_id"], "wamid.reengagement-details")
        self.assertEqual(mocked_send.call_args.kwargs["message_text"], "Full generated report details")
        updated = service.find_reengagement_report(delivery["reportId"])
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["status"], "sent")
        self.assertEqual(updated["detailsMessageId"], "wamid.reengagement-details")

    def test_owner_hebrew_approval_sends_single_pending_suggestion(self) -> None:
        service = self._build_service()
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.inbound-hebrew-approval",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )

        self.assertEqual(parse_owner_command_text("מאשר"), ("send_suggested", ""))

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.customer-hebrew-approval",
        ):
            result = service.handle_owner_event(
                {
                    "thread_id": "15551234567",
                    "sender_name": "Owner",
                    "sender_wa_id": "15551234567",
                    "message_text": "מאשר",
                    "message_type": "text",
                    "source_message_id": "wamid.owner-hebrew-approval",
                    "reply_to_message_id": "",
                    "interactive_reply": {},
                    "raw_payload": {"object": "whatsapp_business_account"},
                }
            )

        self.assertEqual(result["action"], "send_suggested")
        self.assertEqual(result["sent_message_id"], "wamid.customer-hebrew-approval")
        updated = service.store.get_approval(approval["approval_id"])
        self.assertEqual(updated["status"], "sent")
        self.assertEqual(updated["sent_text"], approval["suggested_reply"])

    def test_owner_disable_contact_button_suppresses_future_suggestions(self) -> None:
        service = self._build_service()
        approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="Can you help tomorrow?",
            source_message_id="wamid.inbound-1",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )
        service.store.append_approval_message_id(approval["approval_id"], "wamid.template-first")

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.contact-disabled",
        ):
            result = service.handle_owner_event(
                {
                    "thread_id": "15551234567",
                    "sender_name": "Owner",
                    "sender_wa_id": "15551234567",
                    "message_text": "Never ask for this contact again",
                    "message_type": "button",
                    "source_message_id": "wamid.owner-disable",
                    "reply_to_message_id": "wamid.template-first",
                    "interactive_reply": {
                        "id": f"approval:{approval['approval_id']}:disable_contact",
                        "title": "Never ask for this contact again",
                        "type": "button",
                    },
                    "raw_payload": {"object": "whatsapp_business_account"},
                }
            )

        self.assertEqual(result["action"], "disable_contact")
        updated = service.store.get_approval(approval["approval_id"])
        self.assertEqual(updated["status"], "skipped")
        self.assertEqual(updated["owner_state"], "contact_disabled")
        thread = service.store.get_thread("15551230000")
        self.assertTrue(thread["reply_assistant_disabled"])

        suppressed = service.handle_customer_event(
            {
                "thread_id": "15551230000",
                "sender_name": "John Doe",
                "sender_wa_id": "15551230000",
                "message_text": "Are you there?",
                "source_message_id": "wamid.inbound-2",
                "message_type": "text",
                "raw_payload": {"object": "whatsapp_business_account"},
            }
        )

        self.assertEqual(suppressed["action"], "reply_assistant_suppressed")
        self.assertIsNone(suppressed["approval"])
        self.assertEqual(len(service.store.data["approvals"]), 1)
        thread = service.store.get_thread("15551230000")
        self.assertEqual(thread["latest_message"], "Are you there?")
        self.assertEqual(thread["pending_approval_id"], "")

    def test_extract_inbound_events_handles_template_button_reply(self) -> None:
        events = extract_inbound_events(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": "12345"},
                                    "contacts": [
                                        {
                                            "wa_id": "15551234567",
                                            "profile": {"name": "Owner"},
                                        }
                                    ],
                                    "messages": [
                                        {
                                            "from": "15551234567",
                                            "id": "wamid.owner-sure",
                                            "timestamp": "1720000000",
                                            "type": "button",
                                            "context": {"id": "wamid.template-quick-reply"},
                                            "button": {
                                                "text": "Sure!",
                                                "payload": "approval:abcdef123456:generate",
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message_type"], "button")
        self.assertEqual(events[0]["message_text"], "Sure!")
        self.assertEqual(events[0]["reply_to_message_id"], "wamid.template-quick-reply")
        self.assertEqual(
            events[0]["interactive_reply"],
            {
                "id": "approval:abcdef123456:generate",
                "title": "Sure!",
                "type": "button",
            },
        )

    def test_extract_inbound_events_handles_template_disable_contact_button_reply(self) -> None:
        events = extract_inbound_events(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": "12345"},
                                    "contacts": [
                                        {
                                            "wa_id": "15551234567",
                                            "profile": {"name": "Owner"},
                                        }
                                    ],
                                    "messages": [
                                        {
                                            "from": "15551234567",
                                            "id": "wamid.owner-never",
                                            "timestamp": "1720000001",
                                            "type": "button",
                                            "context": {"id": "wamid.template-first"},
                                            "button": {
                                                "text": "Never ask for this contact again",
                                                "payload": "approval:abcdef123456:disable_contact",
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message_type"], "button")
        self.assertEqual(events[0]["message_text"], "Never ask for this contact again")
        self.assertEqual(events[0]["reply_to_message_id"], "wamid.template-first")
        self.assertEqual(
            events[0]["interactive_reply"],
            {
                "id": "approval:abcdef123456:disable_contact",
                "title": "Never ask for this contact again",
                "type": "button",
            },
        )

    def test_sample_owner_message_uses_template_when_configured(self) -> None:
        service = self._build_service(
            templates={
                "sample_owner": {
                    "name": "assistyca_sample_alert",
                    "language": "en_US",
                },
            },
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.template-1",
        ) as mocked_send:
            message_id, message_text = service.send_sample_owner_message()

        self.assertEqual(message_id, "wamid.template-1")
        self.assertIn("Sample reply alert from Assistyca", message_text)
        mocked_send.assert_called_once()
        self.assertEqual(mocked_send.call_args.kwargs["phone_number_id"], "1186653017865246")
        self.assertIsNone(mocked_send.call_args.kwargs["message_text"])
        self.assertEqual(
            mocked_send.call_args.kwargs["template"],
            {
                "name": "assistyca_sample_alert",
                "language": {
                    "code": "en_US",
                },
            },
        )

    def test_sample_owner_message_falls_back_to_text_without_template(self) -> None:
        service = self._build_service()

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.text-1",
        ) as mocked_send:
            message_id, message_text = service.send_sample_owner_message()

        self.assertEqual(message_id, "wamid.text-1")
        self.assertIn("Sample reply alert from Assistyca", message_text)
        mocked_send.assert_called_once()
        self.assertEqual(mocked_send.call_args.kwargs["phone_number_id"], "1186653017865246")
        self.assertIsNone(mocked_send.call_args.kwargs["template"])
        self.assertIn("Maya Cohen", mocked_send.call_args.kwargs["message_text"])


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
            "packages.tools.whatsapp_reply_approval.server.urllib_request.urlopen",
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


class PortalWhatsAppSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patcher = mock.patch.dict(
            os.environ,
            {"PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp")},
            clear=False,
        )
        self.env_patcher.start()

        # Webhook signature verification fails closed, so these routing tests would
        # otherwise all 403 for want of a WHATSAPP_APP_SECRET. What they exercise is
        # message routing, not authentication; the fail-closed behaviour has its own
        # tests in WhatsAppWebhookSignatureTests below.
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
        self.signature_patcher.stop()
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
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib_error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def test_feature_sample_endpoint_sends_owner_alert_and_updates_health_metadata(self) -> None:
        self.server.database.save_feature_assignment_metadata(
            "owner@example.com",
            WHATSAPP_REPLY_ASSISTANT_FEATURE_ID,
            metadata={
                "settings": {
                    "deliveryChannels": ["whatsapp"],
                }
            },
        )
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

    def test_feature_sample_endpoint_accepts_portal_delivery_without_live_send(self) -> None:
        status, body = self._request(
            "POST",
            f"/api/features/{WHATSAPP_REPLY_ASSISTANT_FEATURE_ID}/sample",
            {},
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(str(body["ownerMessageId"]).startswith("portal-sample-"))
        self.assertEqual(body["connection"]["metadata"]["lastOwnerNotificationStatus"], "requested")

    def test_whatsapp_connection_endpoint_requires_client_token_even_with_sender_token(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_ACCESS_TOKEN": "sender-token"}, clear=False):
            status, body = self._request(
                "POST",
                "/api/whatsapp/connection",
                {
                    "business_account_id": "11111",
                    "phone_number_id": "22222",
                    "owner_wa_id": "15551234567",
                },
            )

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "invalid_fields")
        self.assertIn("access_token", {issue["field"] for issue in body["issues"]})

    def test_whatsapp_connection_endpoint_stores_client_token_and_subscribes_waba(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {
                    "PUBLIC_BASE_URL": "https://portal.example.com",
                    "WHATSAPP_ACCESS_TOKEN": "",
                    "WHATSAPP_VERIFY_TOKEN": "verify-token",
                },
                clear=False,
            ),
            mock.patch(
                "packages.infrastructure.portal_auth.server.test_whatsapp_connection",
                return_value={
                    "phone_number_id": "22222",
                    "display_phone_number": "+1 555 123 4567",
                    "verified_name": "Client Co",
                },
            ) as mocked_test,
            mock.patch(
                "packages.infrastructure.portal_auth.server.list_whatsapp_business_phone_numbers",
                return_value=[
                    {
                        "id": "22222",
                        "display_phone_number": "+1 555 123 4567",
                        "verified_name": "Client Co",
                    }
                ],
            ) as mocked_list_numbers,
            mock.patch(
                "packages.infrastructure.portal_auth.server.subscribe_whatsapp_business_account",
                return_value={"success": True},
            ) as mocked_subscribe,
        ):
            status, body = self._request(
                "POST",
                "/api/whatsapp/connection",
                {
                    "business_account_id": "11111",
                    "phone_number_id": "22222",
                    "access_token": "client-token",
                    "owner_wa_id": "15551234567",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        mocked_test.assert_called_once_with(access_token="client-token", phone_number_id="22222")
        mocked_list_numbers.assert_called_once_with(access_token="client-token", business_account_id="11111")
        mocked_subscribe.assert_called_once_with(
            access_token="client-token",
            business_account_id="11111",
            callback_url="https://portal.example.com/webhooks/whatsapp",
            verify_token="verify-token",
        )
        self.assertNotIn("accessToken", body["connection"])
        self.assertTrue(body["connection"]["accessTokenConfigured"])
        self.assertTrue(body["connection"]["workspaceAccessTokenConfigured"])
        self.assertEqual(body["connection"]["businessAccountId"], "11111")
        self.assertEqual(body["connection"]["phoneNumberId"], "22222")

        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["accessToken"], "client-token")
        self.assertEqual(stored["metadata"]["webhookSubscriptionStatus"], "subscribed")
        self.assertEqual(stored["metadata"]["webhookCallbackUrl"], "https://portal.example.com/webhooks/whatsapp")
        self.assertTrue(stored["metadata"]["webhookCallbackOverrideApplied"])
        self.assertTrue(stored["metadata"]["webhookVerifyTokenConfigured"])

    def test_whatsapp_connection_endpoint_refreshes_webhook_and_number_details(self) -> None:
        self.server.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="11111",
            phone_number_id="22222",
            access_token="client-token",
            owner_wa_id="15551234567",
            display_phone_number="+1 555 123 4567",
            verified_name="Client Co",
            connection_status="connected",
            metadata={
                "webhookSubscriptionStatus": "subscribed",
            },
        )

        with mock.patch(
            "packages.infrastructure.portal_auth.server.test_whatsapp_connection",
            return_value={
                "phone_number_id": "22222",
                "display_phone_number": "+1 555 765 0000",
                "verified_name": "Updated Co",
            },
        ) as mocked_test:
            with mock.patch(
                "packages.infrastructure.portal_auth.server.list_whatsapp_business_phone_numbers",
                side_effect=AssertionError("WABA phone numbers should not be listed"),
            ) as mocked_list_numbers:
                with mock.patch(
                    "packages.infrastructure.portal_auth.server.subscribe_whatsapp_business_account",
                    return_value={"success": True},
                ) as mocked_subscribe:
                    with mock.patch.dict(
                        os.environ,
                        {
                            "PUBLIC_BASE_URL": "https://portal.example.com",
                            "WHATSAPP_VERIFY_TOKEN": "verify-token",
                        },
                        clear=False,
                    ):
                        status, body = self._request(
                            "POST",
                            "/api/whatsapp/connection",
                            {
                                "business_account_id": "11111",
                                "phone_number_id": "22222",
                                "owner_wa_id": "0507322341",
                            },
                        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["liveTested"])
        self.assertTrue(body["numberDetailsRefreshed"])
        self.assertIn("webhook subscription was refreshed", body["message"])
        self.assertEqual(body["connection"]["ownerWaId"], "972507322341")
        self.assertEqual(body["connection"]["displayPhoneNumber"], "+1 555 765 0000")
        self.assertEqual(body["connection"]["verifiedName"], "Updated Co")
        mocked_test.assert_called_once_with(access_token="client-token", phone_number_id="22222")
        mocked_list_numbers.assert_not_called()
        mocked_subscribe.assert_called_once_with(
            access_token="client-token",
            business_account_id="11111",
            callback_url="https://portal.example.com/webhooks/whatsapp",
            verify_token="verify-token",
        )

        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["ownerWaId"], "972507322341")
        self.assertEqual(stored["accessToken"], "client-token")
        self.assertEqual(stored["displayPhoneNumber"], "+1 555 765 0000")
        self.assertEqual(stored["verifiedName"], "Updated Co")
        self.assertEqual(stored["metadata"]["webhookCallbackUrl"], "https://portal.example.com/webhooks/whatsapp")
        self.assertTrue(stored["metadata"]["webhookCallbackOverrideApplied"])
        self.assertEqual(stored["metadata"]["phoneNumberDetailsRefreshStatus"], "refreshed")

    def test_whatsapp_connection_endpoint_keeps_international_approval_phone(self) -> None:
        self.server.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="11111",
            phone_number_id="22222",
            access_token="client-token",
            owner_wa_id="15551234567",
            connection_status="connected",
            metadata={"webhookSubscriptionStatus": "subscribed"},
        )

        with mock.patch(
            "packages.infrastructure.portal_auth.server.subscribe_whatsapp_business_account",
            return_value={"success": True},
        ) as mocked_subscribe:
            status, body = self._request(
                "POST",
                "/api/whatsapp/connection",
                {
                    "business_account_id": "11111",
                    "phone_number_id": "22222",
                    "owner_wa_id": "+972 50-732-2341",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["connection"]["ownerWaId"], "972507322341")
        mocked_subscribe.assert_called_once_with(access_token="client-token", business_account_id="11111")

    def test_whatsapp_history_includes_suggested_reply_for_inbound_message(self) -> None:
        webhook_request = urllib_request.Request(
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
                                        "contacts": [
                                            {
                                                "wa_id": "15559876543",
                                                "profile": {
                                                    "name": "Maya Cohen",
                                                },
                                            }
                                        ],
                                        "messages": [
                                            {
                                                "id": "wamid.inbound-price-1",
                                                "from": "15559876543",
                                                "timestamp": "1720861200",
                                                "type": "text",
                                                "text": {
                                                    "body": "How much does it cost?",
                                                },
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

        with urllib_request.urlopen(webhook_request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status

        self.assertEqual(status, 200)
        self.assertEqual(body["received"], 1)
        self.assertEqual(body["results"][0]["type"], "customer")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        messages = history["conversations"][0]["messages"]
        self.assertEqual(messages[0]["messageId"], "wamid.inbound-price-1")
        self.assertIn("couple of details", messages[0]["suggestedReply"])
        self.assertEqual(messages[0]["metadata"]["approvalStatus"], "pending")
        # The public /approval/<id> review page is gone; approvals are reviewed in
        # the signed-in portal, so no review URL is published on the message.
        self.assertNotIn("approvalReviewUrl", messages[0]["metadata"])

    def test_hebrew_owner_approval_without_reply_context_sends_pending_suggestion(self) -> None:
        customer_request = urllib_request.Request(
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
                                        "contacts": [
                                            {
                                                "wa_id": "15559876543",
                                                "profile": {
                                                    "name": "Maya Cohen",
                                                },
                                            }
                                        ],
                                        "messages": [
                                            {
                                                "id": "wamid.inbound-hebrew-owner-approval-1",
                                                "from": "15559876543",
                                                "timestamp": "1720861200",
                                                "type": "text",
                                                "text": {
                                                    "body": "Can you help tomorrow?",
                                                },
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

        with urllib_request.urlopen(customer_request, timeout=5) as response:
            customer_body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(customer_body["results"][0]["type"], "customer")

        owner_request = urllib_request.Request(
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
                                        "contacts": [
                                            {
                                                "wa_id": "15551234567",
                                                "profile": {
                                                    "name": "Owner",
                                                },
                                            }
                                        ],
                                        "messages": [
                                            {
                                                "id": "wamid.owner-hebrew-approval-1",
                                                "from": "15551234567",
                                                "timestamp": "1720861260",
                                                "type": "text",
                                                "text": {
                                                    "body": "מאשר",
                                                },
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

        with urllib_request.urlopen(owner_request, timeout=5) as response:
            owner_body = json.loads(response.read().decode("utf-8"))
            owner_status = response.status

        self.assertEqual(owner_status, 200)
        self.assertEqual(owner_body["received"], 1)
        self.assertEqual(owner_body["results"][0]["type"], "owner")
        self.assertEqual(owner_body["results"][0]["action"], "send_suggested")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        self.assertEqual(history["conversationCount"], 1)
        messages = history["conversations"][0]["messages"]
        self.assertEqual([message["direction"] for message in messages], ["inbound", "outbound"])
        self.assertNotIn("מאשר", [message["text"] for message in messages])

    def test_whatsapp_history_import_rejects_non_txt_files(self) -> None:
        status, body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "WhatsApp Chat with Maya Cohen.pdf",
                        "content": "13/01/2026, 09:00 - Maya Cohen: Hi",
                    }
                ],
            },
        )

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "unsupported_file_type")
        self.assertIn(".txt file exported from WhatsApp", body["message"])

    def test_whatsapp_history_import_saves_exported_chat(self) -> None:
        status, body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "WhatsApp Chat with Maya Cohen.txt",
                        "content": (
                            "13/01/2026, 09:00 - Maya Cohen: Hi, can you send the quote again?\n"
                            "13/01/2026, 09:05 - Owner: Sure, I will send it today.\n"
                            "13/01/2026, 09:06 - Maya Cohen: Thanks\n"
                        ),
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["messagesParsed"], 3)
        self.assertEqual(body["messagesSaved"], 3)
        self.assertEqual(body["lineCount"], 3)
        self.assertEqual(body["skippedLineCount"], 0)
        self.assertEqual(body["imports"][0]["conversationTitle"], "Maya Cohen")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        self.assertEqual(history["conversationCount"], 1)
        conversation = history["conversations"][0]
        self.assertEqual(conversation["senderName"], "Maya Cohen")
        self.assertEqual(conversation["metadata"]["source"], "manual_import")
        self.assertEqual(conversation["messageCount"], 3)
        messages = conversation["messages"]
        self.assertEqual([message["direction"] for message in messages], ["inbound", "outbound", "inbound"])
        self.assertEqual(messages[1]["metadata"]["importSenderName"], "Owner")

        second_status, second_body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "WhatsApp Chat with Maya Cohen.txt",
                        "content": (
                            "13/01/2026, 09:00 - Maya Cohen: Hi, can you send the quote again?\n"
                            "13/01/2026, 09:05 - Owner: Sure, I will send it today.\n"
                            "13/01/2026, 09:06 - Maya Cohen: Thanks\n"
                        ),
                    }
                ],
            },
        )

        self.assertEqual(second_status, 200)
        self.assertEqual(second_body["messagesSaved"], 3)
        self.assertEqual(second_body["messagesReplaced"], 3)
        self.assertEqual(second_body["duplicates"], 0)

    def test_whatsapp_history_import_reports_export_diagnostics(self) -> None:
        status, body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "WhatsApp Chat with Maya Cohen.txt",
                        "content": (
                            "2026/01/13 09:00 – Maya Cohen: Year-first dates work.\n"
                            "13.01.2026 09:05 — Owner: Dotted dates without commas work too.\n"
                            "13/01/2026, 09:06 - Messages and calls are end-to-end encrypted.\n"
                            "13/01/2026, 09:07 - Maya Cohen: This has\n"
                            "multiple lines.\n"
                        ),
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["messagesParsed"], 3)
        self.assertEqual(body["messagesSaved"], 3)
        self.assertEqual(body["lineCount"], 5)
        self.assertEqual(body["continuationLineCount"], 1)
        self.assertEqual(body["skippedLineCount"], 1)
        self.assertEqual(body["systemOrUnsupportedLineCount"], 1)
        self.assertEqual(body["unsupportedMessageLineCount"], 0)

    def test_whatsapp_history_import_prefers_non_future_ambiguous_date(self) -> None:
        parsed = parse_whatsapp_export_timestamp(
            "03/12/2026",
            "19:13",
            now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.startswith("2026-03-12T"))

    def test_whatsapp_history_import_rejects_tomorrow_for_ambiguous_date(self) -> None:
        parsed = parse_whatsapp_export_timestamp(
            "3/8/26",
            "07:35:20",
            now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.startswith("2026-03-08T"))

    def test_whatsapp_history_import_uses_export_wide_month_first_dates(self) -> None:
        messages = parse_whatsapp_export_messages(
            "\u202a[7/29/26, 18:17:00]\u202c \u202dדולב פלא\u202c: חחחח\n"
            "\u202a[8/2/26, 09:15:20]\u202c Nimrod Shai: Message from today\n"
        )

        self.assertEqual(len(messages), 2)
        self.assertTrue(messages[0]["messageAt"].startswith("2026-07-29T"))
        self.assertTrue(messages[1]["messageAt"].startswith("2026-08-02T"))

    def test_whatsapp_history_import_saves_month_first_august_messages_after_july(self) -> None:
        status, body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "WhatsApp Chat with Dolev.txt",
                        "content": (
                            "[7/29/26, 18:17:00] דולב פלא: חחחח\n"
                            "[8/2/26, 09:15:20] Nimrod Shai: Message from today\n"
                        ),
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["messagesParsed"], 2)
        self.assertEqual(body["messagesSaved"], 2)
        self.assertEqual(body["imports"][0]["dateOrder"], "month_first")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        conversation = history["conversations"][0]
        self.assertEqual(conversation["messageCount"], 2)
        self.assertTrue(conversation["lastMessageAt"].startswith("2026-08-02T"))
        self.assertTrue(conversation["messages"][-1]["messageAt"].startswith("2026-08-02T"))

    def test_whatsapp_history_import_infers_owner_for_generic_chat_file(self) -> None:
        status, body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "_chat.txt",
                        "content": (
                            "13/01/2026, 09:00 - Maya Cohen: Hi, can you send the quote again?\n"
                            "13/01/2026, 09:05 - Owner: Sure, I will send it today.\n"
                            "13/01/2026, 09:06 - Maya Cohen: Thanks\n"
                        ),
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["imports"][0]["conversationTitle"], "Maya Cohen")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        conversation = history["conversations"][0]
        self.assertEqual(conversation["senderName"], "Maya Cohen")
        self.assertEqual(conversation["messageCount"], 3)
        self.assertEqual(
            [message["direction"] for message in conversation["messages"]],
            ["inbound", "outbound", "inbound"],
        )
        self.assertEqual(conversation["messages"][1]["metadata"]["importSenderName"], "Owner")

    def test_whatsapp_history_delete_removes_saved_conversation(self) -> None:
        status, body = self._request(
            "POST",
            "/api/whatsapp/history/import",
            {
                "files": [
                    {
                        "name": "WhatsApp Chat with Maya Cohen.txt",
                        "content": (
                            "13/01/2026, 09:00 - Maya Cohen: Hi, can you send the quote again?\n"
                            "13/01/2026, 09:05 - Owner: Sure, I will send it today.\n"
                            "13/01/2026, 09:06 - Maya Cohen: Thanks\n"
                        ),
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        conversation_id = body["imports"][0]["conversationId"]
        delete_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history/conversations/{conversation_id}",
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(delete_request, timeout=5) as response:
            delete_body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(delete_body["conversationId"], conversation_id)
        self.assertEqual(delete_body["messagesDeleted"], 3)

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        self.assertEqual(history["conversationCount"], 0)
        self.assertEqual(history["messageCount"], 0)

    def test_approval_phone_message_to_connected_number_is_customer_history(self) -> None:
        webhook_request = urllib_request.Request(
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
                                        "contacts": [
                                            {
                                                "wa_id": "15551234567",
                                                "profile": {
                                                    "name": "Owner as tester",
                                                },
                                            }
                                        ],
                                        "messages": [
                                            {
                                                "id": "wamid.owner-as-customer-1",
                                                "from": "15551234567",
                                                "timestamp": "1720861200",
                                                "type": "text",
                                                "text": {
                                                    "body": "Can I book a test appointment?",
                                                },
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

        with urllib_request.urlopen(webhook_request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status

        self.assertEqual(status, 200)
        self.assertEqual(body["received"], 1)
        self.assertEqual(body["results"][0]["type"], "customer")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        self.assertEqual(history["conversationCount"], 1)
        messages = history["conversations"][0]["messages"]
        self.assertEqual(messages[0]["messageId"], "wamid.owner-as-customer-1")
        self.assertEqual(messages[0]["direction"], "inbound")
        self.assertEqual(messages[0]["text"], "Can I book a test appointment?")
        self.assertIn("suggestedReply", messages[0])

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

    def test_whatsapp_status_webhook_routes_platform_sender_status_by_approval_phone(self) -> None:
        self.server.database.update_whatsapp_connection_metadata(
            email="owner@example.com",
            metadata_updates={
                "lastOwnerNotificationStatus": "requested",
                "lastOwnerNotificationMessageId": "wamid.sample-platform-1",
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
                                            "phone_number_id": "1186653017865246",
                                        },
                                        "statuses": [
                                            {
                                                "id": "wamid.sample-platform-1",
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
        self.assertEqual(body["results"][0]["route"], "platform_owner_alert")

        connection = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(connection)
        metadata = connection["metadata"]
        self.assertEqual(metadata["lastOwnerNotificationStatus"], "delivered")
        self.assertEqual(metadata["lastOwnerNotificationMessageId"], "wamid.sample-platform-1")

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
                                            "phone_number_id": "1186653017865246",
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

    def test_owner_reply_to_platform_sender_routes_to_workspace_diagnostics(self) -> None:
        # An owner message to the platform sender that targets no approval is a
        # conversation with the agent now, so this test speaks to the agent:
        # the turn model and the WhatsApp send are mocked at their seams, and
        # what is asserted is the routing and the diagnostics either side of it.
        agent_env = mock.patch.dict(
            os.environ,
            {"WHATSAPP_ALLOW_MOCK_SEND": "1"},
            clear=False,
        )
        agent_env.start()
        self.addCleanup(agent_env.stop)
        secret_patch = mock.patch.object(
            self.server.store, "session_secret", b"manual-run-agent-secret"
        )
        secret_patch.start()
        self.addCleanup(secret_patch.stop)
        turn_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(
                output_text=json.dumps({"outcome": "message", "reply": "Glad it arrived."})
            ),
        )
        turn_patch.start()
        self.addCleanup(turn_patch.stop)

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
                                            "phone_number_id": "1186653017865246",
                                        },
                                        "contacts": [
                                            {
                                                "wa_id": "15551234567",
                                                "profile": {
                                                    "name": "Owner",
                                                },
                                            }
                                        ],
                                        "messages": [
                                            {
                                                "id": "wamid.owner-reply-platform-1",
                                                "from": "15551234567",
                                                "timestamp": "1720861200",
                                                "type": "text",
                                                "text": {
                                                    "body": "I got the sample",
                                                },
                                                "context": {
                                                    "id": "wamid.sample-platform-1",
                                                },
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
        self.assertEqual(body["received"], 1)
        self.assertEqual(body["results"][0]["type"], "owner")
        self.assertEqual(body["results"][0]["route"], "platform_owner_alert")

        self.assertEqual(body["results"][0]["action"], "agent_chat_reply")

        connection = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(connection)
        self.assertEqual(connection["metadata"]["lastWebhookEventType"], "agent_chat")
        self.assertEqual(connection["metadata"]["lastWebhookPhoneNumberId"], "1186653017865246")

        history_request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/history",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.session_token}",
            },
        )
        with urllib_request.urlopen(history_request, timeout=5) as response:
            history = json.loads(response.read().decode("utf-8"))

        self.assertTrue(history["ok"])
        self.assertEqual(history["conversationCount"], 0)
        diagnostic_titles = {item["title"] for item in history["diagnostics"]}
        self.assertNotIn("Latest webhook came from the owner phone", diagnostic_titles)
        self.assertNotIn("Latest webhook was an owner command", diagnostic_titles)
        self.assertNotIn("Latest approval alert failed", diagnostic_titles)

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

    def test_whatsapp_status_webhook_records_external_business_send_placeholder(self) -> None:
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
                                                "id": "wamid.external-1",
                                                "status": "sent",
                                                "recipient_id": "972507322341",
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
        self.assertEqual(body["results"][0]["type"], "status_outbound")
        self.assertTrue(body["results"][0]["saved"])

        messages = self.server.database.list_whatsapp_conversation_messages(
            "972507322341",
            email="owner@example.com",
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["direction"], "outbound")
        self.assertEqual(messages[0]["messageId"], "wamid.external-1")
        self.assertEqual(messages[0]["text"], "You replied here - but the WhatsApp API doesn't let us read the content")
        self.assertTrue(messages[0]["metadata"]["contentUnavailable"])
        self.assertTrue(messages[0]["metadata"]["outsideAssistyca"])
        self.assertEqual(messages[0]["metadata"]["status"], "sent")


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
            "packages.tools.whatsapp_reply_approval.server.urllib_request.urlopen",
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
        for path in ("/", "/portal/", "/portal/app.js", "/portal/styles.css", "/privacy.html"):
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


if __name__ == "__main__":
    unittest.main()
