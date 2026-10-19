"""Opening an account by texting the Assistyca number, with no invite."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.whatsapp_agent_chat import SIGNUP_AFTER_ERASURE_TEXT
from packages.infrastructure.whatsapp_agent_chat import build_whatsapp_signup_link


PLATFORM = "platform-phone-1"
APP_SECRET = "signup-test-secret"
NEW_PHONE = "447700900123"
NEW_HANDLE = f"wa-{NEW_PHONE}@whatsapp.assistyca.com"


def payload(text, *, sender=NEW_PHONE, message_id="wamid.s1", name="Dana", timestamp="1756700000"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
        "contacts": [{"profile": {"name": name}, "wa_id": sender}],
        "messages": [{"from": sender, "id": message_id, "timestamp": timestamp, "type": "text", "text": {"body": text}}],
    }}]}]}


class WhatsAppSignupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="signup-session-secret"))
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
        self.send_patch = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message",
            return_value="wamid.reply",
        )
        self.sent = self.send_patch.start()
        # The assistant answers the first message itself; the model is the
        # assistant's voice for these tests.
        self.model_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps({"outcome": "message", "reply": "Hi, I'm Assistyca. Who is at home?"})),
        )
        self.model = self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop()
        self.send_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def post(self, text, **kwargs) -> dict:
        body = json.dumps(payload(text, **kwargs)).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def replies(self) -> list[str]:
        return [call.kwargs["message_text"] for call in self.sent.call_args_list]

    def turn_text(self) -> str:
        return json.dumps(self.model.call_args.kwargs["input"], ensure_ascii=False)

    def test_a_strangers_first_message_opens_an_account_and_is_answered(self) -> None:
        first = self.post("How can you help me???", message_id="wamid.s1")

        # No email asked for, nothing to collect: the account opens on the
        # phone and the same message is answered by the assistant.
        self.assertEqual(
            [result["action"] for result in first["results"]],
            ["signup_completed_without_email", "agent_chat_reply"],
        )
        self.assertEqual(self.replies(), ["Hi, I'm Assistyca. Who is at home?"])
        self.assertNotIn("email", " ".join(self.replies()).lower())

        user = self.database.get_user(NEW_HANDLE) or {}
        self.assertTrue(user, "the account should exist now, keyed on the phone")
        self.assertEqual(user["displayName"], "Dana")
        self.assertEqual(user["trialDays"], 14, "two weeks free, then it pays")
        self.assertTrue(user["trialStartedAt"])
        self.assertNotIn("accountType", user)
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), int(user["id"]))
        self.assertEqual((self.database.get_whatsapp_signup(NEW_PHONE) or {}).get("status"), "completed")

        # Nobody has introduced the assistant, so its first turn does, and
        # goes straight on into getting to know the family.
        turn = self.turn_text()
        self.assertIn("texted the Assistyca number without registering", turn)
        self.assertIn("Getting to know this family", turn)
        self.assertIn("How can you help me???", turn)
        self.assertEqual(self.model.call_args.kwargs.get("billing_email"), NEW_HANDLE, "the account pays for its own turns")

    def test_once_answered_the_assistant_does_not_introduce_itself_again(self) -> None:
        self.post("hi", message_id="wamid.s1")
        second = self.post("my wife is Stav", message_id="wamid.s2")
        self.assertEqual(second["results"][0]["action"], "agent_chat_reply")
        self.assertNotIn("texted the Assistyca number without registering", self.turn_text())
        self.assertIn("my wife is Stav", self.turn_text())

    def test_a_message_sent_before_the_account_was_deleted_opens_nothing(self) -> None:
        # A deploy cut the turn off, Meta redelivered the message, and by then
        # the account it was written to had been deleted.
        self.database.mark_whatsapp_phones_erased([NEW_PHONE])
        before = str(int((datetime.now(timezone.utc) - timedelta(minutes=6)).timestamp()))

        result = self.post("delete my account please", message_id="wamid.late", timestamp=before)

        self.assertEqual(result["results"][0]["action"], "signup_ignored")
        self.assertEqual(result["results"][0]["reason"], "sent_before_erasure")
        self.assertEqual(self.sent.call_count, 0)
        self.assertEqual(self.model.call_count, 0)
        self.assertIsNone(self.database.get_user(NEW_HANDLE))

    def test_after_a_deletion_the_phone_is_told_once_and_the_next_message_starts_over(self) -> None:
        # "Thanks" after the goodbye must not silently reopen the account they
        # just asked to be rid of; the message after that is a fresh start.
        self.database.mark_whatsapp_phones_erased([NEW_PHONE])
        after = str(int((datetime.now(timezone.utc) + timedelta(seconds=5)).timestamp()))

        told = self.post("thanks", message_id="wamid.after", timestamp=after)
        self.assertEqual(told["results"][0]["action"], "signup_after_erasure")
        self.assertEqual(self.replies(), [SIGNUP_AFTER_ERASURE_TEXT])
        self.assertEqual(self.model.call_count, 0)
        self.assertIsNone(self.database.get_user(NEW_HANDLE))

        fresh = self.post("ok let's start again", message_id="wamid.again", timestamp=after)
        self.assertEqual(fresh["results"][0]["action"], "signup_completed_without_email")
        self.assertTrue(self.database.get_user(NEW_HANDLE))

    def test_a_deletion_is_forgotten_after_a_day(self) -> None:
        self.database.mark_whatsapp_phones_erased([NEW_PHONE])
        with self.database._connection() as conn:
            conn.execute("UPDATE erased_whatsapp_phones SET erased_at = ?",
                         ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),))
            conn.commit()
            stored = [row[0] for row in conn.execute("SELECT phone_hash FROM erased_whatsapp_phones")]
        self.assertIsNone(self.database.whatsapp_phone_erased_at(NEW_PHONE))
        self.assertTrue(stored and NEW_PHONE not in stored[0], "only a hash of the number is kept")

        # And a phone that writes then is simply new.
        result = self.post("hi", message_id="wamid.new")
        self.assertEqual(result["results"][0]["action"], "signup_completed_without_email")

    def test_the_daily_cap_closes_the_door_quietly(self) -> None:
        with mock.patch.dict("os.environ", {"PORTAL_WHATSAPP_SIGNUP_DAILY_CAP": "1"}, clear=False):
            self.post("hi", sender="447700900001", message_id="wamid.c1")
            sent_before = self.sent.call_count
            capped = self.post("hi", sender="447700900002", message_id="wamid.c2")
        self.assertEqual(capped["results"][0]["action"], "signup_capped")
        self.assertEqual(self.sent.call_count, sent_before)
        self.assertIsNone(self.database.get_whatsapp_signup("447700900002"))
        self.assertIsNone(self.database.get_user("wa-447700900002@whatsapp.assistyca.com"))

    def test_the_kill_switch_restores_silence(self) -> None:
        with mock.patch.dict("os.environ", {"PORTAL_WHATSAPP_SIGNUP_ENABLED": "0"}, clear=False):
            result = self.post("hi", message_id="wamid.k1")
        self.assertEqual(result["results"][0]["type"], "error")
        self.sent.assert_not_called()

    def test_a_claim_code_still_wins_over_signup(self) -> None:
        # An existing account linking a second phone sends a code from an
        # unknown number. That is a link, not a new account.
        self.database.register_user("owner@example.com")
        owner = self.database.get_user("owner@example.com") or {}
        self.database.create_whatsapp_claim_code(
            user_id=int(owner["id"]), code="AB2CD3",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
        result = self.post("Assistyca code AB2CD3", message_id="wamid.l1")
        self.assertEqual(result["results"][0]["action"], "number_claimed")
        self.assertIsNone(self.database.get_whatsapp_signup(NEW_PHONE))
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), int(owner["id"]))

    def test_the_public_link_opens_whatsapp_on_the_assistyca_number(self) -> None:
        self.assertEqual(build_whatsapp_signup_link(), "https://wa.me/972559196101?text=Hi%20Assistyca")

    def test_an_admin_can_see_where_the_door_stands(self) -> None:
        self.database.register_user("boss@example.com", is_admin=True)
        code, _ = self.server.store.issue_challenge("boss@example.com")
        ok, _, result = self.server.store.verify_code("boss@example.com", code)
        self.assertTrue(ok)
        token = str((result or {}).get("token") or "")
        self.post("hi", message_id="wamid.a1")

        request = urllib_request.Request(f"{self.base_url}/api/admin/whatsapp/signup",
                                         headers={"Authorization": f"Bearer {token}"})
        with urllib_request.urlopen(request, timeout=15) as response:
            status = json.loads(response.read().decode("utf-8"))

        self.assertTrue(status["ok"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["link"], "https://wa.me/972559196101?text=Hi%20Assistyca")
        self.assertEqual(status["startedToday"], 1)
        self.assertEqual(status["completedToday"], 1)
        self.assertEqual(status["defaultTrialDays"], 14)

    def _family_with_an_invitation(self, code: str = "ABC234", role: str = "partner", name: str = "Yoav") -> int:
        self.database.register_user("dana@example.com", display_name="Dana Levi")
        owner_id = int((self.database.get_user("dana@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=owner_id, wa_id="972500000001")
        member = self.database.save_household_member(user_id=owner_id, name=name, role=role)
        self.database.save_household_member(user_id=owner_id, name="Tom", role="child", age=4)
        self.database.save_household_activity(
            user_id=owner_id, title="Kindergarten", who=["Tom"], days=["sun", "mon"],
            start_time="07:30", end_time="16:00", drop_off_by="me", pick_up_by=name,
        )
        self.database.save_household_profile(user_id=owner_id, getting_to_know="done")
        self.database.create_household_invite(
            user_id=owner_id, member_id=int(member["id"]), code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        return owner_id

    def test_a_partner_joining_in_english_leaves_a_hebrew_family_in_hebrew(self) -> None:
        owner_id = self._family_with_an_invitation()
        self.database.save_household_profile(user_id=owner_id, language="he")
        turn = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps({"outcome": "message", "reply": "Hi Yoav, you're in."})),
        )
        with turn:
            self.post("Assistyca family ABC234", message_id="wamid.lang1", name="Yoav")
            member = self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id) or {}
            # The link's own words are nobody's language.
            self.assertEqual(member.get("language"), "")
            self.post("Thanks, see you on Sunday", message_id="wamid.lang2", name="Yoav")
        member = self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id) or {}
        self.assertEqual(member.get("language"), "en", "what Yoav writes is Yoav's")
        self.assertEqual(
            (self.database.get_household_profile(user_id=owner_id) or {}).get("language"), "he",
            "and never the account holder's",
        )

    def test_an_invited_phone_joins_the_family_and_talks_in_its_own_thread(self) -> None:
        owner_id = self._family_with_an_invitation()
        turn = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps({"outcome": "message", "reply": "Hi Yoav, you're in."})),
        )
        with turn as model:
            result = self.post("Assistyca family ABC234", message_id="wamid.j1", name="Yoav")
        actions = [entry["action"] for entry in result["results"]]
        self.assertEqual(actions, ["member_joined", "agent_chat_reply"], result)
        # No account was opened for the phone: it is Dana's account now, as Yoav.
        self.assertIsNone(self.database.get_whatsapp_signup(NEW_PHONE))
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), owner_id)
        self.assertEqual(self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id)["name"], "Yoav")
        # The welcome is the assistant's own first turn with Yoav, told who is
        # writing and that this is the first thing said on this phone.
        context_text = json.dumps(model.call_args.kwargs["input"], ensure_ascii=False)
        self.assertIn('\\"speaker\\"', context_text)
        self.assertIn('\\"name\\":\\"Yoav\\"', context_text)
        self.assertIn('\\"firstConversation\\":true', context_text)
        self.assertIn('\\"accountHolder\\":\\"Dana Levi\\"', context_text)
        self.assertEqual(self.replies()[-1], "Hi Yoav, you're in.")
        # Yoav's conversation is his own, not Dana's.
        yours = self.database.list_recent_whatsapp_agent_messages(user_id=owner_id, thread_id=f"phone:{NEW_PHONE}")
        self.assertEqual([m["role"] for m in yours], ["user", "assistant"])
        self.assertEqual(self.database.list_recent_whatsapp_agent_messages(user_id=owner_id), [])
        # Dana is told, on her own phone, by a line the assistant writes.
        [note] = [a for a in self.database.list_scheduled_actions_for_user(owner_id, limit=20) if a["payload"].get("title") == "Yoav joined"]
        self.assertEqual((note["recipientRef"], note["channel"]), ("owner", "whatsapp"))
        self.assertIn("Yoav (partner) has just joined", note["payload"]["instruction"])
        self.assertEqual(note["payload"]["fallbackText"], "Yoav is in 👍")

        # From here the phone is Yoav talking to the assistant, as himself.
        with turn as model:
            second = self.post("what's on today?", message_id="wamid.j2", name="Yoav")
        self.assertEqual(second["results"][0]["action"], "agent_chat_reply")
        context_text = json.dumps(model.call_args.kwargs["input"], ensure_ascii=False)
        self.assertIn('\\"drivesAs\\":\\"Yoav\\"', context_text)
        self.assertNotIn('\\"firstConversation\\":true', context_text)

    def composed(self, reply: str = "COMPOSED REPLY"):
        """The model as two voices: the recovery composer writes the words a
        refusal goes out in, the assistant answers everything else."""

        prompts: list[dict] = []

        def respond(**kwargs):
            if kwargs.get("tool_name") == "portal_recovery_composer":
                prompts.append({"prompt": kwargs.get("prompt") or "", "billing_email": kwargs.get("billing_email")})
                return SimpleNamespace(output_text=reply)
            return SimpleNamespace(output_text=json.dumps({"outcome": "message", "reply": "Hi, you're in."}))

        self.model.side_effect = respond
        return prompts

    def test_an_invitation_code_from_the_wrong_phone_joins_nothing(self) -> None:
        owner_id = self._family_with_an_invitation(code="RNA333", role="other", name="Rina")
        prompts = self.composed()
        # Dana taps her own link: the link is for Rina to open.
        result = self.post("Assistyca family RNA333", sender="972500000001", message_id="wamid.w1", name="Dana")
        self.assertEqual(result["results"][0]["action"], "join_link_not_for_this_phone")
        self.assertEqual(self.replies()[-1], "COMPOSED REPLY")
        self.assertIn("for Rina to open on their own phone", prompts[-1]["prompt"])
        self.assertEqual(self.database.get_household_invite("RNA333")["status"], "live")
        # Somebody with an account of their own cannot be moved into the family.
        self.database.register_user("else@example.com")
        self.database.link_user_whatsapp_number(user_id=int(self.database.get_user("else@example.com")["id"]), wa_id="972500000077")
        result = self.post("Assistyca family RNA333", sender="972500000077", message_id="wamid.w2", name="Else")
        self.assertEqual(result["results"][0]["action"], "join_link_not_for_this_phone")
        self.assertIn("its own Assistyca account, belonging to the person writing", prompts[-1]["prompt"])
        self.assertTrue(self.database.get_user("else@example.com"))
        # Rina joins; the spent code from yet another stranger is refused, and
        # no account is opened for that stranger either.
        joined = self.post("Assistyca family RNA333", message_id="wamid.w3", name="Rina")
        self.assertEqual(joined["results"][0]["action"], "member_joined")
        self.assertEqual(joined["results"][0]["role"], "other")
        self.assertEqual(self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id)["name"], "Rina")
        late = self.post("Assistyca family RNA333", sender="447700900999", message_id="wamid.w4", name="Late")
        self.assertEqual((late["results"][0]["action"], late["results"][0]["reason"]), ("join_rejected", "already_claimed"))
        self.assertIn("already been used", prompts[-1]["prompt"])
        self.assertIsNone(self.database.get_whatsapp_signup("447700900999"))
        self.assertIsNone(self.database.get_user("wa-447700900999@whatsapp.assistyca.com"))

    def test_a_phone_that_texted_first_still_joins_with_the_link(self) -> None:
        # Yoav wrote "hi" before he tapped the link, and that opened an
        # account of his own. It holds nothing but the conversation, so the
        # invitation takes it over rather than turning him away.
        owner_id = self._family_with_an_invitation()
        self.composed()
        first = self.post("hi", message_id="wamid.t1", name="Yoav")
        self.assertEqual(first["results"][0]["action"], "signup_completed_without_email")
        self.assertTrue(self.database.get_user(NEW_HANDLE))

        joined = self.post("Assistyca family ABC234", message_id="wamid.t2", name="Yoav")
        actions = [entry["action"] for entry in joined["results"]]
        self.assertEqual(actions, ["member_joined", "agent_chat_reply"], joined)
        self.assertTrue(joined["results"][0]["folded_own_account"])
        self.assertIsNone(self.database.get_user(NEW_HANDLE), "the empty account gave way")
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), owner_id)
        self.assertEqual(self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id)["name"], "Yoav")
        self.assertEqual(self.replies()[-1], "Hi, you're in.")

    def test_an_own_account_with_something_in_it_is_never_taken_over(self) -> None:
        self._family_with_an_invitation()
        prompts = self.composed()
        self.post("hi", message_id="wamid.o1", name="Yoav")
        own = self.database.get_user(NEW_HANDLE) or {}
        self.database.save_household_member(user_id=int(own["id"]), name="Maya", role="child", age=6)

        refused = self.post("Assistyca family ABC234", message_id="wamid.o2", name="Yoav")
        self.assertEqual(refused["results"][0]["action"], "join_link_not_for_this_phone")
        self.assertEqual(refused["results"][0]["reason"], "number_taken")
        self.assertTrue(self.database.get_user(NEW_HANDLE), "an account with a family in it stays")
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), int(own["id"]))
        self.assertIn("its own Assistyca account, belonging to the person writing, with things kept in it", prompts[-1]["prompt"])
        self.assertIn('"reader":{"name":"Yoav"}', prompts[-1]["prompt"])
        self.assertEqual(self.replies()[-1], "COMPOSED REPLY")

    def test_a_member_of_another_family_is_told_that_not_about_an_account_of_their_own(self) -> None:
        self._family_with_an_invitation()
        prompts = self.composed()
        self.database.register_user("other@example.com", display_name="Other Parent")
        other_id = int(self.database.get_user("other@example.com")["id"])
        member = self.database.save_household_member(user_id=other_id, name="Yoav", role="other")
        self.database.create_household_invite(
            user_id=other_id, member_id=int(member["id"]), code="PTH234",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.post("Assistyca family PTH234", message_id="wamid.m1", name="Yoav")
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), other_id)

        refused = self.post("Assistyca family ABC234", message_id="wamid.m2", name="Yoav")
        self.assertEqual(refused["results"][0]["reason"], "number_taken")
        self.assertIn("already part of another family", prompts[-1]["prompt"])
        self.assertNotIn("its own Assistyca account", prompts[-1]["prompt"])
        self.assertIn('"say":"sign out"', prompts[-1]["prompt"])

    def test_words_before_the_join_phrase_do_not_hide_the_code(self) -> None:
        # THANKS has the shape of a code; the code is the one after "family".
        owner_id = self._family_with_an_invitation(code="YE7MJU")
        self.composed()
        joined = self.post("THANKS Assistyca family YE7MJU", message_id="wamid.p1", name="Yoav")
        self.assertEqual(joined["results"][0]["action"], "member_joined", joined)
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), owner_id)

    def test_a_replaced_link_is_told_so_in_the_familys_language_and_opens_nothing(self) -> None:
        owner_id = self._family_with_an_invitation(code="PLD234")
        self.database.save_household_profile(user_id=owner_id, language="he")
        yoav = next(m for m in self.database.list_household_members(user_id=owner_id) if m["name"] == "Yoav")
        self.database.create_household_invite(
            user_id=owner_id, member_id=int(yoav["id"]), code="NEW234",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        prompts = self.composed("הקישור הזה כבר לא בתוקף")
        refused = self.post("Assistyca family PLD234", message_id="wamid.r1", name="Yoav")
        self.assertEqual((refused["results"][0]["action"], refused["results"][0]["reason"]), ("join_rejected", "expired"))
        self.assertEqual(len(refused["results"]), 1, "nothing else ran: no signup, no turn")
        self.assertIsNone(self.database.get_whatsapp_signup(NEW_PHONE))
        self.assertIsNone(self.database.get_user(NEW_HANDLE))
        self.assertEqual(self.replies()[-1], "הקישור הזה כבר לא בתוקף")
        self.assertIn('"language":"he"', prompts[-1]["prompt"])
        self.assertIn("a newer link has replaced it", prompts[-1]["prompt"])
        self.assertIn('"names":{"accountHolder":"Dana"}', prompts[-1]["prompt"])
        self.assertIn('"reader":{"name":"Yoav"}', prompts[-1]["prompt"])
        self.assertEqual(prompts[-1]["billing_email"], "dana@example.com")

        # A mistyped code with nobody behind it is refused the same way, in
        # the language of what they wrote around it.
        mistyped = self.post("שלום Assistyca family ZZZ234", message_id="wamid.r2", name="Yoav")
        self.assertEqual(mistyped["results"][0]["reason"], "unknown_code")
        self.assertIn('"language":"he"', prompts[-1]["prompt"])
        # Their code did not match; nothing of ours failed, and the facts say so.
        self.assertIn("does not match any invitation", prompts[-1]["prompt"])
        self.assertIn("Nothing went wrong on Assistyca's side", prompts[-1]["prompt"])
        self.assertIn("for any other code never say something went wrong on your side", prompts[-1]["prompt"])
        self.assertIsNone(self.database.get_user(NEW_HANDLE))

        # The newer link still works.
        joined = self.post("Assistyca family NEW234", message_id="wamid.r3", name="Yoav")
        self.assertEqual(joined["results"][0]["action"], "member_joined")

    def test_someone_taken_off_the_family_is_told_once_then_starts_over(self) -> None:
        owner_id = self._family_with_an_invitation()
        prompts = self.composed()
        self.post("Assistyca family ABC234", message_id="wamid.x1", name="Yoav")
        self.assertTrue(self.database.remove_household_member(user_id=owner_id, name="Yoav"))
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), 0)

        told = self.post("what's on today?", message_id="wamid.x2", name="Yoav")
        self.assertEqual(told["results"][0]["action"], "told_taken_off_family")
        self.assertIsNone(self.database.get_user(NEW_HANDLE), "no account of their own opened")
        self.assertIn("The account holder took the person writing off the family", prompts[-1]["prompt"])
        self.assertIn('"reader":{"name":"Yoav"}', prompts[-1]["prompt"])
        self.assertIn('"names":{"accountHolder":"Dana"}', prompts[-1]["prompt"])
        self.assertIn("speak to them directly, as you, by situation.reader.name", prompts[-1]["prompt"])
        self.assertIn("fresh invitation link", prompts[-1]["prompt"])

        fresh = self.post("ok, then I want my own", message_id="wamid.x3", name="Yoav")
        self.assertEqual(fresh["results"][0]["action"], "signup_completed_without_email")

    def test_someone_taken_off_is_told_in_their_own_language_and_form(self) -> None:
        owner_id = self._family_with_an_invitation()
        prompts = self.composed("הוסרת מהמשפחה")
        self.post("Assistyca family ABC234", message_id="wamid.h1", name="Yoav")
        yoav = self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id)
        self.database.save_household_member_language(user_id=owner_id, member_id=int(yoav["id"]), language="he")
        self.database.save_household_member_address_form(user_id=owner_id, member_id=int(yoav["id"]), address_form="m", address_basis="self")
        self.assertTrue(self.database.remove_household_member(user_id=owner_id, name="Yoav"))

        told = self.post("👍", message_id="wamid.h2", name="Yoav")
        self.assertEqual(told["results"][0]["action"], "told_taken_off_family")
        self.assertIn('"language":"he"', prompts[-1]["prompt"])
        self.assertIn('"reader":{"name":"Yoav","addressAs":"a man"}', prompts[-1]["prompt"])
        self.assertEqual(self.replies()[-1], "הוסרת מהמשפחה")

    def model_down(self) -> None:
        from packages.infrastructure.openai_api import OpenAIRequestError

        self.model.side_effect = OpenAIRequestError("You exceeded your current quota.")

    def test_with_the_model_down_a_partner_who_joined_is_simply_welcomed(self) -> None:
        self._family_with_an_invitation()
        self.model_down()
        joined = self.post("Assistyca family ABC234", message_id="wamid.d1", name="Yoav")
        self.assertEqual(joined["results"][0]["action"], "member_joined", joined)
        reply = self.replies()[-1]
        self.assertTrue(reply.startswith("Welcome, Yoav - you're in Dana's family on Assistyca now."), reply)
        self.assertNotIn("went wrong", reply)

    def test_with_the_model_down_a_mistyped_code_is_told_in_plain_words(self) -> None:
        self._family_with_an_invitation()
        self.model_down()
        refused = self.post("Assistyca family ZZZ999", message_id="wamid.d2", name="Yoav")
        self.assertEqual(refused["results"][0]["reason"], "unknown_code")
        reply = self.replies()[-1]
        self.assertTrue(reply.startswith("That invitation code doesn't match any invitation"), reply)
        self.assertNotIn("person writing", reply)
        self.assertNotIn("Assistyca's side", reply)

    def test_with_the_model_down_someone_taken_off_is_told_so_and_an_unsent_note_is_tried_again(self) -> None:
        owner_id = self._family_with_an_invitation()
        self.composed()
        self.post("Assistyca family ABC234", message_id="wamid.d3", name="Yoav")
        self.assertTrue(self.database.remove_household_member(user_id=owner_id, name="Yoav"))
        self.model_down()

        # The note does not leave: they have not been told, so the next
        # message tells them.
        self.sent.side_effect = [RuntimeError("WhatsApp is down")]
        failed = self.post("what's on today?", message_id="wamid.d4", name="Yoav")
        self.assertEqual(failed["results"][0]["action"], "told_taken_off_family")
        self.assertIsNotNone(self.database.get_household_departure(NEW_PHONE))

        self.sent.side_effect = None
        told = self.post("hello?", message_id="wamid.d5", name="Yoav")
        self.assertEqual(told["results"][0]["action"], "told_taken_off_family")
        reply = self.replies()[-1]
        self.assertTrue(reply.startswith("Dana took you off the family's account on Assistyca"), reply)
        self.assertIn("ask Dana for a fresh invitation link", reply)
        self.assertNotIn("of their own", reply)
        self.assertIsNone(self.database.get_household_departure(NEW_PHONE), "told once, and only once")

    def test_with_the_model_down_someone_taken_off_hears_it_in_hebrew(self) -> None:
        owner_id = self._family_with_an_invitation()
        self.composed()
        self.post("Assistyca family ABC234", message_id="wamid.d6", name="Yoav")
        yoav = self.database.get_household_member_by_wa_id(NEW_PHONE, user_id=owner_id)
        self.database.save_household_member_language(user_id=owner_id, member_id=int(yoav["id"]), language="he")
        self.assertTrue(self.database.remove_household_member(user_id=owner_id, name="Yoav"))
        self.model_down()
        self.post("👍", message_id="wamid.d7", name="Yoav")
        reply = self.replies()[-1]
        self.assertTrue(reply.startswith("הוסרת מהחשבון המשפחתי"), reply)
        self.assertIn("לבקש מ-Dana קישור הזמנה חדש", reply)

if __name__ == "__main__":
    unittest.main()
