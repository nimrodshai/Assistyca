"""Reading how often a vendor charges out of the receipts they sent."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.subscription_rhythm import read_subscription_rhythm

TODAY = date(2026, 9, 16)


def _charge(day: str, amount: str = "550.00 ILS", *, subject: str = "Your receipt", detail: str = "") -> dict[str, str]:
    return {"kind": "receipt", "date": day, "amount": amount, "subject": subject, "detail": detail}


class RhythmFromTheDatesTests(unittest.TestCase):
    def test_charges_a_month_apart_are_a_monthly_subscription(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge("Mon, 06 Jul 2026 08:00:00 +0300", "19.90 ILS"),
             _charge("Thu, 06 Aug 2026 08:00:00 +0300", "19.90 ILS"),
             _charge("Sun, 06 Sep 2026 08:00:00 +0300", "19.90 ILS")],
            vendor="Spotify",
            today=TODAY,
        )

        self.assertEqual(rhythm["cadence"], "monthly")
        self.assertEqual(rhythm["typicalGapDays"], 31)
        self.assertEqual(rhythm["lastCharge"], "2026-09-06")
        self.assertEqual(rhythm["nextExpected"], "2026-10-06")
        self.assertTrue(rhythm["stillRunning"])
        self.assertTrue(rhythm["settled"])

    def test_a_monthly_plan_that_stopped_four_months_ago_is_not_running(self) -> None:
        # The charge in May is real, and it is exactly what makes "yes, you
        # pay for this" the wrong answer: the next three never arrived.
        rhythm = read_subscription_rhythm(
            [_charge("Sun, 05 Apr 2026 08:00:00 +0300", "19.90 ILS"),
             _charge("Tue, 05 May 2026 08:00:00 +0300", "19.90 ILS")],
            vendor="Spotify",
            today=TODAY,
        )

        self.assertEqual(rhythm["cadence"], "monthly")
        self.assertFalse(rhythm["stillRunning"])
        self.assertEqual(rhythm["daysSinceLastCharge"], 134)

    def test_charges_a_year_apart_are_a_yearly_subscription_still_running(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge("Mon, 05 May 2025 21:36:00 +0300"),
             _charge("Tue, 05 May 2026 21:36:00 +0300")],
            vendor="Sony",
            today=TODAY,
        )

        self.assertEqual(rhythm["cadence"], "yearly")
        self.assertEqual(rhythm["nextExpected"], "2027-05-05")
        self.assertTrue(rhythm["stillRunning"])

    def test_two_mails_about_one_payment_are_not_a_weekly_subscription(self) -> None:
        # The shop and the payment service both wrote, two days apart. A gap
        # too short to be a billing period is not one.
        rhythm = read_subscription_rhythm(
            [_charge("Tue, 05 May 2026 21:36:00 +0300"),
             _charge("Thu, 07 May 2026 09:00:00 +0300")],
            vendor="Sony",
            today=TODAY,
        )

        self.assertNotEqual(rhythm["cadence"], "weekly")
        self.assertIn("how often this is billed", rhythm["unsettled"])


class RhythmFromTheWordsTests(unittest.TestCase):
    def test_a_receipt_that_names_its_period_settles_a_single_charge(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge(
                "Tue, 05 May 2026 21:36:00 +0300",
                detail="PlayStation Plus Premium 12-month membership. Renews 5 May 2027.",
            )],
            vendor="PlayStation Plus",
            today=TODAY,
        )

        self.assertEqual(rhythm["cadence"], "yearly")
        self.assertEqual(rhythm["cadenceFrom"], "the period the receipt names")
        self.assertEqual(rhythm["cadenceInWords"], "12-month")
        self.assertTrue(rhythm["vendorNamedARenewal"])
        self.assertTrue(rhythm["stillRunning"])

    def test_a_hebrew_receipt_names_its_period_too(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge("Tue, 05 May 2026 21:36:00 +0300", detail="מנוי חודשי, חיוב חודשי אוטומטי")],
            vendor="ynet",
            today=TODAY,
        )

        self.assertEqual(rhythm["cadence"], "monthly")

    def test_a_cancellation_outweighs_the_rhythm_the_dates_make(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge("Mon, 06 Jul 2026 08:00:00 +0300", "19.90 ILS"),
             _charge("Thu, 06 Aug 2026 08:00:00 +0300", "19.90 ILS", detail="Your subscription has been cancelled.")],
            vendor="Spotify",
            today=TODAY,
        )

        self.assertFalse(rhythm["stillRunning"])
        self.assertTrue(rhythm["vendorSaysCancelled"])

    def test_dates_and_wording_that_disagree_are_both_reported(self) -> None:
        # A yearly plan billed monthly, or a receipt describing the plan and
        # not the charge. Either way this is not something to pick a side on.
        rhythm = read_subscription_rhythm(
            [_charge("Mon, 06 Jul 2026 08:00:00 +0300", "19.90 ILS", detail="Annual plan"),
             _charge("Thu, 06 Aug 2026 08:00:00 +0300", "19.90 ILS", detail="Annual plan")],
            vendor="Something",
            today=TODAY,
        )

        self.assertFalse(rhythm["settled"])
        self.assertTrue(any("yearly" in note and "monthly" in note for note in rhythm["unsettled"]))


class WhatCannotBeSettledTests(unittest.TestCase):
    def test_one_charge_and_no_words_leaves_the_question_open(self) -> None:
        # This is the PlayStation case exactly: 550 ILS to Sony in May, and
        # nothing in the mail saying whether that buys a month or a year.
        rhythm = read_subscription_rhythm(
            [_charge("Tue, 05 May 2026 21:36:00 +0300", subject="Receipt for Your Payment to SONY INTERACTIVE ENT")],
            vendor="PlayStation Plus, Sony",
            today=TODAY,
        )

        self.assertEqual(rhythm["cadence"], "unclear")
        self.assertIsNone(rhythm["stillRunning"])
        self.assertFalse(rhythm["settled"])
        self.assertIn("only one charge was found, so there is no rhythm to read", rhythm["unsettled"])
        self.assertEqual(rhythm["lastAmount"], "550.00 ILS")

    def test_amounts_that_move_are_said_out_loud(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge("Mon, 06 Jul 2026 08:00:00 +0300", "19.90 ILS"),
             _charge("Thu, 06 Aug 2026 08:00:00 +0300", "34.90 ILS")],
            vendor="Something",
            today=TODAY,
        )

        self.assertFalse(rhythm["amountsAgree"])
        self.assertIn("the amounts are not all the same", rhythm["unsettled"])

    def test_a_receipt_with_no_readable_date_is_counted_not_dropped(self) -> None:
        rhythm = read_subscription_rhythm(
            [_charge("Tue, 05 May 2026 21:36:00 +0300"), _charge("not a date")],
            vendor="Sony",
            today=TODAY,
        )

        self.assertEqual(rhythm["chargeCount"], 1)
        self.assertEqual(rhythm["undatedChargeCount"], 1)

    def test_nothing_found_is_a_rhythm_with_nothing_in_it(self) -> None:
        rhythm = read_subscription_rhythm([], vendor="Sony", today=TODAY)

        self.assertEqual(rhythm["chargeCount"], 0)
        self.assertFalse(rhythm["settled"])


if __name__ == "__main__":
    unittest.main()
