from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.tool_model_selection import list_tool_model_options


class PortalDatabaseModelPriceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "portal.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_database_seeds_default_model_prices(self) -> None:
        database = PortalDatabase(self.db_path)

        gpt_55 = database.get_model_price("gpt-5.5")
        gpt_54 = database.get_model_price("gpt-5.4")
        gpt_54_mini = database.get_model_price("gpt-5.4-mini")

        self.assertIsNotNone(gpt_55)
        self.assertEqual(gpt_55["currency"], "USD")
        self.assertAlmostEqual(gpt_55["input_price_cents_per_1k_tokens"], 0.5)
        self.assertAlmostEqual(gpt_55["output_price_cents_per_1k_tokens"], 3.0)
        self.assertEqual(gpt_55["provider"], "openai")

        self.assertIsNotNone(gpt_54)
        self.assertAlmostEqual(gpt_54["input_price_cents_per_1k_tokens"], 0.25)
        self.assertAlmostEqual(gpt_54["output_price_cents_per_1k_tokens"], 1.5)

        self.assertIsNotNone(gpt_54_mini)
        self.assertAlmostEqual(gpt_54_mini["input_price_cents_per_1k_tokens"], 0.075)
        self.assertAlmostEqual(gpt_54_mini["output_price_cents_per_1k_tokens"], 0.45)

    def test_shared_tool_model_options_include_gpt_54_mini(self) -> None:
        options = list_tool_model_options()

        self.assertIn(
            {
                "id": "gpt-5.4-mini",
                "name": "GPT-5.4 Mini",
                "band": "Efficient",
                "summary": "A lower-cost step up from nano for strong everyday replies and drafting.",
            },
            options,
        )

    def test_database_backfills_missing_defaults_without_overwriting_existing_prices(self) -> None:
        database = PortalDatabase(self.db_path)
        database.upsert_model_price(
            "gpt-5.5",
            input_price_cents_per_1k_tokens=9.9,
            output_price_cents_per_1k_tokens=8.8,
            provider="custom",
            notes="custom override",
        )

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM model_prices WHERE model_name = ?", ("gpt-5.4",))
            conn.commit()

        reopened = PortalDatabase(self.db_path)
        gpt_55 = reopened.get_model_price("gpt-5.5")
        gpt_54 = reopened.get_model_price("gpt-5.4")

        self.assertIsNotNone(gpt_55)
        self.assertAlmostEqual(gpt_55["input_price_cents_per_1k_tokens"], 9.9)
        self.assertAlmostEqual(gpt_55["output_price_cents_per_1k_tokens"], 8.8)
        self.assertEqual(gpt_55["provider"], "custom")

        self.assertIsNotNone(gpt_54)
        self.assertAlmostEqual(gpt_54["input_price_cents_per_1k_tokens"], 0.25)
        self.assertAlmostEqual(gpt_54["output_price_cents_per_1k_tokens"], 1.5)

    def test_whatsapp_conversation_summary_includes_message_count(self) -> None:
        database = PortalDatabase(self.db_path)
        database.register_user("owner@example.com")

        database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="15551230000",
            direction="inbound",
            text="Hi, are you available today?",
            sender_name="Maya Cohen",
            sender_wa_id="15551230000",
            message_id="wamid.1",
            message_at="2026-07-24T08:00:00+00:00",
        )
        database.save_whatsapp_message(
            email="owner@example.com",
            conversation_id="15551230000",
            direction="outbound",
            text="Yes, I can help this afternoon.",
            sender_name="Maya Cohen",
            sender_wa_id="15551230000",
            message_id="wamid.2",
            message_at="2026-07-24T08:03:00+00:00",
        )

        conversations = database.list_whatsapp_conversations(email="owner@example.com")
        messages = database.list_whatsapp_conversation_messages(
            "15551230000",
            email="owner@example.com",
        )

        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["messageCount"], 2)
        self.assertEqual(len(messages), 2)

    def test_whatsapp_connection_preserves_access_token_when_omitted(self) -> None:
        database = PortalDatabase(self.db_path)
        database.register_user("owner@example.com")

        first = database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="waba-1",
            phone_number_id="phone-1",
            access_token="secret-token",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        second = database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="waba-1",
            phone_number_id="phone-2",
            owner_wa_id="15551234567",
            connection_status="connected",
        )

        self.assertTrue(first["accessTokenConfigured"])
        self.assertEqual(second["accessToken"], "secret-token")
        self.assertTrue(second["accessTokenConfigured"])


if __name__ == "__main__":
    unittest.main()
