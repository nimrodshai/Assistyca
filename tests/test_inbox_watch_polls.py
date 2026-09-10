"""The inbox watch end to end: the queue of accounts, the poll, the hold.

What these prove: an account with a connected mailbox is polled and comes
back at the day or night interval, a failing one backs off, an expired
trial is left alone; the first poll only sets the cursor; a later poll
reads only what the change check reports, skips a mailing without the
model, puts the letter to the model once, holds it, and after the hold
tells the person unless they opened it themselves; the alert goes out as
a one-off action with the facts and a plain fallback; and a message is
never judged twice.
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
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.inbox_watch_polls import InboxWatchConfig
from packages.infrastructure.inbox_watch_polls import InboxWatchScheduler
from packages.infrastructure.inbox_watch_polls import TrialOver
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase

JERUSALEM = "Asia/Jerusalem"
ZONE = ZoneInfo(JERUSALEM)
OWNER_WA_ID = "972507322341"


def _connect_mailbox(database: PortalDatabase, email: str) -> None:
    database.save_platform_connection(
        email, platform="email", provider="google_gmail", auth_type="oauth", secret_ciphertext="cipher",
        secret_hint="Google OAuth", key_version="1", secret_fingerprint="fp-1", account_address=email,
        metadata={"provider": "google_gmail"}, connection_status="connected",
    )


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        _connect_mailbox(self.database, "owner@example.com")
        self.database.register_user("nomail@example.com")
        self.config = InboxWatchConfig(day_poll_seconds=180, night_poll_seconds=900, quiet_start_hour=22, quiet_end_hour=7)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _scheduler(self, outcome) -> InboxWatchScheduler:
        def poll(account: dict, timezone_name: str) -> dict:
            self.polls.append((account, timezone_name))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        self.polls: list = []
        return InboxWatchScheduler(self.database, config=self.config, poll=poll)

    def test_only_accounts_with_a_mailbox_are_polled_and_come_back_at_the_day_interval(self) -> None:
        now = datetime(2026, 9, 10, 10, 0, tzinfo=ZONE)
        scheduler = self._scheduler({"ok": True, "new": 0, "notified": 0})
        summary = scheduler.run_pending(now=now)
        self.assertEqual((summary["due"], summary["polled"]), (1, 1))
        self.assertEqual(self.polls[0][0]["email"], "owner@example.com")
        self.assertEqual(self.polls[0][1], JERUSALEM)
        account = self.database.get_inbox_watch_account(user_id=self.user_id)
        self.assertEqual(datetime.fromisoformat(account["nextPollAt"]), (now + timedelta(seconds=180)).astimezone(timezone.utc))
        # Not due again yet.
        self.assertEqual(scheduler.run_pending(now=now + timedelta(seconds=60))["due"], 0)
        self.assertEqual(scheduler.run_pending(now=now + timedelta(seconds=181))["polled"], 1)

    def test_at_night_the_interval_is_longer(self) -> None:
        night = datetime(2026, 9, 10, 23, 30, tzinfo=ZONE)
        self._scheduler({"ok": True}).run_pending(now=night)
        account = self.database.get_inbox_watch_account(user_id=self.user_id)
        self.assertEqual(datetime.fromisoformat(account["nextPollAt"]), (night + timedelta(seconds=900)).astimezone(timezone.utc))

    def test_a_failing_account_backs_off_and_an_ended_trial_is_left_alone(self) -> None:
        now = datetime(2026, 9, 10, 10, 0, tzinfo=ZONE)
        summary = self._scheduler(RuntimeError("Gmail refused")).run_pending(now=now)
        self.assertEqual(summary["failed"], 1)
        account = self.database.get_inbox_watch_account(user_id=self.user_id)
        self.assertEqual(account["failures"], 1)
        self.assertIn("Gmail refused", account["lastError"])
        self.assertEqual(datetime.fromisoformat(account["nextPollAt"]), (now + timedelta(seconds=360)).astimezone(timezone.utc))
        later = now + timedelta(seconds=400)
        self._scheduler(RuntimeError("Gmail refused")).run_pending(now=later)
        self.assertEqual(self.database.get_inbox_watch_account(user_id=self.user_id)["failures"], 2)
        self.assertEqual(datetime.fromisoformat(self.database.get_inbox_watch_account(user_id=self.user_id)["nextPollAt"]), (later + timedelta(seconds=720)).astimezone(timezone.utc))
        paused_at = later + timedelta(seconds=800)
        summary = self._scheduler(TrialOver("trial_expired")).run_pending(now=paused_at)
        self.assertEqual(summary["paused"], 1)
        account = self.database.get_inbox_watch_account(user_id=self.user_id)
        self.assertEqual(account["failures"], 0)
        self.assertEqual(datetime.fromisoformat(account["nextPollAt"]), (paused_at + timedelta(hours=12)).astimezone(timezone.utc))


class FakeMailbox:
    """A reader that reports whatever changes the test lines up."""

    def __init__(self) -> None:
        self.cursor = "h-1"
        self.changes: list[str] = []
        self.messages: dict[str, dict] = {}
        self.reset_next = False
        self.calls: list[str] = []

    def read_change_cursor(self, access_token: str) -> str:
        self.calls.append("cursor")
        return self.cursor

    def list_changes(self, access_token: str, *, cursor: str) -> dict:
        self.calls.append(f"changes:{cursor}")
        if self.reset_next:
            self.reset_next = False
            return {"messageIds": [], "cursor": "", "reset": True}
        ids, self.changes = list(self.changes), []
        self.cursor = f"h-{int(self.cursor.split('-')[1]) + 1}"
        return {"messageIds": ids, "cursor": self.cursor, "reset": False}

    def fetch_message(self, access_token: str, message_id: str) -> dict | None:
        self.calls.append(f"fetch:{message_id}")
        message = self.messages.get(message_id)
        return dict(message) if message else None

    def is_unread(self, access_token: str, message_id: str) -> bool | None:
        self.calls.append(f"unread:{message_id}")
        message = self.messages.get(message_id)
        return None if message is None else bool(message.get("unread"))


class PollEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="inbox-test-secret"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.save_whatsapp_connection("owner@example.com", owner_wa_id=OWNER_WA_ID, connection_status="connected")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, error, result = self.server.store.verify_code("owner@example.com", code)
        self.assertTrue(ok, error)
        self.session_token = str((result or {}).get("token") or "")
        self.mailbox = FakeMailbox()
        self.asks: list[str] = []
        self.reads: dict[str, dict] = {}

        def readers(_handler, session, *, token_cache=None):
            records = [{"id": "conn-1", "accountAddress": "owner@example.com", "secretFingerprint": "fp-1"}]
            return records, (lambda record: "owner@example.com"), (lambda record: (self.mailbox, "token"))

        def prompt_ask(_handler, **kwargs):
            def ask(prompt: str) -> str:
                self.asks.append(prompt)
                reads = []
                for candidate in json.loads(prompt.split("CONTEXT\n", 1)[1])["messages"]:
                    reads.append({"ref": candidate["ref"], **self.reads.get(candidate.get("subject", ""), {"kind": "other", "needsAction": False, "urgency": "none", "confidence": "high"})})
                return json.dumps({"reads": reads})
            return ask

        self.patches = [
            mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._mailbox_readers", autospec=True, side_effect=readers),
            mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._receipt_prompt_ask", autospec=True, side_effect=prompt_ask),
            mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._upcoming_calendar_events", autospec=True, return_value=[]),
            mock.patch.dict("os.environ", {"PORTAL_INBOX_WATCH_HOLD_MINUTES": "10", "PORTAL_INBOX_WATCH_QUIET_START_HOUR": "22", "PORTAL_INBOX_WATCH_QUIET_END_HOUR": "7"}),
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

    def _poll(self) -> dict:
        request = urllib_request.Request(
            f"{self.base_url}/api/inbox-watch/poll", data=json.dumps({"timezone": JERUSALEM}).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.session_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                self.assertEqual(response.status, 200)
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            self.fail(f"{exc.code}: {exc.read().decode('utf-8')}")

    def _alerts(self) -> list[dict]:
        return [action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=20) if (action.get("payload") or {}).get("source") == "inbox_watch"]

    def test_the_first_poll_only_sets_the_cursor(self) -> None:
        result = self._poll()
        self.assertEqual(result["started"], 1)
        self.assertEqual(self.mailbox.calls, ["cursor"])
        self.assertEqual(self.database.get_inbox_watch_cursor(user_id=self.user_id, connection_id="conn-1")["cursor"], "h-1")

    def test_a_letter_is_read_once_held_and_then_told_unless_opened(self) -> None:
        self._poll()
        received = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.mailbox.messages = {
            "m-letter": {"id": "m-letter", "threadId": "t1", "from": "Dana Levi <dana@client.co.il>", "subject": "Quote for the kitchen", "bodyText": "Can you send the quote by tomorrow?", "labels": ["INBOX", "UNREAD"], "unread": True, "bulk": False, "receivedAt": received},
            "m-news": {"id": "m-news", "threadId": "t2", "from": "Shop <news@shop.com>", "subject": "Weekly deals", "bodyText": "50% off", "labels": ["INBOX", "UNREAD"], "unread": True, "bulk": True, "receivedAt": received},
        }
        tomorrow = (datetime.now(ZONE) + timedelta(days=1)).strftime("%Y-%m-%d")
        self.reads["Quote for the kitchen"] = {"kind": "reply_needed", "needsAction": True, "what": "Send Dana the kitchen quote", "who": "Dana Levi", "when": None, "deadline": tomorrow, "urgency": "this_week", "confidence": "high"}
        self.mailbox.changes = ["m-letter", "m-news"]

        result = self._poll()
        self.assertEqual((result["new"], result["read"], result["held"], result["skipped"], result["notified"]), (2, 1, 1, 1, 0))
        self.assertEqual(len(self.asks), 1)
        self.assertNotIn("m-letter", self.asks[0])
        self.assertIn("Quote for the kitchen", self.asks[0])
        self.assertNotIn("Weekly deals", self.asks[0])
        held = self.database.list_held_inbox_watch_messages(user_id=self.user_id)
        self.assertEqual([row["messageId"] for row in held], ["m-letter"])
        self.assertEqual(self.database.get_inbox_watch_cursor(user_id=self.user_id, connection_id="conn-1")["cursor"], "h-2")

        # The same change reported again is not read again; the hold has not run out.
        self.mailbox.changes = ["m-letter"]
        result = self._poll()
        self.assertEqual((result["new"], result["read"], result["notified"]), (0, 0, 0))
        self.assertEqual(len(self.asks), 1)
        self.assertEqual(self._alerts(), [])

        # The hold runs out and the person has not opened it: one alert, with the facts.
        self.database.update_inbox_watch_message(user_id=self.user_id, row_id=int(held[0]["id"]), status="held", notify_after=datetime.now(timezone.utc) - timedelta(seconds=1))
        with mock.patch("packages.infrastructure.inbox_watch.in_quiet_hours", return_value=False):
            result = self._poll()
        self.assertEqual(result["notified"], 1)
        self.assertIn("unread:m-letter", self.mailbox.calls)
        alerts = self._alerts()
        self.assertEqual(len(alerts), 1)
        payload = alerts[0]["payload"]
        self.assertEqual(alerts[0]["actionType"], "run_task")
        self.assertEqual(alerts[0]["channel"], "whatsapp")
        self.assertTrue(payload["oneOff"])
        self.assertIn("From Dana Levi: Send Dana the kitchen quote", payload["instruction"])
        self.assertIn(f"needs an answer by {tomorrow}", payload["fallbackText"])
        self.assertEqual(payload["messageIds"], ["m-letter"])
        self.assertEqual(self.database.list_inbox_watch_messages(user_id=self.user_id, statuses=("notified",))[0]["messageId"], "m-letter")
        self.assertEqual(self.database.list_held_inbox_watch_messages(user_id=self.user_id), [])

    def test_a_message_the_person_opened_is_let_go_quietly(self) -> None:
        self._poll()
        received = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.mailbox.messages = {"m-1": {"id": "m-1", "threadId": "t1", "from": "Dana <dana@client.co.il>", "subject": "Quote", "bodyText": "?", "labels": ["INBOX", "UNREAD"], "unread": True, "bulk": False, "receivedAt": received}}
        self.reads["Quote"] = {"kind": "reply_needed", "needsAction": True, "what": "Send the quote", "who": "Dana", "when": None, "deadline": None, "urgency": "today", "confidence": "high"}
        self.mailbox.changes = ["m-1"]
        self.mailbox.messages["m-1"]["unread"] = False
        with mock.patch("packages.infrastructure.inbox_watch.in_quiet_hours", return_value=False):
            result = self._poll()
        # Same day: no hold, so it was checked on this very poll, and it had been opened.
        self.assertEqual((result["held"], result["released"], result["notified"]), (1, 1, 0))
        self.assertEqual(self.database.list_inbox_watch_messages(user_id=self.user_id, statuses=("skipped",))[0]["reason"], "read_by_person")
        self.assertEqual(self._alerts(), [])

    def test_in_quiet_hours_an_alert_waits_for_the_morning(self) -> None:
        self._poll()
        received = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.mailbox.messages = {"m-1": {"id": "m-1", "threadId": "t1", "from": "Dana <dana@client.co.il>", "subject": "Quote", "bodyText": "?", "labels": ["INBOX", "UNREAD"], "unread": True, "bulk": False, "receivedAt": received}}
        self.reads["Quote"] = {"kind": "reply_needed", "needsAction": True, "what": "Send the quote", "who": "Dana", "when": None, "deadline": None, "urgency": "today", "confidence": "high"}
        self.mailbox.changes = ["m-1"]
        with mock.patch("packages.infrastructure.inbox_watch.in_quiet_hours", return_value=True):
            result = self._poll()
        self.assertEqual((result["deferred"], result["notified"]), (1, 0))
        held = self.database.list_held_inbox_watch_messages(user_id=self.user_id)
        self.assertEqual(held[0]["reason"], "quiet_hours")
        self.assertGreater(datetime.fromisoformat(held[0]["notifyAfter"]), datetime.now(timezone.utc))

    def test_a_lost_cursor_starts_again_from_now(self) -> None:
        self._poll()
        self.mailbox.reset_next = True
        self.mailbox.cursor = "h-9"
        result = self._poll()
        self.assertEqual(result["new"], 0)
        stored = self.database.get_inbox_watch_cursor(user_id=self.user_id, connection_id="conn-1")
        self.assertEqual(stored["cursor"], "h-9")
        self.assertIn("started again", stored["lastError"])


if __name__ == "__main__":
    unittest.main()
