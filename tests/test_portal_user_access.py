from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.portal_db import PortalDatabase


DEFAULT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"
FOLLOW_UP_FEATURE_ID = "whatsapp-business-follow-up-outreach-writer"


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


if __name__ == "__main__":
    unittest.main()
