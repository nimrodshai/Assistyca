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
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server


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
            }, token=token)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["outcome"], "revise_proposal")
        self.assertEqual(payload["changes"], {"timeLocal": "13:50"})
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["tool_name"], "portal_conversational_agent")
        self.assertIn('"activeProposal":{"id":"proposal-1"', kwargs["prompt"])
        self.assertIn("not a new request", kwargs["prompt"])
        self.assertIn("must not ask for confirmation or approval", kwargs["prompt"])
        self.assertIn("application renders the single approval question", kwargs["prompt"])

    def test_initial_scheduled_message_turn_uses_openai_proposal(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "proposal",
            "reply": "Yes — I can do that.",
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


if __name__ == "__main__":
    unittest.main()
