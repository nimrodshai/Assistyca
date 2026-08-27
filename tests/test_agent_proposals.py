from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.agent_proposals import build_agent_proposal_revision_prompt
from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.agent_proposals import normalize_agent_proposal_for_revision
from packages.infrastructure.agent_proposals import normalize_agent_proposal_for_turn
from packages.infrastructure.agent_proposals import normalize_agent_proposal_revision_response
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
from packages.infrastructure.agent_proposals import normalize_agent_tool_context
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.openai_api import OpenAIRequestError


class AgentProposalRevisionTests(unittest.TestCase):
    def test_revision_prompt_includes_current_proposal_and_conversation(self) -> None:
        proposal = normalize_agent_proposal_for_revision({
            "id": "proposal-1",
            "type": "scheduled-message",
            "revision": 1,
            "requestText": "Send me a WhatsApp message when it's 12:40",
            "details": {
                "channel": "whatsapp",
                "timeLocal": "12:40",
                "timezone": "Asia/Jerusalem",
                "messageText": "It's 12:40.",
                "messageSource": "generated",
            },
        })

        prompt = build_agent_proposal_revision_prompt(
            proposal=proposal,
            user_message="Let's change it to 13:30",
            conversation=[
                {"role": "assistant", "text": "What would you like to change?"},
                {"role": "user", "text": "Let's change it to 13:30"},
            ],
        )

        self.assertIn('"timeLocal":"12:40"', prompt)
        self.assertIn('"latestUserMessage":"Let\'s change it to 13:30"', prompt)
        self.assertIn('"text":"What would you like to change?"', prompt)
        self.assertIn("Do not calculate runAt", prompt)

    def test_revision_response_accepts_only_a_structured_delta(self) -> None:
        revision = normalize_agent_proposal_revision_response({
            "outcome": "revised",
            "changes": {"timeLocal": "13:30"},
            "reply": "",
        })

        self.assertEqual(revision, {
            "outcome": "revised",
            "changes": {"timeLocal": "13:30"},
            "reply": "",
        })

    def test_revision_response_rejects_invalid_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid local time"):
            normalize_agent_proposal_revision_response({
                "outcome": "revised",
                "changes": {"timeLocal": "25:90"},
            })

    def test_conversational_turn_treats_natural_followup_as_revision(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "revise_proposal",
            "reply": "Sure — I changed the time to 13:50.",
            "proposalType": "",
            "changes": {"timeLocal": "13:50"},
        }, has_active_proposal=True)

        self.assertEqual(turn["outcome"], "revise_proposal")
        self.assertEqual(turn["changes"], {"timeLocal": "13:50"})
        self.assertIn("changed the time", turn["reply"])

    def test_conversational_turn_preserves_manual_run_month_field(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "revise_proposal",
            "reply": "I’ll use August 2026 for the manual run.",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Pull all receipts for August 2026",
                    "manualRunMonth": "2026-08",
                },
            },
        }, has_active_proposal=True, active_proposal_type="custom")

        self.assertEqual(turn["outcome"], "revise_proposal")
        self.assertEqual(turn["changes"]["fields"]["manualRunMonth"], "2026-08")
        self.assertEqual(turn["changes"]["fields"]["result"], "Pull all receipts for August 2026")

    def test_conversational_turn_prompt_preserves_pending_proposal_context(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="No, let's change it to 13:50",
            conversation=[
                {"role": "assistant", "text": "Would you like me to schedule it?"},
                {"role": "user", "text": "No, let's change it to 13:50"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "scheduled-message",
                "revision": 1,
                "details": {"timeLocal": "12:40"},
            },
        )

        self.assertIn('"activeProposal":{"id":"proposal-1"', prompt)
        self.assertIn('"latestUserMessage":"No, let\'s change it to 13:50"', prompt)
        self.assertIn("not a new request", prompt)

    def test_conversational_turn_prompt_uses_field_based_intake(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="HaSharon and central Israel",
            conversation=[
                {"role": "user", "text": "Please check the web every 5 minutes for fun events to do with kids in August and email me"},
                {"role": "assistant", "text": "What location should I search in?"},
                {"role": "user", "text": "HaSharon and central Israel"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "web-monitor",
                "revision": 1,
                "requestText": "Please check the web every 5 minutes for fun events to do with kids in August and email me",
                "fields": {
                    "watchQuery": "fun events to do with kids",
                    "timeWindow": "August",
                    "frequency": "every 5 minutes",
                    "deliveryChannel": "Email",
                },
            },
        )

        self.assertIn('"proposalFieldSchemas"', prompt)
        self.assertIn('"watchQuery":"fun events to do with kids"', prompt)
        self.assertIn("changes.fields", prompt)
        self.assertIn("Do not restart questions", prompt)
        self.assertIn("Separate hidden structure from visible conversation", prompt)
        self.assertIn("should not sound like a template", prompt)
        self.assertIn("Do not echo the user's full request", prompt)

    def test_agent_tool_context_is_safe_and_guides_connected_whatsapp_use(self) -> None:
        context = normalize_agent_tool_context({
            "whatsapp": {
                "ready": True,
                "platformConnected": True,
                "connectionStatus": "CONNECTED",
                "missingFields": [{"key": "access_token", "label": "Access token", "value": "secret"}],
                "accessToken": "secret",
            },
        })

        self.assertEqual(context, {
            "whatsapp": {
                "ready": True,
                "platformConnected": True,
                "connectionStatus": "connected",
                "missingFields": ["Access token"],
            },
        })
        prompt = build_agent_turn_prompt(
            user_message="Watch new WhatsApp messages",
            conversation=[],
            timezone_name="UTC",
            tool_context=context,
        )
        self.assertIn('"toolContext":{"whatsapp":{"ready":true', prompt)
        self.assertIn("do not ask which WhatsApp number or account", prompt)
        self.assertNotIn("secret", prompt)

    def test_agent_tool_context_includes_calendar_health_without_credentials(self) -> None:
        context = normalize_agent_tool_context({
            "calendar": {
                "platformConnected": True,
                "connectionStatus": "needs_attention",
                "validationStatus": "failed",
                "accessToken": "must-not-be-forwarded",
            },
        })

        self.assertEqual(context["calendar"], {
            "platformConnected": True,
            "connectionStatus": "needs_attention",
            "validationStatus": "failed",
        })
        self.assertNotIn("must-not-be-forwarded", json.dumps(context))

    def test_agent_tool_context_includes_gmail_and_drive_health_without_credentials(self) -> None:
        context = normalize_agent_tool_context({
            "gmail": {
                "platformConnected": True,
                "connectionStatus": "connected",
                "validationStatus": "verified",
                "refreshToken": "must-not-be-forwarded",
            },
            "drive": {
                "platformConnected": False,
                "connectionStatus": "needs_verification",
                "validationStatus": "pending",
                "accessToken": "also-secret",
            },
        })

        self.assertEqual(context["gmail"], {
            "platformConnected": True,
            "connectionStatus": "connected",
            "validationStatus": "verified",
        })
        self.assertEqual(context["drive"], {
            "platformConnected": False,
            "connectionStatus": "needs_verification",
            "validationStatus": "pending",
        })
        self.assertNotIn("must-not-be-forwarded", json.dumps(context))
        self.assertNotIn("also-secret", json.dumps(context))

    def test_conversational_turn_prompt_discourages_repeated_plan_summaries(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Please check the web every 5 minutes for fun events to do with kids in August. When you have the results send me an email with the top most relevant results",
            conversation=[
                {"role": "user", "text": "Please check the web every 5 minutes for fun events to do with kids in August. When you have the results send me an email with the top most relevant results"},
                {"role": "assistant", "text": "Got it — I can watch the web every 5 minutes for fun kid-friendly events in August around HaSharon and central Israel, then email you the top relevant results. Should I set it up?"},
                {"role": "user", "text": "Please check the web every 5 minutes for fun events to do with kids in August. When you have the results send me an email with the top most relevant results"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "web-monitor",
                "revision": 1,
                "requestText": "Please check the web every 5 minutes for fun events to do with kids in August and email me",
                "fields": {
                    "watchQuery": "fun events to do with kids",
                    "location": "HaSharon and central Israel",
                    "timeWindow": "August",
                    "frequency": "every 5 minutes",
                    "deliveryChannel": "Email",
                },
            },
        )

        self.assertIn("avoid repeating a recent assistant reply", prompt)
        self.assertIn("overlaps an active pending activeProposal", prompt)
        self.assertIn("do not tell the user you already have that request", prompt)
        self.assertIn("Treat it as continuing the pending setup", prompt)
        self.assertIn("instead of restating the plan", prompt)
        self.assertIn("may omit them when the reply already gives the user a clear", prompt)
        self.assertNotIn("may attach Set it up and Change something buttons", prompt)

    def test_conversational_turn_prompt_infers_monthly_batch_cadence(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="on a schedule",
            conversation=[
                {"role": "user", "text": "Pull all my receipts from August."},
                {"role": "assistant", "text": "Which mailbox or source should I search for the August receipts?"},
                {"role": "user", "text": "nimrod.shai@gmail.com"},
                {"role": "assistant", "text": "Should this be a one-time pull, or do you want it to run on a schedule?"},
                {"role": "user", "text": "on a schedule"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "custom",
                "revision": 1,
                "requestText": "Pull all my receipts from August.",
                "fields": {
                    "result": "Pull all receipts from August from nimrod.shai@gmail.com",
                },
            },
        )

        self.assertIn("month-based batch jobs", prompt)
        self.assertIn("infer frequency/schedule as monthly", prompt)
        self.assertIn("beginning of each month for the previous month", prompt)
        self.assertIn("manualRunMonth", prompt)
        self.assertIn("previous month rather than a fixed named month", prompt)
        self.assertIn("Do not ask a generic daily/weekly/monthly frequency question", prompt)
        self.assertIn("Do not phrase recurring work as repeatedly pulling the same named month", prompt)
        self.assertIn("ask the user to connect Google with Gmail or Drive read access before approval", prompt)
        self.assertIn("For web-monitor, use the built-in public web monitoring action", prompt)

    def test_conversational_turn_response_removes_duplicate_preface(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "question",
            "reply": "I have that request already. Should this be a one-time pull for August?",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Pull all receipts from August",
                },
            },
        }, has_active_proposal=True, active_proposal_type="custom")

        self.assertEqual(turn["reply"], "Should this be a one-time pull for August?")
        self.assertEqual(turn["outcome"], "question")

    def test_conversational_turn_response_removes_task_noted_preface(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "question",
            "reply": "I already have the receipt-pulling task noted. Is monthly at the beginning of each month for the previous month okay?",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Pull all receipts from August",
                },
            },
        }, has_active_proposal=True, active_proposal_type="custom")

        self.assertEqual(
            turn["reply"],
            "Is monthly at the beginning of each month for the previous month okay?",
        )
        self.assertEqual(turn["outcome"], "question")

    def test_question_turn_can_preserve_known_draft_fields(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "question",
            "reply": "Sure — what location should I search in?",
            "proposalType": "web-monitor",
            "changes": {
                "fields": {
                    "watchQuery": "fun events to do with kids",
                    "timeWindow": "August",
                    "frequency": "every 5 minutes",
                    "deliveryChannel": "Email",
                    "ignoredField": "not allowed",
                },
            },
        }, has_active_proposal=False)

        self.assertEqual(turn["outcome"], "question")
        self.assertEqual(turn["proposalType"], "web-monitor")
        self.assertEqual(turn["changes"]["fields"], {
            "watchQuery": "fun events to do with kids",
            "timeWindow": "August",
            "frequency": "every 5 minutes",
            "deliveryChannel": "Email",
        })

    def test_conversational_turn_requires_llm_reply(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing reply"):
            normalize_agent_turn_response({
                "outcome": "proposal",
                "reply": "",
                "proposalType": "web-monitor",
                "changes": {
                    "fields": {
                        "watchQuery": "kid-friendly events",
                        "location": "HaSharon and central Israel",
                        "frequency": "every 5 minutes",
                        "deliveryChannel": "Email",
                    },
                },
            }, has_active_proposal=False)

    def test_active_non_scheduled_proposal_keeps_fields_for_turns(self) -> None:
        proposal = normalize_agent_proposal_for_turn({
            "id": "proposal-1",
            "type": "web-monitor",
            "revision": 1,
            "requestText": "Watch for events",
            "fields": {
                "watchQuery": "kid-friendly events",
                "frequency": "daily",
                "deliveryChannel": "Email",
            },
        })

        self.assertEqual(proposal["fields"], {
            "watchQuery": "kid-friendly events",
            "frequency": "daily",
            "deliveryChannel": "Email",
        })

    def test_calendar_summary_uses_calendar_not_mailbox(self) -> None:
        proposal = normalize_agent_proposal_for_turn({
            "id": "proposal-calendar",
            "type": "calendar-summary",
            "revision": 1,
            "requestText": "Summarize my meetings next week and email me the brief",
            "fields": {
                "calendar": "Connected calendar",
                "timeWindow": "next week",
                "deliveryChannel": "Email",
            },
        })

        self.assertEqual(proposal["type"], "calendar-summary")
        self.assertEqual(proposal["fields"]["calendar"], "Connected calendar")
        prompt = build_agent_turn_prompt(
            user_message="Yes, set up the meeting summary",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            active_proposal=proposal,
        )
        self.assertIn("calendar-summary", prompt)
        self.assertIn("Never ask for Gmail or mailbox access", prompt)


class AgentProposalRevisionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _session_token_for(self, email: str) -> str:
        self.server.database.register_user(email)
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        return str((result or {}).get("token") or "")

    def _post_revision(self, payload: dict[str, object], *, token: str = "") -> tuple[int, dict[str, object]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/revise",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _post_agent_turn(self, payload: dict[str, object], *, token: str = "") -> tuple[int, dict[str, object]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/turn",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_revision_requires_authentication(self) -> None:
        status, payload = self._post_revision({})

        self.assertEqual(status, 401)
        self.assertFalse(payload["ok"])

    def test_revision_uses_agent_context_and_returns_validated_patch(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "revised",
            "changes": {"timeLocal": "13:30"},
            "reply": "",
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(model_response)),
        ) as call_openai:
            status, payload = self._post_revision({
                "proposal": {
                    "id": "proposal-1",
                    "type": "scheduled-message",
                    "revision": 1,
                    "requestText": "Send me a WhatsApp message when it's 12:40",
                    "details": {
                        "channel": "whatsapp",
                        "timeLocal": "12:40",
                        "timezone": "Asia/Jerusalem",
                        "messageText": "It's 12:40.",
                        "messageSource": "generated",
                    },
                },
                "userMessage": "Let's change it to 13:30",
                "conversation": [
                    {"role": "assistant", "text": "What would you like to change?"},
                    {"role": "user", "text": "Let's change it to 13:30"},
                ],
            }, token=token)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["outcome"], "revised")
        self.assertEqual(payload["changes"], {"timeLocal": "13:30"})
        call_openai.assert_called_once()
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["billing_email"], "owner@example.com")
        self.assertIn('"timeLocal":"12:40"', kwargs["prompt"])
        self.assertIn('"latestUserMessage":"Let\'s change it to 13:30"', kwargs["prompt"])
        self.assertFalse(kwargs["config"].include_prompt_in_metadata)

    def test_normal_conversation_turn_uses_openai_and_pending_proposal(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "revise_proposal",
            "reply": "Sure — I changed the time to 13:50.",
            "proposalType": "",
            "changes": {"timeLocal": "13:50"},
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(model_response)),
        ) as call_openai:
            status, payload = self._post_agent_turn({
                "activeProposal": {
                    "id": "proposal-1",
                    "type": "scheduled-message",
                    "revision": 1,
                    "requestText": "Send me a WhatsApp message when it's 12:40",
                    "details": {
                        "channel": "whatsapp",
                        "timeLocal": "12:40",
                        "datePolicy": "next_occurrence",
                        "timezone": "Asia/Jerusalem",
                        "messageText": "It's 12:40.",
                        "messageSource": "generated",
                    },
                },
                "userMessage": "No, let's change it to 13:50",
                "timezone": "Asia/Jerusalem",
                "conversation": [
                    {"role": "assistant", "text": "Would you like me to schedule it?"},
                    {"role": "user", "text": "No, let's change it to 13:50"},
                ],
                "toolContext": {
                    "whatsapp": {
                        "ready": True,
                        "platformConnected": True,
                        "connectionStatus": "connected",
                        "missingFields": [],
                    },
                },
            }, token=token)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["outcome"], "revise_proposal")
        self.assertEqual(payload["changes"], {"timeLocal": "13:50"})
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["tool_name"], "portal_conversational_agent")
        self.assertIn('"activeProposal":{"id":"proposal-1"', kwargs["prompt"])
        self.assertIn("not a new request", kwargs["prompt"])
        self.assertIn("reply field is the only assistant text", kwargs["prompt"])
        self.assertIn("reply is required for every outcome", kwargs["prompt"])
        self.assertIn("include a natural approval question", kwargs["prompt"])
        self.assertIn("Do not echo the user's full request", kwargs["prompt"])
        self.assertIn("default deliveryChannel to portal (the Notifications center)", kwargs["prompt"])
        self.assertIn("Setup questions and approvals still stay in the Assistyca chat", kwargs["prompt"])
        self.assertIn('"toolContext":{"whatsapp":{"ready":true', kwargs["prompt"])

    def test_initial_scheduled_message_turn_uses_openai_proposal(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "proposal",
            "reply": "Yes — I can do that. Want me to set it up?",
            "proposalType": "scheduled-message",
            "changes": {
                "channel": "whatsapp",
                "timeLocal": "12:40",
                "datePolicy": "next_occurrence",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(model_response)),
        ) as call_openai:
            status, payload = self._post_agent_turn({
                "userMessage": "Can you send me a WhatsApp message when it's 12:40?",
                "timezone": "Asia/Jerusalem",
                "conversation": [
                    {"role": "user", "text": "Can you send me a WhatsApp message when it's 12:40?"},
                ],
            }, token=token)

        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "proposal")
        self.assertEqual(payload["proposalType"], "scheduled-message")
        self.assertEqual(payload["changes"]["timeLocal"], "12:40")
        self.assertEqual(call_openai.call_args.kwargs["tool_name"], "portal_conversational_agent")

    def test_agent_turn_reports_insufficient_openai_funds(self) -> None:
        token = self._session_token_for("owner@example.com")
        provider_error = {
            "error": {
                "message": "You exceeded your current quota, please check your plan and billing details.",
                "type": "insufficient_quota",
                "code": "insufficient_quota",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=OpenAIRequestError(
                "You exceeded your current quota.",
                details=json.dumps(provider_error),
                status_code=429,
            ),
        ):
            status, payload = self._post_agent_turn({
                "userMessage": "Hello",
                "conversation": [],
            }, token=token)

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "agent_billing_required")
        self.assertIn("legacy quota", payload["message"])
        self.assertNotIn("insufficient funds", payload["message"])
        self.assertEqual(payload["upstreamStatus"], 429)
        self.assertEqual(payload["providerCode"], "insufficient_quota")

    def test_agent_turn_does_not_call_quota_type_a_funding_error_when_rate_code_is_present(self) -> None:
        token = self._session_token_for("owner@example.com")
        provider_error = {
            "error": {
                "message": "Rate limit reached for requests.",
                "type": "insufficient_quota",
                "code": "rate_limit_exceeded",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=OpenAIRequestError(
                "Rate limit reached for requests.",
                details=json.dumps(provider_error),
                status_code=429,
            ),
        ):
            status, payload = self._post_agent_turn({
                "userMessage": "Hello",
                "conversation": [],
            }, token=token)

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "agent_rate_limited")
        self.assertNotIn("insufficient funds", payload["message"])
        self.assertEqual(payload["providerCode"], "rate_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
