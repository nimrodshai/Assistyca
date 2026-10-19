"""A situation report always becomes a reply with a way forward.

Every failure path used to end in a sentence written for one case. Now each
one is a report, and the two things every reply must do - say what happened,
say what to do next - are properties of the report rather than of the wording,
so they hold for every code and every mix of options without a test per case.
"""

from __future__ import annotations

import itertools
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.recovery_reply import RECOVERY_CODES
from packages.infrastructure.recovery_reply import build_recovery_prompt
from packages.infrastructure.recovery_reply import build_situation
from packages.infrastructure.recovery_reply import computed_recovery_sentence
from packages.infrastructure.recovery_reply import guard_recovery_reply
from packages.infrastructure.recovery_reply import make_option
from packages.infrastructure.recovery_reply import normalize_situation

GOOGLE = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=y"
NEXT_STEP_WORDS = ("https://", "reply", "ask me again", "tell me")


def _has_way_forward(reply: str) -> bool:
    lowered = reply.lower()
    return any(word in lowered for word in NEXT_STEP_WORDS)


class ComputedSentenceProperties(unittest.TestCase):
    def test_every_code_and_option_mix_says_what_happened_and_what_next(self) -> None:
        option_sets = [
            [],
            [make_option("retry")],
            [make_option("connect", provider="google", link=GOOGLE)],
            [make_option("say", say="connect my email")],
            [make_option("choose", label="which calendars I should read")],
            [make_option("connect", provider="google", link=GOOGLE), make_option("retry")],
        ]
        for code, options, can_retry in itertools.product(sorted(RECOVERY_CODES), option_sets, (False, True)):
            with self.subTest(code=code, options=[o["kind"] for o in options], can_retry=can_retry):
                situation = build_situation(code, request="check my mail", options=options, can_retry=can_retry)
                sentence = computed_recovery_sentence(situation)
                self.assertTrue(sentence.strip())
                self.assertTrue(_has_way_forward(sentence), sentence)
                # The sentence has two parts: what happened, then the step.
                self.assertGreaterEqual(len(sentence.split(". ")), 1)

    def test_a_connect_link_wins_over_a_retry(self) -> None:
        situation = build_situation(
            "source_not_connected",
            what_happened="Reading your email needs a connected mailbox.",
            can_retry=True,
            options=[make_option("retry"), make_option("connect", provider="google", link=GOOGLE)],
        )
        sentence = computed_recovery_sentence(situation)
        self.assertIn(GOOGLE, sentence)
        self.assertNotIn("Ask me again", sentence)

    def test_our_own_failure_is_not_handed_back_as_a_chore(self) -> None:
        # "Ask me again in a moment" made the person do the retrying for a
        # failure that was ours, and when the cause was systemic - the
        # provider out of credits - asking again gave the same apology.
        sentence = computed_recovery_sentence(build_situation("assistant_unavailable"))
        self.assertIn("on my side", sentence)
        self.assertIn("mine to sort out", sentence)
        self.assertNotIn("Ask me again", sentence)
        self.assertNotIn("think that through", sentence)
        # The prompt tells the composer the same thing.
        prompt = build_recovery_prompt(build_situation("assistant_unavailable"), conversation=[], channel="whatsapp", today="2026-09-29")
        self.assertIn("never tell them to send it again", prompt)

    def test_a_hebrew_family_gets_the_floor_in_hebrew_for_every_code(self) -> None:
        import re

        for code in sorted(RECOVERY_CODES):
            for options in ([], [make_option("retry")], [make_option("connect", link=GOOGLE)], [make_option("say", say="sign out")],
                            [make_option("step", label="ask Dana for a fresh invitation link")]):
                with self.subTest(code=code, options=[o["kind"] for o in options]):
                    sentence = computed_recovery_sentence(
                        build_situation(code, what_happened="That can't run here.", options=options), language="he",
                    )
                    words = re.sub(r"https://\S+|\"[^\"]*\"", "", sentence)
                    self.assertRegex(words, r"[א-ת]")
                    self.assertNotRegex(words, r"[A-Za-z]", sentence)

    def test_a_long_option_is_cut_between_words(self) -> None:
        label = (
            "if that was a mistake, ask the account holder for a fresh invitation link; for an assistant of "
            "their own instead, just write again - and in the meantime nothing set for this phone goes on running at all, "
            "not the reminders and not the standing actions"
        )
        self.assertGreater(len(label), 240)
        option = make_option("step", label=label)
        self.assertTrue(label.startswith(option["label"]))
        self.assertTrue(label[len(option["label"]):].startswith(" "), option["label"])
        short = make_option("step", label="if that was a mistake, ask the account holder for a fresh invitation link; for an assistant of their own instead, just write again")
        self.assertTrue(short["label"].endswith("just write again"))

    def test_the_floor_speaks_to_the_reader_and_names_the_account_holder(self) -> None:
        sentence = computed_recovery_sentence(build_situation(
            "not_supported",
            what_happened="The account holder took the person writing off the family's account on Assistyca.",
            reader={"name": "Yoav"}, names={"accountHolder": "Dana"},
        ))
        self.assertTrue(sentence.startswith("Dana took you off the family's account on Assistyca."), sentence)

    def test_a_situation_with_its_own_floor_is_said_with_it_and_the_model_never_sees_it(self) -> None:
        situation = build_situation(
            "not_supported", what_happened="The code the person writing sent matches nothing.",
            floor={"en": "That code doesn't match any invitation.", "he": "הקוד הזה לא תואם אף הזמנה.", "fr": "x"},
        )
        self.assertEqual(computed_recovery_sentence(situation), "That code doesn't match any invitation.")
        self.assertEqual(computed_recovery_sentence(situation, language="he"), "הקוד הזה לא תואם אף הזמנה.")
        self.assertEqual(set(situation["floor"]), {"en", "he"})
        prompt = build_recovery_prompt(situation, channel="whatsapp")
        self.assertNotIn("floor", prompt)
        self.assertNotIn("doesn't match any invitation", prompt)
        self.assertNotIn("floor", build_situation("internal"))

    def test_no_retry_means_no_retry_offered(self) -> None:
        sentence = computed_recovery_sentence(build_situation("not_supported", what_happened="That can't run here."))
        self.assertNotIn("again", sentence)
        self.assertIn("Tell me", sentence)


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.situation = build_situation(
            "source_not_connected",
            what_happened="Gmail was disconnected a minute ago.",
            options=[make_option("connect", provider="google", link=GOOGLE)],
        )

    def test_a_good_reply_passes_untouched(self) -> None:
        reply = f"I can't read your inbox right now because Gmail was disconnected. Reconnect it here, it takes a few seconds:\n{GOOGLE}"
        self.assertEqual(guard_recovery_reply(reply, self.situation), reply)

    def test_a_link_that_was_not_offered_sends_the_reply_back(self) -> None:
        reply = "Reconnect at https://example.com/login and I'll carry on."
        guarded = guard_recovery_reply(reply, self.situation)
        self.assertNotIn("example.com", guarded)
        self.assertIn(GOOGLE, guarded)

    def test_machinery_words_send_the_reply_back(self) -> None:
        guarded = guard_recovery_reply("OpenAI timed out, sorry.", self.situation)
        self.assertNotIn("OpenAI", guarded)
        self.assertIn(GOOGLE, guarded)

    def test_a_reply_that_forgot_the_link_is_given_it(self) -> None:
        guarded = guard_recovery_reply("Reconnect Gmail with the link and I'll check today's mail.", self.situation)
        self.assertTrue(guarded.endswith(GOOGLE))

    def test_an_empty_reply_becomes_the_assembled_sentence(self) -> None:
        self.assertEqual(guard_recovery_reply("", self.situation), computed_recovery_sentence(self.situation))

    def test_code_fences_are_packaging(self) -> None:
        guarded = guard_recovery_reply(f"```\nReconnect here:\n{GOOGLE}\n```", self.situation)
        self.assertNotIn("```", guarded)
        self.assertIn(GOOGLE, guarded)


class SituationShapeTests(unittest.TestCase):
    def test_an_unknown_code_is_internal(self) -> None:
        self.assertEqual(build_situation("something_new")["code"], "internal")

    def test_a_link_off_the_sign_in_hosts_is_dropped(self) -> None:
        option = make_option("connect", link="https://evil.example/steal")
        self.assertNotIn("link", option)
        option = make_option("connect", link="http://accounts.google.com/plain")
        self.assertNotIn("link", option)
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://assistyca.com", "GOOGLE_OAUTH_REDIRECT_URI": "",
                                            "MICROSOFT_OAUTH_REDIRECT_URI": ""}):
            option = make_option("connect", link="https://assistyca.com/connect/google?s=abc")
            self.assertEqual(option["link"], "https://assistyca.com/connect/google?s=abc", "our own sign-in link opens on our site")
            option = make_option("connect", link="https://evil.example/connect/google?s=abc")
            self.assertNotIn("link", option, "the sign-in path on someone else's site is still someone else's site")

    def test_a_report_over_the_wire_is_read_as_data(self) -> None:
        situation = normalize_situation({
            "code": "SOURCE_NOT_CONNECTED",
            "request": "  what's   new  ",
            "whatHappened": ["not", "a", "string"],
            "canRetry": "yes",
            "options": [{"kind": "connect", "link": "https://evil.example/x"}, {"kind": "say", "say": "connect my email"}, "junk"],
        })
        self.assertEqual(situation["code"], "source_not_connected")
        self.assertEqual(situation["request"], "what's new")
        self.assertFalse(situation["canRetry"])
        self.assertEqual([o["kind"] for o in situation["options"]], ["connect", "say"])
        self.assertNotIn("link", situation["options"][0])

    def test_the_prompt_carries_the_channel_rule_and_the_report(self) -> None:
        prompt = build_recovery_prompt(
            build_situation("assistant_unavailable", what_happened="I couldn't think that through."),
            conversation=[{"role": "user", "text": "hi"}],
            channel="whatsapp",
            today="2026-09-04",
        )
        self.assertIn("WhatsApp text message", prompt)
        self.assertIn('"code":"assistant_unavailable"', prompt)
        self.assertIn('"recentConversation":[{"role":"user","text":"hi"}]', prompt)


    def test_a_situation_about_its_reader_names_them_apart_and_asks_to_be_said_to_them(self) -> None:
        situation = normalize_situation(build_situation(
            "not_supported", what_happened="The account holder took the person writing off the family.",
            reader={"name": "Yoav", "addressAs": "a man", "phone": "972500000002"},
            names={"accountHolder": "Dana", "": "nobody"},
        ))
        self.assertEqual(situation["reader"], {"name": "Yoav", "addressAs": "a man"})
        self.assertEqual(situation["names"], {"accountHolder": "Dana"})
        prompt = build_recovery_prompt(situation, channel="whatsapp")
        self.assertIn("speak to them directly, as you, by situation.reader.name", prompt)
        self.assertNotIn("reader", build_situation("internal"))

if __name__ == "__main__":
    unittest.main()
