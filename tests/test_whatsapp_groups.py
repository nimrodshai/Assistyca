from __future__ import annotations

import json
import unittest
from unittest import mock

from packages.infrastructure.whatsapp_api import WhatsAppConnectionError
from packages.infrastructure.whatsapp_api import create_whatsapp_group
from packages.infrastructure.whatsapp_api import fetch_whatsapp_group
from packages.infrastructure.whatsapp_api import remove_whatsapp_group_participants


class FakeGraphResponse:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")


def group_message_payload(*, group_id: str, sender: str, name: str, text: str, message_id: str = "wamid.1") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "1555", "phone_number_id": "PHONE"},
                            "contacts": [{"profile": {"name": name}, "wa_id": sender}],
                            "messages": [
                                {
                                    "from": sender,
                                    "group_id": group_id,
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class CreateGroupTests(unittest.TestCase):
    def test_a_group_comes_back_with_the_link_people_join_by(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse(
                '{"messaging_product":"whatsapp","id":"GROUP1","invite_link":"https://chat.whatsapp.com/ABC"}'
            ),
        ) as urlopen:
            created = create_whatsapp_group(
                access_token="token",
                phone_number_id="PHONE",
                subject="Shai family",
                description="Ours",
            )

        self.assertEqual(created["id"], "GROUP1")
        self.assertEqual(created["invite_link"], "https://chat.whatsapp.com/ABC")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertTrue(request.full_url.endswith("/PHONE/groups"))
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"messaging_product": "whatsapp", "subject": "Shai family", "description": "Ours"},
        )

    def test_a_group_needs_a_name(self) -> None:
        with self.assertRaises(ValueError):
            create_whatsapp_group(access_token="token", phone_number_id="PHONE", subject="  ")

    def test_an_unverified_business_is_told_what_meta_said(self) -> None:
        error = json.dumps({"error": {"message": "Groups require an Official Business Account", "code": 100}})
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse(error),
        ):
            with self.assertRaises(WhatsAppConnectionError) as raised:
                create_whatsapp_group(access_token="token", phone_number_id="PHONE", subject="Shai family")

        self.assertIn("Official Business Account", str(raised.exception))

    def test_a_group_is_read_by_the_fields_that_were_asked_for(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"id":"GROUP1","subject":"Shai family"}'),
        ) as urlopen:
            fetch_whatsapp_group(access_token="token", group_id="GROUP1", fields=("subject", "participants"))

        self.assertIn("fields=subject,participants", urlopen.call_args.args[0].full_url)

    def test_somebody_can_be_taken_back_out(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"success":true}'),
        ) as urlopen:
            remove_whatsapp_group_participants(
                access_token="token",
                group_id="GROUP1",
                participants=["972500000000"],
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "DELETE")
        self.assertTrue(request.full_url.endswith("/GROUP1/participants"))
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"messaging_product": "whatsapp", "participants": [{"user": "972500000000"}]},
        )

    def test_removing_nobody_is_refused_before_the_call(self) -> None:
        with self.assertRaises(ValueError):
            remove_whatsapp_group_participants(access_token="token", group_id="GROUP1", participants=[])


class GroupThreadingTests(unittest.TestCase):
    def test_a_group_message_threads_on_the_group_not_the_speaker(self) -> None:
        from packages.tools.whatsapp_reply_approval.server import extract_inbound_events

        events = extract_inbound_events(
            group_message_payload(group_id="GROUP1", sender="972500000001", name="Dana", text="who is on pickup?")
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["thread_id"], "GROUP1")
        self.assertEqual(events[0]["group_id"], "GROUP1")
        self.assertEqual(events[0]["sender_wa_id"], "972500000001")
        self.assertEqual(events[0]["sender_name"], "Dana")

    def test_a_one_to_one_message_still_threads_on_the_person(self) -> None:
        from packages.tools.whatsapp_reply_approval.server import extract_inbound_events

        payload = group_message_payload(group_id="", sender="972500000001", name="Dana", text="hello")
        del payload["entry"][0]["changes"][0]["value"]["messages"][0]["group_id"]

        events = extract_inbound_events(payload)
        self.assertEqual(events[0]["thread_id"], "972500000001")
        self.assertEqual(events[0]["group_id"], "")

    def test_two_people_in_one_delivery_keep_their_own_names(self) -> None:
        from packages.tools.whatsapp_reply_approval.server import extract_inbound_events

        payload = group_message_payload(group_id="GROUP1", sender="972500000001", name="Dana", text="who is on pickup?")
        value = payload["entry"][0]["changes"][0]["value"]
        value["contacts"].append({"profile": {"name": "Yotam"}, "wa_id": "972500000002"})
        value["messages"].append(
            {
                "from": "972500000002",
                "group_id": "GROUP1",
                "id": "wamid.2",
                "timestamp": "1700000001",
                "type": "text",
                "text": {"body": "me"},
            }
        )

        events = extract_inbound_events(payload)
        self.assertEqual([event["sender_wa_id"] for event in events], ["972500000001", "972500000002"])
        self.assertEqual([event["sender_name"] for event in events], ["Dana", "Yotam"])
        self.assertEqual({event["thread_id"] for event in events}, {"GROUP1"})


class FakeConnectionStore:
    def __init__(self) -> None:
        self.metadata: dict = {}

    def get_whatsapp_connection_by_user_id(self, user_id: int) -> dict:
        return {"userId": user_id, "metadata": dict(self.metadata)}

    def update_whatsapp_connection_metadata(self, *, user_id: int, metadata_updates: dict) -> dict:
        self.metadata.update(metadata_updates)
        return {"userId": user_id, "metadata": dict(self.metadata)}


def group_tool_context(database: FakeConnectionStore) -> "LoopContext":
    from packages.infrastructure.agent_loop import LoopContext

    return LoopContext(
        api=lambda *args, **kwargs: ({"ok": True}, 200),
        database=database,
        email="owner@example.com",
        user_id=1,
        channel="whatsapp",
    )


class CreateGroupChatToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FakeConnectionStore()
        self.context = group_tool_context(self.database)
        self.env = mock.patch.dict(
            "os.environ",
            {
                "WHATSAPP_GROUPS_ENABLED": "1",
                "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "token",
                "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "PHONE",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_tool(self, **args) -> dict:
        from packages.infrastructure.agent_loop import _tool_create_group_chat

        return _tool_create_group_chat(self.context, args)

    def test_the_person_gets_the_link_and_the_group_is_remembered(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse(
                '{"id":"GROUP1","invite_link":"https://chat.whatsapp.com/ABC"}'
            ),
        ):
            result = self.run_tool(name="Shai family")

        self.assertTrue(result["ok"])
        self.assertEqual(result["inviteLink"], "https://chat.whatsapp.com/ABC")
        self.assertEqual(result["peopleItHolds"], 7)
        self.assertEqual(self.database.metadata["groups"][0]["id"], "GROUP1")
        self.assertIn("https://chat.whatsapp.com/ABC", self.context.links_offered)
        self.assertIn("https://chat.whatsapp.com/ABC", self.context.required_links)

    def test_nothing_is_created_while_the_feature_is_off(self) -> None:
        with mock.patch.dict("os.environ", {"WHATSAPP_GROUPS_ENABLED": "0"}):
            with mock.patch(
                "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
                side_effect=AssertionError("a switched-off tool must not reach Meta"),
            ):
                result = self.run_tool(name="Shai family")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unavailable")

    def test_a_group_without_a_name_is_asked_about_rather_than_guessed(self) -> None:
        result = self.run_tool(name="  ")
        self.assertEqual(result["error"]["code"], "missing_input")

    def test_a_refusal_from_meta_is_not_reported_as_a_group(self) -> None:
        error = json.dumps({"error": {"message": "Groups require an Official Business Account", "code": 100}})
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse(error),
        ):
            result = self.run_tool(name="Shai family")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "group_not_created")
        self.assertTrue(result["error"]["canRetry"])
        self.assertEqual(self.database.metadata, {})

    def test_the_tool_is_one_the_model_can_see(self) -> None:
        from packages.infrastructure.agent_loop import tool_definitions

        by_name = {tool["name"]: tool for tool in tool_definitions({})}
        self.assertIn("create_group_chat", by_name)
        self.assertIn("nobody is added", by_name["create_group_chat"]["description"])


if __name__ == "__main__":
    unittest.main()
