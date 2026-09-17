"""Connecting Gmail or Outlook from a link sent over WhatsApp - no portal."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
import urllib.parse as urllib_parse
import urllib.request as urllib_request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import base64
from packages.infrastructure.portal_auth.server import PortalConfig, create_server, sign_oauth_state_payload
from packages.infrastructure.whatsapp_agent_chat import (
    build_connect_links_line,
    build_link_existing_account_text,
    infer_mail_provider,
)


VAULT_KEY = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
PLATFORM = "platform-phone-1"
APP_SECRET = "oauth-test-secret"
SESSION_SECRET = "oauth-session-secret-that-is-long-enough"
PHONE = "447700900123"


def _loop_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    """One model round as the loop reads it: tool calls, or the final reply."""

    outputs = [{"type": "reasoning", "summary": []}, *items]
    text = ""
    if reply is not None:
        text = json.dumps({"reply": "", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, **reply})
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": outputs}, input_tokens=10, output_tokens=5)


def _tool_call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


class ProviderInferenceTests(unittest.TestCase):
    def test_consumer_domains_name_their_provider(self) -> None:
        self.assertEqual(infer_mail_provider("dana@gmail.com"), "google")
        self.assertEqual(infer_mail_provider("dana@googlemail.com"), "google")
        self.assertEqual(infer_mail_provider("dana@outlook.com"), "microsoft")
        self.assertEqual(infer_mail_provider("dana@hotmail.co.il"), "microsoft")
        self.assertEqual(infer_mail_provider("dana@live.com"), "microsoft")

    def test_a_company_domain_gets_both_links(self) -> None:
        self.assertEqual(infer_mail_provider("dana@acme.co"), "")
        line = build_connect_links_line("dana@acme.co", {"google": "https://g", "microsoft": "https://m"})
        self.assertIn("https://g", line)
        self.assertIn("https://m", line)

    def test_only_the_matching_link_is_offered_for_a_known_domain(self) -> None:
        line = build_connect_links_line("dana@gmail.com", {"google": "https://g", "microsoft": "https://m"})
        self.assertIn("https://g", line)
        self.assertNotIn("https://m", line)
        self.assertIn("Google", line)

    def test_no_configured_provider_falls_back_to_the_portal_only_for_linking(self) -> None:
        self.assertEqual(build_connect_links_line("dana@gmail.com", {}), "")
        self.assertIn("assistyca.com", build_link_existing_account_text("dana@gmail.com", {}))
        self.assertNotIn("assistyca.com", build_link_existing_account_text("dana@gmail.com", {"google": "https://g"}))


class WhatsAppOAuthLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db",
            session_secret=SESSION_SECRET,
            # Without a credential vault the OAuth helpers report themselves
            # unconfigured, and no link can be minted at all.
            credential_encryption_key=VAULT_KEY,
            google_oauth_client_id="google-client",
            google_oauth_client_secret="google-secret",
            microsoft_oauth_client_id="ms-client",
            microsoft_oauth_client_secret="ms-secret",
        ))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET,
            "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM,
            "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            "ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": "972559196101",
            "PUBLIC_BASE_URL": "https://assistyca.example",
        }, clear=False)
        self.env.start()
        self.send_patch = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.reply")
        self.sent = self.send_patch.start()
        self.model_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps({"reply": "Sure - what's your email?"})))
        self.model = self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop()
        self.send_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _webhook(self, text, *, sender=PHONE, message_id="wamid.1"):
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
            "contacts": [{"profile": {"name": "Dana"}, "wa_id": sender}],
            "messages": [{"from": sender, "id": message_id, "timestamp": "1756700000", "type": "text", "text": {"body": text}}],
        }}]}]}
        body = json.dumps(payload).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _state(self, **overrides) -> str:
        payload = {"version": 1, "channel": "whatsapp", "provider": "google", "email": "dana@gmail.com",
                   "waId": PHONE, "purpose": "connect", "issuedAt": int(time.time()), "nonce": "n",
                   "scopeIds": ["gmail", "calendar"]}
        payload.update(overrides)
        return sign_oauth_state_payload(SESSION_SECRET, payload)

    def _callback(self, provider: str, state: str, code: str = "auth-code") -> tuple[int, str, str]:
        path = "/api/oauth/google/calendar/callback" if provider == "google" else "/api/oauth/microsoft/email/callback"
        query = urllib_parse.urlencode({"code": code, "state": state})

        class NoRedirect(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib_request.build_opener(NoRedirect)
        try:
            with opener.open(f"{self.base_url}{path}?{query}", timeout=15) as response:
                return int(response.status), response.headers.get("Content-Type", ""), response.read().decode("utf-8", "replace")
        except urllib_request.HTTPError as exc:  # type: ignore[attr-defined]
            location = exc.headers.get("Location", "")
            if not location.startswith("/signed-in?"):
                return int(exc.code), location, ""
        # A WhatsApp sign-in is finished by the callback and shown by the
        # page it sends the browser on to - that page is what a person sees.
        self.last_done_url = f"{self.base_url}{location}"
        return self._open_page(self.last_done_url)

    def _open_without_redirect(self, url: str) -> tuple[int, str, str]:
        class NoRedirect(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        try:
            with urllib_request.build_opener(NoRedirect).open(url, timeout=15) as response:
                return int(response.status), "", response.read().decode("utf-8", "replace")
        except urllib_request.HTTPError as exc:  # type: ignore[attr-defined]
            return int(exc.code), exc.headers.get("Location", ""), ""

    def _open_page(self, url: str) -> tuple[int, str, str]:
        with urllib_request.urlopen(url, timeout=15) as response:
            return int(response.status), response.headers.get("Content-Type", ""), response.read().decode("utf-8", "replace")

    def _last_reply(self) -> str:
        return self.sent.call_args.kwargs["message_text"]

    # --- the links themselves -------------------------------------------

    def test_a_new_account_is_welcomed_with_a_sign_in_link_not_a_website(self) -> None:
        self._webhook("hi", message_id="wamid.a1")
        result = self._webhook("dana@gmail.com", message_id="wamid.a2")
        self.assertEqual(result["results"][0]["action"], "signup_completed")
        reply = self._last_reply()
        self.assertIn("https://assistyca.example/connect/google?s=", reply)
        self.assertNotIn("assistyca.com", reply)
        self.assertNotIn("Settings", reply)
        # An Outlook address gets the Microsoft door instead.
        self._webhook("hi", sender="447700900999", message_id="wamid.a3")
        self._webhook("dana@outlook.com", sender="447700900999", message_id="wamid.a4")
        self.assertIn("/connect/microsoft?", self._last_reply())
        self.assertNotIn("/connect/google?", self._last_reply())

    def test_an_existing_address_gets_a_sign_in_link_to_prove_it_is_theirs(self) -> None:
        self.database.register_user("owner@gmail.com")
        self._webhook("hi", message_id="wamid.b1")
        result = self._webhook("owner@gmail.com", message_id="wamid.b2")
        self.assertEqual(result["results"][0]["action"], "signup_email_taken")
        reply = self._last_reply()
        self.assertIn("already has an Assistyca account", reply)
        self.assertIn("https://assistyca.example/connect/google?", reply)
        self.assertNotIn("assistyca.com", reply)
        # And the phone is not linked by the claim alone.
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(PHONE), 0)

    def test_the_agent_is_handed_the_links_for_a_linked_phone(self) -> None:
        # Under the loop the link is a tool result, not part of the prompt:
        # the model asks for it with connect_link and may only send what
        # came back. The link itself is signed for this phone and account.
        self.database.register_user("dana@gmail.com")
        user = self.database.get_user("dana@gmail.com") or {}
        self.database.link_user_whatsapp_number(user_id=int(user["id"]), wa_id=PHONE)
        self.model.side_effect = [
            _loop_round(_tool_call("read_inbox", "c1", time_window="today")),
            _loop_round(_tool_call("connect_link", "c2", provider="google")),
            _loop_round(reply={"reply": "Tap the link."}),
        ]
        self._webhook("can you read my email?", message_id="wamid.c1")
        items = self.model.call_args.kwargs["input"]
        shown = [json.loads(item["output"]) for item in items if item.get("type") == "function_call_output"]
        self.assertEqual(shown[0]["error"]["code"], "source_not_connected")
        self.assertIn("https://assistyca.example/connect/google?s=", shown[1]["link"])
        status, location, _ = self._open_without_redirect(shown[1]["link"].replace("https://assistyca.example", self.base_url))
        self.assertEqual(status, 303, "a fresh link goes straight on to Google")
        self.assertIn("accounts.google.com/o/oauth2/v2/auth", location)
        self.assertIn("login_hint=dana%40gmail.com", location)
        self.assertIn("gmail", location)
        context = str(items[0]["content"])
        self.assertNotIn("connectLinks", context, "the link reaches the model through the tool, never the context")
        self.assertIn("Never send the person to a website except a link a tool returned", context)

    # --- the callback, with no browser session ---------------------------

    def test_a_link_tapped_from_whatsapp_connects_without_a_session(self) -> None:
        self.database.register_user("dana@gmail.com")
        handler = "packages.infrastructure.portal_auth.server.PortalAuthHandler"
        with (
            mock.patch(f"{handler}._exchange_google_calendar_oauth_code", return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}),
            mock.patch(f"{handler}._save_google_oauth_connections", return_value=[{"accountAddress": "dana@gmail.com"}]) as save,
        ):
            status, content_type, body = self._callback("google", self._state())

        self.assertEqual(status, 200, "a WhatsApp sign-in lands on a page, it is not bounced to the portal")
        self.assertIn("text/html", content_type)
        self.assertIn("Google connected!", body, "the page says the one thing it is for")
        self.assertNotIn("Ask me anything", body, "the invitation belongs in the chat, not on a page that cannot answer")
        self.assertIn("wa.me/972559196101", body)
        save.assert_called_once()
        self.assertEqual(save.call_args.args[0].email, "dana@gmail.com")
        reply = self._last_reply()
        self.assertIn("Gmail and calendar are connected", reply)
        # What they hear about the first read is what may come back to them,
        # not that somebody is going through everything they have.
        self.assertIn("If I see anything worth your attention, I'll let you know.", reply)
        self.assertNotIn("going through", reply)
        self.assertNotIn("your mail now", reply)

    def test_refreshing_the_page_after_a_sign_in_repeats_nothing(self) -> None:
        self.database.register_user("dana@gmail.com")
        handler = "packages.infrastructure.portal_auth.server.PortalAuthHandler"
        with (
            mock.patch(f"{handler}._exchange_google_calendar_oauth_code", return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}) as exchange,
            mock.patch(f"{handler}._save_google_oauth_connections", return_value=[{"accountAddress": "dana@gmail.com"}]) as save,
        ):
            self._callback("google", self._state())
            messages_after_sign_in = self.sent.call_count
            status, _, body = self._open_page(self.last_done_url)
            status_again, _, body_again = self._open_page(self.last_done_url)

        self.assertEqual((status, status_again), (200, 200))
        self.assertIn("Google connected!", body)
        self.assertEqual(body, body_again)
        exchange.assert_called_once()
        save.assert_called_once()
        self.assertEqual(self.sent.call_count, messages_after_sign_in, "a reload says nothing in WhatsApp")

    def test_the_done_page_neither_trusts_a_tampered_address_nor_carries_an_email(self) -> None:
        status, _, body = self._open_page(f"{self.base_url}/signed-in?r=forged.value")
        self.assertEqual(status, 200)
        self.assertNotIn("connected!", body)

        self.database.register_user("owner@gmail.com")
        handler = "packages.infrastructure.portal_auth.server.PortalAuthHandler"
        with (
            mock.patch(f"{handler}._exchange_google_calendar_oauth_code", return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}),
            mock.patch("packages.infrastructure.portal_auth.server.GmailAccessValidator") as validator,
            mock.patch(f"{handler}._save_google_oauth_connections"),
        ):
            validator.return_value.validate.return_value = {"emailAddress": "mallory@gmail.com"}
            self._callback("google", self._state(email="owner@gmail.com", purpose="link_account"))
        token = urllib_parse.parse_qs(urllib_parse.urlparse(self.last_done_url).query)["r"][0]
        body_value = token.split(".", 1)[0]
        decoded = base64.urlsafe_b64decode(body_value + "=" * (-len(body_value) % 4)).decode("utf-8")
        self.assertNotIn("owner@gmail.com", decoded)

    def test_linking_an_existing_account_requires_the_matching_google_account(self) -> None:
        self.database.register_user("owner@gmail.com")
        owner = self.database.get_user("owner@gmail.com") or {}
        handler = "packages.infrastructure.portal_auth.server.PortalAuthHandler"
        with (
            mock.patch(f"{handler}._exchange_google_calendar_oauth_code", return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}),
            mock.patch("packages.infrastructure.portal_auth.server.GmailAccessValidator") as validator,
            mock.patch(f"{handler}._save_google_oauth_connections", return_value=[{"accountAddress": "mallory@gmail.com"}]) as save,
        ):
            validator.return_value.validate.return_value = {"emailAddress": "mallory@gmail.com"}
            status, _, body = self._callback("google", self._state(email="owner@gmail.com", purpose="link_account"))

        self.assertEqual(status, 200)
        self.assertIn("Not connected", body)
        self.assertIn("robot-thinking.webp", body)
        save.assert_not_called()
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(PHONE), 0)
        self.assertIn("isn't owner@gmail.com", self._last_reply())

        with (
            mock.patch(f"{handler}._exchange_google_calendar_oauth_code", return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}),
            mock.patch("packages.infrastructure.portal_auth.server.GmailAccessValidator") as validator,
            mock.patch(f"{handler}._save_google_oauth_connections", return_value=[{"accountAddress": "owner@gmail.com"}]) as save,
        ):
            validator.return_value.validate.return_value = {"emailAddress": "owner@gmail.com"}
            status, _, body = self._callback("google", self._state(email="owner@gmail.com", purpose="link_account"))

        self.assertIn("Google connected!", body)
        save.assert_called_once()
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(PHONE), int(owner["id"]))
        self.assertIn("This phone is now linked", self._last_reply())

    def test_a_forged_or_expired_state_connects_nothing(self) -> None:
        self.database.register_user("dana@gmail.com")
        handler = "packages.infrastructure.portal_auth.server.PortalAuthHandler"
        with mock.patch(f"{handler}._save_google_oauth_connections") as save:
            forged = sign_oauth_state_payload("wrong-secret", {"channel": "whatsapp", "provider": "google",
                                              "email": "dana@gmail.com", "waId": PHONE, "issuedAt": int(time.time())})
            status, location, _ = self._callback("google", forged)
            self.assertIn(status, {302, 303}, "a bad signature falls through to the browser path, which bounces it")
            self.assertIn("/portal/", location)

            status, _, body = self._callback("google", self._state(issuedAt=int(time.time()) - 3 * 3600))
            self.assertEqual(status, 200)
            self.assertIn("expired", body)
        save.assert_not_called()

    def _save_google_row(self, *, status: str, address: str = "dana@gmail.com") -> None:
        self.database.save_platform_connection(
            "dana@gmail.com", platform="email", provider="google_gmail", auth_type="oauth",
            secret_ciphertext="cipher", secret_hint="Google OAuth", account_address=address,
            connection_status=status,
        )

    def test_an_old_link_while_google_is_still_connected_says_there_is_nothing_to_do(self) -> None:
        self.database.register_user("dana@gmail.com")
        self._save_google_row(status="connected")
        status, _, body = self._callback("google", self._state(issuedAt=int(time.time()) - 3 * 3600))
        self.assertEqual(status, 200)
        self.assertIn("Google is still connected", self._last_reply())
        self.assertNotIn("Ask me again", self._last_reply())
        self.assertIn("still connected", body)

    def test_an_old_link_while_a_google_mailbox_needs_attention_still_offers_a_fresh_one(self) -> None:
        self.database.register_user("dana@gmail.com")
        self._save_google_row(status="connected")
        self._save_google_row(status="needs_attention", address="dana.work@gmail.com")
        self._callback("google", self._state(issuedAt=int(time.time()) - 3 * 3600))
        self.assertIn("had expired", self._last_reply())

    def test_tapping_an_old_link_says_so_before_any_sign_in(self) -> None:
        self.database.register_user("dana@gmail.com")
        old = urllib_parse.urlencode({"s": self._state(issuedAt=int(time.time()) - 3 * 3600)})
        messages_before = self.sent.call_count

        status, location, _ = self._open_without_redirect(f"{self.base_url}/connect/google?{old}")
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/signed-in?"), "an old link never reaches Google")
        _, _, body = self._open_page(f"{self.base_url}{location}")
        self.assertIn("out of date", body)
        self.assertIn("fresh one", body)

        self._save_google_row(status="connected")
        _, _, body = self._open_page(f"{self.base_url}/connect/google?{old}")
        self.assertIn("nothing to do: Google is still connected", body)
        self.assertEqual(self.sent.call_count, messages_before, "tapping a link writes nothing in the chat")

        _, _, body = self._open_page(f"{self.base_url}/connect/google?s=forged.value")
        self.assertIn("doesn&#x27;t work", body)

    def test_the_microsoft_callback_takes_the_same_path(self) -> None:
        self.database.register_user("dana@outlook.com")
        handler = "packages.infrastructure.portal_auth.server.PortalAuthHandler"
        with (
            mock.patch(f"{handler}._exchange_microsoft_oauth_code", return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}),
            mock.patch(f"{handler}._save_microsoft_oauth_connection", return_value={"accountAddress": "dana@outlook.com"}) as save,
        ):
            status, _, body = self._callback("microsoft", self._state(provider="microsoft", email="dana@outlook.com", scopeIds=None))
        self.assertEqual(status, 200)
        self.assertIn("Microsoft connected!", body)
        save.assert_called_once()
        self.assertIn("Outlook is connected", self._last_reply())


if __name__ == "__main__":
    unittest.main()
