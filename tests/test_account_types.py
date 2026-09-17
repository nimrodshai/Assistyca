"""Account types: business or family, and which features each may use."""

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
from packages.infrastructure.account_types import feature_allowed
from packages.infrastructure.agent_loop import ACCOUNT_RIGHTS_TOOLS
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.portal_db import PortalDatabase


class CatalogueTests(unittest.TestCase):
    def test_every_gated_tool_exists(self) -> None:
        for feature in ACCOUNT_FEATURES:
            for tool in feature.tools:
                self.assertIn(tool, TOOLS_BY_NAME, f"{feature.feature_id} names a tool that does not exist")

    def test_leaving_and_giving_back_are_never_gated(self) -> None:
        gated = {tool for feature in ACCOUNT_FEATURES for tool in feature.tools}
        for tool in (*ACCOUNT_RIGHTS_TOOLS, "connect_link", "forget_fact", "cancel_scheduled", "dismiss_finding", "remove_family_member", "remove_week_activity"):
            self.assertNotIn(tool, gated)

    def test_nothing_is_switched_off_until_someone_does(self) -> None:
        self.assertTrue(feature_allowed({}, "family", "receipts"))
        self.assertTrue(feature_allowed(None, "", "receipts"))
        self.assertEqual(blocked_tools({}, "family"), {})

    def test_a_switch_applies_to_its_own_type_only(self) -> None:
        permissions = {"family": {"receipts": False}, "business": {}}
        self.assertEqual(set(blocked_tools(permissions, "family")), {"search_receipts", "open_receipts"})
        self.assertEqual(blocked_tools(permissions, "business"), {})
        # An account with no type reads as a business.
        self.assertEqual(blocked_tools(permissions, ""), {})

    def test_a_store_that_cannot_answer_leaves_the_feature_on(self) -> None:
        self.assertTrue(account_feature_allowed(object(), user_id=1, feature_id="receipts"))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "portal.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_a_new_account_is_a_business_until_set_otherwise(self) -> None:
        database = PortalDatabase(self.db_path)
        database.register_user("a@example.com")
        self.assertEqual((database.get_user("a@example.com") or {})["accountType"], "business")
        updated = database.update_user_account_type("a@example.com", account_type="family")
        self.assertEqual(updated["accountType"], "family")
        self.assertEqual(database.get_account_type(email="a@example.com"), "family")
        listed = next(user for user in database.list_users() if user["email"] == "a@example.com")
        self.assertEqual(listed["accountType"], "family")
        self.assertEqual(database.count_accounts_by_type(), {"business": 0, "family": 1})
        with self.assertRaises(ValueError):
            database.update_user_account_type("a@example.com", account_type="enterprise")

    def test_switches_are_kept_and_moved_back(self) -> None:
        database = PortalDatabase(self.db_path)
        permissions = database.set_account_type_feature(account_type="family", feature_id="mail", allowed=False)
        self.assertEqual(permissions, {"business": {}, "family": {"mail": False}})
        permissions = database.set_account_type_feature(account_type="family", feature_id="mail", allowed=True)
        self.assertEqual(permissions["family"], {"mail": True})
        with self.assertRaises(ValueError):
            database.set_account_type_feature(account_type="family", feature_id="teleport", allowed=False)

    def test_accounts_opened_as_a_family_before_the_column_existed_are_found(self) -> None:
        database = PortalDatabase(self.db_path)
        database.register_user("fam@example.com")
        database.register_user("biz@example.com")
        fam_id = int((database.get_user("fam@example.com") or {})["id"])
        biz_id = int((database.get_user("biz@example.com") or {})["id"])
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO whatsapp_signups (wa_id, status, user_id, registration_json, started_at, updated_at) VALUES (?, 'completed', ?, ?, 'x', 'x')",
            ("972500000001", fam_id, json.dumps({"kind": "family"})),
        )
        conn.execute(
            "INSERT INTO whatsapp_signups (wa_id, status, user_id, registration_json, started_at, updated_at) VALUES (?, 'completed', ?, ?, 'x', 'x')",
            ("972500000002", biz_id, json.dumps({"kind": "business"})),
        )
        # An older store: the column is not there yet.
        conn.execute("ALTER TABLE users DROP COLUMN account_type")
        conn.commit()
        conn.close()

        reopened = PortalDatabase(self.db_path)
        self.assertEqual(reopened.get_account_type(email="fam@example.com"), "family")
        self.assertEqual(reopened.get_account_type(email="biz@example.com"), "business")


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
        self.database.update_user_account_type("fam@example.com", account_type="family")
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
            return int(exc.code), json.loads(exc.read().decode("utf-8"))

    def test_the_grid_starts_all_on_and_a_switch_sticks(self) -> None:
        status, payload = self._request("GET", "/api/admin/account-types", self.admin_token)
        self.assertEqual(status, 200, payload)
        self.assertEqual([entry["value"] for entry in payload["accountTypes"]], ["business", "family"])
        counts = {entry["value"]: entry["accountCount"] for entry in payload["accountTypes"]}
        self.assertEqual(counts, {"business": 1, "family": 1})
        self.assertTrue(all(all(feature["allowed"].values()) for feature in payload["features"]))

        status, payload = self._request(
            "POST", "/api/admin/account-types", self.admin_token,
            {"accountType": "family", "featureId": "voice_notes", "allowed": False},
        )
        self.assertEqual(status, 200, payload)
        voice = next(feature for feature in payload["features"] if feature["featureId"] == "voice_notes")
        self.assertEqual(voice["allowed"], {"business": True, "family": False})

    def test_a_client_cannot_see_or_move_the_switches(self) -> None:
        status, _ = self._request("GET", "/api/admin/account-types", self.family_token)
        self.assertEqual(status, 403)
        status, _ = self._request(
            "POST", "/api/admin/account-types", self.family_token,
            {"accountType": "family", "featureId": "mail", "allowed": True},
        )
        self.assertEqual(status, 403)

    def test_an_admin_moves_a_client_between_types(self) -> None:
        status, payload = self._request(
            "POST", "/api/admin/users/fam%40example.com/account-type", self.admin_token, {"accountType": "business"},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["accountType"], "business")
        self.assertEqual(self.database.get_account_type(email="fam@example.com"), "business")

    def test_a_switched_off_voice_note_is_refused_before_it_is_transcribed(self) -> None:
        self.database.set_account_type_feature(account_type="family", feature_id="voice_notes", allowed=False)
        with mock.patch("packages.infrastructure.portal_auth.server.transcribe_voice_note") as transcribe:
            status, payload = self._request("POST", "/api/agent/transcribe", self.family_token, {"voiceNote": {}})
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["error"], "not_included")
        transcribe.assert_not_called()

    def test_the_loop_hides_a_switched_off_feature_from_a_family(self) -> None:
        self.database.set_account_type_feature(account_type="family", feature_id="lists", allowed=False)
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
