"""Questions that get an answer instead of an action.

"How much did I pay Render this month?" used to come back as an offer to set
up an action. These tests pin the behaviour that replaced it: the agent runs
the lookup on the spot, answers in the chat, and saves nothing.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.gmail_summary import GMAIL_MAX_DIGEST_MESSAGES
from packages.infrastructure.gmail_summary import GmailDigestRunner
from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.mail_search import to_gmail_query
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
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

    def _run_answer(self, fields: dict[str, object]) -> dict[str, object]:
        digest = {
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
        return payload

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


class AgentAnswerChatTests(unittest.TestCase):
    """The chat side: a question runs and reports back in the conversation."""

    def setUp(self) -> None:
        self.script = (Path(__file__).resolve().parents[1] / "portal" / "app.js").read_text(encoding="utf-8")

    def test_an_answer_turn_runs_the_lookup_instead_of_making_a_proposal(self) -> None:
        turn_handler = self.script[
            self.script.index("async function applyAgentTurnResponse"):
            self.script.index("function buildAgentReplyMetadata")
        ]

        self.assertIn('if (outcome === "answer_now" && await runAgentAnswerNow(turn, userText))', turn_handler)
        # The proposal branch must stay behind it, or a question becomes a plan.
        self.assertLess(
            turn_handler.index('outcome === "answer_now"'),
            turn_handler.index('if (outcome === "proposal"'),
        )

    def test_a_running_lookup_says_it_is_running_a_task(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertIn('agentTurnProgressText = "Running task"', runner)
        self.assertIn("mode: runMode,", runner)
        self.assertIn('kind: everyTaskFailed ? "error" : "result"', runner)

    def test_a_finished_one_off_offers_what_it_produced(self) -> None:
        runner = self.script[
            self.script.index("function buildAgentAnswerResultActions"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        # A one-off saves no action, so anything worth keeping has to be
        # offered on the result itself while the user is looking at it.
        self.assertIn('createAgentAction("open-result-file", "Read PDF"', runner)
        self.assertIn('createAgentAction("open-result-folder", "Open folder"', runner)
        self.assertIn('createAgentAction("save-answer-to-folder", "Save to a folder")', runner)
        self.assertIn('createAgentAction("save-one-off-as-action", "Save as an action")', runner)
        # Two lookups do not fold into one saved action.
        self.assertIn("if (tasks.length === 1) {", runner)
        self.assertIn("keepActions: resultActions.length > 0", runner)

    def test_a_result_button_outlives_the_messages_after_it(self) -> None:
        # "Read PDF" has to still work once the conversation has moved on.
        resolver = self.script[
            self.script.index("function areAgentMessageActionsResolved"):
            self.script.index("function getAgentStoredMessageActions")
        ]

        self.assertIn("if (message.metadata?.keepActions) {\n    return false;\n  }", resolver)

    def test_a_job_asked_for_once_runs_in_full_rather_than_answering(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function runAgentAnswerNow")
        ]

        self.assertIn('const runMode = task?.mode === "run" ? "run" : "answer";', runner)
        self.assertIn("mode: runMode,", runner)

    def test_the_answer_lands_in_the_chat_rather_than_a_notification(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertNotIn("addAgentNotification", runner)

    def test_every_month_the_question_named_gets_its_own_lookup(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertIn("for (const month of months)", runner)
        self.assertIn("manualRunMonth: month", runner)
        # Every month's result is kept, so an empty month still reports.
        self.assertIn("composeAgentMonthlyAnswer(results)", runner)

    def test_the_progress_line_names_the_month_being_read(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        # Several reads in a row look like one long stall otherwise.
        self.assertIn('agentTurnProgressText = monthLabel ? `Checking ${monthLabel}${step}` : label', runner)

    def test_a_comparison_answer_carries_its_chart(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        # The chart is built from the run's own results, so the picture and the
        # paragraph above it can never disagree.
        self.assertIn("chart: buildAgentAnswerMonthlyChart(results),", runner)
        self.assertIn("const charts = sections.map((section) => section.chart).filter(Boolean);", runner)
        # Two lookups in one message would need two labelled cards.
        self.assertIn("const chart = charts.length === 1 ? charts[0] : null;", runner)
        self.assertIn("chart: everyTaskFailed ? undefined : chart || undefined,", runner)

    def test_a_chart_is_drawn_beside_the_message_that_carries_one(self) -> None:
        renderer = self.script[
            self.script.index("function renderAgentMessage(message) {"):
            self.script.index("function getAgentMessageRenderSignature")
        ]

        # A chart is not a kind of message: it rides along with one, so an
        # answer keeps its own kind and its buttons and still shows the chart.
        self.assertIn("const chart = normalizeAgentChart(message.metadata?.chart);", renderer)
        self.assertIn("row.append(createAgentChartCard(chart));", renderer)

    def test_a_chart_knows_nothing_about_what_it_is_charting(self) -> None:
        card = self.script[
            self.script.index("function createAgentChartCard"):
            self.script.index("function renderAgentMessageBubbleContent")
        ]

        # One card serves every comparison, so the moment it mentions receipts,
        # months, or currencies it has stopped being reusable.
        for word in ("receipt", "month", "vendor", "mailbox", "ILS", "totals"):
            self.assertNotIn(word, card)

    def test_a_month_that_could_not_be_read_is_named(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerTask"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertIn("missedMonths.push", runner)
        self.assertIn("I couldn\u2019t check", runner)


def _run_agent_answer_month_script(expression: str) -> Any:
    """Run the chat's month splitting in node, with its date sources fixed."""

    script = (Path(__file__).resolve().parents[1] / "portal" / "app.js").read_text(encoding="utf-8")
    month_parser = script[
        script.index("const AGENT_MONTH_NAME_INDEX"):
        script.index("function formatAgentPreviousMonth")
    ]
    answer_helpers = script[
        script.index("const AGENT_ANSWER_RUN_MONTH_LIMIT"):
        script.index("async function runAgentAnswerNow")
    ]
    # The chart data itself is defined with the other message normalizers, so
    # the builder below it has something to build.
    chart_model = script[
        script.index("const AGENT_CHART_POINT_LIMIT"):
        script.index("function normalizeAgentMessage")
    ]
    harness = "\n".join([
        'function getWorkspaceTimeZone() { return "UTC"; }',
        "function getAgentWorkspaceDateParts() { return new Date(Date.UTC(2026, 7, 15)); }",
        chart_model,
        month_parser,
        answer_helpers,
        f"console.log(JSON.stringify({expression}));",
    ])
    completed = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the chat script")
class AgentAnswerMonthSplitTests(unittest.TestCase):
    """A question naming two months has to run two lookups, not one."""

    def test_two_months_become_two_lookups(self) -> None:
        result = _run_agent_answer_month_script(
            'getAgentAnswerRunMonths({ manualRunMonth: "2026-07,2026-08" })'
        )

        self.assertEqual(result["months"], ["2026-07", "2026-08"])
        self.assertFalse(result["trimmed"])

    def test_a_month_named_only_in_the_request_text_still_runs(self) -> None:
        # The model may fill one month into the field and leave the second in
        # the sentence; both months were asked about either way.
        result = _run_agent_answer_month_script(
            'getAgentAnswerRunMonths({'
            ' manualRunMonth: "2026-08",'
            ' result: "Find receipts from Render for July and August 2026"'
            ' })'
        )

        self.assertEqual(result["months"], ["2026-07", "2026-08"])

    def test_the_word_may_is_not_read_as_a_month(self) -> None:
        result = _run_agent_answer_month_script(
            'getAgentAnswerRunMonths({'
            ' manualRunMonth: "2026-08",'
            ' result: "Find receipts that may name a total"'
            ' })'
        )

        self.assertEqual(result["months"], ["2026-08"])

    def test_no_month_leaves_the_run_to_resolve_its_own(self) -> None:
        result = _run_agent_answer_month_script("getAgentAnswerRunMonths({})")

        self.assertEqual(result["months"], [""])

    def test_a_whole_year_is_checked_month_by_month(self) -> None:
        # "Compare 2026 month by month" used to come back six months short.
        months = ",".join(f"2026-{month:02d}" for month in range(1, 9))
        result = _run_agent_answer_month_script(
            f'getAgentAnswerRunMonths({{ manualRunMonth: "{months}" }})'
        )

        self.assertEqual(len(result["months"]), 8)
        self.assertEqual(result["months"][-1], "2026-08")
        self.assertFalse(result["trimmed"])

    def test_a_long_list_of_months_keeps_the_newest_and_says_so(self) -> None:
        months = ",".join(f"2025-{month:02d}" for month in range(1, 13))
        months = f"{months},2026-01,2026-02"
        result = _run_agent_answer_month_script(
            f'getAgentAnswerRunMonths({{ manualRunMonth: "{months}" }})'
        )

        self.assertEqual(len(result["months"]), 12)
        # The months that fall off the end are the oldest ones, because the
        # newest are the half of a long comparison anyone is asking about.
        self.assertEqual(result["months"][0], "2025-03")
        self.assertEqual(result["months"][-1], "2026-02")
        self.assertTrue(result["trimmed"])

    def test_two_months_are_added_up_into_one_answer(self) -> None:
        answer = _run_agent_answer_month_script(
            "composeAgentMonthlyAnswer(["
            ' { monthLabel: "Jul 2026", vendor: "Render", totals: {}, receiptCount: 0 },'
            ' { monthLabel: "Aug 2026", vendor: "Render", totals: { USD: 19 }, receiptCount: 1 }'
            "])"
        )

        self.assertIn("You paid 19.00 USD to Render across Jul 2026 and Aug 2026", answer)
        self.assertIn("Jul 2026: nothing found", answer)
        self.assertIn("Aug 2026: 19.00 USD (1 receipt)", answer)

    def test_two_empty_months_say_so_once(self) -> None:
        answer = _run_agent_answer_month_script(
            "composeAgentMonthlyAnswer(["
            ' { monthLabel: "Jul 2026", vendor: "Render", totals: {}, receiptCount: 0 },'
            ' { monthLabel: "Aug 2026", vendor: "Render", totals: {}, receiptCount: 0 }'
            "])"
        )

        self.assertIn("any receipts to Render in Jul 2026 and Aug 2026", answer)
        self.assertNotIn("nothing found", answer)

    def test_one_month_keeps_the_sentence_the_run_wrote(self) -> None:
        answer = _run_agent_answer_month_script(
            'composeAgentMonthlyAnswer([{ monthLabel: "Aug 2026", totals: { USD: 19 }, receiptCount: 1 }])'
        )

        self.assertEqual(answer, "")

    def test_receipts_with_no_readable_amount_are_still_counted_out_loud(self) -> None:
        answer = _run_agent_answer_month_script(
            "composeAgentMonthlyAnswer(["
            ' { monthLabel: "Jul 2026", totals: { USD: 5 }, receiptCount: 1 },'
            ' { monthLabel: "Aug 2026", totals: { USD: 19 }, receiptCount: 1, missingAmountCount: 2 }'
            "])"
        )

        self.assertIn("You paid 24.00 USD across Jul 2026 and Aug 2026, over 2 receipts.", answer)
        self.assertIn("2 more with no amount I could read", answer)

    def test_a_month_is_labelled_the_way_the_answer_reads(self) -> None:
        self.assertEqual(
            _run_agent_answer_month_script('formatAgentAnswerMonthLabel("2026-07")'),
            "Jul 2026",
        )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the chat script")
class AgentAnswerChartTests(unittest.TestCase):
    """A month-by-month answer is a comparison, and gets drawn as one."""

    def test_months_become_one_bar_each(self) -> None:
        chart = _run_agent_answer_month_script(
            "buildAgentAnswerMonthlyChart(["
            ' { monthLabel: "Jul 2026", vendor: "Apple", totals: { ILS: 154.5 }, receiptCount: 6 },'
            ' { monthLabel: "Aug 2026", vendor: "Apple", totals: { ILS: 314.1 }, receiptCount: 10 }'
            "])"
        )

        self.assertEqual(chart["type"], "bar")
        self.assertEqual(chart["title"], "What you paid Apple, by month")
        self.assertEqual([point["label"] for point in chart["points"]], ["Jul 2026", "Aug 2026"])
        self.assertEqual([point["value"] for point in chart["points"]], [154.5, 314.1])
        # The bar is a shape; the amount beside it is the answer.
        self.assertEqual(chart["points"][1]["display"], "314.10 ILS")
        self.assertEqual(chart["caption"], "Amounts in ILS.")

    def test_a_month_with_nothing_in_it_still_gets_a_bar(self) -> None:
        chart = _run_agent_answer_month_script(
            "buildAgentAnswerMonthlyChart(["
            ' { monthLabel: "Jul 2026", totals: {}, receiptCount: 0 },'
            ' { monthLabel: "Aug 2026", totals: { ILS: 314.1 }, receiptCount: 10 }'
            "])"
        )

        self.assertEqual(chart["points"][0]["value"], 0)
        self.assertEqual(chart["points"][0]["note"], "nothing found")

    def test_receipts_with_no_readable_amount_say_so_on_the_bar(self) -> None:
        # A short bar that stands for "I could not read it" would otherwise be
        # read as a quiet month.
        chart = _run_agent_answer_month_script(
            "buildAgentAnswerMonthlyChart(["
            ' { monthLabel: "Jul 2026", totals: { ILS: 10 }, receiptCount: 3, missingAmountCount: 2 },'
            ' { monthLabel: "Aug 2026", totals: { ILS: 314.1 }, receiptCount: 10 }'
            "])"
        )

        self.assertEqual(chart["points"][0]["note"], "2 receipts with no amount I could read")
        self.assertEqual(chart["points"][1]["note"], "")

    def test_two_currencies_are_not_drawn_on_one_scale(self) -> None:
        chart = _run_agent_answer_month_script(
            "buildAgentAnswerMonthlyChart(["
            ' { monthLabel: "Jul 2026", totals: { USD: 19 }, receiptCount: 1 },'
            ' { monthLabel: "Aug 2026", totals: { ILS: 44 }, receiptCount: 1 }'
            "])"
        )

        self.assertIsNone(chart)

    def test_one_month_is_not_a_comparison(self) -> None:
        chart = _run_agent_answer_month_script(
            'buildAgentAnswerMonthlyChart([{ monthLabel: "Aug 2026", totals: { ILS: 44 }, receiptCount: 1 }])'
        )

        self.assertIsNone(chart)

    def test_a_stored_chart_is_read_back_as_data_not_as_given(self) -> None:
        chart = _run_agent_answer_month_script(
            'normalizeAgentChart({ type: "sunburst", title: "Kept", points: ['
            ' { label: "Jul 2026", value: "154.5", display: "154.50 ILS", extra: "ignored" },'
            ' { label: "", value: 1 },'
            ' { label: "Aug 2026", value: 314.1, display: "314.10 ILS" }'
            "] })"
        )

        self.assertEqual(chart["type"], "bar")
        self.assertEqual(len(chart["points"]), 2)
        self.assertEqual(chart["points"][0]["value"], 154.5)
        self.assertNotIn("extra", chart["points"][0])


if __name__ == "__main__":
    unittest.main()
