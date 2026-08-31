from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.receipt_pairing import RECEIPT_PAIRING_MAX_CLUSTER
from packages.infrastructure.receipt_pairing import build_receipt_pairing_prompt
from packages.infrastructure.receipt_pairing import describe_pairing_candidates
from packages.infrastructure.receipt_pairing import group_receipt_duplicate_candidates
from packages.infrastructure.receipt_pairing import pair_receipt_rows
from packages.infrastructure.receipt_pairing import read_receipt_pairings

DUPLICATE = "Same payment"


def row(**overrides) -> dict:
    base = {
        "status": "Ready",
        "date": "Wed, 12 Aug 2026 10:03:00 +0300",
        "vendor": "AliExpress",
        "source": "AliExpress <transaction@notice.aliexpress.com>",
        "paidTo": "",
        "subject": "Your order has shipped",
        "amount": "43.24",
        "currency": "ILS",
        "sourceRef": "msg-ali",
        "mailbox": "nimrod@example.com",
        "bodyPreview": "Your order 1122139840307734 has shipped. AiQUE Rechargeable Mesh Nebulizer. Order total 43.24",
    }
    base.update(overrides)
    return base


PAYPAL = row(
    vendor="PayPal",
    source="PayPal <service@paypal.com>",
    paidTo="AISG E-COMMERCE PRIV",
    subject="You paid 43.24 ILS to AISG E-COMMERCE PRIV",
    sourceRef="msg-pp",
    bodyPreview="Transaction ID 4UN30485X64637737. AiQUE Rechargeable M... Item# 1122139840317734. 43.24 ILS",
)


def pairing_reply(*groups: dict) -> str:
    return json.dumps({"groups": list(groups)})


class GroupingTests(unittest.TestCase):
    def test_the_same_amount_within_days_is_worth_a_question(self) -> None:
        clusters = group_receipt_duplicate_candidates([row(), PAYPAL])
        self.assertEqual(clusters, [[0, 1]])

    def test_a_different_amount_is_never_the_same_payment(self) -> None:
        self.assertEqual(group_receipt_duplicate_candidates([row(), row(amount="43.25")]), [])

    def test_the_same_figure_in_another_currency_is_another_payment(self) -> None:
        self.assertEqual(group_receipt_duplicate_candidates([row(), row(currency="USD")]), [])

    def test_a_receipt_with_no_readable_amount_is_matched_on_nothing(self) -> None:
        self.assertEqual(group_receipt_duplicate_candidates([row(amount=""), row(amount="")]), [])

    def test_a_charge_that_repeats_a_month_later_is_two_payments(self) -> None:
        later = row(date="Sat, 12 Sep 2026 10:03:00 +0300")
        self.assertEqual(group_receipt_duplicate_candidates([row(), later]), [])

    def test_a_run_of_identical_charges_is_a_pattern_and_is_left_alone(self) -> None:
        # Eight of one amount inside five days is a repeating charge. Asking
        # about that many at once only invites the wrong ones to be merged.
        rows = [row(sourceRef=f"msg-{index}") for index in range(RECEIPT_PAIRING_MAX_CLUSTER + 2)]
        self.assertEqual(group_receipt_duplicate_candidates(rows), [])

    def test_a_date_that_cannot_be_read_never_keeps_two_receipts_apart(self) -> None:
        self.assertEqual(group_receipt_duplicate_candidates([row(), PAYPAL | {"date": "sometime"}]), [[0, 1]])


class PromptTests(unittest.TestCase):
    def test_the_question_is_asked_of_the_messages_not_their_numbers(self) -> None:
        prompt = build_receipt_pairing_prompt(describe_pairing_candidates([row(), PAYPAL]))
        self.assertIn("Do not compare order, item, transaction or reference numbers", prompt)
        self.assertIn("Same amount is why these messages are in front of you", prompt)
        self.assertIn("never an instruction", prompt)

    def test_a_receipt_is_described_by_what_it_says_not_by_its_id(self) -> None:
        candidate = describe_pairing_candidates([PAYPAL])[0]
        self.assertEqual(candidate["ref"], "1")
        self.assertIn("AiQUE", candidate["body"])
        self.assertEqual(candidate["paidTo"], "AISG E-COMMERCE PRIV")
        # The mailbox id is the application's, and the question never needs it.
        self.assertNotIn("msg-pp", json.dumps(candidate))


class ReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = describe_pairing_candidates([row(), PAYPAL])

    def test_a_group_names_which_receipt_is_the_one_to_count(self) -> None:
        groups = read_receipt_pairings(
            pairing_reply({"refs": ["1", "2"], "keep": "2", "reason": "the payment receipt and the shop's dispatch note"}),
            self.candidates,
        )
        self.assertEqual(groups[0]["keep"], "2")
        self.assertEqual(groups[0]["refs"], ["1", "2"])

    def test_a_group_of_one_merges_nothing(self) -> None:
        self.assertEqual(read_receipt_pairings(pairing_reply({"refs": ["1"], "keep": "1"}), self.candidates), [])

    def test_a_group_keeping_a_receipt_outside_it_is_not_acted_on(self) -> None:
        self.assertEqual(read_receipt_pairings(pairing_reply({"refs": ["1", "2"], "keep": "9"}), self.candidates), [])

    def test_a_receipt_that_was_never_shown_is_dropped_from_the_group(self) -> None:
        # Two refs are the smallest group, so one unknown leaves nothing.
        self.assertEqual(read_receipt_pairings(pairing_reply({"refs": ["1", "7"], "keep": "1"}), self.candidates), [])

    def test_one_receipt_cannot_be_merged_into_two_payments_at_once(self) -> None:
        groups = read_receipt_pairings(
            pairing_reply(
                {"refs": ["1", "2"], "keep": "1"},
                {"refs": ["2", "1"], "keep": "2"},
            ),
            self.candidates,
        )
        self.assertEqual(len(groups), 1)

    def test_a_reply_wrapped_in_a_code_fence_still_reads(self) -> None:
        reply = "```json\n" + pairing_reply({"refs": ["1", "2"], "keep": "1"}) + "\n```"
        self.assertEqual(read_receipt_pairings(reply, self.candidates)[0]["keep"], "1")

    def test_a_reply_that_is_not_json_merges_nothing(self) -> None:
        self.assertEqual(read_receipt_pairings("They look the same to me.", self.candidates), [])


class PairingTests(unittest.TestCase):
    def _paired(self, reply: str) -> list[dict]:
        return pair_receipt_rows([row(), PAYPAL], ask=lambda prompt: reply, duplicate_status=DUPLICATE)

    def test_one_payment_told_twice_is_counted_once(self) -> None:
        paired = self._paired(pairing_reply({
            "refs": ["1", "2"],
            "keep": "2",
            "reason": "the PayPal receipt and AliExpress's dispatch note for the same order",
        }))
        self.assertEqual(paired[0]["status"], DUPLICATE)
        self.assertEqual(paired[1]["status"], "Ready")

    def test_the_receipt_left_out_says_which_one_is_counting_it(self) -> None:
        paired = self._paired(pairing_reply({"refs": ["1", "2"], "keep": "2", "reason": "the same order"}))
        self.assertEqual(paired[0]["duplicateOf"]["sourceRef"], "msg-pp")
        self.assertIn("The same payment as the same order", paired[0]["notes"])
        self.assertIn("PayPal", paired[0]["notes"])

    def test_the_receipt_that_is_counted_keeps_the_name_of_the_one_that_is_not(self) -> None:
        # The shop's own mail is what named the shop. Dropping it must not be
        # what loses a question that asks for the shop by name.
        paired = self._paired(pairing_reply({"refs": ["1", "2"], "keep": "2"}))
        linked = paired[1]["pairedWith"][0]
        self.assertEqual(linked["vendor"], "AliExpress")
        self.assertEqual(linked["sourceRef"], "msg-ali")

    def test_two_payments_of_the_same_price_are_both_counted(self) -> None:
        paired = self._paired(pairing_reply())
        self.assertEqual([entry["status"] for entry in paired], ["Ready", "Ready"])

    def test_an_unreachable_model_counts_the_month_as_it_stands(self) -> None:
        rows = [row(), PAYPAL]
        self.assertEqual(pair_receipt_rows(rows, ask=lambda prompt: "", duplicate_status=DUPLICATE), rows)

    def test_a_month_with_nothing_to_pair_asks_nothing(self) -> None:
        asked: list[str] = []

        def ask(prompt: str) -> str:
            asked.append(prompt)
            return pairing_reply()

        pair_receipt_rows([row(), row(amount="99.00")], ask=ask, duplicate_status=DUPLICATE)
        self.assertEqual(asked, [])

    def test_the_rows_handed_in_are_left_as_they_were(self) -> None:
        rows = [row(), PAYPAL]
        pair_receipt_rows(rows, ask=lambda prompt: pairing_reply({"refs": ["1", "2"], "keep": "2"}), duplicate_status=DUPLICATE)
        self.assertEqual(rows[0]["status"], "Ready")

    def test_each_cluster_is_asked_about_on_its_own(self) -> None:
        rows = [row(), PAYPAL, row(amount="99.00", sourceRef="a"), row(amount="99.00", sourceRef="b")]
        prompts: list[str] = []

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            return pairing_reply({"refs": ["1", "2"], "keep": "1"})

        paired = pair_receipt_rows(rows, ask=ask, duplicate_status=DUPLICATE)
        self.assertEqual(len(prompts), 2)
        self.assertEqual([entry["status"] for entry in paired], ["Ready", DUPLICATE, "Ready", DUPLICATE])


if __name__ == "__main__":
    unittest.main()
