"""A WhatsApp message cut off by a deploy is answered on redelivery, and a
stopping server waits for the turns it is still running."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
import urllib.request as urllib_request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import (
    InFlightRequests,
    PortalConfig,
    ShutdownRequested,
    create_server,
    drain_in_flight_requests,
)
from packages.infrastructure.portal_db import PortalDatabase


PLATFORM = "platform-phone-1"
APP_SECRET = "redelivery-test-secret"
PHONE = "972507322341"


class ClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_same_server_never_takes_its_own_open_claim_twice(self) -> None:
        self.assertTrue(self.database.claim_whatsapp_message_id("wamid.a", owner="server-1"))
        self.assertFalse(self.database.claim_whatsapp_message_id("wamid.a", owner="server-1"), "still answering it")

    def test_an_open_claim_from_a_dead_server_is_taken_over(self) -> None:
        self.assertTrue(self.database.claim_whatsapp_message_id("wamid.b", owner="server-1"))
        self.assertTrue(self.database.claim_whatsapp_message_id("wamid.b", owner="server-2"), "server-1 died mid-turn")
        self.assertFalse(self.database.claim_whatsapp_message_id("wamid.b", owner="server-2"))

    def test_a_finished_claim_is_a_duplicate_for_everyone(self) -> None:
        self.assertTrue(self.database.claim_whatsapp_message_id("wamid.c", owner="server-1"))
        self.database.finish_whatsapp_message_id("wamid.c")
        self.assertFalse(self.database.claim_whatsapp_message_id("wamid.c", owner="server-1"))
        self.assertFalse(self.database.claim_whatsapp_message_id("wamid.c", owner="server-2"))

    def test_a_claim_without_an_owner_is_never_taken_over(self) -> None:
        self.assertTrue(self.database.claim_whatsapp_message_id("wamid.d"))
        self.assertFalse(self.database.claim_whatsapp_message_id("wamid.d"))
        self.assertFalse(self.database.claim_whatsapp_message_id("wamid.d", owner="server-2"), "a nameless claim looks alive")

    def test_claims_from_before_the_finished_mark_are_treated_as_answered(self) -> None:
        import sqlite3

        path = Path(self.temp_dir.name) / "old.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE whatsapp_processed_messages (message_id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
            conn.execute("INSERT INTO whatsapp_processed_messages VALUES ('wamid.old', '2026-09-01T00:00:00+00:00')")
            conn.commit()
        upgraded = PortalDatabase(path)
        self.assertFalse(upgraded.claim_whatsapp_message_id("wamid.old", owner="server-9"))


class RedeliveryOverWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="redelivery-session-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.database.link_user_whatsapp_number(user_id=int(self.user["id"]), wa_id=PHONE)
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET, "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM, "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
        }, clear=False)
        self.env.start()
        self.send_patch = mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.reply")
        self.sent = self.send_patch.start()
        self.model_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps({"outcome": "message", "reply": "Yes, you can."})))
        self.model = self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop(); self.send_patch.stop(); self.env.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.temp_dir.cleanup()

    def _post(self, text, *, message_id):
        message = {"from": PHONE, "id": message_id, "timestamp": "1756700000", "type": "text", "text": {"body": text}}
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
            "contacts": [{"profile": {"name": "Nimrod"}, "wa_id": PHONE}], "messages": [message]}}]}]}
        body = json.dumps(payload).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_a_message_a_dead_server_never_answered_is_answered_on_redelivery(self) -> None:
        # The server that took the first delivery was replaced by a deploy in
        # the middle of the turn: the claim is open under its name and no
        # reply went out.
        self.assertTrue(self.database.claim_whatsapp_message_id("wamid.cut-off", owner="the-server-a-deploy-replaced"))
        result = self._post("Can I connect another email address?", message_id="wamid.cut-off")
        self.assertEqual(result["results"][0]["action"], "agent_chat_reply", result)
        self.assertEqual(self.model.call_count, 1)
        self.assertTrue(any("Yes, you can." in (c.kwargs.get("message_text") or "") for c in self.sent.call_args_list))

    def test_an_answered_message_stays_a_duplicate_across_deploys(self) -> None:
        first = self._post("hello", message_id="wamid.answered")
        self.assertEqual(first["results"][0]["action"], "agent_chat_reply")
        with mock.patch("packages.infrastructure.portal_auth.server.SERVER_BOOT_ID", "the-next-server"):
            second = self._post("hello", message_id="wamid.answered")
        self.assertEqual(second["results"][0]["type"], "duplicate")
        self.assertEqual(self.model.call_count, 1, "a redelivery after a deploy must not reach the model again")


class DrainTests(unittest.TestCase):
    def test_the_counter_goes_idle_when_the_last_request_leaves(self) -> None:
        in_flight = InFlightRequests()
        in_flight.enter(); in_flight.enter()
        self.assertFalse(in_flight.wait_until_idle(0.05))
        in_flight.leave()
        threading.Timer(0.1, in_flight.leave).start()
        started = time.monotonic()
        self.assertTrue(in_flight.wait_until_idle(5))
        self.assertLess(time.monotonic() - started, 2)

    def test_a_stopping_server_waits_for_a_request_still_running(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(temp_dir.name) / "portal.db", session_secret="drain-session-secret"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        release = threading.Event()
        original = server.RequestHandlerClass.func.do_GET  # type: ignore[attr-defined]

        def slow_get(handler):
            if handler.path == "/slow":
                release.wait(5)
                handler.send_response(200); handler.send_header("Content-Length", "2"); handler.end_headers()
                handler.wfile.write(b"ok")
                return
            original(handler)

        with mock.patch.object(server.RequestHandlerClass.func, "do_GET", slow_get):  # type: ignore[attr-defined]
            outcome: dict[str, bytes] = {}
            client = threading.Thread(
                target=lambda: outcome.setdefault("body", urllib_request.urlopen(f"{base_url}/slow", timeout=10).read()))
            client.start()
            deadline = time.monotonic() + 5
            while server.in_flight.count == 0 and time.monotonic() < deadline:  # type: ignore[attr-defined]
                time.sleep(0.01)
            self.assertEqual(server.in_flight.count, 1)  # type: ignore[attr-defined]

            # Too short a wait gives up, and the server is told not to hang on close.
            self.assertFalse(drain_in_flight_requests(server, 0.05))
            self.assertFalse(server.block_on_close)

            # A long enough wait sees the request through.
            threading.Timer(0.1, release.set).start()
            self.assertTrue(drain_in_flight_requests(server, 5))
            client.join(timeout=5)
            self.assertEqual(outcome.get("body"), b"ok")

        server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
