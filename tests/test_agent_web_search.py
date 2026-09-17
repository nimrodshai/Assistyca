from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions


def _round(*items: dict, reply: str = "") -> SimpleNamespace:
    output = [{"type": "reasoning", "summary": []}, *items]
    output_text = ""
    if reply:
        output_text = json.dumps({
            "reply": reply,
            "claimsCompleted": [],
            "rememberFact": None,
            "forgetFact": None,
            "answersOpenQuestion": None,
        })
        output.append({"type": "message", "content": [{"type": "output_text", "text": output_text}]})
    return SimpleNamespace(output_text=output_text, raw_response={"output": output}, input_tokens=10, output_tokens=5)


class _Model:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = rounds
        self.inputs: list[list[dict]] = []

    def __call__(self, items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(items))
        return self.rounds.pop(0)


class _Database:
    def list_platform_connections(self, email: str) -> list[dict]:
        return []


class AgentWebSearchTests(unittest.TestCase):
    def _context(self) -> LoopContext:
        return LoopContext(
            api=lambda *args, **kwargs: ({"ok": True}, 200),
            database=_Database(),
            email="owner@example.com",
            user_id=1,
            timezone_name="Asia/Jerusalem",
            channel="whatsapp",
        )

    def test_search_web_is_available_without_a_connected_account(self) -> None:
        tools = {tool["name"]: tool for tool in tool_definitions({})}

        self.assertIn("search_web", tools)
        self.assertNotIn("UNAVAILABLE RIGHT NOW", tools["search_web"]["description"])
        self.assertIn("public-web search", tools["schedule_task"]["description"])

    def test_list_mode_exposes_only_five_titles_and_dates_to_the_reply(self) -> None:
        call = {
            "type": "function_call",
            "name": "search_web",
            "call_id": "web-1",
            "arguments": json.dumps({
                "query": "activities for children",
                "location": "central Israel",
                "date_range": "2026-09-13 to 2026-09-19",
                "mode": "list",
            }),
        }
        model = _Model([
            _round(call),
            _round(reply="Family science day — 2026-09-18\nAsk me about any result for more information."),
        ])
        search_result = {
            "mode": "list",
            "items": [
                {
                    "title": f"Activity {index}",
                    "date": f"2026-09-{index + 14:02d}",
                    "details": "A long description that must not reach the list reply.",
                    "sourceName": "Events source",
                    "sourceUrl": f"https://events.example/{index}",
                }
                for index in range(6)
            ],
        }

        with mock.patch("packages.infrastructure.agent_loop.search_public_web", return_value=search_result):
            result = run_agent_loop(
                context=self._context(),
                call_model=model,
                user_message="What children's activities are on this week?",
                conversation=[],
                today="2026-09-13",
            )

        tool_output = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(len(tool_output["items"]), 5)
        self.assertEqual(set(tool_output["items"][0]), {"title", "date"})
        self.assertNotIn("details", json.dumps(tool_output["items"]).lower())
        self.assertNotIn("source", json.dumps(tool_output["items"]).lower())
        self.assertEqual(result.tool_calls[0]["name"], "search_web")
        self.assertIn("Ask me about any result", result.reply)

    def test_follow_up_mode_keeps_details_for_one_result(self) -> None:
        call = {
            "type": "function_call",
            "name": "search_web",
            "call_id": "web-2",
            "arguments": json.dumps({
                "query": "Family science day",
                "location": None,
                "date_range": None,
                "mode": "details",
            }),
        }
        model = _Model([_round(call), _round(reply="It runs from 10:00 to 15:00.")])
        search_result = {
            "mode": "details",
            "items": [{
                "title": "Family science day",
                "date": "2026-09-18",
                "details": "Hands-on exhibits from 10:00 to 15:00.",
                "sourceName": "Museum",
                "sourceUrl": "https://museum.example/science-day",
            }],
        }

        with mock.patch("packages.infrastructure.agent_loop.search_public_web", return_value=search_result):
            run_agent_loop(
                context=self._context(),
                call_model=model,
                user_message="Tell me more about the first one",
                conversation=[{"role": "assistant", "text": "Family science day — 2026-09-18"}],
                today="2026-09-13",
            )

        tool_output = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(tool_output["items"][0]["details"], "Hands-on exhibits from 10:00 to 15:00.")
        self.assertNotIn("sourceUrl", tool_output["items"][0])

    def test_a_search_that_runs_out_of_time_says_it_took_too_long(self) -> None:
        call = {
            "type": "function_call",
            "name": "search_web",
            "call_id": "web-3",
            "arguments": json.dumps({"query": "WhatsApp agent news", "location": None, "date_range": None, "mode": "list"}),
        }
        model = _Model([_round(call), _round(reply="The search took too long this time.")])

        with mock.patch(
            "packages.infrastructure.agent_loop.search_public_web",
            side_effect=TimeoutError("The read operation timed out"),
        ):
            run_agent_loop(
                context=self._context(),
                call_model=model,
                user_message="Any WhatsApp agent news?",
                conversation=[],
                today="2026-09-17",
            )

        tool_output = json.loads(model.inputs[1][-1]["output"])
        self.assertFalse(tool_output["ok"])
        self.assertEqual(tool_output["error"]["code"], "timed_out")
        self.assertIn("took too long", tool_output["error"]["whatHappened"])

    def test_agent_rules_make_web_lists_compact_and_schedulable(self) -> None:
        self.assertIn("exactly one numbered line per result containing only its title and date", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("A recurring request to search or watch the web is a standing action", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("can ask about any result for more information", AGENT_LOOP_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
