from __future__ import annotations

import base64
import json
import tempfile
import time
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import DEFAULT_SESSION_MAX_LIFETIME_SECONDS
from packages.infrastructure.portal_auth.server import DEFAULT_SESSION_TTL_SECONDS
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import PortalSession
from packages.infrastructure.portal_auth.server import SESSION_COOKIE_NAME
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import create_session_token
from packages.infrastructure.portal_auth.server import parse_session_token

DAY = 24 * 60 * 60


class PortalAuthSessionTests(unittest.TestCase):
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

    def _restart_server(self) -> None:
        """Rebuild the server over the same database, as a redeploy would."""

        port = self.server.server_address[1]
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server = create_server(
            "127.0.0.1",
            port,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="test-session-secret",
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _verify_otp_and_get_cookie(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({
                "email": email,
                "code": code,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            cookie_header = response.headers.get("Set-Cookie", "")
            self.assertIn(f"{SESSION_COOKIE_NAME}=", cookie_header)
            return cookie_header.split(";", 1)[0]

    def _session_status(self, cookie_value: str) -> tuple[int, dict, str]:
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={"Cookie": cookie_value},
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8")), response.headers.get("Set-Cookie", "")
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), exc.headers.get("Set-Cookie", "")

    def _signed_cookie(self, *, authenticated_at: float, issued_at: float, expires_at: float) -> str:
        token = create_session_token(
            PortalSession(
                token="",
                email="owner@example.com",
                issued_at=issued_at,
                expires_at=expires_at,
                authenticated_at=authenticated_at,
            ),
            b"test-session-secret",
        )
        return f"{SESSION_COOKIE_NAME}={token}"

    def test_a_session_lasts_a_month_and_the_code_is_asked_again_after_three(self) -> None:
        self.assertEqual(DEFAULT_SESSION_TTL_SECONDS, 30 * DAY)
        self.assertEqual(DEFAULT_SESSION_MAX_LIFETIME_SECONDS, 90 * DAY)
        cookie_value = self._verify_otp_and_get_cookie()

        _, payload, _ = self._session_status(cookie_value)

        self.assertEqual(payload["expiresAt"] - payload["issuedAt"], 30 * DAY * 1000)

    def test_a_fresh_cookie_is_left_alone(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        status, _, set_cookie = self._session_status(cookie_value)

        self.assertEqual(status, 200)
        self.assertEqual(set_cookie, "")

    def test_a_cookie_older_than_a_day_is_renewed_and_keeps_its_sign_in_time(self) -> None:
        now = time.time()
        signed_in_at = now - 2 * DAY
        cookie_value = self._signed_cookie(
            authenticated_at=signed_in_at,
            issued_at=signed_in_at,
            expires_at=signed_in_at + 30 * DAY,
        )

        status, _, set_cookie = self._session_status(cookie_value)

        self.assertEqual(status, 200)
        self.assertIn(f"{SESSION_COOKIE_NAME}=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        renewed_token = set_cookie.split(";", 1)[0].split("=", 1)[1]
        renewed = parse_session_token(renewed_token, b"test-session-secret")
        assert renewed is not None
        self.assertNotIn(renewed_token, cookie_value)
        self.assertAlmostEqual(renewed.authenticated_at, signed_in_at, places=3)
        self.assertGreaterEqual(renewed.issued_at, int(now))
        self.assertAlmostEqual(renewed.expires_at, renewed.issued_at + 30 * DAY, delta=2)

    def test_renewal_never_reaches_past_ninety_days_from_the_sign_in(self) -> None:
        now = time.time()
        signed_in_at = now - 85 * DAY
        cookie_value = self._signed_cookie(
            authenticated_at=signed_in_at,
            issued_at=now - 2 * DAY,
            expires_at=signed_in_at + 90 * DAY,
        )

        status, _, set_cookie = self._session_status(cookie_value)

        self.assertEqual(status, 200)
        self.assertEqual(set_cookie, "")

    def test_a_session_signed_in_more_than_ninety_days_ago_is_refused(self) -> None:
        now = time.time()
        cookie_value = self._signed_cookie(
            authenticated_at=now - 91 * DAY,
            issued_at=now - DAY,
            expires_at=now + 29 * DAY,
        )

        status, _, _ = self._session_status(cookie_value)

        self.assertEqual(status, 401)

    def test_a_token_from_before_renewals_still_signs_in(self) -> None:
        now = time.time()
        session = PortalSession(token="", email="owner@example.com", issued_at=now - DAY, expires_at=now + 29 * DAY)
        token = create_session_token(session, b"test-session-secret")
        stripped = json.loads(base64.urlsafe_b64decode(token.split(".", 1)[0] + "==").decode("utf-8"))
        stripped.pop("auth")
        # Re-sign the payload the way the old server wrote it: no sign-in time.
        from packages.infrastructure.portal_auth.server import encode_token_segment, sign_token_segment
        payload_segment = encode_token_segment(json.dumps(stripped, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        old_token = f"{payload_segment}.{sign_token_segment(payload_segment, b'test-session-secret')}"

        status, payload, _ = self._session_status(f"{SESSION_COOKIE_NAME}={old_token}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["email"], "owner@example.com")

    def test_logging_out_everywhere_ends_the_other_device_too(self) -> None:
        phone_cookie = self._verify_otp_and_get_cookie()
        laptop_cookie = self._verify_otp_and_get_cookie()
        self.assertNotEqual(phone_cookie, laptop_cookie)

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/logout",
            data=json.dumps({"everywhere": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": laptop_cookie},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["everywhere"])
            self.assertEqual(response.headers.get_all("Set-Cookie"), [response.headers.get("Set-Cookie")])
            self.assertIn("Max-Age=0", response.headers.get("Set-Cookie", ""))

        self.assertEqual(self._session_status(phone_cookie)[0], 401)
        self.assertEqual(self._session_status(laptop_cookie)[0], 401)

        self._restart_server()
        self.assertEqual(self._session_status(phone_cookie)[0], 401)

        fresh_cookie = self._verify_otp_and_get_cookie()
        self.assertEqual(self._session_status(fresh_cookie)[0], 200)

    def test_a_plain_log_out_leaves_the_other_device_signed_in(self) -> None:
        phone_cookie = self._verify_otp_and_get_cookie()
        laptop_cookie = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/logout",
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": laptop_cookie},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            self.assertFalse(json.loads(response.read().decode("utf-8"))["everywhere"])

        self.assertEqual(self._session_status(phone_cookie)[0], 200)

    def test_session_can_be_restored_from_cookie_without_authorization_header(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={"Cookie": cookie_value},
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["signedIn"])
        self.assertEqual(payload["email"], "owner@example.com")
        self.assertNotIn("token", payload)

    def test_valid_cookie_wins_when_bearer_token_is_stale(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={
                "Authorization": "Bearer stale-token",
                "Cookie": cookie_value,
            },
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["signedIn"])
        self.assertEqual(payload["email"], "owner@example.com")

    def test_session_cookie_is_http_only_and_same_site(self) -> None:
        code, _ = self.server.store.issue_challenge("owner@example.com")
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({"email": "owner@example.com", "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            cookie_header = response.headers.get("Set-Cookie", "")

        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Lax", cookie_header)
        self.assertIn("Path=/", cookie_header)

    def test_session_token_in_the_query_string_is_ignored(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()
        token = cookie_value.split("=", 1)[1]

        # A token that authenticates over the cookie must not authenticate when it
        # is smuggled through the URL, where it would leak into logs and Referer.
        request = urllib_request.Request(f"{self.base_url}/api/auth/session?token={token}")
        try:
            with urllib_request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            self.assertIn(exc.code, (401, 403))
            payload = json.loads(exc.read().decode("utf-8"))

        self.assertFalse(payload.get("signedIn"))

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={"Cookie": cookie_value},
        )
        with urllib_request.urlopen(request) as response:
            self.assertTrue(json.loads(response.read().decode("utf-8"))["signedIn"])

    def test_logout_revokes_the_session_named_by_the_cookie_alone(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/logout",
            data=b"{}",
            headers={"Content-Type": "application/json", "Cookie": cookie_value},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("Max-Age=0", response.headers.get("Set-Cookie", ""))

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={"Cookie": cookie_value},
        )
        try:
            with urllib_request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            self.assertIn(exc.code, (401, 403))
            payload = json.loads(exc.read().decode("utf-8"))

        self.assertFalse(payload.get("signedIn"))

    def test_verify_reply_carries_no_copy_of_the_session_token(self) -> None:
        code, _ = self.server.store.issue_challenge("owner@example.com")
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({"email": "owner@example.com", "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            cookie_header = response.headers.get("Set-Cookie", "")

        # The cookie is the only place the token is allowed to live. A copy in
        # the body would be readable by any script on the page, which is what
        # the httpOnly cookie exists to prevent.
        self.assertIn(f"{SESSION_COOKIE_NAME}=", cookie_header)
        self.assertNotIn("sessionToken", payload)
        self.assertNotIn("token", payload)

    def test_signing_out_still_holds_after_the_server_restarts(self) -> None:
        cookie_value = self._verify_otp_and_get_cookie()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/logout",
            data=b"{}",
            headers={"Content-Type": "application/json", "Cookie": cookie_value},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            self.assertEqual(response.status, 200)

        # A restart empties everything the process was holding. The revocation
        # has to come back from the database, or the signed-out token works
        # again for the rest of its six months.
        self._restart_server()

        request = urllib_request.Request(
            f"{self.base_url}/api/auth/session",
            headers={"Cookie": cookie_value},
        )
        try:
            with urllib_request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            self.assertIn(exc.code, (401, 403))
            payload = json.loads(exc.read().decode("utf-8"))

        self.assertFalse(payload.get("signedIn"))

    def test_opportunities_owner_can_manage_clients_without_admin_flag(self) -> None:
        owner_email = "nimrod.shai@gmail.com"
        client_email = "client@example.com"
        self.server.database.register_user(owner_email, is_admin=False)
        self.server.database.register_user(client_email)
        cookie_value = self._verify_otp_and_get_cookie(owner_email)

        request = urllib_request.Request(
            f"{self.base_url}/api/admin/users",
            headers={"Cookie": cookie_value},
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["currentUser"]["isAdmin"])
        self.assertIn(client_email, {user["email"] for user in payload["users"]})

    def test_opportunities_owner_can_update_client_type_without_admin_flag(self) -> None:
        owner_email = "nimrod.shai@gmail.com"
        client_email = "client@example.com"
        self.server.database.register_user(owner_email, is_admin=False)
        self.server.database.register_user(client_email)
        cookie_value = self._verify_otp_and_get_cookie(owner_email)

        update_request = urllib_request.Request(
            f"{self.base_url}/api/admin/users/{client_email}/client-type",
            data=json.dumps({"clientType": "qa"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": cookie_value,
            },
            method="POST",
        )
        with urllib_request.urlopen(update_request) as response:
            update_payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(update_payload["ok"])
        self.assertEqual(update_payload["user"]["clientType"], "qa")
        self.assertEqual(self.server.database.get_user(client_email)["clientType"], "qa")


    def test_admin_client_list_reports_monthly_spend_and_demo_billing_state(self) -> None:
        owner_email = "nimrod.shai@gmail.com"
        demo_email = "demo@example.com"
        paying_email = "paying@example.com"
        self.server.database.register_user(owner_email, is_admin=True)
        self.server.database.register_user(demo_email)
        self.server.database.register_user(paying_email)
        self.server.database.update_user_client_type(demo_email, client_type="demo")
        self.server.database.update_user_client_type(paying_email, client_type="paying")
        for email in (demo_email, paying_email):
            self.server.database.record_usage(
                email,
                "gpt-5.5",
                tool_id="assistant",
                input_tokens=1000,
                output_tokens=1000,
            )
        cookie_value = self._verify_otp_and_get_cookie(owner_email)

        request = urllib_request.Request(
            f"{self.base_url}/api/admin/users",
            headers={"Cookie": cookie_value},
        )
        with urllib_request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        users_by_email = {user["email"]: user for user in payload["users"]}
        demo_spend = users_by_email[demo_email]["spend"]
        paying_spend = users_by_email[paying_email]["spend"]

        self.assertFalse(demo_spend["isBilled"])
        self.assertIn("never billed", demo_spend["billingNote"])
        self.assertGreater(demo_spend["currentMonth"]["usageUsd"], 0)
        self.assertEqual(demo_spend["currentMonth"]["billedUsd"], 0.0)
        self.assertIn("previousMonths", demo_spend)

        self.assertTrue(paying_spend["isBilled"])
        self.assertEqual(paying_spend["billingNote"], "")
        self.assertGreater(paying_spend["currentMonth"]["usageUsd"], 0)
        self.assertGreaterEqual(
            paying_spend["currentMonth"]["billedUsd"],
            paying_spend["currentMonth"]["usageUsd"],
        )


if __name__ == "__main__":
    unittest.main()
