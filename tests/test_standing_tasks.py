"""Standing actions: the assistant doing something on a schedule, unasked.

What these prove: the next occurrence is worked out on the person's own
clock; a due action runs, reports, and comes back for its next occurrence
instead of finishing; a bad run leaves it alive; the API saves one with its
first run computed; the whole thing goes through the real loop endpoint with
a scripted model; and the chat tools set one up, list them and stop one.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import mint_agent_session_token
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler
from packages.infrastructure.standing_tasks import STANDING_TASK_ACTION_TYPE
from packages.infrastructure.standing_tasks import StandingTaskRunner
from packages.infrastructure.standing_tasks import build_task_run_message
from packages.infrastructure.standing_tasks import describe_task_schedule
from packages.infrastructure.standing_tasks import next_task_run_at
from packages.infrastructure.standing_tasks import normalize_task_schedule

JERUSALEM = "Asia/Jerusalem"
ZONE = ZoneInfo(JERUSALEM)
OWNER_WA_ID = "972507322341"
DAILY = {"frequency": "daily", "timeLocal": "08:00"}


def _local(instant: datetime | None) -> str:
    assert instant is not None
    return instant.astimezone(ZONE).isoformat()


class ScheduleMathTests(unittest.TestCase):
    def test_daily_after_the_time_has_passed_is_tomorrow(self) -> None:
        after = datetime(2026, 9, 6, 9, 0, tzinfo=ZONE)
        self.assertEqual(_local(next_task_run_at(DAILY, timezone_name=JERUSALEM, after=after)), "2026-09-07T08:00:00+03:00")

    def test_daily_before_the_time_is_today(self) -> None:
        after = datetime(2026, 9, 6, 7, 30, tzinfo=ZONE)
        self.assertEqual(_local(next_task_run_at(DAILY, timezone_name=JERUSALEM, after=after)), "2026-09-06T08:00:00+03:00")

    def test_weekly_lands_on_the_named_day(self) -> None:
        # 6 September 2026 is a Sunday.
        after = datetime(2026, 9, 6, 10, 0, tzinfo=ZONE)
        weekly = {"frequency": "weekly", "timeLocal": "09:00", "weekday": "monday"}
        self.assertEqual(_local(next_task_run_at(weekly, timezone_name=JERUSALEM, after=after)), "2026-09-07T09:00:00+03:00")
        same_day = {"frequency": "weekly", "timeLocal": "09:00", "weekday": "sunday"}
        self.assertEqual(_local(next_task_run_at(same_day, timezone_name=JERUSALEM, after=after)), "2026-09-13T09:00:00+03:00")

    def test_monthly_clamps_to_the_last_day_of_a_short_month(self) -> None:
        after = datetime(2026, 2, 5, 12, 0, tzinfo=ZONE)
        monthly = {"frequency": "monthly", "timeLocal": "09:00", "dayOfMonth": 31}
        self.assertEqual(_local(next_task_run_at(monthly, timezone_name=JERUSALEM, after=after)), "2026-02-28T09:00:00+02:00")

    def test_monthly_moves_to_the_next_month_once_passed(self) -> None:
        after = datetime(2026, 9, 6, 12, 0, tzinfo=ZONE)
        monthly = {"frequency": "monthly", "timeLocal": "09:00", "dayOfMonth": 1}
        self.assertEqual(_local(next_task_run_at(monthly, timezone_name=JERUSALEM, after=after)), "2026-10-01T09:00:00+03:00")

    def test_the_schedule_is_worked_out_on_the_persons_clock(self) -> None:
        after = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        instant = next_task_run_at(DAILY, timezone_name="America/New_York", after=after)
        self.assertEqual(instant.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M"), "08:00")

    def test_a_schedule_is_described_in_words(self) -> None:
        self.assertEqual(describe_task_schedule(DAILY), "every day at 08:00")
        self.assertEqual(describe_task_schedule({"frequency": "weekly", "timeLocal": "9:00", "weekday": 0}), "every Monday at 09:00")
        self.assertEqual(describe_task_schedule({"frequency": "monthly", "timeLocal": "09:00", "dayOfMonth": 1}), "on the 1st of every month at 09:00")
        self.assertEqual(describe_task_schedule({"frequency": "monthly", "timeLocal": "09:00", "dayOfMonth": 22}), "on the 22nd of every month at 09:00")

    def test_an_incomplete_schedule_is_not_one(self) -> None:
        self.assertIsNone(normalize_task_schedule({"frequency": "weekly", "timeLocal": "09:00"}))
        self.assertIsNone(normalize_task_schedule({"frequency": "daily", "timeLocal": "morning"}))
        self.assertIsNone(normalize_task_schedule({"frequency": "yearly", "timeLocal": "09:00"}))
        self.assertEqual(normalize_task_schedule({"frequency": "weekly", "time_local": "9:05", "weekday": "Fri"}), {"frequency": "weekly", "timeLocal": "09:05", "weekday": 4})
        self.assertEqual(normalize_task_schedule({"frequency": "monthly", "timeLocal": "09:00"})["dayOfMonth"], 1)

    def test_the_run_message_says_nobody_is_typing(self) -> None:
        text = build_task_run_message(title="Morning meetings", instruction="read today's calendar", schedule_text="every day at 08:00")
        self.assertIn('"Morning meetings" (every day at 08:00) is running now', text)
        self.assertIn("The person is not writing", text)
        self.assertTrue(text.endswith("Do this now: read today's calendar"))


class StandingTaskSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        self.config = ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _task(self, *, channel: str = "whatsapp", **extra) -> dict:
        return self.database.create_scheduled_action(
            user_id=int(self.user["id"]),
            action_type=STANDING_TASK_ACTION_TYPE,
            channel=channel,
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            timezone_name=JERUSALEM,
            payload={
                "instruction": "read today's calendar and summarise the meetings",
                "title": "Morning meetings",
                "schedule": DAILY,
                "frequency": describe_task_schedule(DAILY),
                "runCount": 0,
                **extra,
            },
        )

    def test_a_due_action_runs_reports_and_comes_back_for_its_next_occurrence(self) -> None:
        action = self._task()
        runner = mock.Mock(return_value="Two meetings today: 10:00 with Dana, 14:00 the dentist.")
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=runner)
        now = datetime.now(timezone.utc)

        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.task-1") as send:
            summary = scheduler.run_pending(now=now)

        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(runner.call_args.args[0]["id"], action["id"])
        self.assertEqual(send.call_args.kwargs["recipient_wa_id"], OWNER_WA_ID)
        self.assertEqual(send.call_args.kwargs["message_text"], "Two meetings today: 10:00 with Dana, 14:00 the dentist.")
        # Not finished: back in the queue for tomorrow at 08:00 where the person is.
        self.assertEqual(saved["status"], "pending")
        self.assertEqual(saved["attemptCount"], 0)
        self.assertEqual(saved["providerMessageId"], "")
        next_run = datetime.fromisoformat(saved["runAt"])
        self.assertGreater(next_run, now)
        self.assertEqual(next_run.astimezone(ZONE).strftime("%H:%M"), "08:00")
        self.assertEqual(saved["payload"]["runCount"], 1)
        self.assertEqual(saved["payload"]["lastRunStatus"], "success")
        self.assertEqual(saved["payload"]["lastProviderMessageId"], "wamid.task-1")
        self.assertEqual(saved["payload"]["nextRunAt"], saved["runAt"])
        self.assertEqual(saved["payload"]["deliveredVia"], "whatsapp")
        # It is due again once that time comes, under the same id.
        due_later = self.database.list_due_scheduled_actions(now=now + timedelta(days=2))
        self.assertEqual([entry["id"] for entry in due_later], [action["id"]])

    def test_a_failed_run_keeps_the_action_alive(self) -> None:
        action = self._task()
        scheduler = ScheduledActionScheduler(
            self.database, config=self.config, task_runner=mock.Mock(side_effect=RuntimeError("the calendar could not be read")),
        )
        now = datetime.now(timezone.utc)

        summary = scheduler.run_pending(now=now)

        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(saved["status"], "pending")
        self.assertGreater(datetime.fromisoformat(saved["runAt"]), now)
        self.assertIn("the calendar could not be read", saved["lastError"])
        self.assertEqual(saved["payload"]["lastRunStatus"], "failed")
        self.assertEqual(saved["payload"]["runCount"], 1)

    def test_a_delivery_receipt_for_one_run_does_not_close_the_action(self) -> None:
        action = self._task()
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=mock.Mock(return_value="Nothing on today."))
        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.task-2"):
            scheduler.run_pending(now=datetime.now(timezone.utc))

        receipt = self.database.update_scheduled_action_delivery_status(provider_message_id="wamid.task-2", status="delivered")

        self.assertIsNone(receipt)
        self.assertEqual((self.database.get_scheduled_action(int(action["id"])) or {})["status"], "pending")

    def test_each_run_reaches_the_in_app_feed_as_its_own_notification(self) -> None:
        action = self._task(channel="portal")
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=mock.Mock(return_value="Day one."))
        scheduler.run_pending(now=datetime.now(timezone.utc))
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.database.reschedule_scheduled_action(
            action_id=int(action["id"]), run_at=datetime.now(timezone.utc) - timedelta(seconds=1), payload=saved["payload"],
        )
        scheduler.task_runner = mock.Mock(return_value="Day two.")

        scheduler.run_pending(now=datetime.now(timezone.utc))

        bodies = sorted(entry["body"] for entry in self.database.list_notifications(user_id=int(self.user["id"])))
        self.assertEqual(bodies, ["Day one.", "Day two."])
        self.assertEqual((self.database.get_scheduled_action(int(action["id"])) or {})["payload"]["runCount"], 2)

    def test_without_a_runner_the_action_says_so_and_waits_for_next_time(self) -> None:
        action = self._task()
        scheduler = ScheduledActionScheduler(self.database, config=self.config)

        summary = scheduler.run_pending(now=datetime.now(timezone.utc))

        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(saved["status"], "pending")
        self.assertIn("not enabled", saved["lastError"])

    def test_a_plain_reminder_still_finishes_as_before(self) -> None:
        reminder = self.database.create_scheduled_action(
            user_id=int(self.user["id"]), action_type="send_message", channel="portal", recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1), timezone_name=JERUSALEM, payload={"messageText": "Call the plumber."},
        )
        scheduler = ScheduledActionScheduler(self.database, config=self.config, task_runner=mock.Mock())

        scheduler.run_pending(now=datetime.now(timezone.utc))

        self.assertEqual((self.database.get_scheduled_action(int(reminder["id"])) or {})["status"], "sent")


class StandingTaskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="standing-test-secret"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, error, result = self.server.store.verify_code("owner@example.com", code)
        self.assertTrue(ok, error)
        self.session_token = str((result or {}).get("token") or "")
        self.env = mock.patch.dict("os.environ", {
            "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "platform-phone",
        })
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.session_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return int(exc.code), json.loads(exc.read().decode("utf-8") or "{}")

    def _create(self, **overrides) -> tuple[int, dict]:
        body = {
            "actionType": "run_task",
            "channel": "whatsapp",
            "timezone": JERUSALEM,
            "instruction": "read today's calendar and summarise the meetings",
            "title": "Morning meetings",
            "schedule": DAILY,
            "source": "whatsapp_agent",
            "payload": {"recipientWaId": OWNER_WA_ID},
            **overrides,
        }
        return self._request("POST", "/api/scheduled-actions", body)

    def test_a_standing_action_is_saved_with_its_first_run_worked_out(self) -> None:
        status, response = self._create()

        self.assertEqual(status, 200, response)
        action = response["action"]
        self.assertEqual(action["actionType"], "run_task")
        self.assertEqual(action["payload"]["title"], "Morning meetings")
        self.assertEqual(action["payload"]["frequency"], "every day at 08:00")
        self.assertEqual(action["payload"]["schedule"], DAILY)
        self.assertEqual(response["runs"], "every day at 08:00")
        first_run = datetime.fromisoformat(action["runAt"])
        self.assertGreater(first_run, datetime.now(timezone.utc))
        self.assertEqual(first_run.astimezone(ZONE).strftime("%H:%M"), "08:00")
        # The phone stays server-side; the row knows it.
        self.assertNotIn("recipientWaId", action["payload"])
        stored = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(stored["payload"]["recipientWaId"], OWNER_WA_ID)

    def test_a_standing_action_without_a_schedule_is_refused(self) -> None:
        status, response = self._create(schedule={"frequency": "weekly", "timeLocal": "09:00"})
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "invalid_schedule")

    def test_a_standing_action_without_an_instruction_is_refused(self) -> None:
        status, response = self._create(instruction="")
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "missing_instruction")

    def test_a_standing_action_is_listed_and_cancelled_like_a_reminder(self) -> None:
        _, created = self._create()
        action_id = int(created["action"]["id"])

        status, listed = self._request("GET", "/api/scheduled-actions")
        self.assertEqual(status, 200)
        self.assertEqual([entry["id"] for entry in listed["actions"]], [action_id])

        status, cancelled = self._request("DELETE", f"/api/scheduled-actions/{action_id}")
        self.assertEqual(status, 200, cancelled)
        self.assertEqual((self.database.get_scheduled_action(action_id) or {})["status"], "cancelled")

    def test_a_standing_action_runs_through_the_assistant_end_to_end(self) -> None:
        _, created = self._create()
        action_id = int(created["action"]["id"])
        row = self.database.get_scheduled_action(action_id) or {}
        self.database.reschedule_scheduled_action(
            action_id=action_id, run_at=datetime.now(timezone.utc) - timedelta(seconds=1), payload=row["payload"],
        )
        self.database.save_whatsapp_agent_message(user_id=int(self.user["id"]), role="user", text="Summarise my meetings every morning")
        runner = StandingTaskRunner(
            database=self.database,
            base_url=self.base_url,
            session_token_factory=lambda email: mint_agent_session_token(self.server.store, email),
        )
        scheduler = ScheduledActionScheduler(
            self.database, config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10), task_runner=runner.run,
        )
        reply = {"reply": "Today: 10:00 with Dana, 14:00 the dentist. Free after 15:00.", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None}
        model_result = SimpleNamespace(
            output_text=json.dumps(reply),
            raw_response={"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(reply)}]}]},
            input_tokens=10, output_tokens=5,
        )

        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", return_value=model_result) as model, mock.patch(
            "packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.task-e2e",
        ) as send:
            summary = scheduler.run_pending(now=datetime.now(timezone.utc))

        self.assertEqual(summary["sent"], 1, summary)
        self.assertEqual(send.call_args.kwargs["recipient_wa_id"], OWNER_WA_ID)
        self.assertEqual(send.call_args.kwargs["message_text"], reply["reply"])
        prompt = str(model.call_args.kwargs["input"][0]["content"])
        self.assertIn("Morning meetings", prompt)
        self.assertIn("(every day at 08:00) is running now on its schedule", prompt)
        self.assertIn("read today's calendar and summarise the meetings", prompt)
        self.assertIn("Summarise my meetings every morning", prompt)
        transcript = self.database.list_recent_whatsapp_agent_messages(user_id=int(self.user["id"]))
        self.assertEqual(transcript[-1]["role"], "assistant")
        self.assertEqual(transcript[-1]["text"], reply["reply"])
        saved = self.database.get_scheduled_action(action_id) or {}
        self.assertEqual(saved["status"], "pending")
        self.assertEqual(saved["payload"]["runCount"], 1)
        self.assertEqual(saved["payload"]["lastRunStatus"], "success")


# -- the chat tools, driven by a scripted model ------------------------------


def _call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


def _model_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    outputs = list(items)
    text = ""
    if reply is not None:
        text = json.dumps(reply)
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": outputs}, input_tokens=1, output_tokens=1)


def _reply(text: str) -> dict:
    return {"reply": text, "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None}


class ScriptedModel:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = list(rounds)
        self.inputs: list[list[dict]] = []

    def __call__(self, input_items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(input_items))
        return self.rounds.pop(0)

    def tool_outputs(self) -> list[dict]:
        return [json.loads(item["output"]) for item in self.inputs[-1] if item.get("type") == "function_call_output"]


class FakeApi:
    def __init__(self, responses: dict[tuple[str, str], tuple[dict, int]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, payload: dict | None = None, **kwargs) -> tuple[dict, int]:
        self.calls.append((method, path, payload))
        return self.responses.get((method, path), ({"ok": True}, 200))


class FakeDatabase:
    def list_platform_connections(self, email: str) -> list[dict]:
        return []


def _context(api: FakeApi) -> LoopContext:
    return LoopContext(
        api=api, database=FakeDatabase(), email="owner@example.com", user_id=1, timezone_name=JERUSALEM,
        tool_context={}, channel="whatsapp", sender_wa_id=OWNER_WA_ID,
    )


def _run(model: ScriptedModel, api: FakeApi, message: str):
    return run_agent_loop(
        context=_context(api), call_model=model, user_message=message, conversation=[], today="2026-09-06", now="11:20",
    )


MORNING = {
    "id": 7, "actionType": "run_task", "status": "pending", "runAt": "2026-09-07T05:00:00+00:00",
    "payload": {"title": "Morning meetings", "instruction": "read today's calendar and summarise the meetings", "frequency": "every day at 08:00", "schedule": DAILY},
}
PLUMBER = {
    "id": 9, "actionType": "send_message", "status": "pending", "runAt": "2026-09-06T13:00:00+00:00",
    "payload": {"messageText": "Call the plumber"},
}


class StandingTaskToolTests(unittest.TestCase):
    def test_schedule_task_sets_the_action_up_and_reports_when_it_first_runs(self) -> None:
        api = FakeApi({("POST", "/api/scheduled-actions"): ({"ok": True, "action": {"id": 7, "runAt": "2026-09-07T05:00:00+00:00", "payload": {"title": "Morning meetings"}}, "nextRunAt": "2026-09-07T05:00:00+00:00", "runs": "every day at 08:00"}, 200)})
        model = ScriptedModel([
            _model_round(_call("schedule_task", "c1", instruction="read today's calendar and summarise the meetings", title="Morning meetings", frequency="daily", time_local="08:00", weekday=None, day_of_month=None)),
            _model_round(reply=_reply("Done: every morning at 08:00 you'll get your meetings. Say 'stop the morning meetings' to end it.")),
        ])

        result = _run(model, api, "Can you give me a summary of my meetings every morning automatically?")

        method, path, posted = api.calls[0]
        self.assertEqual((method, path), ("POST", "/api/scheduled-actions"))
        self.assertEqual(posted["actionType"], "run_task")
        self.assertEqual(posted["channel"], "whatsapp")
        self.assertEqual(posted["schedule"], DAILY)
        self.assertEqual(posted["timezone"], JERUSALEM)
        self.assertEqual(posted["payload"], {"recipientWaId": OWNER_WA_ID})
        outcome = model.tool_outputs()[0]
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["runs"], "every day at 08:00")
        self.assertEqual(outcome["firstRunLocal"], "Mon 7 Sep at 08:00")
        self.assertEqual(result.completed, ["schedule_task"])
        self.assertIn("every morning", result.reply)

    def test_schedule_task_without_a_time_asks_for_one_instead_of_saving(self) -> None:
        api = FakeApi()
        model = ScriptedModel([
            _model_round(_call("schedule_task", "c1", instruction="pull last month's receipts", title="Monthly receipts", frequency="monthly", time_local="", weekday=None, day_of_month=1)),
            _model_round(reply=_reply("What time on the 1st should I send it?")),
        ])

        _run(model, api, "Pull my receipts monthly")

        self.assertEqual(api.calls, [])
        outcome = model.tool_outputs()[0]
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["error"]["code"], "choice_required")

    def test_cancel_scheduled_finds_the_action_by_the_persons_words(self) -> None:
        api = FakeApi({("GET", "/api/scheduled-actions"): ({"ok": True, "actions": [MORNING, PLUMBER]}, 200)})
        model = ScriptedModel([
            _model_round(_call("cancel_scheduled", "c1", what="stop the morning meetings thing", id=None)),
            _model_round(reply=_reply("Stopped - no more morning meetings.")),
        ])

        result = _run(model, api, "stop the morning meetings thing")

        self.assertIn(("DELETE", "/api/scheduled-actions/7", None), api.calls)
        outcome = model.tool_outputs()[0]
        self.assertEqual(outcome["cancelled"]["kind"], "standing action")
        self.assertEqual(outcome["cancelled"]["title"], "Morning meetings")
        self.assertEqual(result.completed, ["cancel_scheduled"])

    def test_cancel_scheduled_with_nothing_to_go_on_lists_the_candidates(self) -> None:
        api = FakeApi({("GET", "/api/scheduled-actions"): ({"ok": True, "actions": [MORNING, PLUMBER]}, 200)})
        model = ScriptedModel([
            _model_round(_call("cancel_scheduled", "c1", what="stop it", id=None)),
            _model_round(reply=_reply("Which one: the morning meetings, or the plumber reminder?")),
        ])

        _run(model, api, "stop it")

        self.assertFalse(any(method == "DELETE" for method, _, _ in api.calls))
        outcome = model.tool_outputs()[0]
        self.assertEqual(outcome["error"]["code"], "choice_required")
        self.assertEqual([entry["kind"] for entry in outcome["error"]["candidates"]], ["standing action", "reminder"])

    def test_show_scheduled_lists_reminders_and_standing_actions(self) -> None:
        api = FakeApi({("GET", "/api/scheduled-actions"): ({"ok": True, "actions": [MORNING, PLUMBER, {**PLUMBER, "id": 3, "status": "sent"}]}, 200)})
        model = ScriptedModel([
            _model_round(_call("show_scheduled", "c1")),
            _model_round(reply=_reply("Two things: your morning meetings every day at 08:00, and a reminder to call the plumber at 16:00.")),
        ])

        _run(model, api, "what do I have scheduled?")

        outcome = model.tool_outputs()[0]
        self.assertEqual(len(outcome["scheduled"]), 2)
        self.assertEqual(outcome["scheduled"][0], {
            "id": 7, "kind": "standing action", "title": "Morning meetings",
            "does": "read today's calendar and summarise the meetings", "runs": "every day at 08:00", "nextRunLocal": "Mon 7 Sep at 08:00",
        })
        self.assertEqual(outcome["scheduled"][1]["kind"], "reminder")
        self.assertEqual(outcome["scheduled"][1]["sendsAtLocal"], "Sun 6 Sep at 16:00")


if __name__ == "__main__":
    unittest.main()
