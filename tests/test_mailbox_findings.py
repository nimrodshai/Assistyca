"""Mailbox findings: the reading and the deriving, with no network.

What these prove: a reply from the model is read into facts and put back on
the right messages; a bill and a renewal coming up are found in their
windows; a recurring charge that went up is found with its old and new
price; and the instruction and fallback the person gets carry the figures
as written.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import mailbox_findings as mf

TODAY = date(2026, 9, 8)


def _fact(kind: str, **fields) -> dict:
    base = {
        "mailbox": "owner@example.com",
        "messageId": fields.pop("messageId", f"m-{kind}-{fields.get('messageDate', '')}-{fields.get('counterparty', '')}"),
        "subject": fields.pop("subject", kind),
        "messageDate": "2026-08-01",
        "kind": kind,
        "counterparty": "",
        "amount": None,
        "currency": "",
        "documentDate": "",
        "dueOn": "",
        "reference": "",
        "recurring": False,
    }
    base.update(fields)
    return base


class ReadingTests(unittest.TestCase):
    def test_a_fenced_reply_is_read_and_unknown_refs_and_kinds_are_dropped(self) -> None:
        candidates = [{"ref": "1"}, {"ref": "2"}]
        reply = "```json\n" + json.dumps({"facts": [
            {"ref": "1", "kind": "bill", "counterparty": "Acme Ltd", "amount": "1,200.00", "currency": "ils", "documentDate": "2026-07-01", "reference": "INV-17"},
            {"ref": "2", "kind": "advert"},
            {"ref": "9", "kind": "charge", "amount": 5},
        ]}) + "\n```"
        facts = mf.read_facts(reply, candidates)
        self.assertEqual(set(facts), {"1"})
        self.assertEqual(facts["1"]["amount"], 1200.0)
        self.assertEqual(facts["1"]["currency"], "ILS")
        self.assertEqual(facts["1"]["reference"], "INV-17")
        self.assertEqual(facts["1"]["documentDate"], "2026-07-01")

    def test_extract_puts_facts_on_the_right_messages_and_never_hands_over_ids(self) -> None:
        items = [
            {"id": "gm-1", "from": "Acme Ltd <billing@acme.co.il>", "subject": "Invoice 17 - please pay by 15 July", "date": "Wed, 1 Jul 2026 10:00:00 +0300", "bodyText": "Invoice 17 for 1,200 ILS"},
            {"id": "gm-2", "from": "Netflix", "subject": "Your receipt", "date": "Sat, 1 Aug 2026 10:00:00 +0300", "bodyText": "We charged 49.90 ILS for your monthly plan"},
        ]
        prompts: list[str] = []

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            return json.dumps({"facts": [
                {"ref": "1", "kind": "bill", "counterparty": "Acme", "amount": 1200, "currency": "ILS", "reference": "17", "dueOn": "2026-07-15"},
                {"ref": "2", "kind": "charge", "counterparty": "Netflix", "amount": 49.9, "currency": "ILS", "recurring": True},
            ]})

        read = mf.extract_mail_facts(items, ask=ask, owner_addresses=["owner@example.com"])
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("gm-1", prompts[0])
        self.assertIn('"owner":["owner"]', prompts[0])
        self.assertEqual(read[0][mf.FACTS_KEY]["kind"], "bill")
        self.assertTrue(read[1][mf.FACTS_KEY]["recurring"])
        entry = mf.fact_entry(read[0])
        self.assertEqual(entry["messageDate"], "2026-07-01")
        self.assertEqual(entry["messageId"], "gm-1")

    def test_an_unreadable_reply_leaves_messages_without_facts(self) -> None:
        read = mf.extract_mail_facts([{"id": "a", "subject": "x"}], ask=lambda prompt: "no idea")
        self.assertFalse(mf.has_fact(read[0]))

    def test_parties_normalise_across_suffixes_and_addresses(self) -> None:
        self.assertEqual(mf.normalize_party("Acme Ltd."), mf.normalize_party("ACME"))
        self.assertEqual(mf.normalize_party("billing@acme.com"), "billing")
        self.assertEqual(mf.normalize_party("Acme <billing@acme.com>"), "acme")

    def test_the_version_is_a_stable_fingerprint(self) -> None:
        self.assertEqual(len(mf.facts_version()), 16)
        self.assertEqual(mf.facts_version(), mf.facts_version())

    def test_the_scan_query_carries_the_words_and_the_window(self) -> None:
        query = mf.build_scan_query(365)
        self.assertEqual(query.newer_than_days, 365)
        self.assertIn("invoice", query.terms)
        self.assertIn("חשבונית", query.terms)


class BillAndRenewalTests(unittest.TestCase):
    def test_a_bill_due_next_week_with_no_charge_is_found(self) -> None:
        facts = [_fact("bill", counterparty="Electric Co", amount=430.5, currency="ILS", messageDate="2026-09-01", dueOn="2026-09-15")]
        findings = mf.derive_findings(facts, today=TODAY)
        self.assertEqual(findings[0]["detector"], "bill_due")
        self.assertEqual(findings[0]["daysUntil"], 7)
        self.assertIn("due in 7 days", mf.describe_finding(findings[0]))

    def test_a_bill_already_charged_is_not_raised(self) -> None:
        facts = [
            _fact("bill", counterparty="Electric Co", amount=430.5, currency="ILS", messageDate="2026-09-01", dueOn="2026-09-15"),
            _fact("charge", counterparty="Electric Co", amount=430.5, currency="ILS", messageDate="2026-09-05"),
        ]
        self.assertEqual(mf.derive_findings(facts, today=TODAY), [])

    def test_a_renewal_coming_up_carries_last_years_price(self) -> None:
        facts = [
            _fact("charge", counterparty="Harel Insurance", amount=3200, currency="ILS", messageDate="2025-09-20"),
            _fact("renewal", counterparty="Harel Insurance", amount=3650, currency="ILS", messageDate="2026-09-05", dueOn="2026-09-25"),
            _fact("renewal", messageId="dup", counterparty="Harel", amount=None, messageDate="2026-09-06", dueOn="2026-09-25"),
        ]
        findings = mf.derive_findings(facts, today=TODAY)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["detector"], "renewal")
        self.assertEqual(finding["previousAmount"], 3200)
        self.assertEqual(len(finding["sources"]), 2)
        line = mf.describe_finding(finding)
        self.assertIn("2026-09-25", line)
        self.assertIn("3,650 ILS", line)
        self.assertIn("up from 3,200 ILS", line)

    def test_a_renewal_far_off_or_long_past_is_not_raised(self) -> None:
        facts = [
            _fact("renewal", counterparty="Domain", messageDate="2026-09-01", dueOn="2026-12-01"),
            _fact("renewal", counterparty="Old", messageDate="2026-06-01", dueOn="2026-06-10"),
        ]
        self.assertEqual(mf.derive_findings(facts, today=TODAY), [])


class PriceRiseTests(unittest.TestCase):
    def _charges(self, amounts: list[float]) -> list[dict]:
        return [
            _fact("charge", messageId=f"c{index}", counterparty="Netflix", amount=amount, currency="ILS", recurring=True, messageDate=f"2026-0{index + 4}-01")
            for index, amount in enumerate(amounts)
        ]

    def test_a_recurring_charge_that_went_up_is_found(self) -> None:
        findings = mf.derive_findings(self._charges([49.9, 49.9, 49.9, 59.9]), today=TODAY)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["detector"], "price_rise")
        self.assertEqual(finding["previousAmount"], 49.9)
        self.assertEqual(finding["amount"], 59.9)
        self.assertEqual(finding["risePercent"], 20)
        self.assertIn("+20%", mf.describe_finding(finding))

    def test_a_flat_or_barely_moved_charge_is_not(self) -> None:
        self.assertEqual(mf.derive_findings(self._charges([49.9, 49.9, 49.9, 49.9]), today=TODAY), [])
        self.assertEqual(mf.derive_findings(self._charges([49.9, 49.9, 49.9, 51.0]), today=TODAY), [])

    def test_too_few_charges_say_nothing(self) -> None:
        self.assertEqual(mf.derive_findings(self._charges([49.9, 59.9]), today=TODAY), [])

    def test_subscriptions_are_summed_by_currency(self) -> None:
        facts = self._charges([49.9, 49.9, 49.9, 59.9]) + [
            _fact("charge", messageId="s1", counterparty="Spotify", amount=25, currency="ILS", recurring=True, messageDate="2026-08-15"),
            _fact("charge", messageId="s2", counterparty="Adobe", amount=20, currency="USD", recurring=True, messageDate="2026-08-15"),
            _fact("charge", messageId="s3", counterparty="Gone", amount=99, currency="ILS", recurring=True, messageDate="2025-10-15"),
        ]
        summary = mf.summarize_subscriptions(facts, today=TODAY)
        self.assertEqual(summary["ILS"]["count"], 2)
        self.assertEqual(summary["ILS"]["latestTotal"], 84.9)
        self.assertEqual(summary["USD"]["count"], 1)
        self.assertEqual(summary["ILS"]["vendors"][0]["name"], "Netflix")


class TellingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = [
            _fact("bill", counterparty="Acme Ltd", amount=1200, currency="ILS", messageDate="2026-09-01", dueOn="2026-09-15", reference="INV-17"),
            _fact("renewal", counterparty="Harel Insurance", amount=3650, currency="ILS", messageDate="2026-09-05", dueOn="2026-09-25"),
        ] + [
            _fact("charge", messageId=f"c{index}", counterparty="Netflix", amount=amount, currency="ILS", recurring=True, messageDate=f"2026-0{index + 4}-01")
            for index, amount in enumerate([49.9, 49.9, 49.9, 59.9])
        ]

    def test_findings_come_back_best_first(self) -> None:
        findings = mf.derive_findings(self.facts, today=TODAY)
        self.assertEqual({finding["detector"] for finding in findings}, {"bill_due", "renewal", "price_rise"})
        self.assertEqual([finding["score"] for finding in findings], sorted((finding["score"] for finding in findings), reverse=True))
        self.assertEqual(findings[0]["detector"], "bill_due", "a bill due next week comes before a renewal in a fortnight")

    def test_the_instruction_carries_the_figures_and_the_count_of_the_rest(self) -> None:
        findings = mf.derive_findings(self.facts, today=TODAY)
        text = mf.build_findings_instruction(findings[:1], kind="first", more_count=2)
        self.assertIn("1. Bill from Acme Ltd for 1,200 ILS, due in 7 days (2026-09-15)", text)
        self.assertIn("There are 2 more", text)
        self.assertIn("do not use any tool", text)
        self.assertIn("Open with what you found, never with the reading", text)
        self.assertNotIn("2.", text.split("FINDINGS:")[1])

    def test_the_digest_mentions_recurring_charges(self) -> None:
        findings = mf.derive_findings(self.facts, today=TODAY)
        subscriptions = mf.summarize_subscriptions(self.facts, today=TODAY)
        text = mf.build_findings_instruction(findings, kind="digest", subscriptions=subscriptions)
        self.assertIn("RECURRING CHARGES", text)
        self.assertIn("1 in ILS totalling 59.9 ILS", text)
        self.assertIn("connected their mailbox yesterday", text)

    def test_the_fallback_is_plain_lines_with_the_same_figures(self) -> None:
        findings = mf.derive_findings(self.facts, today=TODAY)
        text = mf.build_findings_fallback_text(findings[:1], kind="first", more_count=2)
        # It opens on the finding: nobody wants to hear their mail was read
        # through, only what came back from it.
        self.assertTrue(text.startswith("One thing in your mail worth knowing:"))
        self.assertNotIn("looked through", text)
        self.assertIn("• Bill from Acme Ltd for 1,200 ILS, due in 7 days (2026-09-15)", text)
        self.assertIn("2 more", text)

    def test_a_quiet_mailbox_is_told_as_reassurance_not_as_a_report(self) -> None:
        self.assertTrue(mf.NOTHING_FOUND_TEXT.startswith("Nothing in your mail needs your attention"))
        self.assertNotIn("looked through", mf.NOTHING_FOUND_TEXT)
        self.assertIn("no \"I've looked through the last year of your mail\" opener",
                      mf.build_nothing_found_instruction())

    def test_the_date_of_an_email_header_is_read_as_a_day(self) -> None:
        self.assertEqual(mf.message_day("Wed, 1 Jul 2026 10:00:00 +0300"), "2026-07-01")
        self.assertEqual(mf.message_day("2026-07-01T10:00:00Z"), "2026-07-01")
        self.assertEqual(mf.message_day("nonsense"), "")


if __name__ == "__main__":
    unittest.main()
