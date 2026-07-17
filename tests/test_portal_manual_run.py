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

    def tearDown(self) -> None:
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

    def test_build_portal_runtime_config_reads_owner_notification_template_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_NAME": "new_reply_for_review",
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
                "name": "new_reply_for_review",
                "language": "en",
                "button_index": "0",
                "url_mode": "path",
            },
        )

    def test_owner_notification_uses_template_when_configured(self) -> None:
        service = self._build_service(
            templates={
                "owner_notification": {
                    "name": "new_reply_for_review",
                    "language": "en",
                    "button_index": "0",
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
        self.assertIn("working backend access token", str(body["message"]).lower())

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


if __name__ == "__main__":
    unittest.main()
