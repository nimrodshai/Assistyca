from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key
from packages.infrastructure.portal_auth.server import create_server


class AccountDeletionTests(unittest.TestCase):
    """The account holder's own route to erasure, without an admin in the loop."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.receipt_root = Path(self.temp_dir.name) / "agent-receipts"
        self.server = self._start_server()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _start_server(self, **config_overrides: object):
        server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                agent_output_dir=self.receipt_root,
                **config_overrides,  # type: ignore[arg-type]
            ),
        )
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()
        return server

    def _cookie(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request) as response:
            return response.headers.get("Set-Cookie", "").split(";", 1)[0]

    def _delete_account(self, cookie: str):
        request = urllib_request.Request(
            f"{self.base_url}/api/account",
            headers={"Cookie": cookie},
            method="DELETE",
        )
        with urllib_request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_account_delete_requires_authentication(self) -> None:
        request = urllib_request.Request(f"{self.base_url}/api/account", method="DELETE")

        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request)

        self.assertEqual(context.exception.code, 401)

    def test_account_delete_removes_the_account_and_what_was_saved_with_it(self) -> None:
        self.server.database.register_user("owner@example.com")
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext="cipher-google",
            secret_hint="google",
            secret_fingerprint="google-grant",
            provider="google",
            account_address="owner@example.com",
        )
        owner_folder = self.receipt_root / build_agent_receipt_owner_key("owner@example.com") / "receipts-2026-08"
        owner_folder.mkdir(parents=True)
        (owner_folder / "receipts.xlsx").write_text("rows", encoding="utf-8")
        cookie = self._cookie()

        payload = self._delete_account(cookie)

        self.assertTrue(payload["ok"])
        self.assertIsNone(self.server.database.get_user("owner@example.com"))
        self.assertEqual(self.server.database.list_platform_connections("owner@example.com"), [])
        self.assertFalse(owner_folder.parent.exists())

    def test_account_delete_takes_each_family_members_saved_files_too(self) -> None:
        from datetime import datetime, timedelta, timezone

        database = self.server.database
        database.register_user("owner@example.com")
        user_id = int(database.get_user("owner@example.com")["id"])
        member = database.save_household_member(user_id=user_id, name="Yoav", role="partner")
        database.create_household_invite(
            user_id=user_id, member_id=int(member["id"]), code="YOAV55",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.assertTrue(database.claim_household_invite(code="YOAV55", wa_id="972500000002")["ok"])
        partner_folder = self.receipt_root / build_agent_receipt_owner_key("owner@example.com", "972500000002") / "Receipts"
        partner_folder.mkdir(parents=True)
        (partner_folder / "yoav.pdf").write_bytes(b"%PDF")

        self.assertTrue(self._delete_account(self._cookie())["ok"])
        self.assertFalse(partner_folder.parent.exists())

    def _partner_with_receipts(self, phone: str = "972500000002") -> tuple[int, Path]:
        from datetime import datetime, timedelta, timezone

        database = self.server.database
        database.register_user("owner@example.com")
        user_id = int(database.get_user("owner@example.com")["id"])
        member = database.save_household_member(user_id=user_id, name="Yoav", role="partner")
        database.create_household_invite(
            user_id=user_id, member_id=int(member["id"]), code="YOAV55",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.assertTrue(database.claim_household_invite(code="YOAV55", wa_id=phone)["ok"])
        database.create_account_receipt(
            user_id=user_id, record={"vendor": "Pharmacy", "amount": "40", "receiptDate": "2026-10-01", "ownerWaId": phone},
        )
        database.create_account_receipt(
            user_id=user_id, record={"vendor": "Bakery", "amount": "12", "receiptDate": "2026-10-02"},
        )
        folder = self.receipt_root / build_agent_receipt_owner_key("owner@example.com", phone) / "Receipts"
        folder.mkdir(parents=True)
        (folder / "yoav.pdf").write_bytes(b"%PDF")
        return user_id, folder

    def test_taking_a_partner_off_the_family_takes_their_receipts_and_files(self) -> None:
        user_id, partner_folder = self._partner_with_receipts()
        cookie = self._cookie()
        request = urllib_request.Request(
            f"{self.base_url}/api/household/members/Yoav",
            headers={"Cookie": cookie, "Origin": self.base_url},
            method="DELETE",
        )
        with urllib_request.urlopen(request) as response:
            self.assertEqual(response.status, 200)

        left = self.server.database.list_account_receipts(user_id=user_id, owner_wa_id=None)
        self.assertEqual([row["vendor"] for row in left], ["Bakery"])
        self.assertFalse(partner_folder.parent.exists())

    def test_account_delete_takes_the_files_of_someone_who_already_left(self) -> None:
        # Taken off before leaving cleared their files: the folder is still
        # on disk, and only the departure and the receipt rows remember it.
        user_id, partner_folder = self._partner_with_receipts()
        self.server.database.remove_household_member(user_id=user_id, name="Yoav")
        stray_folder = self.receipt_root / build_agent_receipt_owner_key("owner@example.com", "972500000009") / "Receipts"
        stray_folder.mkdir(parents=True)
        self.server.database.create_account_receipt(
            user_id=user_id, record={"vendor": "Garage", "amount": "300", "receiptDate": "2026-10-03", "ownerWaId": "972500000009"},
        )
        self.assertTrue(partner_folder.is_dir())

        self.assertTrue(self._delete_account(self._cookie())["ok"])
        self.assertFalse(partner_folder.parent.exists())
        self.assertFalse(stray_folder.parent.exists())

    def test_account_delete_takes_the_whatsapp_signup_conversation_with_it(self) -> None:
        # The signup row is keyed on the phone, not the account: it holds the
        # name, the business and the first messages, and no cascade reaches it.
        database = self.server.database
        database.register_user("owner@example.com")
        user_id = int((database.get_user("owner@example.com") or {}).get("id") or 0)
        database.start_whatsapp_signup(wa_id="972501234567", sender_name="Nimrod")
        database.complete_whatsapp_signup(wa_id="972501234567", user_id=user_id)
        database.link_user_whatsapp_number(user_id=user_id, wa_id="972501234567")
        database.start_whatsapp_signup(wa_id="972509999999", sender_name="Someone else")
        cookie = self._cookie()

        self._delete_account(cookie)

        self.assertIsNone(database.get_whatsapp_signup("972501234567"))
        self.assertIsNotNone(database.get_whatsapp_signup("972509999999"))
        # The phone's next message is answered knowing the account is gone.
        self.assertIsNotNone(database.whatsapp_phone_erased_at("972501234567"))
        self.assertIsNone(database.whatsapp_phone_erased_at("972509999999"))

    def test_account_delete_ends_the_session_it_was_asked_from(self) -> None:
        self.server.database.register_user("owner@example.com")
        cookie = self._cookie()

        self._delete_account(cookie)

        request = urllib_request.Request(
            f"{self.base_url}/api/account/profile",
            headers={"Cookie": cookie},
        )
        with self.assertRaises(urllib_error.HTTPError) as context:
            urllib_request.urlopen(request)
        self.assertEqual(context.exception.code, 401)

    def test_account_delete_refuses_to_leave_the_portal_without_an_admin(self) -> None:
        self.server.database.register_user("owner@example.com", is_admin=True)
        cookie = self._cookie()

        with self.assertRaises(urllib_error.HTTPError) as context:
            self._delete_account(cookie)

        self.assertEqual(context.exception.code, 409)
        payload = json.loads(context.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "last_admin")
        self.assertIsNotNone(self.server.database.get_user("owner@example.com"))

    def test_a_seeded_admin_is_registered_again_as_an_empty_account(self) -> None:
        self.tearDown()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.receipt_root = Path(self.temp_dir.name) / "agent-receipts"
        self.server = self._start_server(seed_admin_emails=frozenset({"owner@example.com"}))
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.server.database.register_user("owner@example.com", is_admin=True)
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext="cipher-google",
            secret_hint="google",
            secret_fingerprint="google-grant",
            provider="google",
            account_address="owner@example.com",
        )
        cookie = self._cookie()

        payload = self._delete_account(cookie)

        self.assertTrue(payload["registeredAgain"])
        # The operator's own account is what the seed list restores at every
        # boot, so erasing it empties it rather than locking them out.
        restored = self.server.database.get_user("owner@example.com")
        self.assertIsNotNone(restored)
        self.assertTrue(restored["isAdmin"])
        self.assertIsNone(restored["lastLoginAt"])
        self.assertEqual(self.server.database.list_platform_connections("owner@example.com"), [])


if __name__ == "__main__":
    unittest.main()
