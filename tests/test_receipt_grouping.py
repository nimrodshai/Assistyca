"""The groupings a spending question is usually really about.

The totals answered one shape of question. Which vendor is biggest, what each
month came to, what repeats, what is new - those were left to the model to
work out by reading sixty receipts and doing the sums in its head, which is
the one part of an answer that belongs in code.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.receipt_grouping import LARGEST_LIMIT
from packages.infrastructure.receipt_grouping import group_by_month
from packages.infrastructure.receipt_grouping import group_by_vendor
from packages.infrastructure.receipt_grouping import group_receipt_records
from packages.infrastructure.receipt_grouping import largest_receipts
from packages.infrastructure.receipt_grouping import month_key
from packages.infrastructure.receipt_grouping import _entries


def record(vendor: str, amount: str, date: str = "", subject: str = "") -> dict:
    return {"kind": "receipt", "vendor": vendor, "amount": amount, "date": date, "subject": subject}


class MonthReadingTests(unittest.TestCase):
    def test_a_mail_header_says_which_month_it_is(self) -> None:
        self.assertEqual(month_key("Fri, 1 Aug 2026 09:00:00 +0000"), "2026-08")

    def test_a_written_month_says_which_month_it_is(self) -> None:
        self.assertEqual(month_key("August 2026"), "2026-08")

    def test_an_iso_month_says_which_month_it_is(self) -> None:
        self.assertEqual(month_key("2026-08"), "2026-08")

    def test_the_month_label_stands_in_when_the_date_is_unreadable(self) -> None:
        self.assertEqual(month_key("", "Aug 2026"), "2026-08")

    def test_a_month_that_cannot_be_read_is_no_month_at_all(self) -> None:
        # Grouping it under the wrong month is worse than leaving it out of
        # the month grouping, where it still counts towards the vendor.
        self.assertEqual(month_key("last thursday"), "")
        self.assertEqual(month_key("2026-13"), "")


class EntryReadingTests(unittest.TestCase):
    def test_an_amount_is_read_with_its_currency_beside_it(self) -> None:
        entries = _entries([record("Render", "19.00 USD")])

        self.assertEqual(entries[0]["amount"], 19.0)
        self.assertEqual(entries[0]["currency"], "USD")

    def test_a_receipt_with_no_readable_amount_is_left_out(self) -> None:
        # Counting it as zero would put a figure on something nobody read.
        self.assertEqual(_entries([record("Render", "")]), [])
        self.assertEqual(_entries([record("Render", "not found")]), [])

    def test_a_receipt_with_no_currency_is_left_out(self) -> None:
        self.assertEqual(_entries([record("Render", "19.00")]), [])

    def test_the_shop_behind_a_payment_service_is_the_vendor(self) -> None:
        entries = _entries([{"vendor": "PayPal", "paidTo": "Backblaze", "amount": "6.00 USD"}])

        self.assertEqual(entries[0]["vendor"], "Backblaze")


class VendorGroupingTests(unittest.TestCase):
    def test_vendors_are_ranked_by_what_they_came_to(self) -> None:
        groups = group_by_vendor(_entries([
            record("Render", "20.00 USD"),
            record("Fastly", "35.00 USD"),
            record("Render", "20.00 USD"),
        ]))

        self.assertEqual(groups[0]["vendor"], "Render")
        self.assertEqual(groups[0]["total"], 40.0)
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(groups[1]["vendor"], "Fastly")

    def test_the_same_vendor_in_two_currencies_is_two_lines(self) -> None:
        # Adding a shekel to a dollar produces a ranking that is wrong in a way
        # nobody can see.
        groups = group_by_vendor(_entries([
            record("Render", "20.00 USD"),
            record("Render", "70.00 ILS"),
        ]))

        self.assertEqual(len(groups), 2)
        self.assertEqual({group["currency"] for group in groups}, {"USD", "ILS"})

    def test_a_vendor_is_counted_once_however_it_is_capitalised(self) -> None:
        groups = group_by_vendor(_entries([
            record("Render", "20.00 USD"),
            record("render", "10.00 USD"),
        ]))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["total"], 30.0)


class MonthGroupingTests(unittest.TestCase):
    def test_months_are_reported_oldest_first(self) -> None:
        groups = group_by_month(_entries([
            record("Render", "20.00 USD", "Fri, 1 Aug 2026 09:00:00 +0000"),
            record("Render", "15.00 USD", "Wed, 1 Jul 2026 09:00:00 +0000"),
        ]))

        self.assertEqual([group["month"] for group in groups], ["2026-07", "2026-08"])
        self.assertEqual(groups[1]["total"], 20.0)

    def test_a_receipt_with_no_month_sits_out_of_the_month_grouping(self) -> None:
        groups = group_by_month(_entries([
            record("Render", "20.00 USD", "Fri, 1 Aug 2026 09:00:00 +0000"),
            record("Fastly", "15.00 USD", "sometime"),
        ]))

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["total"], 20.0)


class LargestReceiptTests(unittest.TestCase):
    def test_the_biggest_charges_come_first(self) -> None:
        largest = largest_receipts(_entries([
            record("Render", "20.00 USD"),
            record("Apple", "199.90 USD"),
            record("Fastly", "3.90 USD"),
        ]))

        self.assertEqual(largest[0]["vendor"], "Apple")
        self.assertEqual(largest[0]["amount"], 199.9)

    def test_only_a_few_are_named(self) -> None:
        largest = largest_receipts(_entries([
            record(f"Vendor {index}", f"{index}.00 USD") for index in range(1, 20)
        ]))

        self.assertEqual(len(largest), LARGEST_LIMIT)


class VendorMovementTests(unittest.TestCase):
    ROWS = [
        record("Render", "20.00 USD", "Wed, 1 Jul 2026 09:00:00 +0000"),
        record("Render", "20.00 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
        record("Dropbox", "12.00 USD", "Wed, 1 Jul 2026 09:00:00 +0000"),
        record("Linear", "8.00 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
    ]

    def test_a_vendor_billing_in_both_months_is_repeating(self) -> None:
        groups = group_receipt_records(self.ROWS)

        self.assertEqual(groups["vendorMovement"]["billingInSeveralMonths"], ["Render"])

    def test_a_vendor_only_in_the_latest_month_is_new(self) -> None:
        groups = group_receipt_records(self.ROWS)

        self.assertEqual(groups["vendorMovement"]["firstSeenInLatestMonth"], ["Linear"])

    def test_a_vendor_missing_from_the_latest_month_has_gone_quiet(self) -> None:
        groups = group_receipt_records(self.ROWS)

        self.assertEqual(groups["vendorMovement"]["absentFromLatestMonth"], ["Dropbox"])

    def test_one_month_has_nothing_to_be_new_against(self) -> None:
        groups = group_receipt_records([
            record("Render", "20.00 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
            record("Linear", "8.00 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
        ])

        self.assertNotIn("vendorMovement", groups)


class GroupedRecordTests(unittest.TestCase):
    def test_records_with_no_money_in_them_group_to_nothing(self) -> None:
        # A calendar read and a plain mailbox read reach the same endpoint.
        self.assertEqual(group_receipt_records([
            {"kind": "event", "title": "Standup", "date": "Mon, 3 Aug 2026"},
        ]), {})
        self.assertEqual(group_receipt_records([]), {})

    def test_one_month_of_receipts_is_grouped_by_vendor_alone(self) -> None:
        groups = group_receipt_records([
            record("Render", "20.00 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
        ])

        self.assertEqual(groups["countedReceipts"], 1)
        self.assertIn("byVendor", groups)
        self.assertNotIn("byMonth", groups)
        # One receipt has nothing to stand out from.
        self.assertNotIn("largestReceipts", groups)

    def test_a_span_carries_every_grouping_worth_having(self) -> None:
        groups = group_receipt_records([
            record("Render", "20.00 USD", "Wed, 1 Jul 2026 09:00:00 +0000"),
            record("Apple", "199.90 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
            record("Render", "20.00 USD", "Sat, 1 Aug 2026 09:00:00 +0000"),
        ])

        self.assertEqual(groups["countedReceipts"], 3)
        self.assertEqual(groups["byVendor"][0]["vendor"], "Apple")
        self.assertEqual([month["month"] for month in groups["byMonth"]], ["2026-07", "2026-08"])
        self.assertEqual(groups["largestReceipts"][0]["amount"], 199.9)
        self.assertEqual(groups["vendorMovement"]["monthsRead"], ["2026-07", "2026-08"])


if __name__ == "__main__":
    unittest.main()
