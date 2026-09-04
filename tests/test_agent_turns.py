"""One record per turn, and the numbers that come from it.

The turn record is written from what went in and what came out, so these
tests drive it the same way: a path, a request, a status and a payload, and
check the row. The alert and the weekly sample are checked against a real
database in a temp file, because their whole job is what they leave behind.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_turns import AgentTurnSamplingConfig
from packages.infrastructure.agent_turns import AgentTurnSamplingScheduler
from packages.infrastructure.agent_turns import TurnRecorder
from packages.infrastructure.agent_turns import check_fallback_alert
from packages.infrastructure.agent_turns import describe_account_state
from packages.infrastructure.agent_turns import describe_response
from packages.infrastructure.agent_turns import format_sample_report
from packages.infrastructure.agent_turns import new_turn_record
from packages.infrastructure.agent_turns import summarize_window
from packages.infrastructure.agent_turns import turn_metrics
from packages.infrastructure.openai_api import OpenAIConfig
from packages.infrastructure.openai_api import OpenAIError
from packages.infrastructure.openai_api import OpenAIGateway
from packages.infrastructure.openai_api import OpenAIRequest
from packages.infrastructure.openai_api import observe_responses
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.reply_judge import parse_scores
from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _turn(*, fallback: bool = False, reason: str = "", outcome: str = "message", incomplete: int = 0, tools=(), created: datetime = NOW) -> dict:
    record = new_turn_record(turn_id=f"t{created.timestamp()}{reason}{fallback}{len(tools)}", path="/api/agent/loop", user_id=1, channel="whatsapp", created_at=created.isoformat())
    record.update(outcome=outcome, fallback_used=fallback, fallback_reason=reason, incomplete_responses=incomplete, tool_calls=list(tools))
    return record


class DescribeResponseTests(unittest.TestCase):
    def test_a_good_turn_is_a_message_with_no_fallback(self) -> None:
        described = describe_response("/api/agent/turn", {}, 200, {"ok": True, "outcome": "answer_now", "reply": "Here you go."})
        self.assertEqual(described["outcome"], "answer_now")
        self.assertFalse(described["fallback_used"])
        self.assertEqual(described["reply"], "Here you go.")

    def test_a_recovered_turn_is_a_fallback_with_the_situation_code(self) -> None:
        described = describe_response("/api/agent/turn", {}, 200, {"ok": True, "recovered": True, "recoveryCode": "assistant_unclear", "composed": True})
        self.assertTrue(described["fallback_used"])
        self.assertEqual(described["fallback_reason"], "assistant_unclear")

    def test_an_assembled_sentence_is_marked_as_the_last_resort(self) -> None:
        described = describe_response("/api/agent/recover", {"situation": {"code": "source_not_connected"}}, 200, {"ok": True, "composed": False, "code": "source_not_connected"})
        self.assertEqual(described["fallback_reason"], "source_not_connected/computed")
        self.assertEqual(described["outcome"], "recovered")

    def test_the_loop_reports_its_own_fallback_and_tool_calls(self) -> None:
        payload = {"ok": True, "reply": "…", "fallbackUsed": True, "fallbackReason": "empty_reply", "toolCalls": [{"name": "read_inbox", "ok": False, "code": "source_not_connected", "ms": 12}]}
        described = describe_response("/api/agent/loop", {}, 200, payload)
        self.assertEqual(described["fallback_reason"], "empty_reply")
        self.assertEqual(described["tool_calls"], [{"name": "read_inbox", "ok": False, "code": "source_not_connected", "ms": 12}])

    def test_a_pending_confirmation_is_its_own_outcome(self) -> None:
        described = describe_response("/api/agent/loop", {}, 200, {"ok": True, "reply": "Shall I?", "pendingConfirmation": {"tool": "disconnect"}})
        self.assertEqual(described["outcome"], "confirmation_asked")

    def test_a_refusal_is_not_a_fallback_but_a_server_error_is(self) -> None:
        refused = describe_response("/api/agent/turn", {}, 402, {"ok": False, "error": "trial_expired"})
        self.assertEqual(refused["outcome"], "refused")
        self.assertFalse(refused["fallback_used"])
        broken = describe_response("/api/agent/turn", {}, 500, {"ok": False, "error": "internal"})
        self.assertEqual(broken["outcome"], "error")
        self.assertEqual(broken["fallback_reason"], "http_500:internal")

    def test_a_lookup_run_is_a_tool_call_with_its_error_code(self) -> None:
        described = describe_response("/api/agent/proposals/run", {"proposalType": "gmail", "mode": "answer"}, 200, {"ok": False, "error": "gmail_not_connected"}, latency_ms=40)
        self.assertEqual(described["tool_call"], {"name": "gmail:answer", "ok": False, "code": "gmail_not_connected", "ms": 40})

    def test_a_composer_that_failed_counts_as_a_fallback(self) -> None:
        described = describe_response("/api/agent/answer/compose", {}, 503, {"ok": False, "error": "answer_unavailable"})
        self.assertTrue(described["fallback_used"])
        self.assertEqual(described["fallback_reason"], "answer_compose_failed:answer_unavailable")

    def test_account_state_names_what_is_connected(self) -> None:
        state = describe_account_state({"whatsapp": {"ready": True}, "gmail": {"platformConnected": True, "connectionStatus": "connected"}, "calendar": {"platformConnected": False}})
        self.assertIn("WhatsApp number is connected", state)
        self.assertIn("Connected sources: Gmail.", state)
        self.assertIn("No mailbox", describe_account_state({}))


class RecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("admin@example.com", is_admin=True)

    def _finish(self, recorder: TurnRecorder, status: int, payload: dict) -> dict:
        with redirect_stdout(io.StringIO()):
            return recorder.finish(status, payload)

    def test_a_turn_row_carries_the_model_call_and_the_reply(self) -> None:
        recorder = TurnRecorder(database=self.database, path="/api/agent/turn", request={"userMessage": "rates?", "channel": "whatsapp", "toolContext": {"whatsapp": {"ready": True}}}, user_id=1)
        recorder.observe(SimpleNamespace(model="m-1", input_tokens=120, output_tokens=30, incomplete_attempts=1, request_payload={"reasoning": {"effort": "medium"}}, output_text='{"reply":"3.7"}'))
        record = self._finish(recorder, 200, {"ok": True, "outcome": "message", "reply": "A dollar is 3.7 shekels."})
        stored = self.database.get_agent_turn(record["turn_id"])
        self.assertEqual(stored["model"], "m-1")
        self.assertEqual(stored["reasoning_effort"], "medium")
        self.assertEqual((stored["input_tokens"], stored["output_tokens"], stored["model_calls"]), (120, 30, 1))
        self.assertEqual(stored["incomplete_responses"], 1)
        self.assertEqual(stored["user_message"], "rates?")
        self.assertEqual(stored["reply"], "A dollar is 3.7 shekels.")
        self.assertEqual(stored["channel"], "whatsapp")
        self.assertIn("WhatsApp number is connected", stored["account_state"])
        self.assertFalse(stored["fallback_used"])
        self.assertEqual(stored["raw_output_on_failure"], "")

    def test_a_failed_turn_keeps_the_raw_model_text(self) -> None:
        recorder = TurnRecorder(database=self.database, path="/api/agent/turn", request={"userMessage": "hi"}, user_id=1)
        recorder.observe(SimpleNamespace(model="m-1", input_tokens=1, output_tokens=1, incomplete_attempts=0, request_payload={}, output_text="not json at all"))
        record = self._finish(recorder, 200, {"ok": True, "recovered": True, "recoveryCode": "assistant_unclear", "composed": True, "reply": "Lost the thread."})
        self.assertTrue(record["fallback_used"])
        self.assertEqual(record["fallback_reason"], "assistant_unclear")
        self.assertEqual(record["raw_output_on_failure"], "not json at all")

    def test_follow_up_calls_land_on_the_same_row(self) -> None:
        first = TurnRecorder(database=self.database, path="/api/agent/loop", request={"userMessage": "emails?", "channel": "whatsapp"}, user_id=1)
        first.observe(SimpleNamespace(model="m-1", input_tokens=100, output_tokens=10, incomplete_attempts=0, request_payload={}, output_text="x"))
        record = self._finish(first, 200, {"ok": True, "reply": "", "outcome": "answer_now", "turnId": "loop-1"})
        self.assertEqual(record["turn_id"], "loop-1")

        run = TurnRecorder(database=self.database, path="/api/agent/proposals/run", request={"turnId": "loop-1", "proposalType": "gmail"}, user_id=1)
        self._finish(run, 200, {"ok": False, "error": "gmail_not_connected"})
        recover = TurnRecorder(database=self.database, path="/api/agent/recover", request={"turnId": "loop-1", "situation": {"code": "source_not_connected"}}, user_id=1)
        recover.observe(SimpleNamespace(model="m-1", input_tokens=50, output_tokens=20, incomplete_attempts=0, request_payload={}, output_text="Connect Gmail first."))
        self._finish(recover, 200, {"ok": True, "composed": True, "code": "source_not_connected", "reply": "Connect Gmail first."})

        stored = self.database.get_agent_turn("loop-1")
        self.assertEqual(stored["outcome"], "recovered")
        self.assertTrue(stored["fallback_used"])
        self.assertEqual(stored["fallback_reason"], "source_not_connected")
        self.assertEqual(stored["tool_calls"][0]["code"], "gmail_not_connected")
        self.assertEqual((stored["input_tokens"], stored["model_calls"]), (150, 2))
        self.assertEqual(stored["reply"], "Connect Gmail first.")
        self.assertEqual(len(self.database.list_agent_turns(since="2000-01-01")), 1)

    def test_a_lookup_with_no_turn_is_recorded_but_not_counted_as_one(self) -> None:
        run = TurnRecorder(database=self.database, path="/api/agent/proposals/run", request={"proposalType": "exchange-rate"}, user_id=1)
        record = self._finish(run, 200, {"ok": True})
        self.assertEqual(record["outcome"], "tool_only")
        window = summarize_window(self.database.list_agent_turns(since="2000-01-01"))
        self.assertEqual((window["turns"], window["toolCalls"]), (0, 1))

    def test_a_crash_is_an_error_row(self) -> None:
        recorder = TurnRecorder(database=self.database, path="/api/agent/turn", request={"userMessage": "hi"}, user_id=1)
        with redirect_stdout(io.StringIO()):
            record = recorder.finish(0, None, crashed=True)
        self.assertEqual(record["outcome"], "error")
        self.assertEqual(record["status_code"], 500)
        self.assertEqual(record["fallback_reason"], "http_500")


class MetricsTests(unittest.TestCase):
    def test_the_three_numbers(self) -> None:
        turns = [
            _turn(),
            _turn(fallback=True, reason="assistant_unclear"),
            _turn(incomplete=1, tools=[{"name": "a", "ok": True, "code": "", "ms": 1}, {"name": "b", "ok": False, "code": "source_not_connected", "ms": 1}]),
            _turn(outcome="tool_only", tools=[{"name": "c", "ok": False, "code": "source_not_connected", "ms": 1}]),
        ]
        window = summarize_window(turns)
        self.assertEqual(window["turns"], 3)
        self.assertAlmostEqual(window["fallbackRate"], 1 / 3)
        self.assertEqual(window["fallbackReasons"], {"assistant_unclear": 1})
        self.assertAlmostEqual(window["incompleteRate"], 1 / 3)
        self.assertEqual((window["toolCalls"], window["toolErrors"]), (3, 2))
        self.assertEqual(window["toolErrorsByCode"], {"source_not_connected": 2})

    def test_day_and_week_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = PortalDatabase(Path(temp_dir) / "portal.db")
            database.save_agent_turn(_turn(created=NOW - timedelta(hours=2)))
            database.save_agent_turn(_turn(fallback=True, reason="x", created=NOW - timedelta(days=3)))
            database.save_agent_turn(_turn(created=NOW - timedelta(days=9)))
            metrics = turn_metrics(database, now=NOW)
        self.assertEqual(metrics["day"]["turns"], 1)
        self.assertEqual(metrics["week"]["turns"], 2)
        self.assertEqual(metrics["week"]["fallbacks"], 1)


class AlertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("admin@example.com", is_admin=True)
        self.database.register_user("client@example.com")
        self.env = mock.patch.dict(os.environ, {"PORTAL_AGENT_FALLBACK_ALERT_MIN_TURNS": "5"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def _fill(self, fallbacks: int, total: int) -> None:
        for index in range(total):
            record = _turn(fallback=index < fallbacks, reason="assistant_unclear" if index < fallbacks else "", created=NOW - timedelta(minutes=index))
            record["turn_id"] = f"t-{index}"
            self.database.save_agent_turn(record)

    def test_below_the_line_or_below_the_floor_stays_quiet(self) -> None:
        self._fill(1, 4)
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(check_fallback_alert(self.database, now=NOW))
        self._fill(0, 60)
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(check_fallback_alert(self.database, now=NOW))
        self.assertEqual(self.database.count_unread_notifications(user_id=1), 0)

    def test_crossing_the_line_tells_every_admin_once_a_day(self) -> None:
        self._fill(2, 20)
        with redirect_stdout(io.StringIO()):
            window = check_fallback_alert(self.database, now=NOW)
            check_fallback_alert(self.database, now=NOW + timedelta(hours=1))
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window["fallbackRate"], 0.1)
        admin_feed = self.database.list_notifications(user_id=1, limit=10)
        self.assertEqual(len(admin_feed), 1)
        self.assertIn("10%", admin_feed[0]["title"])
        self.assertIn("2 of 20 turns", admin_feed[0]["body"])
        self.assertIn("assistant_unclear (2)", admin_feed[0]["body"])
        self.assertEqual(self.database.list_notifications(user_id=2, limit=10), [])


class SamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("admin@example.com", is_admin=True)
        for index in range(6):
            record = _turn(fallback=index == 0, reason="empty_reply" if index == 0 else "", created=NOW - timedelta(days=index % 4))
            record.update(turn_id=f"s-{index}", user_message=f"question {index}", reply="" if index == 5 else f"answer {index}")
            self.database.save_agent_turn(record)

    def test_the_weekly_report_lands_in_the_admin_feed_once(self) -> None:
        def judge(state: str, conversation: list, reply: str) -> dict:
            return {"truthful": 5, "forward": 1 if reply == "answer 1" else 5, "channel": 5, "clean": 5, "honest": 5, "note": "dead end" if reply == "answer 1" else ""}

        config = AgentTurnSamplingConfig(timezone_name="UTC", schedule_weekday=NOW.weekday(), schedule_hour=9, schedule_minute=0, sample_size=20)
        scheduler = AgentTurnSamplingScheduler(self.database, config=config, judge=judge)
        summary = scheduler.run_pending(now=NOW)
        self.assertTrue(summary["ran"])
        self.assertEqual(summary["report"]["sampled"], 6)
        self.assertEqual(summary["report"]["passed"], 4)
        feed = self.database.list_notifications(user_id=1, limit=10)
        self.assertEqual(len(feed), 1)
        self.assertIn("4 of 6 replies scored 3 or better", feed[0]["title"])
        self.assertIn("'question 1'", feed[0]["body"])
        self.assertIn("nothing was sent back", feed[0]["body"])
        self.assertFalse(scheduler.run_pending(now=NOW + timedelta(hours=2))["ran"])

    def test_a_judge_outage_is_reported_not_hidden(self) -> None:
        def judge(state: str, conversation: list, reply: str) -> dict:
            raise OpenAIError("no key")

        config = AgentTurnSamplingConfig(timezone_name="UTC", schedule_weekday=NOW.weekday(), schedule_hour=9, schedule_minute=0)
        scheduler = AgentTurnSamplingScheduler(self.database, config=config, judge=judge)
        summary = scheduler.run_pending(now=NOW)
        self.assertEqual(summary["report"]["unscored"], 5)
        title, body = format_sample_report(summary["report"])
        # Five replies could not be scored; the sixth had no reply at all, which fails without a judge.
        self.assertIn("0 of 1 replies scored 3 or better", title)
        self.assertIn("could not be scored", body)
        self.assertNotIn("passed on every point", body)

    def test_the_slot_is_the_most_recent_scheduled_moment(self) -> None:
        config = AgentTurnSamplingConfig(timezone_name="UTC", schedule_weekday=0, schedule_hour=9, schedule_minute=30)
        scheduler = AgentTurnSamplingScheduler(self.database, config=config, judge=lambda *a: {})
        # 2026-09-04 is a Friday; the slot is Monday the 31st at 09:30.
        self.assertEqual(scheduler.due_slot(NOW).isoformat(), "2026-08-31T09:30:00+00:00")
        monday_early = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(scheduler.due_slot(monday_early).isoformat(), "2026-08-24T09:30:00+00:00")

    def test_judge_scores_are_read_tolerantly(self) -> None:
        scores = parse_scores('Sure: {"truthful": 5, "forward": "4", "channel": 9, "clean": -1, "honest": 5, "note": "fine"} thanks')
        self.assertEqual((scores["forward"], scores["channel"], scores["clean"]), (4, 5, 0))
        self.assertEqual(parse_scores("nothing")["truthful"], 0)


class GatewayObserverTests(unittest.TestCase):
    def test_an_observer_hears_the_result_with_its_incomplete_count(self) -> None:
        incomplete = {"id": "r1", "model": "m", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": [], "usage": {"input_tokens": 1, "output_tokens": 2}}
        complete = {"id": "r2", "model": "m", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}], "usage": {"input_tokens": 1, "output_tokens": 2}}
        seen = []
        gateway = OpenAIGateway(config=OpenAIConfig(api_key="k", default_model="m"))
        with mock.patch("packages.infrastructure.openai_api._json_request", side_effect=[(incomplete, 200), (complete, 200)]):
            with observe_responses(seen.append):
                result = gateway.create_response(OpenAIRequest(tool_name="t", prompt="p", max_output_tokens=100))
        self.assertEqual(result.output_text, "done")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].incomplete_attempts, 1)
        self.assertEqual(seen[0].incomplete_reason, "max_output_tokens")

    def test_observers_are_per_thread(self) -> None:
        seen = []
        complete = {"id": "r2", "model": "m", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "x"}]}], "usage": {"input_tokens": 1, "output_tokens": 2}}
        gateway = OpenAIGateway(config=OpenAIConfig(api_key="k", default_model="m"))

        def other_thread() -> None:
            with mock.patch("packages.infrastructure.openai_api._json_request", return_value=(complete, 200)):
                gateway.create_response(OpenAIRequest(tool_name="t", prompt="p"))

        with observe_responses(seen.append):
            worker = threading.Thread(target=other_thread)
            worker.start()
            worker.join()
        self.assertEqual(seen, [])


class WhatsAppTurnIdTests(unittest.TestCase):
    def test_the_turn_id_from_a_turn_rides_on_the_calls_that_follow(self) -> None:
        chat = WhatsAppAgentChat(database=object(), connection={"userId": 1, "email": "o@example.com", "ownerWaId": "972500000000"}, base_url="http://portal.test", session_token_factory=lambda email: "tok")
        sent: list[dict] = []

        class FakeResponse:
            def __init__(self, body: dict) -> None:
                self.body = json.dumps(body).encode("utf-8")
                self.status = 200

            def read(self) -> bytes:
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

        def fake_urlopen(request, timeout=0):
            payload = json.loads(request.data.decode("utf-8"))
            sent.append({"path": request.full_url.replace("http://portal.test", ""), "payload": payload})
            if request.full_url.endswith("/api/agent/loop"):
                return FakeResponse({"ok": True, "reply": "…", "turnId": "loop-9"})
            return FakeResponse({"ok": True, "reply": "Connect Gmail first."})

        with mock.patch("packages.infrastructure.whatsapp_agent_chat.urllib_request.urlopen", side_effect=fake_urlopen):
            chat._api("POST", "/api/agent/loop", {"userMessage": "emails?"})
            chat._api("POST", "/api/agent/recover", {"situation": {"code": "source_not_connected"}})
            chat._api("POST", "/api/agent/turn", {"userMessage": "again"})
        self.assertNotIn("turnId", sent[0]["payload"])
        self.assertEqual(sent[1]["payload"]["turnId"], "loop-9")
        self.assertNotIn("turnId", sent[2]["payload"])


class ServerRecordingTests(unittest.TestCase):
    """The record is written around the handlers, so a real request must leave a row."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.env = mock.patch.dict(os.environ, {"PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp")}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        root = Path(__file__).resolve().parents[1]
        self.server = create_server("127.0.0.1", 0, root, PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"))
        self.database = self.server.database
        self.database.register_user("admin@example.com", is_admin=True)
        self.database.register_user("client@example.com")
        self.tokens = {}
        for email in ("admin@example.com", "client@example.com"):
            code, _ = self.server.store.issue_challenge(email)
            ok, _, result = self.server.store.verify_code(email, code)
            assert ok and result is not None
            self.tokens[email] = result["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _request(self, method: str, path: str, payload: dict | None, *, email: str) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.tokens[email]}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_a_recovery_reply_leaves_a_fallback_row_and_the_page_shows_it(self) -> None:
        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=OpenAIError("no model")), redirect_stdout(io.StringIO()):
            status, payload = self._request(
                "POST", "/api/agent/recover",
                {"situation": {"code": "source_not_connected", "request": "emails?", "source": "gmail"}, "channel": "whatsapp"},
                email="client@example.com",
            )
        self.assertEqual(status, 200)
        self.assertTrue(payload["turnId"])
        record = self.database.get_agent_turn(payload["turnId"])
        self.assertEqual(record["channel"], "whatsapp")
        self.assertEqual(record["outcome"], "recovered")
        self.assertTrue(record["fallback_used"])
        self.assertEqual(record["fallback_reason"], "source_not_connected/computed")
        self.assertEqual(record["user_id"], 2)
        self.assertEqual(record["reply"], payload["reply"])

        status, page = self._request("GET", "/api/admin/agent-turns?limit=5", None, email="admin@example.com")
        self.assertEqual(status, 200)
        self.assertEqual(page["metrics"]["day"]["turns"], 1)
        self.assertEqual(page["metrics"]["day"]["fallbacks"], 1)
        self.assertEqual(page["recent"][0]["turnId"], payload["turnId"])
        self.assertEqual(page["alert"]["rate"], 0.02)

        status, _ = self._request("GET", "/api/admin/agent-turns", None, email="client@example.com")
        self.assertEqual(status, 403)

        # The house owner sees the turns the same way they see the clients,
        # admin flag or not. The menu offered the page to them; the API must
        # not then turn them away.
        self.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, result = self.server.store.verify_code("owner@example.com", code)
        assert ok and result is not None
        self.tokens["owner@example.com"] = result["token"]
        with mock.patch.dict(os.environ, {"PORTAL_OPPORTUNITIES_OWNER_EMAIL": "owner@example.com"}):
            status, page = self._request("GET", "/api/admin/agent-turns?limit=5", None, email="owner@example.com")
        self.assertEqual(status, 200)
        self.assertEqual(page["recent"][0]["turnId"], payload["turnId"])

    def test_a_turn_row_carries_what_the_model_said(self) -> None:
        turn = {"outcome": "message", "reply": "Hi! I can help with that."}
        result = SimpleNamespace(output_text=json.dumps(turn), model="m-test", input_tokens=11, output_tokens=7, incomplete_attempts=0, request_payload={"reasoning": {"effort": "low"}})

        def fake_call(**kwargs):
            from packages.infrastructure.openai_api import _notify_response_observers

            _notify_response_observers(result)
            return result

        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=fake_call), redirect_stdout(io.StringIO()):
            status, payload = self._request("POST", "/api/agent/turn", {"userMessage": "What can you do?", "channel": "whatsapp"}, email="client@example.com")
        self.assertEqual(status, 200)
        record = self.database.get_agent_turn(payload["turnId"])
        self.assertEqual(record["outcome"], "message")
        self.assertEqual(record["model"], "m-test")
        self.assertEqual(record["reasoning_effort"], "low")
        self.assertEqual((record["input_tokens"], record["output_tokens"]), (11, 7))
        self.assertEqual(record["user_message"], "What can you do?")
        self.assertEqual(record["reply"], "Hi! I can help with that.")
        self.assertFalse(record["fallback_used"])


if __name__ == "__main__":
    unittest.main()
