"""Signing out and deleting the account from the chat.

Both are held for a yes like any other action that changes something, and
the question names what the yes means: a sign-out is one phone, a deletion
is everything. What these prove is that the loop asks before it acts, that
the yes runs exactly the stored call, and that neither can run where it
makes no sense - sign_out on the portal, or on a phone nobody linked.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions

PHONE = "972501234567"


def _call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


def _model_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    outputs = list(items)
    text = ""
    if reply is not None:
        text = json.dumps({"reply": "", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, **reply})
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": [{"type": "reasoning", "summary": []}, *outputs]}, input_tokens=1, output_tokens=1)


class FakeDatabase:
    def __init__(self, numbers: list[str] | None = None) -> None:
        self.numbers = list(numbers or [])

    def list_platform_connections(self, email: str) -> list[dict]:
        return []

    def list_user_whatsapp_numbers(self, *, user_id: int) -> list[dict]:
        return [{"waId": number, "label": ""} for number in self.numbers]


class ScriptedModel:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = list(rounds)
        self.inputs: list[list[dict]] = []

    def __call__(self, input_items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(input_items))
        return self.rounds.pop(0)


class FakeApi:
    def __init__(self, responses: dict[str, tuple[dict, int]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, path: str, payload: dict | None = None, **kwargs) -> tuple[dict, int]:
        self.calls.append((method, path))
        return self.responses.get(path, ({"ok": True}, 200))


def _context(api: FakeApi | None = None, *, channel: str = "whatsapp", sender: str = PHONE, linked: list[str] | None = None) -> LoopContext:
    return LoopContext(
        api=api or FakeApi(), database=FakeDatabase(linked if linked is not None else [PHONE]), email="owner@example.com",
        user_id=1, timezone_name="Asia/Jerusalem", channel=channel, sender_wa_id=sender,
    )


def _told(model: ScriptedModel) -> dict:
    return json.loads(model.inputs[1][-1]["output"])


class SignOutTests(unittest.TestCase):
    def test_both_tools_are_offered_and_need_a_yes(self) -> None:
        by_name = {tool["name"]: tool for tool in tool_definitions({})}
        self.assertIn("Needs the person's yes", by_name["sign_out"]["description"])
        self.assertIn("Needs the person's yes", by_name["delete_account"]["description"])
        self.assertIn("permanently", by_name["delete_account"]["description"])

    def test_a_sign_out_is_held_for_a_yes_and_the_yes_unlinks_this_phone_only(self) -> None:
        api = FakeApi()
        model = ScriptedModel([
            _model_round(_call("sign_out", "c1")),
            _model_round(reply={"reply": "I can sign this phone out; your account stays. Yes?"}),
        ])
        result = run_agent_loop(context=_context(api), call_model=model, user_message="log me out", conversation=[], today="2026-09-05")

        self.assertEqual(api.calls, [])
        self.assertEqual(result.pending_confirmation["tool"], "sign_out")
        asked = _told(model)
        self.assertEqual(asked["error"]["code"], "confirmation_required")
        self.assertIn("everything saved in it stay", asked["error"]["whatHappened"])

        model = ScriptedModel([_model_round(reply={"reply": "Signed out. Text me when you want back in.", "claimsCompleted": ["sign_out"]})])
        resumed = run_agent_loop(
            context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-05",
            confirmed_call=result.pending_confirmation,
        )
        self.assertEqual(api.calls, [("DELETE", f"/api/whatsapp/my-numbers/{PHONE}")])
        self.assertEqual(resumed.completed, ["sign_out"])
        self.assertIn("link code", model.inputs[0][0]["content"])

    def test_a_sign_out_on_the_portal_is_refused_before_any_question(self) -> None:
        model = ScriptedModel([
            _model_round(_call("sign_out", "c1")),
            _model_round(reply={"reply": "Use the Sign out button under Settings."}),
        ])
        result = run_agent_loop(context=_context(channel="portal", sender=""), call_model=model, user_message="sign me out", conversation=[], today="2026-09-05")
        self.assertIsNone(result.pending_confirmation)
        self.assertEqual(_told(model)["error"]["code"], "not_supported")
        self.assertIn("Sign out button", _told(model)["error"]["whatHappened"])

    def test_a_phone_nobody_linked_cannot_be_signed_out_from_the_chat(self) -> None:
        # The account's own line comes from the environment, not from a link
        # the person made, so there is nothing the chat could take back.
        model = ScriptedModel([
            _model_round(_call("sign_out", "c1")),
            _model_round(reply={"reply": "That's managed from Settings."}),
        ])
        result = run_agent_loop(context=_context(linked=[]), call_model=model, user_message="sign me out", conversation=[], today="2026-09-05")
        self.assertIsNone(result.pending_confirmation)
        self.assertEqual(_told(model)["error"]["code"], "not_supported")


class DeleteAccountTests(unittest.TestCase):
    def test_a_deletion_is_held_for_a_yes_that_names_everything_that_goes(self) -> None:
        api = FakeApi()
        model = ScriptedModel([
            _model_round(_call("delete_account", "c1")),
            _model_round(reply={"reply": "This erases everything for good. Do you understand and want to go ahead?"}),
        ])
        result = run_agent_loop(context=_context(api), call_model=model, user_message="delete my data", conversation=[], today="2026-09-05")

        self.assertEqual(api.calls, [])
        self.assertEqual(result.pending_confirmation["tool"], "delete_account")
        asked = _told(model)
        self.assertEqual(asked["error"]["code"], "confirmation_required")
        for words in ("owner@example.com", "permanently", "sign-ins are revoked", "chat's history", "none of it can be brought back"):
            self.assertIn(words, asked["error"]["whatHappened"])

    def test_the_yes_deletes_the_account_and_the_model_reports_it(self) -> None:
        api = FakeApi()
        model = ScriptedModel([_model_round(reply={"reply": "Done. Everything is gone.", "claimsCompleted": ["delete_account"]})])
        resumed = run_agent_loop(
            context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-05",
            confirmed_call={"tool": "delete_account", "arguments": {}},
        )
        self.assertEqual(api.calls, [("DELETE", "/api/account")])
        self.assertEqual(resumed.completed, ["delete_account"])
        self.assertIn('"deleted":true', model.inputs[0][0]["content"])

    def test_the_only_admin_is_told_why_it_cannot_be_deleted(self) -> None:
        api = FakeApi({"/api/account": ({"ok": False, "error": "last_admin"}, 409)})
        model = ScriptedModel([_model_round(reply={"reply": "I can't: you're the only admin."})])
        resumed = run_agent_loop(
            context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-05",
            confirmed_call={"tool": "delete_account", "arguments": {}},
        )
        self.assertEqual(resumed.completed, [])
        self.assertIn("only admin account", model.inputs[0][0]["content"])

    def test_the_prompt_tells_the_model_to_make_sure_the_person_understands(self) -> None:
        from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS

        self.assertIn("understand what they are agreeing to", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("nothing can be brought back", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("A hesitant or unclear answer is not a yes", AGENT_LOOP_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
