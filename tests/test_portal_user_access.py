from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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

    def test_set_user_feature_assignments_can_clear_and_replace_defaults(self) -> None:
        self.database.register_user("owner@example.com")

        self.database.set_user_feature_assignments("owner@example.com", [])
        assigned_after_clear = self.database.list_assigned_features("owner@example.com")

        self.assertEqual(assigned_after_clear, [])

        self.database.set_user_feature_assignments("owner@example.com", [FOLLOW_UP_FEATURE_ID])
        assigned_features = self.database.list_assigned_features("owner@example.com")
        assignments = {
            assignment["featureId"]: assignment
            for assignment in self.database.list_feature_assignments("owner@example.com")
        }

        self.assertEqual([feature["featureId"] for feature in assigned_features], [FOLLOW_UP_FEATURE_ID])
        self.assertFalse(assignments[DEFAULT_FEATURE_ID]["isAssigned"])
        self.assertTrue(assignments[FOLLOW_UP_FEATURE_ID]["isAssigned"])
        self.assertFalse(assignments[MONITOR_FEATURE_ID]["isAssigned"])

    def test_set_user_feature_assignments_preserves_existing_metadata(self) -> None:
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

        self.database.set_user_feature_assignments("owner@example.com", [FOLLOW_UP_FEATURE_ID])

        assignments = {
            assignment["featureId"]: assignment
            for assignment in self.database.list_feature_assignments("owner@example.com")
        }

        self.assertFalse(assignments[MONITOR_FEATURE_ID]["isAssigned"])
        self.assertEqual(
            assignments[MONITOR_FEATURE_ID]["metadata"]["settings"]["watchItems"],
            ["Court holidays", "Criminal law conferences"],
        )

    def test_delete_user_removes_account_and_related_records(self) -> None:
        self.database.register_user("owner@example.com", is_admin=True)
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
            [feature["featureId"] for feature in self.database.list_assigned_features("better@example.com")],
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

    def test_delete_user_handles_legacy_feature_assignments_without_cascade(self) -> None:
        self.database.register_user("owner@example.com")

        with self.database._connection() as conn:
            conn.execute("ALTER TABLE feature_assignments RENAME TO feature_assignments_old")
            conn.execute(
                """
                CREATE TABLE feature_assignments (
                    user_id INTEGER NOT NULL,
                    feature_id TEXT NOT NULL,
                    is_assigned INTEGER NOT NULL DEFAULT 1,
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
                    is_assigned,
                    metadata_json,
                    assigned_at,
                    updated_at
                )
                SELECT
                    user_id,
                    feature_id,
                    is_assigned,
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


if __name__ == "__main__":
    unittest.main()
