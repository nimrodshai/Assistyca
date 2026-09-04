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


if __name__ == "__main__":
    unittest.main()
