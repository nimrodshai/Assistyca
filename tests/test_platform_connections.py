from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.credential_vault import CredentialVault
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import SESSION_COOKIE_NAME
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase


class PlatformConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.db_path = Path(self.temp_dir.name) / "portal.db"
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=self.db_path),
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

    def _cookie_for(self, server, base_url: str, email: str = "owner@example.com") -> str:
        code, _ = server.store.issue_challenge(email)
        request = urllib_request.Request(
            f"{base_url}/api/auth/otp/verify",
            data=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            return response.headers.get("Set-Cookie", "").split(";", 1)[0]

    def _cookie(self) -> str:
        return self._cookie_for(self.server, self.base_url)

    def test_platform_connection_list_requires_authentication(self) -> None:
        request = urllib_request.Request(f"{self.base_url}/api/platform-connections")
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request)
        self.assertEqual(context.exception.code, 401)

    def test_platform_connection_list_reports_storage_availability(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/platform-connections",
            headers={"Cookie": self._cookie()},
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["credentialStorageAvailable"])
        self.assertIn("no token was saved", payload["credentialStorageMessage"])
        self.assertEqual(payload["connections"], [])

    def test_platform_connection_write_fails_closed_without_encryption_key(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/platform-connections",
            data=json.dumps({
                "platform": "slack",
                "authType": "bot_token",
                "credential": "xoxb-test-secret-value",
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": self._cookie(),
            },
            method="POST",
        )
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request)
        body = context.exception.read().decode("utf-8")
        self.assertEqual(context.exception.code, 503)
        self.assertIn("no token was saved", body)
        self.assertNotIn("xoxb-test-secret-value", body)

    def test_calendar_connection_appears_after_encrypted_save(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "vault-backed.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=db_path, credential_encryption_key=key),
        )
        server.database.register_user("owner@example.com")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cookie = self._cookie_for(server, base_url)
            request = urllib_request.Request(
                f"{base_url}/api/platform-connections",
                data=json.dumps({
                    "platform": "calendar",
                    "authType": "api_token",
                    "credential": "calendar-secret-value-that-stays-server-side",
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie,
                },
                method="POST",
            )
            with urllib_request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

            body = json.dumps(payload)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["credentialStorageAvailable"])
            self.assertEqual(payload["connection"]["platform"], "calendar")
            self.assertEqual(payload["connection"]["authType"], "api_token")
            self.assertIn("secretHint", payload["connection"])
            self.assertNotIn("calendar-secret-value-that-stays-server-side", body)

            list_request = urllib_request.Request(
                f"{base_url}/api/platform-connections",
                headers={"Cookie": cookie},
            )
            with urllib_request.urlopen(list_request) as response:
                list_payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(list_payload["credentialStorageAvailable"])
            self.assertEqual(
                [connection["platform"] for connection in list_payload["connections"]],
                ["calendar"],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_agent_turn_rejects_a_pasted_secret_before_model_call(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/turn",
            data=json.dumps({
                "userMessage": "api_key=xoxb-test-secret-value-that-must-not-reach-the-model",
                "conversation": [],
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": self._cookie(),
            },
            method="POST",
        )
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request)
        body = context.exception.read().decode("utf-8")
        self.assertEqual(context.exception.code, 400)
        self.assertIn("secret_in_chat", body)
        self.assertNotIn("xoxb-test-secret-value", body)

    def test_database_connection_serializer_never_returns_ciphertext(self) -> None:
        database = PortalDatabase(self.db_path)
        database.register_user("database@example.com")
        saved = database.save_platform_connection(
            "database@example.com",
            platform="slack",
            auth_type="bot_token",
            secret_ciphertext="v1:nonce:encrypted-value",
            secret_hint="••••alue",
        )

        self.assertNotIn("secretCiphertext", saved)
        self.assertEqual(saved["secretHint"], "••••alue")
        with sqlite3.connect(str(self.db_path)) as connection:
            raw = connection.execute(
                "SELECT secret_ciphertext FROM platform_connections WHERE id = ?",
                (saved["id"],),
            ).fetchone()[0]
        self.assertEqual(raw, "v1:nonce:encrypted-value")

    def test_legacy_whatsapp_token_uses_vault_when_attached(self) -> None:
        class FakeVault:
            key_version = "7"

            @staticmethod
            def encrypt(value: str) -> str:
                return f"enc:{value}"

            @staticmethod
            def decrypt(value: str) -> str:
                return value.removeprefix("enc:")

            @staticmethod
            def fingerprint(_value: str) -> str:
                return "fingerprint"

        database = PortalDatabase(self.db_path)
        database.register_user("whatsapp@example.com")
        database.set_credential_vault(FakeVault())
        saved = database.save_whatsapp_connection(
            "whatsapp@example.com",
            business_account_id="123",
            phone_number_id="456",
            access_token="legacy-secret",
            owner_wa_id="972501234567",
        )
        self.assertEqual(saved["accessToken"], "legacy-secret")
        with sqlite3.connect(str(self.db_path)) as connection:
            raw = connection.execute(
                """
                SELECT w.access_token, w.access_token_ciphertext
                FROM whatsapp_connections AS w
                INNER JOIN users AS u ON u.id = w.user_id
                WHERE u.email = ?
                """,
                ("whatsapp@example.com",),
            ).fetchone()
        self.assertEqual(raw, ("", "enc:legacy-secret"))

    def test_credential_vault_round_trip_when_cryptography_is_installed(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        vault = CredentialVault(key)
        encrypted = vault.encrypt("xoxb-test-secret-value")
        self.assertNotIn("xoxb-test-secret-value", encrypted)
        self.assertEqual(vault.decrypt(encrypted), "xoxb-test-secret-value")


if __name__ == "__main__":
    unittest.main()
