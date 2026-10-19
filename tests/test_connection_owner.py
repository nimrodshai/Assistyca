"""Mail, calendars and Google belong to whoever connected them.

A family account is several people. The week and the lists are the
family's; each mailbox and calendar is its owner's alone. These tests hold
that line both ways - the account holder never reads the partner's, the
partner never reads the holder's - and check the one thing that may cross
between the parents: when each of them is busy, and nothing else.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from packages.infrastructure import household
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import tool_availability
from packages.infrastructure.connection_owner import CONNECTION_VIEWER_HEADER
from packages.infrastructure.connection_owner import busy_blocks
from packages.infrastructure.connection_owner import read_connection_viewer
from packages.infrastructure.connection_owner import sign_connection_viewer
from packages.infrastructure.inbox_watch_polls import InboxWatchConfig
from packages.infrastructure.inbox_watch_polls import InboxWatchScheduler
from packages.infrastructure.mailbox_finding_scans import FindingScanScheduler
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat

SERVER = "packages.infrastructure.portal_auth.server"
SECRET = "connection-owner-test-secret-0123456789"
HOLDER_PHONE = "972500000001"
PARTNER_PHONE = "972500000002"
GRANDMA_PHONE = "972500000005"
# What a calendar event holds beyond its times. None of it may leave the
# person whose calendar it is.
PRIVATE_WORDS = ("Dentist", "Clinic on Herzl", "dr.cohen@example.com", "root canal")


def _family(database: PortalDatabase) -> int:
    """Dana holds the account; Yoav (partner) and Rina (grandmother) joined
    from their own phones. Dana and Yoav each connected Gmail and a calendar."""

    database.register_user("dana@example.com", display_name="Dana Levi")
    user_id = int((database.get_user("dana@example.com") or {})["id"])
    database.link_user_whatsapp_number(user_id=user_id, wa_id=HOLDER_PHONE)
    for name, role, phone, code in (("Yoav", "partner", PARTNER_PHONE, "YOAV22"), ("Rina", "other", GRANDMA_PHONE, "RINA22")):
        member = database.save_household_member(user_id=user_id, name=name, role=role)
        database.create_household_invite(
            user_id=user_id, member_id=int(member["id"]), code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        assert database.claim_household_invite(code=code, wa_id=phone)["ok"]
    for owner, address in (("", "dana@gmail.com"), (PARTNER_PHONE, "yoav@gmail.com")):
        database.save_platform_connection(
            "dana@example.com", platform="email", provider="google_gmail", auth_type="oauth",
            secret_ciphertext=f"mail-{address}", secret_hint="", account_address=address, owner_wa_id=owner,
        )
        database.save_platform_connection(
            "dana@example.com", platform="calendar", provider="google_calendar", auth_type="oauth",
            secret_ciphertext=f"calendar-{address}", secret_hint="", owner_wa_id=owner,
        )
    return user_id


class BusyBlocksTests(unittest.TestCase):
    def test_only_start_and_end_leave_and_overlaps_merge(self) -> None:
        zone = ZoneInfo("Asia/Jerusalem")
        events = [
            {"title": "Dentist", "location": "Clinic on Herzl", "attendees": ["dr.cohen@example.com"],
             "description": "root canal", "start": datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc),
             "end": datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)},
            {"title": "Standup", "start": "2026-10-22T10:30:00+03:00", "end": "2026-10-22T12:00:00+03:00"},
            {"title": "Reserve duty", "allDay": True, "start": "2026-10-24", "end": "2026-10-25"},
        ]
        blocks = busy_blocks(events, zone)
        self.assertEqual(blocks, [
            {"start": "2026-10-22T10:00", "end": "2026-10-22T12:00"},
            {"start": "2026-10-24T00:00", "end": "2026-10-25T00:00"},
        ])
        for word in (*PRIVATE_WORDS, "Standup", "Reserve"):
            self.assertNotIn(word, json.dumps(blocks))

    def test_the_viewer_is_signed_by_the_server_alone(self) -> None:
        signed = sign_connection_viewer(SECRET, "dana@example.com", "+972 50-000-0002")
        self.assertEqual(read_connection_viewer(SECRET, "dana@example.com", signed), PARTNER_PHONE)
        self.assertIsNone(read_connection_viewer("another-secret", "dana@example.com", signed))
        self.assertIsNone(read_connection_viewer(SECRET, "someone@example.com", signed), "signed for one account only")
        self.assertIsNone(read_connection_viewer(SECRET, "dana@example.com", f"{GRANDMA_PHONE}.{signed.split('.')[1]}"))
        self.assertIsNone(read_connection_viewer(SECRET, "dana@example.com", "nobody"))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.user_id = _family(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_each_person_reads_their_own_connections(self) -> None:
        mine = self.database.list_platform_connections("dana@example.com", owner_wa_id="")
        theirs = self.database.list_platform_connections("dana@example.com", owner_wa_id=PARTNER_PHONE)
        self.assertEqual({row["ownerWaId"] for row in mine}, {""})
        self.assertEqual({row["ownerWaId"] for row in theirs}, {PARTNER_PHONE})
        self.assertEqual(len(mine), 2)
        self.assertEqual(len(theirs), 2, "the partner's calendar is a row of its own, not the holder's overwritten")
        self.assertEqual(self.database.list_platform_connections("dana@example.com", owner_wa_id=GRANDMA_PHONE), [])
        self.assertEqual(self.database.list_platform_connections("dana@example.com", owner_wa_id="-"), [])
        self.assertEqual(len(self.database.list_platform_connections("dana@example.com")), 4)
        self.assertEqual(self.database.list_connection_owners(user_id=self.user_id, platform="email"), ["", PARTNER_PHONE])

        # A status written for "the calendar" lands on that person's own.
        self.database.update_platform_connection_status(
            "dana@example.com", platform="calendar", connection_status="needs_attention", owner_wa_id=PARTNER_PHONE,
        )
        statuses = {
            row["ownerWaId"]: row["connectionStatus"]
            for row in self.database.list_platform_connections("dana@example.com")
            if row["platform"] == "calendar"
        }
        self.assertEqual(statuses, {"": "connected", PARTNER_PHONE: "needs_attention"})

        # Someone who has left the family is nobody's to read for.
        self.database.remove_household_member(user_id=self.user_id, name="Yoav")
        self.assertEqual(self.database.list_connection_owners(user_id=self.user_id, platform="email"), [""])

    def test_findings_and_receipts_are_kept_per_person(self) -> None:
        renewal = {"key": "renewal:netflix", "detector": "renewal", "title": "Netflix renews", "amount": 12.0}
        self.assertEqual(self.database.upsert_account_findings(user_id=self.user_id, findings=[renewal]), ["renewal:netflix"])
        self.assertEqual(
            self.database.upsert_account_findings(user_id=self.user_id, findings=[renewal], owner_wa_id=PARTNER_PHONE),
            ["renewal:netflix"], "the same renewal in two people's mail is two findings",
        )
        # The holder's scan no longer finding it resolves the holder's only.
        self.database.resolve_missing_account_findings(user_id=self.user_id, active_keys=[])
        self.assertEqual(self.database.list_account_findings(user_id=self.user_id), [])
        partner = self.database.list_account_findings(user_id=self.user_id, owner_wa_id=PARTNER_PHONE)
        self.assertEqual([finding["key"] for finding in partner], ["renewal:netflix"])
        self.assertIsNone(self.database.get_account_finding(user_id=self.user_id, finding_id=int(partner[0]["id"])))

        # Scans queue one per person.
        first = self.database.schedule_finding_scan(user_id=self.user_id, kind="daily", run_at=datetime.now(timezone.utc))
        second = self.database.schedule_finding_scan(
            user_id=self.user_id, kind="first", run_at=datetime.now(timezone.utc), owner_wa_id=PARTNER_PHONE,
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["ownerWaId"], PARTNER_PHONE)

        stored, _ = self.database.upsert_account_receipt(user_id=self.user_id, record={
            "messageId": "m1", "mailbox": "yoav@gmail.com", "vendor": "Wolt", "ownerWaId": PARTNER_PHONE,
        })
        self.assertEqual(self.database.list_account_receipts(user_id=self.user_id), [], "the receipts page is the holder's")
        self.assertEqual([r["vendor"] for r in self.database.list_account_receipts(user_id=self.user_id, owner_wa_id=PARTNER_PHONE)], ["Wolt"])
        self.assertIsNone(self.database.get_account_receipt(user_id=self.user_id, receipt_id=int(stored["id"])))
        self.assertIsNone(self.database.update_account_receipt(user_id=self.user_id, receipt_id=int(stored["id"]), notes="mine now"))
        self.assertFalse(self.database.delete_account_receipt(user_id=self.user_id, receipt_id=int(stored["id"])))


class RoleTests(unittest.TestCase):
    """What each grown-up on the account has, beyond the week."""

    def test_a_partner_has_their_own_mail_lists_and_tasks_but_not_the_holders_records(self) -> None:
        partner = household.describe_speaker({"name": "Yoav", "role": "partner"}, owner_name="Dana")
        grandma = household.describe_speaker({"name": "Rina", "role": "other"}, owner_name="Dana")
        connected = {"gmail": {"platformConnected": True, "writeAccess": True}, "calendar": {"platformConnected": True, "writeAccess": True}}
        own = (
            "read_inbox", "send_email", "read_calendar", "create_calendar_event", "search_receipts", "disconnect",
            "follow_email", "show_followed_emails", "stop_following_email", "connect_link", "check_family_busy",
            "create_list", "show_lists", "schedule_task", "show_scheduled", "cancel_scheduled",
        )
        for name in own:
            self.assertTrue(tool_availability(TOOLS_BY_NAME[name], connected, {}, speaker=partner).usable, name)
        for name in ("open_receipts", "show_insurance_policies", "save_insurance_policy", "delete_account"):
            self.assertEqual(tool_availability(TOOLS_BY_NAME[name], connected, {}, speaker=partner).code, "not_theirs", name)
        for name in (*own, "open_receipts"):
            self.assertEqual(tool_availability(TOOLS_BY_NAME[name], connected, {}, speaker=grandma).code, "not_theirs", name)
        self.assertTrue(household.can_connect_own_sources("partner"))
        self.assertTrue(household.can_connect_own_sources("owner"))
        self.assertFalse(household.can_connect_own_sources("other"))

    def test_the_busy_tool_passes_on_times_and_nothing_else(self) -> None:
        answered = {
            "ok": True, "from": "2026-10-22", "to": "2026-10-22",
            "people": [{"name": "Yoav", "calendarConnected": True, "busy": [
                {"start": "2026-10-22T10:00", "end": "2026-10-22T11:00", "title": "Dentist", "location": "Clinic on Herzl"},
            ], "events": [{"title": "root canal"}]}],
        }
        asked: list[tuple] = []

        def api(method, path, body=None, **_):
            asked.append((method, path, body))
            return answered, 200

        context = LoopContext(api=api, database=None, email="dana@example.com", user_id=1, timezone_name="Asia/Jerusalem")
        result = TOOLS_BY_NAME["check_family_busy"].run(context, {"from": "2026-10-22", "to": "2026-10-22"})
        self.assertEqual(asked, [("POST", "/api/family-week/busy", {"from": "2026-10-22", "to": "2026-10-22", "timezone": "Asia/Jerusalem"})])
        self.assertEqual(result["people"], [{"name": "Yoav", "calendarConnected": True, "busy": [{"start": "2026-10-22T10:00", "end": "2026-10-22T11:00"}]}])
        for word in PRIVATE_WORDS:
            self.assertNotIn(word, json.dumps(result))


class ChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.user_id = _family(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def chat(self, phone: str) -> WhatsAppAgentChat:
        connection = {
            "userId": self.user_id, "email": "dana@example.com", "ownerWaId": phone,
            **household.phone_conversation(self.database, user_id=self.user_id, wa_id=phone),
        }
        return WhatsAppAgentChat(
            database=self.database, connection=connection, base_url="http://127.0.0.1:1",
            session_token_factory=lambda email: "token",
            viewer_signer=lambda email, wa_id: sign_connection_viewer(SECRET, email, wa_id),
        )

    def test_the_chat_shows_and_signs_for_the_phone_that_wrote(self) -> None:
        partner = self.chat(PARTNER_PHONE)
        self.assertEqual(partner._build_tool_context()["mailboxes"], [{"name": "", "provider": "Gmail"}])
        self.assertEqual(partner.connection_owner, PARTNER_PHONE)
        holder = self.chat(HOLDER_PHONE)
        self.assertEqual(holder.connection_owner, "")
        self.assertEqual(self.chat(GRANDMA_PHONE)._build_tool_context().get("mailboxes"), None)

        sent: list[dict] = []

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true}'

        def urlopen(request, timeout=0):
            sent.append(dict(request.header_items()))
            return _Response()

        with mock.patch("packages.infrastructure.whatsapp_agent_chat.urllib_request.urlopen", side_effect=urlopen):
            partner._api("GET", "/api/agent/email/follows")
        header = sent[0].get(CONNECTION_VIEWER_HEADER.capitalize()) or sent[0].get(CONNECTION_VIEWER_HEADER)
        self.assertEqual(read_connection_viewer(SECRET, "dana@example.com", header), PARTNER_PHONE)


class _Answer:
    status = 200

    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class StandingRunTests(unittest.TestCase):
    """A scheduled run - the morning plan, a task, an alert - goes out as the
    person it is for, so it reads their own mail and calendar."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.user_id = _family(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_for(self, phone: str) -> tuple[str | None, dict]:
        from packages.infrastructure.standing_tasks import StandingTaskRunner

        sent: list[tuple[dict, dict]] = []

        def urlopen(request, timeout=0):
            sent.append((dict(request.header_items()), json.loads(request.data.decode())))
            return _Answer({"ok": True, "reply": "Your day: Tom at 16:00."})

        runner = StandingTaskRunner(
            database=self.database, base_url="http://127.0.0.1:1", session_token_factory=lambda email: "token",
            viewer_signer=lambda email, wa_id: sign_connection_viewer(SECRET, email, wa_id),
        )
        action = {"id": 7, "userId": self.user_id, "channel": "whatsapp",
                  "payload": {"title": "Morning", "instruction": "Say what today holds.", "recipientWaId": phone}}
        with mock.patch("packages.infrastructure.whatsapp_agent_chat.urllib_request.urlopen", side_effect=urlopen):
            runner.run(action)
        headers, body = sent[0]
        signed = headers.get(CONNECTION_VIEWER_HEADER.capitalize())
        return read_connection_viewer(SECRET, "dana@example.com", signed), body

    def test_each_run_is_signed_for_its_own_phone(self) -> None:
        viewer, body = self.run_for(PARTNER_PHONE)
        self.assertEqual(viewer, PARTNER_PHONE)
        self.assertEqual(body["senderWaId"], PARTNER_PHONE)
        self.assertEqual(body["toolContext"].get("mailboxes"), [{"name": "", "provider": "Gmail"}])
        viewer, _ = self.run_for(HOLDER_PHONE)
        self.assertEqual(viewer, HOLDER_PHONE, "the holder's phone, which the server reads as the holder's own")


class BackgroundJobTests(unittest.TestCase):
    """Each person's mailbox is scanned on its own and told to its owner."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.user_id = _family(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_inbox_watch_polls_each_person_once(self) -> None:
        polled: list[str] = []
        scheduler = InboxWatchScheduler(
            self.database, config=InboxWatchConfig(),
            poll=lambda account, tz: polled.append(account.get("memberWaId")) or {"ok": True, "new": 1, "notified": 0},
        )
        summary = scheduler.run_pending()
        self.assertEqual(summary["polled"], 1)
        self.assertEqual(polled, ["", PARTNER_PHONE])

    def test_a_partners_findings_go_to_the_partners_phone(self) -> None:
        scan = self.database.schedule_finding_scan(
            user_id=self.user_id, kind="first", run_at=datetime.now(timezone.utc) - timedelta(minutes=1), owner_wa_id=PARTNER_PHONE,
        )
        self.database.upsert_account_findings(
            user_id=self.user_id, owner_wa_id=PARTNER_PHONE,
            findings=[{"key": "bill:electric", "detector": "bill_due", "title": "Electric bill", "amount": 300.0, "dueOn": "2026-10-30", "score": 5}],
        )
        seen: list[dict] = []

        def scan_fn(row, account):
            seen.append(account)
            return {"ok": True, "findings": self.database.list_account_findings(user_id=self.user_id, owner_wa_id=PARTNER_PHONE)}

        scheduler = FindingScanScheduler(self.database, scan=scan_fn)
        scheduler.run_scan(self.database.claim_finding_scan(int(scan["id"])))
        self.assertEqual(seen[0]["memberWaId"], PARTNER_PHONE)
        actions = self.database.list_scheduled_actions_for_user(user_id=self.user_id)
        self.assertEqual([action["payload"].get("recipientWaId") for action in actions], [PARTNER_PHONE])
        self.assertEqual([f["status"] for f in self.database.list_account_findings(user_id=self.user_id, owner_wa_id=PARTNER_PHONE)], ["told"])
        following = self.database.list_finding_scans_for_user(user_id=self.user_id, owner_wa_id=PARTNER_PHONE)
        self.assertEqual(following[0]["kind"], "digest", "the partner's own scans carry on as theirs")


class ServerTests(unittest.TestCase):
    """Over the real handlers: the header the server signs is the only way
    to read anyone but the account holder, and busy times are all that
    crosses."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, root, PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret=SECRET),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.user_id = _family(self.database)
        code, _ = self.server.store.issue_challenge("dana@example.com")
        ok, error, result = self.server.store.verify_code("dana@example.com", code)
        self.assertTrue(ok, error)
        self.token = str((result or {}).get("token") or "")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, *, phone: str | None = None, header: str = "") -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
        if phone is not None:
            headers[CONNECTION_VIEWER_HEADER] = sign_connection_viewer(SECRET, "dana@example.com", phone)
        if header:
            headers[CONNECTION_VIEWER_HEADER] = header
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers,
        )
        try:
            with urllib_request.urlopen(request, timeout=20) as response:
                return int(response.status), json.loads(response.read().decode() or "{}")
        except urllib_error.HTTPError as exc:
            raw = exc.read().decode() or "{}"
            try:
                return int(exc.code), json.loads(raw)
            except ValueError:
                return int(exc.code), {}

    def owners(self, **kwargs) -> set[str]:
        status, body = self.request("GET", "/api/platform-connections", **kwargs)
        self.assertEqual(status, 200, body)
        return {row["ownerWaId"] for row in body["connections"]}

    def test_the_session_alone_is_the_holder_and_only_a_signed_phone_is_anyone_else(self) -> None:
        self.assertEqual(self.owners(), {""})
        self.assertEqual(self.owners(phone=HOLDER_PHONE), {""})
        self.assertEqual(self.owners(phone=PARTNER_PHONE), {PARTNER_PHONE})
        self.assertEqual(self.owners(phone=GRANDMA_PHONE), set())
        # A phone named without the server's signature, or one that has
        # left the family, reads nobody's - never the holder's in its place.
        self.assertEqual(self.owners(header=f"{PARTNER_PHONE}.forged"), set())
        self.assertEqual(self.owners(header=sign_connection_viewer("another-secret", "dana@example.com", PARTNER_PHONE)), set())
        self.assertEqual(self.owners(phone="972500000099"), set())

    def fake_calendar(self, read_for: list[str]):
        def events_between(handler, session, *, start, end, label, owner_wa_id=None):
            read_for.append(owner_wa_id)
            return [
                {"title": "Dentist", "location": "Clinic on Herzl", "attendees": ["dr.cohen@example.com"],
                 "description": "root canal", "start": start.replace(hour=10), "end": start.replace(hour=11), "allDay": False},
            ]
        return mock.patch(f"{SERVER}.PortalAuthHandler._calendar_events_between", new=events_between)

    def test_busy_times_cross_between_the_parents_and_nothing_else_does(self) -> None:
        read_for: list[str] = []
        with self.fake_calendar(read_for):
            status, holder_view = self.request("POST", "/api/family-week/busy", {"from": "2026-10-22", "to": "2026-10-22", "timezone": "Asia/Jerusalem"})
            self.assertEqual(status, 200, holder_view)
            status, partner_view = self.request(
                "POST", "/api/family-week/busy", {"from": "2026-10-22", "timezone": "Asia/Jerusalem"}, phone=PARTNER_PHONE,
            )
            self.assertEqual(status, 200, partner_view)
            status, grandma_view = self.request("POST", "/api/family-week/busy", {"from": "2026-10-22"}, phone=GRANDMA_PHONE)
            self.assertEqual(status, 403, grandma_view)
        self.assertEqual(read_for, [PARTNER_PHONE, ""], "each reads the other parent's calendar, never their own or a third")
        self.assertEqual(holder_view["people"], [{"name": "Yoav", "calendarConnected": True, "busy": [{"start": "2026-10-22T10:00", "end": "2026-10-22T11:00"}]}])
        self.assertEqual(partner_view["people"][0]["name"], "Dana Levi")
        for word in PRIVATE_WORDS:
            self.assertNotIn(word, json.dumps(holder_view) + json.dumps(partner_view))

    def turn(self, *, phone: str, signed: bool, calls: list) -> tuple[int, dict, list[str]]:
        """One WhatsApp turn from a phone, in which the model asks for the
        other parent's busy times; returns what the model was given."""

        given: list[str] = []
        rounds = iter([
            SimpleNamespace(output_text="", input_tokens=1, output_tokens=1, raw_response={"output": [
                {"type": "function_call", "name": "check_family_busy", "call_id": "c1", "arguments": json.dumps({"from": "2026-10-22", "to": "2026-10-22"})},
            ]}),
            SimpleNamespace(output_text=json.dumps({"reply": "Noted.", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None}),
                            input_tokens=1, output_tokens=1, raw_response={"output": []}),
        ])

        def model(**kwargs):
            given.append(json.dumps(kwargs.get("input"), default=str))
            calls.append(kwargs.get("tool_name"))
            return next(rounds)

        with mock.patch(f"{SERVER}.call_openai_response", side_effect=model), self.fake_calendar([]):
            status, body = self.request(
                "POST", "/api/agent/loop",
                {"userMessage": "who should take Tom on Thursday?", "timezone": "Asia/Jerusalem", "channel": "whatsapp", "senderWaId": phone},
                phone=phone if signed else None,
            )
        return status, body, given

    def test_a_turn_hands_the_model_busy_times_only(self) -> None:
        status, body, given = self.turn(phone=PARTNER_PHONE, signed=True, calls=[])
        self.assertEqual(status, 200, body)
        result = given[-1]
        self.assertIn("2026-10-22T10:00", result)
        self.assertIn("Dana Levi", result)
        for word in PRIVATE_WORDS:
            self.assertNotIn(word, "".join(given), "no event detail ever reaches the model")

    def test_a_partners_turn_without_their_signed_phone_reads_nobodys(self) -> None:
        status, body, given = self.turn(phone=PARTNER_PHONE, signed=False, calls=[])
        self.assertEqual(status, 200, body)
        self.assertNotIn("2026-10-22T10:00", given[-1])
        self.assertIn("could not be read", given[-1])


class _NoRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


class MemberBrowserTests(unittest.TestCase):
    """A page link sent to a family member's phone signs that browser in as
    them: the lists and the week, and their own connections. The account
    holder's receipts, mailbox, threads and assistant stay the holder's,
    and the browser stops working the moment they leave the family or sign
    the phone out."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, root, PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret=SECRET),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.user_id = _family(self.database)
        self.receipt = self.database.create_account_receipt(user_id=self.user_id, record={
            "status": "confirmed", "kind": "receipt", "vendor": "Dana's pharmacy", "amount": "42.00", "currency": "ILS",
        })

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def open_link(self, *, phone: str = "", prefix: str = "/lists/open/", opened_at: str = "") -> tuple[str, str]:
        """Tap a page link as the loop mints it for this phone - scoped to
        the page it is for - the cookie the browser is given, and where it
        lands. opened_at is another page's address to open it at."""

        code = self.database.create_list_open_code(
            user_id=self.user_id, list_id=0, expires_at=datetime.now(timezone.utc).timestamp() + 60, wa_id=phone,
            scope="receipts" if prefix == "/receipts/open/" else "family",
        )
        return self.tap(f"{opened_at or prefix}{code}")

    def tap(self, path: str) -> tuple[str, str]:
        try:
            urllib_request.build_opener(_NoRedirect).open(f"{self.base_url}{path}", timeout=10)
        except urllib_error.HTTPError as exc:
            cookie = str(exc.headers.get("Set-Cookie") or "").split(";", 1)[0]
            return cookie, str(exc.headers.get("Location") or "")
        self.fail("expected a redirect")

    def request(self, method: str, path: str, cookie: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", "Origin": self.base_url}
        if cookie:
            headers["Cookie"] = cookie
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers,
        )
        try:
            with urllib_request.urlopen(request, timeout=20) as response:
                return int(response.status), json.loads(response.read().decode() or "{}")
        except urllib_error.HTTPError as exc:
            raw = exc.read().decode() or "{}"
            try:
                return int(exc.code), json.loads(raw)
            except ValueError:
                return int(exc.code), {}

    def holders_records(self, cookie: str) -> dict[str, int]:
        """What each of the account holder's private endpoints answers."""

        return {
            "receipts": self.request("GET", "/api/receipts", cookie)[0],
            "receipt": self.request("GET", f"/api/receipts/{self.receipt['id']}", cookie)[0],
            "export": self.request("GET", "/api/receipts/export?format=csv", cookie)[0],
            "delete receipt": self.request("DELETE", f"/api/receipts/{self.receipt['id']}", cookie)[0],
            "follows": self.request("GET", "/api/agent/email/follows", cookie)[0],
            "loop": self.request("POST", "/api/agent/loop", cookie, {"message": "what's in my mail?"})[0],
            "notifications": self.request("GET", "/api/notifications", cookie)[0],
            "account": self.request("DELETE", "/api/account", cookie)[0],
            "remove a member": self.request("DELETE", "/api/household/members/Rina", cookie)[0],
        }

    def test_a_partners_link_opens_the_family_and_nothing_of_the_holders(self) -> None:
        cookie, landed = self.open_link(phone=PARTNER_PHONE)
        self.assertEqual(landed, "/lists")
        self.assertTrue(cookie)

        refused = self.holders_records(cookie)
        self.assertEqual(set(refused.values()), {403}, refused)
        self.assertIsNotNone(
            self.database.get_account_receipt(user_id=self.user_id, receipt_id=int(self.receipt["id"])),
            "the holder's receipt is still there",
        )
        self.assertIsNotNone(self.database.get_user("dana@example.com"))

        # A lists link opens the lists and the week; connections are not
        # part of what it was sent for, the partner's own included.
        status, connections = self.request("GET", "/api/platform-connections", cookie)
        self.assertEqual(status, 403, connections)
        self.assertNotIn("dana@gmail.com", json.dumps(connections))
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 200)
        self.assertEqual(self.request("GET", "/api/household", cookie)[0], 200)
        status, week = self.request("POST", "/api/household/activities", cookie, {"title": "Swimming", "days": ["mon"]})
        self.assertEqual(status, 200, week)
        status, signed_in = self.request("GET", "/api/auth/session", cookie)
        self.assertEqual((status, signed_in.get("member")), (200, True))
        self.assertNotIn("dana@example.com", json.dumps(signed_in))

    def test_a_grandparents_link_reads_the_week_and_changes_nothing(self) -> None:
        cookie, _ = self.open_link(phone=GRANDMA_PHONE, prefix="/week/open/")
        self.assertEqual(self.request("GET", "/api/household", cookie)[0], 200)
        self.assertEqual(self.request("POST", "/api/household/activities", cookie, {"title": "Swimming", "days": ["mon"]})[0], 403)
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 403)
        self.assertEqual(self.request("GET", "/api/platform-connections", cookie)[0], 403)

    def test_taking_the_partner_off_the_family_ends_their_browser(self) -> None:
        cookie, _ = self.open_link(phone=PARTNER_PHONE)
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 200)

        self.database.remove_household_member(user_id=self.user_id, name="Yoav")

        after = self.holders_records(cookie)
        after["lists"] = self.request("GET", "/api/lists", cookie)[0]
        after["week"] = self.request("GET", "/api/household", cookie)[0]
        after["connections"] = self.request("GET", "/api/platform-connections", cookie)[0]
        self.assertEqual(set(after.values()), {401}, after)
        # And a link minted for that phone before they left opens nothing.
        cookie, landed = self.open_link(phone=PARTNER_PHONE)
        self.assertEqual((cookie, landed), ("", "/lists?expired=1"))

    def test_signing_the_phone_out_ends_their_browser_and_joining_again_does_not_bring_it_back(self) -> None:
        cookie, _ = self.open_link(phone=PARTNER_PHONE)
        self.assertTrue(self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=PARTNER_PHONE))
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 401)
        self.assertEqual(self.request("GET", "/api/receipts", cookie)[0], 401)

        yoav = next(m for m in self.database.list_household_members(user_id=self.user_id) if m["name"] == "Yoav")
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(yoav["id"]), code="YOAV33",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.assertTrue(self.database.claim_household_invite(code="YOAV33", wa_id=PARTNER_PHONE)["ok"])
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 401, "an old browser stays signed out")
        fresh, _ = self.open_link(phone=PARTNER_PHONE)
        self.assertEqual(self.request("GET", "/api/lists", fresh)[0], 200)

    def test_the_holders_receipts_link_opens_her_receipts_and_nothing_else(self) -> None:
        cookie, landed = self.open_link(prefix="/receipts/open/")
        self.assertEqual(landed, "/receipts")
        status, listed = self.request("GET", "/api/receipts", cookie)
        self.assertEqual(status, 200, listed)
        self.assertEqual([row["vendor"] for row in listed["receipts"]], ["Dana's pharmacy"])
        self.assertEqual(self.request("GET", "/api/agent/email/follows", cookie)[0], 403)
        self.assertEqual(self.request("GET", "/api/platform-connections", cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/agent/loop", cookie, {"message": "hi"})[0], 403)
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 403)
        self.assertEqual(self.request("DELETE", f"/api/receipts/{self.receipt['id']}", cookie)[0], 200)

    def test_the_holders_week_link_forwarded_on_opens_only_what_the_family_shares(self) -> None:
        # Her own week link, as the model once suggested she share it: the
        # browser that opens it reaches the week and the lists, and nothing
        # of hers - not her receipts, connections, threads or assistant.
        cookie, landed = self.open_link(prefix="/week/open/")
        self.assertEqual(landed, "/week")
        refused = self.holders_records(cookie)
        refused["connections"] = self.request("GET", "/api/platform-connections", cookie)[0]
        self.assertEqual(set(refused.values()), {403}, refused)
        self.assertIsNotNone(self.database.get_account_receipt(user_id=self.user_id, receipt_id=int(self.receipt["id"])))
        self.assertIsNotNone(self.database.get_user("dana@example.com"))
        self.assertEqual(self.request("GET", "/api/household", cookie)[0], 200)
        status, week = self.request("POST", "/api/household/activities", cookie, {"title": "Swimming", "days": ["mon"]})
        self.assertEqual(status, 200, week)
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 200)
        status, made = self.request("POST", "/api/lists", cookie, {"name": "Groceries"})
        self.assertIn(status, {200, 201}, made)

    def test_a_link_opened_at_another_pages_address_opens_nothing(self) -> None:
        cookie, landed = self.open_link(prefix="/week/open/", opened_at="/receipts/open/")
        self.assertEqual((cookie, landed), ("", "/receipts?expired=1"))
        # A code minted before codes carried a scope is the family's.
        code = self.database.create_list_open_code(
            user_id=self.user_id, list_id=0, expires_at=datetime.now(timezone.utc).timestamp() + 60,
        )
        self.assertEqual(self.tap(f"/receipts/open/{code}"), ("", "/receipts?expired=1"))

    def test_an_old_link_of_a_partner_taken_off_and_brought_back_stays_shut(self) -> None:
        # Links minted before codes existed carried a signed session token.
        # Tapped after the partner left and joined again, it must not come
        # back as a sign-in newer than their return.
        old = self.server.store.issue_session("dana@example.com", member_wa_id=PARTNER_PHONE)["token"]
        self.database.remove_household_member(user_id=self.user_id, name="Yoav")
        yoav = self.database.save_household_member(user_id=self.user_id, name="Yoav", role="partner")
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(yoav["id"]), code="YOAV44",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.assertTrue(self.database.claim_household_invite(code="YOAV44", wa_id=PARTNER_PHONE)["ok"])
        cookie, _ = self.tap(f"/lists/open/{old}")
        self.assertEqual(self.request("GET", "/api/lists", cookie)[0], 401)
        self.assertEqual(self.request("GET", "/api/household", cookie)[0], 401)

    def test_the_receipts_handlers_read_only_the_phone_the_server_signed_for(self) -> None:
        code, _ = self.server.store.issue_challenge("dana@example.com")
        ok, error, result = self.server.store.verify_code("dana@example.com", code)
        self.assertTrue(ok, error)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {result['token']}",
            CONNECTION_VIEWER_HEADER: sign_connection_viewer(SECRET, "dana@example.com", PARTNER_PHONE),
        }

        def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
            request = urllib_request.Request(
                f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None,
                method=method, headers=headers,
            )
            try:
                with urllib_request.urlopen(request, timeout=20) as response:
                    return int(response.status), json.loads(response.read().decode() or "{}")
            except urllib_error.HTTPError as exc:
                return int(exc.code), {}

        status, listed = call("GET", "/api/receipts")
        self.assertEqual((status, listed["receipts"], listed["unsureTotal"]), (200, [], 0))
        self.assertEqual(call("GET", f"/api/receipts/{self.receipt['id']}")[0], 404)
        self.assertEqual(call("POST", f"/api/receipts/{self.receipt['id']}", {"amount": "1"})[0], 404)
        self.assertEqual(call("POST", "/api/receipts", {"vendor": "Partner's shop"})[0], 404)
        self.assertEqual(call("DELETE", f"/api/receipts/{self.receipt['id']}")[0], 404)
        kept = self.database.get_account_receipt(user_id=self.user_id, receipt_id=int(self.receipt["id"]))
        self.assertEqual(kept["amount"], "42.00")


class LeavingTakesTheirConnectionsTests(unittest.TestCase):
    """Taking someone off the family disconnects what they connected and
    hands Google's permission back. Signing their phone out does neither:
    it holds, like their reminders."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, root, PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret=SECRET),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.user_id = _family(self.database)
        code, _ = self.server.store.issue_challenge("dana@example.com")
        ok, error, result = self.server.store.verify_code("dana@example.com", code)
        self.assertTrue(ok, error)
        self.token = str((result or {}).get("token") or "")
        self.revoked: list[str] = []

        def revoke(handler, encrypted_secret):
            self.revoked.append(encrypted_secret)
            return True, ""

        patcher = mock.patch(f"{SERVER}.PortalAuthHandler._revoke_google_calendar_connection", new=revoke)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def owners(self) -> list[str]:
        return sorted(row["ownerWaId"] for row in self.database.list_platform_connections("dana@example.com"))

    def test_removing_the_partner_on_the_week_page_disconnects_and_revokes_theirs_only(self) -> None:
        request = urllib_request.Request(
            f"{self.base_url}/api/household/members/Yoav", method="DELETE",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=20) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.owners(), ["", ""], "Dana's own mail and calendar stay")
        self.assertEqual(sorted(self.revoked), ["calendar-yoav@gmail.com", "mail-yoav@gmail.com"])

    def test_removing_the_partner_in_the_chat_disconnects_theirs_and_says_so(self) -> None:
        from packages.infrastructure.portal_auth.server import PortalAuthHandler

        released: list[str] = []

        def release(wa_id: str) -> dict:
            released.append(wa_id)
            return PortalAuthHandler._release_departed_connections(
                SimpleNamespace(
                    database=self.database,
                    _revoke_connection_grant=lambda record: (self.revoked.append(record["secretCiphertext"]) or True, ""),
                ),
                "dana@example.com", wa_id,
            )

        context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="dana@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp", release_connections=release,
        )
        from packages.infrastructure.agent_loop import describe_remove_family_member

        self.assertIn("Google permission is withdrawn", describe_remove_family_member(context, {"name": "Yoav"}))
        result = TOOLS_BY_NAME["remove_family_member"].run(context, {"name": "Yoav"})
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["theirConnectionsDisconnected"], result["googlePermissionWithdrawn"]), (2, True))
        self.assertEqual(released, [PARTNER_PHONE])
        self.assertEqual(self.owners(), ["", ""])
        self.assertEqual(sorted(self.revoked), ["calendar-yoav@gmail.com", "mail-yoav@gmail.com"])

    def test_signing_the_phone_out_keeps_their_connections(self) -> None:
        self.assertTrue(self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=PARTNER_PHONE))
        self.assertEqual(self.owners(), ["", "", PARTNER_PHONE, PARTNER_PHONE])
        self.assertEqual(self.revoked, [])
        # Taken off later, from signed out: theirs still go.
        removed = self.database.remove_household_member(user_id=self.user_id, name="Yoav")
        self.assertEqual(removed["phones"], [PARTNER_PHONE])


if __name__ == "__main__":
    unittest.main()
