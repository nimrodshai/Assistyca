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
from packages.infrastructure.whatsapp_agent_chat import SIGNUP_CONCIERGE_INSTRUCTIONS


class AssistantVoiceTests(unittest.TestCase):
    def test_every_prompt_the_person_reads_carries_the_voice(self) -> None:
        for name, instructions in (
            ("agent loop", AGENT_LOOP_INSTRUCTIONS),
            ("turn flow", AGENT_TURN_INSTRUCTIONS),
            ("answer composer", ANSWER_COMPOSER_INSTRUCTIONS),
            ("recovery reply", RECOVERY_INSTRUCTIONS),
            ("signup concierge", SIGNUP_CONCIERGE_INSTRUCTIONS),
        ):
            with self.subTest(prompt=name):
                self.assertIn(ASSISTANT_VOICE, instructions)

    def test_the_voice_asks_for_calm_rather_than_enthusiasm(self) -> None:
        # The point of the change: the person should put the phone down
        # holding less than they picked it up with.
        self.assertIn("calm and unhurried", ASSISTANT_VOICE)
        self.assertIn("holding less", ASSISTANT_VOICE)
        self.assertIn("no hype", ASSISTANT_VOICE)

    def test_the_whatsapp_channel_no_longer_asks_for_playful(self) -> None:
        # Warmth stays; the cheerfulness that talked over the answer does not.
        self.assertNotIn("playful", _CHANNEL_RULES["whatsapp"])
        self.assertIn("warm", _CHANNEL_RULES["whatsapp"].lower())


if __name__ == "__main__":
    unittest.main()
