"""Exceptions: what the person says is not happening for some days.

What these prove: an exception covers its first and last day and nothing
either side; it holds an activity, everything one person does, the whole
week, one scheduled action or all of them; the assistant saves one only for
things that exist in this account and removes it on request, and every turn
after that can see it; the week's nudges leave out what it holds; a standing
action skips a held day and comes back, a reminder is moved to the same time
the day after rather than lost, and a group's messages and the server's own
alerts are never held by an account's pause.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.family_week_nudges import FamilyWeekNudgeConfig
from packages.infrastructure.family_week_nudges import FamilyWeekNudger
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler
from packages.infrastructure.schedule_exceptions import action_exception
from packages.infrastructure.schedule_exceptions import activity_exception
from packages.infrastructure.schedule_exceptions import family_week_paused
from packages.infrastructure.schedule_exceptions import held_until
from packages.infrastructure.schedule_exceptions import normalize_targets
from packages.infrastructure.standing_tasks import STANDING_TASK_ACTION_TYPE

UTC = timezone.utc
JERUSALEM = "Asia/Jerusalem"
ZONE = ZoneInfo(JERUSALEM)
OWNER_WA_ID = "972507322341"
# 2026-09-20 is a Sunday.
SUNDAY = datetime(2026, 9, 20, tzinfo=UTC)
FOOTBALL = {"id": 4, "title": "Football", "who": ["Tom"], "days": ["mon"]}
GAN = {"id": 5, "title": "gan", "who": ["Noa"], "days": ["mon"]}


def held(start: str, end: str, *targets: dict, exception_id: int = 1) -> dict:
    return {"id": exception_id, "startsOn": start, "endsOn": end, "targets": list(targets)}


class RulesTests(unittest.TestCase):
    def test_an_exception_covers_its_first_and_last_day_and_nothing_else(self) -> None:
        week = [held("2026-09-21", "2026-09-23", {"kind": "activity", "ref": "4"})]
        self.assertIsNone(activity_exception(FOOTBALL, week, date(2026, 9, 20)))
        self.assertIsNotNone(activity_exception(FOOTBALL, week, date(2026, 9, 21)))
        self.assertIsNotNone(activity_exception(FOOTBALL, week, date(2026, 9, 23)))
        self.assertIsNone(activity_exception(FOOTBALL, week, date(2026, 9, 24)))
        self.assertIsNone(activity_exception(GAN, week, date(2026, 9, 21)), "only the activity it names")

    def test_a_person_or_the_whole_week_holds_everything_it_reaches(self) -> None:
        sick = [held("2026-09-21", "2026-09-21", {"kind": "person", "ref": "tom"})]
        self.assertIsNotNone(activity_exception(FOOTBALL, sick, date(2026, 9, 21)))
        self.assertIsNone(activity_exception(GAN, sick, date(2026, 9, 21)))
        away = [held("2026-09-21", "2026-09-30", {"kind": "family_week", "ref": ""})]
        self.assertIsNotNone(activity_exception(GAN, away, date(2026, 9, 25)))
        self.assertTrue(family_week_paused(away, date(2026, 9, 25)))
        self.assertFalse(family_week_paused(sick, date(2026, 9, 21)))

    def test_actions_are_held_by_number_or_all_together(self) -> None:
        one = [held("2026-09-21", "2026-09-22", {"kind": "action", "ref": "7"})]
        self.assertIsNotNone(action_exception(7, one, date(2026, 9, 22)))
        self.assertIsNone(action_exception(8, one, date(2026, 9, 22)))
        every = [held("2026-09-21", "2026-09-22", {"kind": "all_actions", "ref": "anything"})]
        self.assertIsNotNone(action_exception(8, every, date(2026, 9, 21)))

    def test_targets_are_kept_once_and_only_when_they_say_something(self) -> None:
        self.assertEqual(
            normalize_targets([
                {"kind": "person", "ref": "Tom"}, {"kind": "person", "ref": "tom "}, {"kind": "activity", "ref": ""},
                {"kind": "family_week", "ref": "x"}, {"kind": "holiday", "ref": "1"},
            ]),
            [{"kind": "person", "ref": "Tom"}, {"kind": "family_week", "ref": ""}],
        )

    def test_a_held_reminder_goes_at_its_own_time_the_day_after(self) -> None:
        due = datetime(2026, 10, 3, 9, 30, tzinfo=ZONE)
        self.assertEqual(held_until(due, held("2026-10-01", "2026-10-10")), datetime(2026, 10, 11, 9, 30, tzinfo=ZONE))


# -- the assistant, with a scripted model --------------------------------------


class _Store:
    def __init__(self, database: PortalDatabase) -> None:
        self._database = database

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    def list_platform_connections(self, email: str) -> list[dict]:
        return []


class _Model:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = rounds
        self.inputs: list[list[dict]] = []

    def __call__(self, items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(items))
        return self.rounds.pop(0)


def _call(name: str, **args) -> SimpleNamespace:
    call = {"type": "function_call", "name": name, "call_id": "c-1", "arguments": json.dumps(args)}
    return SimpleNamespace(output_text="", raw_response={"output": [call]}, input_tokens=1, output_tokens=1)


def _reply(text: str = "Done.") -> SimpleNamespace:
    body = json.dumps({"reply": text, "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None})
    return SimpleNamespace(
        output_text=body, raw_response={"output": [{"type": "message", "content": [{"type": "output_text", "text": body}]}]},
        input_tokens=1, output_tokens=1,
    )


def _hold(**overrides) -> dict:
    return {
        "from": "2099-09-21", "until": "2099-09-27", "reason": "", "activities": [], "people": [], "wholeWeek": False,
        "actions": [], "allActions": False, **overrides,
    }


class ExceptionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com", display_name="Dana Levi")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        self.football = self.database.save_household_activity(
            user_id=self.user_id, title="Football", who=["Tom"], days=["mon"], start_time="16:00", end_time="17:00",
        )
        self.summary = self.database.create_scheduled_action(
            user_id=self.user_id, action_type=STANDING_TASK_ACTION_TYPE, channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(UTC) + timedelta(hours=1), timezone_name=JERUSALEM,
            payload={"title": "Morning summary", "instruction": "summarise", "schedule": {"frequency": "daily", "timeLocal": "08:00"}},
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _turn(self, *rounds: SimpleNamespace, group: dict | None = None) -> tuple[object, _Model]:
        context = LoopContext(
            api=lambda *args, **kwargs: ({"ok": True}, 200), database=_Store(self.database), email="dana@example.com",
            user_id=self.user_id, timezone_name=JERUSALEM, channel="whatsapp",
            in_group=bool(group), group=group or {},
        )
        model = _Model(list(rounds))
        result = run_agent_loop(context=context, call_model=model, user_message="no football this week", conversation=[], today="2099-09-20")
        return result, model

    @staticmethod
    def _output(model: _Model) -> dict:
        return json.loads(model.inputs[1][-1]["output"])

    def test_an_activity_is_put_on_hold_and_the_next_turn_can_see_it(self) -> None:
        result, model = self._turn(_call("add_exception", **_hold(activities=[self.football["id"]], reason="no football")), _reply())
        output = self._output(model)
        self.assertTrue(output["ok"], output)
        self.assertEqual(output["saved"]["covers"], [f"Football (Tom), activity {self.football['id']}"])
        self.assertIn("back on 2099-09-28", output["note"])
        self.assertIn("add_exception", result.completed)

        _, later = self._turn(_reply("Football is off until Sunday."))
        prompt = str(later.inputs[0][0]["content"])
        self.assertIn('"exceptions":[{"id":', prompt)
        self.assertIn('"reason":"no football"', prompt)

    def test_a_person_is_matched_however_it_is_written_and_a_stranger_is_not(self) -> None:
        _, model = self._turn(_call("add_exception", **_hold(people=["tom"])), _reply())
        self.assertEqual(self._output(model)["saved"]["covers"], ["everything Tom does"])
        _, model = self._turn(_call("add_exception", **_hold(people=["Gil"])), _reply())
        output = self._output(model)
        self.assertEqual(output["error"]["code"], "not_found")
        self.assertEqual(output["error"]["family"], ["Tom"])

    def test_a_scheduled_action_of_this_account_can_be_held_and_nobody_else_s(self) -> None:
        _, model = self._turn(_call("add_exception", **_hold(actions=[self.summary["id"]])), _reply())
        output = self._output(model)
        self.assertEqual(output["saved"]["covers"], [f"Morning summary, scheduled {self.summary['id']}"])
        self.assertIn("A reminder due in those days is not lost", output["note"])
        self.database.register_user("other@example.com")
        other = self.database.create_scheduled_action(
            user_id=int((self.database.get_user("other@example.com") or {})["id"]), action_type="send_message",
            channel="whatsapp", recipient_ref="owner", run_at=datetime.now(UTC) + timedelta(hours=1),
            timezone_name=JERUSALEM, payload={"messageText": "theirs"},
        )
        _, model = self._turn(_call("add_exception", **_hold(actions=[other["id"]])), _reply())
        self.assertEqual(self._output(model)["error"]["code"], "not_found")

    def test_days_that_are_over_or_nothing_named_are_refused(self) -> None:
        _, model = self._turn(_call("add_exception", **_hold(**{"from": "2020-01-01", "until": "2020-01-02", "wholeWeek": True})), _reply())
        self.assertEqual(self._output(model)["error"]["code"], "choice_required")
        _, model = self._turn(_call("add_exception", **_hold()), _reply())
        self.assertIn("Say what is on hold", self._output(model)["error"]["whatHappened"])
        self.assertEqual(self.database.list_schedule_exceptions(user_id=self.user_id), [])

    def test_a_group_can_hold_its_own_week_but_no_one_s_actions(self) -> None:
        group = {"id": "120363@g.us", "name": "Football parents", "speaker": ""}
        _, model = self._turn(_call("add_exception", **_hold(allActions=True)), _reply(), group=group)
        self.assertEqual(self._output(model)["error"]["code"], "not_supported")
        _, model = self._turn(_call("add_exception", **_hold(wholeWeek=True)), _reply(), group=group)
        self.assertTrue(self._output(model)["ok"])
        self.assertEqual(self.database.list_schedule_exceptions(user_id=self.user_id), [], "not the account's own week")
        self.assertEqual(len(self.database.list_schedule_exceptions(user_id=self.user_id, group_id=group["id"])), 1)

    def test_an_exception_is_taken_off_on_request(self) -> None:
        saved = self.database.save_schedule_exception(
            user_id=self.user_id, starts_on="2099-09-21", ends_on="2099-09-27", targets=[{"kind": "family_week", "ref": ""}],
        )
        _, model = self._turn(_call("remove_exception", id=saved["id"]), _reply())
        self.assertTrue(self._output(model)["ok"])
        self.assertEqual(self.database.list_schedule_exceptions(user_id=self.user_id), [])


# -- the week's nudges -----------------------------------------------------------


class NudgesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com", display_name="Dana Levi")
        self.database.update_user_account_type("dana@example.com", account_type="family")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        self.gan = self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["sun"],
            start_time="07:30", end_time="16:00", drop_off_by="Dana", pick_up_by="Shirly",
        )
        self.ballet = self.database.save_household_activity(
            user_id=self.user_id, title="Ballet", who=["Noa"], days=["sun"],
            start_time="16:30", end_time="17:30", drop_off_by="Shirly", pick_up_by="me",
        )
        self.nudger = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def hold(self, *targets: dict, start: str = "2026-09-20", end: str = "2026-09-20") -> None:
        self.database.save_schedule_exception(user_id=self.user_id, starts_on=start, ends_on=end, targets=list(targets))

    def queued(self, title: str) -> list[dict]:
        return [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("title") == title
        ]

    def test_what_is_held_is_left_out_of_the_morning_and_its_drive(self) -> None:
        self.hold({"kind": "person", "ref": "Tom"})
        summary = self.nudger.run_pending(now=SUNDAY.replace(hour=7, minute=5))
        self.assertEqual((summary["morning"], summary["rides"]), (1, 0), "Dana's 07:30 drop-off is Tom's, and Tom is off")
        [morning] = self.queued("Today in your family's week")
        self.assertIn("Ballet (Noa)", morning["payload"]["instruction"])
        self.assertNotIn("Kindergarten", morning["payload"]["instruction"])

    def test_the_evening_before_asks_nothing_about_a_held_day(self) -> None:
        self.database.save_household_activity(
            user_id=self.user_id, title="Swimming", who=["Noa"], days=["mon"], start_time="17:00", end_time="18:00",
        )
        self.hold({"kind": "family_week", "ref": ""}, start="2026-09-21", end="2026-09-21")
        self.assertEqual(self.nudger.run_pending(now=SUNDAY.replace(hour=20, minute=15))["evening"], 0)

    def test_the_whole_week_on_hold_is_quiet_about_the_family_birthdays_and_all(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", birthday="2021-10-20")
        self.hold({"kind": "family_week", "ref": ""})
        for hour in (7, 11, 17):
            self.nudger.run_pending(now=SUNDAY.replace(hour=hour, minute=5))
        self.assertEqual(
            [a for a in self.database.list_scheduled_actions_for_user(self.user_id, limit=50) if a["payload"].get("source") == "family_week"],
            [],
        )
        # The day after, the birthday is raised as it would have been.
        self.assertEqual(self.nudger.run_pending(now=SUNDAY.replace(day=21, hour=11))["birthdays"], 1)


# -- the scheduled actions worker ------------------------------------------------


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        self.runner = mock.Mock(return_value="Today: nothing unusual.")
        self.scheduler = ScheduledActionScheduler(
            self.database, config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10), task_runner=self.runner,
        )
        self.now = datetime.now(UTC)
        self.today = self.now.astimezone(ZONE).date()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _action(self, action_type: str, *, recipient: str = "owner", **payload) -> dict:
        return self.database.create_scheduled_action(
            user_id=self.user_id, action_type=action_type, channel="whatsapp", recipient_ref=recipient,
            run_at=self.now - timedelta(seconds=1), timezone_name=JERUSALEM, payload=payload,
        )

    def _pause(self, *targets: dict, days: int = 3) -> dict:
        return self.database.save_schedule_exception(
            user_id=self.user_id, starts_on=self.today.isoformat(),
            ends_on=(self.today + timedelta(days=days - 1)).isoformat(), targets=list(targets),
        )

    def _run(self) -> mock.Mock:
        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.x") as send:
            self.scheduler.run_pending(now=self.now)
        return send

    def test_a_held_standing_action_skips_the_day_and_comes_back(self) -> None:
        action = self._action(STANDING_TASK_ACTION_TYPE, title="Pickups", instruction="who picks up today",
                              schedule={"frequency": "daily", "timeLocal": "08:00"})
        self._pause({"kind": "action", "ref": str(action["id"])})
        send = self._run()
        send.assert_not_called()
        self.runner.assert_not_called()
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved["status"], "pending")
        self.assertEqual(saved["payload"]["lastRunStatus"], "paused")
        self.assertGreater(datetime.fromisoformat(saved["runAt"]), self.now)

    def test_a_held_reminder_waits_until_the_day_after_the_pause(self) -> None:
        reminder = self._action("send_message", messageText="Call the plumber")
        pause = self._pause({"kind": "all_actions", "ref": ""}, days=2)
        self._run().assert_not_called()
        saved = self.database.get_scheduled_action(int(reminder["id"])) or {}
        self.assertEqual(saved["status"], "pending")
        moved = datetime.fromisoformat(saved["runAt"]).astimezone(ZONE)
        self.assertEqual(moved.date(), self.today + timedelta(days=2))
        self.assertEqual(moved.strftime("%H:%M"), (self.now - timedelta(seconds=1)).astimezone(ZONE).strftime("%H:%M"))
        self.assertEqual(saved["payload"]["heldBy"], {"exceptionId": pause["id"], "until": pause["endsOn"]})

    def test_only_what_the_pause_names_is_held(self) -> None:
        reminder = self._action("send_message", messageText="Call the plumber")
        self._pause({"kind": "action", "ref": str(int(reminder["id"]) + 100)})
        self.assertEqual(self._run().call_count, 1)

    def test_the_server_s_own_alerts_and_a_group_s_messages_are_never_held(self) -> None:
        self._pause({"kind": "all_actions", "ref": ""})
        self._action(STANDING_TASK_ACTION_TYPE, title="Mail", instruction="alert", oneOff=True, source="inbox_watch")
        self._action("send_message", recipient="group:120363@g.us", messageText="Who takes Noam?")
        with mock.patch.object(ScheduledActionScheduler, "_deliver_whatsapp", return_value="wamid.x") as deliver:
            self.scheduler.run_pending(now=self.now)
        self.assertEqual(deliver.call_count, 2)


if __name__ == "__main__":
    unittest.main()
