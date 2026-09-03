"""Free trials: how long an account may run before it has to pay."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.trial_access import (
    DEFAULT_TRIAL_DAYS,
    describe_trial,
    resolve_default_trial_days,
)


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


class TrialLogicTests(unittest.TestCase):
    def test_an_account_with_no_trial_length_is_never_limited(self) -> None:
        # Every account that existed before trials carries zero, so switching
        # this on must not switch anybody off.
        trial = describe_trial({"trialDays": 0, "trialStartedAt": None}, now=NOW)
        self.assertTrue(trial["allowed"])
        self.assertFalse(trial["onTrial"])

    def test_a_running_trial_is_allowed_and_counts_down(self) -> None:
        trial = describe_trial(
            {"trialDays": 2, "trialStartedAt": (NOW - timedelta(days=1)).isoformat()},
            now=NOW,
        )
        self.assertTrue(trial["allowed"])
        self.assertTrue(trial["onTrial"])
        self.assertEqual(trial["daysLeft"], 1)

    def test_a_finished_trial_is_refused(self) -> None:
        trial = describe_trial(
            {"trialDays": 2, "trialStartedAt": (NOW - timedelta(days=3)).isoformat()},
            now=NOW,
        )
        self.assertFalse(trial["allowed"])
        self.assertTrue(trial["expired"])
        self.assertEqual(trial["daysLeft"], 0)

    def test_paying_outlives_the_trial(self) -> None:
        record = {"trialDays": 2, "trialStartedAt": (NOW - timedelta(days=30)).isoformat()}
        self.assertFalse(describe_trial(record, now=NOW)["allowed"])
        self.assertTrue(describe_trial(record, is_paying=True, now=NOW)["allowed"])

    def test_a_length_with_no_start_has_not_begun_counting(self) -> None:
        # A field nobody filled in must not lock an account out.
        trial = describe_trial({"trialDays": 2, "trialStartedAt": None}, now=NOW)
        self.assertTrue(trial["allowed"])

    def test_the_default_length_is_two_days_and_is_configurable(self) -> None:
        self.assertEqual(DEFAULT_TRIAL_DAYS, 2)
        with mock.patch.dict("os.environ", {"PORTAL_DEFAULT_TRIAL_DAYS": "14"}, clear=False):
            self.assertEqual(resolve_default_trial_days(), 14)
        with mock.patch.dict("os.environ", {"PORTAL_DEFAULT_TRIAL_DAYS": "nonsense"}, clear=False):
            self.assertEqual(resolve_default_trial_days(), DEFAULT_TRIAL_DAYS)


class TrialEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="trial-test-secret",
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.token = self._sign_in("owner@example.com")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _sign_in(self, email: str) -> str:
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        return str((result or {}).get("token") or "")

    def _turn(self, token: str) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/turn",
            data=json.dumps({"userMessage": "hello", "timezone": "UTC"}).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=15) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return int(exc.code), json.loads(exc.read().decode("utf-8"))

    def test_an_existing_account_keeps_working(self) -> None:
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(
                output_text=json.dumps({"outcome": "message", "reply": "Hi."})
            ),
        ):
            status, payload = self._turn(self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["reply"], "Hi.")

    def test_an_expired_trial_is_refused_before_the_model_is_called(self) -> None:
        self.database.set_user_trial("owner@example.com", trial_days=2)
        user = self.database.get_user("owner@example.com") or {}
        # Wind the clock back rather than waiting two days for it.
        with self.database._connection() as conn:  # noqa: SLF001 - fixture setup
            conn.execute(
                "UPDATE users SET trial_started_at = ? WHERE id = ?",
                ((datetime.now(timezone.utc) - timedelta(days=5)).isoformat(), int(user["id"])),
            )
            conn.commit()

        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
        ) as model:
            status, payload = self._turn(self.token)

        model.assert_not_called()
        self.assertEqual(status, 402)
        self.assertEqual(payload["error"], "trial_expired")
        self.assertTrue(payload["trial"]["expired"])

    def test_a_running_trial_still_answers(self) -> None:
        self.database.set_user_trial("owner@example.com", trial_days=2)
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(
                output_text=json.dumps({"outcome": "message", "reply": "Still here."})
            ),
        ):
            status, payload = self._turn(self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["reply"], "Still here.")

    def test_an_admin_sets_the_trial_length_per_client(self) -> None:
        self.database.register_user("client@example.com")
        admin_email = "boss@example.com"
        self.database.register_user(admin_email, is_admin=True)
        admin_token = self._sign_in(admin_email)

        request = urllib_request.Request(
            f"{self.base_url}/api/admin/users/client%40example.com/trial",
            data=json.dumps({"trialDays": 14}).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user"]["trial"]["trialDays"], 14)
        self.assertTrue(payload["user"]["trial"]["onTrial"])
        stored = self.database.get_user("client@example.com") or {}
        self.assertEqual(stored["trialDays"], 14)
        self.assertTrue(stored["trialStartedAt"])

    def test_extending_a_trial_does_not_restart_its_clock(self) -> None:
        self.database.set_user_trial("owner@example.com", trial_days=2)
        started = (self.database.get_user("owner@example.com") or {})["trialStartedAt"]
        self.database.set_user_trial("owner@example.com", trial_days=30)
        after = self.database.get_user("owner@example.com") or {}
        self.assertEqual(after["trialStartedAt"], started)
        self.assertEqual(after["trialDays"], 30)

    def test_zero_days_removes_the_limit(self) -> None:
        self.database.set_user_trial("owner@example.com", trial_days=2)
        updated = self.database.set_user_trial("owner@example.com", trial_days=0)
        self.assertEqual(updated["trialDays"], 0)
        self.assertTrue(describe_trial(updated)["allowed"])

    def test_the_client_list_reports_the_trial_each_account_is_really_on(self) -> None:
        # The list is the only place an operator sees every client at once. It
        # used to drop the trial columns, so every account read as unlimited
        # however many days it actually had.
        self.database.set_user_trial("owner@example.com", trial_days=14)
        listed = next(
            user for user in self.database.list_users()
            if user["email"] == "owner@example.com"
        )

        self.assertEqual(listed["trialDays"], 14)
        self.assertTrue(listed["trialStartedAt"])
        self.assertEqual(describe_trial(listed)["daysLeft"], 14)

    def test_an_admin_listing_clients_sees_who_is_running_out(self) -> None:
        self.database.register_user("boss@example.com", is_admin=True)
        admin_token = self._sign_in("boss@example.com")
        self.database.set_user_trial("owner@example.com", trial_days=7)

        request = urllib_request.Request(
            f"{self.base_url}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        with urllib_request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))

        listed = next(user for user in payload["users"] if user["email"] == "owner@example.com")
        self.assertEqual(listed["trial"]["trialDays"], 7)
        self.assertTrue(listed["trial"]["onTrial"])
        self.assertEqual(listed["trial"]["daysLeft"], 7)
        self.assertTrue(listed["trial"]["endsAt"])


if __name__ == "__main__":
    unittest.main()
