from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import SESSION_COOKIE_NAME
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.whatsapp_api import WhatsAppConnectionError
from packages.infrastructure.whatsapp_api import exchange_embedded_signup_code
from packages.infrastructure.whatsapp_api import register_whatsapp_phone_number


class FakeGraphResponse:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")


class EmbeddedSignupGraphCallTests(unittest.TestCase):
    def test_code_exchange_posts_app_credentials_and_returns_the_business_token(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"access_token":"client-business-token","token_type":"bearer"}'),
        ) as urlopen:
            result = exchange_embedded_signup_code(
                code="one-time-code",
                app_id="app-1",
                app_secret="app-secret",
            )

        self.assertEqual(result["accessToken"], "client-business-token")
        request = urlopen.call_args_list[0].args[0]
        self.assertEqual(request.get_method(), "GET")
        url = urllib_parse.urlparse(request.full_url)
        self.assertEqual(url.path, "/v20.0/oauth/access_token")
        self.assertEqual(
            urllib_parse.parse_qs(url.query),
            {"client_id": ["app-1"], "client_secret": ["app-secret"], "code": ["one-time-code"]},
        )

    def test_code_exchange_rejects_a_response_with_no_token(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"token_type":"bearer"}'),
        ):
            with self.assertRaises(WhatsAppConnectionError):
                exchange_embedded_signup_code(code="c", app_id="a", app_secret="s")

    def test_code_exchange_surfaces_a_graph_error_object(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"error":{"message":"Code expired","type":"OAuthException"}}'),
        ):
            with self.assertRaises(WhatsAppConnectionError) as caught:
                exchange_embedded_signup_code(code="c", app_id="a", app_secret="s")

        self.assertIn("Code expired", str(caught.exception))

    def test_code_exchange_never_sends_a_blank_secret(self) -> None:
        with self.assertRaises(ValueError):
            exchange_embedded_signup_code(code="c", app_id="a", app_secret="")

    def test_phone_registration_requires_a_six_digit_pin(self) -> None:
        for bad_pin in ("", "12345", "1234567", "abcdef"):
            with self.subTest(pin=bad_pin):
                with self.assertRaises(ValueError):
                    register_whatsapp_phone_number(
                        access_token="t",
                        phone_number_id="1",
                        pin=bad_pin,
                    )

    def test_phone_registration_posts_the_pin_as_the_business_token(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"success":true}'),
        ) as urlopen:
            register_whatsapp_phone_number(
                access_token="client-business-token",
                phone_number_id="55555",
                pin="123456",
            )

        request = urlopen.call_args_list[0].args[0]
        self.assertEqual(request.full_url, "https://graph.facebook.com/v20.0/55555/register")
        self.assertEqual(request.get_header("Authorization"), "Bearer client-business-token")
        self.assertEqual(
            urllib_parse.parse_qs(request.data.decode("utf-8")),
            {"messaging_product": ["whatsapp"], "pin": ["123456"]},
        )


class EmbeddedSignupEndpointTests(unittest.TestCase):
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
        self.server.database.register_user("other@example.com")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _cookie(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            return response.headers.get("Set-Cookie", "").split(";", 1)[0]

    def _call(self, path: str, *, cookie: str = "", body: dict | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # --- configuration ---------------------------------------------------

    def test_config_reports_unconfigured_without_the_meta_settings(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("META_APP_ID", "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "WHATSAPP_APP_SECRET"):
                os.environ.pop(key, None)
            status, payload = self._call("/api/whatsapp/embedded-signup/config", cookie=self._cookie())

        self.assertEqual(status, 200)
        self.assertFalse(payload["configured"])

    def test_config_returns_only_the_public_identifiers(self) -> None:
        env = {
            "META_APP_ID": "app-1",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "config-1",
            "WHATSAPP_APP_SECRET": "the-app-secret",
        }
        with mock.patch.dict(os.environ, env):
            status, payload = self._call("/api/whatsapp/embedded-signup/config", cookie=self._cookie())

        self.assertEqual(status, 200)
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["appId"], "app-1")
        self.assertEqual(payload["configId"], "config-1")
        # The secret must never reach the browser, under any key.
        self.assertNotIn("the-app-secret", json.dumps(payload))

    def test_config_requires_a_signed_in_user(self) -> None:
        status, _ = self._call("/api/whatsapp/embedded-signup/config")
        self.assertEqual(status, 401)

    # --- completing a signup ---------------------------------------------

    def test_code_endpoint_requires_a_signed_in_user(self) -> None:
        status, _ = self._call(
            "/api/whatsapp/embedded-signup/code",
            body={"code": "c", "waba_id": "1", "phone_number_id": "2"},
        )
        self.assertEqual(status, 401)

    def test_code_endpoint_refuses_when_the_server_is_not_configured(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("META_APP_ID", "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "WHATSAPP_APP_SECRET"):
                os.environ.pop(key, None)
            status, payload = self._call(
                "/api/whatsapp/embedded-signup/code",
                cookie=self._cookie(),
                body={"code": "c", "waba_id": "1", "phone_number_id": "2"},
            )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "embedded_signup_not_configured")

    def test_code_endpoint_rejects_an_incomplete_signup_result(self) -> None:
        env = {
            "META_APP_ID": "app-1",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "config-1",
            "WHATSAPP_APP_SECRET": "app-secret",
        }
        for body in (
            {"waba_id": "1", "phone_number_id": "2"},
            {"code": "c", "phone_number_id": "2"},
            {"code": "c", "waba_id": "1"},
        ):
            with self.subTest(body=sorted(body)):
                with mock.patch.dict(os.environ, env):
                    status, payload = self._call(
                        "/api/whatsapp/embedded-signup/code",
                        cookie=self._cookie(),
                        body=body,
                    )
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"], "invalid_fields")

    def _complete_signup(
        self,
        cookie: str,
        *,
        owner_wa_id: str = "",
        onboarding_type: str = "",
    ) -> tuple[int, dict]:
        env = {
            "META_APP_ID": "app-1",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "config-1",
            "WHATSAPP_APP_SECRET": "app-secret",
            "PUBLIC_BASE_URL": "https://portal.example.com",
            "WHATSAPP_VERIFY_TOKEN": "verify-token",
        }
        body = {"code": "one-time-code", "waba_id": "11111", "phone_number_id": "55555"}
        if owner_wa_id:
            body["owner_wa_id"] = owner_wa_id
        if onboarding_type:
            body["onboarding_type"] = onboarding_type

        server_module = "packages.infrastructure.portal_auth.server"
        with mock.patch.dict(os.environ, env), \
             mock.patch(f"{server_module}.exchange_embedded_signup_code",
                        return_value={"accessToken": "client-business-token"}) as exchange, \
             mock.patch(f"{server_module}.register_whatsapp_phone_number",
                        return_value={"success": True}) as register, \
             mock.patch(f"{server_module}.test_whatsapp_connection",
                        return_value={"display_phone_number": "+1 555 0100", "verified_name": "Test Co"}), \
             mock.patch(f"{server_module}.subscribe_whatsapp_business_account",
                        return_value={"success": True}):
            status, payload = self._call(
                "/api/whatsapp/embedded-signup/code",
                cookie=cookie,
                body=body,
            )

        self.exchange_mock = exchange
        self.register_mock = register
        return status, payload

    def test_a_successful_signup_stores_the_connection_and_subscribes_the_webhook(self) -> None:
        cookie = self._cookie()
        status, payload = self._complete_signup(cookie, owner_wa_id="+15550111")

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["webhookSubscribed"])

        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertEqual(stored["businessAccountId"], "11111")
        self.assertEqual(stored["phoneNumberId"], "55555")
        self.assertEqual(stored["connectionStatus"], "connected")
        self.assertEqual(stored["metadata"]["onboarding"], "embedded_signup")

    def test_the_one_time_code_is_exchanged_server_side_and_the_token_never_returns_to_the_browser(self) -> None:
        cookie = self._cookie()
        _status, payload = self._complete_signup(cookie)

        self.exchange_mock.assert_called_once()
        self.assertEqual(self.exchange_mock.call_args.kwargs["code"], "one-time-code")
        self.assertEqual(self.exchange_mock.call_args.kwargs["app_secret"], "app-secret")
        # The customer's business token is the whole point of doing this server
        # side; it must not appear anywhere in the response.
        self.assertNotIn("client-business-token", json.dumps(payload))

    def test_registration_uses_a_six_digit_pin_kept_for_later_re_registration(self) -> None:
        cookie = self._cookie()
        self._complete_signup(cookie)

        pin = self.register_mock.call_args.kwargs["pin"]
        self.assertTrue(pin.isdigit() and len(pin) == 6, pin)
        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertEqual(stored["metadata"]["registrationPin"], pin)

    def test_a_coexistence_signup_never_tries_to_register_the_number(self) -> None:
        """The owner keeps WhatsApp on their phone.

        Registering would move the number onto the API and take it off the
        handset -- the exact outcome coexistence exists to avoid.
        """
        cookie = self._cookie()
        status, payload = self._complete_signup(cookie, onboarding_type="coexistence")

        self.assertEqual(status, 200, payload)
        self.register_mock.assert_not_called()

    def test_a_coexistence_signup_is_recorded_as_such(self) -> None:
        cookie = self._cookie()
        self._complete_signup(cookie, onboarding_type="coexistence")

        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertEqual(stored["metadata"]["onboarding"], "coexistence")
        self.assertEqual(stored["connectionStatus"], "connected")

    def test_a_number_that_refuses_registration_still_connects(self) -> None:
        """Numbers already on the WhatsApp Business app reject /register."""
        cookie = self._cookie()
        env = {
            "META_APP_ID": "app-1",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "config-1",
            "WHATSAPP_APP_SECRET": "app-secret",
            "PUBLIC_BASE_URL": "https://portal.example.com",
            "WHATSAPP_VERIFY_TOKEN": "verify-token",
        }
        server_module = "packages.infrastructure.portal_auth.server"
        with mock.patch.dict(os.environ, env), \
             mock.patch(f"{server_module}.exchange_embedded_signup_code",
                        return_value={"accessToken": "client-business-token"}), \
             mock.patch(f"{server_module}.register_whatsapp_phone_number",
                        side_effect=WhatsAppConnectionError("Already registered")), \
             mock.patch(f"{server_module}.test_whatsapp_connection",
                        return_value={"display_phone_number": "+1 555 0100", "verified_name": "Test Co"}), \
             mock.patch(f"{server_module}.subscribe_whatsapp_business_account",
                        return_value={"success": True}):
            status, payload = self._call(
                "/api/whatsapp/embedded-signup/code",
                cookie=cookie,
                body={"code": "c", "waba_id": "11111", "phone_number_id": "55555"},
            )

        self.assertEqual(status, 200, payload)
        stored = self.server.database.get_whatsapp_connection("owner@example.com")
        self.assertEqual(stored["connectionStatus"], "connected")
        self.assertIn("Already registered", stored["metadata"]["registrationNote"])

    def test_a_failed_code_exchange_saves_nothing(self) -> None:
        cookie = self._cookie()
        env = {
            "META_APP_ID": "app-1",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "config-1",
            "WHATSAPP_APP_SECRET": "app-secret",
        }
        server_module = "packages.infrastructure.portal_auth.server"
        with mock.patch.dict(os.environ, env), \
             mock.patch(f"{server_module}.exchange_embedded_signup_code",
                        side_effect=WhatsAppConnectionError("Code expired")):
            status, payload = self._call(
                "/api/whatsapp/embedded-signup/code",
                cookie=cookie,
                body={"code": "stale", "waba_id": "11111", "phone_number_id": "55555"},
            )

        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "whatsapp_code_exchange_failed")
        self.assertIsNone(self.server.database.get_whatsapp_connection("owner@example.com"))

    def test_one_users_signup_does_not_touch_another_users_connection(self) -> None:
        self._complete_signup(self._cookie("owner@example.com"))

        self.assertIsNotNone(self.server.database.get_whatsapp_connection("owner@example.com"))
        self.assertIsNone(self.server.database.get_whatsapp_connection("other@example.com"))


if __name__ == "__main__":
    unittest.main()
