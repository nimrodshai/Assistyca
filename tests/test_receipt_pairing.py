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
from packages.infrastructure.receipt_pairing import duplicate_pair_key
from packages.infrastructure.receipt_pairing import read_receipt_pairing_questions

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


def unsure_reply(*questions: dict) -> str:
    return json.dumps({"groups": [], "unsure": list(questions)})


ASK_QUESTION = "Is that one payment reported twice, or two separate charges of 43.24 ILS?"


class QuestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = describe_pairing_candidates([row(), PAYPAL])

    def test_a_pair_the_messages_do_not_settle_becomes_a_question(self) -> None:
        questions = read_receipt_pairing_questions(
            unsure_reply({"refs": ["1", "2"], "question": ASK_QUESTION}),
            self.candidates,
        )
        self.assertEqual(questions[0]["refs"], ["1", "2"])
        self.assertEqual(questions[0]["question"], ASK_QUESTION)

    def test_a_question_with_nothing_to_ask_is_not_asked(self) -> None:
        self.assertEqual(
            read_receipt_pairing_questions(unsure_reply({"refs": ["1"], "question": ASK_QUESTION}), self.candidates),
            [],
        )
        self.assertEqual(
            read_receipt_pairing_questions(unsure_reply({"refs": ["1", "2"], "question": ""}), self.candidates),
            [],
        )

    def test_a_pair_already_merged_is_not_also_asked_about(self) -> None:
        # The model settled it. Asking anyway would be asking the owner to
        # confirm a decision that was never theirs to make.
        questions = read_receipt_pairing_questions(
            json.dumps({
                "groups": [{"refs": ["1", "2"], "keep": "1"}],
                "unsure": [{"refs": ["1", "2"], "question": ASK_QUESTION}],
            }),
            self.candidates,
            merged=[{"refs": ["1", "2"], "keep": "1"}],
        )
        self.assertEqual(questions, [])

    def test_the_question_carries_the_receipts_it_is_about(self) -> None:
        pairing = pair_receipt_rows(
            [row(), PAYPAL],
            ask=lambda prompt: unsure_reply({"refs": ["1", "2"], "question": ASK_QUESTION}),
            duplicate_status=DUPLICATE,
        )
        question = pairing.questions[0]

        self.assertEqual(question["question"], ASK_QUESTION)
        self.assertEqual([entry["sourceRef"] for entry in question["receipts"]], ["msg-ali", "msg-pp"])
        self.assertEqual(question["amount"], "43.24")
        # Nothing is merged while the question is open: the higher total is
        # the one that can be argued with.
        self.assertEqual([entry["status"] for entry in pairing.rows], ["Ready", "Ready"])

    def test_the_key_is_the_messages_rather_than_the_amount(self) -> None:
        # Two receipts of the same amount from a different pair of emails are
        # a different question, and an answer to one is not an answer to both.
        self.assertNotEqual(
            duplicate_pair_key([row(), PAYPAL]),
            duplicate_pair_key([row(sourceRef="msg-x"), PAYPAL]),
        )
        # The order they were read in is not part of it.
        self.assertEqual(duplicate_pair_key([row(), PAYPAL]), duplicate_pair_key([PAYPAL, row()]))
        self.assertEqual(duplicate_pair_key([row()]), "")


class AnsweredPairTests(unittest.TestCase):
    def _decision(self, decision: str, keep_ref: str = "") -> list[dict]:
        return [{
            "key": duplicate_pair_key([row(), PAYPAL]),
            "decision": decision,
            "keepRef": keep_ref,
        }]

    def _paired(self, decisions: list[dict], asked: list[str] | None = None):
        def ask(prompt: str) -> str:
            (asked if asked is not None else []).append(prompt)
            return unsure_reply({"refs": ["1", "2"], "question": ASK_QUESTION})

        return pair_receipt_rows(
            [row(), PAYPAL],
            ask=ask,
            duplicate_status=DUPLICATE,
            decisions=decisions,
        )

    def test_one_payment_counts_the_receipt_the_owner_named(self) -> None:
        pairing = self._paired(self._decision("same", "nimrod@example.com::msg-pp"))

        self.assertEqual([entry["status"] for entry in pairing.rows], [DUPLICATE, "Ready"])
        self.assertEqual(pairing.questions, [])

    def test_two_payments_leaves_both_counted(self) -> None:
        pairing = self._paired(self._decision("separate"))

        self.assertEqual([entry["status"] for entry in pairing.rows], ["Ready", "Ready"])
        self.assertEqual(pairing.questions, [])

    def test_a_settled_pair_is_never_asked_about_again(self) -> None:
        asked: list[str] = []
        self._paired(self._decision("separate"), asked)

        # Not the owner, and not the model either: the answer is already in.
        self.assertEqual(asked, [])

    def test_an_answer_about_other_receipts_settles_nothing_here(self) -> None:
        asked: list[str] = []
        pairing = self._paired([{"key": "some-other-pair", "decision": "same"}], asked)

        self.assertEqual(len(asked), 1)
        self.assertEqual(len(pairing.questions), 1)


class ThreeOfAKindTests(unittest.TestCase):
    """A cluster where one pair is settled and the third receipt is not.

    The answer is about the receipts it was asked about, which is not always
    the whole cluster. Looking it up by the cluster instead made the answer
    unfindable, so the same question came back after every answer to it.
    """

    def setUp(self) -> None:
        self.rows = [
            row(sourceRef="m1", date="Mon, 03 Aug 2026 10:00:00 +0300"),
            row(sourceRef="m2", date="Wed, 05 Aug 2026 10:00:00 +0300"),
            row(sourceRef="m3", date="Fri, 07 Aug 2026 10:00:00 +0300"),
        ]
        self.asked: list[str] = []

    def _ask(self, prompt: str) -> str:
        self.asked.append(prompt)
        return unsure_reply({"refs": ["1", "2"], "question": ASK_QUESTION})

    def _paired(self, decisions: list[dict] | None = None):
        return pair_receipt_rows(
            self.rows,
            ask=self._ask,
            duplicate_status=DUPLICATE,
            decisions=decisions,
        )

    def test_the_question_is_about_the_two_it_named(self) -> None:
        question = self._paired().questions[0]
        self.assertEqual([entry["sourceRef"] for entry in question["receipts"]], ["m1", "m2"])

    def test_answering_it_settles_it_and_ends_it(self) -> None:
        question = self._paired().questions[0]
        answered = self._paired([{
            "key": question["key"],
            "decision": "same",
            "keepRef": question["receipts"][0]["keepRef"],
        }])

        self.assertEqual([entry["status"] for entry in answered.rows], ["Ready", DUPLICATE, "Ready"])
        self.assertEqual(answered.questions, [])

    def test_two_payments_is_settled_the_same_way(self) -> None:
        question = self._paired().questions[0]
        answered = self._paired([{"key": question["key"], "decision": "separate"}])

        self.assertEqual([entry["status"] for entry in answered.rows], ["Ready", "Ready", "Ready"])
        self.assertEqual(answered.questions, [])

    def test_the_third_receipt_is_still_open_to_a_question_of_its_own(self) -> None:
        # Settling one pair does not settle the cluster, so the model is still
        # asked about what is left. It is the answered pair that must not come
        # back, not the rest of the month.
        question = self._paired().questions[0]
        self.asked.clear()
        self._paired([{"key": question["key"], "decision": "separate"}])

        self.assertEqual(len(self.asked), 1)


class UnsureTests(unittest.TestCase):
    """The owner cannot tell either, and says so."""

    def _paired(self, asked: list[str]):
        question_key = duplicate_pair_key([row(), PAYPAL])

        def ask(prompt: str) -> str:
            asked.append(prompt)
            return unsure_reply({"refs": ["1", "2"], "question": ASK_QUESTION})

        return pair_receipt_rows(
            [row(), PAYPAL],
            ask=ask,
            duplicate_status=DUPLICATE,
            decisions=[{"key": question_key, "decision": "skip"}],
        )

    def test_not_knowing_counts_them_apart_and_stops_the_asking(self) -> None:
        asked: list[str] = []
        pairing = self._paired(asked)

        # Apart is the higher total, and the one that can be argued with.
        self.assertEqual([entry["status"] for entry in pairing.rows], ["Ready", "Ready"])
        # It is not put again in this run, to the owner or to the model.
        self.assertEqual(pairing.questions, [])
        self.assertEqual(asked, [])


class PairingTests(unittest.TestCase):
    def _paired(self, reply: str) -> list[dict]:
        return pair_receipt_rows([row(), PAYPAL], ask=lambda prompt: reply, duplicate_status=DUPLICATE).rows

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
        self.assertEqual(pair_receipt_rows(rows, ask=lambda prompt: "", duplicate_status=DUPLICATE).rows, rows)

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

        paired = pair_receipt_rows(rows, ask=ask, duplicate_status=DUPLICATE).rows
        self.assertEqual(len(prompts), 2)
        self.assertEqual([entry["status"] for entry in paired], ["Ready", DUPLICATE, "Ready", DUPLICATE])


if __name__ == "__main__":
    unittest.main()
