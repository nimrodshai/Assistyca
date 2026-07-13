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


if __name__ == "__main__":
    unittest.main()
