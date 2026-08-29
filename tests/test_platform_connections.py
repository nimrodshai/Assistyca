from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from unittest import mock

from packages.infrastructure.credential_vault import CredentialVault
from packages.infrastructure.portal_auth.server import GOOGLE_CALENDAR_LIST_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_CALENDAR_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_DRIVE_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_GMAIL_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_REVOKE_URL
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_TOKEN_URL
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import SESSION_COOKIE_NAME
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase

# Connecting Calendar asks for two grants: reading events, and seeing which
# calendars the account holds. Only the first decides whether the permission
# connected, which is why the token responses below still grant it alone.
GOOGLE_CALENDAR_REQUESTED_SCOPE_TEXT = f"{GOOGLE_CALENDAR_OAUTH_SCOPE} {GOOGLE_CALENDAR_LIST_OAUTH_SCOPE}"


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _NoRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


# Patching urlopen on the server module patches urllib.request globally, so a
# blanket patch also swallows these tests' own requests to the portal under
# test. Only the provider token and revoke endpoints are stubbed; everything
# else goes to the real opener.
_PROVIDER_HOSTS = (
    "oauth2.googleapis.com",
    "accounts.google.com",
    "login.microsoftonline.com",
    "gmail.googleapis.com",
    "www.googleapis.com",
    "graph.microsoft.com",
)


def _provider_endpoint_patch(*responders, target="packages.infrastructure.portal_auth.server.urllib_request.urlopen"):
    """Route provider calls to the given responders, portal calls to the network.

    Every responder is tried in turn; the first one that does not raise
    ``_NotMine`` answers. Nesting two blanket patches would not work: they
    target the same global ``urlopen``, so the inner one would swallow the
    outer one's calls.
    """

    real_urlopen = urllib_request.urlopen

    def routed(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        if any(host in url for host in _PROVIDER_HOSTS):
            for responder in responders:
                try:
                    return responder(request, timeout=timeout)
                except _NotMine:
                    continue
            raise AssertionError(f"no responder handled {url}")
        return real_urlopen(request, timeout=timeout, **kwargs)

    return mock.patch(target, side_effect=routed)


class _NotMine(Exception):
    """Raised by a responder that does not handle this request's host."""


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

    def test_platform_connection_delete_removes_only_the_authenticated_connection(self) -> None:
        saved = self.server.database.save_platform_connection(
            "owner@example.com",
            platform="slack",
            auth_type="bot_token",
            secret_ciphertext="ciphertext-that-stays-server-side",
            secret_hint="••••side",
        )
        self.server.database.register_user("other@example.com")
        other = self.server.database.save_platform_connection(
            "other@example.com",
            platform="slack",
            auth_type="bot_token",
            secret_ciphertext="other-ciphertext",
            secret_hint="••••text",
        )

        request = urllib_request.Request(
            f"{self.base_url}/api/platform-connections/{urllib_parse.quote(saved['id'])}",
            headers={"Cookie": self._cookie()},
            method="DELETE",
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertIn("disconnected", payload["message"].lower())
        self.assertNotIn("ciphertext-that-stays-server-side", json.dumps(payload))
        self.assertEqual(self.server.database.list_platform_connections("owner@example.com"), [])
        self.assertEqual(self.server.database.list_platform_connections("other@example.com")[0]["id"], other["id"])

    def test_google_calendar_delete_revokes_refresh_token_before_local_removal(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "oauth-delete.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=db_path, credential_encryption_key=key),
        )
        server.database.register_user("owner@example.com")
        encrypted = server.credential_vault.encrypt(json.dumps({
            "type": "google_calendar_refresh_token",
            "provider": "google_calendar",
            "refreshToken": "refresh-token-to-revoke",
        }))
        saved = server.database.save_platform_connection(
            "owner@example.com",
            platform="calendar",
            auth_type="oauth",
            secret_ciphertext=encrypted,
            secret_hint="Google OAuth",
            metadata={"validationStatus": "verified"},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cookie = self._cookie_for(server, base_url)

            def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                self.assertEqual(timeout, 20)
                self.assertEqual(request.full_url, GOOGLE_OAUTH_REVOKE_URL)
                self.assertEqual(request.get_method(), "POST")
                fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
                self.assertEqual(fields["token"], ["refresh-token-to-revoke"])
                return _JsonResponse({})

            request = urllib_request.Request(
                f"{base_url}/api/platform-connections/{urllib_parse.quote(saved['id'])}",
                headers={"Cookie": cookie},
                method="DELETE",
            )
            with _provider_endpoint_patch(fake_urlopen):
                with urllib_request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["ok"])
            self.assertTrue(payload["providerRevoked"])
            self.assertNotIn("refresh-token-to-revoke", json.dumps(payload))
            self.assertEqual(server.database.list_platform_connections("owner@example.com"), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_whatsapp_connection_delete_removes_saved_credentials(self) -> None:
        self.server.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="waba-123",
            phone_number_id="phone-456",
            access_token="whatsapp-secret-that-stays-server-side",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/connection",
            headers={"Cookie": self._cookie()},
            method="DELETE",
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertIn("disconnected", payload["message"].lower())
        self.assertNotIn("whatsapp-secret-that-stays-server-side", json.dumps(payload))
        self.assertIsNone(self.server.database.get_whatsapp_connection("owner@example.com"))

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

    def test_calendar_oauth_start_reports_missing_server_config(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/oauth/google/calendar/start",
            headers={"Cookie": self._cookie()},
        )
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request, timeout=5)

        body = json.loads(context.exception.read().decode("utf-8"))
        self.assertEqual(context.exception.code, 503)
        self.assertEqual(body["error"], "google_oauth_not_configured")
        self.assertIn("/api/oauth/google/calendar/callback", body["redirectUri"])
        popup_redirect = urllib_parse.urlparse(body["popupRedirectUri"])
        self.assertIn(popup_redirect.scheme, {"http", "https"})
        self.assertTrue(popup_redirect.netloc)
        self.assertEqual(popup_redirect.path, "")
        self.assertEqual(body["scope"], GOOGLE_CALENDAR_REQUESTED_SCOPE_TEXT)

    def test_calendar_oauth_start_returns_google_authorization_url(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "oauth-start.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=db_path,
                credential_encryption_key=key,
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
                google_oauth_redirect_uri="https://assistyca.com/api/oauth/google/calendar/callback",
            ),
        )
        server.database.register_user("owner@example.com")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = urllib_request.Request(
                f"{base_url}/api/oauth/google/calendar/start",
                headers={"Cookie": self._cookie_for(server, base_url)},
            )
            with urllib_request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["clientId"], "google-client-id.apps.googleusercontent.com")
            self.assertEqual(payload["mode"], "google_identity_services")
            popup_redirect = urllib_parse.urlparse(payload["popupRedirectUri"])
            self.assertIn(popup_redirect.scheme, {"http", "https"})
            self.assertTrue(popup_redirect.netloc)
            self.assertEqual(popup_redirect.path, "")
            auth_url = urllib_parse.urlparse(payload["authUrl"])
            params = urllib_parse.parse_qs(auth_url.query)
            self.assertEqual(auth_url.netloc, "accounts.google.com")
            self.assertEqual(params["client_id"], ["google-client-id.apps.googleusercontent.com"])
            self.assertEqual(params["redirect_uri"], ["https://assistyca.com/api/oauth/google/calendar/callback"])
            self.assertEqual(params["scope"], [GOOGLE_CALENDAR_REQUESTED_SCOPE_TEXT])
            self.assertEqual(params["access_type"], ["offline"])
            self.assertEqual(params["prompt"], ["consent"])
            self.assertTrue(params["state"][0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_calendar_oauth_code_post_saves_encrypted_refresh_token(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "oauth-code.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=db_path,
                credential_encryption_key=key,
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
            ),
        )
        server.database.register_user("owner@example.com")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cookie = self._cookie_for(server, base_url)

            def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                self.assertEqual(timeout, 20)
                self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
                fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
                self.assertEqual(fields["grant_type"], ["authorization_code"])
                self.assertEqual(fields["code"], ["popup-calendar-code"])
                self.assertEqual(fields["redirect_uri"], [base_url])
                return _JsonResponse({
                    "access_token": "popup-google-access-token",
                    "refresh_token": "popup-refresh-token-that-stays-encrypted",
                    "scope": GOOGLE_CALENDAR_OAUTH_SCOPE,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                })

            request = urllib_request.Request(
                f"{base_url}/api/oauth/google/calendar/code",
                data=json.dumps({"code": "popup-calendar-code"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie,
                    "X-Requested-With": "XMLHttpRequest",
                    "X-Forwarded-Proto": "http",
                },
                method="POST",
            )
            opener = urllib_request.build_opener()
            with _provider_endpoint_patch(fake_urlopen):
                with mock.patch(
                    "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
                    return_value={"eventCount": 0, "message": "", "summary": ""},
                ) as run:
                    with opener.open(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["connection"]["platform"], "calendar")
            self.assertEqual(payload["connection"]["authType"], "oauth")
            self.assertNotIn("popup-refresh-token-that-stays-encrypted", json.dumps(payload))
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], "popup-google-access-token")

            with sqlite3.connect(str(db_path)) as database:
                raw = database.execute("SELECT secret_ciphertext FROM platform_connections").fetchone()[0]
            decrypted = server.credential_vault.decrypt(raw)  # type: ignore[union-attr]
            self.assertIn("popup-refresh-token-that-stays-encrypted", decrypted)
            self.assertNotIn("popup-google-access-token", decrypted)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_gmail_oauth_code_post_saves_verified_email_connection(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "oauth-gmail-code.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=db_path,
                credential_encryption_key=key,
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
            ),
        )
        server.database.register_user("owner@example.com")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cookie = self._cookie_for(server, base_url)

            def fake_token_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                self.assertEqual(timeout, 20)
                self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
                fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
                self.assertEqual(fields["grant_type"], ["authorization_code"])
                self.assertEqual(fields["code"], ["popup-gmail-code"])
                self.assertEqual(fields["redirect_uri"], [base_url])
                return _JsonResponse({
                    "access_token": "popup-google-gmail-access-token",
                    "refresh_token": "popup-gmail-refresh-token-that-stays-encrypted",
                    "scope": GOOGLE_GMAIL_OAUTH_SCOPE,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                })

            def fake_gmail_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                if "gmail.googleapis.com" not in request.full_url:
                    raise _NotMine
                self.assertEqual(timeout, 20)
                self.assertEqual(request.get_header("Authorization"), "Bearer popup-google-gmail-access-token")
                # Connecting also reads the mailbox's own address, which is how
                # a user tells two connected Gmail accounts apart.
                if request.full_url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/profile"):
                    return _JsonResponse({"emailAddress": "Popup.Owner@Gmail.com"})
                self.assertTrue(request.full_url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"))
                return _JsonResponse({"messages": [], "resultSizeEstimate": 0})

            request = urllib_request.Request(
                f"{base_url}/api/oauth/google/calendar/code",
                data=json.dumps({"code": "popup-gmail-code", "scopes": ["gmail"]}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie,
                    "X-Requested-With": "XMLHttpRequest",
                    "X-Forwarded-Proto": "http",
                },
                method="POST",
            )
            opener = urllib_request.build_opener()
            with _provider_endpoint_patch(fake_gmail_urlopen, fake_token_urlopen):
                if True:
                    with opener.open(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["ok"])
            self.assertIn("Gmail connected", payload["message"])
            self.assertEqual(payload["connection"]["platform"], "email")
            self.assertEqual(payload["connection"]["authType"], "oauth")
            self.assertEqual(payload["connection"]["connectionStatus"], "connected")
            self.assertEqual(payload["connection"]["metadata"]["provider"], "google_gmail")
            self.assertEqual(payload["connection"]["metadata"]["scope"], GOOGLE_GMAIL_OAUTH_SCOPE)
            # The address is stored lowercased so it can key the connection.
            self.assertEqual(payload["connection"]["accountAddress"], "popup.owner@gmail.com")
            self.assertNotIn("popup-gmail-refresh-token-that-stays-encrypted", json.dumps(payload))

            with sqlite3.connect(str(db_path)) as database:
                raw = database.execute("SELECT secret_ciphertext FROM platform_connections").fetchone()[0]
            decrypted = server.credential_vault.decrypt(raw)  # type: ignore[union-attr]
            self.assertIn("popup-gmail-refresh-token-that-stays-encrypted", decrypted)
            self.assertNotIn("popup-google-gmail-access-token", decrypted)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_google_oauth_code_post_saves_selected_calendar_gmail_and_drive_connections(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "oauth-google-multi-code.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=db_path,
                credential_encryption_key=key,
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
            ),
        )
        server.database.register_user("owner@example.com")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cookie = self._cookie_for(server, base_url)
            granted_scope = " ".join([
                GOOGLE_CALENDAR_OAUTH_SCOPE,
                GOOGLE_GMAIL_OAUTH_SCOPE,
                GOOGLE_DRIVE_OAUTH_SCOPE,
            ])

            def fake_token_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                self.assertEqual(timeout, 20)
                self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
                fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
                self.assertEqual(fields["grant_type"], ["authorization_code"])
                self.assertEqual(fields["code"], ["popup-google-multi-code"])
                self.assertEqual(fields["redirect_uri"], [base_url])
                return _JsonResponse({
                    "access_token": "popup-google-multi-access-token",
                    "refresh_token": "popup-google-multi-refresh-token-that-stays-encrypted",
                    "scope": granted_scope,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                })

            def fake_gmail_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                if "gmail.googleapis.com" not in request.full_url:
                    raise _NotMine
                self.assertEqual(timeout, 20)
                self.assertEqual(request.get_header("Authorization"), "Bearer popup-google-multi-access-token")
                if request.full_url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/profile"):
                    return _JsonResponse({"emailAddress": "multi.owner@gmail.com"})
                self.assertTrue(request.full_url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"))
                return _JsonResponse({"messages": [], "resultSizeEstimate": 0})

            request = urllib_request.Request(
                f"{base_url}/api/oauth/google/calendar/code",
                data=json.dumps({
                    "code": "popup-google-multi-code",
                    "scopes": ["calendar", "gmail", "drive"],
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie,
                    "X-Requested-With": "XMLHttpRequest",
                    "X-Forwarded-Proto": "http",
                },
                method="POST",
            )
            opener = urllib_request.build_opener()
            with _provider_endpoint_patch(fake_gmail_urlopen, fake_token_urlopen):
                if True:
                    with mock.patch(
                        "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
                        return_value={"eventCount": 0, "message": "", "summary": ""},
                    ) as calendar_run:
                        with opener.open(request, timeout=5) as response:
                            payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["ok"])
            self.assertIn("Google Calendar, Gmail, and Drive connected", payload["message"])
            connections = {connection["platform"]: connection for connection in payload["connections"]}
            self.assertEqual(set(connections), {"calendar", "email", "drive"})
            self.assertEqual(connections["calendar"]["metadata"]["scope"], GOOGLE_CALENDAR_REQUESTED_SCOPE_TEXT)
            self.assertEqual(connections["email"]["metadata"]["provider"], "google_gmail")
            self.assertEqual(connections["email"]["metadata"]["scope"], GOOGLE_GMAIL_OAUTH_SCOPE)
            self.assertEqual(connections["drive"]["metadata"]["provider"], "google_drive")
            self.assertEqual(connections["drive"]["metadata"]["scope"], GOOGLE_DRIVE_OAUTH_SCOPE)
            self.assertNotIn("popup-google-multi-refresh-token-that-stays-encrypted", json.dumps(payload))
            calendar_run.assert_called_once()
            self.assertEqual(calendar_run.call_args.args[0], "popup-google-multi-access-token")

            with sqlite3.connect(str(db_path)) as database:
                row = database.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT secret_ciphertext) FROM platform_connections",
                ).fetchone()
            self.assertEqual(row, (3, 1))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_calendar_oauth_callback_saves_encrypted_refresh_token(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")

        db_path = Path(self.temp_dir.name) / "oauth-callback.db"
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=db_path,
                credential_encryption_key=key,
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
            ),
        )
        server.database.register_user("owner@example.com")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cookie = self._cookie_for(server, base_url)
            start_request = urllib_request.Request(
                f"{base_url}/api/oauth/google/calendar/start",
                headers={
                    "Cookie": cookie,
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "assistyca.com",
                },
            )
            with urllib_request.urlopen(start_request, timeout=5) as response:
                start_payload = json.loads(response.read().decode("utf-8"))
            state = urllib_parse.parse_qs(urllib_parse.urlparse(start_payload["authUrl"]).query)["state"][0]

            def fake_urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
                self.assertEqual(timeout, 20)
                self.assertEqual(request.full_url, GOOGLE_OAUTH_TOKEN_URL)
                fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
                self.assertEqual(fields["grant_type"], ["authorization_code"])
                self.assertEqual(fields["code"], ["calendar-code"])
                return _JsonResponse({
                    "access_token": "short-lived-google-access-token",
                    "refresh_token": "refresh-token-that-stays-encrypted",
                    "scope": GOOGLE_CALENDAR_OAUTH_SCOPE,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                })

            opener = urllib_request.build_opener(_NoRedirect)
            callback_url = (
                f"{base_url}/api/oauth/google/calendar/callback?"
                f"{urllib_parse.urlencode({'code': 'calendar-code', 'state': state})}"
            )
            callback_request = urllib_request.Request(callback_url, headers={"Cookie": cookie})
            with _provider_endpoint_patch(fake_urlopen):
                with mock.patch(
                    "packages.infrastructure.portal_auth.server.CalendarSummaryRunner.run",
                    return_value={"eventCount": 0, "message": "", "summary": ""},
                ) as run:
                    with self.assertRaises(urllib_error.HTTPError) as context:
                        opener.open(callback_request, timeout=5)

            self.assertEqual(context.exception.code, 303)
            self.assertIn("calendar_oauth=success", context.exception.headers["Location"])
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], "short-lived-google-access-token")

            connections = server.database.list_platform_connections("owner@example.com")
            self.assertEqual(len(connections), 1)
            connection = connections[0]
            self.assertEqual(connection["platform"], "calendar")
            self.assertEqual(connection["authType"], "oauth")
            self.assertEqual(connection["connectionStatus"], "connected")
            self.assertEqual(connection["secretHint"], "Google OAuth")
            self.assertEqual(connection["metadata"]["validationStatus"], "verified")
            self.assertNotIn("refresh-token-that-stays-encrypted", json.dumps(connection))

            with sqlite3.connect(str(db_path)) as database:
                raw = database.execute("SELECT secret_ciphertext FROM platform_connections").fetchone()[0]
            decrypted = server.credential_vault.decrypt(raw)  # type: ignore[union-attr]
            self.assertIn("refresh-token-that-stays-encrypted", decrypted)
            self.assertNotIn("short-lived-google-access-token", decrypted)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

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
            self.assertEqual(payload["connection"]["connectionStatus"], "needs_verification")
            self.assertIn("saved securely", payload["message"])
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
