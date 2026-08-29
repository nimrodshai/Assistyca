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
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import resolve_agent_batch_run_month
from packages.infrastructure.portal_auth.server import resolve_local_today
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

    def test_answering_a_question_skips_downloading_attachments(self) -> None:
        self._run_answer({
            "result": "Find receipts from Render for August 2026",
            "vendor": "Render",
            "manualRunMonth": "2026-08",
        })

        self.assertFalse(self.run_call.kwargs["include_attachments"])


class AgentAnswerChatTests(unittest.TestCase):
    """The chat side: a question runs and reports back in the conversation."""

    def setUp(self) -> None:
        self.script = (Path(__file__).resolve().parents[1] / "portal" / "app.js").read_text(encoding="utf-8")

    def test_an_answer_turn_runs_the_lookup_instead_of_making_a_proposal(self) -> None:
        turn_handler = self.script[
            self.script.index("async function applyAgentTurnResponse"):
            self.script.index("function buildAgentReplyMetadata")
        ]

        self.assertIn('if (outcome === "answer_now" && await runAgentAnswerNow(turn))', turn_handler)
        # The proposal branch must stay behind it, or a question becomes a plan.
        self.assertLess(
            turn_handler.index('outcome === "answer_now"'),
            turn_handler.index('if (outcome === "proposal"'),
        )

    def test_a_running_lookup_says_it_is_running_a_task(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerNow"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertIn('agentTurnProgressText = "Running task"', runner)
        self.assertIn('mode: "answer"', runner)
        self.assertIn('pushAgentMessage("assistant", answer, { kind: "result" })', runner)

    def test_the_answer_lands_in_the_chat_rather_than_a_notification(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerNow"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertNotIn("addAgentNotification", runner)

    def test_every_month_the_question_named_gets_its_own_lookup(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerNow"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertIn("for (const month of months)", runner)
        self.assertIn("manualRunMonth: month", runner)
        # Every month's sentence is kept, so an empty month still reports.
        self.assertIn("lines.join", runner)

    def test_a_month_that_could_not_be_read_is_named(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerNow"):
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
    harness = "\n".join([
        'function getWorkspaceTimeZone() { return "UTC"; }',
        "function getAgentWorkspaceDateParts() { return new Date(Date.UTC(2026, 7, 15)); }",
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

    def test_a_long_list_of_months_stops_and_says_so(self) -> None:
        months = ",".join(f"2026-{month:02d}" for month in range(1, 10))
        result = _run_agent_answer_month_script(
            f'getAgentAnswerRunMonths({{ manualRunMonth: "{months}" }})'
        )

        self.assertEqual(len(result["months"]), 6)
        self.assertTrue(result["trimmed"])

    def test_a_month_is_labelled_the_way_the_answer_reads(self) -> None:
        self.assertEqual(
            _run_agent_answer_month_script('formatAgentAnswerMonthLabel("2026-07")'),
            "Jul 2026",
        )


if __name__ == "__main__":
    unittest.main()
