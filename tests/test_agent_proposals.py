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
from packages.infrastructure.agent_proposals import normalize_agent_proposal_for_revision
from packages.infrastructure.agent_proposals import normalize_agent_proposal_revision_response
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


if __name__ == "__main__":
    unittest.main()
