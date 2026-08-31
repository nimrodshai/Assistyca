"""The provider-neutral mail query, and the two dialects it renders into."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.mail_search import DEFAULT_DIGEST_QUERY
from packages.infrastructure.mail_search import MAIL_QUERY_MAX_LENGTH
from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.mail_search import describe_widening
from packages.infrastructure.mail_search import matches
from packages.infrastructure.mail_search import normalize_terms
from packages.infrastructure.mail_search import widen_query
from packages.infrastructure.mail_search import month_window
from packages.infrastructure.mail_search import parse_gmail_query
from packages.infrastructure.mail_search import parse_time_window_days
from packages.infrastructure.mail_search import to_gmail_query
from packages.infrastructure.mail_search import to_graph_search
from packages.infrastructure.portal_auth.server import AGENT_GMAIL_BATCH_SEARCH_TERMS

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


class QueryLengthTests(unittest.TestCase):
    """A query too long to send is shortened, never cut in half."""

    def _long_query(self) -> MailQuery:
        window = month_window(2026, 7)
        # Long enough to overflow on purpose. The real receipt search asks for
        # its words in five languages, so the room for terms is wide - and a
        # test of shortening that never overflows tests nothing.
        filler = tuple(f"searchword{index:02d}" for index in range(30))
        return MailQuery(
            terms=RECEIPT_TERMS + ("payment", "purchase", "charged", "paid") + filler,
            required_terms=("A Very Long Supplier Name That Goes On And On Limited",),
            after=window.after,
            before=window.before,
        )

    def test_the_query_these_tests_use_really_is_too_long_to_send(self) -> None:
        query = self._long_query()

        self.assertNotIn(query.terms[-1], to_gmail_query(query))
        self.assertNotIn(query.terms[-1], to_graph_search(query))

    def test_gmail_never_receives_an_unclosed_bracket(self) -> None:
        rendered = to_gmail_query(self._long_query())

        self.assertLessEqual(len(rendered), MAIL_QUERY_MAX_LENGTH)
        # "(receipt OR invo" is not a narrower search, it is a broken one.
        self.assertEqual(rendered.count("("), rendered.count(")"))
        self.assertNotIn("OR)", rendered)

    def test_graph_gives_up_whole_words_rather_than_half_of_one(self) -> None:
        rendered = to_graph_search(self._long_query())

        self.assertLessEqual(len(rendered), MAIL_QUERY_MAX_LENGTH)
        self.assertEqual(rendered.count("("), rendered.count(")"))
        self.assertEqual(rendered.count('"') % 2, 0)

    def test_what_is_given_up_is_a_search_word_and_never_the_window(self) -> None:
        query = self._long_query()
        rendered = to_graph_search(query)

        # The vendor and the month are what make the search narrow; dropping
        # either would widen it, which is the opposite of shortening it.
        self.assertIn(query.required_terms[0], rendered)
        self.assertIn("received>=2026-07-01", rendered)
        self.assertIn("received<2026-08-01", rendered)
        self.assertIn("receipt", rendered)


class ReceiptTermsTests(unittest.TestCase):
    """The words a receipt is written in, whichever language it is billed in."""

    def _receipt_query(self) -> MailQuery:
        window = month_window(2026, 8)
        return MailQuery(
            terms=normalize_terms(AGENT_GMAIL_BATCH_SEARCH_TERMS),
            required_terms=("A Very Long Supplier Name That Goes On And On Limited",),
            after=window.after,
            before=window.before,
        )

    def test_no_receipt_word_is_lost_between_the_list_and_the_provider(self) -> None:
        # Both caps - how many terms a query may hold and how long it may be -
        # drop what does not fit silently, and what they drop is the end of the
        # list. That is the languages, so a list that outgrows either of them
        # reads as "no receipts that month" for whoever bills in Chinese.
        gmail = to_gmail_query(self._receipt_query())
        graph = to_graph_search(self._receipt_query())

        for term in AGENT_GMAIL_BATCH_SEARCH_TERMS:
            with self.subTest(term=term):
                self.assertIn(term, gmail)
                self.assertIn(term, graph)

    def test_the_search_asks_in_every_language_the_vendors_bill_in(self) -> None:
        gmail = to_gmail_query(self._receipt_query())

        for word in ("receipt", "חשבונית", "factura", "facture", "发票"):
            with self.subTest(word=word):
                self.assertIn(word, gmail)


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


class WideningTests(unittest.TestCase):
    """A search that finds nothing is asked again, less narrowly."""

    def test_the_topic_words_are_what_a_wider_search_gives_up(self) -> None:
        # A receipt does not have to say "receipt". Vendors send "Your Render
        # statement", and the narrow search misses every one of them.
        query = MailQuery(
            terms=("receipt", "invoice"),
            required_terms=("Render",),
            after=date(2026, 8, 1),
            before=date(2026, 9, 1),
        )

        wider = widen_query(query)

        self.assertIsNotNone(wider)
        self.assertEqual(wider.terms, ())
        self.assertEqual(wider.required_terms, ("Render",))
        self.assertEqual(wider.after, date(2026, 8, 1))
        self.assertEqual(wider.before, date(2026, 9, 1))

    def test_a_search_with_nothing_holding_it_down_has_no_wider_version(self) -> None:
        # Dropping the topic words here would read a whole month of mail to
        # answer a question about receipts.
        query = MailQuery(terms=("receipt", "invoice"), after=date(2026, 8, 1))

        self.assertIsNone(widen_query(query))

    def test_a_vendor_with_no_window_is_not_widened_either(self) -> None:
        # Every message they ever sent is a different question, not a wider
        # answer to this one.
        query = MailQuery(terms=("receipt",), required_terms=("Render",))

        self.assertIsNone(widen_query(query))

    def test_a_search_that_is_already_wide_stays_where_it_is(self) -> None:
        query = MailQuery(required_terms=("Render",), after=date(2026, 8, 1))

        self.assertIsNone(widen_query(query))

    def test_an_attachment_requirement_is_given_up_with_the_words(self) -> None:
        query = MailQuery(
            terms=("receipt",),
            required_terms=("Render",),
            newer_than_days=31,
            has_attachment=True,
        )

        wider = widen_query(query)

        self.assertFalse(wider.has_attachment)
        self.assertEqual(wider.newer_than_days, 31)

    def test_the_widening_is_described_in_the_words_someone_asked_in(self) -> None:
        note = describe_widening(MailQuery(terms=("receipt",), required_terms=("Render",)))

        self.assertIn("Render", note)
        self.assertIn("not only the mail that calls itself a receipt", note)

    def test_a_widening_with_no_vendor_has_nothing_to_describe(self) -> None:
        self.assertEqual(describe_widening(MailQuery(terms=("receipt",))), "")


if __name__ == "__main__":
    unittest.main()
