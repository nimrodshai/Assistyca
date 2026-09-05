"""Lists: kept in the portal store, edited from chat or the lists page, shared by link.

What these prove: a list is one thing whichever side writes it; the agent
resolves a list from the person's words and hands back the page link; a
reminder about a list reads the list when it fires, not when it was set;
the share link shows only the words on the list, and dies when sharing is
turned off; a link from WhatsApp signs the phone in exactly once.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions
from packages.infrastructure.portal_auth.server import LISTS_HANDOFF_PREFIX
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import PortalSession
from packages.infrastructure.portal_auth.server import SESSION_COOKIE_NAME
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import create_session_token
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler
from packages.infrastructure.scheduled_actions import describe_list_for_message
from packages.infrastructure.list_due_nudges import ListDueNudgeConfig
from packages.infrastructure.list_due_nudges import ListDueNudger
from packages.infrastructure.list_due_nudges import describe_due
from datetime import date

LINK = "https://assistyca.test/lists#/list/{id}"


class ListStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)

    def test_a_list_keeps_its_items_in_order_and_never_twice(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Shopping", items=["Milk", "Eggs", "milk"])
        self.assertEqual([item["text"] for item in record["items"]], ["Milk", "Eggs"])

        outcome = self.database.add_account_list_items(user_id=self.user_id, list_id=record["id"], texts=["Bread", "EGGS"])
        self.assertEqual([item["text"] for item in outcome["added"]], ["Bread"])
        self.assertEqual(outcome["skipped"], ["EGGS"])
        self.assertEqual([item["text"] for item in outcome["list"]["items"]], ["Milk", "Eggs", "Bread"])

    def test_a_name_in_the_persons_words_finds_the_list(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Shopping list")
        self.database.create_account_list(user_id=self.user_id, name="Rome packing", kind="todo")

        self.assertEqual([r["name"] for r in self.database.find_account_lists(user_id=self.user_id, name="shopping")], ["Shopping list"])
        self.assertEqual([r["name"] for r in self.database.find_account_lists(user_id=self.user_id, name="the packing list for rome")], ["Rome packing"])
        self.assertEqual(self.database.find_account_lists(user_id=self.user_id, name="birthday"), [])

    def test_ticking_off_and_clearing_are_for_todo_lists(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Today", kind="todo", items=["Call bank", "Send invoice"])
        first = record["items"][0]["id"]
        self.assertEqual(self.database.set_account_list_items_done(user_id=self.user_id, list_id=record["id"], item_ids=[first], done=True), 1)
        summary = self.database.list_account_lists(user_id=self.user_id)[0]
        self.assertEqual((summary["itemCount"], summary["openCount"]), (2, 1))
        self.assertEqual(self.database.clear_done_account_list_items(user_id=self.user_id, list_id=record["id"]), 1)
        self.assertEqual([i["text"] for i in self.database.get_account_list(user_id=self.user_id, list_id=record["id"])["items"]], ["Send invoice"])

    def test_sharing_mints_a_link_and_turning_it_off_kills_it(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Ideas", items=["Podcast"])
        shared = self.database.set_account_list_share(user_id=self.user_id, list_id=record["id"], enabled=True)
        token = shared["shareToken"]
        self.assertTrue(token)
        self.assertEqual(self.database.get_account_list_by_share_token(token)["name"], "Ideas")

        self.database.set_account_list_share(user_id=self.user_id, list_id=record["id"], enabled=False)
        self.assertIsNone(self.database.get_account_list_by_share_token(token))

        # An archived list is off the air even with a live token.
        again = self.database.set_account_list_share(user_id=self.user_id, list_id=record["id"], enabled=True)
        self.assertNotEqual(again["shareToken"], token)
        self.database.update_account_list(user_id=self.user_id, list_id=record["id"], archived=True)
        self.assertIsNone(self.database.get_account_list_by_share_token(again["shareToken"]))

    def test_a_todo_item_keeps_a_due_date_and_a_general_list_does_not(self) -> None:
        todo = self.database.create_account_list(user_id=self.user_id, name="Admin", kind="todo")
        added = self.database.add_account_list_items(user_id=self.user_id, list_id=todo["id"], texts=["VAT return"], due_on="2026-09-15")
        self.assertEqual(added["added"][0]["dueOn"], "2026-09-15")
        item_id = added["added"][0]["id"]
        self.assertEqual(self.database.update_account_list_item(user_id=self.user_id, list_id=todo["id"], item_id=item_id, due_on="")["dueOn"], "")
        with self.assertRaises(ValueError):
            self.database.update_account_list_item(user_id=self.user_id, list_id=todo["id"], item_id=item_id, due_on="next friday")

        general = self.database.create_account_list(user_id=self.user_id, name="Shopping")
        added = self.database.add_account_list_items(user_id=self.user_id, list_id=general["id"], texts=["Milk"], due_on="2026-09-15")
        self.assertEqual(added["added"][0]["dueOn"], "")
        self.assertEqual(self.database.list_open_due_items(user_id=self.user_id), [])

    def test_another_account_cannot_see_or_touch_the_list(self) -> None:
        self.database.register_user("other@example.com")
        other = int((self.database.get_user("other@example.com") or {}).get("id") or 0)
        record = self.database.create_account_list(user_id=self.user_id, name="Private", items=["x"])
        self.assertIsNone(self.database.get_account_list(user_id=other, list_id=record["id"]))
        self.assertFalse(self.database.delete_account_list(user_id=other, list_id=record["id"]))
        self.assertEqual(self.database.remove_account_list_items(user_id=other, list_id=record["id"], item_ids=[record["items"][0]["id"]]), 0)


def _call(tool: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": tool, "call_id": call_id, "arguments": json.dumps(args)}


def _model_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    outputs = list(items)
    text = ""
    if reply is not None:
        text = json.dumps(reply)
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": outputs}, input_tokens=10, output_tokens=5)


def _reply(text: str, **extra) -> dict:
    return {"reply": text, "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None, **extra}


class ScriptedModel:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = list(rounds)
        self.inputs: list[list[dict]] = []

    def __call__(self, input_items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(input_items))
        return self.rounds.pop(0)


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, payload: dict | None = None, **kwargs) -> tuple[dict, int]:
        self.calls.append((method, path, payload))
        return {"ok": True, "action": {"id": 1}}, 200


class ListToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)
        self.api = FakeApi()

    def _context(self) -> LoopContext:
        return LoopContext(
            api=self.api, database=self.database, email="owner@example.com", user_id=self.user_id,
            timezone_name="Asia/Jerusalem", channel="whatsapp",
            list_link=lambda list_id: LINK.format(id=list_id) if list_id else LINK.format(id=0).replace("#/list/0", ""),
        )

    def _last_output(self, model: ScriptedModel) -> dict:
        return json.loads(model.inputs[-1][-1]["output"])

    def test_the_tools_are_offered_without_any_source_connected(self) -> None:
        by_name = {tool["name"]: tool for tool in tool_definitions({})}
        for name in ("create_list", "update_list", "show_lists"):
            self.assertNotIn("UNAVAILABLE", by_name[name]["description"])
        self.assertIn("list_name", by_name["schedule_message"]["parameters"]["properties"])

    def test_the_lists_page_is_in_context_so_a_reply_without_a_tool_can_point_at_it(self) -> None:
        # "Can you help with my todos?" is answered without a tool; the link
        # must still be there to give, and the guard must let it through.
        home = LINK.format(id=0).replace("#/list/0", "")
        model = ScriptedModel([_model_round(reply=_reply(f"Yes. Dump them here or open the page:\n{home}"))])
        result = run_agent_loop(context=self._context(), call_model=model, user_message="can you help with my todos?", conversation=[], today="2026-09-05")
        self.assertIn(f'"listsPage":"{home}"', model.inputs[0][0]["content"])
        self.assertIn(home, result.reply)

    def test_creating_a_list_hands_back_the_link_and_the_reply_may_carry_it(self) -> None:
        model = ScriptedModel([
            _model_round(_call("create_list", "c1", name="Shopping", kind="general", items=["Milk", "Eggs"])),
            _model_round(reply=_reply(f"Started your shopping list with milk and eggs.\n{LINK.format(id=1)}", claimsCompleted=["create_list"])),
        ])
        result = run_agent_loop(context=self._context(), call_model=model, user_message="start a shopping list: milk, eggs", conversation=[], today="2026-09-05")

        output = self._last_output(model)
        self.assertTrue(output["ok"])
        self.assertEqual([item["text"] for item in output["list"]["items"]], ["Milk", "Eggs"])
        self.assertEqual(output["link"], LINK.format(id=1))
        self.assertIn(LINK.format(id=1), result.reply)
        self.assertEqual(result.completed, ["create_list"])
        self.assertEqual(self.database.list_account_lists(user_id=self.user_id)[0]["name"], "Shopping")

    def test_a_list_is_found_by_the_persons_words_and_changed(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Shopping list", items=["Milk", "Eggs"])
        model = ScriptedModel([
            _model_round(_call("update_list", "c1", list_name="shopping", action="add", items=["Bread", "milk"], new_name=None)),
            _model_round(_call("update_list", "c2", list_name="shopping", action="remove", items=["the eggs", "butter"], new_name=None)),
            _model_round(reply=_reply("Added bread; milk was already there. Took eggs off; butter wasn't on it.")),
        ])
        run_agent_loop(context=self._context(), call_model=model, user_message="add bread and milk, remove eggs and butter", conversation=[], today="2026-09-05")

        added = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(added["added"], ["Bread"])
        self.assertEqual(added["alreadyThere"], ["milk"])
        removed = json.loads(model.inputs[2][-1]["output"])
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(removed["notOnList"], ["butter"])
        record = self.database.list_account_lists(user_id=self.user_id)[0]
        self.assertEqual(record["itemCount"], 2)

    def test_two_lists_that_could_be_meant_become_a_question(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Rome packing")
        self.database.create_account_list(user_id=self.user_id, name="Beach packing")
        model = ScriptedModel([
            _model_round(_call("update_list", "c1", list_name="packing", action="add", items=["Sunscreen"], new_name=None)),
            _model_round(reply=_reply("Which one - Rome packing or Beach packing?")),
        ])
        run_agent_loop(context=self._context(), call_model=model, user_message="add sunscreen to the packing list", conversation=[], today="2026-09-05")
        output = self._last_output(model)
        self.assertEqual(output["error"]["code"], "choice_required")
        self.assertCountEqual([o["say"] for o in output["error"]["options"]], ["Rome packing", "Beach packing"])

    def test_a_missing_list_names_the_ones_that_exist(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Shopping")
        model = ScriptedModel([
            _model_round(_call("show_lists", "c1", list_name="birthday")),
            _model_round(reply=_reply("There's no birthday list; you have Shopping.")),
        ])
        run_agent_loop(context=self._context(), call_model=model, user_message="what's on the birthday list?", conversation=[], today="2026-09-05")
        output = self._last_output(model)
        self.assertEqual(output["error"]["code"], "nothing_found")
        self.assertIn("Shopping", output["error"]["whatHappened"])

    def test_ticking_off_a_general_list_is_refused_and_a_todo_is_ticked(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Ideas", items=["Podcast"])
        self.database.create_account_list(user_id=self.user_id, name="Today", kind="todo", items=["Call bank"])
        model = ScriptedModel([
            _model_round(_call("update_list", "c1", list_name="ideas", action="check", items=["podcast"], new_name=None)),
            _model_round(_call("update_list", "c2", list_name="today", action="check", items=["bank"], new_name=None)),
            _model_round(reply=_reply("Ticked off the bank call.")),
        ])
        run_agent_loop(context=self._context(), call_model=model, user_message="tick off podcast and the bank", conversation=[], today="2026-09-05")
        refused = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(refused["error"]["code"], "not_supported")
        ticked = json.loads(model.inputs[2][-1]["output"])
        self.assertEqual(ticked["checked"], 1)
        self.assertEqual(ticked["list"]["openCount"], 0)

    def test_a_deadline_rides_with_the_item_and_the_weekday_is_in_context(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Admin", kind="todo", items=["Call bank"])
        model = ScriptedModel([
            _model_round(_call("update_list", "c1", list_name="admin", action="add", items=["Renew insurance"], due="2026-09-11", new_name=None)),
            _model_round(_call("update_list", "c2", list_name="admin", action="set_due", items=["bank"], due="2026-09-08", new_name=None)),
            _model_round(reply=_reply("Added, due Friday; the bank call is due Tuesday.")),
        ])
        run_agent_loop(context=self._context(), call_model=model, user_message="add renew insurance by friday, and the bank call by tuesday", conversation=[], today="2026-09-05")
        self.assertIn('"todayWeekday":"Saturday"', model.inputs[0][0]["content"])
        added = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(added["dueOn"], "2026-09-11")
        dated = json.loads(model.inputs[2][-1]["output"])
        self.assertEqual(dated["dueSet"], 1)
        by_text = {item["text"]: item.get("dueOn") for item in dated["list"]["items"]}
        self.assertEqual(by_text, {"Call bank": "2026-09-08", "Renew insurance": "2026-09-11"})

    def test_deleting_from_chat_puts_the_list_away_not_gone(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Old")
        model = ScriptedModel([
            _model_round(_call("update_list", "c1", list_name="old", action="delete", items=[], new_name=None)),
            _model_round(reply=_reply("Put the Old list away.")),
        ])
        run_agent_loop(context=self._context(), call_model=model, user_message="delete the old list", conversation=[], today="2026-09-05")
        self.assertEqual(self.database.list_account_lists(user_id=self.user_id), [])
        archived = self.database.list_account_lists(user_id=self.user_id, include_archived=True)
        self.assertEqual((archived[0]["id"], archived[0]["archived"]), (record["id"], True))

    def test_a_reminder_about_a_list_carries_the_list_id_not_its_items(self) -> None:
        self.database.create_account_list(user_id=self.user_id, name="Groceries", items=["Milk"])
        model = ScriptedModel([
            _model_round(_call("schedule_message", "c1", time_local="18:00", date_policy="today", delay_minutes=None, message_text="Time to shop", list_name="groceries")),
            _model_round(reply=_reply("I can text you at 18:00 with what's still on Groceries. Yes?")),
        ])
        result = run_agent_loop(context=self._context(), call_model=model, user_message="remind me at 6 about groceries", conversation=[], today="2026-09-05")
        asked = self._last_output(model)
        self.assertEqual(asked["error"]["code"], "confirmation_required")
        self.assertIn("Groceries", asked["error"]["whatHappened"])

        model = ScriptedModel([_model_round(reply=_reply("Set.", claimsCompleted=["schedule_message"]))])
        run_agent_loop(context=self._context(), call_model=model, user_message="yes", conversation=[], today="2026-09-05", confirmed_call=result.pending_confirmation)
        payload = self.api.calls[0][2]["payload"]
        self.assertEqual(payload["listName"], "Groceries")
        self.assertGreater(payload["listId"], 0)
        self.assertNotIn("Milk", json.dumps(payload))

    def test_a_reminder_about_a_list_nobody_has_is_never_asked_about(self) -> None:
        model = ScriptedModel([
            _model_round(_call("schedule_message", "c1", time_local="18:00", date_policy="today", delay_minutes=None, message_text="Shop", list_name="groceries")),
            _model_round(reply=_reply("You don't have a groceries list yet - want me to start one?")),
        ])
        result = run_agent_loop(context=self._context(), call_model=model, user_message="remind me about groceries at 6", conversation=[], today="2026-09-05")
        self.assertIsNone(result.pending_confirmation)
        self.assertEqual(self._last_output(model)["error"]["code"], "nothing_found")


class ListReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)

    def test_the_reminder_reads_the_list_when_it_fires(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Groceries", kind="todo", items=["Milk", "Eggs", "Bread"])
        action = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="send_message", channel="portal", recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1), timezone_name="Asia/Jerusalem",
            payload={"messageText": "Time to shop", "listId": record["id"], "listName": "Groceries"},
        )
        # Eggs got bought after the reminder was set.
        self.database.set_account_list_items_done(user_id=self.user_id, list_id=record["id"], item_ids=[record["items"][1]["id"]], done=True)

        ScheduledActionScheduler(self.database, config=ScheduledActionConfig(poll_seconds=1, batch_size=5)).run_pending()

        body = self.database.list_notifications(user_id=self.user_id)[0]["body"]
        self.assertIn("Time to shop", body)
        self.assertIn("• Milk", body)
        self.assertIn("• Bread", body)
        self.assertNotIn("Eggs", body)
        self.assertEqual(self.database.get_scheduled_action(int(action["id"]))["status"], "sent")

    def test_the_morning_nudge_goes_once_and_only_after_the_hour(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Admin", kind="todo")
        self.database.add_account_list_items(user_id=self.user_id, list_id=record["id"], texts=["VAT return"], due_on="2026-09-05")
        self.database.add_account_list_items(user_id=self.user_id, list_id=record["id"], texts=["Renew insurance"], due_on="2026-09-03")
        self.database.add_account_list_items(user_id=self.user_id, list_id=record["id"], texts=["Book courier"], due_on="2026-09-06")
        self.database.add_account_list_items(user_id=self.user_id, list_id=record["id"], texts=["Far away"], due_on="2026-10-01")
        nudger = ListDueNudger(self.database, config=ListDueNudgeConfig(hour=8, poll_seconds=60))

        # 07:30 UTC: nothing yet, the account has no timezone so UTC stands in.
        early = nudger.run_pending(now=datetime(2026, 9, 5, 7, 30, tzinfo=timezone.utc))
        self.assertEqual(early["queued"], 0)

        sent = nudger.run_pending(now=datetime(2026, 9, 5, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(sent["queued"], 1)
        actions = self.database.list_scheduled_actions_for_user(self.user_id, limit=5)
        self.assertEqual(len(actions), 1)
        text = actions[0]["payload"]["messageText"]
        self.assertIn("Due today:\n• VAT return (Admin)", text)
        self.assertIn("Due tomorrow:\n• Book courier (Admin)", text)
        self.assertIn("Overdue:\n• Renew insurance (Admin) - 2 days overdue", text)
        self.assertNotIn("Far away", text)
        self.assertEqual(actions[0]["channel"], "portal")

        again = nudger.run_pending(now=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc))
        self.assertEqual((again["queued"], again["skipped"]), (0, 1))
        self.assertEqual(len(self.database.list_scheduled_actions_for_user(self.user_id, limit=5)), 1)

    def test_a_ticked_item_is_never_nudged_about(self) -> None:
        record = self.database.create_account_list(user_id=self.user_id, name="Admin", kind="todo")
        added = self.database.add_account_list_items(user_id=self.user_id, list_id=record["id"], texts=["VAT return"], due_on="2026-09-01")
        self.database.set_account_list_items_done(user_id=self.user_id, list_id=record["id"], item_ids=[added["added"][0]["id"]], done=True)
        summary = ListDueNudger(self.database, config=ListDueNudgeConfig(hour=0)).run_pending(now=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(summary["queued"], 0)

    def test_due_dates_are_said_in_words(self) -> None:
        today = date(2026, 9, 5)
        self.assertEqual(describe_due("2026-09-05", today), "due today")
        self.assertEqual(describe_due("2026-09-06", today), "due tomorrow")
        self.assertEqual(describe_due("2026-09-08", today), "due Tuesday")
        self.assertEqual(describe_due("2026-09-30", today), "due Wed 30 Sep")
        self.assertEqual(describe_due("2026-09-04", today), "1 day overdue")
        self.assertEqual(describe_due("", today), "")

    def test_a_list_with_nothing_left_says_so(self) -> None:
        self.assertEqual(describe_list_for_message({"name": "Today", "kind": "todo", "items": [{"text": "x", "done": True}]}), "Today: nothing left on it.")
        self.assertEqual(describe_list_for_message({"name": "Names", "kind": "general", "items": [{"text": "Dana"}]}), "Names:\n• Dana")


class ListApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="lists-test-secret-that-is-long-enough"),
        )
        self.server.database.register_user("owner@example.com")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cookie = self._sign_in()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _sign_in(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib_request.urlopen(request) as response:
            return response.headers.get("Set-Cookie", "").split(";", 1)[0]

    def _request(self, method: str, path: str, body: dict | None = None, *, cookie: str | None = "", raw: bool = False):
        headers = {"Content-Type": "application/json"}
        if cookie is not None:
            headers["Cookie"] = cookie or self.cookie
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers, method=method,
        )
        try:
            with urllib_request.urlopen(request) as response:
                data = response.read()
                return response.status, (data.decode("utf-8") if raw else json.loads(data.decode("utf-8")))
        except urllib_error.HTTPError as exc:
            data = exc.read()
            try:
                return exc.code, json.loads(data.decode("utf-8"))
            except ValueError:
                return exc.code, data.decode("utf-8")

    def test_the_page_lives_at_lists_and_needs_no_inline_script(self) -> None:
        for path in ("/lists", "/lists/"):
            with urllib_request.urlopen(f"{self.base_url}{path}") as response:
                markup = response.read().decode("utf-8")
            self.assertIn("Assistyca | Lists", markup)
            self.assertNotIn("<script>", markup)
        with urllib_request.urlopen(f"{self.base_url}/l/whatever-token") as response:
            self.assertIn("Shared list", response.read().decode("utf-8"))

    def test_lists_are_created_changed_and_read_through_the_api(self) -> None:
        status, created = self._request("POST", "/api/lists", {"name": "Shopping", "kind": "general", "items": ["Milk"]})
        self.assertEqual(status, 200)
        list_id = created["list"]["id"]

        status, added = self._request("POST", f"/api/lists/{list_id}/items", {"items": ["Eggs", "milk"]})
        self.assertEqual([item["text"] for item in added["added"]], ["Eggs"])
        self.assertEqual(added["skipped"], ["milk"])

        egg_id = added["list"]["items"][1]["id"]
        status, edited = self._request("POST", f"/api/lists/{list_id}/items/{egg_id}", {"text": "A dozen eggs"})
        self.assertEqual(edited["item"]["text"], "A dozen eggs")

        status, removed = self._request("DELETE", f"/api/lists/{list_id}/items/{egg_id}")
        self.assertEqual(removed["removed"], 1)

        status, renamed = self._request("POST", f"/api/lists/{list_id}", {"name": "Groceries"})
        self.assertEqual(renamed["list"]["name"], "Groceries")

        status, listing = self._request("GET", "/api/lists")
        self.assertEqual([entry["name"] for entry in listing["lists"]], ["Groceries"])
        self.assertEqual(listing["lists"][0]["itemCount"], 1)

        status, gone = self._request("DELETE", f"/api/lists/{list_id}")
        self.assertTrue(gone["deleted"])
        status, _ = self._request("GET", f"/api/lists/{list_id}")
        self.assertEqual(status, 404)

    def test_a_due_date_is_set_and_cleared_through_the_api(self) -> None:
        _, created = self._request("POST", "/api/lists", {"name": "Admin", "kind": "todo", "items": []})
        list_id = created["list"]["id"]
        _, added = self._request("POST", f"/api/lists/{list_id}/items", {"items": ["VAT return"], "dueOn": "2026-09-15"})
        item = added["added"][0]
        self.assertEqual(item["dueOn"], "2026-09-15")
        _, cleared = self._request("POST", f"/api/lists/{list_id}/items/{item['id']}", {"dueOn": ""})
        self.assertEqual(cleared["item"]["dueOn"], "")
        status, bad = self._request("POST", f"/api/lists/{list_id}/items/{item['id']}", {"dueOn": "friday"})
        self.assertEqual(status, 400)

    def test_without_a_session_the_lists_api_says_sign_in(self) -> None:
        status, payload = self._request("GET", "/api/lists", cookie=None)
        self.assertEqual(status, 401)
        status, payload = self._request("POST", "/api/lists", {"name": "x"}, cookie=None)
        self.assertEqual(status, 401)

    def test_the_share_link_shows_the_words_and_nothing_about_the_owner(self) -> None:
        _, created = self._request("POST", "/api/lists", {"name": "Packing", "kind": "todo", "items": ["Passport", "Charger"]})
        list_id = created["list"]["id"]
        self.assertEqual(created["list"]["shareUrl"], "")

        _, shared = self._request("POST", f"/api/lists/{list_id}/share", {"enabled": True})
        share_url = shared["list"]["shareUrl"]
        # The scheme is whatever the server believes it is served over; the
        # host and the path are what matter here.
        self.assertIn(f"127.0.0.1:{self.server.server_address[1]}/l/", share_url)
        token = share_url.rsplit("/", 1)[1]

        status, public = self._request("GET", f"/api/public/lists/{token}", cookie=None)
        self.assertEqual(status, 200)
        self.assertEqual(public["list"]["name"], "Packing")
        self.assertEqual(public["list"]["items"], [{"text": "Passport", "done": False, "dueOn": ""}, {"text": "Charger", "done": False, "dueOn": ""}])
        self.assertNotIn("owner", json.dumps(public))
        self.assertNotIn("example.com", json.dumps(public))

        status, csv_text = self._request("GET", f"/api/public/lists/{token}.csv", cookie=None, raw=True)
        self.assertEqual(csv_text, "text,done,due\n\"Passport\",false,\n\"Charger\",false,\n")

        self._request("POST", f"/api/lists/{list_id}/share", {"enabled": False})
        status, _ = self._request("GET", f"/api/public/lists/{token}", cookie=None)
        self.assertEqual(status, 404)

    def test_a_link_from_whatsapp_signs_the_phone_in_once(self) -> None:
        now = time.time()
        token = create_session_token(
            PortalSession(token="", email="owner@example.com", issued_at=now, expires_at=now + 3600),
            self.server.store.session_secret,
        )

        class NoRedirect(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib_request.build_opener(NoRedirect)
        try:
            opener.open(f"{self.base_url}{LISTS_HANDOFF_PREFIX}{token}?list=7")
            self.fail("expected a redirect")
        except urllib_error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            self.assertEqual(exc.headers.get("Location"), "/lists#/list/7")
            cookie = exc.headers.get("Set-Cookie", "")
            self.assertIn(f"{SESSION_COOKIE_NAME}=", cookie)
            session_cookie = cookie.split(";", 1)[0]

        # The cookie it set is a real session.
        status, listing = self._request("GET", "/api/lists", cookie=session_cookie)
        self.assertEqual(status, 200)

        # The same link a second time opens nothing.
        try:
            opener.open(f"{self.base_url}{LISTS_HANDOFF_PREFIX}{token}?list=7")
            self.fail("expected a redirect")
        except urllib_error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            self.assertEqual(exc.headers.get("Location"), "/lists?expired=1")
            self.assertNotIn(SESSION_COOKIE_NAME, exc.headers.get("Set-Cookie", "") or "")

    def test_the_loop_hands_whatsapp_a_signed_link_and_the_browser_a_plain_one(self) -> None:
        handler = SimpleNamespace(
            _public_base_url=lambda: "https://assistyca.test",
            store=self.server.store,
        )
        from packages.infrastructure.portal_auth.server import PortalAuthHandler

        build_whatsapp = PortalAuthHandler._lists_link_builder(handler, "owner@example.com", "whatsapp")
        link = build_whatsapp(3)
        self.assertTrue(link.startswith(f"https://assistyca.test{LISTS_HANDOFF_PREFIX}"))
        self.assertTrue(link.endswith("?list=3"))
        build_portal = PortalAuthHandler._lists_link_builder(handler, "owner@example.com", "portal")
        self.assertEqual(build_portal(3), "https://assistyca.test/lists#/list/3")
        self.assertEqual(build_portal(0), "https://assistyca.test/lists")


if __name__ == "__main__":
    unittest.main()
