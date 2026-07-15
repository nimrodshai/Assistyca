from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server


class PortalContactApiTests(unittest.TestCase):
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

    def _post_contact(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib_request.Request(
            f"{self.base_url}/api/contact",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib_error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def test_contact_requires_name_contact_channel_and_message(self) -> None:
        status, payload = self._post_contact({
            "name": "",
            "email": "",
            "phone": "",
            "message": "Hi",
        })

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_contact_request")
        self.assertIn("name", payload["fieldErrors"])
        self.assertIn("contact", payload["fieldErrors"])
        self.assertIn("message", payload["fieldErrors"])

    def test_missing_contact_chat_id_returns_service_unavailable(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_CONTACT_CHAT_ID": "", "TELEGRAM_CHAT_ID": ""}):
            with patch("packages.infrastructure.portal_auth.server.send_telegram_notification") as send_telegram:
                status, payload = self._post_contact({
                    "name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "message": "I need help automating weekly client follow-ups.",
                })

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "telegram_contact_not_configured")
        send_telegram.assert_not_called()

    def test_honeypot_submission_is_accepted_without_sending(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_CONTACT_CHAT_ID": "123456789"}):
            with patch("packages.infrastructure.portal_auth.server.send_telegram_notification") as send_telegram:
                status, payload = self._post_contact({
                    "name": "Bot",
                    "email": "bot@example.com",
                    "companyWebsite": "https://spam.example",
                    "message": "This should not be delivered.",
                })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        send_telegram.assert_not_called()

    def test_valid_contact_request_sends_telegram_message(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_CONTACT_CHAT_ID": "123456789"}):
            with patch("packages.infrastructure.portal_auth.server.send_telegram_notification") as send_telegram:
                status, payload = self._post_contact({
                    "name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "phone": "+44 20 0000 0000",
                    "business": "Analytical Engines Ltd",
                    "message": "I need help automating weekly client follow-ups.",
                    "page": "http://127.0.0.1/about/index.html#home",
                })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        send_telegram.assert_called_once()
        call_kwargs = send_telegram.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], "123456789")
        self.assertIn("New Assistyca contact request", call_kwargs["text"])
        self.assertIn("Ada Lovelace", call_kwargs["text"])
        self.assertIn("ada@example.com", call_kwargs["text"])
        self.assertIn("Analytical Engines Ltd", call_kwargs["text"])


if __name__ == "__main__":
    unittest.main()
