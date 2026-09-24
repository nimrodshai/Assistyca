from __future__ import annotations

import json
import unittest
from unittest import mock

from packages.infrastructure.account_types import blocked_tools
from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions
from tests.test_agent_news_search import _Database
from tests.test_agent_news_search import _Model
from tests.test_agent_news_search import _round


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

    def _call(self, **arguments: object) -> dict:
        return {"type": "function_call", "name": "search_web", "call_id": "web-1", "arguments": json.dumps(arguments)}

    def test_web_search_and_news_search_are_separate_tools(self) -> None:
        tools = {tool["name"]: tool for tool in tool_definitions({})}

        self.assertIn("hotels, concerts", tools["search_web"]["description"])
        self.assertNotIn("mode", tools["search_web"]["parameters"]["properties"])
        self.assertIn("news", tools["search_news"]["description"])
        self.assertIn("mode", tools["search_news"]["parameters"]["properties"])

    def test_the_model_gets_each_result_with_its_facts_and_link(self) -> None:
        model = _Model([
            _round(self._call(query="concerts", location="Tel Aviv", date_range="2026-10-01 to 2026-10-31")),
            _round(reply="Two good ones in October."),
        ])
        found = {
            "results": [{
                "name": "Jazz night",
                "kind": "concert",
                "summary": "Quartet at the port.",
                "where": "Hangar 11, Tel Aviv Port",
                "when": "2026-10-08 21:00",
                "price": "180 ILS",
                "rating": "",
                "sourceName": "Tickets",
                "url": "https://tickets.example/jazz",
            }],
            "note": "",
        }

        with mock.patch("packages.infrastructure.agent_loop.search_web", return_value=found) as search:
            result = run_agent_loop(
                context=self._context(),
                call_model=model,
                user_message="Any concerts in Tel Aviv next month?",
                conversation=[],
                today="2026-09-17",
            )

        self.assertEqual(search.call_args.kwargs["location"], "Tel Aviv")
        tool_output = json.loads(model.inputs[1][-1]["output"])
        self.assertTrue(tool_output["ok"])
        self.assertEqual(tool_output["results"][0]["url"], "https://tickets.example/jazz")
        self.assertEqual(tool_output["results"][0]["price"], "180 ILS")
        self.assertEqual(result.tool_calls[0]["name"], "search_web")

    def test_a_search_that_runs_out_of_time_says_it_took_too_long(self) -> None:
        model = _Model([_round(self._call(query="hotels", location=None, date_range=None)), _round(reply="It took too long.")])

        with mock.patch("packages.infrastructure.agent_loop.search_web", side_effect=TimeoutError("timed out")):
            run_agent_loop(context=self._context(), call_model=model, user_message="Find me a hotel", conversation=[], today="2026-09-17")

        tool_output = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(tool_output["error"]["code"], "timed_out")

    def test_rules_link_each_result_and_keep_news_apart(self) -> None:
        # How a link is written is said once, in the Links section, instead of
        # in every paragraph that returns one; which search to use is in the
        # tools themselves, where the model reads it while choosing.
        self.assertIn("with its url so they can open it", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("it goes in the reply on its own line, exactly as given, once", AGENT_LOOP_INSTRUCTIONS)
        by_name = {tool["name"]: tool for tool in tool_definitions({})}
        self.assertIn("Only for news", by_name["search_news"]["description"])
        self.assertIn("a hotel, a concert or a price is search_web", by_name["search_news"]["description"])

    def test_news_and_web_search_switch_off_separately(self) -> None:
        blocked = blocked_tools({"family": {"news_search": False}}, "family")

        self.assertIn("search_news", blocked)
        self.assertNotIn("search_web", blocked)


if __name__ == "__main__":
    unittest.main()
