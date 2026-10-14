"""One person is writing, and they are spoken to as themselves.

Hebrew marks the gender of "you", and a message that speaks to one parent
in the plural - רוצים, as to a crowd - is written for nobody. The person
says it themselves every time they speak of themselves in the present
tense; these tests pin how that is read, where it is kept for the account
holder and for a family member on their own phone, and how it reaches the
words written when nobody is typing.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import household
from packages.infrastructure.assistant_voice import ASSISTANT_VOICE
from packages.infrastructure.family_week_nudges import leave_words
from packages.infrastructure.person_address import address_word
from packages.infrastructure.person_address import detect_address_form
from packages.infrastructure.person_address import remember_address_form
from packages.infrastructure.person_address import resolve_address_form
from packages.infrastructure.portal_db import PortalDatabase


class DetectAddressFormTests(unittest.TestCase):
    def test_a_present_tense_word_about_themselves_says_it(self) -> None:
        self.assertEqual(detect_address_form("אני לוקחת את להב מחר"), "f")
        self.assertEqual(detect_address_form("אני לוקח אותו"), "m")
        self.assertEqual(detect_address_form("מחר אני אוספת את אור"), "f")
        self.assertEqual(detect_address_form("כשאני חוזרת הביתה"), "f")
        self.assertEqual(detect_address_form("אני עובד מהבית"), "m")
        self.assertEqual(detect_address_form("ואני אמא של להב"), "f")
        self.assertEqual(detect_address_form("אני אבא של שניים"), "m")

    def test_a_word_between_does_not_hide_it(self) -> None:
        self.assertEqual(detect_address_form("אני לא יכול מחר"), "m")
        self.assertEqual(detect_address_form("אני בדרך כלל מגיעה ב-4"), "f")
        self.assertEqual(detect_address_form("אני עדיין לא יודעת"), "f")

    def test_a_message_that_says_nothing_is_nothing(self) -> None:
        # רוצה reads the same for both, and the past tense says nothing.
        self.assertEqual(detect_address_form("אני רוצה תזכורת"), "")
        self.assertEqual(detect_address_form("אני לקחתי אותו אתמול"), "")
        self.assertEqual(detect_address_form("I'll take him"), "")
        self.assertEqual(detect_address_form("👍"), "")
        self.assertEqual(detect_address_form(""), "")
        # A gendered word about somebody else is not about the writer.
        self.assertEqual(detect_address_form("היא לוקחת אותו היום"), "")
        self.assertEqual(detect_address_form("אני חושב שהיא לוקחת"), "m")

    def test_both_in_one_message_is_nobody(self) -> None:
        self.assertEqual(detect_address_form("אני לוקחת ואני לוקח"), "")


class KeptAddressFormTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.partner = self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_account_holder_is_kept_on_the_profile_and_the_last_clear_word_wins(self) -> None:
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id), "")
        self.assertEqual(remember_address_form(self.database, user_id=self.user_id, text="אני לוקח את להב"), "m")
        self.assertEqual((self.database.get_household_profile(user_id=self.user_id) or {})["addressForm"], "m")
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id), "m")
        # A message that says nothing changes nothing.
        self.assertEqual(remember_address_form(self.database, user_id=self.user_id, text="כן, 5 דקות לפני"), "")
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id), "m")
        self.assertEqual(remember_address_form(self.database, user_id=self.user_id, text="אני צריכה לצאת"), "f")
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id), "f")

    def test_a_family_member_is_kept_on_their_own_row_not_the_account(self) -> None:
        member_id = int(self.partner["id"])
        self.assertEqual(remember_address_form(self.database, user_id=self.user_id, text="אני אוספת היום", member_id=member_id), "f")
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id, member_id=member_id), "f")
        self.assertEqual((self.database.get_household_member(user_id=self.user_id, member_id=member_id) or {})["addressForm"], "f")
        # The account holder is still unsaid.
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id), "")
        self.assertEqual((self.database.get_household_profile(user_id=self.user_id) or {})["addressForm"], "")

    def test_the_store_refuses_a_form_it_does_not_know(self) -> None:
        with self.assertRaises(ValueError):
            self.database.save_household_profile(user_id=self.user_id, address_form="x")
        with self.assertRaises(ValueError):
            self.database.save_household_member_address_form(user_id=self.user_id, member_id=int(self.partner["id"]), address_form="they")

    def test_the_model_reads_it_in_the_household_and_on_the_speaker(self) -> None:
        today = date(2026, 10, 14)
        before = household.describe_household(
            profile=self.database.get_household_profile(user_id=self.user_id), members=[], activities=[], today=today,
        )
        self.assertNotIn("addressAs", before)
        remember_address_form(self.database, user_id=self.user_id, text="אני לוקחת")
        after = household.describe_household(
            profile=self.database.get_household_profile(user_id=self.user_id), members=[], activities=[], today=today,
        )
        self.assertEqual(after["addressAs"], "a woman")
        # A group is a room, not a person.
        in_group = household.describe_household(
            profile=self.database.get_household_profile(user_id=self.user_id), members=[], activities=[], today=today,
            group_name="Kita Gimel",
        )
        self.assertNotIn("addressAs", in_group)
        self.assertNotIn("addressAs", household.describe_speaker(self.partner, owner_name="Dana"))
        remember_address_form(self.database, user_id=self.user_id, text="אני לוקח", member_id=int(self.partner["id"]))
        member = self.database.get_household_member(user_id=self.user_id, member_id=int(self.partner["id"]))
        self.assertEqual(household.describe_speaker(member, owner_name="Dana")["addressAs"], "a man")


class WordsWrittenForOnePersonTests(unittest.TestCase):
    def test_the_voice_speaks_to_one_person_in_their_own_gender(self) -> None:
        self.assertIn("never in the plural", ASSISTANT_VOICE)
        self.assertIn("addressAs", ASSISTANT_VOICE)
        self.assertIn("רוצים", ASSISTANT_VOICE)

    def test_a_family_members_ride_word_names_how_they_are_addressed(self) -> None:
        plain = leave_words(["Shirly collects Tom - Kindergarten at 16:00"], 0, reader="Shirly")
        self.assertIn("This message is for Shirly,", plain["instruction"])
        known = leave_words(
            ["Shirly collects Tom - Kindergarten at 16:00"], 0, reader="Shirly", reader_address=address_word("f"),
        )
        self.assertIn("This message is for Shirly (a woman),", known["instruction"])
        # The account holder's own word carries nothing here: the context does.
        own = leave_words(["You collect Tom - Kindergarten at 16:00"], 0, reader_address=address_word("f"))
        self.assertNotIn("a woman", own["instruction"])


if __name__ == "__main__":
    unittest.main()
