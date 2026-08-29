"""Coexistence: the owner keeps WhatsApp on their phone, we only watch it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.whatsapp_portal_service import PortalWhatsAppService
from packages.infrastructure.whatsapp_portal_service import build_portal_runtime_config
from packages.tools.whatsapp_reply_approval.server import BackendStore
from packages.tools.whatsapp_reply_approval.server import extract_coexistence_events
from packages.tools.whatsapp_reply_approval.server import extract_inbound_events

BUSINESS_NUMBER = "15550783881"
CUSTOMER_NUMBER = "16505551234"


def echo_payload(*, text: str = "Here's the info you requested.", message_id: str = "wamid.echo1") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "smb_message_echoes",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": BUSINESS_NUMBER,
                                "phone_number_id": "106540352242922",
                            },
                            "message_echoes": [
                                {
                                    "from": BUSINESS_NUMBER,
                                    "to": CUSTOMER_NUMBER,
                                    "id": message_id,
                                    "timestamp": "1739321024",
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


def history_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "history",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": BUSINESS_NUMBER,
                                "phone_number_id": "106540352242922",
                            },
                            "history": [
                                {
                                    "metadata": {"phase": "0", "chunk_order": 1, "progress": 100},
                                    "threads": [
                                        {
                                            "id": CUSTOMER_NUMBER,
                                            "messages": [
                                                {
                                                    "from": CUSTOMER_NUMBER,
                                                    "to": BUSINESS_NUMBER,
                                                    "id": "wamid.hist-in",
                                                    "timestamp": "1739300000",
                                                    "type": "text",
                                                    "text": {"body": "Are you open Sunday?"},
                                                },
                                                {
                                                    "from": BUSINESS_NUMBER,
                                                    "to": CUSTOMER_NUMBER,
                                                    "id": "wamid.hist-out",
                                                    "timestamp": "1739300100",
                                                    "type": "text",
                                                    "text": {"body": "Yes, 9 to 5."},
                                                },
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class CoexistenceExtractionTests(unittest.TestCase):
    def test_echo_is_outbound_and_keyed_by_the_customer(self) -> None:
        events = extract_coexistence_events(echo_payload())

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["direction"], "outbound")
        self.assertEqual(event["thread_id"], CUSTOMER_NUMBER)
        self.assertFalse(event["is_history"])
        self.assertEqual(event["message_text"], "Here's the info you requested.")

    def test_history_direction_is_derived_from_the_business_number(self) -> None:
        events = extract_coexistence_events(history_payload())

        self.assertEqual([event["direction"] for event in events], ["inbound", "outbound"])
        self.assertTrue(all(event["is_history"] for event in events))
        self.assertTrue(all(event["thread_id"] == CUSTOMER_NUMBER for event in events))

    def test_epoch_timestamps_become_iso(self) -> None:
        event = extract_coexistence_events(echo_payload())[0]
        self.assertTrue(event["timestamp"].startswith("2025-"), event["timestamp"])

    def test_edits_and_revokes_carry_no_content_and_are_skipped(self) -> None:
        payload = echo_payload()
        message = payload["entry"][0]["changes"][0]["value"]["message_echoes"][0]
        message["type"] = "revoke"
        message.pop("text")

        self.assertEqual(extract_coexistence_events(payload), [])

    def test_customer_inbound_extraction_ignores_coexistence_fields(self) -> None:
        # The owner talking to their own customers must never look like a new
        # customer message waiting on a reply.
        self.assertEqual(extract_inbound_events(echo_payload()), [])
        self.assertEqual(extract_inbound_events(history_payload()), [])


class CoexistenceIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name) / "whatsapp-store.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_service(self) -> PortalWhatsAppService:
        config = build_portal_runtime_config(
            client_id="portal-user-1",
            client_name="Portal User",
            base_url="https://example.com",
            phone_number_id="106540352242922",
            owner_wa_id=BUSINESS_NUMBER,
            data_path=self.data_path,
        )
        config.access_token = "test-token"
        return PortalWhatsAppService(config, BackendStore(self.data_path), delivery_settings={})

    def test_an_echo_is_recorded_but_never_creates_an_approval(self) -> None:
        service = self._build_service()

        result = service.process_webhook_payload(echo_payload())

        self.assertEqual(result["approvals"], [])
        self.assertEqual(result["coexistence_received"], 1)

        thread = service.get_thread(CUSTOMER_NUMBER)
        self.assertIsNotNone(thread)
        self.assertEqual(len(thread["messages"]), 1)
        self.assertEqual(thread["messages"][0]["direction"], "outbound")
        self.assertEqual(thread["messages"][0]["source"], "coexistence")

    def test_a_repeated_message_id_is_stored_once(self) -> None:
        service = self._build_service()

        service.process_webhook_payload(echo_payload())
        service.process_webhook_payload(echo_payload())

        thread = service.get_thread(CUSTOMER_NUMBER)
        self.assertEqual(len(thread["messages"]), 1)

    def test_history_backfill_is_ordered_and_leaves_the_live_message_latest(self) -> None:
        service = self._build_service()

        service.process_webhook_payload(echo_payload(text="Live reply", message_id="wamid.live"))
        service.process_webhook_payload(history_payload())

        thread = service.get_thread(CUSTOMER_NUMBER)
        self.assertEqual(
            [message["message_id"] for message in thread["messages"]],
            ["wamid.hist-in", "wamid.hist-out", "wamid.live"],
        )
        # Backfilled history is older than the live message; it must not become
        # the headline of the thread.
        self.assertEqual(thread["latest_message"], "Live reply")
        self.assertTrue(thread["coexistence_history_imported"])


if __name__ == "__main__":
    unittest.main()
