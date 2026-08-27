import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.source_actions import SourceActionScheduler
from packages.infrastructure.source_actions import validate_source_url


class SourceActionTests(unittest.TestCase):
    def test_url_validation_rejects_local_network_targets(self):
        with self.assertRaises(ValueError):
            validate_source_url("http://127.0.0.1/private")
        with self.assertRaises(ValueError):
            validate_source_url("https://user:pass@example.com/private")

    def test_file_action_stores_bytes_but_list_never_returns_them(self):
        with tempfile.TemporaryDirectory() as directory:
            database = PortalDatabase(Path(directory) / "portal.db", bootstrap_registered_emails=["owner@example.com"])
            user = database.get_user("owner@example.com")
            action = database.create_source_action(
                user_id=int(user["id"]),
                source_type="file",
                file_name="customers.csv",
                mime_type="text/csv",
                file_bytes=b"name\nAda\n",
                interval_minutes=60,
            )
            self.assertNotIn("fileBytes", action)
            listed = database.list_source_actions_for_user(int(user["id"]))[0]
            self.assertNotIn("fileBytes", listed)
            SourceActionScheduler(database).run_one(int(action["id"]))
            updated = database.get_source_action(int(action["id"]))
            self.assertEqual(updated["lastRunStatus"], "success")
            self.assertEqual(updated["lastContentSize"], 9)

    def test_source_action_is_account_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            database = PortalDatabase(
                Path(directory) / "portal.db",
                bootstrap_registered_emails=["owner@example.com", "other@example.com"],
            )
            owner = database.get_user("owner@example.com")
            other = database.get_user("other@example.com")
            action = database.create_source_action(
                user_id=int(owner["id"]), source_type="file", file_name="notes.txt", file_bytes=b"notes", interval_minutes=60,
            )
            self.assertEqual(database.list_source_actions_for_user(int(other["id"])), [])
            self.assertIsNone(database.cancel_source_action(int(action["id"]), user_id=int(other["id"])))
            self.assertEqual(database.get_source_action(int(action["id"]))["status"], "active")

    def test_source_action_can_pause_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            database = PortalDatabase(Path(directory) / "portal.db", bootstrap_registered_emails=["owner@example.com"])
            user = database.get_user("owner@example.com")
            action = database.create_source_action(
                user_id=int(user["id"]),
                source_type="file",
                file_name="notes.txt",
                file_bytes=b"notes",
                interval_minutes=60,
            )

            paused = database.pause_source_action(int(action["id"]), user_id=int(user["id"]))

            self.assertEqual(paused["status"], "paused")
            self.assertEqual(database.list_due_source_actions(now=paused["nextRunAt"]), [])

            rescheduled = database.update_source_action_schedule(
                action_id=int(action["id"]),
                user_id=int(user["id"]),
                interval_minutes=1440,
            )
            self.assertEqual(rescheduled["status"], "paused")

            resumed = database.resume_source_action(int(action["id"]), user_id=int(user["id"]))

            self.assertEqual(resumed["status"], "active")


if __name__ == "__main__":
    unittest.main()
