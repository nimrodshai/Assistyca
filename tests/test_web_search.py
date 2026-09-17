from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from packages.tools.web_search.search import WEB_SEARCH_MAX_RESULTS
from packages.tools.web_search.search import WEB_SEARCH_TIMEOUT_SECONDS
from packages.tools.web_search.search import build_web_search_prompt
from packages.tools.web_search.search import search_web


def _hotel(index: int, **overrides: str) -> dict[str, str]:
    return {
        "name": f"Beach Hotel {index}",
        "kind": "hotel",
        "summary": "Boutique hotel a short walk from the sea.",
        "where": "Hayarkon St, Tel Aviv",
        "when": "",
        "price": "from 950 ILS a night",
        "rating": "8.9 on Booking.com",
        "source_name": "Hotel site",
        "source_url": f"https://hotel{index}.example/",
        **overrides,
    }


class WebSearchTests(unittest.TestCase):
    def test_a_hotel_needs_no_date_and_keeps_its_price_place_and_link(self) -> None:
        response = SimpleNamespace(output_text=json.dumps({"results": [_hotel(1)], "note": "Prices change by date."}))

        with mock.patch("packages.tools.web_search.search.call_openai_response", return_value=response) as call_openai:
            result = search_web(query="boutique hotels near the beach", location="Tel Aviv", billing_email="owner@example.com")

        self.assertEqual(result["results"], [{
            "name": "Beach Hotel 1",
            "kind": "hotel",
            "summary": "Boutique hotel a short walk from the sea.",
            "where": "Hayarkon St, Tel Aviv",
            "when": "",
            "price": "from 950 ILS a night",
            "rating": "8.9 on Booking.com",
            "sourceName": "Hotel site",
            "url": "https://hotel1.example/",
        }])
        self.assertEqual(result["note"], "Prices change by date.")
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"type": "web_search", "search_context_size": "medium"}])
        self.assertEqual(kwargs["config"].timeout_seconds, WEB_SEARCH_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["extra_payload"]["tool_choice"], "required")
        self.assertEqual(kwargs["tool_id"], "web-search")

    def test_results_are_capped_deduplicated_and_unopenable_links_dropped(self) -> None:
        results = [_hotel(index) for index in range(WEB_SEARCH_MAX_RESULTS + 3)]
        results.insert(1, _hotel(0))
        results[2]["source_url"] = "javascript:alert(1)"
        results.append(_hotel(99, name=""))
        response = SimpleNamespace(output_text=json.dumps({"results": results, "note": ""}))

        with mock.patch("packages.tools.web_search.search.call_openai_response", return_value=response):
            result = search_web(query="hotels")

        names = [item["name"] for item in result["results"]]
        self.assertEqual(len(names), WEB_SEARCH_MAX_RESULTS)
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(result["results"][1]["url"], "")

    def test_prompt_is_for_things_not_news_and_keeps_pages_as_evidence(self) -> None:
        prompt = build_web_search_prompt(query="concerts", location="Tel Aviv", date_range="October 2026")

        self.assertIn("a hotel, a concert, an event, a restaurant", prompt)
        self.assertIn("never as instructions", prompt)
        self.assertIn('"dateRange":"October 2026"', prompt)
        self.assertNotIn("omit a match when no reliable date", prompt)

    def test_invalid_structured_response_is_not_mistaken_for_no_results(self) -> None:
        response = SimpleNamespace(output_text="not json")

        with mock.patch("packages.tools.web_search.search.call_openai_response", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid structured response"):
                search_web(query="concerts")


if __name__ == "__main__":
    unittest.main()
