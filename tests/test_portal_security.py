from __future__ import annotations

import http.client as http_client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key
from packages.infrastructure.portal_auth.server import create_server


class PortalSecurityTests(unittest.TestCase):
    """The doors that must stay shut: webhook verification, cross-site writes, oversized bodies."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="test-session-secret",
                agent_output_dir=Path(self.temp_dir.name) / "agent_receipts",
            ),
        )
        self.server.database.register_user("owner@example.com")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib_error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def _cookie(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        status, _, headers = self._request(
            "/api/auth/otp/verify",
            method="POST",
            body=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    # --- WhatsApp webhook verification ------------------------------------

    def test_webhook_verification_answers_the_challenge_with_the_right_token(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "verify-token"}):
            status, body, _ = self._request(
                "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=12345",
            )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"12345")

    def test_webhook_verification_rejects_the_wrong_token(self) -> None:
        with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "verify-token"}):
            status, _, _ = self._request(
                "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=guess&hub.challenge=12345",
            )

        self.assertEqual(status, 403)

    def test_webhook_verification_fails_closed_without_a_configured_token(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHATSAPP_VERIFY_TOKEN", None)
            status, body, _ = self._request(
                "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=&hub.challenge=12345",
            )

        self.assertEqual(status, 503)
        self.assertNotIn(b"12345", body)

    # --- cross-site writes ----------------------------------------------------

    def _logout(self, cookie: str, extra_headers: dict[str, str]) -> int:
        status, _, _ = self._request(
            "/api/auth/logout",
            method="POST",
            body=b"{}",
            headers={"Content-Type": "application/json", "Cookie": cookie, **extra_headers},
        )
        return status

    def _signed_in(self, cookie: str) -> bool:
        status, _, _ = self._request("/api/auth/session", headers={"Cookie": cookie})
        return status == 200

    def test_a_write_from_another_site_is_refused_before_it_can_act(self) -> None:
        cookie = self._cookie()

        status = self._logout(cookie, {"Origin": "https://evil.example"})

        self.assertEqual(status, 403)
        self.assertTrue(self._signed_in(cookie))

    def test_a_write_from_our_own_origin_goes_through(self) -> None:
        cookie = self._cookie()

        status = self._logout(cookie, {"Origin": self.base_url})

        self.assertEqual(status, 200)
        self.assertFalse(self._signed_in(cookie))

    def test_the_public_address_counts_as_our_own_origin_behind_a_proxy(self) -> None:
        cookie = self._cookie()

        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://portal.example.com/"}):
            status = self._logout(cookie, {"Origin": "https://portal.example.com"})

        self.assertEqual(status, 200)

    def test_the_www_twin_of_the_public_address_is_the_same_site(self) -> None:
        cookie = self._cookie()

        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://assistyca.example"}):
            status = self._logout(cookie, {"Origin": "https://www.assistyca.example"})

        self.assertEqual(status, 200)

    def test_an_origin_named_in_the_environment_is_allowed(self) -> None:
        cookie = self._cookie()

        with mock.patch.dict(os.environ, {"PORTAL_ALLOWED_ORIGINS": "https://www.assistyca.example, https://app.assistyca.example"}):
            status = self._logout(cookie, {"Origin": "https://app.assistyca.example"})

        self.assertEqual(status, 200)

    def test_a_browser_that_says_cross_site_is_refused_even_without_an_origin(self) -> None:
        cookie = self._cookie()

        status = self._logout(cookie, {"Sec-Fetch-Site": "cross-site"})

        self.assertEqual(status, 403)
        self.assertTrue(self._signed_in(cookie))

    def test_a_client_that_is_not_a_browser_is_let_through_to_prove_itself(self) -> None:
        cookie = self._cookie()

        status = self._logout(cookie, {})

        self.assertEqual(status, 200)

    def test_a_delete_from_another_site_is_refused_too(self) -> None:
        cookie = self._cookie()

        status, _, _ = self._request(
            "/api/account",
            method="DELETE",
            headers={"Cookie": cookie, "Origin": "https://evil.example"},
        )

        self.assertEqual(status, 403)
        self.assertTrue(self._signed_in(cookie))

    # --- cross-origin reads ---------------------------------------------------

    def test_another_origin_is_never_allowed_to_read_the_api(self) -> None:
        _, _, headers = self._request("/api/pricing", headers={"Origin": "https://evil.example"})

        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_our_own_origin_is_named_back_and_never_a_wildcard(self) -> None:
        _, _, headers = self._request("/api/pricing", headers={"Origin": self.base_url})

        self.assertEqual(headers.get("Access-Control-Allow-Origin"), self.base_url)
        self.assertEqual(headers.get("Vary"), "Origin")

    def test_a_preflight_from_another_origin_grants_nothing(self) -> None:
        status, _, headers = self._request(
            "/api/lists",
            method="OPTIONS",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )

        self.assertEqual(status, 204)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn("Access-Control-Allow-Methods", headers)

    # --- body sizes -----------------------------------------------------------

    def _oversized_json(self, size: int) -> bytes:
        return json.dumps({"padding": "x" * size}).encode("utf-8")

    def _post_large(self, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        """Send a big body the way a browser would, and read the answer even if the
        server refused before taking all of it."""

        host, port = self.base_url.removeprefix("http://").split(":")
        connection = http_client.HTTPConnection(host, int(port), timeout=10)
        connection.putrequest("POST", path)
        for name, value in {"Content-Type": "application/json", "Content-Length": str(len(body)), **headers}.items():
            connection.putheader(name, value)
        connection.endheaders()
        try:
            for start in range(0, len(body), 64 * 1024):
                connection.send(body[start:start + 64 * 1024])
        except (BrokenPipeError, ConnectionResetError):
            pass
        response = connection.getresponse()
        return response.status, response.read()

    def test_an_ordinary_signed_in_request_stops_at_a_megabyte(self) -> None:
        cookie = self._cookie()

        status, body = self._post_large("/api/lists", self._oversized_json(2 * 1024 * 1024), {"Cookie": cookie})

        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"], "payload_too_large")

    def test_a_public_request_stops_far_sooner(self) -> None:
        status, _ = self._post_large("/api/contact", self._oversized_json(300 * 1024), {})

        self.assertEqual(status, 413)

    # --- saved files ----------------------------------------------------------

    def _saved_file(self, name: str, content: bytes) -> str:
        owner_key = build_agent_receipt_owner_key("owner@example.com")
        folder = Path(self.temp_dir.name) / "agent_receipts" / owner_key
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        return f"/output/agent_receipts/{owner_key}/{name}"

    def test_a_saved_pdf_opens_in_the_browser(self) -> None:
        cookie = self._cookie()
        path = self._saved_file("receipt.pdf", b"%PDF-1.4\n")

        status, _, headers = self._request(path, headers={"Cookie": cookie})

        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Disposition"].startswith("inline;"))

    def test_a_saved_file_that_is_not_a_pdf_or_picture_is_offered_as_a_download(self) -> None:
        cookie = self._cookie()
        path = self._saved_file("report.html", b"<script>alert(1)</script>")

        status, _, headers = self._request(path, headers={"Cookie": cookie})

        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        self.assertIn('filename="report.html"', headers["Content-Disposition"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_a_saved_file_is_not_served_to_a_stranger(self) -> None:
        path = self._saved_file("receipt.pdf", b"%PDF-1.4\n")

        status, _, _ = self._request(path)

        self.assertEqual(status, 404)

    def _raw_get(self, path: str, cookie: str) -> int:
        # http.client sends the path exactly as written, dots and all, the way
        # a hand-made request would.
        connection = http_client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            connection.request("GET", path, headers={"Cookie": cookie})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def _plant(self, owner_key: str) -> None:
        folder = Path(self.temp_dir.name) / "agent_receipts" / owner_key / "Receipts" / "Oct2026"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "bundle.json").write_text("{\"secret\": true}", encoding="utf-8")

    def test_a_saved_file_address_cannot_climb_into_another_accounts_folder(self) -> None:
        self.server.database.register_user("victim@example.com")
        cookie = self._cookie()
        own_key = build_agent_receipt_owner_key("owner@example.com")
        victim_key = build_agent_receipt_owner_key("victim@example.com")
        self._plant(own_key)
        self._plant(victim_key)
        tail = f"{victim_key}/Receipts/Oct2026/bundle.json"

        # The caller's own file still opens, so the refusals below are the climb.
        self.assertEqual(self._raw_get(f"/output/agent_receipts/{own_key}/Receipts/Oct2026/bundle.json", cookie), 200)
        for climb in ("..", "%2e%2e", "%2E%2E", "%2e.", "%252e%252e", "..%5C..", "./.."):
            with self.subTest(climb=climb):
                status = self._raw_get(f"/output/agent_receipts/{own_key}/{climb}/{tail}", cookie)
                self.assertEqual(status, 404)
        self.assertEqual(self._raw_get(f"/output/agent_receipts/{own_key}/..%5C{tail}", cookie), 404)
        self.assertEqual(self._raw_get(f"/output/agent_receipts/{own_key}%2F..%2F{tail}", cookie), 404)

    def test_a_saved_file_address_cannot_climb_into_a_partners_folder(self) -> None:
        cookie = self._cookie()
        own_key = build_agent_receipt_owner_key("owner@example.com")
        partner_key = build_agent_receipt_owner_key("owner@example.com", "972500000002")
        self._plant(partner_key)

        for climb in ("..", "%2e%2e", "%2E%2E"):
            with self.subTest(climb=climb):
                status = self._raw_get(
                    f"/output/agent_receipts/{own_key}/{climb}/{partner_key}/Receipts/Oct2026/bundle.json", cookie,
                )
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
