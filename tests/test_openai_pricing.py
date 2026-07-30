from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path

from packages.infrastructure.openai_pricing import build_pricing_snapshot_json
from packages.infrastructure.openai_pricing import parse_openai_pricing_markdown
from packages.infrastructure.openai_pricing import pick_representative_models
from packages.infrastructure.portal_db import PortalDatabase


SAMPLE_PRICING_MARKDOWN = """
## Flagship models

<AccordionGroup id="latest-models" title="Latest models">
  <div data-value="standard">
    rows=[
      ["gpt-5.5 (<272K context length)", 5, 0.5, "-", 30],
      ["gpt-5.4 (<272K context length)", 2.5, 0.25, "-", 15],
      ["gpt-5.4-mini", 0.75, 0.075, "-", 4.5],
      ["gpt-5.4-nano", 0.2, 0.02, "-", 1.25]
    ]
  </div>
</AccordionGroup>
"""

SAMPLE_TABLE_PRICING_MARKDOWN = """
# Pricing

Flagship models

Prices per 1M tokens.

Standard

### Standard pricing data

| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna | $1.00 | $0.10 | $1.25 | $6.00 | $2.00 | $0.20 | $2.50 | $9.00 |
| gpt-5.5 (<272K context length) | $5.00 | $0.50 | - | $30.00 | $10.00 | $1.00 | - | $45.00 |
| gpt-5.4-mini | $0.75 | $0.075 | - | $4.50 | - | - | - | - |
"""


class OpenAIPricingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_openai_pricing_markdown_extracts_standard_flagship_rows(self) -> None:
        prices = parse_openai_pricing_markdown(SAMPLE_PRICING_MARKDOWN)

        self.assertEqual([price.model_id for price in prices], [
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ])
        self.assertEqual(prices[0].display_name, "gpt-5.5 (<272K context length)")
        self.assertEqual(prices[-1].input_usd_per_1m_tokens, Decimal("0.2"))
        self.assertEqual(prices[-1].output_usd_per_1m_tokens, Decimal("1.25"))

    def test_parse_openai_pricing_markdown_extracts_current_standard_table(self) -> None:
        prices = parse_openai_pricing_markdown(SAMPLE_TABLE_PRICING_MARKDOWN)

        self.assertEqual([price.model_id for price in prices], [
            "gpt-5.6-luna",
            "gpt-5.5",
            "gpt-5.4-mini",
        ])
        self.assertEqual(prices[0].cached_input_usd_per_1m_tokens, Decimal("0.10"))
        self.assertEqual(prices[0].cache_write_usd_per_1m_tokens, Decimal("1.25"))
        self.assertEqual(prices[-1].input_usd_per_1m_tokens, Decimal("0.75"))
        self.assertEqual(prices[-1].output_usd_per_1m_tokens, Decimal("4.50"))

    def test_pick_representative_models_returns_cheap_middle_and_expensive(self) -> None:
        prices = parse_openai_pricing_markdown(SAMPLE_PRICING_MARKDOWN)
        representatives = pick_representative_models(prices)

        self.assertEqual([price.model_id for price in representatives], [
            "gpt-5.4-nano",
            "gpt-5.4",
            "gpt-5.5",
        ])

    def test_build_pricing_snapshot_json_applies_markup_and_syncs_database(self) -> None:
        snapshot = build_pricing_snapshot_json(
            self.database,
            input_multiplier=1.5,
            output_multiplier=1.5,
            markdown_text=SAMPLE_PRICING_MARKDOWN,
            now=datetime(2026, 7, 12, tzinfo=timezone.utc),
        )

        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["source"], "openai")
        self.assertEqual(len(snapshot["cards"]), 3)

        lean_card = snapshot["cards"][0]
        self.assertEqual(lean_card["modelId"], "gpt-5.4-nano")
        self.assertAlmostEqual(lean_card["openai"]["inputUsdPer1MTokens"], 0.2)
        self.assertAlmostEqual(lean_card["ours"]["inputUsdPer1MTokens"], 0.3)
        self.assertAlmostEqual(lean_card["ours"]["outputUsdPer1MTokens"], 1.875)

        synced_row = self.database.get_model_price("gpt-5.5")
        self.assertIsNotNone(synced_row)
        self.assertEqual(synced_row["provider"], "openai")
        self.assertAlmostEqual(synced_row["input_price_cents_per_1k_tokens"], 0.5)
        self.assertAlmostEqual(synced_row["output_price_cents_per_1k_tokens"], 3.0)


if __name__ == "__main__":
    unittest.main()
