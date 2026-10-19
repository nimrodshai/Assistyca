"""Which language each person's messages come in: the account holder's on
the profile, a family member's on their own row, and the one never
overwriting the other."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.message_language import remember_message_language
from packages.infrastructure.message_language import resolve_message_language
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.whatsapp_agent_chat import words_beyond_family_join


class PersonalLanguageTests(unittest.TestCase):
    HOLDER_PHONE = "972500000001"
    PARTNER_PHONE = "972500000002"

    def setUp(self) -> None:
        from datetime import datetime, timedelta, timezone

        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("parent@example.com", display_name="דנה")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=self.HOLDER_PHONE)
        self.partner = self.database.save_household_member(user_id=self.user_id, name="Yoav", role="partner")
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(self.partner["id"]), code="ABC234",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.database.claim_household_invite(code="ABC234", wa_id=self.PARTNER_PHONE, label="Yoav")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_a_member_writing_english_keeps_it_as_their_own(self) -> None:
        remember_message_language(self.database, user_id=self.user_id, text="אני אאסוף")
        member_id = int(self.partner["id"])

        self.assertEqual(remember_message_language(self.database, user_id=self.user_id, text="Sure, I'll take him", member_id=member_id), "en")

        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "he")
        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id, member_id=member_id), "en")

    def test_a_member_who_has_not_written_gets_the_familys(self) -> None:
        remember_message_language(self.database, user_id=self.user_id, text="בוקר טוב")
        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id, member_id=int(self.partner["id"])), "he")

    def test_the_join_links_own_words_say_nothing(self) -> None:
        self.assertEqual(words_beyond_family_join("Assistyca family ABC234"), "")
        self.assertEqual(words_beyond_family_join("היי Assistyca family ABC234"), "היי")

    def test_each_phone_gets_its_own_persons_template_language(self) -> None:
        from packages.infrastructure.scheduled_actions import ScheduledActionConfig
        from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

        remember_message_language(self.database, user_id=self.user_id, text="בוקר טוב")
        remember_message_language(self.database, user_id=self.user_id, text="Thanks", member_id=int(self.partner["id"]))
        scheduler = ScheduledActionScheduler(self.database, config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10))

        self.assertEqual(scheduler._recipient_language(self.user_id, self.HOLDER_PHONE), "he")
        self.assertEqual(scheduler._recipient_language(self.user_id, self.PARTNER_PHONE), "en")


if __name__ == "__main__":
    unittest.main()
