"""One voice, wherever the assistant happens to be writing from.

The assistant answers through several prompts - the main loop, the answer a
lookup feeds, the sentence for when something got in the way, the turn flow in
the browser, the conversation before there is an account. Each used to carry
its own line about tone, and four descriptions of one voice drift: the reply
about last month's spend ends up sounding nothing like the reply about a
mailbox that will not open.

These tests pin the arrangement that replaced it. The voice is written once
and every user-facing prompt quotes it, so a new prompt that forgets to fails
here rather than in someone's chat.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS
from packages.infrastructure.agent_loop import _CHANNEL_RULES
from packages.infrastructure.agent_proposals import AGENT_TURN_INSTRUCTIONS
from packages.infrastructure.answer_composer import ANSWER_COMPOSER_INSTRUCTIONS
from packages.infrastructure.assistant_voice import ASSISTANT_VOICE
from packages.infrastructure.recovery_reply import RECOVERY_INSTRUCTIONS
from packages.infrastructure.reply_judge import JUDGE_INSTRUCTIONS
from packages.infrastructure.reply_judge import RUBRIC
from packages.infrastructure.reply_judge import low_points
from packages.infrastructure.whatsapp_agent_chat import RESUME_ASK_INSTRUCTIONS
from packages.infrastructure.whatsapp_agent_chat import SIGNUP_CONCIERGE_INSTRUCTIONS


class AssistantVoiceTests(unittest.TestCase):
    def test_every_prompt_the_person_reads_carries_the_voice(self) -> None:
        for name, instructions in (
            ("agent loop", AGENT_LOOP_INSTRUCTIONS),
            ("turn flow", AGENT_TURN_INSTRUCTIONS),
            ("answer composer", ANSWER_COMPOSER_INSTRUCTIONS),
            ("recovery reply", RECOVERY_INSTRUCTIONS),
            ("signup concierge", SIGNUP_CONCIERGE_INSTRUCTIONS),
            ("resume ask", RESUME_ASK_INSTRUCTIONS),
        ):
            with self.subTest(prompt=name):
                self.assertIn(ASSISTANT_VOICE, instructions)

    def test_the_voice_asks_for_calm_rather_than_enthusiasm(self) -> None:
        # The point of the change: the person should put the phone down
        # holding less than they picked it up with.
        self.assertIn("calm and unhurried", ASSISTANT_VOICE)
        self.assertIn("holding less", ASSISTANT_VOICE)
        self.assertIn("no hype", ASSISTANT_VOICE)

    def test_the_voice_keeps_the_reading_to_itself(self) -> None:
        # Being told your mail is being gone through is unsettling however
        # kindly it is put; what comes back to the person is the part that is
        # theirs.
        self.assertIn("Never announce that you are about to go through their mail", ASSISTANT_VOICE)
        self.assertIn("what may come back to them", ASSISTANT_VOICE)

    def test_the_voice_picks_a_thread_up_instead_of_quoting_it(self) -> None:
        self.assertIn("quoting their message back at them", ASSISTANT_VOICE)

    def test_the_whatsapp_channel_no_longer_asks_for_playful(self) -> None:
        # Warmth stays; the cheerfulness that talked over the answer does not.
        self.assertNotIn("playful", _CHANNEL_RULES["whatsapp"])
        self.assertIn("warm", _CHANNEL_RULES["whatsapp"].lower())


class JudgedForCalmTests(unittest.TestCase):
    """The voice asked for in the prompt is also the voice scored afterwards.

    Without this the only guard on tone is a prompt that says the word calm,
    which proves what was asked for and nothing about what came back.
    """

    def test_the_judge_scores_calm_alongside_the_other_points(self) -> None:
        self.assertIn("calm", RUBRIC)
        self.assertIn("on each of six points", JUDGE_INSTRUCTIONS)
        self.assertIn('"calm":n', JUDGE_INSTRUCTIONS)

    def test_calm_is_scored_for_what_is_absent_not_for_style(self) -> None:
        # A rubric that rewarded calm as a quality would push replies towards
        # the precious. The criterion has to hand a plain answer full marks.
        self.assertIn("A plain reply that answers and stops is a 5", JUDGE_INSTRUCTIONS)
        self.assertIn("is not pressure", JUDGE_INSTRUCTIONS)

    def test_a_reply_that_fails_only_on_calm_is_caught(self) -> None:
        scores = {key: 5 for key in RUBRIC}
        scores["calm"] = 1
        self.assertEqual(low_points(scores), ["calm"])
        self.assertEqual(low_points({key: 5 for key in RUBRIC}), [])


if __name__ == "__main__":
    unittest.main()
