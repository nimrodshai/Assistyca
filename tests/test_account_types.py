"""The feature switches: one set, for every account."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.account_types import ACCOUNT_FEATURES
from packages.infrastructure.account_types import account_feature_allowed
from packages.infrastructure.account_types import blocked_tools
from packages.infrastructure.account_types import describe_features
from packages.infrastructure.account_types import feature_allowed
from packages.infrastructure.agent_loop import ACCOUNT_RIGHTS_TOOLS
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.portal_db import PortalDatabase


class CatalogueTests(unittest.TestCase):
    def test_a_feature_arrives_whole(self) -> None:
        # A feature's tools are all in this build or none of them are: a
        # half-present feature is a typo, not a feature still on its way.
        for feature in ACCOUNT_FEATURES:
            present = [tool in TOOLS_BY_NAME for tool in feature.tools]
            self.assertTrue(all(present) or not any(present), f"{feature.feature_id} names a tool that does not exist")

    def test_the_list_leaves_out_a_feature_this_build_does_not_have(self) -> None:
        listed = describe_features({}, {"read_inbox", "send_email"})
        ids = [feature["featureId"] for feature in listed["features"]]
        self.assertIn("mail", ids)
        self.assertIn("inbox_watch", ids)
        self.assertNotIn("receipts", ids)

    def test_leaving_and_giving_back_are_never_gated(self) -> None:
        gated = {tool for feature in ACCOUNT_FEATURES for tool in feature.tools}
        for tool in (*ACCOUNT_RIGHTS_TOOLS, "connect_link", "forget_fact", "cancel_scheduled", "dismiss_finding", "remove_family_member", "remove_week_activity"):
            self.assertNotIn(tool, gated)

    def test_nothing_is_switched_off_until_someone_does(self) -> None:
        self.assertTrue(feature_allowed({}, "receipts"))
        self.assertTrue(feature_allowed(None, "receipts"))
        self.assertEqual(blocked_tools({}), {})

    def test_a_switch_takes_its_tools_with_it(self) -> None:
        self.assertEqual(set(blocked_tools({"receipts": False})), {"search_receipts", "open_receipts"})
        self.assertEqual(blocked_tools({"receipts": True}), {})

    def test_a_store_that_cannot_answer_leaves_the_feature_on(self) -> None:
        self.assertTrue(account_feature_allowed(object(), feature_id="receipts"))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "portal.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_switches_are_kept_and_moved_back(self) -> None:
        database = PortalDatabase(self.db_path)
        switches = database.set_feature_switch(feature_id="mail", allowed=False)
        self.assertEqual(switches, {"mail": False})
        switches = database.set_feature_switch(feature_id="mail", allowed=True)
        self.assertEqual(switches, {"mail": True})
        with self.assertRaises(ValueError):
            database.set_feature_switch(feature_id="teleport", allowed=False)

    def test_the_family_column_of_the_old_grid_becomes_the_switches(self) -> None:
        # Switches used to be kept per kind of account. Only families are
        # left, so what the house switched off for them carries over and the
        # business column is forgotten with the table.
        database = PortalDatabase(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE account_type_features (account_type TEXT NOT NULL, feature_id TEXT NOT NULL, allowed INTEGER NOT NULL DEFAULT 1, "
            "updated_by TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(account_type, feature_id))"
        )
        conn.execute("INSERT INTO account_type_features VALUES ('family', 'mail', 0, 'boss@example.com', 'x')")
        conn.execute("INSERT INTO account_type_features VALUES ('business', 'lists', 0, 'boss@example.com', 'x')")
        conn.commit()
        conn.close()

        reopened = PortalDatabase(self.db_path)
        self.assertEqual(reopened.get_feature_switches(), {"mail": False})
        conn = sqlite3.connect(self.db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
        self.assertNotIn("account_type_features", tables)

    def test_a_user_row_carries_no_account_type(self) -> None:
        database = PortalDatabase(self.db_path)
        database.register_user("a@example.com")
        self.assertNotIn("accountType", database.get_user("a@example.com") or {})


class LoopTests(unittest.TestCase):
    def test_a_switched_off_tool_is_marked_and_refused(self) -> None:
        calls: list[tuple] = []

        def api(method: str, path: str, payload: dict | None = None, **_: object) -> tuple[dict, int]:
            calls.append((method, path, payload))
            return {"ok": True}, 200

        rounds = [
            SimpleNamespace(output_text="", raw_response={"output": [{
                "type": "function_call", "name": "search_receipts", "call_id": "c1",
                "arguments": json.dumps({"what": "receipts", "vendor": None, "months": None}),
            }]}),
            SimpleNamespace(output_text=json.dumps({"reply": "Receipts are not part of this account.", "claimsCompleted": [], "rememberFact": None, "forgetFact": None}), raw_response={"output": []}),
        ]
        seen: list[list[dict]] = []
        inputs: list[list[dict]] = []

        def model(input_items: list[dict], tools: list[dict]) -> SimpleNamespace:
            seen.append(tools)
            inputs.append(list(input_items))
            return rounds.pop(0)

        context = LoopContext(
            api=api, database=SimpleNamespace(), email="fam@example.com", user_id=1,
            tool_context={"gmail": {"platformConnected": True, "connectionStatus": "connected"}},
            blocked_tools={"search_receipts": "Receipts", "open_receipts": "Receipts"},
        )
        result = run_agent_loop(context=context, call_model=model, user_message="find my receipts", conversation=[], today="2026-09-17")

        by_name = {tool["name"]: tool for tool in seen[0]}
        self.assertIn("Receipts is not included in this account", by_name["search_receipts"]["description"])
        self.assertNotIn("UNAVAILABLE", by_name["remember_fact"]["description"])
        output = json.loads(inputs[1][-1]["output"])
        self.assertEqual(output["error"]["code"], "not_included")
        self.assertEqual(calls, [])
        self.assertEqual(result.reply, "Receipts are not part of this account.")


class AdminEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="account-types-secret"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("boss@example.com", is_admin=True)
        self.database.register_user("fam@example.com")
        self.admin_token = self._sign_in("boss@example.com")
        self.family_token = self._sign_in("fam@example.com")

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

    def _request(self, method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=15) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                return int(exc.code), json.loads(body)
            except json.JSONDecodeError:
                return int(exc.code), {"raw": body}

    def test_the_switches_start_all_on_and_a_switch_sticks(self) -> None:
        status, payload = self._request("GET", "/api/admin/features", self.admin_token)
        self.assertEqual(status, 200, payload)
        self.assertNotIn("accountTypes", payload)
        self.assertTrue(all(feature["allowed"] is True for feature in payload["features"]))
        self.assertTrue(payload["alwaysOn"])

        status, payload = self._request(
            "POST", "/api/admin/features", self.admin_token,
            {"featureId": "voice_notes", "allowed": False},
        )
        self.assertEqual(status, 200, payload)
        voice = next(feature for feature in payload["features"] if feature["featureId"] == "voice_notes")
        self.assertFalse(voice["allowed"])

    def test_a_switch_needs_a_feature_and_a_yes_or_no(self) -> None:
        status, payload = self._request("POST", "/api/admin/features", self.admin_token, {"featureId": "teleport", "allowed": False})
        self.assertEqual(status, 400, payload)
        status, payload = self._request("POST", "/api/admin/features", self.admin_token, {"featureId": "mail", "allowed": "no"})
        self.assertEqual(status, 400, payload)

    def test_a_family_cannot_see_or_move_the_switches(self) -> None:
        status, _ = self._request("GET", "/api/admin/features", self.family_token)
        self.assertEqual(status, 403)
        status, _ = self._request("POST", "/api/admin/features", self.family_token, {"featureId": "mail", "allowed": True})
        self.assertEqual(status, 403)

    def test_the_old_per_account_type_route_is_gone(self) -> None:
        status, _ = self._request("POST", "/api/admin/users/fam%40example.com/account-type", self.admin_token, {"accountType": "business"})
        self.assertEqual(status, 404)
        status, payload = self._request("GET", "/api/admin/users", self.admin_token)
        self.assertEqual(status, 200, payload)
        self.assertTrue(all("accountType" not in user for user in payload["users"]))

    def test_a_switched_off_voice_note_is_refused_before_it_is_transcribed(self) -> None:
        self.database.set_feature_switch(feature_id="voice_notes", allowed=False)
        with mock.patch("packages.infrastructure.portal_auth.server.transcribe_voice_note") as transcribe:
            status, payload = self._request("POST", "/api/agent/transcribe", self.family_token, {"voiceNote": {}})
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["error"], "not_included")
        transcribe.assert_not_called()

    def test_the_loop_hides_a_switched_off_feature(self) -> None:
        self.database.set_feature_switch(feature_id="lists", allowed=False)
        descriptions: dict[str, str] = {}

        def model(**kwargs):
            descriptions.update({tool["name"]: tool["description"] for tool in kwargs.get("tools") or []})
            text = json.dumps({"reply": "Hi.", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, "answersOpenQuestion": None})
            return SimpleNamespace(output_text=text, raw_response={"output": []})

        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=model):
            status, payload = self._request(
                "POST", "/api/agent/loop", self.family_token,
                {"userMessage": "hello", "timezone": "UTC", "channel": "whatsapp"},
            )
        self.assertEqual(status, 200, payload)
        self.assertIn("Lists is not included in this account", descriptions["create_list"])
        self.assertNotIn("not included", descriptions["remember_fact"])


if __name__ == "__main__":
    unittest.main()
