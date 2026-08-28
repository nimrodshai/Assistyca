"""Connecting an Outlook mailbox, and running actions against it.

The point of these is that an email action does not care which provider is
behind the mailbox: the same request that works on Gmail works on Outlook, and
the run picks its reader from the saved credential.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import MICROSOFT_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import MICROSOFT_OUTLOOK_OAUTH_PROVIDER
from packages.infrastructure.portal_auth.server import MICROSOFT_OUTLOOK_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server

SERVER_MODULE = "packages.infrastructure.portal_auth.server"


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")



def _token_endpoint_patch(responder):
    """Patch only the providers' token endpoints, leaving portal calls alone.

    Patching ``urlopen`` on the server module patches the module globally, so a
    blanket patch would also swallow this test's own request to the portal.
    """

    real_urlopen = urllib_request.urlopen
    token_hosts = ("login.microsoftonline.com", "oauth2.googleapis.com")

    def fake_urlopen(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        if any(host in url for host in token_hosts):
            return responder(request)
        return real_urlopen(request, timeout=timeout, **kwargs)

    return mock.patch(f"{SERVER_MODULE}.urllib_request.urlopen", side_effect=fake_urlopen)


class OutlookConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.server = create_server(
            "127.0.0.1",
            0,
            root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
                agent_output_dir=Path(self.temp_dir.name) / "agent_outputs",
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                microsoft_oauth_client_id="microsoft-client-id",
                microsoft_oauth_client_secret="microsoft-client-secret",
            ),
        )
        if self.server.credential_vault is None:
            self.server.server_close()
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path: str, body: dict[str, object]):  # type: ignore[no-untyped-def]
        return urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    def _save_outlook_connection(self) -> None:
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": MICROSOFT_OAUTH_SECRET_TYPE,
                "provider": "microsoft",
                "refreshToken": "saved-outlook-refresh-token",
            })),
            secret_hint="Microsoft OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            metadata={"provider": MICROSOFT_OUTLOOK_OAUTH_PROVIDER, "validationStatus": "verified"},
        )

    def _save_gmail_connection(self) -> None:
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": GOOGLE_OAUTH_SECRET_TYPE,
                "provider": "google",
                "refreshToken": "saved-gmail-refresh-token",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )

    # --- starting the sign-in ------------------------------------------------

    def test_the_start_endpoint_needs_a_signed_in_user(self) -> None:
        request = urllib_request.Request(f"{self.base_url}/api/oauth/microsoft/email/start")

        with self.assertRaises(urllib_error.HTTPError) as caught:
            urllib_request.urlopen(request, timeout=5)

        self.assertEqual(caught.exception.code, 401)

    def test_the_start_endpoint_returns_a_microsoft_sign_in_url(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/oauth/microsoft/email/start",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )

        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        auth_url = payload["authUrl"]
        self.assertTrue(auth_url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"))
        params = urllib_parse.parse_qs(urllib_parse.urlparse(auth_url).query)
        self.assertEqual(params["client_id"], ["microsoft-client-id"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["scope"], [MICROSOFT_OUTLOOK_OAUTH_SCOPE])
        self.assertTrue(params["redirect_uri"][0].endswith("/api/oauth/microsoft/email/callback"))
        # offline_access is what makes Microsoft return a refresh token.
        self.assertIn("offline_access", params["scope"][0])
        self.assertTrue(params["state"][0])

    def test_a_configured_tenant_replaces_the_common_endpoint(self) -> None:
        self.server.config.microsoft_oauth_tenant = "contoso.onmicrosoft.com"
        request = urllib_request.Request(
            f"{self.base_url}/api/oauth/microsoft/email/start",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )

        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertIn("contoso.onmicrosoft.com", payload["authUrl"])

    def test_an_unconfigured_server_says_so_instead_of_failing(self) -> None:
        self.server.config.microsoft_oauth_client_id = ""
        request = urllib_request.Request(
            f"{self.base_url}/api/oauth/microsoft/email/start",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )

        with self.assertRaises(urllib_error.HTTPError) as caught:
            urllib_request.urlopen(request, timeout=5)

        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(caught.exception.code, 503)
        self.assertEqual(payload["error"], "microsoft_oauth_not_configured")

    # --- saving the connection ----------------------------------------------

    def test_the_code_is_exchanged_server_side_and_the_token_never_reaches_the_browser(self) -> None:
        def responder(request):  # type: ignore[no-untyped-def]
            self.assertTrue(request.full_url.endswith("/oauth2/v2.0/token"))
            fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(fields["grant_type"], ["authorization_code"])
            self.assertEqual(fields["code"], ["one-time-code"])
            self.assertEqual(fields["client_secret"], ["microsoft-client-secret"])
            return _FakeResponse({
                "access_token": "microsoft-access-token",
                "refresh_token": "microsoft-refresh-token-that-stays-encrypted",
                "scope": MICROSOFT_OUTLOOK_OAUTH_SCOPE,
            })

        with _token_endpoint_patch(responder):
            with mock.patch(
                f"{SERVER_MODULE}.OutlookAccessValidator.validate",
                return_value={"outlookValidation": "ok"},
            ):
                with urllib_request.urlopen(
                    self._post("/api/oauth/microsoft/email/code", {"code": "one-time-code"}),
                    timeout=5,
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["connection"]["platform"], "email")
        self.assertEqual(payload["connection"]["authType"], "oauth")
        self.assertEqual(payload["connection"]["metadata"]["provider"], MICROSOFT_OUTLOOK_OAUTH_PROVIDER)
        serialized = json.dumps(payload)
        self.assertNotIn("microsoft-refresh-token-that-stays-encrypted", serialized)
        self.assertNotIn("microsoft-access-token", serialized)

    def test_the_refresh_token_is_stored_encrypted(self) -> None:
        def responder(request):  # type: ignore[no-untyped-def]
            return _FakeResponse({
                "access_token": "microsoft-access-token",
                "refresh_token": "microsoft-refresh-token-that-stays-encrypted",
                "scope": MICROSOFT_OUTLOOK_OAUTH_SCOPE,
            })

        with _token_endpoint_patch(responder):
            with mock.patch(
                f"{SERVER_MODULE}.OutlookAccessValidator.validate",
                return_value={"outlookValidation": "ok"},
            ):
                with urllib_request.urlopen(
                    self._post("/api/oauth/microsoft/email/code", {"code": "one-time-code"}),
                    timeout=5,
                ):
                    pass

        record = self.server.database.get_platform_connection_ciphertext("owner@example.com", "email")
        decrypted = self.server.credential_vault.decrypt(record)  # type: ignore[union-attr]
        self.assertIn("microsoft-refresh-token-that-stays-encrypted", decrypted)
        self.assertNotIn("microsoft-access-token", decrypted)

    def test_a_grant_with_no_refresh_token_is_refused_rather_than_half_saved(self) -> None:
        def responder(request):  # type: ignore[no-untyped-def]
            return _FakeResponse({"access_token": "microsoft-access-token"})

        with _token_endpoint_patch(responder):
            with self.assertRaises(urllib_error.HTTPError) as caught:
                urllib_request.urlopen(
                    self._post("/api/oauth/microsoft/email/code", {"code": "one-time-code"}),
                    timeout=5,
                )

        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(self.server.database.list_platform_connections("owner@example.com"), [])

    # --- running an action against the connected mailbox --------------------

    def test_an_email_digest_run_uses_the_outlook_reader(self) -> None:
        self._save_outlook_connection()

        def responder(request):  # type: ignore[no-untyped-def]
            fields = urllib_parse.parse_qs(request.data.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(fields["grant_type"], ["refresh_token"])
            self.assertEqual(fields["refresh_token"], ["saved-outlook-refresh-token"])
            return _FakeResponse({"access_token": "fresh-outlook-access-token"})

        fake_result = {
            "message": "Outlook digest\n\n1 recent message:\n1. Proposal review - Maya",
            "summary": "Outlook digest - 1 message",
            "messageCount": 1,
            "items": [{"subject": "Proposal review"}],
        }
        with _token_endpoint_patch(responder):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value=fake_result) as run:
                with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run") as gmail_run:
                    with urllib_request.urlopen(self._post("/api/agent/proposals/run", {
                        "proposalType": "email-digest",
                        "fields": {"mailbox": "Outlook", "deliveryChannel": "portal"},
                    }), timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mailbox"], "Outlook")
        run.assert_called_once()
        gmail_run.assert_not_called()
        self.assertEqual(run.call_args.args[0], "fresh-outlook-access-token")

    def test_a_gmail_connection_still_uses_the_gmail_reader(self) -> None:
        # The dispatch has to keep every existing Gmail user on Gmail.
        self._save_gmail_connection()
        self.server.config.google_oauth_client_id = "google-client-id.apps.googleusercontent.com"
        self.server.config.google_oauth_client_secret = "google-client-secret"

        def responder(request):  # type: ignore[no-untyped-def]
            return _FakeResponse({"access_token": "fresh-gmail-access-token"})

        fake_result = {
            "message": "Gmail digest\n\n1 recent message:\n1. Proposal review - Maya",
            "summary": "Gmail digest - 1 message",
            "messageCount": 1,
            "items": [{"subject": "Proposal review"}],
        }
        with _token_endpoint_patch(responder):
            with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", return_value=fake_result) as gmail_run:
                with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run") as outlook_run:
                    with urllib_request.urlopen(self._post("/api/agent/proposals/run", {
                        "proposalType": "email-digest",
                        "fields": {"mailbox": "Gmail", "deliveryChannel": "portal"},
                    }), timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["mailbox"], "Gmail")
        gmail_run.assert_called_once()
        outlook_run.assert_not_called()

    def test_a_receipts_run_asks_outlook_for_the_right_month(self) -> None:
        self._save_outlook_connection()

        def responder(request):  # type: ignore[no-untyped-def]
            return _FakeResponse({"access_token": "fresh-outlook-access-token"})

        fake_result = {
            "message": "Outlook digest\n\n1 recent message:\n1. Receipt - Store",
            "summary": "Outlook digest - 1 message",
            "messageCount": 1,
            "items": [{
                "id": "msg-1",
                "threadId": "thread-1",
                "from": "Store <receipts@example.com>",
                "subject": "Receipt - Store",
                "date": "Tue, 14 Jul 2026 08:15:00 +0000",
                "snippet": "Thanks for your purchase",
                "attachments": [],
            }],
        }
        with _token_endpoint_patch(responder):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value=fake_result) as run:
                with urllib_request.urlopen(self._post("/api/agent/proposals/run", {
                    "proposalType": "custom",
                    "fields": {
                        "result": "Pull all receipts for August 2026",
                        "manualRunMonth": "2026-08",
                        "outputFolder": "Receipts/Aug2026/",
                        "deliveryChannel": "portal",
                    },
                    "deliveryChannel": "portal",
                }), timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        query = run.call_args.kwargs["query"]
        self.assertEqual(query.after.isoformat(), "2026-08-01")
        self.assertEqual(query.before.isoformat(), "2026-09-01")
        self.assertIn("receipt", query.terms)
        # The receipts label survives, even though the reader said "Outlook
        # digest" rather than "Gmail digest".
        self.assertIn("Receipt search", payload["summary"])

    def test_an_action_saved_with_a_gmail_query_still_runs_on_outlook(self) -> None:
        # Actions written before Outlook support stored a Gmail search string.
        self._save_outlook_connection()

        def responder(request):  # type: ignore[no-untyped-def]
            return _FakeResponse({"access_token": "fresh-outlook-access-token"})

        fake_result = {"message": "Outlook digest", "summary": "Outlook digest", "messageCount": 0, "items": []}
        with _token_endpoint_patch(responder):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value=fake_result) as run:
                with urllib_request.urlopen(self._post("/api/agent/proposals/run", {
                    "proposalType": "email-digest",
                    "fields": {
                        "gmailQuery": "after:2026/07/01 before:2026/08/01 (receipt OR invoice)",
                        "deliveryChannel": "portal",
                    },
                }), timeout=5) as response:
                    json.loads(response.read().decode("utf-8"))

        query = run.call_args.kwargs["query"]
        self.assertEqual(query.after.isoformat(), "2026-07-01")
        self.assertEqual(query.before.isoformat(), "2026-08-01")
        self.assertEqual(query.terms, ("receipt", "invoice"))

    def test_a_run_with_no_mailbox_connected_asks_for_either_provider(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            urllib_request.urlopen(self._post("/api/agent/proposals/run", {
                "proposalType": "email-digest",
                "fields": {"deliveryChannel": "portal"},
            }), timeout=5)

        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(payload["error"], "email_setup_required")
        self.assertIn("Gmail or Outlook", payload["message"])

    def test_disconnecting_outlook_never_calls_google_to_revoke(self) -> None:
        # The email platform is shared, so without a provider check this would
        # tell the owner to visit their Google Account for a Microsoft mailbox.
        self._save_outlook_connection()
        connection_id = self.server.database.list_platform_connections("owner@example.com")[0]["id"]

        real_urlopen = urllib_request.urlopen

        def no_provider_calls(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
            url = getattr(request, "full_url", str(request))
            if "google" in url or "microsoftonline" in url:
                raise AssertionError(f"disconnect should not call a provider: {url}")
            return real_urlopen(request, timeout=timeout, **kwargs)

        request = urllib_request.Request(
            f"{self.base_url}/api/platform-connections/{connection_id}",
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with mock.patch(f"{SERVER_MODULE}.urllib_request.urlopen", side_effect=no_provider_calls):
            with urllib_request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertIn("Outlook was disconnected", payload["message"])
        self.assertNotIn("Google Account", payload["message"])
        self.assertEqual(self.server.database.list_platform_connections("owner@example.com"), [])

    def test_a_rejected_microsoft_credential_marks_the_connection_for_attention(self) -> None:
        self._save_outlook_connection()

        def responder(request):  # type: ignore[no-untyped-def]
            raise urllib_error.HTTPError(request.full_url, 400, "invalid_grant", {}, None)  # type: ignore[attr-defined]

        with _token_endpoint_patch(responder):
            with self.assertRaises(urllib_error.HTTPError) as caught:
                urllib_request.urlopen(self._post("/api/agent/proposals/run", {
                    "proposalType": "email-digest",
                    "fields": {"deliveryChannel": "portal"},
                }), timeout=5)

        self.assertEqual(caught.exception.code, 409)
        connection = [
            item for item in self.server.database.list_platform_connections("owner@example.com")
            if item["platform"] == "email"
        ][0]
        self.assertEqual(connection["connectionStatus"], "needs_attention")
        self.assertEqual(connection["metadata"]["provider"], MICROSOFT_OUTLOOK_OAUTH_PROVIDER)


if __name__ == "__main__":
    unittest.main()
