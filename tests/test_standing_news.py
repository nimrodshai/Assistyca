"""A recurring news task sends only what is new: since its last message, and never twice.

What these prove: the window starts at the last delivered run (one period
back on the first); older dated items and items already sent are held back;
the search is asked for that window; a run with nothing new sends nothing and
still moves on; and what a run found is written down only once it is
delivered.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import mint_agent_session_token
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler
from packages.infrastructure.standing_news import item_fingerprints
from packages.infrastructure.standing_news import news_window_start
from packages.infrastructure.standing_news import parse_item_date
from packages.infrastructure.standing_news import select_new_items
from packages.infrastructure.standing_tasks import STANDING_TASK_ACTION_TYPE
from packages.infrastructure.standing_tasks import NothingNewToSend
from packages.infrastructure.standing_tasks import StandingTaskRunner

JERUSALEM = "Asia/Jerusalem"
OWNER_WA_ID = "972507322341"
DAILY = {"frequency": "daily", "timeLocal": "08:00"}
SINCE = datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)


def _item(title: str, day: str, url: str = "") -> dict:
    return {"title": title, "date": day, "details": "", "sourceName": "", "sourceUrl": url or f"https://news.example/{title.lower().replace(' ', '-')}"}


class WhatIsNewTests(unittest.TestCase):
    def test_the_window_starts_where_the_last_message_left_off(self) -> None:
        now = datetime(2026, 9, 17, 5, 0, tzinfo=timezone.utc)
        covered = {"payload": {"schedule": DAILY, "newsCoveredUntil": "2026-09-15T05:00:00+00:00"}}
        self.assertEqual(news_window_start(covered, now=now), datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc))

    def test_a_first_run_looks_back_one_period(self) -> None:
        now = datetime(2026, 9, 17, 5, 0, tzinfo=timezone.utc)
        self.assertEqual(news_window_start({"payload": {"schedule": DAILY}}, now=now), now - timedelta(days=1))
        weekly = {"payload": {"schedule": {"frequency": "weekly", "timeLocal": "08:00", "weekday": 0}}}
        self.assertEqual(news_window_start(weekly, now=now), now - timedelta(days=7))

    def test_dates_are_read_in_the_ways_sources_write_them(self) -> None:
        for text in ("2026-09-16", "2026-09-16T10:00:00Z", "16 September 2026", "Sep 16, 2026", "September 16th, 2026", "16/09/2026"):
            self.assertEqual(str(parse_item_date(text)), "2026-09-16", text)
        self.assertIsNone(parse_item_date("last week"))

    def test_older_and_already_sent_items_are_held_back(self) -> None:
        sent = _item("Meta opens WhatsApp to agents", "2026-09-16")
        items = [
            _item("Old launch", "2026-09-10"),
            sent,
            {**_item("Meta opens WhatsApp to agents, updated", "2026-09-17"), "sourceUrl": sent["sourceUrl"] + "/"},
            _item("Fresh partner programme", "2026-09-17"),
            _item("Undated but new", "recently"),
        ]
        seen = set(item_fingerprints(sent))

        kept, held = select_new_items(items, since=SINCE, seen=seen)

        self.assertEqual([item["title"] for item in kept], ["Fresh partner programme", "Undated but new"])
        self.assertEqual(held, {"older": 1, "alreadySent": 2})


class _Model:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = rounds
        self.inputs: list[list[dict]] = []

    def __call__(self, items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(items))
        return self.rounds.pop(0)


def _round(*items: dict, reply: str = "") -> SimpleNamespace:
    output = list(items)
    text = ""
    if reply:
        text = json.dumps({"reply": reply, "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None})
        output.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": output}, input_tokens=1, output_tokens=1)


class _Store:
    def __init__(self, database: PortalDatabase) -> None:
        self._database = database

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    def list_platform_connections(self, email: str) -> list[dict]:
        return []


class NewsSearchInARecurringRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run(self, found: list[dict], reply: str = "1. Fresh partner programme — 2026-09-17") -> tuple[object, dict, mock.Mock]:
        context = LoopContext(
            api=lambda *args, **kwargs: ({"ok": True}, 200),
            database=_Store(self.database),
            email="owner@example.com",
            user_id=self.user_id,
            timezone_name=JERUSALEM,
            channel="whatsapp",
            standing_task_id=41,
            news_since=SINCE,
        )
        call = {"type": "function_call", "name": "search_news", "call_id": "n-1", "arguments": json.dumps({"query": "WhatsApp agents", "location": None, "date_range": None, "mode": "list"})}
        model = _Model([_round(call), _round(reply=reply)])
        with mock.patch("packages.infrastructure.agent_loop.search_news", return_value={"mode": "list", "items": found}) as search:
            result = run_agent_loop(context=context, call_model=model, user_message="Do this now: news", conversation=[], today="2026-09-17")
        return result, json.loads(model.inputs[1][-1]["output"]), search

    def test_the_search_asks_for_the_window_and_only_unsent_items_reach_the_reply(self) -> None:
        sent = _item("Meta opens WhatsApp to agents", "2026-09-16")
        self.database.save_standing_news_sent(user_id=self.user_id, action_id=41, items=[{**sent, "fingerprints": item_fingerprints(sent)}])

        result, output, search = self._run([sent, _item("Fresh partner programme", "2026-09-17")])

        self.assertIn("after 2026-09-16 08:00 (Asia/Jerusalem)", search.call_args.kwargs["date_range"])
        self.assertEqual([item["title"] for item in output["items"]], ["Fresh partner programme"])
        self.assertEqual(output["heldBack"]["alreadySent"], 1)
        self.assertFalse(result.nothing_new)
        self.assertEqual([item["title"] for item in result.news_found], ["Fresh partner programme"])

    def test_nothing_new_is_flagged_so_no_message_goes(self) -> None:
        result, output, _ = self._run([_item("Old launch", "2026-09-01")], reply="No new news on WhatsApp agents.")

        self.assertEqual(output["items"], [])
        self.assertTrue(result.nothing_new)

    def test_the_ledger_belongs_to_one_task(self) -> None:
        sent = _item("Meta opens WhatsApp to agents", "2026-09-16")
        self.database.save_standing_news_sent(user_id=self.user_id, action_id=99, items=[{**sent, "fingerprints": item_fingerprints(sent)}])

        _, output, _ = self._run([sent])

        self.assertEqual(len(output["items"]), 1)


class RecurringNewsDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        self.config = ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10)
        self.action = self.database.create_scheduled_action(
            user_id=self.user_id,
            action_type=STANDING_TASK_ACTION_TYPE,
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name=JERUSALEM,
            payload={"instruction": "news about WhatsApp agents", "title": "WhatsApp agent news", "schedule": DAILY, "runCount": 0},
        )
        self.fresh = _item("Fresh partner programme", "2026-09-17")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _sent_keys(self) -> set[str]:
        return self.database.get_standing_news_sent(user_id=self.user_id, action_id=int(self.action["id"]), fingerprints=item_fingerprints(self.fresh))

    def _runner_finding_news(self, action: dict) -> str:
        action["payload"]["newsFound"] = [{"title": self.fresh["title"], "date": self.fresh["date"], "fingerprints": item_fingerprints(self.fresh)}]
        return "1. Fresh partner programme — 2026-09-17"

    def test_nothing_new_sends_nothing_and_moves_on(self) -> None:
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=mock.Mock(side_effect=NothingNewToSend()))
        now = datetime.now(timezone.utc)

        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification") as send:
            summary = scheduler.run_pending(now=now)

        send.assert_not_called()
        self.assertEqual(summary["failed"], 0)
        saved = self.database.get_scheduled_action(int(self.action["id"])) or {}
        self.assertEqual(saved["status"], "pending")
        self.assertEqual(saved["payload"]["lastRunStatus"], "nothing_new")
        self.assertEqual(saved["payload"]["newsCoveredUntil"], now.isoformat())
        self.assertEqual(saved["lastError"], "")

    def test_what_a_delivered_run_sent_is_written_down(self) -> None:
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=self._runner_finding_news)

        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.news"):
            scheduler.run_pending(now=datetime.now(timezone.utc))

        self.assertEqual(self._sent_keys(), set(item_fingerprints(self.fresh)))
        saved = self.database.get_scheduled_action(int(self.action["id"])) or {}
        self.assertNotIn("newsFound", saved["payload"])
        self.assertIn("newsCoveredUntil", saved["payload"])

    def test_a_message_that_never_arrived_uses_up_nothing(self) -> None:
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=self._runner_finding_news)

        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", side_effect=RuntimeError("down")), mock.patch.object(
            ScheduledActionScheduler, "_deliver_in_app", side_effect=RuntimeError("also down"),
        ):
            scheduler.run_pending(now=datetime.now(timezone.utc))

        self.assertEqual(self._sent_keys(), set())
        saved = self.database.get_scheduled_action(int(self.action["id"])) or {}
        self.assertNotIn("newsCoveredUntil", saved["payload"])

    def test_the_runner_names_the_task_and_stops_on_nothing_new(self) -> None:
        runner = StandingTaskRunner(database=self.database, base_url="http://127.0.0.1:1", session_token_factory=lambda email: "token")
        action = self.database.get_scheduled_action(int(self.action["id"])) or {}

        with mock.patch("packages.infrastructure.whatsapp_agent_chat.WhatsAppAgentChat._api", return_value=({"ok": True, "reply": "No new news.", "nothingNew": True}, 200)) as api:
            with self.assertRaises(NothingNewToSend):
                runner.run(action)

        request = api.call_args.args[2]
        self.assertEqual(request["standingTask"]["actionId"], int(self.action["id"]))
        self.assertTrue(request["standingTask"]["newsSince"])
        self.assertEqual(self.database.list_recent_whatsapp_agent_messages(user_id=self.user_id), [])


class RecurringNewsThroughTheServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name) / "site"
        root.mkdir()
        (root / "index.html").write_text("<!doctype html><title>Portal</title>", encoding="utf-8")
        self.server = create_server(
            "127.0.0.1", 0, root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="standing-news-secret"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_two_mornings_the_second_with_nothing_new_sends_once(self) -> None:
        action = self.database.create_scheduled_action(
            user_id=self.user_id,
            action_type=STANDING_TASK_ACTION_TYPE,
            channel="whatsapp",
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name=JERUSALEM,
            payload={"instruction": "news about WhatsApp agents", "title": "WhatsApp agent news", "schedule": DAILY, "runCount": 0},
        )
        action_id = int(action["id"])
        runner = StandingTaskRunner(
            database=self.database,
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            session_token_factory=lambda email: mint_agent_session_token(self.server.store, email),
        )
        scheduler = ScheduledActionScheduler(self.database, config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10), task_runner=runner.run)
        today = datetime.now(timezone.utc).date().isoformat()
        found = {"mode": "list", "items": [_item("Fresh partner programme", today)]}
        call = {"type": "function_call", "name": "search_news", "call_id": "n-1", "arguments": json.dumps({"query": "WhatsApp agents", "location": None, "date_range": None, "mode": "list"})}

        def morning() -> mock.Mock:
            rounds = [_round(call), _round(reply=f"1. Fresh partner programme — {today}")]
            with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=lambda **kwargs: rounds.pop(0)), mock.patch(
                "packages.infrastructure.agent_loop.search_news", return_value=found,
            ), mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.news") as send:
                scheduler.run_pending(now=datetime.now(timezone.utc))
            return send

        first = morning()
        self.assertEqual(first.call_count, 1)
        row = self.database.get_scheduled_action(action_id) or {}
        self.database.reschedule_scheduled_action(action_id=action_id, run_at=datetime.now(timezone.utc) - timedelta(seconds=1), payload=row["payload"])

        second = morning()

        second.assert_not_called()
        saved = self.database.get_scheduled_action(action_id) or {}
        self.assertEqual(saved["payload"]["lastRunStatus"], "nothing_new")
        self.assertEqual(saved["payload"]["runCount"], 2)


if __name__ == "__main__":
    unittest.main()
