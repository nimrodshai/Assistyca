from __future__ import annotations

import io
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
from packages.infrastructure.whatsapp_portal_service import PortalWhatsAppService
from packages.infrastructure.whatsapp_portal_service import build_portal_runtime_config
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID
from packages.tools.whatsapp_reply_approval.server import BackendStore
from packages.tools.whatsapp_reply_approval.server import OWNER_REVIEW_ACTION_TEXT
from packages.tools.whatsapp_reply_approval.server import OWNER_REVIEW_INTRO_TEXT
from packages.tools.whatsapp_reply_approval.server import extract_inbound_events
from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message


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

    def _build_service(self, *, templates: dict[str, object] | None = None) -> PortalWhatsAppService:
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
        return PortalWhatsAppService(config, BackendStore(self.data_path))

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

    def test_owner_notification_uses_template_when_configured(self) -> None:
        service = self._build_service(
            templates={
                "owner_notification": {
                    "name": "new_reply_for_review",
                    "language": "en",
                    "button_index": "0",
                    "button_type": "url",
                    "url_mode": "path",
                },
            },
        )
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
            return_value="wamid.template-2",
        ) as mocked_send:
            message_id = service.notify_owner_about_approval(approval)

        self.assertEqual(message_id, "wamid.template-2")
        mocked_send.assert_called_once()
        self.assertEqual(mocked_send.call_args.kwargs["phone_number_id"], "1186653017865246")
        self.assertIsNone(mocked_send.call_args.kwargs["message_text"])
        self.assertIsNone(mocked_send.call_args.kwargs["interactive"])
        self.assertEqual(
            mocked_send.call_args.kwargs["template"],
            {
                "name": "new_reply_for_review",
                "language": {
                    "code": "en",
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {
                                "type": "text",
                                "text": "John Doe",
                            }
                        ],
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [
                            {
                                "type": "text",
                                "text": f"approval/{approval['approval_id']}",
                            }
                        ],
                    },
                ],
            },
        )

    def test_owner_notification_uses_quick_reply_template_when_configured(self) -> None:
        service = self._build_service(
            templates={
                "owner_notification": {
                    "name": "whatsapp_reply_assistant",
                    "language": "en",
                    "button_index": "0",
                    "button_type": "quick_reply",
                    "button_action": "generate",
                },
            },
        )
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
            return_value="wamid.template-quick-reply",
        ) as mocked_send:
            message_id = service.notify_owner_about_approval(approval)

        self.assertEqual(message_id, "wamid.template-quick-reply")
        self.assertEqual(
            mocked_send.call_args.kwargs["template"]["components"][1],
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": "0",
                "parameters": [
                    {
                        "type": "payload",
                        "payload": f"approval:{approval['approval_id']}:generate",
                    }
                ],
            },
        )

    def test_owner_notification_uses_first_then_repeat_reply_assistant_templates(self) -> None:
        service = self._build_service(
            templates={
                "owner_notification": {
                    "first_name": "whatsapp_reply_assistant_1",
                    "repeat_name": "whatsapp_reply_assistant_2",
                    "language": "en",
                    "button_type": "quick_reply",
                    "button_action": "generate",
                    "disable_button_index": "1",
                    "disable_button_action": "disable_contact",
                },
            },
        )
        first_approval = service.store.record_inbound_message(
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
            return_value="wamid.template-first",
        ) as mocked_first_send:
            service.notify_owner_about_approval(first_approval)

        first_template = mocked_first_send.call_args.kwargs["template"]
        self.assertEqual(first_template["name"], "whatsapp_reply_assistant_1")
        self.assertEqual(len(first_template["components"]), 3)
        self.assertEqual(
            first_template["components"][1]["parameters"][0]["payload"],
            f"approval:{first_approval['approval_id']}:generate",
        )
        self.assertEqual(first_template["components"][2]["index"], "1")
        self.assertEqual(
            first_template["components"][2]["parameters"][0]["payload"],
            f"approval:{first_approval['approval_id']}:disable_contact",
        )

        repeat_approval = service.store.record_inbound_message(
            thread_id="15551230000",
            sender_name="John Doe",
            sender_wa_id="15551230000",
            message_text="What about Friday?",
            source_message_id="wamid.inbound-2",
            message_type="text",
            raw_payload={"object": "whatsapp_business_account"},
            config=service.config,
        )

        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.template-repeat",
        ) as mocked_repeat_send:
            service.notify_owner_about_approval(repeat_approval)

        repeat_template = mocked_repeat_send.call_args.kwargs["template"]
        self.assertEqual(repeat_template["name"], "whatsapp_reply_assistant_2")
        self.assertEqual(len(repeat_template["components"]), 2)
        self.assertEqual(
            repeat_template["components"][1]["parameters"][0]["payload"],
            f"approval:{repeat_approval['approval_id']}:generate",
        )

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
        self.assertIn("assistyca sender access token", str(body["message"]).lower())

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
        with mock.patch.dict(os.environ, {"WHATSAPP_ACCESS_TOKEN": ""}, clear=False):
            with mock.patch(
                "packages.infrastructure.portal_auth.server.test_whatsapp_connection",
                return_value={
                    "phone_number_id": "22222",
                    "display_phone_number": "+1 555 123 4567",
                    "verified_name": "Client Co",
                },
            ) as mocked_test:
                with mock.patch(
                    "packages.infrastructure.portal_auth.server.list_whatsapp_business_phone_numbers",
                    return_value=[
                        {
                            "id": "22222",
                            "display_phone_number": "+1 555 123 4567",
                            "verified_name": "Client Co",
                        }
                    ],
                ) as mocked_list_numbers:
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
                                "access_token": "client-token",
                                "owner_wa_id": "15551234567",
                            },
                        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        mocked_test.assert_called_once_with(access_token="client-token", phone_number_id="22222")
        mocked_list_numbers.assert_called_once_with(access_token="client-token", business_account_id="11111")
        mocked_subscribe.assert_called_once_with(access_token="client-token", business_account_id="11111")
        self.assertNotIn("accessToken", body["connection"])
        self.assertTrue(body["connection"]["accessTokenConfigured"])
        self.assertTrue(body["connection"]["workspaceAccessTokenConfigured"])
        self.assertEqual(body["connection"]["businessAccountId"], "11111")
        self.assertEqual(body["connection"]["phoneNumberId"], "22222")

        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["accessToken"], "client-token")
        self.assertEqual(stored["metadata"]["webhookSubscriptionStatus"], "subscribed")

    def test_whatsapp_connection_endpoint_saves_approval_phone_without_retesting_existing_connection(self) -> None:
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
            side_effect=AssertionError("Meta connection should not be retested"),
        ) as mocked_test:
            with mock.patch(
                "packages.infrastructure.portal_auth.server.list_whatsapp_business_phone_numbers",
                side_effect=AssertionError("WABA phone numbers should not be listed"),
            ) as mocked_list_numbers:
                with mock.patch(
                    "packages.infrastructure.portal_auth.server.subscribe_whatsapp_business_account",
                    side_effect=AssertionError("Webhook subscription should not be retried"),
                ) as mocked_subscribe:
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
        self.assertIn("Approval phone saved", body["message"])
        self.assertEqual(body["connection"]["ownerWaId"], "972507322341")
        self.assertEqual(body["connection"]["displayPhoneNumber"], "+1 555 123 4567")
        mocked_test.assert_not_called()
        mocked_list_numbers.assert_not_called()
        mocked_subscribe.assert_not_called()

        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["ownerWaId"], "972507322341")
        self.assertEqual(stored["accessToken"], "client-token")

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
        self.assertTrue(messages[0]["metadata"]["approvalReviewUrl"].endswith(
            f"/approval/{messages[0]['approvalId']}"
        ))

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
        self.assertEqual(second_body["messagesSaved"], 0)
        self.assertEqual(second_body["duplicates"], 3)

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

    def test_owner_reply_to_platform_sender_routes_to_workspace_diagnostics(self) -> None:
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

        connection = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertIsNotNone(connection)
        self.assertEqual(connection["metadata"]["lastWebhookEventType"], "owner_command")
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
        self.assertEqual(history["diagnostics"][0]["title"], "Latest webhook came from the owner phone")

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


if __name__ == "__main__":
    unittest.main()
