"""What each lookup needs, declared once and checked before it runs."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_proposals import LOOKUP_SOURCE_REQUIREMENTS
from packages.infrastructure.agent_proposals import _AGENT_ANSWER_NOW_TYPES
from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.agent_proposals import connected_sources
from packages.infrastructure.agent_proposals import missing_sources_for_lookup


def _context(**connected: bool) -> dict:
    return {key: {"platformConnected": value, "connectionStatus": "connected" if value else "not_connected"} for key, value in connected.items()}


class LookupRequirementTests(unittest.TestCase):
    def test_every_runnable_lookup_declares_its_needs(self) -> None:
        # Absence of an entry must never be mistaken for absence of a need.
        self.assertEqual(set(LOOKUP_SOURCE_REQUIREMENTS), _AGENT_ANSWER_NOW_TYPES)

    def test_a_mailbox_is_gmail_or_outlook(self) -> None:
        self.assertEqual(missing_sources_for_lookup("email-digest", _context(gmail=True)), [])
        self.assertEqual(missing_sources_for_lookup("email-digest", _context(outlook=True)), [])
        self.assertEqual(missing_sources_for_lookup("email-digest", _context(gmail=False)), ["mailbox"])
        self.assertEqual(missing_sources_for_lookup("email-digest", {}), ["mailbox"])

    def test_a_disconnected_entry_does_not_count(self) -> None:
        self.assertEqual(connected_sources(_context(calendar=False, gmail=False)), set())
        self.assertEqual(missing_sources_for_lookup("calendar-summary", _context(calendar=False)), ["calendar"])

    def test_lookups_that_need_nothing_need_nothing(self) -> None:
        self.assertEqual(missing_sources_for_lookup("exchange-rate", {}), [])
        self.assertEqual(missing_sources_for_lookup("saved-files", {}), [])
        self.assertEqual(missing_sources_for_lookup("something-else", {}), [])

    def test_the_model_is_shown_the_same_declaration(self) -> None:
        prompt = build_agent_turn_prompt(user_message="hi", conversation=[], timezone_name="UTC")
        self.assertIn('"lookupRequirements":{"email-digest":["mailbox"]', prompt)
        self.assertIn("Every lookup needs what lookupRequirements lists for it", prompt)


if __name__ == "__main__":
    unittest.main()
