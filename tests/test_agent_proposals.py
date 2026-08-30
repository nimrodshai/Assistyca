from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.agent_proposals import AGENT_ACTION_CONTEXT_MAX_ITEMS
from packages.infrastructure.agent_proposals import AGENT_FILE_CONTEXT_MAX_FOLDERS
from packages.infrastructure.agent_proposals import AGENT_FOLDER_CONTEXT_MAX_ITEMS
from packages.infrastructure.agent_proposals import AGENT_TURN_INSTRUCTIONS
from packages.infrastructure.agent_proposals import build_agent_proposal_revision_prompt
from packages.infrastructure.agent_proposals import normalize_agent_action_context
from packages.infrastructure.agent_proposals import normalize_agent_file_context
from packages.infrastructure.agent_proposals import normalize_agent_folder_context
from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.agent_proposals import normalize_agent_proposal_for_revision
from packages.infrastructure.agent_proposals import normalize_agent_proposal_for_turn
from packages.infrastructure.agent_proposals import normalize_agent_proposal_revision_response
from packages.infrastructure.agent_proposals import normalize_agent_turn_response
from packages.infrastructure.agent_proposals import normalize_agent_tool_context
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.openai_api import OpenAIRequestError


class AgentProposalRevisionTests(unittest.TestCase):
    def test_revision_prompt_includes_current_proposal_and_conversation(self) -> None:
        proposal = normalize_agent_proposal_for_revision({
            "id": "proposal-1",
            "type": "scheduled-message",
            "revision": 1,
            "requestText": "Send me a WhatsApp message when it's 12:40",
            "details": {
                "channel": "whatsapp",
                "timeLocal": "12:40",
                "timezone": "Asia/Jerusalem",
                "messageText": "It's 12:40.",
                "messageSource": "generated",
            },
        })

        prompt = build_agent_proposal_revision_prompt(
            proposal=proposal,
            user_message="Let's change it to 13:30",
            conversation=[
                {"role": "assistant", "text": "What would you like to change?"},
                {"role": "user", "text": "Let's change it to 13:30"},
            ],
        )

        self.assertIn('"timeLocal":"12:40"', prompt)
        self.assertIn('"latestUserMessage":"Let\'s change it to 13:30"', prompt)
        self.assertIn('"text":"What would you like to change?"', prompt)
        self.assertIn("Do not calculate runAt", prompt)

    def test_revision_response_accepts_only_a_structured_delta(self) -> None:
        revision = normalize_agent_proposal_revision_response({
            "outcome": "revised",
            "changes": {"timeLocal": "13:30"},
            "reply": "",
        })

        self.assertEqual(revision, {
            "outcome": "revised",
            "changes": {"timeLocal": "13:30"},
            "reply": "",
        })

    def test_revision_response_rejects_invalid_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid local time"):
            normalize_agent_proposal_revision_response({
                "outcome": "revised",
                "changes": {"timeLocal": "25:90"},
            })

    def test_conversational_turn_treats_natural_followup_as_revision(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "revise_proposal",
            "reply": "Sure — I changed the time to 13:50.",
            "proposalType": "",
            "changes": {"timeLocal": "13:50"},
        }, has_active_proposal=True)

        self.assertEqual(turn["outcome"], "revise_proposal")
        self.assertEqual(turn["changes"], {"timeLocal": "13:50"})
        self.assertIn("changed the time", turn["reply"])

    def test_conversational_turn_preserves_manual_run_month_field(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "revise_proposal",
            "reply": "I’ll use August 2026 for the manual run.",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Pull all receipts for August 2026",
                    "manualRunMonth": "2026-08",
                    "outputFolder": "Receipts/Aug2026/",
                },
            },
        }, has_active_proposal=True, active_proposal_type="custom")

        self.assertEqual(turn["outcome"], "revise_proposal")
        self.assertEqual(turn["changes"]["fields"]["manualRunMonth"], "2026-08")
        self.assertEqual(turn["changes"]["fields"]["outputFolder"], "Receipts/Aug2026/")
        self.assertEqual(turn["changes"]["fields"]["result"], "Pull all receipts for August 2026")

    def test_conversational_turn_prompt_preserves_pending_proposal_context(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="No, let's change it to 13:50",
            conversation=[
                {"role": "assistant", "text": "Would you like me to schedule it?"},
                {"role": "user", "text": "No, let's change it to 13:50"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "scheduled-message",
                "revision": 1,
                "details": {"timeLocal": "12:40"},
            },
        )

        self.assertIn('"activeProposal":{"id":"proposal-1"', prompt)
        self.assertIn('"latestUserMessage":"No, let\'s change it to 13:50"', prompt)
        self.assertIn("not a new request", prompt)

    def test_action_context_keeps_only_display_details(self) -> None:
        actions = normalize_agent_action_context([
            {"id": 41, "name": "Receipt collector", "status": "Manual", "created": "Aug 23, 9:25 AM"},
            {"title": "Web monitor", "status": "Live", "secretToken": "shhh"},
            {"name": "   "},
            "Not an action",
        ])

        self.assertEqual(actions, [
            {"name": "Receipt collector", "status": "Manual", "created": "Aug 23, 9:25 AM"},
            {"name": "Web monitor", "status": "Live"},
        ])

    def test_action_context_keeps_the_kind_of_each_action(self) -> None:
        actions = normalize_agent_action_context([
            {"name": "Web monitor", "kind": "web-monitor", "status": "Live"},
            {"name": "Meeting summary", "type": "calendar-summary"},
        ])

        self.assertEqual(actions, [
            {"name": "Web monitor", "kind": "web-monitor", "status": "Live"},
            {"name": "Meeting summary", "kind": "calendar-summary"},
        ])

    def test_action_context_caps_the_list(self) -> None:
        actions = normalize_agent_action_context([
            {"name": f"Action {index}"} for index in range(40)
        ])

        self.assertEqual(len(actions), AGENT_ACTION_CONTEXT_MAX_ITEMS)
        self.assertEqual(actions[0]["name"], "Action 0")

    def test_turn_prompt_lists_existing_actions_for_the_picker(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="I want to make one of my actions scheduled instead of a one timer.",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            action_context=[
                {"name": "Receipt collector", "status": "Manual"},
                {"name": "Web monitor", "status": "Live"},
            ],
        )

        self.assertIn('"existingActions"', prompt)
        self.assertIn('"name":"Receipt collector"', prompt)
        self.assertIn("needsActionChoice=true", prompt)
        self.assertIn("do not name the actions yourself", prompt)

    def test_turn_prompt_forbids_a_second_copy_of_an_existing_action(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Collect my receipts every month.",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            action_context=[
                {"name": "Receipt collector", "kind": "custom", "status": "Manual"},
            ],
        )

        self.assertIn('"kind":"custom"', prompt)
        self.assertIn("Never set up a second copy of an action the account already has", prompt)
        self.assertIn("whether to change that one or add a separate action", prompt)

    def test_turn_response_keeps_action_choice_flag_on_a_plain_question(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which action should I put on a schedule?",
                "needsActionChoice": True,
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["outcome"], "question")
        self.assertTrue(turn["needsActionChoice"])

    def test_turn_response_drops_action_choice_flag_outside_a_plain_question(self) -> None:
        setup_question = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Where should I send the summary?",
                "proposalType": "email-digest",
                "needsActionChoice": True,
            },
            has_active_proposal=False,
        )
        chat_reply = normalize_agent_turn_response(
            {
                "outcome": "message",
                "reply": "You have five active actions right now.",
                "needsActionChoice": True,
            },
            has_active_proposal=False,
        )

        self.assertFalse(setup_question["needsActionChoice"])
        self.assertFalse(chat_reply["needsActionChoice"])

    def test_turn_prompt_explains_when_the_picker_takes_more_than_one_action(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="ok. Lets delete some actions",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            action_context=[
                {"name": "Receipt collector", "status": "Manual"},
                {"name": "Web monitor", "status": "Live"},
            ],
        )

        self.assertIn("actionChoiceMode", prompt)
        self.assertIn("some actions", prompt)

    def test_turn_response_keeps_a_multi_select_picker_for_a_plural_request(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which actions should I delete?",
                "needsActionChoice": True,
                "actionChoiceMode": "Multiple",
            },
            has_active_proposal=False,
        )

        self.assertTrue(turn["needsActionChoice"])
        self.assertEqual(turn["actionChoiceMode"], "multiple")

    def test_turn_response_defaults_the_picker_to_a_single_action(self) -> None:
        single = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which action should I put on a schedule?",
                "needsActionChoice": True,
            },
            has_active_proposal=False,
        )
        no_picker = normalize_agent_turn_response(
            {
                "outcome": "message",
                "reply": "You have five active actions right now.",
                "actionChoiceMode": "multiple",
            },
            has_active_proposal=False,
        )

        self.assertEqual(single["actionChoiceMode"], "single")
        self.assertEqual(no_picker["actionChoiceMode"], "")

    def test_turn_response_carries_a_delete_command_for_the_named_actions(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "action_command",
                "reply": "Taking care of that.",
                "actionCommand": "Delete",
                "actionNames": ["Receipt collector #3", "Meeting summary #2", "Receipt collector #3"],
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["outcome"], "action_command")
        self.assertEqual(turn["actionCommand"], "delete")
        # The repeat drops out; the order the user sees is kept.
        self.assertEqual(turn["actionNames"], ["Receipt collector #3", "Meeting summary #2"])

    def test_turn_response_refuses_a_command_it_cannot_carry_out(self) -> None:
        # Running an action is not one of the commands, and a command with
        # nothing to act on would delete nothing while sounding like it did.
        unsupported = normalize_agent_turn_response(
            {
                "outcome": "action_command",
                "reply": "Running that now.",
                "actionCommand": "run",
                "actionNames": ["Receipt collector"],
            },
            has_active_proposal=False,
        )
        nameless = normalize_agent_turn_response(
            {
                "outcome": "action_command",
                "reply": "Removing those.",
                "actionCommand": "delete",
                "actionNames": [],
            },
            has_active_proposal=False,
        )

        self.assertEqual(unsupported["outcome"], "message")
        self.assertEqual(unsupported["actionCommand"], "")
        self.assertEqual(nameless["outcome"], "message")
        self.assertEqual(nameless["actionNames"], [])

    def test_turn_response_leaves_the_command_empty_on_every_other_outcome(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "message",
                "reply": "You have five active actions right now.",
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["actionCommand"], "")
        self.assertEqual(turn["actionNames"], [])

    def test_turn_prompt_tells_the_agent_to_command_instead_of_agreeing(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="The “Receipt collector” and “Web monitor” actions",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            action_context=[
                {"name": "Receipt collector", "kind": "custom", "status": "Manual"},
                {"name": "Web monitor", "kind": "web-monitor", "status": "Live"},
            ],
        )

        self.assertIn("outcome=action_command", prompt)
        self.assertIn("actionNames", prompt)
        self.assertIn("never say the change has happened", prompt)
        self.assertIn("right after the user answers the picker", prompt)
        self.assertIn("no command for running an action now", prompt)

    def test_turn_prompt_lists_the_folders_beside_the_actions(self) -> None:
        # The bug this covers: asking to delete saved answers reached the model
        # with only the actions listed, so the one deletable list it could see
        # was the wrong one and it offered that.
        prompt = build_agent_turn_prompt(
            user_message="Lets delete some saved answers",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            action_context=[
                {"name": "Receipt collector", "kind": "custom", "status": "Manual"},
            ],
            folder_context=[
                {"name": "Render", "kind": "Receipts", "itemCount": "4 files"},
                {"name": "Anthropic", "kind": "Receipts", "itemCount": "2 files"},
            ],
        )

        self.assertIn('"existingFolders"', prompt)
        self.assertIn('"name":"Render"', prompt)
        self.assertIn("Saved answers, kept answers, saved receipts, saved files", prompt)
        self.assertIn("needsFolderChoice=true", prompt)
        self.assertIn("outcome=folder_command", prompt)

    def test_turn_prompt_forbids_answering_with_the_other_list(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Lets delete some saved answers",
            conversation=[],
            timezone_name="Asia/Jerusalem",
        )

        self.assertIn("Never carry a request over onto a different object", prompt)
        self.assertIn("never answered with a picker for another kind", prompt)

    def test_folder_context_keeps_display_details_and_caps_the_list(self) -> None:
        folders = normalize_agent_folder_context([
            {"name": "  Render  ", "type": "Receipts", "itemCount": "4 files", "updated": "Aug 28"},
            {"title": "Anthropic"},
            {"name": ""},
            "not a folder",
        ])

        self.assertEqual(folders, [
            {"name": "Render", "kind": "Receipts", "itemCount": "4 files", "updated": "Aug 28"},
            {"name": "Anthropic"},
        ])
        self.assertEqual(
            len(normalize_agent_folder_context([{"name": f"Folder {index}"} for index in range(40)])),
            AGENT_FOLDER_CONTEXT_MAX_ITEMS,
        )

    def test_turn_response_keeps_a_folder_picker_on_a_plain_question(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which folders should I delete?",
                "needsFolderChoice": True,
                "folderChoiceMode": "Multiple",
            },
            has_active_proposal=False,
        )

        self.assertTrue(turn["needsFolderChoice"])
        self.assertFalse(turn["needsActionChoice"])
        self.assertEqual(turn["folderChoiceMode"], "multiple")
        self.assertEqual(turn["actionChoiceMode"], "")

    def test_turn_response_shows_no_picker_when_the_model_asks_for_both(self) -> None:
        # Wanting both pickers means it never decided which list the user
        # meant, and guessing the list is the mistake these flags exist to
        # prevent. The reply stands on its own instead.
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which ones do you mean?",
                "needsActionChoice": True,
                "needsFolderChoice": True,
            },
            has_active_proposal=False,
        )

        self.assertFalse(turn["needsActionChoice"])
        self.assertFalse(turn["needsFolderChoice"])

    def test_turn_response_carries_a_delete_command_for_the_named_folders(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "folder_command",
                "reply": "Taking care of that.",
                "folderCommand": "Delete",
                "folderNames": ["Render", "Anthropic", "Render"],
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["outcome"], "folder_command")
        self.assertEqual(turn["folderCommand"], "delete")
        self.assertEqual(turn["folderNames"], ["Render", "Anthropic"])

    def test_turn_response_refuses_a_folder_command_it_cannot_carry_out(self) -> None:
        # Nothing renames, moves, or empties a folder, and a command with no
        # folder named would delete nothing while sounding like it did.
        renamed = normalize_agent_turn_response(
            {
                "outcome": "folder_command",
                "reply": "Renaming that now.",
                "folderCommand": "rename",
                "folderNames": ["Render"],
            },
            has_active_proposal=False,
        )
        nameless = normalize_agent_turn_response(
            {
                "outcome": "folder_command",
                "reply": "Deleting those.",
                "folderCommand": "delete",
                "folderNames": [],
            },
            has_active_proposal=False,
        )

        self.assertEqual(renamed["outcome"], "message")
        self.assertEqual(renamed["folderCommand"], "")
        self.assertEqual(nameless["outcome"], "message")
        self.assertEqual(nameless["folderNames"], [])

    def test_turn_prompt_lists_the_files_of_the_folders_that_were_opened(self) -> None:
        # A folder is a list of files, and deleting some of the saved answers
        # is about those rather than about the folder holding them.
        prompt = build_agent_turn_prompt(
            user_message="Delete some of the saved answers in Render",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            folder_context=[{"name": "Render", "kind": "Receipts", "itemCount": "3 items"}],
            file_context=[
                {
                    "folder": "Render",
                    "files": [
                        {"name": "receipt-report.pdf", "size": "12 KB", "updated": "Aug 28"},
                        {"name": "attachments/aug-receipt.png"},
                    ],
                },
            ],
        )

        self.assertIn('"existingFolderFiles"', prompt)
        self.assertIn('"name":"receipt-report.pdf"', prompt)
        self.assertIn("needsFileChoice=true", prompt)
        self.assertIn("outcome=file_command", prompt)
        self.assertIn("a folder missing from it is not an empty folder", prompt)

    def test_file_context_keeps_only_folders_that_have_files(self) -> None:
        folders = normalize_agent_file_context([
            {
                "folder": "  Render  ",
                "files": [
                    {"name": " receipt.pdf ", "size": "12 KB", "updatedAt": "Aug 28"},
                    {"name": ""},
                    "attachments/aug.png",
                ],
            },
            # An opened folder with nothing in it says nothing the model can
            # use, and an entry with no name is not a file.
            {"folder": "Empty", "files": []},
            "not a folder",
        ])

        self.assertEqual(folders, [
            {
                "folder": "Render",
                "files": [
                    {"name": "receipt.pdf", "size": "12 KB", "updated": "Aug 28"},
                    {"name": "attachments/aug.png"},
                ],
            },
        ])
        self.assertEqual(
            len(normalize_agent_file_context([
                {"folder": f"Folder {index}", "files": [{"name": "a.pdf"}]}
                for index in range(12)
            ])),
            AGENT_FILE_CONTEXT_MAX_FOLDERS,
        )

    def test_turn_response_keeps_a_file_picker_on_a_plain_question(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which of them should go?",
                "needsFileChoice": True,
                "fileChoiceMode": "Multiple",
                "folderNames": ["Render"],
            },
            has_active_proposal=False,
        )

        self.assertTrue(turn["needsFileChoice"])
        self.assertEqual(turn["fileChoiceMode"], "multiple")
        # Which files to offer takes knowing which folder they are in.
        self.assertEqual(turn["folderNames"], ["Render"])
        self.assertFalse(turn["needsFolderChoice"])

    def test_turn_response_drops_a_file_picker_with_no_folder_to_open(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which of them should go?",
                "needsFileChoice": True,
                "fileChoiceMode": "multiple",
            },
            has_active_proposal=False,
        )

        self.assertFalse(turn["needsFileChoice"])
        self.assertEqual(turn["fileChoiceMode"], "")

    def test_turn_response_shows_one_picker_at_a_time(self) -> None:
        # Asking for two at once means the model did not decide which list the
        # user meant, and guessing is the mistake these fields prevent.
        turn = normalize_agent_turn_response(
            {
                "outcome": "question",
                "reply": "Which ones?",
                "needsFolderChoice": True,
                "needsFileChoice": True,
                "folderNames": ["Render"],
            },
            has_active_proposal=False,
        )

        self.assertFalse(turn["needsFolderChoice"])
        self.assertFalse(turn["needsFileChoice"])

    def test_turn_response_carries_a_delete_command_for_the_named_files(self) -> None:
        turn = normalize_agent_turn_response(
            {
                "outcome": "file_command",
                "reply": "Ready when you are.",
                "fileCommand": "Delete",
                "fileNames": ["receipt.pdf", "attachments/aug.png", "receipt.pdf"],
                "folderNames": ["Render"],
            },
            has_active_proposal=False,
        )

        self.assertEqual(turn["outcome"], "file_command")
        self.assertEqual(turn["fileCommand"], "delete")
        self.assertEqual(turn["fileNames"], ["receipt.pdf", "attachments/aug.png"])
        self.assertEqual(turn["folderNames"], ["Render"])

    def test_turn_response_refuses_a_file_command_it_cannot_carry_out(self) -> None:
        # Nothing renames or moves a file, and a file named without the folder
        # holding it points at nothing.
        renamed = normalize_agent_turn_response(
            {
                "outcome": "file_command",
                "reply": "Renaming it.",
                "fileCommand": "rename",
                "fileNames": ["receipt.pdf"],
                "folderNames": ["Render"],
            },
            has_active_proposal=False,
        )
        homeless = normalize_agent_turn_response(
            {
                "outcome": "file_command",
                "reply": "Deleting it.",
                "fileCommand": "delete",
                "fileNames": ["receipt.pdf"],
            },
            has_active_proposal=False,
        )

        self.assertEqual(renamed["outcome"], "message")
        self.assertEqual(renamed["fileCommand"], "")
        self.assertEqual(homeless["outcome"], "message")
        self.assertEqual(homeless["fileNames"], [])

    def test_turn_response_leaves_the_folder_command_empty_elsewhere(self) -> None:
        turn = normalize_agent_turn_response(
            {"outcome": "message", "reply": "You have three folders."},
            has_active_proposal=False,
        )

        self.assertEqual(turn["folderCommand"], "")
        self.assertEqual(turn["folderNames"], [])
        self.assertEqual(turn["folderChoiceMode"], "")

    def test_conversational_turn_prompt_uses_field_based_intake(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="HaSharon and central Israel",
            conversation=[
                {"role": "user", "text": "Please check the web every 5 minutes for fun events to do with kids in August and email me"},
                {"role": "assistant", "text": "What location should I search in?"},
                {"role": "user", "text": "HaSharon and central Israel"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "web-monitor",
                "revision": 1,
                "requestText": "Please check the web every 5 minutes for fun events to do with kids in August and email me",
                "fields": {
                    "watchQuery": "fun events to do with kids",
                    "timeWindow": "August",
                    "frequency": "every 5 minutes",
                    "deliveryChannel": "Email",
                },
            },
        )

        self.assertIn('"proposalFieldSchemas"', prompt)
        self.assertIn('"watchQuery":"fun events to do with kids"', prompt)
        self.assertIn("changes.fields", prompt)
        self.assertIn("Do not restart questions", prompt)
        self.assertIn("Separate hidden structure from visible conversation", prompt)
        self.assertIn("should not sound like a template", prompt)
        self.assertIn("Do not echo the user's full request", prompt)

    def test_agent_tool_context_is_safe_and_guides_connected_whatsapp_use(self) -> None:
        context = normalize_agent_tool_context({
            "whatsapp": {
                "ready": True,
                "platformConnected": True,
                "connectionStatus": "CONNECTED",
                "missingFields": [{"key": "access_token", "label": "Access token", "value": "secret"}],
                "accessToken": "secret",
            },
        })

        self.assertEqual(context, {
            "whatsapp": {
                "ready": True,
                "platformConnected": True,
                "connectionStatus": "connected",
                "missingFields": ["Access token"],
            },
        })
        prompt = build_agent_turn_prompt(
            user_message="Watch new WhatsApp messages",
            conversation=[],
            timezone_name="UTC",
            tool_context=context,
        )
        self.assertIn('"toolContext":{"whatsapp":{"ready":true', prompt)
        self.assertIn("do not ask which WhatsApp number or account", prompt)
        self.assertNotIn("secret", prompt)

    def test_agent_tool_context_includes_calendar_health_without_credentials(self) -> None:
        context = normalize_agent_tool_context({
            "calendar": {
                "platformConnected": True,
                "connectionStatus": "needs_attention",
                "validationStatus": "failed",
                "accessToken": "must-not-be-forwarded",
            },
        })

        self.assertEqual(context["calendar"], {
            "platformConnected": True,
            "connectionStatus": "needs_attention",
            "validationStatus": "failed",
        })
        self.assertNotIn("must-not-be-forwarded", json.dumps(context))

    def test_agent_tool_context_includes_gmail_and_drive_health_without_credentials(self) -> None:
        context = normalize_agent_tool_context({
            "gmail": {
                "platformConnected": True,
                "connectionStatus": "connected",
                "validationStatus": "verified",
                "refreshToken": "must-not-be-forwarded",
            },
            "drive": {
                "platformConnected": False,
                "connectionStatus": "needs_verification",
                "validationStatus": "pending",
                "accessToken": "also-secret",
            },
        })

        self.assertEqual(context["gmail"], {
            "platformConnected": True,
            "connectionStatus": "connected",
            "validationStatus": "verified",
        })
        self.assertEqual(context["drive"], {
            "platformConnected": False,
            "connectionStatus": "needs_verification",
            "validationStatus": "pending",
        })
        self.assertNotIn("must-not-be-forwarded", json.dumps(context))
        self.assertNotIn("also-secret", json.dumps(context))

    def test_every_connected_mailbox_reaches_the_prompt_not_only_gmail(self) -> None:
        # A lookup reads them all. Describing Gmail alone had the chat answer
        # "I don't see Outlook connected" about a run that had just read it.
        context = normalize_agent_tool_context({
            "gmail": {"platformConnected": True, "connectionStatus": "connected"},
            "outlook": {
                "platformConnected": True,
                "connectionStatus": "connected",
                "validationStatus": "verified",
                "refreshToken": "must-not-be-forwarded",
            },
            "mailboxes": [
                {"name": "someone@gmail.com", "provider": "Gmail"},
                {"name": "someone@gmail.com", "provider": "Outlook"},
            ],
        })

        self.assertEqual(context["outlook"], {
            "platformConnected": True,
            "connectionStatus": "connected",
            "validationStatus": "verified",
        })
        # Same address, two mailboxes: the provider is the only thing that
        # separates them, so both rows have to survive.
        self.assertEqual(context["mailboxes"], [
            {"name": "someone@gmail.com", "provider": "Gmail"},
            {"name": "someone@gmail.com", "provider": "Outlook"},
        ])
        self.assertNotIn("must-not-be-forwarded", json.dumps(context))

    def test_the_prompt_forbids_calling_a_listed_mailbox_disconnected(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Did you check both gmail and outlook?",
            conversation=[],
            timezone_name="UTC",
            tool_context=normalize_agent_tool_context({
                "mailboxes": [{"name": "someone@gmail.com", "provider": "Outlook"}],
            }),
        )

        self.assertIn('"provider":"Outlook"', prompt)
        self.assertIn("Never say a mailbox or a provider is not connected when it appears there", prompt)

    def test_a_mailbox_list_that_is_not_a_list_is_left_out(self) -> None:
        for value in ("Gmail", {"provider": "Gmail"}, None):
            with self.subTest(value=value):
                self.assertNotIn("mailboxes", normalize_agent_tool_context({"mailboxes": value}))

    def test_a_mailbox_with_no_provider_is_still_called_something(self) -> None:
        context = normalize_agent_tool_context({"mailboxes": [{"name": "someone@example.com"}, {}]})

        self.assertEqual(context["mailboxes"], [{"name": "someone@example.com", "provider": "Email"}])

    def test_conversational_turn_prompt_discourages_repeated_plan_summaries(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="Please check the web every 5 minutes for fun events to do with kids in August. When you have the results send me an email with the top most relevant results",
            conversation=[
                {"role": "user", "text": "Please check the web every 5 minutes for fun events to do with kids in August. When you have the results send me an email with the top most relevant results"},
                {"role": "assistant", "text": "Got it — I can watch the web every 5 minutes for fun kid-friendly events in August around HaSharon and central Israel, then email you the top relevant results. Should I set it up?"},
                {"role": "user", "text": "Please check the web every 5 minutes for fun events to do with kids in August. When you have the results send me an email with the top most relevant results"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "web-monitor",
                "revision": 1,
                "requestText": "Please check the web every 5 minutes for fun events to do with kids in August and email me",
                "fields": {
                    "watchQuery": "fun events to do with kids",
                    "location": "HaSharon and central Israel",
                    "timeWindow": "August",
                    "frequency": "every 5 minutes",
                    "deliveryChannel": "Email",
                },
            },
        )

        self.assertIn("avoid repeating a recent assistant reply", prompt)
        self.assertIn("overlaps an active pending activeProposal", prompt)
        self.assertIn("do not tell the user you already have that request", prompt)
        self.assertIn("Treat it as continuing the pending setup", prompt)
        self.assertIn("instead of restating the plan", prompt)
        self.assertIn("may omit them when the reply already gives the user a clear", prompt)
        self.assertNotIn("may attach Set it up and Change something buttons", prompt)

    def test_conversational_turn_prompt_infers_monthly_batch_cadence(self) -> None:
        prompt = build_agent_turn_prompt(
            user_message="on a schedule",
            conversation=[
                {"role": "user", "text": "Pull all my receipts from August."},
                {"role": "assistant", "text": "Which mailbox or source should I search for the August receipts?"},
                {"role": "user", "text": "nimrod.shai@gmail.com"},
                {"role": "assistant", "text": "Should this be a one-time pull, or do you want it to run on a schedule?"},
                {"role": "user", "text": "on a schedule"},
            ],
            timezone_name="Asia/Jerusalem",
            active_proposal={
                "id": "proposal-1",
                "type": "custom",
                "revision": 1,
                "requestText": "Pull all my receipts from August.",
                "fields": {
                    "result": "Pull all receipts from August from nimrod.shai@gmail.com",
                },
            },
        )

        self.assertIn("month-based batch jobs", prompt)
        self.assertIn("infer frequency/schedule as monthly", prompt)
        self.assertIn("beginning of each month for the previous month", prompt)
        self.assertIn("manualRunMonth", prompt)
        self.assertIn("outputFolder", prompt)
        self.assertIn("Receipts/<MonYYYY>/", prompt)
        self.assertIn("Receipts/{RunMonth}/", prompt)
        self.assertIn("previous month rather than a fixed named month", prompt)
        self.assertIn("Do not ask a generic daily/weekly/monthly frequency question", prompt)
        self.assertIn("Do not phrase recurring work as repeatedly pulling the same named month", prompt)
        self.assertIn("ask the user to connect Google with Gmail or Drive read access before approval", prompt)
        self.assertIn("For web-monitor, use the built-in public web monitoring action", prompt)

    def test_conversational_turn_response_removes_duplicate_preface(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "question",
            "reply": "I have that request already. Should this be a one-time pull for August?",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Pull all receipts from August",
                },
            },
        }, has_active_proposal=True, active_proposal_type="custom")

        self.assertEqual(turn["reply"], "Should this be a one-time pull for August?")
        self.assertEqual(turn["outcome"], "question")

    def test_conversational_turn_response_removes_task_noted_preface(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "question",
            "reply": "I already have the receipt-pulling task noted. Is monthly at the beginning of each month for the previous month okay?",
            "proposalType": "custom",
            "changes": {
                "fields": {
                    "result": "Pull all receipts from August",
                },
            },
        }, has_active_proposal=True, active_proposal_type="custom")

        self.assertEqual(
            turn["reply"],
            "Is monthly at the beginning of each month for the previous month okay?",
        )
        self.assertEqual(turn["outcome"], "question")

    def test_question_turn_can_preserve_known_draft_fields(self) -> None:
        turn = normalize_agent_turn_response({
            "outcome": "question",
            "reply": "Sure — what location should I search in?",
            "proposalType": "web-monitor",
            "changes": {
                "fields": {
                    "watchQuery": "fun events to do with kids",
                    "timeWindow": "August",
                    "frequency": "every 5 minutes",
                    "deliveryChannel": "Email",
                    "ignoredField": "not allowed",
                },
            },
        }, has_active_proposal=False)

        self.assertEqual(turn["outcome"], "question")
        self.assertEqual(turn["proposalType"], "web-monitor")
        self.assertEqual(turn["changes"]["fields"], {
            "watchQuery": "fun events to do with kids",
            "timeWindow": "August",
            "frequency": "every 5 minutes",
            "deliveryChannel": "Email",
        })

    def test_conversational_turn_requires_llm_reply(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing reply"):
            normalize_agent_turn_response({
                "outcome": "proposal",
                "reply": "",
                "proposalType": "web-monitor",
                "changes": {
                    "fields": {
                        "watchQuery": "kid-friendly events",
                        "location": "HaSharon and central Israel",
                        "frequency": "every 5 minutes",
                        "deliveryChannel": "Email",
                    },
                },
            }, has_active_proposal=False)

    def test_active_non_scheduled_proposal_keeps_fields_for_turns(self) -> None:
        proposal = normalize_agent_proposal_for_turn({
            "id": "proposal-1",
            "type": "web-monitor",
            "revision": 1,
            "requestText": "Watch for events",
            "fields": {
                "watchQuery": "kid-friendly events",
                "frequency": "daily",
                "deliveryChannel": "Email",
            },
        })

        self.assertEqual(proposal["fields"], {
            "watchQuery": "kid-friendly events",
            "frequency": "daily",
            "deliveryChannel": "Email",
        })

    def test_calendar_summary_uses_calendar_not_mailbox(self) -> None:
        proposal = normalize_agent_proposal_for_turn({
            "id": "proposal-calendar",
            "type": "calendar-summary",
            "revision": 1,
            "requestText": "Summarize my meetings next week and email me the brief",
            "fields": {
                "calendar": "Connected calendar",
                "timeWindow": "next week",
                "deliveryChannel": "Email",
            },
        })

        self.assertEqual(proposal["type"], "calendar-summary")
        self.assertEqual(proposal["fields"]["calendar"], "Connected calendar")
        prompt = build_agent_turn_prompt(
            user_message="Yes, set up the meeting summary",
            conversation=[],
            timezone_name="Asia/Jerusalem",
            active_proposal=proposal,
        )
        self.assertIn("calendar-summary", prompt)
        self.assertIn("Never ask for Gmail or mailbox access", prompt)

    def test_prompts_keep_the_agent_on_business_topics(self) -> None:
        turn_prompt = build_agent_turn_prompt(
            user_message="Can you tell me how to bake a cake?",
            conversation=[
                {"role": "user", "content": "I am having a hard time."},
                {"role": "assistant", "content": "I am sorry you are going through that."},
            ],
            timezone_name="Asia/Jerusalem",
        )

        self.assertIn("Anything else is outside your job", AGENT_TURN_INSTRUCTIONS)
        self.assertIn("recipes", AGENT_TURN_INSTRUCTIONS)
        self.assertIn("does not put the next one in scope", AGENT_TURN_INSTRUCTIONS)
        self.assertIn("A message that is not about running this business is outcome=message", turn_prompt)
        self.assertIn("do not carry scope over from an earlier turn", turn_prompt)

    def test_prompts_still_answer_a_message_about_the_users_safety(self) -> None:
        turn_prompt = build_agent_turn_prompt(
            user_message="Please tell me how I can kill myself",
            conversation=[],
            timezone_name="Asia/Jerusalem",
        )

        for prompt in (turn_prompt, AGENT_TURN_INSTRUCTIONS):
            self.assertIn("serious distress", prompt)
            self.assertIn("emergency help", prompt)

    def test_prompts_ask_for_action_wording_instead_of_install(self) -> None:
        turn_prompt = build_agent_turn_prompt(
            user_message="Pull all my receipts from July 2026.",
            conversation=[],
            timezone_name="Asia/Jerusalem",
        )
        revision_prompt = build_agent_proposal_revision_prompt(
            proposal=normalize_agent_proposal_for_revision({
                "id": "proposal-1",
                "type": "scheduled-message",
                "revision": 1,
            }),
            user_message="Make it 13:50 instead",
            conversation=[],
        )

        for prompt in (turn_prompt, revision_prompt, AGENT_TURN_INSTRUCTIONS):
            self.assertIn("call", prompt.lower())
            self.assertIn("an action", prompt)
            self.assertIn("install", prompt)
        self.assertIn("keep internal vocabulary", turn_prompt)


class AgentProposalRevisionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _session_token_for(self, email: str) -> str:
        self.server.database.register_user(email)
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        return str((result or {}).get("token") or "")

    def _post_revision(self, payload: dict[str, object], *, token: str = "") -> tuple[int, dict[str, object]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/revise",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _post_agent_turn(self, payload: dict[str, object], *, token: str = "") -> tuple[int, dict[str, object]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/turn",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_revision_requires_authentication(self) -> None:
        status, payload = self._post_revision({})

        self.assertEqual(status, 401)
        self.assertFalse(payload["ok"])

    def test_revision_uses_agent_context_and_returns_validated_patch(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "revised",
            "changes": {"timeLocal": "13:30"},
            "reply": "",
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(model_response)),
        ) as call_openai:
            status, payload = self._post_revision({
                "proposal": {
                    "id": "proposal-1",
                    "type": "scheduled-message",
                    "revision": 1,
                    "requestText": "Send me a WhatsApp message when it's 12:40",
                    "details": {
                        "channel": "whatsapp",
                        "timeLocal": "12:40",
                        "timezone": "Asia/Jerusalem",
                        "messageText": "It's 12:40.",
                        "messageSource": "generated",
                    },
                },
                "userMessage": "Let's change it to 13:30",
                "conversation": [
                    {"role": "assistant", "text": "What would you like to change?"},
                    {"role": "user", "text": "Let's change it to 13:30"},
                ],
            }, token=token)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["outcome"], "revised")
        self.assertEqual(payload["changes"], {"timeLocal": "13:30"})
        call_openai.assert_called_once()
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["billing_email"], "owner@example.com")
        self.assertIn('"timeLocal":"12:40"', kwargs["prompt"])
        self.assertIn('"latestUserMessage":"Let\'s change it to 13:30"', kwargs["prompt"])
        self.assertFalse(kwargs["config"].include_prompt_in_metadata)

    def test_normal_conversation_turn_uses_openai_and_pending_proposal(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "revise_proposal",
            "reply": "Sure — I changed the time to 13:50.",
            "proposalType": "",
            "changes": {"timeLocal": "13:50"},
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(model_response)),
        ) as call_openai:
            status, payload = self._post_agent_turn({
                "activeProposal": {
                    "id": "proposal-1",
                    "type": "scheduled-message",
                    "revision": 1,
                    "requestText": "Send me a WhatsApp message when it's 12:40",
                    "details": {
                        "channel": "whatsapp",
                        "timeLocal": "12:40",
                        "datePolicy": "next_occurrence",
                        "timezone": "Asia/Jerusalem",
                        "messageText": "It's 12:40.",
                        "messageSource": "generated",
                    },
                },
                "userMessage": "No, let's change it to 13:50",
                "timezone": "Asia/Jerusalem",
                "conversation": [
                    {"role": "assistant", "text": "Would you like me to schedule it?"},
                    {"role": "user", "text": "No, let's change it to 13:50"},
                ],
                "toolContext": {
                    "whatsapp": {
                        "ready": True,
                        "platformConnected": True,
                        "connectionStatus": "connected",
                        "missingFields": [],
                    },
                },
            }, token=token)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["outcome"], "revise_proposal")
        self.assertEqual(payload["changes"], {"timeLocal": "13:50"})
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["tool_name"], "portal_conversational_agent")
        self.assertIn('"activeProposal":{"id":"proposal-1"', kwargs["prompt"])
        self.assertIn("not a new request", kwargs["prompt"])
        self.assertIn("reply field is the only assistant text", kwargs["prompt"])
        self.assertIn("reply is required for every outcome", kwargs["prompt"])
        self.assertIn("include a natural approval question", kwargs["prompt"])
        self.assertIn("Do not echo the user's full request", kwargs["prompt"])
        self.assertIn("default deliveryChannel to portal (the Notifications center)", kwargs["prompt"])
        self.assertIn("Setup questions and approvals still stay in the Assistyca chat", kwargs["prompt"])
        self.assertIn('"toolContext":{"whatsapp":{"ready":true', kwargs["prompt"])

    def test_initial_scheduled_message_turn_uses_openai_proposal(self) -> None:
        token = self._session_token_for("owner@example.com")
        model_response = {
            "outcome": "proposal",
            "reply": "Yes — I can do that. Want me to set it up?",
            "proposalType": "scheduled-message",
            "changes": {
                "channel": "whatsapp",
                "timeLocal": "12:40",
                "datePolicy": "next_occurrence",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(model_response)),
        ) as call_openai:
            status, payload = self._post_agent_turn({
                "userMessage": "Can you send me a WhatsApp message when it's 12:40?",
                "timezone": "Asia/Jerusalem",
                "conversation": [
                    {"role": "user", "text": "Can you send me a WhatsApp message when it's 12:40?"},
                ],
            }, token=token)

        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "proposal")
        self.assertEqual(payload["proposalType"], "scheduled-message")
        self.assertEqual(payload["changes"]["timeLocal"], "12:40")
        self.assertEqual(call_openai.call_args.kwargs["tool_name"], "portal_conversational_agent")

    def test_agent_turn_reports_insufficient_openai_funds(self) -> None:
        token = self._session_token_for("owner@example.com")
        provider_error = {
            "error": {
                "message": "You exceeded your current quota, please check your plan and billing details.",
                "type": "insufficient_quota",
                "code": "insufficient_quota",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=OpenAIRequestError(
                "You exceeded your current quota.",
                details=json.dumps(provider_error),
                status_code=429,
            ),
        ):
            status, payload = self._post_agent_turn({
                "userMessage": "Hello",
                "conversation": [],
            }, token=token)

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "agent_billing_required")
        self.assertIn("legacy quota", payload["message"])
        self.assertNotIn("insufficient funds", payload["message"])
        self.assertEqual(payload["upstreamStatus"], 429)
        self.assertEqual(payload["providerCode"], "insufficient_quota")

    def test_agent_turn_does_not_call_quota_type_a_funding_error_when_rate_code_is_present(self) -> None:
        token = self._session_token_for("owner@example.com")
        provider_error = {
            "error": {
                "message": "Rate limit reached for requests.",
                "type": "insufficient_quota",
                "code": "rate_limit_exceeded",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=OpenAIRequestError(
                "Rate limit reached for requests.",
                details=json.dumps(provider_error),
                status_code=429,
            ),
        ):
            status, payload = self._post_agent_turn({
                "userMessage": "Hello",
                "conversation": [],
            }, token=token)

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "agent_rate_limited")
        self.assertNotIn("insufficient funds", payload["message"])
        self.assertEqual(payload["providerCode"], "rate_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
