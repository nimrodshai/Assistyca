"""The homework check: asked once at the first 13:00, answered on a private page."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from packages.infrastructure import homework_check
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import tool_definitions
from packages.infrastructure.credential_vault import CredentialVault
from packages.infrastructure.family_week_nudges import FamilyWeekNudgeConfig
from packages.infrastructure.family_week_nudges import FamilyWeekNudger
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

ISRAEL = ZoneInfo("Asia/Jerusalem")
TEST_KEY = "11" * 32


def _open_the_check(test: unittest.TestCase) -> None:
    """The check is frozen unless switched on; these tests are of it open."""

    patcher = mock.patch.dict("os.environ", {homework_check.HOMEWORK_CHECK_SWITCH: "1"})
    patcher.start()
    test.addCleanup(patcher.stop)


class FirstOneOClockTests(unittest.TestCase):
    def test_the_first_one_oclock_after_joining_saturday_passed_over(self) -> None:
        # 2026-10-15 is a Thursday.
        thursday_morning = datetime(2026, 10, 15, 12, 59, tzinfo=ISRAEL)
        self.assertEqual(homework_check.first_offer_moment(thursday_morning), datetime(2026, 10, 15, 13, 0, tzinfo=ISRAEL))
        thursday_afternoon = datetime(2026, 10, 15, 13, 1, tzinfo=ISRAEL)
        self.assertEqual(homework_check.first_offer_moment(thursday_afternoon), datetime(2026, 10, 16, 13, 0, tzinfo=ISRAEL))
        friday_afternoon = datetime(2026, 10, 16, 15, 0, tzinfo=ISRAEL)
        self.assertEqual(homework_check.first_offer_moment(friday_afternoon), datetime(2026, 10, 18, 13, 0, tzinfo=ISRAEL))

    def test_due_only_at_that_moment_and_never_for_an_older_account(self) -> None:
        joined = datetime(2026, 10, 15, 9, 0, tzinfo=ISRAEL)
        self.assertFalse(homework_check.offer_due(joined, datetime(2026, 10, 15, 12, 58, tzinfo=ISRAEL)))
        self.assertTrue(homework_check.offer_due(joined, datetime(2026, 10, 15, 13, 2, tzinfo=ISRAEL)))
        self.assertFalse(homework_check.offer_due(joined, datetime(2026, 10, 15, 15, 1, tzinfo=ISRAEL)))
        self.assertFalse(homework_check.offer_due(joined, datetime(2026, 10, 16, 13, 2, tzinfo=ISRAEL)))
        self.assertFalse(homework_check.offer_due(None, datetime(2026, 10, 15, 13, 2, tzinfo=ISRAEL)))

    def test_only_children_at_school_count(self) -> None:
        today = date(2026, 10, 15)
        members = [
            {"name": "Lahav", "role": "child", "age": 7, "ageNotedOn": "2026-10-01"},
            {"name": "Laor", "role": "child", "age": 4, "ageNotedOn": "2026-10-01", "school": "Gan Rimon"},
            {"name": "Noa", "role": "child", "school": "Shaked school"},
            {"name": "Tom", "role": "child", "school": "גן חצב"},
            {"name": "Ido", "role": "child"},
            {"name": "Stav", "role": "partner", "age": 38},
        ]
        self.assertEqual(homework_check.school_children(members, today), ["Lahav", "Noa"])

    def test_the_form_is_checked_and_the_password_kept_as_typed(self) -> None:
        fields, problem = homework_check.clean_login_form({
            "platform": "mashov", "schoolCode": " 44 01 22 ", "username": " 123456789 ", "password": " pa ss ",
        })
        self.assertEqual(problem, "")
        self.assertEqual((fields["schoolCode"], fields["username"], fields["password"]), ("440122", "123456789", " pa ss "))
        self.assertEqual(homework_check.clean_login_form({"platform": "tiktok", "username": "a", "password": "b"})[1], "platform_required")
        self.assertEqual(homework_check.clean_login_form({"platform": "other", "username": "a", "password": "b"})[1], "platform_required")
        self.assertEqual(homework_check.clean_login_form({"platform": "webtop", "username": "a", "password": "  "})[1], "login_required")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.vault = CredentialVault(TEST_KEY)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def link(self, code: str = "code-1") -> None:
        self.database.create_homework_login_link(
            user_id=self.user_id, code=code, expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        )

    def test_nothing_is_kept_without_the_vault(self) -> None:
        self.link()
        with self.assertRaises(RuntimeError):
            self.database.save_homework_login(code="code-1", platform="mashov", username="u", password="p")
        self.assertEqual(self.database.list_homework_logins(user_id=self.user_id), [])
        self.assertEqual(self.database.get_homework_login_link("code-1")["status"], "live")

    def test_the_login_is_kept_encrypted_and_the_link_spent(self) -> None:
        self.database.set_credential_vault(self.vault)
        self.link()
        self.database.save_homework_login(
            code="code-1", platform="mashov", school_code="440122", username="123456789", password="secret-pass",
        )
        with self.database._connection() as conn:
            row = dict(conn.execute("SELECT * FROM homework_logins").fetchone())
        self.assertNotIn("secret-pass", json.dumps(row))
        self.assertNotIn("123456789", json.dumps(row))
        self.assertEqual(self.vault.decrypt(row["password_ciphertext"]), "secret-pass")
        self.assertEqual(self.vault.decrypt(row["username_ciphertext"]), "123456789")
        [kept] = self.database.list_homework_logins(user_id=self.user_id)
        self.assertEqual((kept["platform"], kept["hasSchoolCode"]), ("mashov", True))
        self.assertNotIn("123456789", json.dumps(kept))
        self.assertEqual(self.database.get_homework_login_link("code-1")["status"], "used")
        with self.assertRaises(LookupError):
            self.database.save_homework_login(code="code-1", platform="mashov", username="x", password="y")

    def test_an_old_link_and_a_replaced_one_do_not_work(self) -> None:
        self.database.set_credential_vault(self.vault)
        self.database.create_homework_login_link(
            user_id=self.user_id, code="old", expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        self.assertEqual(self.database.get_homework_login_link("old")["status"], "expired")
        self.link("first")
        self.link("second")
        self.assertIsNone(self.database.get_homework_login_link("first"))
        self.assertIsNone(self.database.get_homework_login_link("nobody-issued-this"))

    def test_removed_one_at_a_time_or_all_and_with_the_account(self) -> None:
        self.database.set_credential_vault(self.vault)
        for code in ("a", "b"):
            self.link(code)
            self.database.save_homework_login(code=code, platform="webtop", username="u", password="p")
        first, second = self.database.list_homework_logins(user_id=self.user_id)
        self.assertEqual(self.database.delete_homework_logins(user_id=self.user_id, login_id=first["id"]), 1)
        self.assertEqual([login["id"] for login in self.database.list_homework_logins(user_id=self.user_id)], [second["id"]])
        self.database.delete_user("parent@example.com")
        with self.database._connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM homework_logins").fetchone()[0], 0)


class OfferTests(unittest.TestCase):
    """The nudger asks once, at the first 13:00, inside the window."""

    def setUp(self) -> None:
        _open_the_check(self)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.database.save_whatsapp_connection("parent@example.com", owner_wa_id="972500000001", connection_status="connected")
        self.database.save_household_member(user_id=self.user_id, name="Lahav", role="child", age=8)
        self.nudger = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(week_ahead=False))
        registered = datetime.fromisoformat(self.database.get_user_by_id(self.user_id)["registeredAt"])
        self.moment = homework_check.first_offer_moment(registered.astimezone(ISRAEL))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def wrote_at(self, when: datetime) -> None:
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="hi")
        with self.database._connection() as conn:
            conn.execute("UPDATE whatsapp_agent_messages SET created_at = ?", (when.astimezone(timezone.utc).isoformat(),))

    def offers(self) -> list[dict]:
        return [
            action["payload"] for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("title") == "Homework check"
        ]

    def test_asked_once_at_the_first_one_oclock_as_plain_text(self) -> None:
        self.wrote_at(self.moment - timedelta(hours=3))
        self.assertEqual(self.nudger.run_pending(now=self.moment - timedelta(minutes=5))["homeworkOffer"], 0)
        self.assertEqual(self.nudger.run_pending(now=self.moment + timedelta(minutes=1))["homeworkOffer"], 1)
        [offer] = self.offers()
        self.assertTrue(offer["windowOnly"])
        self.assertIn("CHILDREN AT SCHOOL: Lahav", offer["instruction"])
        self.assertIn("Never ask for a username or a password", offer["instruction"])
        self.assertEqual(self.nudger.run_pending(now=self.moment + timedelta(minutes=3))["homeworkOffer"], 0)
        self.assertEqual(len(self.offers()), 1)

    def test_outside_the_window_it_is_dropped_for_good(self) -> None:
        self.wrote_at(self.moment - timedelta(hours=25))
        self.assertEqual(self.nudger.run_pending(now=self.moment + timedelta(minutes=1))["homeworkOffer"], 0)
        self.wrote_at(self.moment)
        self.assertEqual(self.nudger.run_pending(now=self.moment + timedelta(minutes=3))["homeworkOffer"], 0)
        self.assertEqual(self.offers(), [])

    def test_not_asked_without_a_child_at_school_or_outside_israel(self) -> None:
        self.wrote_at(self.moment - timedelta(hours=1))
        self.database.save_household_member(user_id=self.user_id, name="Lahav", role="child", age=3)
        self.assertEqual(self.nudger.run_pending(now=self.moment + timedelta(minutes=1))["homeworkOffer"], 0)
        self.database.save_household_member(user_id=self.user_id, name="Lahav", role="child", age=9)
        self.database.save_whatsapp_connection("parent@example.com", owner_wa_id="447700900001", connection_status="connected")
        self.assertEqual(self.nudger.run_pending(now=self.moment + timedelta(minutes=2))["homeworkOffer"], 0)
        self.assertEqual(self.offers(), [])

    def test_a_closed_window_by_send_time_stops_it_before_it_is_written(self) -> None:
        self.wrote_at(self.moment - timedelta(hours=3))
        self.nudger.run_pending(now=self.moment + timedelta(minutes=1))
        self.wrote_at(datetime.now(timezone.utc) - timedelta(days=2))
        written: list[dict] = []
        scheduler = ScheduledActionScheduler(
            self.database, config=ScheduledActionConfig(), task_runner=lambda action: written.append(action) or "Hi",
        )
        scheduler.run_pending(now=datetime.now(timezone.utc) + timedelta(days=30))
        self.assertEqual(written, [])
        [action] = [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("title") == "Homework check"
        ]
        self.assertEqual(action["status"], "failed")
        self.assertNotEqual(action["payload"].get("deliveredVia"), "portal_fallback")


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        _open_the_check(self)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.set_credential_vault(CredentialVault(TEST_KEY))
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp",
            homework_link=lambda code: f"https://assistyca.com/homework/{code}",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_a_yes_gets_the_page_and_the_login_can_be_taken_back(self) -> None:
        made = TOOLS_BY_NAME["homework_login_link"].run(self.context, {})
        self.assertTrue(made["ok"], made)
        self.assertRegex(made["link"], r"^https://assistyca\.com/homework/[A-Za-z0-9_-]{20,}$")
        self.assertEqual(made["alreadyKept"], [])
        code = made["link"].rsplit("/", 1)[1]
        self.database.save_homework_login(code=code, platform="mashov", username="u", password="p")

        again = TOOLS_BY_NAME["homework_login_link"].run(self.context, {})
        self.assertEqual([login["platform"] for login in again["alreadyKept"]], ['Mashov'])

        removed = TOOLS_BY_NAME["forget_homework_login"].run(self.context, {"id": None})
        self.assertEqual((removed["removed"], removed["stillKept"]), (1, []))
        self.assertEqual(TOOLS_BY_NAME["forget_homework_login"].run(self.context, {"id": None})["removed"], 0)

    def test_no_page_where_no_link_can_be_made(self) -> None:
        bare = LoopContext(api=lambda *a, **k: ({}, 200), database=self.database, email="parent@example.com", user_id=self.user_id)
        self.assertFalse(TOOLS_BY_NAME["homework_login_link"].run(bare, {})["ok"])


class PageTests(unittest.TestCase):
    def setUp(self) -> None:
        _open_the_check(self)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="homework-page-test-secret-0123456789abcdef",
                credential_encryption_key=TEST_KEY,
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.database.create_homework_login_link(
            user_id=self.user_id, code="page-code-123", expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None, method=method,
            headers={"Content-Type": "application/json", "Origin": self.base_url},
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return int(response.status), json.loads(response.read().decode() or "{}")
        except urllib_error.HTTPError as exc:
            return int(exc.code), json.loads(exc.read().decode() or "{}")

    def test_the_page_opens_saves_once_and_says_nothing_back(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/homework/page-code-123", timeout=10) as response:
            self.assertIn("homework.js", response.read().decode())
        status, opened = self.request("GET", "/api/public/homework/page-code-123")
        self.assertEqual((status, opened["status"]), (200, "live"))
        self.assertIn("mashov", [platform["id"] for platform in opened["platforms"]])

        status, refused = self.request("POST", "/api/public/homework/page-code-123", {"platform": "mashov", "username": "u"})
        self.assertEqual((status, refused["error"]), (400, "login_required"))

        status, saved = self.request("POST", "/api/public/homework/page-code-123", {
            "platform": "mashov", "schoolCode": "440122", "username": "123456789", "password": "secret-pass",
        })
        self.assertEqual((status, saved), (200, {"ok": True}))
        self.assertEqual(len(self.database.list_homework_logins(user_id=self.user_id)), 1)

        status, again = self.request("POST", "/api/public/homework/page-code-123", {
            "platform": "mashov", "username": "x", "password": "y",
        })
        self.assertEqual((status, again["error"]), (410, "link_used"))
        status, gone = self.request("GET", "/api/public/homework/page-code-123")
        self.assertEqual((status, gone["status"]), (200, "used"))
        status, _ = self.request("GET", "/api/public/homework/never-issued")
        self.assertEqual(status, 404)


class FrozenTests(PageTests):
    """Frozen for everyone: no 13:00 question, no tool that hands out the
    page, and the page closed - with every kept login still there."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict("os.environ", {homework_check.HOMEWORK_CHECK_SWITCH: ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_page_is_closed(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            urllib_request.urlopen(f"{self.base_url}/homework/page-code-123", timeout=10)
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(self.request("GET", "/api/public/homework/page-code-123")[0], 404)
        status, _ = self.request("POST", "/api/public/homework/page-code-123", {
            "platform": "mashov", "username": "u", "password": "p",
        })
        self.assertEqual(status, 404)
        self.assertEqual(self.database.get_homework_login_link("page-code-123")["status"], "live", "kept for later")

    def test_the_page_file_is_not_served_by_its_own_address_either(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            urllib_request.urlopen(f"{self.base_url}/portal/homework.html", timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def test_the_page_file_is_not_served_by_another_spelling_of_its_address(self) -> None:
        import http.client as http_client

        for spelling in (
            "/portal/%68omework.html", "/portal/homework%2Ehtml", "/portal//homework.html",
            "/portal/./homework.html", "/portal/HOMEWORK.html", "/portal/homework.html/",
        ):
            with self.subTest(spelling=spelling):
                connection = http_client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
                try:
                    connection.request("GET", spelling)
                    response = connection.getresponse()
                    response.read()
                finally:
                    connection.close()
                self.assertEqual(response.status, 404)

    def test_the_page_is_open_again_once_switched_back_on(self) -> None:
        with mock.patch.dict("os.environ", {homework_check.HOMEWORK_CHECK_SWITCH: "1"}):
            self.assertEqual(self.request("GET", "/api/public/homework/page-code-123")[0], 200)
            with urllib_request.urlopen(f"{self.base_url}/portal/homework.html", timeout=10) as response:
                self.assertEqual(response.status, 200)

    def test_the_page_opens_saves_once_and_says_nothing_back(self) -> None:
        self.skipTest("the page is closed while the check is frozen")

    def test_nothing_offers_it(self) -> None:
        names = {tool["name"] for tool in tool_definitions({})}
        self.assertNotIn("homework_login_link", names)
        self.assertIn("forget_homework_login", names, "a kept login can still be removed")
        from packages.infrastructure.agent_loop import tool_availability

        self.assertEqual(tool_availability(TOOLS_BY_NAME["homework_login_link"], {}).code, "not_here")

    def test_no_question_at_one_oclock(self) -> None:
        self.database.save_whatsapp_connection("parent@example.com", owner_wa_id="972500000001", connection_status="connected")
        self.database.save_household_member(user_id=self.user_id, name="Lahav", role="child", age=8)
        nudger = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(week_ahead=False))
        registered = datetime.fromisoformat(self.database.get_user_by_id(self.user_id)["registeredAt"])
        moment = homework_check.first_offer_moment(registered.astimezone(ISRAEL))
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="hi")
        with self.database._connection() as conn:
            conn.execute("UPDATE whatsapp_agent_messages SET created_at = ?", ((moment - timedelta(hours=3)).astimezone(timezone.utc).isoformat(),))
        self.assertEqual(nudger.run_pending(now=moment + timedelta(minutes=1))["homeworkOffer"], 0)
        with mock.patch.dict("os.environ", {homework_check.HOMEWORK_CHECK_SWITCH: "1"}):
            self.assertEqual(nudger.run_pending(now=moment + timedelta(minutes=2))["homeworkOffer"], 1, "asked once open")


if __name__ == "__main__":
    unittest.main()
