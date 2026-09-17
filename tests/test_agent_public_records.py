from __future__ import annotations

import json
import unittest
from unittest import mock

from packages.infrastructure.account_types import blocked_tools
from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions
from packages.tools.public_records import PublicRecordsError
from tests.test_agent_news_search import _Database
from tests.test_agent_news_search import _Model
from tests.test_agent_news_search import _round


class AgentPublicRecordsTests(unittest.TestCase):
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
        return {"type": "function_call", "name": "look_up_property", "call_id": "p-1", "arguments": json.dumps(arguments)}

    def _run(self, model: _Model, message: str = "What is planned at Herzl 10 Tel Aviv?"):
        return run_agent_loop(context=self._context(), call_model=model, user_message=message, conversation=[], today="2026-09-17")

    def test_the_tool_is_offered_with_its_arguments(self) -> None:
        tools = {tool["name"]: tool for tool in tool_definitions({})}

        self.assertEqual(set(tools["look_up_property"]["parameters"]["properties"]), {"address", "gush", "helka"})
        self.assertIn("Tabu extract", tools["look_up_property"]["description"])

    def test_the_model_gets_the_parcel_plans_and_tabu_link(self) -> None:
        model = _Model([_round(self._call(address="הרצל 10 תל אביב", gush=None, helka=None)), _round(reply="Gush 7422.")])
        found = {
            "found": True,
            "location": {"from": "address", "matchedAddress": "10, הרצל", "exactBuilding": True},
            "parcel": {"gush": 7422, "helka": 71},
            "plans": [{"number": "507-1", "url": "https://mavat.iplan.gov.il/SV4/1/1/310"}],
            "planCount": 1,
            "tabuExtract": {"url": "https://www.gov.il/he/service/land_registration_extract"},
        }

        with mock.patch("packages.infrastructure.agent_loop.look_up_property", return_value=found) as lookup:
            self._run(model)

        self.assertEqual(lookup.call_args.kwargs["address"], "הרצל 10 תל אביב")
        output = json.loads(model.inputs[1][-1]["output"])
        self.assertTrue(output["ok"])
        self.assertNotIn("found", output)
        self.assertEqual(output["parcel"]["gush"], 7422)
        self.assertEqual(output["plans"][0]["url"], "https://mavat.iplan.gov.il/SV4/1/1/310")

    def test_plan_and_tabu_links_survive_the_reply(self) -> None:
        reply = "Plan 507-1:\nhttps://mavat.iplan.gov.il/SV4/1/1/310\nTabu:\nhttps://www.gov.il/he/service/land_registration_extract"
        model = _Model([_round(self._call(address="הרצל 10 תל אביב", gush=None, helka=None)), _round(reply=reply)])
        found = {
            "found": True,
            "plans": [{"number": "507-1", "url": "https://mavat.iplan.gov.il/SV4/1/1/310"}],
            "tabuExtract": {"url": "https://www.gov.il/he/service/land_registration_extract"},
        }

        with mock.patch("packages.infrastructure.agent_loop.look_up_property", return_value=found):
            result = self._run(model)

        self.assertIn("https://mavat.iplan.gov.il/SV4/1/1/310", result.reply)
        self.assertEqual(
            [(link["label"], link["url"]) for link in result.links],
            [("Plan 507-1", "https://mavat.iplan.gov.il/SV4/1/1/310"), ("Order Tabu extract", "https://www.gov.il/he/service/land_registration_extract")],
        )

    def test_nothing_to_look_up_asks_for_an_address(self) -> None:
        model = _Model([_round(self._call(address=None, gush=None, helka=None)), _round(reply="Which address?")])

        with mock.patch("packages.infrastructure.agent_loop.look_up_property") as lookup:
            self._run(model, "Look up a property")

        lookup.assert_not_called()
        self.assertEqual(json.loads(model.inputs[1][-1]["output"])["error"]["code"], "choice_required")

    def test_a_place_not_found_and_a_service_down_are_said_differently(self) -> None:
        model = _Model([_round(self._call(address="nowhere", gush=None, helka=None)), _round(reply="Not found.")])
        with mock.patch("packages.infrastructure.agent_loop.look_up_property", return_value={"found": False, "reason": "no"}):
            self._run(model)
        self.assertEqual(json.loads(model.inputs[1][-1]["output"])["error"]["code"], "nothing_found")

        model = _Model([_round(self._call(address="x", gush=None, helka=None)), _round(reply="Down.")])
        with mock.patch(
            "packages.infrastructure.agent_loop.look_up_property",
            side_effect=PublicRecordsError("timed_out", "The Planning Administration map took too long to answer."),
        ):
            self._run(model)
        error = json.loads(model.inputs[1][-1]["output"])["error"]
        self.assertEqual(error["code"], "timed_out")
        self.assertTrue(error["canRetry"])

    def test_rules_keep_ownership_to_the_tabu_extract(self) -> None:
        self.assertIn("call look_up_property rather than search_web", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("never guess them", AGENT_LOOP_INSTRUCTIONS)

    def test_property_records_switch_off_on_their_own(self) -> None:
        blocked = blocked_tools({"family": {"public_records": False}}, "family")

        self.assertIn("look_up_property", blocked)
        self.assertNotIn("search_web", blocked)


if __name__ == "__main__":
    unittest.main()
