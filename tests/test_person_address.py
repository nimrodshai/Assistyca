"""One person is writing, and they are spoken to as themselves.

Hebrew marks the gender of "you", and a message that speaks to one parent
in the plural - רוצים, as to a crowd - is written for nobody. The person
says it themselves every time they speak of themselves in the present
tense; these tests pin how that is read, where it is kept for the account
holder and for a family member on their own phone, and how it reaches the
words written when nobody is typing.
"""

from __future__ import annotations

import json
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
from packages.infrastructure.person_address import ADDRESS_READER_INSTRUCTIONS
from packages.infrastructure.person_address import detect_address_form
from packages.infrastructure.person_address import learn_address_forms
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


class ReadAddressFormTests(unittest.TestCase):
    """Most people never write a sentence the word list can read, and a
    reply model left to guess each turn called the partner אורי a woman in
    one run and a man in the next. The model reads it once from the context
    - their own phrasing, the names, how others speak of them - and what it
    read is kept, with what it rests on, so every turn uses the same form
    until stronger evidence or their own correction changes it."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.partner = self.database.save_household_member(user_id=self.user_id, name="משה", role="partner")
        self.database.save_household_member(user_id=self.user_id, name="להב", role="child")
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def reader(self, *people: dict[str, str]):
        def ask(prompt: str) -> str:
            self.prompts.append(prompt)
            return json.dumps({"people": list(people)})
        return ask

    def kept(self, member_id: int = 0) -> tuple[str, str]:
        if member_id:
            row = self.database.get_household_member(user_id=self.user_id, member_id=member_id) or {}
        else:
            row = self.database.get_household_profile(user_id=self.user_id) or {}
        return row.get("addressForm"), row.get("addressBasis")

    def test_how_the_writer_speaks_of_themselves_is_read_and_kept(self) -> None:
        # "גמורה" is no word on the list; the model reads it.
        changed = learn_address_forms(
            self.database, user_id=self.user_id, text="היום הייתי גמורה, תזכיר לי מחר",
            ask=self.reader({"ref": "holder", "form": "f", "basis": "self"}),
        )
        self.assertEqual(changed, {"holder": "f"})
        self.assertEqual(self.kept(), ("f", "self"))
        self.assertIn("היום הייתי גמורה", self.prompts[0])
        self.assertIn('"writer": "holder"', self.prompts[0])

    def test_the_partners_name_tells_the_holders_form_and_both_are_kept_as_inferred(self) -> None:
        learn_address_forms(
            self.database, user_id=self.user_id, text="תזכיר לי לאסוף את להב ב-4",
            ask=self.reader(
                {"ref": "holder", "form": "f", "basis": "name"},
                {"ref": f"member:{self.partner['id']}", "form": "m", "basis": "name"},
            ),
        )
        prompt = json.loads(self.prompts[0].split("CONTEXT\n", 1)[1])
        # The grown-ups with their names and roles; a child is not read.
        self.assertEqual(
            [(person["ref"], person["name"], person["role"]) for person in prompt["people"]],
            [("holder", None, "account holder"), (f"member:{self.partner['id']}", "משה", "partner")],
        )
        self.assertEqual(self.kept(), ("f", "name"))
        self.assertEqual(self.kept(int(self.partner["id"])), ("m", "name"))
        # And the reply model reads both.
        described = household.describe_household(
            profile=self.database.get_household_profile(user_id=self.user_id),
            members=self.database.list_household_members(user_id=self.user_id), activities=[], today=date(2026, 10, 19),
        )
        self.assertEqual(described["addressAs"], "a woman")
        self.assertEqual(described["members"][0]["addressAs"], "a man")

    def test_what_is_kept_is_used_again_rather_than_guessed_afresh(self) -> None:
        learn_address_forms(
            self.database, user_id=self.user_id, text="תזכיר לי לאסוף את להב",
            ask=self.reader({"ref": f"member:{self.partner['id']}", "form": "m", "basis": "name"}),
        )
        # Another run of the same weak guess comes out the other way: what
        # is kept stays, so the partner is the same person every turn.
        learn_address_forms(
            self.database, user_id=self.user_id, text="מה יש מחר?",
            ask=self.reader({"ref": f"member:{self.partner['id']}", "form": "f", "basis": "name"}),
        )
        self.assertEqual(self.kept(int(self.partner["id"])), ("m", "name"))
        self.assertEqual(resolve_address_form(self.database, user_id=self.user_id, member_id=int(self.partner["id"])), "m")
        # Stronger evidence does move it: the holder speaks of the partner.
        learn_address_forms(
            self.database, user_id=self.user_id, text="משה אמרה שהיא תאסוף",
            ask=self.reader({"ref": f"member:{self.partner['id']}", "form": "f", "basis": "others"}),
        )
        self.assertEqual(self.kept(int(self.partner["id"])), ("f", "others"))
        # Once everyone is known and the writer has said it outright, the
        # model is not asked at all.
        self.database.save_household_profile(user_id=self.user_id, address_form="f", address_basis="confirmed")
        asked = len(self.prompts)
        learn_address_forms(self.database, user_id=self.user_id, text="מה יש מחר?", ask=self.reader())
        self.assertEqual(len(self.prompts), asked)

    def test_a_correction_overrides_an_inference_and_sticks(self) -> None:
        member_id = int(self.partner["id"])
        learn_address_forms(
            self.database, user_id=self.user_id, member_id=member_id, text="מה התוכנית למחר?",
            ask=self.reader({"ref": f"member:{member_id}", "form": "m", "basis": "name"}),
        )
        learn_address_forms(
            self.database, user_id=self.user_id, member_id=member_id, text="תפנה אליי בלשון נקבה בבקשה",
            ask=self.reader({"ref": f"member:{member_id}", "form": "f", "basis": "said"}),
        )
        self.assertEqual(self.kept(member_id), ("f", "confirmed"))
        # Nothing read afterwards undoes it - not a name, not the word list.
        learn_address_forms(
            self.database, user_id=self.user_id, member_id=member_id, text="אני לוקח את להב",
            ask=self.reader({"ref": f"member:{member_id}", "form": "m", "basis": "self"}),
        )
        self.assertEqual(self.kept(member_id), ("f", "confirmed"))
        self.assertEqual(remember_address_form(self.database, user_id=self.user_id, member_id=member_id, text="אני לוקח"), "m")
        self.assertEqual(self.kept(member_id), ("f", "confirmed"))

    def test_only_the_writer_can_say_it_of_themselves(self) -> None:
        # The holder telling the assistant about the partner is what others
        # say: it can be outweighed by the partner's own words later.
        learn_address_forms(
            self.database, user_id=self.user_id, text="משה הוא בעלי",
            ask=self.reader({"ref": f"member:{self.partner['id']}", "form": "m", "basis": "said"}),
        )
        self.assertEqual(self.kept(int(self.partner["id"])), ("m", "others"))

    def test_an_unreadable_or_failed_reading_changes_nothing(self) -> None:
        def broken(prompt: str) -> str:
            raise RuntimeError("no credits")
        self.assertEqual(learn_address_forms(self.database, user_id=self.user_id, text="מה יש מחר?", ask=broken), {})
        self.assertEqual(learn_address_forms(
            self.database, user_id=self.user_id, text="מה יש מחר?", ask=lambda prompt: "I think she is a woman",
        ), {})
        self.assertEqual(learn_address_forms(
            self.database, user_id=self.user_id, text="מה יש מחר?",
            ask=self.reader({"ref": "member:999", "form": "f", "basis": "name"}, {"ref": "holder", "form": "x", "basis": "name"}),
        ), {})
        self.assertEqual(self.kept(), ("", ""))

    def test_english_is_not_read(self) -> None:
        learn_address_forms(self.database, user_id=self.user_id, text="what's on tomorrow?", ask=self.reader())
        self.assertEqual(self.prompts, [])

    def test_nobody_is_ever_asked(self) -> None:
        # The reader is silent: it returns readings, it never writes to the person.
        self.assertIn("Nobody is ever asked", ADDRESS_READER_INSTRUCTIONS)
        # And the reply model is told never to ask, and to take a correction.
        self.assertIn("Never ask anyone their gender", ASSISTANT_VOICE)
        self.assertIn("If they correct the form you used", ASSISTANT_VOICE)


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
        # The account holder's own word names her form too: left to the
        # context alone, a woman was told "אתה לוקח" half an hour after her
        # morning said "את לוקחת".
        own = leave_words(["You collect Tom - Kindergarten at 16:00"], 0, reader_address=address_word("f"))
        self.assertIn("The person (a woman, written to in that form)", own["instruction"])


if __name__ == "__main__":
    unittest.main()
