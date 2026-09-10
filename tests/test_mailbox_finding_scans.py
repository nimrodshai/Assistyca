"""Mailbox scans: when they run, what they keep, and how the person hears.

What these prove: one scan waits per account and a first scan takes over a
waiting morning one; a claim is atomic and an abandoned scan comes back;
findings keep their status across scans and come back new when they
return; the first scan tells one thing and lines up the morning after, the
morning tells the rest and lines up the next morning; a first scan that
found nothing still says so; a scan that fails still lines up tomorrow; a
one-off whose message the model could not write goes out as the plain
sentence; the endpoint reads the mailbox once and the ledger after; and
the chat can list and drop findings.
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
from packages.infrastructure.mailbox_finding_scans import FindingScanConfig
from packages.infrastructure.mailbox_finding_scans import FindingScanScheduler
from packages.infrastructure.mailbox_finding_scans import next_scan_run_at
from packages.infrastructure.mailbox_findings import NOTHING_FOUND_TEXT
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

JERUSALEM = "Asia/Jerusalem"
ZONE = ZoneInfo(JERUSALEM)
OWNER_WA_ID = "972507322341"


def _finding(key: str, detector: str = "unpaid_invoice", score: float = 90, **extra) -> dict:
    base = {
        "key": key, "detector": detector, "title": key, "counterparty": "Acme Ltd", "amount": 1200.0, "currency": "ILS",
        "date": "2026-07-20", "dueOn": "", "reference": "INV-17", "ageDays": 50, "sources": [{"mailbox": "m", "messageId": "x", "subject": "Invoice 17"}],
        "score": score,
    }
    base.update(extra)
    return base


class ScanQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_one_scan_waits_per_account_and_a_first_scan_takes_over(self) -> None:
        soon = datetime.now(timezone.utc) + timedelta(hours=10)
        daily = self.database.schedule_finding_scan(user_id=self.user_id, kind="daily", run_at=soon, timezone_name=JERUSALEM)
        again = self.database.schedule_finding_scan(user_id=self.user_id, kind="daily", run_at=soon + timedelta(days=1))
        self.assertEqual(again["id"], daily["id"])
        first = self.database.schedule_finding_scan(user_id=self.user_id, kind="first", run_at=datetime.now(timezone.utc))
        self.assertEqual(first["id"], daily["id"])
        self.assertEqual(first["kind"], "first")
        self.assertEqual(len(self.database.list_due_finding_scans(limit=5)), 1)

    def test_a_claim_is_atomic_and_an_abandoned_scan_comes_back(self) -> None:
        scan = self.database.schedule_finding_scan(user_id=self.user_id, kind="first", run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        claimed = self.database.claim_finding_scan(scan["id"])
        self.assertEqual(claimed["status"], "running")
        self.assertIsNone(self.database.claim_finding_scan(scan["id"]))
        later = datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertEqual(self.database.requeue_stale_finding_scans(now=later), 1)
        self.assertEqual(self.database.list_due_finding_scans(now=later)[0]["status"], "pending")
        self.database.finish_finding_scan(scan_id=scan["id"], status="done", summary={"findings": 2})
        self.assertEqual(self.database.list_finding_scans_for_user(user_id=self.user_id)[0]["summary"], {"findings": 2})

    def test_findings_keep_their_status_and_come_back_when_they_return(self) -> None:
        new = self.database.upsert_account_findings(user_id=self.user_id, findings=[_finding("a"), _finding("b", score=60)])
        self.assertEqual(new, ["a", "b"])
        self.assertEqual(self.database.mark_account_findings_told(user_id=self.user_id, keys=["a"]), 1)
        self.assertEqual(self.database.upsert_account_findings(user_id=self.user_id, findings=[_finding("a", amount=1300.0), _finding("b")]), [])
        listed = {record["key"]: record for record in self.database.list_account_findings(user_id=self.user_id)}
        self.assertEqual(listed["a"]["status"], "told")
        self.assertEqual(listed["a"]["amount"], 1300.0)
        self.assertEqual(listed["b"]["status"], "new")
        # The payment arrived: a no longer derives.
        self.assertEqual(self.database.resolve_missing_account_findings(user_id=self.user_id, active_keys=["b"]), 1)
        self.assertEqual([record["key"] for record in self.database.list_account_findings(user_id=self.user_id)], ["b"])
        # It comes back: told once already, but new again to the person.
        self.assertEqual(self.database.upsert_account_findings(user_id=self.user_id, findings=[_finding("a")]), ["a"])
        record = self.database.list_account_findings(user_id=self.user_id, statuses=("new",))[0]
        self.assertEqual(record["key"], "a")
        self.assertTrue(self.database.set_account_finding_status(user_id=self.user_id, finding_id=record["id"], status="dismissed"))
        self.assertEqual(self.database.resolve_missing_account_findings(user_id=self.user_id, active_keys=[]), 1)
        self.assertEqual(self.database.list_account_findings(user_id=self.user_id, statuses=("dismissed",))[0]["key"], "a")

    def test_facts_are_remembered_per_message_and_read_back_by_window(self) -> None:
        entries = [
            {"mailbox": "m", "messageId": "1", "factsVersion": "v1", "messageDate": "2026-07-20", "kind": "invoice_sent", "amount": 1200, "currency": "ILS", "counterparty": "Acme"},
            {"mailbox": "m", "messageId": "2", "factsVersion": "v1", "messageDate": "2025-01-01", "kind": "charge", "amount": 5, "currency": "ILS"},
            {"mailbox": "m", "messageId": "3", "factsVersion": "v1", "messageDate": "2026-08-01", "kind": "none"},
        ]
        self.assertEqual(self.database.save_mail_facts(user_id=self.user_id, entries=entries), 3)
        known = self.database.get_mail_facts(user_id=self.user_id, mailbox="m", message_ids=["1", "3", "9"], facts_version="v1")
        self.assertEqual(set(known), {"1", "3"})
        self.assertEqual(known["1"]["facts"]["amount"], 1200)
        self.assertEqual(self.database.get_mail_facts(user_id=self.user_id, mailbox="m", message_ids=["1"], facts_version="v2"), {})
        facts = self.database.list_mail_facts(user_id=self.user_id, since="2026-01-01", facts_version="v1")
        self.assertEqual([fact["messageId"] for fact in facts], ["1"])
        self.assertEqual(facts[0]["counterparty"], "Acme")


class ScanScheduleMathTests(unittest.TestCase):
    def test_the_next_morning_is_on_the_persons_clock(self) -> None:
        after = datetime(2026, 9, 8, 9, 30, tzinfo=ZONE)
        self.assertEqual(next_scan_run_at(hour=8, timezone_name=JERUSALEM, after=after).astimezone(ZONE).isoformat(), "2026-09-09T08:00:00+03:00")
        before = datetime(2026, 9, 8, 6, 30, tzinfo=ZONE)
        self.assertEqual(next_scan_run_at(hour=8, timezone_name=JERUSALEM, after=before).astimezone(ZONE).isoformat(), "2026-09-08T08:00:00+03:00")

    def test_the_morning_after_connecting_is_never_minutes_away(self) -> None:
        early = datetime(2026, 9, 8, 7, 50, tzinfo=ZONE)
        run_at = next_scan_run_at(hour=8, timezone_name=JERUSALEM, after=early, min_gap=timedelta(hours=8))
        self.assertEqual(run_at.astimezone(ZONE).isoformat(), "2026-09-09T08:00:00+03:00")


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        self.config = FindingScanConfig(hour=8, poll_seconds=60, first_delay_minutes=2)
        self.scans: list[tuple[dict, dict]] = []

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _scheduler(self, result: dict | Exception) -> FindingScanScheduler:
        def scan(row: dict, account: dict) -> dict:
            self.scans.append((row, account))
            if isinstance(result, Exception):
                raise result
            # The endpoint stores findings; here the test does, so the
            # scheduler reads statuses the way it would in the server.
            findings = result.get("findings") or []
            self.database.upsert_account_findings(user_id=self.user_id, findings=findings)
            stored = self.database.list_account_findings(user_id=self.user_id)
            return {**result, "findings": stored}

        return FindingScanScheduler(self.database, config=self.config, scan=scan)

    def _queued(self) -> list[dict]:
        return [action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=20) if action.get("actionType") == "run_task"]

    def test_the_first_scan_tells_one_thing_and_lines_up_the_morning_after(self) -> None:
        now = datetime(2026, 9, 8, 12, 0, tzinfo=ZONE)
        self.database.schedule_finding_scan(user_id=self.user_id, kind="first", run_at=now - timedelta(minutes=1), timezone_name=JERUSALEM)
        scheduler = self._scheduler({"ok": True, "mailboxes": 1, "findings": [_finding("a"), _finding("b", detector="price_rise", score=55, previousAmount=49.9, amount=59.9, risePercent=20, chargeCount=4)], "newKeys": ["a", "b"], "subscriptions": {}})

        summary = scheduler.run_pending(now=now)

        self.assertEqual((summary["processed"], summary["done"], summary["failed"]), (1, 1, 0))
        self.assertEqual(self.scans[0][1]["timezone"], JERUSALEM)
        self.assertEqual(self.scans[0][1]["email"], "owner@example.com")
        queued = self._queued()
        self.assertEqual(len(queued), 1)
        payload = queued[0]["payload"]
        self.assertEqual(queued[0]["channel"], "whatsapp")
        self.assertTrue(payload["oneOff"])
        self.assertEqual(payload["findingKeys"], ["a"])
        self.assertIn("1,200 ILS", payload["instruction"])
        self.assertIn("There are 1 more", payload["instruction"])
        self.assertNotIn("Netflix", payload["instruction"])
        self.assertIn("1,200 ILS", payload["fallbackText"])
        statuses = {record["key"]: record["status"] for record in self.database.list_account_findings(user_id=self.user_id)}
        self.assertEqual(statuses, {"a": "told", "b": "new"})
        following = self.database.list_due_finding_scans(now=now + timedelta(days=2))
        self.assertEqual(len(following), 1)
        self.assertEqual(following[0]["kind"], "digest")
        self.assertEqual(datetime.fromisoformat(following[0]["runAt"]).astimezone(ZONE).isoformat(), "2026-09-09T08:00:00+03:00")

        # The morning after: the rest goes, and the next morning is lined up.
        morning = datetime(2026, 9, 9, 8, 0, 30, tzinfo=ZONE)
        scheduler = self._scheduler({"ok": True, "mailboxes": 1, "findings": [_finding("a"), _finding("b", detector="price_rise", score=55, previousAmount=49.9, amount=59.9, risePercent=20, chargeCount=4)], "newKeys": [], "subscriptions": {"ILS": {"count": 1, "latestTotal": 59.9, "vendors": []}}})
        summary = scheduler.run_pending(now=morning)
        self.assertEqual(summary["done"], 1)
        queued = self._queued()
        self.assertEqual(len(queued), 2)
        digest = next(action for action in queued if action["payload"]["scanKind"] == "digest")
        self.assertEqual(digest["payload"]["findingKeys"], ["b"])
        self.assertIn("RECURRING CHARGES", digest["payload"]["instruction"])
        self.assertNotIn("There are", digest["payload"]["instruction"])
        following = self.database.list_due_finding_scans(now=morning + timedelta(days=2))
        self.assertEqual(following[0]["kind"], "daily")
        self.assertEqual(datetime.fromisoformat(following[0]["runAt"]).astimezone(ZONE).isoformat(), "2026-09-10T08:00:00+03:00")

    def test_a_first_scan_with_nothing_still_says_so_and_a_morning_with_nothing_stays_quiet(self) -> None:
        now = datetime(2026, 9, 8, 12, 0, tzinfo=ZONE)
        self.database.schedule_finding_scan(user_id=self.user_id, kind="first", run_at=now, timezone_name=JERUSALEM)
        self._scheduler({"ok": True, "mailboxes": 1, "findings": [], "newKeys": []}).run_pending(now=now)
        queued = self._queued()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["payload"]["fallbackText"], NOTHING_FOUND_TEXT)
        self.assertEqual(queued[0]["payload"]["findingKeys"], [])

        morning = datetime(2026, 9, 9, 8, 1, tzinfo=ZONE)
        self._scheduler({"ok": True, "mailboxes": 1, "findings": [], "newKeys": []}).run_pending(now=morning)
        self.assertEqual(len(self._queued()), 1)

    def test_a_scan_that_fails_is_recorded_and_tomorrow_is_still_lined_up(self) -> None:
        now = datetime(2026, 9, 8, 12, 0, tzinfo=ZONE)
        scan = self.database.schedule_finding_scan(user_id=self.user_id, kind="first", run_at=now, timezone_name=JERUSALEM)
        summary = self._scheduler(RuntimeError("Gmail refused")).run_pending(now=now)
        self.assertEqual(summary["failed"], 1)
        rows = self.database.list_finding_scans_for_user(user_id=self.user_id, limit=5)
        failed = next(row for row in rows if row["id"] == scan["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Gmail refused", failed["lastError"])
        pending = [row for row in rows if row["status"] == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["kind"], "daily")
        self.assertEqual(self._queued(), [])

    def test_a_one_off_whose_message_the_model_could_not_write_goes_out_plain(self) -> None:
        action = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1), timezone_name=JERUSALEM,
            payload={"title": "What I found", "instruction": "tell them", "fallbackText": "Invoice INV-17: no payment found.", "oneOff": True},
        )

        def runner(_action: dict) -> str:
            raise RuntimeError("the loop is down")

        scheduler = ScheduledActionScheduler(self.database, config=ScheduledActionConfig(), task_runner=runner)
        with mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", return_value="wamid.plain") as send:
            summary = scheduler.run_pending()
        self.assertEqual((summary["sent"], summary["failed"]), (1, 0))
        self.assertEqual(send.call_args.kwargs["message_text"], "Invoice INV-17: no payment found.")
        stored = next(row for row in self.database.list_scheduled_actions_for_user(self.user_id, limit=5) if row["id"] == action["id"])
        self.assertEqual(stored["status"], "sent")
        self.assertIn("the loop is down", stored["payload"]["taskRunnerError"])


class FakeMailbox:
    """A reader that lists the same messages every time and honours the ledger."""

    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.runs: list[dict] = []

    def run(self, access_token: str, *, query, max_results: int, include_body: bool = False, known=None, **_) -> dict:
        ids = [item["id"] for item in self.items]
        remembered = known(ids) if known is not None else {}
        out = []
        fetched = 0
        for item in self.items:
            cached = remembered.get(item["id"])
            if cached:
                out.append({**cached, "id": item["id"]})
                continue
            fetched += 1
            out.append(dict(item))
        self.runs.append({"fetched": fetched, "fromLedger": len(out) - fetched, "query": query})
        return {"ok": True, "items": out, "messageCount": len(out)}


class ScanEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="findings-test-secret"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, error, result = self.server.store.verify_code("owner@example.com", code)
        self.assertTrue(ok, error)
        self.session_token = str((result or {}).get("token") or "")
        self.mailbox = FakeMailbox([
            {"id": "g1", "from": "Green Invoice <no-reply@greeninvoice.co.il>", "subject": "Invoice 17 to Acme Ltd", "date": "Mon, 20 Jul 2026 10:00:00 +0300", "bodyText": "Invoice 17: 1,200 ILS"},
            {"id": "g2", "from": "Netflix", "subject": "Your receipt", "date": "Tue, 1 Sep 2026 10:00:00 +0300", "bodyText": "49.90 ILS monthly plan"},
            {"id": "g3", "from": "Shop", "subject": "Sale!", "date": "Tue, 1 Sep 2026 11:00:00 +0300", "bodyText": "50% off"},
        ])
        self.asks: list[str] = []

        def readers(_handler, session):
            records = [{"id": "conn-1", "accountAddress": "owner@example.com"}]
            return records, (lambda record: "owner@example.com"), (lambda record: (self.mailbox, "token"))

        def prompt_ask(_handler, **kwargs):
            def ask(prompt: str) -> str:
                self.asks.append(prompt)
                facts = []
                for candidate in json.loads(prompt.split("CONTEXT\n", 1)[1])["messages"]:
                    subject = candidate.get("subject", "")
                    if "Invoice 17" in subject:
                        facts.append({"ref": candidate["ref"], "kind": "invoice_sent", "counterparty": "Acme Ltd", "amount": 1200, "currency": "ILS", "documentDate": "2026-07-20", "reference": "17"})
                    elif "receipt" in subject:
                        facts.append({"ref": candidate["ref"], "kind": "charge", "counterparty": "Netflix", "amount": 49.9, "currency": "ILS", "recurring": True})
                    else:
                        facts.append({"ref": candidate["ref"], "kind": "none"})
                return json.dumps({"facts": facts})
            return ask

        self.patches = [
            mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._mailbox_readers", autospec=True, side_effect=readers),
            mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._receipt_prompt_ask", autospec=True, side_effect=prompt_ask),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self.patches:
            patcher.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.session_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return int(exc.code), json.loads(exc.read().decode("utf-8") or "{}")

    def test_the_endpoint_reads_once_and_the_ledger_after(self) -> None:
        status, first = self._post("/api/findings/scan", {"kind": "first", "timezone": JERUSALEM})
        self.assertEqual(status, 200, first)
        self.assertTrue(first["ok"])
        self.assertEqual(first["mailboxes"], 1)
        self.assertEqual(first["read"], {"fromLedger": 0, "fetched": 3, "withFacts": 3})
        self.assertEqual(len(self.asks), 1)
        self.assertNotIn("g1", self.asks[0])
        self.assertEqual(self.mailbox.runs[0]["query"].newer_than_days, 365)
        self.assertEqual([finding["detector"] for finding in first["findings"]], ["unpaid_invoice"])
        self.assertEqual(first["findings"][0]["status"], "new")
        self.assertEqual(first["newKeys"], ["unpaid_invoice:owner@example.com:g1"])
        self.assertEqual(self.database.count_mail_facts(user_id=self.user_id), 3)

        status, daily = self._post("/api/findings/scan", {"kind": "daily", "timezone": JERUSALEM})
        self.assertEqual(status, 200, daily)
        self.assertEqual(daily["read"], {"fromLedger": 3, "fetched": 0, "withFacts": 0})
        self.assertEqual(len(self.asks), 1)
        self.assertEqual(self.mailbox.runs[1]["query"].newer_than_days, 45)
        self.assertEqual(daily["newKeys"], [])
        self.assertEqual(len(daily["findings"]), 1)

    def test_the_chat_lists_and_drops_findings(self) -> None:
        self._post("/api/findings/scan", {"kind": "first", "timezone": JERUSALEM})

        def call(name: str, call_id: str, **args) -> dict:
            return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}

        def round_(*items: dict, reply: str = "") -> SimpleNamespace:
            outputs = list(items)
            text = ""
            if reply:
                text = json.dumps({"reply": reply, "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None})
                outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
            return SimpleNamespace(output_text=text, raw_response={"output": outputs}, input_tokens=1, output_tokens=1)

        inputs: list[list[dict]] = []
        rounds = [
            round_(call("show_findings", "c1")),
            round_(call("dismiss_finding", "c2", id=1)),
            round_(reply="Dropped it."),
        ]

        def model(input_items: list[dict], tools: list[dict]) -> SimpleNamespace:
            inputs.append(list(input_items))
            return rounds.pop(0)

        context = LoopContext(
            api=lambda *args, **kwargs: ({"ok": True}, 200), database=self.database, email="owner@example.com",
            user_id=self.user_id, timezone_name=JERUSALEM, tool_context={"gmail": {"platformConnected": True, "connectionStatus": "connected"}},
            channel="whatsapp", sender_wa_id=OWNER_WA_ID,
        )
        result = run_agent_loop(context=context, call_model=model, user_message="That Acme invoice was paid in cash, drop it", conversation=[], today="2026-09-08")

        outputs = [json.loads(item["output"]) for item in inputs[-1] if item.get("type") == "function_call_output"]
        listed, dropped = outputs[0], outputs[1]
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["findings"][0]["kind"], "unpaid_invoice")
        self.assertIn("1,200 ILS", listed["findings"][0]["summary"])
        self.assertEqual(listed["findings"][0]["emails"], ["Invoice 17 to Acme Ltd"])
        self.assertEqual(dropped["dismissed"], 1)
        self.assertEqual(result.reply, "Dropped it.")
        self.assertEqual(self.database.list_account_findings(user_id=self.user_id), [])
        self.assertEqual(self.database.list_account_findings(user_id=self.user_id, statuses=("dismissed",))[0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
