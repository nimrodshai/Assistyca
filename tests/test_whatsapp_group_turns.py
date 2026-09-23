"""A message in a group: answered, let be, and never out of the account.

What these prove is the shape of a group turn. The decision to speak comes
first and a quiet one sends nothing; the conversation a group has is its own
and never the owner's; and the tools that read an account are shut off in a
group, both where the model sees them and where a call is run.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.agent_loop import GROUP_TOOLS
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat


class FakeGroupDatabase:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.history: list[dict] = []
        self.asked_threads: list[str] = []

    def list_recent_whatsapp_agent_messages(self, *, user_id: int, limit: int = 12, thread_id: str = "") -> list[dict]:
        self.asked_threads.append(thread_id)
        return [item for item in self.history if item.get("threadId", "") == thread_id][-limit:]

    def save_whatsapp_agent_message(
        self, *, user_id: int, role: str, text: str, thread_id: str = "", message_id: str = ""
    ) -> dict:
        row = {"userId": user_id, "role": role, "text": text, "threadId": thread_id, "messageId": message_id}
        self.saved.append(row)
        self.history.append(row)
        return row


def group_chat(database: FakeGroupDatabase) -> WhatsAppAgentChat:
    return WhatsAppAgentChat(
        database=database,
        connection={"userId": 1, "email": "owner@example.com", "ownerWaId": "972500000000"},
        base_url="http://127.0.0.1:1",
        session_token_factory=lambda email: "token",
    )


class GroupTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FakeGroupDatabase()
        self.chat = group_chat(self.database)

    def test_a_message_that_is_not_for_it_is_written_down_and_left_alone(self) -> None:
        with mock.patch.object(self.chat, "_ask_group_voice", return_value='{"speak":false,"reason":"they are talking"}'):
            with mock.patch(
                "packages.infrastructure.whatsapp_agent_chat.send_assistyca_group_text",
                side_effect=AssertionError("a quiet turn must send nothing"),
            ):
                result = self.chat.handle_group_message(
                    "are we still on for 6?",
                    group_id="GROUP1",
                    speaker_name="Dana",
                )

        self.assertEqual(result["action"], "stayed_quiet")
        self.assertEqual(result["decided_by"], "model")
        self.assertEqual(len(self.database.saved), 1)
        self.assertEqual(self.database.saved[0]["threadId"], "GROUP1")
        self.assertEqual(self.database.saved[0]["text"], "Dana: are we still on for 6?")

    def test_being_named_is_answered_in_the_group(self) -> None:
        with mock.patch.object(self.chat, "_api", return_value=({"ok": True, "reply": "Tuesday at four."}, 200)) as api:
            with mock.patch(
                "packages.infrastructure.whatsapp_agent_chat.send_assistyca_group_text",
                return_value="wamid.sent",
            ) as send:
                result = self.chat.handle_group_message(
                    "Assistyca, when is it?",
                    group_id="GROUP1",
                    group_name="Shai family",
                    speaker_name="Dana",
                )

        self.assertEqual(result["action"], "group_reply")
        self.assertEqual(result["decided_by"], "addressed")
        self.assertEqual(send.call_args.kwargs["group_id"], "GROUP1")
        self.assertEqual(send.call_args.kwargs["text"], "Tuesday at four.")
        payload = api.call_args.args[2]
        self.assertEqual(payload["group"], {"id": "GROUP1", "name": "Shai family", "speaker": "Dana"})
        assistant_rows = [row for row in self.database.saved if row["role"] == "assistant"]
        self.assertEqual(assistant_rows[0]["threadId"], "GROUP1")
        self.assertEqual(assistant_rows[0]["messageId"], "wamid.sent")

    def test_replying_to_something_it_said_is_being_addressed(self) -> None:
        self.database.history.append(
            {"role": "assistant", "text": "Tuesday at four.", "threadId": "GROUP1", "messageId": "wamid.mine"}
        )
        with mock.patch.object(self.chat, "_ask_group_voice", side_effect=AssertionError("no judgement needed")):
            with mock.patch.object(self.chat, "_api", return_value=({"ok": True, "reply": "Yes."}, 200)):
                with mock.patch(
                    "packages.infrastructure.whatsapp_agent_chat.send_assistyca_group_text",
                    return_value="wamid.sent",
                ):
                    result = self.chat.handle_group_message(
                        "and the week after?",
                        group_id="GROUP1",
                        speaker_name="Dana",
                        reply_to_message_id="wamid.mine",
                    )

        self.assertEqual(result["action"], "group_reply")
        self.assertEqual(result["decided_by"], "addressed")

    def test_the_group_reads_its_own_conversation_and_not_the_owner_s(self) -> None:
        self.database.history.append({"role": "user", "text": "my salary slip", "threadId": "", "messageId": ""})
        self.database.history.append({"role": "user", "text": "Dana: hi all", "threadId": "GROUP1", "messageId": ""})

        with mock.patch.object(self.chat, "_api", return_value=({"ok": True, "reply": "Hello."}, 200)) as api:
            with mock.patch(
                "packages.infrastructure.whatsapp_agent_chat.send_assistyca_group_text",
                return_value="wamid.sent",
            ):
                self.chat.handle_group_message("Assistyca, hello", group_id="GROUP1", speaker_name="Dana")

        self.assertEqual(self.database.asked_threads, ["GROUP1"])
        conversation = api.call_args.args[2]["conversation"]
        self.assertEqual([item["text"] for item in conversation], ["Dana: hi all"])

    def test_a_turn_that_fails_says_nothing_rather_than_reporting_itself(self) -> None:
        with mock.patch.object(self.chat, "_api", return_value=({"ok": False}, 500)):
            with mock.patch(
                "packages.infrastructure.whatsapp_agent_chat.send_assistyca_group_text",
                side_effect=AssertionError("a failed turn must send nothing"),
            ):
                result = self.chat.handle_group_message(
                    "Assistyca, when is it?",
                    group_id="GROUP1",
                    speaker_name="Dana",
                )

        self.assertEqual(result["action"], "stayed_quiet")

    def test_a_group_message_needs_the_group_it_was_sent_in(self) -> None:
        from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChatError

        with self.assertRaises(WhatsAppAgentChatError):
            self.chat.handle_group_message("hello", group_id="")


class GroupToolTests(unittest.TestCase):
    def test_the_model_is_shown_that_an_account_is_not_readable_here(self) -> None:
        in_group = {tool["name"]: tool for tool in tool_definitions({}, in_group=True)}
        self.assertIn("This is a group", in_group["read_inbox"]["description"])
        self.assertIn("This is a group", in_group["create_list"]["description"])
        self.assertNotIn("This is a group", in_group["search_web"]["description"])

    def test_the_tools_left_in_a_group_read_nothing_of_anyone_s(self) -> None:
        self.assertEqual(GROUP_TOOLS, frozenset({"search_web", "search_news", "look_up_property", "exchange_rate"}))

    def test_a_call_to_a_shut_off_tool_is_refused_and_not_run(self) -> None:
        calls: list[str] = []
        seen: list[list[dict]] = []

        def call_model(input_items, tools):
            seen.append(list(input_items))
            if not calls:
                calls.append("read_inbox")
                return SimpleNamespace(
                    output_text="",
                    raw_response={
                        "output": [
                            {
                                "type": "function_call",
                                "name": "read_inbox",
                                "call_id": "c1",
                                "arguments": json.dumps({"question": "anything new?"}),
                            }
                        ]
                    },
                    input_tokens=1,
                    output_tokens=1,
                )
            return SimpleNamespace(
                output_text=json.dumps({"reply": "Not here.", "claimsCompleted": []}),
                raw_response={"output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}]},
                input_tokens=1,
                output_tokens=1,
            )

        context = LoopContext(
            api=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("a group turn must not reach the account")),
            database=None,
            email="owner@example.com",
            user_id=1,
            channel="whatsapp",
            in_group=True,
            group={"id": "GROUP1", "name": "Shai family", "speaker": "Dana"},
        )
        result = run_agent_loop(
            context=context,
            call_model=call_model,
            user_message="anything new in my mail?",
            conversation=[],
            today="2026-09-23",
        )

        self.assertEqual(result.reply, "Not here.")
        # The refusal goes back to the model in place of a result, and the
        # account was never reached: the api would have raised if it had been.
        refusals = [
            json.loads(item["output"])
            for item in seen[-1]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        self.assertEqual(refusals[0]["error"]["code"], "not_here")
        self.assertIn("This is a group", refusals[0]["error"]["whatHappened"])


class GroupLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)

    def test_a_group_finds_the_account_that_opened_it(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            phone_number_id="PHONE",
            owner_wa_id="972500000000",
            metadata={"groups": [{"id": "GROUP1", "subject": "Shai family"}]},
        )

        found = self.database.get_whatsapp_connection_by_group_id("GROUP1")

        self.assertIsNotNone(found)
        self.assertEqual(int(found["userId"]), self.user_id)

    def test_a_group_nobody_opened_belongs_to_nobody(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            phone_number_id="PHONE",
            owner_wa_id="972500000000",
            metadata={"groups": [{"id": "GROUP1", "subject": "Shai family"}]},
        )

        self.assertIsNone(self.database.get_whatsapp_connection_by_group_id("GROUP2"))
        self.assertIsNone(self.database.get_whatsapp_connection_by_group_id(""))

    def test_a_group_keeps_its_own_transcript(self) -> None:
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="my salary slip")
        self.database.save_whatsapp_agent_message(
            user_id=self.user_id, role="user", text="Dana: hi all", thread_id="GROUP1"
        )

        own = self.database.list_recent_whatsapp_agent_messages(user_id=self.user_id)
        group = self.database.list_recent_whatsapp_agent_messages(user_id=self.user_id, thread_id="GROUP1")

        self.assertEqual([item["text"] for item in own], ["my salary slip"])
        self.assertEqual([item["text"] for item in group], ["Dana: hi all"])


class GroupSendTests(unittest.TestCase):
    def test_a_group_message_is_addressed_to_the_group(self) -> None:
        from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'{"messages":[{"id":"wamid.sent"}]}'

        with mock.patch(
            "packages.tools.whatsapp_reply_approval.server.urllib_request.urlopen",
            return_value=Response(),
        ) as urlopen:
            sent = send_whatsapp_message(
                access_token="token",
                phone_number_id="PHONE",
                api_version="v20.0",
                recipient_wa_id="GROUP1",
                message_text="Tuesday at four.",
                to_group=True,
            )

        self.assertEqual(sent, "wamid.sent")
        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["recipient_type"], "group")
        self.assertEqual(body["to"], "GROUP1")

    def test_buttons_are_refused_rather_than_sent_into_a_group(self) -> None:
        from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message

        with self.assertRaises(RuntimeError):
            send_whatsapp_message(
                access_token="token",
                phone_number_id="PHONE",
                api_version="v20.0",
                recipient_wa_id="GROUP1",
                interactive={"type": "button"},
                to_group=True,
            )


if __name__ == "__main__":
    unittest.main()
