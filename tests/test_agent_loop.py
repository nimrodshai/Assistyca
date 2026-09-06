"""The loop, driven by a scripted model and a fake runner.

What these prove is the mechanics: a tool call becomes a result the model
reads, a confirmation pauses the turn and a yes resumes the stored call, the
budget is a wall the model is told about, and the reply carries only links
the turn handed out.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import MAX_TOOL_CALLS_PER_TURN
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions

GOOGLE = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=y"


def _call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


def _model_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    outputs = list(items)
    text = ""
    if reply is not None:
        text = json.dumps(reply)
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": [{"type": "reasoning", "summary": []}, *outputs]}, input_tokens=100, output_tokens=20)


def _reply(text: str, **extra) -> dict:
    return {"reply": text, "claimsCompleted": [], "rememberFact": None, "forgetFact": None, **extra}


class FakeDatabase:
    def __init__(self) -> None:
        self.facts: dict[str, str] = {}
        self.connections: list[dict] = []

    def save_account_fact(self, *, user_id: int, key: str, fact: str) -> None:
        self.facts[key] = fact

    def forget_account_fact(self, *, user_id: int, key: str) -> None:
        self.facts.pop(key, None)

    def list_platform_connections(self, email: str) -> list[dict]:
        return list(self.connections)


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
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, payload: dict | None = None, **kwargs) -> tuple[dict, int]:
        self.calls.append((method, path, payload))
        return self.responses.get(path, ({"ok": True}, 200))


def _context(api: FakeApi | None = None, *, connected: dict | None = None, links: dict | None = None) -> LoopContext:
    tool_context = {key: {"platformConnected": True, "connectionStatus": "connected"} for key in (connected or {})}
    return LoopContext(
        api=api or FakeApi(), database=FakeDatabase(), email="owner@example.com", user_id=1,
        timezone_name="Asia/Jerusalem", tool_context=tool_context, connect_links=links or {}, channel="whatsapp",
    )


class ToolDefinitionTests(unittest.TestCase):
    def test_a_tool_missing_its_source_is_marked_unavailable(self) -> None:
        by_name = {tool["name"]: tool for tool in tool_definitions({})}
        self.assertIn("UNAVAILABLE RIGHT NOW", by_name["read_inbox"]["description"])
        self.assertNotIn("UNAVAILABLE", by_name["exchange_rate"]["description"])
        self.assertTrue(all(tool["strict"] for tool in by_name.values()))

    def test_a_connected_source_lifts_the_mark(self) -> None:
        by_name = {tool["name"]: tool for tool in tool_definitions({"gmail": {"platformConnected": True}})}
        self.assertNotIn("UNAVAILABLE", by_name["read_inbox"]["description"])


class LoopMechanicsTests(unittest.TestCase):
    def test_a_tool_result_reaches_the_model_and_the_reply_comes_back(self) -> None:
        api = FakeApi({"/api/agent/proposals/run": ({"ok": True, "answer": "1 USD is 3.70 ILS", "answerRecords": [{"rate": "3.70"}]}, 200)})
        model = ScriptedModel([
            _model_round(_call("exchange_rate", "c1", base_currency="usd", quote_currency="ils", rate_date=None)),
            _model_round(reply=_reply("A dollar is 3.70 shekels right now.")),
        ])
        result = run_agent_loop(context=_context(api), call_model=model, user_message="dollar in shekels?", conversation=[], today="2026-09-04")

        self.assertEqual(result.reply, "A dollar is 3.70 shekels right now.")
        self.assertEqual([c["name"] for c in result.tool_calls], ["exchange_rate"])
        self.assertTrue(result.tool_calls[0]["ok"])
        # The second round saw the reasoning, the call, and the result.
        second = model.inputs[1]
        self.assertEqual([item.get("type") for item in second[1:]], ["reasoning", "function_call", "function_call_output"])
        output = json.loads(second[-1]["output"])
        self.assertTrue(output["ok"])
        self.assertEqual(output["summary"], "1 USD is 3.70 ILS")
        self.assertEqual(api.calls[0][2]["fields"], {"baseCurrency": "USD", "quoteCurrency": "ILS"})
        self.assertFalse(result.fallback_used)

    def test_a_lookup_missing_its_source_never_reaches_the_runner(self) -> None:
        api = FakeApi()
        model = ScriptedModel([
            _model_round(_call("read_inbox", "c1", time_window="today")),
            _model_round(_call("connect_link", "c2", provider="google")),
            _model_round(reply=_reply(f"I need Gmail connected first, it takes a few seconds:\n{GOOGLE}")),
        ])
        result = run_agent_loop(context=_context(api, links={"google": GOOGLE}), call_model=model, user_message="important emails?", conversation=[], today="2026-09-04")

        self.assertEqual(api.calls, [])
        first_output = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(first_output["error"]["code"], "source_not_connected")
        link_output = json.loads(model.inputs[2][-1]["output"])
        self.assertEqual(link_output["link"], GOOGLE)
        self.assertIn(GOOGLE, result.reply)

    def test_a_link_the_turn_did_not_hand_out_is_dropped(self) -> None:
        model = ScriptedModel([_model_round(reply=_reply("Sign in at https://evil.example/login and I'll carry on."))])
        result = run_agent_loop(context=_context(), call_model=model, user_message="hi", conversation=[], today="2026-09-04")
        self.assertNotIn("evil.example", result.reply)

    def test_the_links_the_reply_carries_come_back_labelled_for_a_button(self) -> None:
        link = "https://accounts.google.com/o/oauth2/v2/auth?state=abc"
        context = _context()
        context.connect_links = {"google": link}
        model = ScriptedModel([
            _model_round(_call("connect_link", "c1", provider="google")),
            _model_round(reply=_reply(f"Tap the button below, it takes a few seconds.\n{link}")),
        ])
        result = run_agent_loop(context=context, call_model=model, user_message="read my mail", conversation=[], today="2026-09-04")
        self.assertIn(link, result.reply)
        self.assertEqual(result.links, [{"url": link, "label": "Connect Google"}])

    def test_a_confirm_tool_pauses_the_turn_and_a_yes_resumes_the_stored_call(self) -> None:
        api = FakeApi({"/api/scheduled-actions": ({"ok": True, "action": {"id": 1}}, 200)})
        model = ScriptedModel([
            _model_round(_call("schedule_message", "c1", time_local="07:30", date_policy="tomorrow", message_text="Call the accountant")),
            _model_round(reply=_reply("I can text you tomorrow at 07:30: Call the accountant. Say yes and it's set.")),
        ])
        result = run_agent_loop(context=_context(api), call_model=model, user_message="text me at 7:30 tomorrow to call the accountant", conversation=[], today="2026-09-04")

        self.assertEqual(api.calls, [])
        self.assertEqual(result.pending_confirmation["tool"], "schedule_message")
        self.assertEqual(result.pending_confirmation["arguments"]["time_local"], "07:30")
        asked = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(asked["error"]["code"], "confirmation_required")
        self.assertIn("07:30", asked["error"]["whatHappened"])

        # The yes: the stored call runs first, and the model reports it.
        model = ScriptedModel([_model_round(reply=_reply("Done, it's set for tomorrow at 07:30.", claimsCompleted=["schedule_message"]))])
        resumed = run_agent_loop(
            context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-04",
            confirmed_call=result.pending_confirmation,
        )
        self.assertEqual(api.calls[0][1], "/api/scheduled-actions")
        self.assertEqual(api.calls[0][2]["messageText"], "Call the accountant")
        self.assertEqual(resumed.completed, ["schedule_message"])
        context_text = model.inputs[0][0]["content"]
        self.assertIn('"confirmedAction"', context_text)
        self.assertIn('"scheduledFor"', context_text)

    def test_a_reminder_asked_for_over_whatsapp_goes_back_to_the_phone_that_asked(self) -> None:
        api = FakeApi({"/api/scheduled-actions": ({"ok": True, "action": {"id": 1}}, 200)})
        context = _context(api)
        context.sender_wa_id = "972501234567"
        model = ScriptedModel([
            _model_round(_call("schedule_message", "c1", time_local="16:00", date_policy="next_occurrence", message_text="take my kid to drum lesson")),
            _model_round(reply=_reply("Say yes and I'll remind you at 16:00.")),
        ])
        asked = run_agent_loop(context=context, call_model=model, user_message="remind me at 16:00", conversation=[], today="2026-09-04")

        model = ScriptedModel([_model_round(reply=_reply("Set for 16:00.", claimsCompleted=["schedule_message"]))])
        run_agent_loop(
            context=context, call_model=model, user_message="yes", conversation=[], today="2026-09-04",
            confirmed_call=asked.pending_confirmation,
        )

        self.assertEqual(api.calls[0][1], "/api/scheduled-actions")
        self.assertEqual(api.calls[0][2]["payload"]["recipientWaId"], "972501234567")

    def test_a_delay_in_minutes_is_scheduled_by_code_and_the_clock_is_in_context(self) -> None:
        api = FakeApi({"/api/scheduled-actions": ({"ok": True, "action": {"id": 1}}, 200)})
        model = ScriptedModel([
            _model_round(_call("schedule_message", "c1", time_local=None, date_policy="today", delay_minutes=10, message_text="Get back to me")),
            _model_round(reply=_reply("I'll text you in 10 minutes: Get back to me. Yes?")),
        ])
        result = run_agent_loop(
            context=_context(api), call_model=model, user_message="get back to me in 10 minutes", conversation=[],
            today="2026-09-05", now="23:24",
        )
        context_text = model.inputs[0][0]["content"]
        self.assertIn('"now":"23:24"', context_text)
        self.assertEqual(api.calls, [])
        self.assertEqual(result.pending_confirmation["arguments"]["delay_minutes"], 10)
        asked = json.loads(model.inputs[1][-1]["output"])
        self.assertIn("in 10 minutes", asked["error"]["whatHappened"])

        model = ScriptedModel([_model_round(reply=_reply("Done, in 10 minutes.", claimsCompleted=["schedule_message"]))])
        run_agent_loop(
            context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-05", now="23:25",
            confirmed_call=result.pending_confirmation,
        )
        self.assertEqual(api.calls[0][1], "/api/scheduled-actions")
        self.assertTrue(api.calls[0][2]["runAt"])
        self.assertIn('"scheduledForLocal"', model.inputs[0][0]["content"])

    def test_the_model_can_read_a_yes_the_parser_could_not(self) -> None:
        open_question = {"kind": "confirmation", "tool": "schedule_message", "question": "Text you at 07:30?"}
        model = ScriptedModel([_model_round(reply=_reply("Great.", answersOpenQuestion="yes"))])
        result = run_agent_loop(context=_context(), call_model=model, user_message="sure thing boss", conversation=[], today="2026-09-05", open_question=open_question)
        self.assertEqual(result.answers_open_question, "yes")
        self.assertIn('"openQuestion"', model.inputs[0][0]["content"])

        model = ScriptedModel([_model_round(reply=_reply("What's on tomorrow: nothing.", answersOpenQuestion=None))])
        result = run_agent_loop(context=_context(), call_model=model, user_message="what's on tomorrow?", conversation=[], today="2026-09-05", open_question=open_question)
        self.assertEqual(result.answers_open_question, "")

        model = ScriptedModel([_model_round(reply=_reply("?", answersOpenQuestion="maybe"))])
        result = run_agent_loop(context=_context(), call_model=model, user_message="hm", conversation=[], today="2026-09-05", open_question=open_question)
        self.assertEqual(result.answers_open_question, "")

    def test_a_refused_schedule_tells_the_model_why(self) -> None:
        # The stored call runs on the yes; the scheduler refuses; the model is
        # told the reason in the person's terms, and the turn keeps the code.
        api = FakeApi({"/api/scheduled-actions": ({"ok": False, "error": "missing_whatsapp_recipient", "message": "Add the number."}, 409)})
        held = {"tool": "schedule_message", "arguments": {"time_local": None, "date_policy": "today", "delay_minutes": 10, "message_text": "Call back"}}
        model = ScriptedModel([_model_round(reply=_reply("I couldn't set it: no WhatsApp number is saved yet."))])
        result = run_agent_loop(context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-05", confirmed_call=held)
        context_text = model.inputs[0][0]["content"]
        self.assertIn('"code":"missing_whatsapp_recipient"', context_text)
        self.assertIn("No WhatsApp number is saved", context_text)
        self.assertEqual(result.completed, [])
        self.assertEqual(result.tool_calls[0]["code"], "missing_whatsapp_recipient")

        api = FakeApi({"/api/scheduled-actions": ({}, 500)})
        model = ScriptedModel([_model_round(reply=_reply("Something failed on our side; try again."))])
        result = run_agent_loop(context=_context(api), call_model=model, user_message="yes", conversation=[], today="2026-09-05", confirmed_call=held)
        self.assertIn('"code":"internal"', model.inputs[0][0]["content"])
        self.assertEqual(result.tool_calls[0]["code"], "internal")

    def test_a_confirm_tool_that_could_not_run_is_never_asked_about(self) -> None:
        # Nothing is connected, so a disconnect has nothing to do: the model is
        # told so and no question is held for a yes that would do nothing.
        model = ScriptedModel([
            _model_round(_call("disconnect", "c1", targets=["google"])),
            _model_round(reply=_reply("Nothing from Google is connected, so there's nothing to log out of.")),
        ])
        result = run_agent_loop(context=_context(), call_model=model, user_message="log me out of google", conversation=[], today="2026-09-04")
        self.assertIsNone(result.pending_confirmation)
        told = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(told["error"]["code"], "nothing_found")

        model = ScriptedModel([
            _model_round(_call("schedule_message", "c1", time_local="soonish", date_policy="tomorrow", message_text="Call")),
            _model_round(reply=_reply("What time exactly?")),
        ])
        result = run_agent_loop(context=_context(), call_model=model, user_message="text me soonish", conversation=[], today="2026-09-04")
        self.assertIsNone(result.pending_confirmation)
        self.assertEqual(json.loads(model.inputs[1][-1]["output"])["error"]["code"], "choice_required")

    def test_the_budget_is_a_wall_the_model_is_told_about(self) -> None:
        api = FakeApi({"/api/agent/proposals/run": ({"ok": True, "answer": "rate", "answerRecords": []}, 200)})
        rounds = [
            _model_round(*[_call("exchange_rate", f"c{i}", base_currency="USD", quote_currency="ILS", rate_date=None) for i in range(MAX_TOOL_CALLS_PER_TURN + 2)]),
            _model_round(reply=_reply("Here is what I have.")),
        ]
        model = ScriptedModel(rounds)
        result = run_agent_loop(context=_context(api), call_model=model, user_message="rates", conversation=[], today="2026-09-04")

        self.assertEqual(len(api.calls), MAX_TOOL_CALLS_PER_TURN)
        outputs = [json.loads(item["output"]) for item in model.inputs[1] if item.get("type") == "function_call_output"]
        self.assertEqual(sum(1 for o in outputs if o.get("ok")), MAX_TOOL_CALLS_PER_TURN)
        self.assertIn("used all the lookups", outputs[-1]["error"]["whatHappened"])

    def test_a_model_that_never_writes_gets_the_assembled_sentence(self) -> None:
        model = ScriptedModel([_model_round(reply=None)] * 10)
        result = run_agent_loop(context=_context(), call_model=model, user_message="hi", conversation=[], today="2026-09-04")
        self.assertTrue(result.fallback_used)
        self.assertIn("Ask me again", result.reply)

    def test_a_tool_that_throws_is_a_result_not_a_dead_turn(self) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("loopback down")

        model = ScriptedModel([
            _model_round(_call("exchange_rate", "c1", base_currency="USD", quote_currency="ILS", rate_date=None)),
            _model_round(reply=_reply("I couldn't get the rate just now; ask me again in a moment.")),
        ])
        result = run_agent_loop(context=_context(boom), call_model=model, user_message="rate?", conversation=[], today="2026-09-04")
        output = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(output["error"]["code"], "internal")
        self.assertEqual(result.tool_calls[0]["code"], "internal")

    def test_facts_are_written_through_the_store(self) -> None:
        context = _context()
        model = ScriptedModel([
            _model_round(_call("remember_fact", "c1", key="render currency", fact="Render bills in dollars.")),
            _model_round(reply=_reply("Noted: Render bills in dollars.", claimsCompleted=["remember_fact"])),
        ])
        result = run_agent_loop(context=context, call_model=model, user_message="render bills me in dollars btw", conversation=[], today="2026-09-04")
        self.assertEqual(context.database.facts, {"render currency": "Render bills in dollars."})
        self.assertEqual(result.completed, ["remember_fact"])


if __name__ == "__main__":
    unittest.main()
