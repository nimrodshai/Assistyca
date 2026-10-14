"""Questions that get an answer instead of an action.

"How much did I pay Render this month?" used to come back as an offer to set
up an action. These tests pin the behaviour that replaced it: the agent runs
the lookup on the spot, answers in the chat, and saves nothing.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest import mock
from urllib import parse as urllib_parse
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.gmail_summary import GMAIL_MAX_DIGEST_MESSAGES
from packages.infrastructure.gmail_summary import GmailDigestRunner
from packages.infrastructure.portal_auth.server import AGENT_GMAIL_BATCH_SEARCH_TERMS as AGENT_RECEIPT_SEARCH_TERMS
from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.openai_api import OpenAIError
from packages.infrastructure.mail_search import to_gmail_query
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
from packages.infrastructure.portal_auth.server import AGENT_RECEIPT_ANSWER_MAX_MESSAGES
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import resolve_agent_batch_run_month
from packages.infrastructure.portal_auth.server import resolve_local_today
from packages.infrastructure.portal_auth.server import resolve_saved_mail_query
from packages.infrastructure.receipt_collector import answer_receipt_question

SERVER_MODULE = "packages.infrastructure.portal_auth.server"


class _FakeTokenResponse:
    """The provider's token endpoint, so a test never leaves the machine."""

    def __enter__(self) -> "_FakeTokenResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"access_token": "fresh-access-token"}).encode("utf-8")


def _token_endpoint_patch():  # type: ignore[no-untyped-def]
    real_urlopen = urllib_request.urlopen

    def fake_urlopen(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        if "oauth2.googleapis.com" in url:
            return _FakeTokenResponse()
        return real_urlopen(request, timeout=timeout, **kwargs)

    return mock.patch(f"{SERVER_MODULE}.urllib_request.urlopen", side_effect=fake_urlopen)


class AgentAnswerMailWindowTests(unittest.TestCase):
    """A question that named a period has to be read for that period."""

    def test_the_period_the_question_named_sets_the_window(self) -> None:
        query = resolve_saved_mail_query({"timeWindow": "this week"}, {})

        self.assertEqual(query.newer_than_days, 7)
        self.assertTrue(query.in_inbox)

    def test_a_question_naming_no_period_keeps_the_digest_default(self) -> None:
        query = resolve_saved_mail_query({}, {})

        self.assertEqual(query.newer_than_days, 1)

    def test_a_saved_query_still_wins_over_the_period(self) -> None:
        query = resolve_saved_mail_query({"mailQuery": "newer_than:3d", "timeWindow": "this week"}, {})

        self.assertEqual(query.newer_than_days, 3)


class AgentAnswerTurnTests(unittest.TestCase):
    def test_a_spending_question_is_answered_rather_than_proposed(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Let me check — this might take a minute.",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Find receipts from Render for August 2026",
                    "vendor": "Render",
                    "manualRunMonth": "2026-08",
                },
            },
        }, has_active_proposal=False)

        self.assertEqual(turn["outcome"], "answer_now")
        self.assertEqual(turn["proposalType"], "custom")
        self.assertEqual(turn["changes"]["fields"]["vendor"], "Render")
        self.assertEqual(turn["changes"]["fields"]["manualRunMonth"], "2026-08")

    def test_a_lookup_with_no_runner_never_claims_it_can_answer(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Let me check.",
            "proposalType": "web-monitor",
            "changes": {"fields": {"watchQuery": "kid friendly events"}},
        }, has_active_proposal=False)

        self.assertNotEqual(turn["outcome"], "answer_now")

    def test_a_receipt_lookup_with_nothing_to_search_for_is_not_run(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Let me check.",
            "proposalType": "custom",
            "changes": {"fields": {"vendor": "Render"}},
        }, has_active_proposal=False)

        self.assertNotEqual(turn["outcome"], "answer_now")

    def test_a_message_asking_for_two_things_runs_both(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Checking both now.",
            "tasks": [
                {"proposalType": "email-digest", "changes": {"fields": {"timeWindow": "this week"}}},
                {"proposalType": "calendar-summary", "changes": {"fields": {"timeWindow": "this week"}}},
            ],
        }, has_active_proposal=False)

        self.assertEqual(turn["outcome"], "answer_now")
        self.assertEqual(
            [task["proposalType"] for task in turn["tasks"]],
            ["email-digest", "calendar-summary"],
        )
        # The first lookup also fills the single-lookup keys, so nothing that
        # only knows about one lookup is left without one.
        self.assertEqual(turn["proposalType"], "email-digest")
        self.assertEqual(turn["changes"]["fields"]["timeWindow"], "this week")

    def test_the_same_lookup_asked_for_twice_runs_once(self) -> None:
        # "Check Gmail and Outlook" is one mailbox read, not two: the runner
        # already reads every connected mailbox.
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Checking now.",
            "tasks": [
                {"proposalType": "email-digest", "changes": {"fields": {"timeWindow": "this week"}}},
                {"proposalType": "email-digest", "changes": {"fields": {"timeWindow": "this week"}}},
            ],
        }, has_active_proposal=False)

        self.assertEqual(len(turn["tasks"]), 1)

    def test_a_lookup_with_no_runner_is_dropped_from_the_task_list(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Checking now.",
            "tasks": [
                {"proposalType": "web-monitor", "changes": {"fields": {"watchQuery": "events"}}},
                {"proposalType": "email-digest", "changes": {"fields": {"timeWindow": "today"}}},
            ],
        }, has_active_proposal=False)

        self.assertEqual([task["proposalType"] for task in turn["tasks"]], ["email-digest"])

    def test_a_single_lookup_turn_still_carries_one_task(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "Checking now.",
            "proposalType": "email-digest",
            "changes": {"fields": {"timeWindow": "this week"}},
        }, has_active_proposal=False)

        self.assertEqual(len(turn["tasks"]), 1)
        self.assertEqual(turn["tasks"][0]["proposalType"], "email-digest")

    def test_only_a_custom_task_may_produce_something(self) -> None:
        # A digest and a calendar summary have nothing to write, so a run mode
        # on them is a misread and must not reach the runner.
        turn = normalize_agent_turn_response({
            "outcome": "answer_now",
            "reply": "On it.",
            "tasks": [
                {"proposalType": "custom", "mode": "run", "changes": {"fields": {"result": "Collect August receipts"}}},
                {"proposalType": "email-digest", "mode": "run", "changes": {"fields": {"timeWindow": "this week"}}},
            ],
        }, has_active_proposal=False)

        self.assertEqual([task["mode"] for task in turn["tasks"]], ["run", "answer"])

    def test_a_one_off_is_never_turned_into_a_proposal_by_the_prompt(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Collect my August receipts",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            today="2026-08-30",
        )

        self.assertIn("A request to do something once is a one-off task, never a proposal", prompt)
        self.assertIn("offers to save it as a reusable action afterwards", prompt)

    def test_the_prompt_asks_for_the_period_an_email_question_named(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Summarize my emails from this week",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            today="2026-08-30",
        )

        self.assertIn("changes.fields.timeWindow", prompt)
        self.assertIn("break it into its separate lookups", prompt)

    def test_the_turn_prompt_offers_answering_as_an_outcome(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Please check how much did i pay to render this month",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            today="2026-08-29",
        )

        self.assertIn("answer_now", prompt)
        self.assertIn('"today":"2026-08-29"', prompt)
        self.assertIn("Do not offer to create an action for these", prompt)

    def test_the_prompt_asks_for_every_month_a_question_names(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="How much did I pay Render in July and in August?",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            today="2026-08-29",
        )

        self.assertIn("list every month it names in manualRunMonth", prompt)
        self.assertIn("2026-07,2026-08", prompt)

    def test_today_falls_back_to_utc_for_an_unknown_timezone(self) -> None:
        self.assertEqual(
            resolve_local_today("Not/AZone"),
            resolve_local_today("UTC"),
        )


class AgentRunMonthTests(unittest.TestCase):
    def test_this_month_means_this_month(self) -> None:
        month = resolve_agent_batch_run_month({"result": "Find receipts from Render this month"}, {})

        self.assertEqual(month, resolve_agent_batch_run_month({"manualRunMonth": _current_month_text()}, {}))

    def test_an_explicit_month_still_wins(self) -> None:
        month = resolve_agent_batch_run_month(
            {"result": "Find receipts this month", "manualRunMonth": "2026-03"},
            {},
        )

        self.assertEqual(month, (2026, 3))


def _current_month_text() -> str:
    from datetime import datetime
    from datetime import timezone

    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


class ReceiptAnswerTests(unittest.TestCase):
    def _render_receipt(self, amount: str) -> dict[str, object]:
        return {
            "subject": "Your Render receipt",
            "from": "Render <billing@render.com>",
            "snippet": f"Total charged {amount}",
            "bodyText": f"Total charged {amount}",
        }

    def test_the_answer_names_the_total_and_the_vendor(self) -> None:
        answer = answer_receipt_question(
            [self._render_receipt("$19.00"), self._render_receipt("$8.00")],
            vendor="Render",
            month_label="August 2026",
        )

        self.assertIn("27.00 USD", answer["answer"])
        self.assertIn("Render", answer["answer"])
        self.assertIn("August 2026", answer["answer"])
        self.assertEqual(answer["receiptCount"], 2)

    def test_another_vendors_receipts_stay_out_of_the_total(self) -> None:
        other = {
            "subject": "Your Netlify receipt",
            "from": "Netlify <billing@netlify.com>",
            "snippet": "Total charged $99.00",
            "bodyText": "Total charged $99.00",
        }

        answer = answer_receipt_question(
            [self._render_receipt("$19.00"), other],
            vendor="Render",
            month_label="August 2026",
        )

        self.assertEqual(answer["totals"], {"USD": 19.0})
        self.assertEqual(answer["receiptCount"], 1)

    def test_finding_nothing_says_so_plainly(self) -> None:
        answer = answer_receipt_question([], vendor="Render", month_label="August 2026")

        self.assertIn("couldn't find any receipts", answer["answer"])
        self.assertEqual(answer["receiptCount"], 0)


class AgentAnswerRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.output_dir = Path(self.temp_dir.name) / "agent_outputs"
        self.server = create_server(
            "127.0.0.1",
            0,
            root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
                agent_output_dir=self.output_dir,
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
            ),
        )
        if self.server.credential_vault is None:
            self.server.server_close()
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({
                "type": GOOGLE_OAUTH_SECRET_TYPE,
                "provider": "google",
                "refreshToken": "refresh-token",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,
            connection_status="connected",
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _run_answer(
        self,
        fields: dict[str, object],
        digest: dict[str, object] | None = None,
        **extra: object,
    ) -> dict[str, object]:
        digest = digest or {
            "summary": "Gmail digest - 1 message",
            "messageCount": 1,
            "items": [{
                "id": "msg-1",
                "mailbox": "owner@gmail.com",
                "subject": "Your Render receipt",
                "from": "Render <billing@render.com>",
                "snippet": "Total charged $19.00",
                "bodyText": "Total charged $19.00",
            }],
        }
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "custom",
                "mode": "answer",
                "fields": fields,
                "deliveryChannel": "portal",
                "timezone": "Asia/Jerusalem",
                **extra,
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with _token_endpoint_patch():
            with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", return_value=digest) as runner:
                with urllib_request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        self.run_call = runner.call_args
        self.mailbox_reads = runner.call_count
        return payload

    def _run_answer_with_reader(self, fields: dict[str, object], reader) -> dict[str, object]:
        """Run a lookup against a mailbox that answers differently per query."""

        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "custom",
                "mode": "answer",
                "fields": fields,
                "deliveryChannel": "portal",
                "timezone": "Asia/Jerusalem",
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with _token_endpoint_patch():
            with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", side_effect=reader) as runner:
                with urllib_request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        self.reader_queries = [call.kwargs["query"] for call in runner.call_args_list]
        return payload

    def test_a_search_that_finds_nothing_is_asked_again_less_narrowly(self) -> None:
        # The vendor called it a statement, not a receipt. The narrow search
        # comes back empty, which reads as "you were never charged".
        def reader(_token, *, query, **_kwargs):
            if query.terms:
                return {"summary": "Gmail digest - 0 messages", "messageCount": 0, "items": []}
            return {
                "summary": "Gmail digest - 1 message",
                "messageCount": 1,
                "items": [{
                    "id": "msg-1",
                    "mailbox": "owner@gmail.com",
                    "subject": "Your Render statement",
                    "from": "Render <billing@render.com>",
                    "snippet": "Total charged $19.00",
                    "bodyText": "Total charged $19.00",
                }],
            }

        payload = self._run_answer_with_reader({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        }, reader)

        self.assertTrue(payload["ok"])
        self.assertIn("19.00 USD", payload["answer"])
        # The second read gave up the topic words and kept the vendor.
        self.assertEqual(len(self.reader_queries), 2)
        self.assertTrue(self.reader_queries[0].terms)
        self.assertEqual(self.reader_queries[1].terms, ())
        self.assertEqual(self.reader_queries[1].required_terms, ("Render",))
        # A wider search is a different question, so the answer says so.
        self.assertIn("Render", payload["widenedSearch"])

    def test_a_search_that_finds_something_is_never_widened(self) -> None:
        def reader(_token, *, query, **_kwargs):
            return {
                "summary": "Gmail digest - 1 message",
                "messageCount": 1,
                "items": [{
                    "id": "msg-1",
                    "mailbox": "owner@gmail.com",
                    "subject": "Your receipt from Render",
                    "from": "Render <billing@render.com>",
                    "snippet": "Total charged $19.00",
                    "bodyText": "Total charged $19.00",
                }],
            }

        payload = self._run_answer_with_reader({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        }, reader)

        self.assertEqual(len(self.reader_queries), 1)
        self.assertNotIn("widenedSearch", payload)

    def test_a_search_with_no_vendor_is_left_alone_when_it_finds_nothing(self) -> None:
        # There is nothing holding this one down, so widening it would read a
        # whole month of mail to answer a question about receipts.
        def reader(_token, *, query, **_kwargs):
            return {"summary": "Gmail digest - 0 messages", "messageCount": 0, "items": []}

        payload = self._run_answer_with_reader({
            "result": "Find receipts for August 2026",
            "manualRunMonth": "2026-08",
        }, reader)

        self.assertEqual(len(self.reader_queries), 1)
        self.assertNotIn("widenedSearch", payload)

    def test_a_question_comes_back_with_the_amount(self) -> None:
        payload = self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertTrue(payload["ok"])
        self.assertIn("19.00 USD", payload["answer"])
        self.assertIn("Render", payload["answer"])
        self.assertIn("Aug 2026", payload["answer"])

    def test_a_question_that_checks_an_earlier_answer_still_runs(self) -> None:
        # "Are you sure?" is the same search over the same month as the
        # question before it. It used to be told the lookup had no runner,
        # because the words it was phrased with were not on a list.
        payload = self._run_answer(
            {
                "result": "Re-check the Netflix receipts for August 2026 and verify the one on 20 Aug",
                "vendor": "Netflix",
                "manualRunMonth": "2026-08",
            },
            digest={
                "summary": "Gmail digest - 1 message",
                "messageCount": 1,
                "items": [{
                    "id": "msg-1",
                    "mailbox": "owner@gmail.com",
                    "subject": "Your payment to Netflix.com",
                    "from": "PayPal <service@paypal.com>",
                    "snippet": "You sent a payment of 71.80 ILS to Netflix.com",
                    "bodyText": "You sent a payment of 71.80 ILS to Netflix.com",
                }],
            },
        )

        self.assertTrue(payload["ok"])
        self.assertIn("71.80 ILS", payload["answer"])

    def test_a_vendor_and_a_month_are_enough_to_run(self) -> None:
        # A follow-up need not name receipts at all: the vendor and the month
        # it carries are what this search is built out of.
        payload = self._run_answer({
            "result": "Was there really a Netflix charge on 20 Aug?",
            "vendor": "Netflix",
            "manualRunMonth": "2026-08",
        })

        self.assertTrue(payload["ok"])

    def test_the_adverts_a_receipt_search_dragged_in_are_not_totalled(self) -> None:
        # A vendor that sends receipts sends far more mail carrying the words
        # a receipt search asks for. Every message below names an amount, and
        # only one of them is money that was actually paid.
        judged: list[str] = []

        def judge(**kwargs: Any) -> Any:
            judged.append(kwargs["tool_name"])
            return mock.Mock(output_text=json.dumps({"verdicts": [
                {"ref": "1", "isReceipt": False, "reason": "a sale announcement"},
                {"ref": "2", "isReceipt": False, "reason": "a delivery update"},
                {"ref": "3", "isReceipt": True, "paidTo": "Render"},
            ]}))

        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=judge):
            payload = self._run_answer(
                {
                    "result": "Find receipts from Render for August 2026",
                    "vendor": "Render",
                    "manualRunMonth": "2026-08",
                },
                digest={
                    "summary": "Gmail digest - 3 messages",
                    "messageCount": 3,
                    "items": [
                        {
                            "id": "msg-1",
                            "mailbox": "owner@gmail.com",
                            "subject": "Big save! Up to 70% off",
                            "from": "Render <deals@render.com>",
                            "bodyText": "Super deals are live. Plans from $1.99.",
                        },
                        {
                            "id": "msg-2",
                            "mailbox": "owner@gmail.com",
                            "subject": "Your order is on its way",
                            "from": "Render <shipping@render.com>",
                            "bodyText": "Your order has shipped. Order total $24.50.",
                        },
                        {
                            "id": "msg-3",
                            "mailbox": "owner@gmail.com",
                            "subject": "Your Render receipt",
                            "from": "Render <billing@render.com>",
                            "bodyText": "Total charged $19.00",
                        },
                    ],
                },
            )

        self.assertEqual(judged, ["portal_receipt_judge"])
        self.assertIn("19.00 USD", payload["answer"])
        self.assertIn("1 receipt", payload["answer"])
        self.assertNotIn("45.49", payload["answer"])

    # Two receipts of the same amount, days apart, that nothing in the mail
    # settles. A total is the one place a coin toss must not be reported as a
    # number, so the owner is asked.
    TWIN_DIGEST = {
        "summary": "Gmail digest - 2 messages",
        "messageCount": 2,
        "items": [
            {
                "id": "msg-20",
                "mailbox": "owner@gmail.com",
                "subject": "Your payment to Netflix.com",
                "from": "PayPal <service@paypal.com>",
                "date": "Thu, 20 Aug 2026 09:00:00 +0300",
                "bodyText": "You sent a payment of 71.80 ILS to Netflix.com",
            },
            {
                "id": "msg-28",
                "mailbox": "owner@gmail.com",
                "subject": "Your payment to Netflix.com",
                "from": "PayPal <service@paypal.com>",
                "date": "Fri, 28 Aug 2026 09:00:00 +0300",
                "bodyText": "You sent a payment of 71.80 ILS to Netflix.com",
            },
        ],
    }
    TWIN_FIELDS = {
        "result": "Find receipts from Netflix for August 2026",
        "vendor": "Netflix",
        "manualRunMonth": "2026-08",
    }

    def _twin_model(self, tools: list[str], *, unsure: bool = True) -> Any:
        def respond(**kwargs: Any) -> Any:
            tools.append(kwargs["tool_name"])
            if kwargs["tool_name"] == "portal_receipt_pairing":
                return mock.Mock(output_text=json.dumps({
                    "groups": [],
                    "unsure": [{
                        "refs": ["1", "2"],
                        "question": (
                            "Two payments of 71.80 ILS to Netflix.com, on 20 and 28 August. "
                            "Is that one payment reported twice, or two separate charges?"
                        ),
                    }] if unsure else [],
                }))
            return mock.Mock(output_text=json.dumps({"verdicts": [
                {"ref": "1", "isReceipt": True, "paidTo": "Netflix.com"},
                {"ref": "2", "isReceipt": True, "paidTo": "Netflix.com"},
            ]}))

        return respond

    def test_a_pair_nobody_can_settle_is_asked_about_rather_than_counted(self) -> None:
        tools: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            payload = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)

        self.assertTrue(payload["needsReceiptDecision"])
        self.assertNotIn("answer", payload)
        self.assertIn("71.80", payload["receiptQuestions"][0]["question"])
        self.assertEqual(len(payload["receiptQuestions"][0]["receipts"]), 2)
        self.assertTrue(payload["runToken"])
        self.assertIn("portal_receipt_pairing", tools)

    def test_the_answer_finishes_the_count_without_reading_the_mailbox_again(self) -> None:
        tools: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            asked = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)

        question = asked["receiptQuestions"][0]
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            payload = self._run_answer(
                self.TWIN_FIELDS,
                digest=self.TWIN_DIGEST,
                runToken=asked["runToken"],
                receiptDecisions=[{
                    "key": question["key"],
                    "decision": "same",
                    "keepRef": question["receipts"][0]["keepRef"],
                    "question": question["question"],
                }],
            )

        # The mail was read when the question was asked. Answering counts it
        # again; it does not go back to the mailbox.
        self.assertEqual(self.mailbox_reads, 0)
        self.assertIn("71.80 ILS", payload["answer"])
        self.assertEqual(payload["receiptCount"], 1)

    def test_two_payments_is_an_answer_too(self) -> None:
        tools: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            asked = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)
            payload = self._run_answer(
                self.TWIN_FIELDS,
                digest=self.TWIN_DIGEST,
                runToken=asked["runToken"],
                receiptDecisions=[{
                    "key": asked["receiptQuestions"][0]["key"],
                    "decision": "separate",
                }],
            )

        self.assertIn("143.60 ILS", payload["answer"])
        self.assertEqual(payload["receiptCount"], 2)

    def test_not_knowing_answers_the_run_without_being_remembered(self) -> None:
        tools: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            asked = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)
            payload = self._run_answer(
                self.TWIN_FIELDS,
                digest=self.TWIN_DIGEST,
                runToken=asked["runToken"],
                receiptDecisions=[{
                    "key": asked["receiptQuestions"][0]["key"],
                    "decision": "skip",
                }],
            )

        # Counted apart, which is the higher figure and the arguable one.
        self.assertIn("143.60 ILS", payload["answer"])
        # Nothing is written down: not knowing today says nothing about next
        # month, so a later run is free to ask again.
        user = self.server.database.get_user("owner@example.com") or {}
        self.assertEqual(
            self.server.database.list_receipt_duplicate_decisions(user_id=int(user["id"])),
            [],
        )

    def test_the_chat_is_told_how_many_questions_there_are(self) -> None:
        tools: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            asked = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)

        # One read finds them all, so the chat can say "1 of 3" instead of
        # letting the owner discover the second one by answering the first.
        self.assertEqual(asked["receiptQuestionCount"], len(asked["receiptQuestions"]))

    def test_the_same_pair_is_never_asked_about_twice(self) -> None:
        tools: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(tools)):
            asked = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)
            self._run_answer(
                self.TWIN_FIELDS,
                digest=self.TWIN_DIGEST,
                runToken=asked["runToken"],
                receiptDecisions=[{
                    "key": asked["receiptQuestions"][0]["key"],
                    "decision": "same",
                    "keepRef": asked["receiptQuestions"][0]["receipts"][0]["keepRef"],
                }],
            )

        # A fresh run, months later, with nothing in the message about it.
        later: list[str] = []
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=self._twin_model(later)):
            payload = self._run_answer(self.TWIN_FIELDS, digest=self.TWIN_DIGEST)

        self.assertNotIn("needsReceiptDecision", payload)
        self.assertIn("71.80 ILS", payload["answer"])
        # The pair is settled, so nothing is asked about it - not the owner,
        # and not the model either.
        self.assertNotIn("portal_receipt_pairing", later)

    def test_a_receipt_search_that_could_not_be_read_still_answers(self) -> None:
        # The model was unreachable. The lookup found receipts either way, and
        # an answer built from what the collector can see for itself beats no
        # answer at all.
        with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=OpenAIError("no key")):
            payload = self._run_answer({
                "result": "Find receipts from Render for August 2026",
                "vendor": "Render",
                "manualRunMonth": "2026-08",
            })

        self.assertTrue(payload["ok"])
        self.assertIn("19.00 USD", payload["answer"])

    def test_a_question_names_the_emails_its_answer_came_from(self) -> None:
        # Nothing is written, so the receipts stay in the mailbox. Naming them
        # is what lets "Save to a folder" go back for the receipt itself
        # rather than filing the sentence on its own.
        payload = self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertEqual(
            [(source["messageId"], source["mailbox"]) for source in payload["receiptSources"]],
            [("msg-1", "owner@gmail.com")],
        )

    def test_answering_a_question_saves_no_files(self) -> None:
        # The chat asked a question, not for a bundle. Writing one would also
        # overwrite the export a real receipt action saved for that month.
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        written = list(self.output_dir.rglob("*")) if self.output_dir.exists() else []
        self.assertEqual([path for path in written if path.is_file()], [])

    def test_the_vendor_is_searched_for_in_the_mailbox(self) -> None:
        # Filtering to the vendor after the read is what lost an August
        # receipt: the month returns more receipt mail than one read, and the
        # Render one sat past the end of it.
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        query = self.run_call.kwargs["query"]
        self.assertEqual(query.required_terms, ("Render",))
        self.assertIn("Render", to_gmail_query(query))

    def test_every_name_a_payment_could_carry_is_searched_for(self) -> None:
        # A PlayStation Plus charge arrives as a PayPal receipt naming Sony.
        # Requiring all three names asks the mailbox for mail that does not
        # exist, and the answer comes back "you are not paying for it".
        self._run_answer({
            "result": "Am I paying for PlayStation Plus?",
            "vendor": "PlayStation Plus, Sony, PlayStation Network",
            "manualRunMonth": "2026-08",
        })

        query = self.run_call.kwargs["query"]
        self.assertEqual(query.required_terms, ())
        self.assertEqual(query.required_any, ("PlayStation Plus", "Sony", "PlayStation Network"))
        self.assertIn('("PlayStation Plus" OR Sony OR "PlayStation Network")', to_gmail_query(query))

    def _receipt_item(self, index: int, date_header: str, amount: str) -> dict[str, object]:
        return {
            "id": f"msg-{index}",
            "mailbox": "owner@gmail.com",
            "subject": "Your Render receipt",
            "from": "Render <billing@render.com>",
            "date": date_header,
            "snippet": f"Total charged {amount}",
            "bodyText": f"Total charged {amount}",
        }

    def _run_span(self, months: str, items: list[dict[str, object]]) -> dict[str, object]:
        return self._run_answer(
            {
                "result": "Find receipts from Render across 2026",
                "vendor": "Render",
                "manualRunMonth": months,
            },
            digest={"summary": "Gmail digest", "messageCount": len(items), "items": items},
        )

    def _run_span_of_everything(self, months: str, items: list[dict[str, object]]) -> dict[str, object]:
        """A span with no vendor to narrow it, which is the shorter ceiling."""

        return self._run_answer(
            {"result": "Find all my receipts", "manualRunMonth": months},
            digest={"summary": "Gmail digest", "messageCount": len(items), "items": items},
        )

    def test_a_run_of_months_searches_the_mailbox_once(self) -> None:
        # Twelve months used to mean twelve searches of the same mailbox, each
        # one asking for the same mail with a different window around it.
        self._run_span("2026-07,2026-08,2026-09", [
            self._receipt_item(1, "Tue, 14 Jul 2026 10:00:00 +0300", "$10.00"),
        ])

        query = self.run_call.kwargs["query"]
        self.assertEqual(query.after.isoformat(), "2026-07-01")
        self.assertEqual(query.before.isoformat(), "2026-10-01")

    def test_the_months_are_still_counted_apart(self) -> None:
        payload = self._run_span("2026-07,2026-08,2026-09", [
            self._receipt_item(1, "Tue, 14 Jul 2026 10:00:00 +0300", "$10.00"),
            self._receipt_item(2, "Sat, 01 Aug 2026 09:00:00 +0300", "$19.00"),
            self._receipt_item(3, "Mon, 31 Aug 2026 23:30:00 +0300", "$1.00"),
        ])

        months = payload["months"]
        self.assertEqual([month["monthLabel"] for month in months], ["Jul 2026", "Aug 2026", "Sep 2026"])
        self.assertEqual(months[0]["totals"], {"USD": 10.0})
        self.assertEqual(months[1]["totals"], {"USD": 20.0})
        # A month with nothing in it is still reported, or it reads as a month
        # that was never checked.
        self.assertEqual(months[2]["receiptCount"], 0)
        self.assertEqual(payload["totals"], {"USD": 30.0})

    def test_a_receipt_keeps_the_month_its_own_date_says(self) -> None:
        # Half past midnight in Jerusalem is still the previous day in UTC, and
        # the month a person sees on the email is the month it belongs to.
        payload = self._run_span("2026-07,2026-08", [
            self._receipt_item(1, "Sat, 01 Aug 2026 00:30:00 +0300", "$5.00"),
        ])

        months = {month["monthLabel"]: month for month in payload["months"]}
        self.assertEqual(months["Aug 2026"]["receiptCount"], 1)
        self.assertEqual(months["Jul 2026"]["receiptCount"], 0)

    def test_an_email_with_no_readable_date_is_counted_out_loud(self) -> None:
        payload = self._run_span("2026-07,2026-08", [
            self._receipt_item(1, "Tue, 14 Jul 2026 10:00:00 +0300", "$10.00"),
            self._receipt_item(2, "not a date", "$99.00"),
        ])

        # It cannot go in a month, so it goes in the sentence instead.
        self.assertEqual(payload["undatedCount"], 1)
        self.assertEqual(payload["totals"], {"USD": 10.0})

    def test_the_ceiling_follows_the_span(self) -> None:
        self._run_span("2026-07,2026-08,2026-09", [
            self._receipt_item(1, "Tue, 14 Jul 2026 10:00:00 +0300", "$10.00"),
        ])

        # Three months of receipts held to one month's ceiling would cut the
        # older end off every long question.
        self.assertEqual(
            self.run_call.kwargs["max_results"],
            AGENT_RECEIPT_ANSWER_MAX_MESSAGES * 3 + 1,
        )

    TWELVE_MONTHS = (
        "2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,"
        "2026-04,2026-05,2026-06,2026-07,2026-08,2026-09"
    )

    def test_a_year_of_one_vendor_is_read_in_one_go(self) -> None:
        # "Am I still paying for this" needs a year: a yearly subscription
        # charges once, and half a year can miss it completely. One vendor's
        # year is a handful of messages, so it costs one search.
        payload = self._run_span(self.TWELVE_MONTHS, [
            self._receipt_item(1, "Tue, 05 May 2026 21:36:00 +0300", "$10.00"),
        ])

        query = self.run_call.kwargs["query"]
        self.assertEqual(query.after.isoformat(), "2025-10-01")
        self.assertEqual(query.before.isoformat(), "2026-10-01")
        self.assertNotIn("monthsNotSearched", payload)

    def test_last_septembers_yearly_renewal_is_in_reach_in_september(self) -> None:
        # Twelve months asked on 17 Sep 2026 start in October and miss a
        # yearly plan renewed on 25 Sep 2025, due again next week. This month
        # and the twelve before it reach that charge.
        payload = self._run_span("2025-09," + self.TWELVE_MONTHS, [
            self._receipt_item(1, "Thu, 25 Sep 2025 10:00:00 +0300", "$79.99"),
        ])

        self.assertEqual(self.run_call.kwargs["query"].after.isoformat(), "2025-09-01")
        self.assertNotIn("monthsNotSearched", payload)
        self.assertEqual(payload["months"][0]["monthLabel"], "Sep 2025")
        self.assertEqual(payload["months"][0]["receiptCount"], 1)

    def test_a_year_of_everyone_still_stops_at_six_months(self) -> None:
        # Without a vendor the same year is every receipt-ish email the
        # mailbox holds, which is not one search.
        payload = self._run_answer(
            {"result": "Find all my receipts for the last year", "manualRunMonth": self.TWELVE_MONTHS},
            digest={"summary": "Gmail digest", "messageCount": 0, "items": []},
        )

        self.assertEqual(self.run_call.kwargs["query"].after.isoformat(), "2026-04-01")
        self.assertEqual(payload["monthsNotSearched"][-1], "Mar 2026")

    def test_a_span_too_long_to_read_is_answered_from_its_recent_end(self) -> None:
        # Twelve months is more than one request covers. The six it reads are
        # the ones nearest today: "look further back" is asked about something
        # being paid for now, and reading last autumn instead answers nothing.
        payload = self._run_span_of_everything(
            self.TWELVE_MONTHS,
            [self._receipt_item(1, "Tue, 05 May 2026 21:36:00 +0300", "$10.00")],
        )

        query = self.run_call.kwargs["query"]
        self.assertEqual(query.after.isoformat(), "2026-04-01")
        self.assertEqual(query.before.isoformat(), "2026-10-01")
        self.assertEqual([month["monthLabel"] for month in payload["months"]][0], "Apr 2026")

    def test_the_months_that_were_not_read_are_named_rather_than_dropped(self) -> None:
        # Nothing found over six months reads as nothing found over the twelve
        # that were asked about, unless the six are named.
        payload = self._run_span_of_everything(
            self.TWELVE_MONTHS,
            [self._receipt_item(1, "Tue, 05 May 2026 21:36:00 +0300", "$10.00")],
        )

        self.assertEqual(payload["monthsSearched"][0], "Apr 2026")
        self.assertEqual(payload["monthsSearched"][-1], "Sep 2026")
        self.assertEqual(payload["monthsNotSearched"][0], "Oct 2025")
        self.assertEqual(payload["monthsNotSearched"][-1], "Mar 2026")

    def test_a_span_that_fits_says_nothing_about_months_it_missed(self) -> None:
        payload = self._run_span("2026-07,2026-08,2026-09", [
            self._receipt_item(1, "Tue, 14 Jul 2026 10:00:00 +0300", "$10.00"),
        ])

        self.assertNotIn("monthsNotSearched", payload)

    def test_the_charges_come_back_with_the_rhythm_they_make(self) -> None:
        # A total cannot answer "am I still paying for this". How far apart
        # the charges sit can, so the gaps are read and handed over.
        payload = self._run_span("2026-07,2026-08,2026-09", [
            self._receipt_item(1, "Mon, 06 Jul 2026 08:00:00 +0300", "$19.00"),
            self._receipt_item(2, "Thu, 06 Aug 2026 08:00:00 +0300", "$19.00"),
            self._receipt_item(3, "Sun, 06 Sep 2026 08:00:00 +0300", "$19.00"),
        ])

        rhythm = payload["subscription"]
        self.assertEqual(rhythm["cadence"], "monthly")
        self.assertEqual(rhythm["chargeCount"], 3)
        self.assertEqual(rhythm["lastCharge"], "2026-09-06")
        self.assertEqual(rhythm["nextExpected"], "2026-10-06")
        self.assertTrue(rhythm["settled"])

    def test_one_charge_comes_back_as_a_question_it_could_not_settle(self) -> None:
        # One payment to Sony in May, and nothing saying whether it bought a
        # month or a year. The answer must not pick one.
        payload = self._run_answer(
            {
                "result": "Am I paying for PlayStation Plus?",
                "vendor": "PlayStation Plus, Sony",
                "manualRunMonth": "2026-05",
            },
            digest={"summary": "Gmail digest", "messageCount": 1, "items": [{
                "id": "msg-9",
                "mailbox": "owner@gmail.com",
                "subject": "Receipt for Your Payment to SONY INTERACTIVE ENT",
                "from": "PayPal <service@paypal.co.il>",
                "date": "Tue, 05 May 2026 21:36:00 +0300",
                "snippet": "You paid ILS 550.00 to SONY INTERACTIVE ENT",
                "bodyText": "You paid ILS 550.00 to SONY INTERACTIVE ENT",
            }]},
        )

        rhythm = payload["subscription"]
        self.assertEqual(rhythm["cadence"], "unclear")
        self.assertEqual(rhythm["lastAmount"], "550.00 ILS")
        self.assertIsNone(rhythm["stillRunning"])
        self.assertFalse(rhythm["settled"])

    def test_a_question_with_no_vendor_asks_for_no_rhythm(self) -> None:
        # "What did I spend in August" is a question about a month, not about
        # whether one thing is still being paid for.
        payload = self._run_answer({
            "result": "Find all my receipts for August 2026",
            "manualRunMonth": "2026-08",
        })

        self.assertNotIn("subscription", payload)

    def test_one_month_answers_exactly_as_it_always_has(self) -> None:
        payload = self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertNotIn("months", payload)
        self.assertEqual(payload["monthLabel"], "Aug 2026")

    def test_a_mailbox_with_more_than_one_read_holds_says_so(self) -> None:
        # Reading the first 100 and reporting the total as if that were all of
        # it is the same failure as a mailbox that could not be opened: a
        # partial answer passing for the whole one.
        overflowing = {
            "summary": "Gmail digest",
            "messageCount": AGENT_RECEIPT_ANSWER_MAX_MESSAGES + 1,
            "items": [
                {
                    "id": f"msg-{index}",
                    "mailbox": "owner@gmail.com",
                    "subject": "Your Render receipt",
                    "from": "Render <billing@render.com>",
                    "snippet": "Total charged $1.00",
                    "bodyText": "Total charged $1.00",
                }
                for index in range(AGENT_RECEIPT_ANSWER_MAX_MESSAGES + 1)
            ],
        }
        payload = self._run_answer(
            {
                "result": "Find receipts from Render for August 2026",
                "vendor": "Render",
                "manualRunMonth": "2026-08",
            },
            digest=overflowing,
        )

        self.assertEqual(
            payload["cappedMailboxes"],
            # The mailbox is named the way every other message names it, which
            # is the connection's display name and not the address on the row.
            [{"mailbox": "Gmail", "limit": AGENT_RECEIPT_ANSWER_MAX_MESSAGES}],
        )
        # Only what was actually read is counted, so the total and the caveat
        # describe the same set of receipts.
        self.assertEqual(payload["receiptCount"], AGENT_RECEIPT_ANSWER_MAX_MESSAGES)

    def test_a_reader_that_stopped_early_is_reported_as_short(self) -> None:
        # The reader holds a lower ceiling than the run and stops there
        # without handing back anything past it, so the run cannot count
        # what it cut. The reader's own word is what says the year was not
        # all read - without it "nothing since June" passed as "nothing".
        payload = self._run_answer(
            {
                "result": "Find receipts from Render for August 2026",
                "vendor": "Render",
                "manualRunMonth": "2026-08",
            },
            digest={
                "summary": "Gmail digest",
                "messageCount": 0,
                "items": [],
                "leftMailBehind": True,
                "readLimit": 100,
            },
        )

        self.assertEqual(payload["cappedMailboxes"], [{"mailbox": "Gmail", "limit": 100}])

    def test_a_mailbox_that_fits_says_nothing_about_a_ceiling(self) -> None:
        payload = self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertNotIn("cappedMailboxes", payload)

    def test_the_read_looks_one_past_its_own_ceiling(self) -> None:
        # Filling the ceiling exactly is not the same as having more behind it,
        # and warning about a month that happened to hold exactly 100 would be
        # a caveat on a complete answer.
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertEqual(
            self.run_call.kwargs["max_results"],
            AGENT_RECEIPT_ANSWER_MAX_MESSAGES + 1,
        )

    def test_the_search_knows_the_words_a_receipt_actually_uses(self) -> None:
        # A vendor that writes "Payment confirmation" and never "receipt" was
        # invisible to this search while its receipts sat in the mailbox.
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        terms = self.run_call.kwargs["query"].terms
        for word in ("receipt", "invoice", "payment", "purchase", "charged", "paid"):
            self.assertIn(word, terms)

    def test_a_question_reads_more_than_a_digest_does(self) -> None:
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertGreater(self.run_call.kwargs["max_results"], GMAIL_MAX_DIGEST_MESSAGES)

    def test_the_answer_carries_the_month_it_covered(self) -> None:
        # The chat adds several months up itself, which needs the parts.
        payload = self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertEqual(payload["monthLabel"], "Aug 2026")
        self.assertEqual(payload["vendor"], "Render")
        self.assertEqual(payload["totals"], {"USD": 19.0})

    def test_answering_a_question_skips_downloading_attachments(self) -> None:
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertFalse(self.run_call.kwargs["include_attachments"])

    def test_answering_a_question_still_reads_the_email_itself(self) -> None:
        # Not downloading attachments is not the same as not opening the email:
        # the total is in the body, so a headers-only read can only answer when
        # the amount happens to be in the subject line.
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertTrue(self.run_call.kwargs["include_body"])


class _FakeGmailResponse:
    """One Gmail JSON reply, shaped like the object urlopen hands back."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeGmailResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class GmailSearchReachTests(unittest.TestCase):
    """A month holds more receipt mail than one page of results."""

    def test_a_search_reads_past_the_first_page(self) -> None:
        # The receipt that answers the question can be the eleventh newest,
        # and reading only the first page reported it as missing.
        listed: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = getattr(request, "full_url", str(request))
            if "/messages?" in url:
                listed.append(url)
                if "pageToken=" in url:
                    return _FakeGmailResponse({
                        "messages": [{"id": f"late-{index}"} for index in range(5)],
                    })
                return _FakeGmailResponse({
                    "messages": [{"id": f"recent-{index}"} for index in range(10)],
                    "nextPageToken": "page-two",
                })
            return _FakeGmailResponse({
                "id": url.rsplit("/", 1)[-1].split("?")[0],
                "payload": {"headers": [
                    {"name": "Subject", "value": "Your Render receipt"},
                    {"name": "From", "value": "Render <billing@render.com>"},
                ]},
                "snippet": "Total charged $19.00",
            })

        items = GmailDigestRunner(opener=opener).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("receipt",), required_terms=("Render",)),
            max_results=15,
        )

        self.assertEqual(len(items), 15)
        self.assertEqual(len(listed), 2)
        self.assertIn("pageToken=page-two", listed[1])

    def test_a_digest_still_reads_only_its_own_handful(self) -> None:
        pages: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = getattr(request, "full_url", str(request))
            if "/messages?" in url:
                pages.append(url)
                return _FakeGmailResponse({
                    "messages": [{"id": f"message-{index}"} for index in range(10)],
                    "nextPageToken": "page-two",
                })
            return _FakeGmailResponse({"id": "message", "payload": {"headers": []}})

        items = GmailDigestRunner(opener=opener).fetch_message_summaries("token")

        self.assertEqual(len(items), GMAIL_MAX_DIGEST_MESSAGES)
        self.assertEqual(len(pages), 1)

    def _listing_opener(self, listed: list[str], ids: list[str]):
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = getattr(request, "full_url", str(request))
            if "/messages?" in url:
                listed.append(url)
                return _FakeGmailResponse({"messages": [{"id": value} for value in ids]})
            return _FakeGmailResponse({
                "id": url.rsplit("/", 1)[-1].split("?")[0],
                "payload": {"headers": [{"name": "Subject", "value": "Receipt"}]},
            })

        return opener

    def test_the_vendor_reaches_gmail_whole(self) -> None:
        # "Am I paying for PlayStation Plus?" searched a year of everyone's
        # receipts: the reader cut the query at 200 characters, the receipt
        # words filled them, and the names at the end - the Sony a PayPal
        # receipt carries - never reached Gmail. Its May receipt sat behind
        # four months of other mail.
        listed: list[str] = []
        query = MailQuery(
            terms=AGENT_RECEIPT_SEARCH_TERMS,
            required_any=("PlayStation Plus", "Sony", "PlayStation Network"),
            after=date(2025, 9, 1),
            before=date(2026, 10, 1),
        )
        GmailDigestRunner(opener=self._listing_opener(listed, ["one"])).run(
            "token", query=query, max_results=10, include_body=True,
        )

        sent = urllib_parse.parse_qs(urllib_parse.urlparse(listed[0]).query)["q"][0]
        self.assertEqual(sent, to_gmail_query(query))
        self.assertIn('("PlayStation Plus" OR Sony OR "PlayStation Network")', sent)

    def test_a_read_that_stops_with_mail_behind_it_says_so(self) -> None:
        listed: list[str] = []
        result = GmailDigestRunner(opener=self._listing_opener(listed, ["a", "b", "c"])).run(
            "token", query=MailQuery(terms=("receipt",)), max_results=2, include_body=True,
            known=lambda ids: {},
        )

        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["leftMailBehind"])
        self.assertEqual(result["readLimit"], 2)

    def test_a_read_that_reaches_the_end_says_nothing_was_left(self) -> None:
        result = GmailDigestRunner(opener=self._listing_opener([], ["a", "b"])).run(
            "token", query=MailQuery(terms=("receipt",)), max_results=5, include_body=True,
            known=lambda ids: {},
        )

        self.assertFalse(result["leftMailBehind"])


class GmailDraftTests(unittest.TestCase):
    """A reply someone started writing is not a second receipt."""

    def _opener(self, *, draft_labels: list[str]):
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = getattr(request, "full_url", str(request))
            if "/messages?" in url:
                return _FakeGmailResponse({"messages": [{"id": "receipt-1"}, {"id": "draft-1"}]})
            message_id = url.rsplit("/", 1)[-1].split("?")[0]
            if message_id == "draft-1":
                return _FakeGmailResponse({
                    "id": "draft-1",
                    "threadId": "thread-1",
                    "labelIds": draft_labels,
                    "payload": {"headers": [
                        {"name": "Subject", "value": "Re: Your payment to Netflix.com"},
                        {"name": "From", "value": "Owner <owner@example.com>"},
                        {"name": "Date", "value": "Fri, 28 Aug 2026 09:00:00 +0300"},
                    ]},
                    # A reply quotes what it answers, so the draft carries the
                    # receipt's own words and its amount.
                    "snippet": "You sent a payment of 71.80 ILS to Netflix.com",
                })
            return _FakeGmailResponse({
                "id": "receipt-1",
                "threadId": "thread-1",
                "labelIds": ["INBOX"],
                "payload": {"headers": [
                    {"name": "Subject", "value": "Your payment to Netflix.com"},
                    {"name": "From", "value": "PayPal <service@paypal.com>"},
                    {"name": "Date", "value": "Thu, 20 Aug 2026 09:00:00 +0300"},
                ]},
                "snippet": "You sent a payment of 71.80 ILS to Netflix.com",
            })

        return opener

    def test_a_draft_reply_to_a_receipt_is_not_read_as_mail(self) -> None:
        # One payment, one receipt, and a reply the owner began and left in
        # drafts. Counted, the reply turns 71.80 into 143.60.
        items = GmailDigestRunner(opener=self._opener(draft_labels=["DRAFT"])).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("payment",), required_terms=("Netflix",)),
            max_results=10,
        )

        self.assertEqual([item["id"] for item in items], ["receipt-1"])

    def test_the_receipt_the_draft_answers_is_still_counted(self) -> None:
        items = GmailDigestRunner(opener=self._opener(draft_labels=["DRAFT"])).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("payment",), required_terms=("Netflix",)),
            max_results=10,
        )
        answer = answer_receipt_question(items, vendor="Netflix", month_label="Aug 2026")

        self.assertEqual(answer["totals"], {"ILS": 71.80})

    def test_a_message_carrying_other_labels_is_left_alone(self) -> None:
        # Only the draft label decides this. A receipt is labelled too.
        items = GmailDigestRunner(opener=self._opener(draft_labels=["INBOX", "IMPORTANT"])).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("payment",), required_terms=("Netflix",)),
            max_results=10,
        )

        self.assertEqual([item["id"] for item in items], ["receipt-1", "draft-1"])


class GmailAnswerBodyTests(unittest.TestCase):
    """A question asked in chat has to read the email, not just its headers."""

    RECEIPT_HTML = (
        "<html><body><p>Receipt from Render Services, Inc dba Render</p>"
        "<table><tr><td>Amount paid</td><td>$13.35</td></tr></table></body></html>"
    )

    def _opener(self, urls: list[str]):
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = getattr(request, "full_url", str(request))
            urls.append(url)
            if "/messages?" in url:
                return _FakeGmailResponse({"messages": [{"id": "receipt-1"}]})
            return _FakeGmailResponse({
                "id": "receipt-1",
                "payload": {
                    "mimeType": "text/html",
                    "headers": [
                        {"name": "Subject", "value": "Your receipt from Render #2021-3589"},
                        {"name": "From", "value": "Render <invoice@stripe.com>"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(
                        self.RECEIPT_HTML.encode("utf-8")
                    ).decode("ascii")},
                },
                "snippet": "Receipt from Render Services, Inc dba Render",
            })

        return opener

    def test_asking_for_the_body_asks_gmail_for_the_whole_message(self) -> None:
        # The total lives in the body. Gmail only sends it for format=full, so
        # a headers-only fetch can answer "how much" by luck alone.
        urls: list[str] = []
        items = GmailDigestRunner(opener=self._opener(urls)).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("receipt",)),
            include_body=True,
        )

        self.assertIn("format=full", urls[1])
        self.assertIn("$13.35", items[0]["bodyText"])

    def test_a_body_read_saves_no_attachments(self) -> None:
        # Answering in chat writes no files, so it must not start downloading
        # attachments just because it now reads the body.
        items = GmailDigestRunner(opener=self._opener([])).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("receipt",)),
            include_body=True,
        )

        self.assertNotIn("attachments", items[0])

    def test_a_digest_still_reads_headers_only(self) -> None:
        urls: list[str] = []
        GmailDigestRunner(opener=self._opener(urls)).fetch_message_summaries("token")

        self.assertIn("format=metadata", urls[1])

    def test_the_amount_survives_the_whole_way_into_the_answer(self) -> None:
        items = GmailDigestRunner(opener=self._opener([])).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("receipt",)),
            include_body=True,
        )
        answer = answer_receipt_question(items, vendor="Render", month_label="Aug 2026")

        self.assertEqual(answer["totals"], {"USD": 13.35})
        self.assertIn("13.35 USD", answer["answer"])


if __name__ == "__main__":
    unittest.main()
