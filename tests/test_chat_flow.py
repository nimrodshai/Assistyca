"""The opening of the conversation.

A family is asked who is at home and what their week looks like, and only
once that is in is connecting offered. A "not now" is remembered, so nobody
is asked the same thing the next morning. Someone who texted the number out
of the blue is introduced to the assistant first.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import chat_flow
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import build_loop_context_text
from packages.infrastructure.portal_db import PortalDatabase

TODAY = "2026-09-17"


class GettingToKnowVoiceTests(unittest.TestCase):
    def test_the_saving_is_kept_quiet_and_the_next_question_follows(self) -> None:
        # Every answer is saved the moment it lands, but the person is not
        # told so: "I've got Ella, Tom and Rina in the family now" is a
        # system notice, not something one person says to another.
        rules = chat_flow.chat_flow_rules({"goal": "family", "status": "in_progress"})
        self.assertIn("Keep the saving to yourself", rules)
        self.assertIn("a word of acknowledgement if any, then the next question", rules)
        self.assertIn("The week is shown back once, when it is done", rules)


class WhichOpeningTests(unittest.TestCase):
    def flow(self, **kwargs) -> dict:
        kwargs.setdefault("profile", None)
        kwargs.setdefault("connected", [])
        kwargs.setdefault("today", TODAY)
        return chat_flow.describe_chat_flow(**kwargs)

    def test_a_family_is_got_to_know_before_anything_is_offered(self) -> None:
        # Nothing connected, but connecting is not what a family needs first.
        flow = self.flow()
        self.assertEqual((flow["goal"], flow["status"]), ("family", "not_started"))
        self.assertNotIn("notConnected", flow)
        self.assertNotIn("accountType", flow)
        started = self.flow(profile={"gettingToKnow": "in_progress"})
        self.assertEqual(started["goal"], "family")

    def test_what_the_week_still_lacks_travels_with_the_opening(self) -> None:
        # Code works out what is missing, so the asking ends when the week is
        # ready rather than when the conversation runs out of steam.
        flow = self.flow(
            profile={"gettingToKnow": "in_progress"},
            household_block={
                "members": [{"name": "Lotan", "role": "child"}],
                "week": [{"id": 1, "title": "School", "who": ["Lotan"], "days": ["sun"], "end": "13:30"}],
            },
        )
        self.assertFalse(flow["weekReady"])
        self.assertEqual(
            flow["weekGaps"],
            [{"missing": "drop_off", "activity": "School", "id": 1}, {"missing": "pick_up", "activity": "School", "id": 1}],
        )

    def test_a_week_with_everybody_placed_and_every_pickup_taken_is_ready(self) -> None:
        flow = self.flow(
            profile={"gettingToKnow": "in_progress"},
            household_block={
                "members": [{"name": "Lotan", "role": "child"}],
                "week": [{
                    "id": 1, "title": "School", "who": ["Lotan"], "days": ["sun"],
                    "end": "13:30", "dropOffBy": "me", "pickUpBy": "Stav",
                }],
            },
        )
        self.assertTrue(flow["weekReady"])
        self.assertNotIn("weekGaps", flow)

    def test_the_afternoons_question_travels_without_holding_the_week_back(self) -> None:
        # The block has already worked out that the week can be run; what it
        # still carries is the question nobody has put yet.
        from packages.infrastructure import household

        block = household.describe_household(
            profile={"gettingToKnow": "in_progress"},
            members=[{"name": "Lahav", "role": "child"}],
            activities=[{
                "id": 1, "title": "School", "who": ["Lahav"], "days": ["sun"],
                "endTime": "13:45", "dropOffBy": "me", "pickUpBy": "Stav",
            }],
            today=date(2026, 9, 24),
        )
        flow = self.flow(profile={"gettingToKnow": "in_progress"}, household_block=block)
        self.assertEqual(flow["goal"], "family")
        self.assertTrue(flow["weekReady"], "the two never disagree about whether the week can be run")
        self.assertEqual(
            flow["weekGaps"],
            [{"missing": "afternoons", "who": "Lahav", "after": "School"}, {"missing": "own_week", "who": "me"}],
            "the child's afternoon first, then the parent's own week - and neither holds the week back",
        )

    def test_a_week_they_have_called_finished_is_not_reopened_as_questions(self) -> None:
        # Their "that's everything" stands: the goal moves on. What nobody is
        # down for still travels, so it can be raised on the day it matters.
        flow = self.flow(
            profile={"gettingToKnow": "done"},
            household_block={"members": [{"name": "Lotan", "role": "child"}], "week": []},
        )
        self.assertEqual(flow["goal"], "connect")
        self.assertEqual(flow["weekGaps"], [{"missing": "week", "who": "Lotan"}])

    def test_a_family_whose_week_is_in_is_then_offered_the_calendar_and_the_mail(self) -> None:
        flow = self.flow(profile={"gettingToKnow": "done"})
        self.assertEqual(flow["goal"], "connect")
        self.assertEqual(flow["notConnected"], ["mailbox", "calendar"])
        self.assertEqual(self.flow(profile={"gettingToKnow": "done"}, connected=["mailbox"])["notConnected"], ["calendar"])
        done = self.flow(profile={"gettingToKnow": "done"}, connected=["mailbox", "calendar"])
        self.assertEqual(done, {"goal": "done", "weekReady": True})

    def test_a_family_the_house_switched_the_week_off_for_opens_on_connecting(self) -> None:
        flow = self.flow(family_flow_allowed=False)
        self.assertEqual(flow["goal"], "connect")
        self.assertEqual(self.flow(family_flow_allowed=False, connected=["mailbox", "calendar"]), {"goal": "done"})

    def test_not_now_about_connecting_is_kept_until_the_day_it_named(self) -> None:
        holding = self.flow(profile={"gettingToKnow": "done", "connectOffer": "postponed", "connectAskAgainOn": "2026-09-20"})
        self.assertEqual((holding["status"], holding["askNow"]), ("postponed", False))
        due = self.flow(profile={"gettingToKnow": "done", "connectOffer": "postponed", "connectAskAgainOn": TODAY})
        self.assertTrue(due["askNow"])
        settled = self.flow(profile={"gettingToKnow": "done", "connectOffer": "done"})
        self.assertEqual(settled["goal"], "done")

    def test_an_offer_already_made_is_not_made_again_until_its_rest_is_over(self) -> None:
        # On WhatsApp the conversation never ends, so an offer nobody took up
        # is held by a date, not by the model remembering it said so.
        offered = self.flow(profile={"gettingToKnow": "done", "connectOffer": "in_progress", "connectAskAgainOn": "2026-09-30"})
        self.assertEqual((offered["status"], offered["askNow"]), ("in_progress", False))
        rested = self.flow(profile={"gettingToKnow": "done", "connectOffer": "in_progress", "connectAskAgainOn": TODAY})
        self.assertTrue(rested["askNow"])

    def test_the_offer_waits_for_a_message_it_belongs_to(self) -> None:
        rules = chat_flow.chat_flow_rules({"goal": "connect", "askNow": True})
        self.assertIn("A quick change, a correction, a list", rules)
        self.assertIn("in the same turn", rules)

    def test_a_family_putting_it_off_is_not_pushed_on_to_connecting(self) -> None:
        # Postponed is not done: the opening is still getting to know them,
        # it is only on hold.
        flow = self.flow(profile={"gettingToKnow": "postponed", "askAgainOn": "2026-09-30"})
        self.assertEqual((flow["goal"], flow["askNow"]), ("family", False))

    def test_a_stranger_is_introduced_first_whatever_the_opening(self) -> None:
        # Nothing was ever said to someone who simply texted the number, so
        # the first turn carries the introduction - and nobody else's does.
        self.assertTrue(self.flow(first_contact=True)["introduce"])
        self.assertTrue(self.flow(first_contact=True, profile={"gettingToKnow": "done"})["introduce"])
        self.assertTrue(self.flow(first_contact=True, family_flow_allowed=False, connected=["mailbox", "calendar"])["introduce"])
        self.assertNotIn("introduce", self.flow())


class RulesTests(unittest.TestCase):
    def test_every_account_is_spoken_to_as_a_family(self) -> None:
        rules = chat_flow.chat_flow_rules({"goal": "done"})
        self.assertIn("their household and their week", rules)
        self.assertNotIn("business", rules.lower())

    def test_each_opening_carries_its_own_rules(self) -> None:
        getting_to_know = chat_flow.chat_flow_rules({"goal": "family"})
        self.assertIn("one question in a message", getting_to_know)
        self.assertIn("set_getting_to_know", getting_to_know)
        # One question at a time, but about the thing as a whole: asking the
        # days, then the hour, then who drives, each in its own message, is
        # the intake form the opening is meant not to be.
        self.assertIn("One question is not one field", getting_to_know)
        self.assertIn("give it all at once", getting_to_know)
        # The school already wrote the timetable: a picture or a voice
        # message is offered once, and only who drives is asked after it. A
        # PDF is read too but never offered.
        self.assertIn("timetable as a picture", getting_to_know)
        self.assertIn("in a voice message", getting_to_know)
        self.assertIn("Name a picture, never", getting_to_know)
        self.assertIn("never says who takes them in or who collects them", getting_to_know)
        # Once in the whole getting-to-know: it was made for Tamar and again
        # for Omer, one school question each.
        self.assertIn("Offer it once in the whole getting-to-know, with the first child's school question, never for a second child", getting_to_know)
        # The finished week is the picture and one sentence, not a printout
        # of the week read back with a page button under it.
        self.assertIn("show the week with show_family_week as a picture, not in words", getting_to_know)
        self.assertIn("Do not read the week back, and do not offer the week page", getting_to_know)
        self.assertNotIn("show the week back in a few short lines", getting_to_know)
        self.assertNotIn("{shortcut}", getting_to_know)
        self.assertNotIn("{voice}", getting_to_know)
        self.assertNotIn("set_connect_offer", getting_to_know)

        then_connecting = chat_flow.chat_flow_rules({"goal": "connect"})
        self.assertIn("their household and their week", then_connecting)
        self.assertIn("Their family and their week are in", then_connecting)
        self.assertIn("set_connect_offer", then_connecting)

    def test_a_voice_note_is_never_offered_where_voice_notes_are_off(self) -> None:
        flow = chat_flow.describe_chat_flow(
            profile={}, connected=(), today="2026-10-18", voice_notes_allowed=False,
        )
        self.assertTrue(flow["voiceNotesOff"])
        rules = chat_flow.chat_flow_rules(flow)
        self.assertIn("timetable as a picture", rules)
        self.assertNotIn("voice message", rules)

    def test_the_introduction_comes_first_and_only_when_asked_for(self) -> None:
        introduced = chat_flow.chat_flow_rules({"goal": "family", "introduce": True})
        self.assertIn("texted the Assistyca number without registering", introduced)
        self.assertIn("never ask for an email", introduced)
        self.assertLess(introduced.index("texted the Assistyca number"), introduced.index("Getting to know this family"))
        self.assertNotIn("texted the Assistyca number", chat_flow.chat_flow_rules({"goal": "family"}))

    def test_getting_to_know_a_family_is_about_the_week_and_never_about_an_email(self) -> None:
        rules = chat_flow.chat_flow_rules({"goal": "family"})
        self.assertIn("who takes them and who collects them", rules)
        self.assertIn("weekGaps", rules)
        self.assertIn("you never ask for either while you are learning it", rules)
        self.assertIn("do not call done", rules)
        # School hours are the easy half; the afternoon is the half that
        # needs somebody in it, and it is asked for rather than assumed.
        self.assertIn("what that one does after school", rules)
        self.assertIn("never decide for yourself that there is nothing after them", rules)
        self.assertIn("'afternoons' gap never makes a week unready", rules)

    def test_the_parent_is_asked_for_their_own_week_and_offered_their_calendar_for_it(self) -> None:
        # Knowing when the parent works is knowing when it cannot be them
        # collecting. They are asked once, may say no, and are offered their
        # Google Calendar as the other way to answer - the one connection
        # raised while the family is still being got to know.
        rules = chat_flow.chat_flow_rules({"goal": "family"})
        self.assertIn("'own_week' means the children are in", rules)
        self.assertIn("whether they want to put their own week in too", rules)
        self.assertIn("when they cannot be the one collecting", rules)
        self.assertIn("Google Calendar", rules)
        self.assertIn("call connect_link with google", rules)
        self.assertIn("who is [\"me\"]", rules)
        self.assertIn("drop_off_by and pick_up_by left empty", rules)
        self.assertIn("a no is a whole answer", rules)
        self.assertIn("the 'own_week' gap is the same kind of question", rules)

        # And for good: a grown-up's hours are read as when they cannot do
        # a pickup, never as something to collect them from.
        for_good = chat_flow.chat_flow_rules({"goal": "done"})
        self.assertIn("marked grownUp is a grown-up's own week", for_good)
        self.assertIn("that grown-up cannot be the one", for_good)

        # A calendar connected for their own week is not offered again.
        then_connecting = chat_flow.chat_flow_rules({"goal": "connect"})
        self.assertIn("A calendar they connected while you were getting to know them", then_connecting)

    def test_a_family_is_never_told_it_must_connect_anything(self) -> None:
        rules = chat_flow.chat_flow_rules({"goal": "connect"})
        self.assertIn("nothing about it waits on anything being connected", rules)
        self.assertIn("Never say, or imply, that you cannot help them until they connect something", rules)

    def test_nothing_is_said_when_there_is_no_block(self) -> None:
        self.assertEqual(chat_flow.chat_flow_rules(None), "")


class TurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(self.path)
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="owner@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_opening_travels_in_the_context_with_its_rules(self) -> None:
        flow = chat_flow.describe_chat_flow(profile=None, connected=[], today=TODAY)
        text = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="Asia/Jerusalem", today=TODAY,
            tool_context={}, facts=[], channel="whatsapp", chat_flow=flow,
        )
        context = json.loads(text.split("CONTEXT\n", 1)[1])
        self.assertEqual(context["chatFlow"]["goal"], "family")
        self.assertIn("one question in a message", text)

    def test_an_ended_trial_is_not_asked_to_connect_anything(self) -> None:
        flow = chat_flow.describe_chat_flow(profile={"gettingToKnow": "done"}, connected=[], today=TODAY)
        text = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="Asia/Jerusalem", today=TODAY,
            tool_context={}, facts=[], channel="whatsapp", chat_flow=flow, trial_ended=True,
        )
        self.assertNotIn("set_connect_offer", text)

    def test_a_not_now_about_connecting_is_written_down_and_read_back(self) -> None:
        offered = TOOLS_BY_NAME["set_connect_offer"].run(self.context, {"status": "in_progress"})
        self.assertEqual(offered["status"], "in_progress")
        self.assertRegex(offered["askAgainOn"], r"^\d{4}-\d{2}-\d{2}$", "an offer made is held back for a while")
        held = TOOLS_BY_NAME["set_connect_offer"].run(self.context, {"status": "postponed", "ask_again_in_days": None})
        self.assertRegex(held["askAgainOn"], r"^\d{4}-\d{2}-\d{2}$")

        TOOLS_BY_NAME["set_getting_to_know"].run(self.context, {"status": "done"})
        profile = self.database.get_household_profile(user_id=self.user_id) or {}
        flow = chat_flow.describe_chat_flow(profile=profile, connected=[], today=date.today().isoformat())
        self.assertEqual(flow["goal"], "connect")
        self.assertFalse(flow["askNow"], "a not now said today is not asked again today")

        # Getting to know the family and the offer to connect are two
        # separate answers: one does not overwrite the other.
        self.assertEqual((profile["gettingToKnow"], profile["connectOffer"]), ("done", "postponed"))

    def test_a_bad_status_is_refused(self) -> None:
        refused = TOOLS_BY_NAME["set_connect_offer"].run(self.context, {"status": "later"})
        self.assertEqual(refused["error"]["code"], "choice_required")

    def test_a_database_from_before_the_offer_existed_reads_as_not_started(self) -> None:
        self.database.save_household_profile(user_id=self.user_id, connect_offer="postponed", connect_ask_again_on="2026-09-30")
        with sqlite3.connect(self.path) as conn:
            conn.execute("ALTER TABLE household_profiles DROP COLUMN connect_offer")
            conn.execute("ALTER TABLE household_profiles DROP COLUMN connect_ask_again_on")
        reopened = PortalDatabase(self.path)
        profile = reopened.get_household_profile(user_id=self.user_id) or {}
        self.assertEqual((profile["connectOffer"], profile["connectAskAgainOn"]), ("not_started", ""))


if __name__ == "__main__":
    unittest.main()
