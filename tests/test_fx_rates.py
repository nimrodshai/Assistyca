"""What the rate lookup promises: the day's own rate, or nothing at all."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import fx_rates
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
from packages.infrastructure.portal_auth.server import merge_receipt_month_conversion
from packages.infrastructure.receipt_collector import answer_receipt_question
from packages.infrastructure.receipt_collector import preferred_receipt_currency


AUGUST_SERIES = {
    "2026-08-05": 3.0100,
    "2026-08-12": 2.9895,
    "2026-08-13": 2.9810,
    "2026-08-14": 2.9496,
    "2026-08-20": 2.9920,
    "2026-08-28": 2.9728,
}


def _series_payload(series: dict[str, float], quote: str = "ILS") -> dict[str, object]:
    return {
        "base": "USD",
        "start_date": min(series),
        "end_date": max(series),
        "rates": {day: {quote: value} for day, value in series.items()},
    }


def _fake_bank(series: dict[str, float] = AUGUST_SERIES, *, pairs: tuple[str, ...] = ("USD/ILS",)):
    """A stand-in bank that answers for one pair, spans and latest alike.

    The real endpoint answers a span with a day-by-day table and "latest"
    with a single day, and the difference matters here: choosing which
    currency to answer in asks for the latest rate, while the figures in the
    answer are read from the span.
    """

    def read(url: str, base: str, quote: str, *, config: object) -> object:
        if f"{base}/{quote}" in pairs:
            table = series
        elif f"{quote}/{base}" in pairs:
            table = {day: round(1 / value, 6) for day, value in series.items()}
        else:
            return None
        if url.endswith("/latest"):
            newest = max(table)
            return {"base": base, "date": newest, "rates": {quote: table[newest]}}
        return {
            "base": base,
            "start_date": min(table),
            "end_date": max(table),
            "rates": {day: {quote: value} for day, value in table.items()},
        }

    return read


class CurrencyAndDateReadingTests(unittest.TestCase):
    def test_only_a_three_letter_code_is_a_currency(self) -> None:
        self.assertEqual(fx_rates.normalize_currency_code(" ils "), "ILS")
        self.assertEqual(fx_rates.normalize_currency_code("$"), "")
        self.assertEqual(fx_rates.normalize_currency_code("SHEKEL"), "")
        self.assertEqual(fx_rates.normalize_currency_code(None), "")

    def test_a_mail_date_header_is_read_as_the_day_it_names(self) -> None:
        self.assertEqual(
            fx_rates.normalize_rate_date("Thu, 13 Aug 2026 09:12:00 +0300"),
            "2026-08-13",
        )
        self.assertEqual(fx_rates.normalize_rate_date("2026-08-13T21:00:00Z"), "2026-08-13")
        self.assertEqual(fx_rates.normalize_rate_date("sometime last week"), "")


class RateLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        fx_rates.reset_fx_rate_cache()
        self.addCleanup(fx_rates.reset_fx_rate_cache)

    def test_a_day_the_bank_skipped_uses_the_rate_that_was_standing(self) -> None:
        with mock.patch.object(fx_rates, "_get_json", return_value=_series_payload(AUGUST_SERIES)):
            rate = fx_rates.exchange_rate("USD", "ILS", "2026-08-16")

        self.assertIsNotNone(rate)
        self.assertEqual(rate.rate_date, "2026-08-14")
        self.assertEqual(rate.asked_date, "2026-08-16")
        self.assertTrue(rate.is_stale)
        self.assertIn("Nothing was published on 16 Aug 2026", fx_rates.describe_rate(rate))

    def test_a_month_of_receipts_is_one_read_not_one_per_receipt(self) -> None:
        days = sorted(AUGUST_SERIES)
        with mock.patch.object(
            fx_rates, "_get_json", return_value=_series_payload(AUGUST_SERIES)
        ) as reader:
            first = fx_rates.exchange_rates_for_dates("USD", "ILS", days)
            # Asked again, the answer comes from what was already read.
            second = fx_rates.exchange_rates_for_dates("USD", "ILS", days)

        self.assertEqual(reader.call_count, 1)
        self.assertEqual(len(first), len(days))
        self.assertEqual(first["2026-08-13"].rate, 2.9810)
        self.assertEqual(second["2026-08-13"].rate, 2.9810)

    def test_the_same_currency_needs_no_rate_at_all(self) -> None:
        with mock.patch.object(fx_rates, "_get_json", side_effect=AssertionError("no read")) as reader:
            rates = fx_rates.exchange_rates_for_dates("ILS", "ILS", ["2026-08-13"])

        reader.assert_not_called()
        self.assertEqual(rates["2026-08-13"].rate, 1.0)

    def test_an_endpoint_that_cannot_be_read_is_read_once_not_once_per_day(self) -> None:
        with mock.patch.object(fx_rates, "_get_json", return_value=None) as reader:
            first = fx_rates.exchange_rates_for_dates("USD", "ILS", sorted(AUGUST_SERIES))
            second = fx_rates.exchange_rates_for_dates("USD", "ILS", sorted(AUGUST_SERIES))

        self.assertEqual(reader.call_count, 1)
        self.assertEqual(first, {})
        self.assertEqual(second, {})


class ConvertingAmountsTests(unittest.TestCase):
    def setUp(self) -> None:
        fx_rates.reset_fx_rate_cache()
        self.addCleanup(fx_rates.reset_fx_rate_cache)

    def test_each_amount_is_converted_at_its_own_date(self) -> None:
        entries = [
            {"amount": "100.00", "currency": "ILS", "date": "2026-08-05"},
            {"amount": "10.00", "currency": "USD", "date": "2026-08-13"},
            {"amount": "10.00", "currency": "USD", "date": "2026-08-28"},
        ]
        with mock.patch.object(fx_rates, "_get_json", side_effect=_fake_bank()):
            converted = fx_rates.convert_amounts(entries, target="ILS")

        # 100 + 10 x 2.9810 + 10 x 2.9728, and not 20 dollars at one rate.
        self.assertEqual(converted["currency"], "ILS")
        self.assertEqual(converted["amount"], 159.54)
        self.assertEqual(converted["convertedCount"], 3)
        self.assertEqual(converted["unconvertedTotals"], {})

    def test_money_that_could_not_be_converted_is_named_not_dropped(self) -> None:
        entries = [
            {"amount": "100.00", "currency": "ILS", "date": "2026-08-05"},
            {"amount": "10.00", "currency": "USD", "date": "2026-08-13"},
            {"amount": "5.00", "currency": "JPY", "date": "2026-08-13"},
        ]

        with mock.patch.object(fx_rates, "_get_json", side_effect=_fake_bank()):
            converted = fx_rates.convert_amounts(entries, target="ILS")

        self.assertEqual(converted["amount"], 129.81)
        self.assertEqual(converted["unconvertedTotals"], {"JPY": 5.0})
        sentence = fx_rates.describe_conversion(converted)
        self.assertIn("129.81 ILS", sentence)
        self.assertIn("5.00 JPY", sentence)


class ReceiptConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        fx_rates.reset_fx_rate_cache()
        self.addCleanup(fx_rates.reset_fx_rate_cache)

    def _receipt(self, amount: str, date: str) -> dict[str, str]:
        return {
            "subject": "Your PayPal receipt",
            "from": "PayPal <service@paypal.com>",
            "date": date,
            "snippet": f"Total charged {amount}",
            "bodyText": f"Total charged {amount}",
        }

    def test_a_month_in_two_currencies_comes_back_as_one_figure(self) -> None:
        items = [
            self._receipt("147.52 ILS", "Wed, 5 Aug 2026 09:12:00 +0300"),
            self._receipt("$34.99", "Thu, 13 Aug 2026 09:12:00 +0300"),
        ]
        with mock.patch.object(fx_rates, "_get_json", side_effect=_fake_bank()):
            answer = answer_receipt_question(items, vendor="PayPal", month_label="Aug 2026")

        self.assertEqual(answer["totals"], {"ILS": 147.52, "USD": 34.99})
        self.assertEqual(answer["converted"]["currency"], "ILS")
        self.assertEqual(answer["converted"]["amount"], 251.83)
        self.assertIn("251.83 ILS", answer["answer"])
        self.assertIn("147.52 ILS and 34.99 USD", answer["answer"])

    def test_a_month_in_one_currency_reads_no_rate_and_says_nothing_extra(self) -> None:
        items = [
            self._receipt("$34.99", "Thu, 13 Aug 2026 09:12:00 +0300"),
            self._receipt("$4.99", "Thu, 13 Aug 2026 21:12:00 +0300"),
        ]
        with mock.patch.object(fx_rates, "_get_json", side_effect=AssertionError("no read")):
            answer = answer_receipt_question(items, vendor="PayPal", month_label="Aug 2026")

        self.assertEqual(answer["converted"], {})
        self.assertNotIn("comes to about", answer["answer"])

    def test_a_rate_that_cannot_be_read_leaves_the_two_totals_alone(self) -> None:
        items = [
            self._receipt("147.52 ILS", "Wed, 5 Aug 2026 09:12:00 +0300"),
            self._receipt("$34.99", "Thu, 13 Aug 2026 09:12:00 +0300"),
        ]
        with mock.patch.object(fx_rates, "_get_json", return_value=None):
            answer = answer_receipt_question(items, vendor="PayPal", month_label="Aug 2026")

        self.assertEqual(answer["converted"], {})
        self.assertIn("147.52 ILS and 34.99 USD", answer["answer"])
        self.assertNotIn("comes to about", answer["answer"])

    def test_the_answer_speaks_the_currency_most_of_the_money_is_in(self) -> None:
        entries = [
            {"amount": "262.56", "currency": "ILS", "date": "2026-08-20"},
            {"amount": "54.97", "currency": "USD", "date": "2026-08-28"},
        ]
        with mock.patch.object(fx_rates, "_get_json", side_effect=_fake_bank()):
            # 55 dollars is 163 shekels, so the shekels hold more of it -
            # which the plain numbers 262 and 55 cannot tell you.
            self.assertEqual(preferred_receipt_currency(entries), "ILS")


class RateQuestionRoutingTests(unittest.TestCase):
    def test_a_rate_question_becomes_a_lookup_rather_than_a_refusal(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "answer_now",
                "reply": "Let me check that rate.",
                "proposalType": "exchange-rate",
                "changes": {"fields": {"baseCurrency": "usd", "quoteCurrency": "ils"}},
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["outcome"], "answer_now")
        self.assertEqual(turn["proposalType"], "exchange-rate")
        self.assertEqual(
            turn["changes"]["fields"],
            {"baseCurrency": "usd", "quoteCurrency": "ils"},
        )

    def test_one_currency_on_its_own_is_not_a_lookup(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "answer_now",
                "reply": "Which currency against which?",
                "proposalType": "exchange-rate",
                "tasks": [{
                    "proposalType": "exchange-rate",
                    "changes": {"fields": {"baseCurrency": "USD"}},
                }],
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn.get("tasks", []), [])


class MonthSpanConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        fx_rates.reset_fx_rate_cache()
        self.addCleanup(fx_rates.reset_fx_rate_cache)

    def test_every_month_of_a_span_is_read_in_the_same_currency(self) -> None:
        answers = [
            {
                "monthLabel": "Jul 2026",
                "totals": {"USD": 10.0},
                "amountEntries": [{"amount": "10.00", "currency": "USD", "date": "2026-08-13"}],
            },
            {
                "monthLabel": "Aug 2026",
                "totals": {"ILS": 100.0},
                "amountEntries": [{"amount": "100.00", "currency": "ILS", "date": "2026-08-20"}],
            },
        ]
        with mock.patch.object(fx_rates, "_get_json", side_effect=_fake_bank()):
            span = merge_receipt_month_conversion(answers)

        # A month that was all shekels still reports in the span's currency,
        # so the months and the figure over them cannot disagree.
        self.assertEqual(span["currency"], "ILS")
        self.assertEqual(span["amount"], 129.81)
        self.assertEqual(answers[0]["converted"]["amount"], 29.81)
        self.assertEqual(answers[1]["converted"]["amount"], 100.0)
        self.assertEqual(
            round(sum(answer["converted"]["amount"] for answer in answers), 2),
            span["amount"],
        )


if __name__ == "__main__":
    unittest.main()
