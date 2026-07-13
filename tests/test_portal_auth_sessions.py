from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import SESSION_COOKIE_NAME
from packages.infrastructure.portal_auth.server import create_server


class PortalAuthSessionTests(unittest.TestCase):
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

    def _verify_otp_and_get_cookie(self) -> str:
        code, _ = self.server.store.issue_challenge("owner@example.com")
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({
                "email": "owner@example.com",
                "code": code,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            cookie_header = response.headers.get("Set-Cookie", "")
            self.assertIn(f"{SESSION_COOKIE_NAME}=", cookie_header)
            return cookie_header.split(";", 1)[0]

    def test_session_can_be_restored_from_cookie_without_authorization_header(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={"Cookie": cookie_value},
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["signedIn"])
        self.assertEqual(payload["email"], "owner@example.com")
        self.assertTrue(str(payload.get("token", "")).strip())

    def test_valid_cookie_wins_when_bearer_token_is_stale(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={
                "Authorization": "Bearer stale-token",
                "Cookie": cookie_value,
            },
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["signedIn"])
        self.assertEqual(payload["email"], "owner@example.com")


if __name__ == "__main__":
    unittest.main()
