"""Registering on the web, and being texted first by the agent."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.registration_welcome import FAMILY_HELLO
from packages.infrastructure.registration_welcome import FAMILY_WELCOME_BODY
from packages.infrastructure.registration_welcome import HEBREW_FAMILY_HELLO
from packages.infrastructure.registration_welcome import HEBREW_FAMILY_WELCOME_BODY
from packages.infrastructure.whatsapp_agent_chat import flatten_for_template


PLATFORM = "platform-phone-1"
APP_SECRET = "register-test-secret"
PHONE = "972507322341"
HANDLE = "wa-972507322341@whatsapp.assistyca.com"


def webhook_payload(text, *, sender=PHONE, message_id="wamid.r1", name="Dana on WhatsApp", timestamp="1756700000"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
        "contacts": [{"profile": {"name": name}, "wa_id": sender}],
        "messages": [{"from": sender, "id": message_id, "timestamp": timestamp, "type": "text", "text": {"body": text}}],
    }}]}]}


def registration(**overrides):
    # A name and a phone, nothing else: the page asks nothing about the family.
    body = {
        "name": "Dana Levi",
        "phone": "+972507322341",
        "country": "IL",
    }
    body.update(overrides)
    return body


class WebRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="register-session-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.env = mock.patch.dict("os.environ", {
            "WHATSAPP_APP_SECRET": APP_SECRET,
            "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM,
            "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            "ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": "972559196101",
        }, clear=False)
        self.env.start()
        # The welcome goes out as a template through the notification sender;
        # the conversation's replies go out as plain text through the chat sender.
        self.template_patch = mock.patch(
            "packages.infrastructure.whatsapp_messaging.send_whatsapp_message",
            return_value="wamid.welcome",
        )
        self.template_sent = self.template_patch.start()
        self.reply_patch = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message",
            return_value="wamid.reply",
        )
        self.reply_sent = self.reply_patch.start()
        self.model_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(
                {"outcome": "message", "reply": "Lovely - Stav, Lotan, Lahav and Laor. When are their birthdays?"},
            )),
        )
        self.model = self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop()
        self.reply_patch.stop()
        self.template_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def register(self, body: dict) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}/api/register",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def follow_nothing(self, path: str) -> tuple[int, str]:
        """Ask for a page and report where it points instead of going there."""

        class Stay(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, D102
                return None

        try:
            with urllib_request.build_opener(Stay).open(f"{self.base_url}{path}", timeout=10) as response:
                return response.status, response.headers.get("Location", "")
        except urllib_error.HTTPError as exc:
            return exc.code, exc.headers.get("Location", "")

    def text(self, body: str, **kwargs) -> dict:
        raw = json.dumps(webhook_payload(body, **kwargs)).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=raw, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def replies(self) -> list[str]:
        return [call.kwargs["message_text"] for call in self.reply_sent.call_args_list]

    def turn_text(self) -> str:
        return json.dumps(self.model.call_args.kwargs["input"], ensure_ascii=False)

    def test_registering_texts_the_phone_first_and_the_first_reply_opens_the_account(self) -> None:
        status, payload = self.register(registration())
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["whatsappSent"])
        self.assertEqual(payload["phone"], PHONE)
        self.assertEqual(payload["whatsappLink"], "https://wa.me/972559196101?text=Hi%20Assistyca")
        self.assertEqual(payload["assistycaNumber"], "972559196101")

        # No account yet: the phone has a signup open that knows the name.
        self.assertEqual(self.database.list_users(), [])
        signup = self.database.get_whatsapp_signup(PHONE) or {}
        self.assertEqual(signup["status"], "awaiting_email")
        self.assertEqual(signup["registration"], {"name": "Dana Levi", "source": "web"})
        self.assertEqual([m["role"] for m in signup["transcript"]], ["assistant"])

        # The welcome is the approved family template, in English for a name
        # typed in English: their first name and nothing else. No model is
        # asked to write it.
        self.assertFalse(self.model.called)
        send = self.template_sent.call_args.kwargs
        self.assertEqual(send["recipient_wa_id"], PHONE)
        self.assertIsNone(send["message_text"])
        self.assertEqual(send["template"]["name"], "assistyca_welcome_family_hello")
        self.assertEqual(send["template"]["language"], {"code": "en"})
        components = {component["type"]: component for component in send["template"]["components"]}
        self.assertEqual([parameter["text"] for parameter in components["body"]["parameters"]], ["Dana"])
        # A test server has no public address, so Meta gets no picture to fetch.
        self.assertNotIn("header", components)

        # Their first reply opens the account on the spot - no address asked
        # for, nothing standing between them and the assistant - and that same
        # message is answered by the assistant itself, which is the one that
        # can keep what it says about the family.
        first = self.text("My wife is Stav, my kids are Lotan, Lahav and Laor", message_id="wamid.f1")
        self.assertEqual(
            [result["action"] for result in first["results"]],
            ["signup_completed_without_email", "agent_chat_reply"],
        )
        self.assertNotIn("email", " ".join(self.replies()).lower())

        user = self.database.get_user(HANDLE) or {}
        self.assertTrue(user, "the account should exist now, keyed on the phone")
        self.assertEqual(user["displayName"], "Dana Levi", "the typed name wins over the WhatsApp profile name")
        self.assertEqual(user["trialDays"], 14)
        self.assertNotIn("accountType", user)
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(PHONE), int(user["id"]))
        self.assertEqual((self.database.get_whatsapp_signup(PHONE) or {}).get("status"), "completed")

        # What the page asked is all they were ever asked, and it is pinned.
        user_id = int(user["id"])
        facts = {fact["key"]: fact["fact"] for fact in self.database.list_account_facts(user_id=user_id)}
        self.assertEqual(facts, {"name": "Their name is Dana Levi."})
        pinned = {fact["key"] for fact in self.database.list_account_facts(user_id=user_id) if fact["pinned"]}
        self.assertEqual(pinned, {"name"})
        self.assertEqual(user["profile"]["businessSummary"], "", "nothing about the family is kept in the profile summary")

        # The assistant read their message with the family's opening in front
        # of it, so getting to know them is what it does with it. The welcome
        # already introduced it, so it does not introduce itself again.
        turn = self.turn_text()
        self.assertIn("Getting to know this family", turn)
        self.assertIn("My wife is Stav", turn)
        self.assertNotIn("texted the Assistyca number without registering", turn)
        profile = self.database.get_household_profile(user_id=user_id) or {}
        self.assertEqual(profile["gettingToKnow"], "not_started")
        self.assertNotIn("accountKind", profile)
        # The welcome that was sent before the account existed is the first
        # thing in its conversation, so nothing it said is said again.
        transcript = self.database.list_recent_whatsapp_agent_messages(user_id=user_id)
        self.assertEqual([entry["role"] for entry in transcript], ["assistant", "user", "assistant"])
        self.assertEqual(transcript[0]["text"], FAMILY_HELLO.format(name="Dana"))

    def test_while_meta_reviews_the_new_welcome_the_approved_one_carries_it(self) -> None:
        # Meta refuses the new welcome while the review runs; the one it
        # approved earlier goes in its place, in their language, and the
        # conversation we keep has its words.
        def not_the_new_one(**kwargs):
            if (kwargs.get("template") or {}).get("name") == "assistyca_welcome_family_hello":
                raise RuntimeError("(#132001) Template name does not exist in the translation")
            return "wamid.welcome-approved"

        self.template_sent.side_effect = not_the_new_one
        status, payload = self.register(registration(name="דנה לוי"))

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["whatsappSent"])
        sent = self.template_sent.call_args.kwargs["template"]
        self.assertEqual((sent["name"], sent["language"]), ("assistyca_welcome_family", {"code": "he"}))
        transcript = (self.database.get_whatsapp_signup(PHONE) or {})["transcript"]
        self.assertTrue(transcript[0]["text"].startswith("היי דנה 👋"))
        self.assertIn(HEBREW_FAMILY_WELCOME_BODY, transcript[0]["text"])

    def test_when_neither_family_welcome_is_taken_the_earliest_one_carries_it(self) -> None:
        # The English welcome Meta approved first stands last, in English, so
        # the family still hears from us.
        def only_the_old_one(**kwargs):
            template = kwargs.get("template") or {}
            if template.get("name") in ("assistyca_welcome_family_hello", "assistyca_welcome_family"):
                raise RuntimeError("(#132001) Template name does not exist in the translation")
            return "wamid.welcome-old"

        self.template_sent.side_effect = only_the_old_one
        status, payload = self.register(registration(name="דנה לוי"))

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["whatsappSent"])
        sent = self.template_sent.call_args.kwargs["template"]
        self.assertEqual(sent["name"], "assistyca_welcome_family_english_short")
        self.assertEqual(sent["language"], {"code": "en"})
        self.assertEqual([parameter["text"] for parameter in sent["components"][-1]["parameters"]], ["דנה"])
        # The conversation we keep says what their phone showed: the English words.
        transcript = (self.database.get_whatsapp_signup(PHONE) or {})["transcript"]
        self.assertEqual(len(transcript), 1)
        self.assertTrue(transcript[0]["text"].startswith("Hi דנה 👋"))
        self.assertIn(FAMILY_WELCOME_BODY, transcript[0]["text"])

    def test_nobody_is_ever_asked_for_an_email_however_they_answer(self) -> None:
        # Even "later" or a question opens the account: there is nothing to
        # collect first, so nothing to keep asking for.
        self.register(registration())
        result = self.text("What can you actually do?", message_id="wamid.f1")

        self.assertEqual(result["results"][0]["action"], "signup_completed_without_email")
        self.assertNotIn("email", " ".join(self.replies()).lower())
        self.assertTrue(self.database.get_user(HANDLE))

    def just_now(self) -> str:
        """A message sent now, for the tests where the clock matters."""

        return str(int(datetime.now(timezone.utc).timestamp()))

    def _erase_the_phone_an_hour_ago(self) -> None:
        """This phone asked to be forgotten, earlier today rather than now, so
        the message that follows is not read as one sent before the deletion."""

        self.database.mark_whatsapp_phones_erased([PHONE])
        with self.database._connection() as conn:
            conn.execute(
                "UPDATE erased_whatsapp_phones SET erased_at = ?",
                ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
            )
            conn.commit()

    def test_a_family_that_asked_to_be_forgotten_and_registered_again_starts_over_at_once(self) -> None:
        # A phone is remembered as erased for a day, so a family could ask to
        # be forgotten in the afternoon and register again in the evening.
        # Registering again is starting over on purpose: the deletion has
        # nothing left to say, and the first reply opens the new account.
        self._erase_the_phone_an_hour_ago()
        self.assertIsNotNone(self.database.whatsapp_phone_erased_at(PHONE))

        self.register(registration())
        result = self.text("My wife is Stav and we have three kids", message_id="wamid.f1", timestamp=self.just_now())

        self.assertEqual(result["results"][0]["action"], "signup_completed_without_email")
        self.assertNotIn("erased", " ".join(self.replies()).lower())
        self.assertTrue(self.database.get_user(HANDLE))

    def test_the_handle_an_account_is_keyed_on_is_not_a_way_in(self) -> None:
        # Nobody has that address, so a code sent to it would reach nobody.
        self.register(registration())
        self.text("Hi", message_id="wamid.f1")

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/request",
            data=json.dumps({"email": HANDLE}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib_error.HTTPError) as refused:
            urllib_request.urlopen(request, timeout=10)

        self.assertEqual(refused.exception.code, 403)
        body = json.loads(refused.exception.read().decode("utf-8"))
        self.assertEqual(body["error"], "whatsapp_account")
        self.assertIn("WhatsApp", body["message"])

    def test_a_name_typed_in_hebrew_is_welcomed_in_hebrew(self) -> None:
        status, payload = self.register(registration(name="דנה לוי"))
        self.assertEqual(status, 200, payload)

        sent = self.template_sent.call_args.kwargs["template"]
        self.assertEqual(sent["name"], "assistyca_welcome_family_hello")
        self.assertEqual(sent["language"], {"code": "he"})
        self.assertEqual([parameter["text"] for parameter in sent["components"][-1]["parameters"]], ["דנה"])
        # The conversation we keep says what their phone showed, in Hebrew.
        transcript = (self.database.get_whatsapp_signup(PHONE) or {})["transcript"]
        self.assertEqual(transcript[0]["text"], HEBREW_FAMILY_HELLO.format(name="דנה"))

    def test_whatever_else_the_page_sends_is_not_kept(self) -> None:
        # The old page asked what the business did; a stale tab may still send
        # it. A registration keeps the name and nothing else.
        status, payload = self.register(registration(kind="business", business="Anything at all"))
        self.assertEqual(status, 200, payload)
        self.assertEqual((self.database.get_whatsapp_signup(PHONE) or {})["registration"], {"name": "Dana Levi", "source": "web"})

    def test_names_are_capitalised(self) -> None:
        status, payload = self.register(registration(name="nimrod shai-cohen"))
        self.assertEqual(status, 200, payload)
        signup = self.database.get_whatsapp_signup(PHONE) or {}
        self.assertEqual(signup["registration"]["name"], "Nimrod Shai-Cohen")
        greeted = self.template_sent.call_args.kwargs["template"]["components"][-1]["parameters"][0]["text"]
        self.assertEqual(greeted, "Nimrod")

    def test_the_fields_are_checked_before_anything_is_recorded(self) -> None:
        status, payload = self.register(registration(name="D", phone="+9720"))
        self.assertEqual(status, 400)
        self.assertEqual(set(payload["fieldErrors"]), {"name", "phone"})
        self.assertIsNone(self.database.get_whatsapp_signup("9720"))
        self.assertFalse(self.template_sent.called)

    def test_a_local_number_is_written_out_in_full(self) -> None:
        status, payload = self.register(registration(phone="050-732-2341"))
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["phone"], PHONE)
        self.assertEqual(self.template_sent.call_args.kwargs["recipient_wa_id"], PHONE)

    def test_a_phone_already_on_an_account_is_refused(self) -> None:
        self.database.register_user("owner@example.com")
        owner = self.database.get_user("owner@example.com") or {}
        self.database.link_user_whatsapp_number(user_id=int(owner["id"]), wa_id=PHONE)
        status, payload = self.register(registration())
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "phone_taken")
        self.assertEqual(payload["whatsappUrl"], "/whatsapp")
        self.assertFalse(self.template_sent.called)

    def test_a_picture_meta_cannot_fetch_does_not_cost_them_the_welcome(self) -> None:
        # Meta fetches the header image itself and refuses the whole message
        # when it cannot. The words matter more than the picture, so the
        # second attempt goes without it.
        def refuse_the_picture(**kwargs):
            template = kwargs.get("template") or {}
            if template.get("name") == "assistyca_welcome_family_hello":
                raise RuntimeError("(#132001) Template name does not exist in the translation")
            components = template.get("components") or []
            if any(component.get("type") == "header" for component in components):
                raise RuntimeError("(#131053) Media upload error")
            return "wamid.welcome-no-picture"

        self.template_sent.side_effect = refuse_the_picture
        # A test server has no public address; pretend it does so a picture is tried.
        with mock.patch("packages.infrastructure.registration_welcome.is_publicly_fetchable", return_value=True):
            status, payload = self.register(registration())

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["whatsappSent"])
        # The new welcome (no picture, refused), the approved one with its
        # picture (refused), then the approved one without it.
        self.assertEqual(self.template_sent.call_count, 3)
        sent = self.template_sent.call_args.kwargs["template"]
        self.assertEqual([component["type"] for component in sent["components"]], ["body"])
        self.assertEqual(sent["name"], "assistyca_welcome_family")

    def test_when_the_welcome_cannot_be_sent_the_page_still_gets_a_way_in(self) -> None:
        with mock.patch.dict("os.environ", {"ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "", "WHATSAPP_ACCESS_TOKEN": ""}, clear=False):
            status, payload = self.register(registration())
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["whatsappSent"])
        self.assertIn("Open WhatsApp", payload["message"])
        self.assertEqual(payload["whatsappLink"], "https://wa.me/972559196101?text=Hi%20Assistyca")
        # Saying hi from that phone opens the account that knows their name.
        result = self.text("Hi Assistyca", message_id="wamid.h1")
        self.assertEqual(result["results"][0]["action"], "signup_completed_without_email")
        self.assertEqual((self.database.get_user(HANDLE) or {}).get("displayName"), "Dana Levi")

    def test_a_different_phone_is_a_stranger_who_gets_their_own_account(self) -> None:
        self.register(registration())
        result = self.text("hi", sender="447700900999", message_id="wamid.s1", name="Someone Else")
        self.assertEqual(result["results"][0]["action"], "signup_completed_without_email")
        stranger = self.database.get_user("wa-447700900999@whatsapp.assistyca.com") or {}
        self.assertEqual(stranger.get("displayName"), "Someone Else")
        # Nobody has introduced the assistant to this phone, so its first turn does.
        self.assertIn("texted the Assistyca number without registering", self.turn_text())
        # Dana's registration still waits for Dana.
        self.assertEqual((self.database.get_whatsapp_signup(PHONE) or {}).get("status"), "awaiting_email")

    def test_a_reply_days_later_still_knows_who_registered(self) -> None:
        self.register(registration())
        stale = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        with self.database._connection() as conn:  # noqa: SLF001 - moving the clock is the point
            conn.execute("UPDATE whatsapp_signups SET started_at = ?, updated_at = ? WHERE wa_id = ?", (stale, stale, PHONE))
            conn.commit()
        result = self.text("hello", message_id="wamid.l1")
        self.assertEqual(result["results"][0]["action"], "signup_completed_without_email")
        user = self.database.get_user(HANDLE) or {}
        self.assertEqual(user["displayName"], "Dana Levi")
        facts = {fact["key"] for fact in self.database.list_account_facts(user_id=int(user["id"]))}
        self.assertIn("name", facts)

    def test_the_signup_switch_and_cap_close_this_door_too(self) -> None:
        with mock.patch.dict("os.environ", {"PORTAL_WHATSAPP_SIGNUP_ENABLED": "0"}, clear=False):
            status, payload = self.register(registration())
        self.assertEqual((status, payload["error"]), (503, "registration_closed"))
        with mock.patch.dict("os.environ", {"PORTAL_WHATSAPP_SIGNUP_DAILY_CAP": "1"}, clear=False):
            self.assertEqual(self.register(registration())[0], 200)
            status, payload = self.register(registration(phone="+972507654321"))
        self.assertEqual((status, payload["error"]), (429, "registration_capped"))

    def test_the_page_is_served_at_register(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/register", timeout=10) as response:
            body = response.read().decode("utf-8")
        self.assertIn("/portal/register.js", body)
        self.assertIn("data-phone-country", body)
        self.assertNotIn('type="email"', body)
        # Someone who already has an account texts; they do not sign in.
        self.assertIn('Already have an account? <a href="/whatsapp">Open WhatsApp</a>', body)
        self.assertNotIn('<a href="/portal/">Sign in</a>', body)
        # Two questions and no choice to make: the name is the first.
        self.assertNotIn('name="kind"', body)
        self.assertNotIn('data-step="business"', body)
        self.assertNotIn("register-address.js", body)
        self.assertLess(body.index('data-step="name"'), body.index('data-step="phone"'))

    def test_the_old_family_address_still_serves_the_page_and_the_business_one_is_gone(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/register/family", timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("/portal/register.js", response.read().decode("utf-8"))
        status, _ = self.follow_nothing("/register/business")
        self.assertEqual(status, 404)

    def test_the_short_link_sends_an_existing_account_to_the_conversation(self) -> None:
        status, location = self.follow_nothing("/whatsapp")
        self.assertEqual(status, 303)
        self.assertEqual(location, "https://wa.me/972559196101?text=Hi%20Assistyca")

    def test_the_short_link_still_opens_a_door_with_no_number_configured(self) -> None:
        # A link that goes nowhere is worse than one that goes somewhere else.
        with mock.patch.dict("os.environ", {"ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": ""}, clear=False):
            status, location = self.follow_nothing("/whatsapp")
        self.assertEqual((status, location), (303, "/"))


class TemplateParameterTests(unittest.TestCase):
    def test_a_template_parameter_is_one_line(self) -> None:
        self.assertEqual(flatten_for_template("Hi\t  friend  "), "Hi friend")

    def test_a_template_parameter_folds_lines_into_sentences(self) -> None:
        # A morning plan written one run per line once reached the phone as a
        # single line with bullets stranded in the middle of it. Each line
        # becomes a sentence instead; a line already closed keeps its ending.
        plan = (
            "Today:\n"
            "- 08:00 Lahav — Shaked; you take, nobody collects yet\n"
            "• 08:15 Laor — gan. Gan is open.\n"
            "\n"
            "Have a great day 🙂"
        )
        self.assertEqual(
            flatten_for_template(plan),
            "Today: 08:00 Lahav — Shaked; you take, nobody collects yet. 08:15 Laor — gan. Gan is open. Have a great day 🙂",
        )


if __name__ == "__main__":
    unittest.main()
