"""The provider-neutral mail query, and the two dialects it renders into."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.mail_search import DEFAULT_DIGEST_QUERY
from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.mail_search import matches
from packages.infrastructure.mail_search import month_window
from packages.infrastructure.mail_search import parse_gmail_query
from packages.infrastructure.mail_search import parse_time_window_days
from packages.infrastructure.mail_search import to_gmail_query
from packages.infrastructure.mail_search import to_graph_search

RECEIPT_TERMS = ("receipt", "invoice", "statement", "bill", "transaction", "expense")


class GmailRenderingTests(unittest.TestCase):
    def test_the_receipts_month_renders_the_string_gmail_has_always_been_sent(self) -> None:
        window = month_window(2026, 7)
        query = MailQuery(terms=RECEIPT_TERMS, after=window.after, before=window.before)

        # Byte for byte what build_custom_google_batch_gmail_query used to
        # produce, so switching to the neutral shape cannot change a Gmail run.
        self.assertEqual(
            to_gmail_query(query),
            "after:2026/07/01 before:2026/08/01 "
            "(receipt OR invoice OR statement OR bill OR transaction OR expense)",
        )

    def test_december_rolls_the_window_into_the_next_year(self) -> None:
        window = month_window(2026, 12)

        self.assertEqual(window.after, date(2026, 12, 1))
        self.assertEqual(window.before, date(2027, 1, 1))

    def test_the_default_digest_query_is_unchanged(self) -> None:
        self.assertEqual(to_gmail_query(DEFAULT_DIGEST_QUERY), "in:inbox newer_than:1d")

    def test_a_relative_window_renders_as_newer_than(self) -> None:
        query = MailQuery(terms=("receipt", "invoice"), newer_than_days=31)

        self.assertEqual(to_gmail_query(query), "newer_than:31d (receipt OR invoice)")

    def test_a_named_vendor_narrows_the_search_rather_than_widening_it(self) -> None:
        window = month_window(2026, 8)
        query = MailQuery(
            terms=RECEIPT_TERMS,
            required_terms=("Render",),
            after=window.after,
            before=window.before,
        )

        # The vendor sits outside the OR group, so Gmail requires it.
        self.assertEqual(
            to_gmail_query(query),
            "after:2026/08/01 before:2026/09/01 "
            "(receipt OR invoice OR statement OR bill OR transaction OR expense) Render",
        )

    def test_a_vendor_of_two_words_stays_one_search_term(self) -> None:
        query = MailQuery(terms=("receipt",), required_terms=("Green Invoice",))

        self.assertEqual(to_gmail_query(query), '(receipt) "Green Invoice"')


class GmailParsingTests(unittest.TestCase):
    def test_a_saved_gmail_query_survives_the_round_trip(self) -> None:
        original = (
            "after:2026/07/01 before:2026/08/01 "
            "(receipt OR invoice OR statement OR bill OR transaction OR expense)"
        )

        self.assertEqual(to_gmail_query(parse_gmail_query(original)), original)

    def test_the_default_digest_query_survives_the_round_trip(self) -> None:
        self.assertEqual(to_gmail_query(parse_gmail_query("in:inbox newer_than:1d")), "in:inbox newer_than:1d")

    def test_an_attachment_filter_is_understood(self) -> None:
        parsed = parse_gmail_query("has:attachment (receipt)")

        self.assertTrue(parsed.has_attachment)
        self.assertEqual(parsed.terms, ("receipt",))

    def test_an_operator_the_portal_does_not_model_keeps_its_value_as_a_word(self) -> None:
        # Dropping it would widen the search to the whole mailbox, which is the
        # one outcome a receipts run must never have.
        parsed = parse_gmail_query("from:billing@example.com receipt")

        self.assertIn("receipt", parsed.terms)
        self.assertIn("billing@example.com", parsed.terms)

    def test_an_empty_query_parses_to_an_empty_intent(self) -> None:
        self.assertTrue(parse_gmail_query("").is_empty())
        self.assertTrue(parse_gmail_query("   ").is_empty())

    def test_a_malformed_date_does_not_become_a_silent_all_time_search(self) -> None:
        parsed = parse_gmail_query("after:not-a-date (receipt)")

        self.assertIsNone(parsed.after)
        self.assertEqual(parsed.terms, ("receipt",))


class GraphRenderingTests(unittest.TestCase):
    def test_terms_and_the_window_travel_together_in_one_kql_string(self) -> None:
        window = month_window(2026, 7)
        query = MailQuery(terms=("receipt", "invoice"), after=window.after, before=window.before)

        self.assertEqual(
            to_graph_search(query),
            '("receipt" OR "invoice") AND received>=2026-07-01 AND received<2026-08-01',
        )

    def test_a_relative_window_becomes_a_concrete_date(self) -> None:
        query = MailQuery(terms=("receipt",), newer_than_days=7)

        rendered = to_graph_search(query, today=date(2026, 8, 28))

        self.assertEqual(rendered, '"receipt" AND received>=2026-08-21')

    def test_a_named_vendor_is_required_in_the_kql_too(self) -> None:
        window = month_window(2026, 8)
        search = to_graph_search(MailQuery(
            terms=("receipt", "invoice"),
            required_terms=("Render",),
            after=window.after,
            before=window.before,
        ))

        self.assertIn('("receipt" OR "invoice") AND "Render"', search)

    def test_an_attachment_filter_is_carried_across(self) -> None:
        query = MailQuery(terms=("receipt",), has_attachment=True)

        self.assertIn("hasattachment:true", to_graph_search(query))

    def test_an_empty_intent_renders_no_search_at_all(self) -> None:
        self.assertEqual(to_graph_search(MailQuery()), "")


class ClientSideMatchTests(unittest.TestCase):
    """Graph's KQL window is looser than Gmail's, so results are re-checked."""

    def setUp(self) -> None:
        window = month_window(2026, 7)
        self.query = MailQuery(terms=("receipt",), after=window.after, before=window.before)

    def test_a_message_inside_the_window_matches(self) -> None:
        self.assertTrue(matches(
            self.query,
            received=datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            subject="Your receipt",
        ))

    def test_a_message_from_the_month_before_is_rejected(self) -> None:
        self.assertFalse(matches(
            self.query,
            received=datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc),
            subject="Your receipt",
        ))

    def test_the_first_moment_of_the_next_month_is_rejected(self) -> None:
        self.assertFalse(matches(
            self.query,
            received=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
            subject="Your receipt",
        ))

    def test_a_message_with_none_of_the_words_is_rejected(self) -> None:
        self.assertFalse(matches(
            self.query,
            received=datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            subject="Lunch tomorrow?",
            snippet="Are you free at one",
        ))

    def test_the_word_may_appear_in_the_sender_or_the_preview(self) -> None:
        self.assertTrue(matches(
            self.query,
            received=datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            subject="Order 4181",
            snippet="Your receipt is attached",
        ))

    def test_an_attachment_requirement_rejects_a_message_without_one(self) -> None:
        query = MailQuery(terms=("receipt",), has_attachment=True)

        self.assertFalse(matches(query, subject="receipt", has_attachment=False))
        self.assertTrue(matches(query, subject="receipt", has_attachment=True))


class TimeWindowTests(unittest.TestCase):
    """A period named in chat has to reach the mailbox as a real window."""

    def test_a_week_is_seven_days_however_it_is_written(self) -> None:
        self.assertEqual(parse_time_window_days("this week"), 7)
        self.assertEqual(parse_time_window_days("last week"), 7)
        self.assertEqual(parse_time_window_days("the past week"), 7)

    def test_a_counted_window_keeps_its_count(self) -> None:
        self.assertEqual(parse_time_window_days("the last 3 days"), 3)
        self.assertEqual(parse_time_window_days("last two weeks"), 14)
        self.assertEqual(parse_time_window_days("this month"), 31)

    def test_today_and_yesterday_are_read_as_days(self) -> None:
        self.assertEqual(parse_time_window_days("today"), 1)
        self.assertEqual(parse_time_window_days("yesterday"), 2)

    def test_text_naming_no_period_leaves_the_caller_its_default(self) -> None:
        self.assertIsNone(parse_time_window_days(""))
        self.assertIsNone(parse_time_window_days("my inbox"))
        self.assertIsNone(parse_time_window_days(None))

    def test_an_absurd_window_is_capped_rather_than_read_literally(self) -> None:
        self.assertEqual(parse_time_window_days("the last 500 years"), 366)


if __name__ == "__main__":
    unittest.main()
