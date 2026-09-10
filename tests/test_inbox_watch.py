"""The inbox watch's judgement, with no network.

What these prove: mailings, machine senders and the person's own mail are
never put to the model, while a no-reply calendar invitation is; a reply
is read into a fact and put back on the right message; the decision holds
a message for the hold and waives it for anything happening today, and
skips what needs nothing, is unsure, is past, is far off, or is already on
the calendar; quiet hours and the poll interval follow the person's clock;
the alert instruction and fallback carry the facts as written; and the
token cache keeps a token for its hour and drops it on a reconnect.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import inbox_watch as iw

ZONE = ZoneInfo("Asia/Jerusalem")
NOW = datetime(2026, 9, 10, 10, 0, tzinfo=ZONE)
HOLD = timedelta(minutes=10)


def _item(**fields) -> dict:
    base = {"id": "m1", "from": "Dana Levi <dana@client.co.il>", "subject": "Quote for the kitchen", "bodyText": "Can you send the quote by Thursday?", "labels": ["INBOX", "UNREAD"], "bulk": False, "receivedAt": "2026-09-10T07:55:00+00:00"}
    base.update(fields)
    return base


class SkipTests(unittest.TestCase):
    def test_a_plain_letter_is_read(self) -> None:
        self.assertEqual(iw.skip_reason(_item(), owner_addresses=["owner@example.com"]), "")

    def test_mailings_machine_senders_and_own_mail_are_not(self) -> None:
        self.assertEqual(iw.skip_reason(_item(bulk=True)), "bulk_mail")
        self.assertEqual(iw.skip_reason(_item(labels=["INBOX", "CATEGORY_PROMOTIONS"])), "not_inbox_mail")
        self.assertEqual(iw.skip_reason(_item(**{"from": "Owner <owner@example.com>"}), owner_addresses=["owner@example.com"]), "own_mail")
        self.assertEqual(iw.skip_reason(_item(**{"from": "Shop <no-reply@shop.com>"}, subject="Your order shipped", bodyText="Track it here")), "machine_sender")

    def test_a_no_reply_invitation_is_still_read(self) -> None:
        item = _item(**{"from": "Google Calendar <calendar-notification@google.com>"}, subject="Invitation: Interview @ Thu 11 Sep 14:00", bodyText="")
        self.assertEqual(iw.skip_reason(item), "")


class ReadingTests(unittest.TestCase):
    def test_a_reply_is_read_onto_the_right_message_without_ids(self) -> None:
        prompts: list[str] = []

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            return "```json\n" + json.dumps({"reads": [
                {"ref": "1", "kind": "reply_needed", "needsAction": True, "what": "Send Dana the kitchen quote", "who": "Dana Levi", "when": None, "deadline": "2026-09-11", "urgency": "this_week", "confidence": "high"},
                {"ref": "2", "kind": "other", "needsAction": False, "what": "", "who": "", "when": None, "deadline": None, "urgency": "none", "confidence": "high"},
                {"ref": "7", "kind": "meeting", "needsAction": True},
            ]}) + "\n```"

        read = iw.read_new_mail([_item(), _item(id="m2", subject="Newsletter")], ask=ask, now_local="2026-09-10 10:00 (Thursday)", owner_addresses=["owner@example.com"])
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("m1", prompts[0])
        self.assertIn('"now":"2026-09-10 10:00 (Thursday)"', prompts[0])
        self.assertEqual(read[0][iw.READ_KEY]["deadline"], "2026-09-11")
        self.assertEqual(read[0][iw.READ_KEY]["kind"], "reply_needed")
        self.assertFalse(read[1][iw.READ_KEY]["needsAction"])

    def test_a_bad_kind_or_a_bad_date_is_dropped_not_guessed(self) -> None:
        self.assertEqual(iw.normalize_read({"kind": "party", "needsAction": True}), {})
        read = iw.normalize_read({"kind": "meeting", "needsAction": True, "when": "next Thursday", "urgency": "soon"})
        self.assertEqual(read["when"], "")
        self.assertEqual(read["urgency"], "none")
        self.assertEqual(iw.normalize_read({"kind": "meeting", "when": "2026-09-11T14:00"})["when"], "2026-09-11T14:00")

    def test_the_version_is_stable(self) -> None:
        self.assertEqual(iw.read_version(), iw.read_version())
        self.assertEqual(len(iw.read_version()), 16)


class DecisionTests(unittest.TestCase):
    def _decide(self, read: dict, *, received: datetime | None = None, events=()) -> dict:
        return iw.decide(read, received_at=received or NOW - timedelta(minutes=2), now=NOW, zone=ZONE, hold=HOLD, calendar_events=events)

    def test_a_reply_due_this_week_is_held_for_the_hold(self) -> None:
        decision = self._decide({"kind": "reply_needed", "needsAction": True, "deadline": "2026-09-11", "urgency": "this_week", "confidence": "high"})
        self.assertEqual(decision["action"], "notify")
        self.assertFalse(decision["sameDay"])
        self.assertEqual(datetime.fromisoformat(decision["notifyAfter"]).astimezone(ZONE), NOW + timedelta(minutes=8))

    def test_anything_today_skips_the_hold(self) -> None:
        decision = self._decide({"kind": "meeting", "needsAction": True, "when": "2026-09-10T15:00", "urgency": "today", "confidence": "high"})
        self.assertTrue(decision["sameDay"])
        self.assertEqual(datetime.fromisoformat(decision["notifyAfter"]).astimezone(ZONE), NOW - timedelta(minutes=2))

    def test_nothing_to_do_unsure_past_and_far_off_are_skipped(self) -> None:
        self.assertEqual(self._decide({})["reason"], "unread_by_model")
        self.assertEqual(self._decide({"kind": "other", "needsAction": False, "urgency": "today", "confidence": "high"})["reason"], "nothing_to_do")
        self.assertEqual(self._decide({"kind": "meeting", "needsAction": True, "urgency": "today", "confidence": "low"})["reason"], "unsure")
        self.assertEqual(self._decide({"kind": "meeting", "needsAction": True, "when": "2026-09-08T09:00", "urgency": "today", "confidence": "high"})["reason"], "already_past")
        self.assertEqual(self._decide({"kind": "deadline", "needsAction": True, "deadline": "2026-10-30", "urgency": "later", "confidence": "high"})["reason"], "beyond_horizon")
        self.assertEqual(self._decide({"kind": "reply_needed", "needsAction": True, "urgency": "later", "confidence": "high"})["reason"], "not_timed")

    def test_an_untimed_reply_someone_waits_on_now_still_goes(self) -> None:
        decision = self._decide({"kind": "reply_needed", "needsAction": True, "urgency": "today", "confidence": "high"})
        self.assertEqual(decision["action"], "notify")

    def test_a_meeting_already_on_the_calendar_is_not_news(self) -> None:
        read = {"kind": "interview", "needsAction": True, "what": "Interview with Acme at 14:00", "who": "Acme", "when": "2026-09-11T14:00", "urgency": "this_week", "confidence": "high"}
        events = [{"title": "Acme interview", "start": "2026-09-11T14:00:00+03:00"}]
        self.assertEqual(self._decide(read, events=events)["reason"], "on_calendar")
        self.assertEqual(self._decide(read, events=[{"title": "Dentist", "start": "2026-09-11T09:00:00+03:00"}])["action"], "notify")

    def test_quiet_hours_and_the_poll_interval_follow_the_clock(self) -> None:
        night = datetime(2026, 9, 10, 23, 30, tzinfo=ZONE)
        day = datetime(2026, 9, 10, 9, 30, tzinfo=ZONE)
        self.assertTrue(iw.in_quiet_hours(night, start_hour=22, end_hour=7))
        self.assertFalse(iw.in_quiet_hours(day, start_hour=22, end_hour=7))
        self.assertEqual(iw.quiet_hours_end(night, start_hour=22, end_hour=7).isoformat(), "2026-09-11T07:00:00+03:00")
        self.assertEqual(iw.poll_interval_seconds(night, day_seconds=180, night_seconds=900, quiet_start=22, quiet_end=7), 900)
        self.assertEqual(iw.poll_interval_seconds(day, day_seconds=180, night_seconds=900, quiet_start=22, quiet_end=7), 180)


class TellingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = {
            "from": "Dana Levi <dana@client.co.il>", "subject": "Quote for the kitchen",
            "read": {"kind": "reply_needed", "what": "Send Dana the kitchen quote", "who": "Dana Levi", "when": "", "deadline": "2026-09-11T17:00"},
        }

    def test_the_line_carries_who_what_and_when(self) -> None:
        line = iw.describe_alert(self.entry)
        self.assertIn("From Dana Levi: Send Dana the kitchen quote", line)
        self.assertIn("needs an answer by 2026-09-11 at 17:00", line)
        self.assertIn('email subject: "Quote for the kitchen"', line)

    def test_the_instruction_and_fallback_carry_the_facts(self) -> None:
        text = iw.build_alert_instruction([self.entry], hold_minutes=10)
        self.assertIn("An email just arrived", text)
        self.assertIn("in the 10 minutes since", text)
        self.assertIn("1. From Dana Levi", text)
        self.assertIn("do not use any tool", text)
        fallback = iw.build_alert_fallback_text([self.entry])
        self.assertTrue(fallback.startswith("Something in your inbox needs you:"))
        self.assertIn("• From Dana Levi", fallback)
        self.assertIn("A few things", iw.build_alert_fallback_text([self.entry, self.entry]))


class TokenCacheTests(unittest.TestCase):
    def test_a_token_is_kept_for_its_hour_and_dropped_on_reconnect(self) -> None:
        cache = iw.AccessTokenCache(ttl_seconds=3000)
        cache.put("conn-1", fingerprint="fp-a", provider="google_gmail", access_token="tok-1")
        self.assertEqual(cache.get("conn-1", fingerprint="fp-a"), ("google_gmail", "tok-1"))
        self.assertIsNone(cache.get("conn-1", fingerprint="fp-b"))
        cache.put("conn-1", fingerprint="fp-a", provider="google_gmail", access_token="tok-1")
        cache.forget("conn-1")
        self.assertIsNone(cache.get("conn-1", fingerprint="fp-a"))


if __name__ == "__main__":
    unittest.main()
