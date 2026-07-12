from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.portal_db import PortalDatabase


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

        self.assertIsNotNone(gpt_55)
        self.assertEqual(gpt_55["currency"], "USD")
        self.assertAlmostEqual(gpt_55["input_price_cents_per_1k_tokens"], 0.5)
        self.assertAlmostEqual(gpt_55["output_price_cents_per_1k_tokens"], 3.0)
        self.assertEqual(gpt_55["provider"], "openai")

        self.assertIsNotNone(gpt_54)
        self.assertAlmostEqual(gpt_54["input_price_cents_per_1k_tokens"], 0.25)
        self.assertAlmostEqual(gpt_54["output_price_cents_per_1k_tokens"], 1.5)

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
