"""choose_calendars: the person changes which calendars are read, whenever they like."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions

CALENDARS = [
    {"id": "primary", "label": "Nimrod", "primary": True, "color": "#039BE5"},
    {"id": "work@group.calendar.google.com", "label": "Work", "primary": False, "color": "#D50000"},
    {"id": "family@group.calendar.google.com", "label": "Family", "primary": False, "color": "#33B679"},
]
LIST_PATH = "/api/platform-connections/calendars"


class FakeApi:
    def __init__(self, *, selected: list[dict] | None = None, sources: list[dict] | None = None, status: int = 200) -> None:
        source = {"status": "ok", "calendars": list(CALENDARS), "selectedCalendars": list(selected or [CALENDARS[0]])}
        self.sources = [source] if sources is None else sources
        self.status = status
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, payload: dict | None = None, **kwargs) -> tuple[dict, int]:
        self.calls.append((method, path, payload))
        if method == "GET" and path == LIST_PATH:
            return {"ok": True, "sources": self.sources}, self.status
        if method == "POST" and path == LIST_PATH:
            return {"ok": True, "selectedCalendars": payload["calendars"]}, 200
        return {"ok": True}, 200

    def saved(self) -> list[str]:
        posts = [payload for method, path, payload in self.calls if method == "POST" and path == LIST_PATH]
        return [entry["id"] for entry in posts[-1]["calendars"]] if posts else []


def _context(api: FakeApi, channel: str = "whatsapp") -> LoopContext:
    return LoopContext(
        api=api, database=SimpleNamespace(), email="owner@example.com", user_id=1, timezone_name="Asia/Jerusalem",
        tool_context={"calendar": {"platformConnected": True, "connectionStatus": "connected"}}, channel=channel,
    )


def _run(context: LoopContext, **args) -> dict:
    return TOOLS_BY_NAME["choose_calendars"].run(context, {"add": [], "remove": [], **args})


class ChooseCalendarsToolTests(unittest.TestCase):
    def test_the_tool_is_offered_and_strict(self) -> None:
        by_name = {tool["name"]: tool for tool in tool_definitions({"calendar": {"platformConnected": True}})}
        tool = by_name["choose_calendars"]
        self.assertTrue(tool["strict"])
        self.assertEqual(sorted(tool["parameters"]["required"]), ["add", "remove"])
        self.assertIn("add another calendar", tool["description"])

    def test_without_names_the_phone_gets_the_picker_with_todays_choice_ticked(self) -> None:
        api = FakeApi()
        context = _context(api)
        result = _run(context)
        self.assertTrue(result["ok"])
        self.assertEqual(result["readCalendars"], ["Nimrod"])
        self.assertEqual(result["availableCalendars"], ["Nimrod", "Work", "Family"])
        self.assertIn("ticked", result["note"])
        self.assertEqual([c["id"] for c in context.calendar_choice], ["primary", "work@group.calendar.google.com", "family@group.calendar.google.com"])
        self.assertEqual(context.calendar_choice_selected, ["primary"])
        self.assertTrue(context.calendar_choice_requested)
        self.assertEqual(api.saved(), [], "nothing is saved until they tap Done")

    def test_without_names_on_the_portal_the_choice_is_only_reported(self) -> None:
        context = _context(FakeApi(), channel="portal")
        result = _run(context)
        self.assertTrue(result["ok"])
        self.assertIn("Choose calendars", result["note"])
        self.assertIsNone(context.calendar_choice)
        self.assertFalse(context.calendar_choice_requested)

    def test_a_name_adds_a_calendar_there_and_then(self) -> None:
        api = FakeApi()
        result = _run(_context(api), add=["work"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["readCalendars"], ["Nimrod", "Work"])
        self.assertEqual(result["added"], ["Work"])
        self.assertEqual(api.saved(), ["primary", "work@group.calendar.google.com"])

    def test_a_name_removes_a_calendar(self) -> None:
        api = FakeApi(selected=[CALENDARS[0], CALENDARS[1]])
        result = _run(_context(api), remove=["Work"])
        self.assertEqual(result["readCalendars"], ["Nimrod"])
        self.assertEqual(api.saved(), ["primary"])

    def test_the_last_calendar_cannot_be_removed(self) -> None:
        api = FakeApi()
        result = _run(_context(api), remove=["Nimrod"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "choice_required")
        self.assertEqual(api.saved(), [])

    def test_an_unknown_name_names_the_calendars_instead_of_guessing(self) -> None:
        api = FakeApi()
        result = _run(_context(api), add=["Gym"])
        self.assertFalse(result["ok"])
        self.assertIn("no calendar called Gym", result["error"]["whatHappened"])
        self.assertIn("Nimrod, Work, Family", result["error"]["whatHappened"])
        self.assertEqual(result["error"]["readCalendars"], ["Nimrod"])
        self.assertEqual(api.saved(), [])

    def test_an_address_is_matched_by_the_part_before_the_at(self) -> None:
        api = FakeApi(sources=[{"status": "ok", "calendars": [
            {"id": "primary", "label": "nimrod.shai@gmail.com", "primary": True},
            {"id": "team@group.calendar.google.com", "label": "Team (shared)", "primary": False},
        ], "selectedCalendars": [{"id": "primary", "label": "nimrod.shai@gmail.com"}]}])
        result = _run(_context(api), add=["team"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(api.saved(), ["primary", "team@group.calendar.google.com"])

    def test_no_connection_means_no_calendars_to_choose(self) -> None:
        result = _run(_context(FakeApi(sources=[])))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "source_not_connected")

    def test_the_turn_carries_the_request_to_the_channel(self) -> None:
        api = FakeApi()
        call = {"type": "function_call", "name": "choose_calendars", "call_id": "c1", "arguments": json.dumps({"add": [], "remove": []})}
        reply = json.dumps({"reply": "Tick the ones I should read.", "claimsCompleted": [], "rememberFact": None, "forgetFact": None})
        rounds = [
            SimpleNamespace(output_text="", raw_response={"output": [call]}, input_tokens=1, output_tokens=1),
            SimpleNamespace(output_text=reply, raw_response={"output": [{"type": "message", "content": [{"type": "output_text", "text": reply}]}]}, input_tokens=1, output_tokens=1),
        ]
        result = run_agent_loop(context=_context(api), call_model=lambda input_items, tools: rounds.pop(0),
                                user_message="add another calendar", conversation=[], today="2026-09-07")
        self.assertEqual(result.reply, "Tick the ones I should read.")
        self.assertTrue(result.calendar_choice_requested)
        self.assertEqual(result.calendar_choice_selected, ["primary"])
        self.assertEqual(len(result.calendar_choice), 3)


if __name__ == "__main__":
    unittest.main()
