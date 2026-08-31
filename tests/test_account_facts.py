"""The things an account tells us once and should not be asked again.

Receipt pairing already worked this way: the owner is asked which of two
receipts is the real one, and the answer holds for every run afterwards. It
was the only question that got that treatment. Which currency a vendor bills
in, what a name is short for, when the business year starts - all of it was
re-asked or re-derived every month.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_proposals import AGENT_FACT_CONTEXT_MAX_ITEMS
from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.agent_proposals import normalize_agent_fact_context
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
from packages.infrastructure.portal_db import ACCOUNT_FACT_LIMIT
from packages.infrastructure.portal_db import PortalDatabase


class AccountFactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)

    def test_a_fact_is_kept_and_read_back(self) -> None:
        self.database.save_account_fact(
            user_id=self.user_id,
            key="render currency",
            fact="Render bills in US dollars.",
        )

        facts = self.database.list_account_facts(user_id=self.user_id)

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "render currency")
        self.assertEqual(facts[0]["fact"], "Render bills in US dollars.")

    def test_telling_us_again_corrects_what_we_had(self) -> None:
        # Two versions of the same fact is worse than one wrong one: nothing
        # says which of them is being applied.
        self.database.save_account_fact(user_id=self.user_id, key="render currency", fact="Dollars.")
        self.database.save_account_fact(user_id=self.user_id, key="Render Currency", fact="Shekels now.")

        facts = self.database.list_account_facts(user_id=self.user_id)

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact"], "Shekels now.")

    def test_a_fact_can_stop_being_true(self) -> None:
        self.database.save_account_fact(user_id=self.user_id, key="render currency", fact="Dollars.")

        self.assertTrue(self.database.forget_account_fact(user_id=self.user_id, key="render currency"))
        self.assertEqual(self.database.list_account_facts(user_id=self.user_id), [])

    def test_forgetting_something_we_never_knew_changes_nothing(self) -> None:
        self.assertFalse(self.database.forget_account_fact(user_id=self.user_id, key="nothing"))

    def test_half_a_fact_is_not_kept(self) -> None:
        with self.assertRaises(ValueError):
            self.database.save_account_fact(user_id=self.user_id, key="", fact="Dollars.")
        with self.assertRaises(ValueError):
            self.database.save_account_fact(user_id=self.user_id, key="render currency", fact="")

    def test_an_account_stops_remembering_before_it_remembers_everything(self) -> None:
        # Every one of these travels with every turn, so the oldest go first.
        for index in range(ACCOUNT_FACT_LIMIT + 10):
            self.database.save_account_fact(
                user_id=self.user_id,
                key=f"fact {index}",
                fact=f"Something number {index}.",
            )

        facts = self.database.list_account_facts(user_id=self.user_id)

        self.assertEqual(len(facts), ACCOUNT_FACT_LIMIT)
        self.assertIn("fact 49", [entry["key"] for entry in facts])
        self.assertNotIn("fact 0", [entry["key"] for entry in facts])

    def test_one_account_never_reads_another_account_facts(self) -> None:
        self.database.register_user("someone@example.com")
        other_id = int((self.database.get_user("someone@example.com") or {}).get("id") or 0)
        self.database.save_account_fact(user_id=other_id, key="render currency", fact="Theirs.")

        self.assertEqual(self.database.list_account_facts(user_id=self.user_id), [])

    def test_deleting_the_account_takes_its_facts_with_it(self) -> None:
        self.database.save_account_fact(user_id=self.user_id, key="render currency", fact="Dollars.")

        self.database.delete_user("owner@example.com")

        self.assertEqual(self.database.list_account_facts(user_id=self.user_id), [])


class AgentFactContextTests(unittest.TestCase):
    def test_the_facts_travel_with_the_turn(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="How much did Render come to?",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            fact_context=[{"key": "render currency", "fact": "Render bills in US dollars."}],
        )

        self.assertIn('"knownFacts"', prompt)
        self.assertIn("Render bills in US dollars.", prompt)
        self.assertIn("Read it before you ask anything", prompt)

    def test_half_a_fact_never_reaches_the_turn(self) -> None:
        facts = normalize_agent_fact_context([
            {"key": "render currency", "fact": "Dollars."},
            {"key": "", "fact": "Nothing to be about."},
            {"key": "no words", "fact": ""},
            {"key": "Render Currency", "fact": "A second copy."},
            "not a fact",
        ])

        self.assertEqual(facts, [{"key": "render currency", "fact": "Dollars."}])

    def test_the_context_is_capped(self) -> None:
        facts = normalize_agent_fact_context([
            {"key": f"fact {index}", "fact": "Something."} for index in range(100)
        ])

        self.assertEqual(len(facts), AGENT_FACT_CONTEXT_MAX_ITEMS)


class AgentFactTurnTests(unittest.TestCase):
    def test_a_fact_rides_along_with_the_answer(self) -> None:
        # A message can both answer a question and state something lasting.
        turn = normalize_agent_turn_response(
            {
                "outcome": "message",
                "reply": "Good to know — I'll read Render in dollars from now on.",
                "rememberFact": {"key": "render currency", "fact": "Render bills in US dollars."},
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["outcome"], "message")
        self.assertEqual(turn["rememberFact"], {
            "key": "render currency",
            "fact": "Render bills in US dollars.",
        })

    def test_half_a_fact_is_not_remembered(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "message",
                "reply": "Noted.",
                "rememberFact": {"fact": "Something with nothing to file it under."},
            },
            has_active_proposal=False,
        )

        self.assertNotIn("rememberFact", turn)

    def test_a_turn_that_remembers_nothing_carries_nothing(self) -> None:
        turn = normalize_agent_turn_response(
            {"outcome": "message", "reply": "Sure."},
            has_active_proposal=False,
        )

        self.assertNotIn("rememberFact", turn)
        self.assertNotIn("forgetFact", turn)

    def test_a_fact_can_be_dropped_from_the_chat(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "message",
                "reply": "I'll stop assuming that.",
                "forgetFact": "render currency",
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["forgetFact"], "render currency")


if __name__ == "__main__":
    unittest.main()
