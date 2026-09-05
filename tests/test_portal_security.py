from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server


class PortalSecurityTests(unittest.TestCase):
    """The doors that must stay shut: webhook verification, cross-site writes, oversized bodies."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="test-session-secret",
            ),
        )
        self.server.database.register_user("owner@example.com")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib_error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def _cookie(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        status, _, headers = self._request(
            "/api/auth/otp/verify",
            method="POST",
            body=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    # --- WhatsApp webhook verification ------------------------------------

    def test_webhook_verification_answers_the_challenge_with_the_right_token(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "verify-token"}):
            status, body, _ = self._request(
                "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=12345",
            )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"12345")

    def test_webhook_verification_rejects_the_wrong_token(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "verify-token"}):
            status, _, _ = self._request(
                "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=guess&hub.challenge=12345",
            )

        self.assertEqual(status, 403)

    def test_webhook_verification_fails_closed_without_a_configured_token(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHATSAPP_VERIFY_TOKEN", None)
            status, body, _ = self._request(
                "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=&hub.challenge=12345",
            )

        self.assertEqual(status, 503)
        self.assertNotIn(b"12345", body)


if __name__ == "__main__":
    unittest.main()
