from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.account_erasure import erase_account
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.whatsapp_portal_service import delete_portal_whatsapp_store_for_connection
from packages.infrastructure.whatsapp_portal_service import portal_whatsapp_store_path_for_connection


DEFAULT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"
FOLLOW_UP_FEATURE_ID = "whatsapp-business-follow-up-outreach-writer"
MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier"


class PortalUserAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_get_user_returns_admin_flag(self) -> None:
        self.database.register_user(
            "admin@example.com",
            display_name="Admin User",
            is_admin=True,
        )

        user = self.database.get_user("admin@example.com")

        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "admin@example.com")
        self.assertEqual(user["displayName"], "Admin User")
        self.assertTrue(user["isAdmin"])

    def test_update_user_client_type_persists_admin_classification(self) -> None:
        self.database.register_user("owner@example.com")

        updated_user = self.database.update_user_client_type("owner@example.com", client_type="QA")
        users = self.database.list_users(include_inactive=True)

        self.assertEqual(updated_user["clientType"], "qa")
        self.assertEqual(users[0]["clientType"], "qa")

    def test_every_client_sees_every_active_tool(self) -> None:
        self.database.register_user("owner@example.com")

        available_features = self.database.list_available_features("owner@example.com")

        self.assertEqual(
            [feature["featureId"] for feature in available_features],
            [DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID],
        )
        for feature_id in (DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID):
            self.assertIsNotNone(self.database.get_available_feature("owner@example.com", feature_id))

    def test_available_tool_carries_the_settings_this_client_saved(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={
                "settings": {
                    "watchItems": [
                        "Court holidays",
                        "Criminal law conferences",
                    ],
                    "intervalDays": 7,
                    "deliveryChannel": "email",
                }
            },
        )

        features = {
            feature["featureId"]: feature
            for feature in self.database.list_available_features("owner@example.com")
        }

        self.assertEqual(
            features[MONITOR_FEATURE_ID]["assignment"]["metadata"]["settings"]["watchItems"],
            ["Court holidays", "Criminal law conferences"],
        )
        self.assertNotIn("assignment", features[FOLLOW_UP_FEATURE_ID])

    def test_delete_user_removes_account_and_related_records(self) -> None:
        self.database.register_user("owner@example.com", is_admin=True)
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={"settings": {"intervalDays": 7}},
        )
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        self.assertEqual(self.database.count_admin_users(), 1)

        deleted_user = self.database.delete_user("owner@example.com")

        self.assertEqual(deleted_user["email"], "owner@example.com")
        self.assertEqual(self.database.count_registered_users(), 0)
        self.assertEqual(self.database.count_admin_users(), 0)
        self.assertIsNone(self.database.get_user("owner@example.com"))
        self.assertIsNone(self.database.get_whatsapp_connection("owner@example.com"))
        with self.database._connection() as conn:
            feature_assignment_row = conn.execute(
                "SELECT COUNT(*) AS count FROM feature_assignments WHERE user_id = ?",
                (int(deleted_user["id"]),),
            ).fetchone()

        self.assertEqual(int(feature_assignment_row["count"] or 0), 0)

    def test_update_user_identity_changes_email_and_name_and_keeps_related_records(self) -> None:
        self.database.register_user("owner@example.com", display_name="Owner")
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
        )

        updated_user = self.database.update_user_identity(
            "owner@example.com",
            email="better@example.com",
            display_name="Better Name",
        )

        self.assertEqual(updated_user["email"], "better@example.com")
        self.assertEqual(updated_user["displayName"], "Better Name")
        self.assertIsNone(self.database.get_user("owner@example.com"))
        self.assertIsNotNone(self.database.get_user("better@example.com"))
        self.assertIsNotNone(self.database.get_whatsapp_connection("better@example.com"))
        self.assertEqual(
            [feature["featureId"] for feature in self.database.list_available_features("better@example.com")],
            [DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID],
        )

    def test_update_user_identity_rejects_duplicate_email(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.register_user("other@example.com")

        with self.assertRaisesRegex(ValueError, "already registered"):
            self.database.update_user_identity(
                "owner@example.com",
                email="other@example.com",
                display_name="Owner",
            )

    def test_inactive_client_stays_visible_to_admin_management(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.save_billing_customer(
            "owner@example.com",
            provider="lemon_squeezy",
            subscription_status="active",
        )

        inactive_user = self.database.update_user_status("owner@example.com", is_active=False)

        self.assertFalse(inactive_user["isActive"])
        self.assertIsNone(self.database.get_billing_customer("owner@example.com"))
        self.assertEqual(
            self.database.get_billing_customer("owner@example.com", include_inactive=True)["subscriptionStatus"],
            "active",
        )
        self.assertEqual(self.database.list_users(include_inactive=False), [])
        self.assertEqual(self.database.list_users(include_inactive=True)[0]["email"], "owner@example.com")

        reactivated_user = self.database.update_user_status("owner@example.com", is_active=True)

        self.assertTrue(reactivated_user["isActive"])
        self.assertEqual(
            [feature["featureId"] for feature in self.database.list_available_features("owner@example.com")],
            [DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID],
        )

    def test_update_user_status_rejects_disabling_last_active_admin(self) -> None:
        self.database.register_user("admin@example.com", is_admin=True)

        with self.assertRaisesRegex(ValueError, "last admin"):
            self.database.update_user_status("admin@example.com", is_active=False)

        self.database.register_user("other@example.com", is_admin=True)
        disabled_user = self.database.update_user_status("admin@example.com", is_active=False)

        self.assertFalse(disabled_user["isActive"])
        self.assertEqual(self.database.count_admin_users(), 1)

    def test_reopening_a_database_drops_the_old_per_client_access_columns(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={"settings": {"intervalDays": 7}},
        )

        # An older portal database gated each tool per client. Put those columns back
        # and reopen, the way a deploy meets a database written by the previous build.
        with self.database._connection() as conn:
            conn.execute("ALTER TABLE feature_assignments ADD COLUMN is_assigned INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE features ADD COLUMN default_assigned INTEGER NOT NULL DEFAULT 0")

        reopened = PortalDatabase(self.database.path)

        with reopened._connection() as conn:
            assignment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(feature_assignments)")}
            feature_columns = {row["name"] for row in conn.execute("PRAGMA table_info(features)")}

        self.assertNotIn("is_assigned", assignment_columns)
        self.assertNotIn("default_assigned", feature_columns)
        self.assertEqual(
            [feature["featureId"] for feature in reopened.list_available_features("owner@example.com")],
            [DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID],
        )
        self.assertEqual(
            reopened.get_feature_assignment("owner@example.com", MONITOR_FEATURE_ID)["metadata"]["settings"],
            {"intervalDays": 7},
        )

    def test_delete_user_handles_legacy_feature_assignments_without_cascade(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.save_feature_assignment_metadata(
            "owner@example.com",
            MONITOR_FEATURE_ID,
            metadata={"settings": {"intervalDays": 7}},
        )

        with self.database._connection() as conn:
            conn.execute("ALTER TABLE feature_assignments RENAME TO feature_assignments_old")
            conn.execute(
                """
                CREATE TABLE feature_assignments (
                    user_id INTEGER NOT NULL,
                    feature_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    assigned_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, feature_id),
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(feature_id) REFERENCES features(feature_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO feature_assignments (
                    user_id,
                    feature_id,
                    metadata_json,
                    assigned_at,
                    updated_at
                )
                SELECT
                    user_id,
                    feature_id,
                    metadata_json,
                    assigned_at,
                    updated_at
                FROM feature_assignments_old
                """
            )
            conn.execute("DROP TABLE feature_assignments_old")

        deleted_user = self.database.delete_user("owner@example.com")

        self.assertEqual(deleted_user["email"], "owner@example.com")
        self.assertIsNone(self.database.get_user("owner@example.com"))

    def test_delete_portal_whatsapp_store_for_connection_removes_cached_file(self) -> None:
        connection = {
            "userId": 7,
            "email": "owner@example.com",
        }
        store_cache = {}
        store_path = portal_whatsapp_store_path_for_connection(Path(self.temp_dir.name), connection)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text('{"threads":{},"approvals":{}}\n', encoding="utf-8")
        store_cache[str(store_path.resolve())] = object()

        deleted_path = delete_portal_whatsapp_store_for_connection(
            root=Path(self.temp_dir.name),
            connection=connection,
            store_cache=store_cache,
        )

        self.assertEqual(deleted_path, store_path.resolve())
        self.assertFalse(store_path.exists())
        self.assertEqual(store_cache, {})


    def test_erase_account_removes_receipt_bundles_and_contact_submissions(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.create_contact_opportunity(
            email="Owner@example.com",
            name="Owner",
            phone="+972500000000",
            transcript=[{"role": "user", "text": "I need help with receipts"}],
        )
        self.database.create_contact_opportunity(email="someone.else@example.com", name="Someone Else")
        root = Path(self.temp_dir.name)
        receipt_root = root / "agent-receipts"
        owner_folder = receipt_root / "owner-key" / "receipts-2026-08"
        owner_folder.mkdir(parents=True)
        (owner_folder / "receipts.xlsx").write_text("rows", encoding="utf-8")
        neighbour_folder = receipt_root / "another-owner-key"
        neighbour_folder.mkdir(parents=True)
        (neighbour_folder / "receipts.xlsx").write_text("rows", encoding="utf-8")
        store_path = portal_whatsapp_store_path_for_connection(root, {"userId": 1, "email": "owner@example.com"})
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text('{"threads":{},"approvals":{}}\n', encoding="utf-8")

        erasure = erase_account(
            database=self.database,
            email="owner@example.com",
            root=root,
            receipt_output_root=receipt_root,
            receipt_owner_key="owner-key",
        )

        self.assertIsNone(self.database.get_user("owner@example.com"))
        self.assertFalse((receipt_root / "owner-key").exists())
        self.assertFalse(store_path.exists())
        self.assertEqual(erasure.contact_submissions_removed, 1)
        self.assertEqual(erasure.failed_paths, [])
        self.assertEqual(
            {path.name for path in erasure.removed_paths},
            {"owner-key", store_path.name},
        )
        # Nothing outside the account being erased is touched.
        self.assertTrue((neighbour_folder / "receipts.xlsx").exists())
        self.assertEqual(len(self.database.list_contact_opportunities()), 1)

    def test_erase_account_revokes_each_google_grant_once(self) -> None:
        self.database.register_user("owner@example.com")
        # One Google sign-in backing a mailbox and a drive shares a refresh
        # token, so it is one grant to revoke, not two.
        for platform, address in (("email", "owner@example.com"), ("drive", "")):
            self.database.save_platform_connection(
                "owner@example.com",
                platform=platform,
                auth_type="oauth",
                secret_ciphertext=f"cipher-google-{platform}",
                secret_hint="google",
                secret_fingerprint="shared-google-grant",
                provider="google",
                account_address=address,
            )
        self.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext="cipher-microsoft",
            secret_hint="microsoft",
            secret_fingerprint="microsoft-grant",
            provider="microsoft",
            account_address="owner@outlook.com",
        )
        revoked: list[str] = []

        def revoke_grant(record: dict[str, str]) -> tuple[bool, str]:
            if record.get("provider") != "google":
                return False, ""
            revoked.append(record.get("secretCiphertext", ""))
            return True, ""

        erasure = erase_account(
            database=self.database,
            email="owner@example.com",
            root=Path(self.temp_dir.name),
            revoke_grant=revoke_grant,
        )

        self.assertEqual(len(revoked), 1)
        self.assertEqual(erasure.revoked_grants, 1)
        self.assertIsNone(self.database.get_user("owner@example.com"))

    def test_erase_account_revokes_grants_of_a_disabled_account(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext="cipher-google",
            secret_hint="google",
            secret_fingerprint="google-grant",
            provider="google",
            account_address="owner@example.com",
        )
        self.database.update_user_status("owner@example.com", is_active=False)
        seen: list[dict[str, str]] = []

        erasure = erase_account(
            database=self.database,
            email="owner@example.com",
            root=Path(self.temp_dir.name),
            revoke_grant=lambda record: (seen.append(record) or (True, "")),
        )

        self.assertEqual(len(seen), 1)
        self.assertEqual(erasure.revoked_grants, 1)

    def test_erase_account_reports_a_warning_the_provider_returned(self) -> None:
        self.database.register_user("owner@example.com")
        self.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext="cipher-google",
            secret_hint="google",
            secret_fingerprint="google-grant",
            provider="google",
            account_address="owner@example.com",
        )

        erasure = erase_account(
            database=self.database,
            email="owner@example.com",
            root=Path(self.temp_dir.name),
            revoke_grant=lambda record: (False, "Google could not confirm revocation."),
        )

        self.assertEqual(erasure.revoked_grants, 0)
        self.assertEqual(erasure.revocation_warnings, ["Google could not confirm revocation."])
        # A provider that would not answer never keeps the rows alive.
        self.assertIsNone(self.database.get_user("owner@example.com"))

    def test_erase_account_rejects_an_unknown_account(self) -> None:
        with self.assertRaises(KeyError):
            erase_account(
                database=self.database,
                email="nobody@example.com",
                root=Path(self.temp_dir.name),
            )


if __name__ == "__main__":
    unittest.main()
