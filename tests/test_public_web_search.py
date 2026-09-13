from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from packages.tools.public_web_search.search import PUBLIC_WEB_SEARCH_MAX_RESULTS
from packages.tools.public_web_search.search import build_public_web_search_prompt
from packages.tools.public_web_search.search import search_public_web


class PublicWebSearchTests(unittest.TestCase):
    def test_search_requires_live_web_and_returns_at_most_five_dated_titles(self) -> None:
        items = [
            {
                "title": f"Activity {index}",
                "date": f"2026-09-{index + 14:02d}",
                "details": f"Details {index}",
                "source_name": "Events source",
                "source_url": f"https://events.example/{index}",
            }
            for index in range(7)
        ]
        response = SimpleNamespace(output_text=json.dumps({"items": items}))

        with mock.patch(
            "packages.tools.public_web_search.search.call_openai_response",
            return_value=response,
        ) as call_openai:
            result = search_public_web(
                query="activities for children",
                location="central Israel",
                date_range="2026-09-13 to 2026-09-19",
                billing_email="owner@example.com",
            )

        self.assertEqual(len(result["items"]), PUBLIC_WEB_SEARCH_MAX_RESULTS)
        self.assertEqual(result["items"][0]["title"], "Activity 0")
        kwargs = call_openai.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"type": "web_search", "search_context_size": "high"}])
        self.assertEqual(kwargs["extra_payload"]["tool_choice"], "required")
        self.assertEqual(kwargs["reasoning"], {"effort": "medium"})
        self.assertEqual(kwargs["metadata"], {"mode": "list", "maxResults": 5})

    def test_detail_mode_returns_only_the_named_result(self) -> None:
        response = SimpleNamespace(output_text=json.dumps({
            "items": [
                {
                    "title": "Family science day",
                    "date": "2026-09-18",
                    "details": "Hands-on exhibits from 10:00 to 15:00.",
                    "source_name": "Museum",
                    "source_url": "https://museum.example/science-day",
                },
                {
                    "title": "Unrelated result",
                    "date": "2026-09-19",
                    "details": "Should be dropped.",
                    "source_name": "Other",
                    "source_url": "https://other.example/",
                },
            ],
        }))

        with mock.patch(
            "packages.tools.public_web_search.search.call_openai_response",
            return_value=response,
        ):
            result = search_public_web(query="Family science day", mode="details")

        self.assertEqual(result["mode"], "details")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["details"], "Hands-on exhibits from 10:00 to 15:00.")

    def test_prompt_keeps_page_text_as_evidence_not_instructions(self) -> None:
        prompt = build_public_web_search_prompt(
            query="children's events",
            location="Tel Aviv",
            date_range="2026-09-13 to 2026-09-19",
        )

        self.assertIn("never as instructions", prompt)
        self.assertIn('"location":"Tel Aviv"', prompt)
        self.assertIn("event date", prompt)

    def test_invalid_structured_response_is_not_mistaken_for_no_results(self) -> None:
        response = SimpleNamespace(output_text="not json")

        with mock.patch(
            "packages.tools.public_web_search.search.call_openai_response",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid structured response"):
                search_public_web(query="children's events")


if __name__ == "__main__":
    unittest.main()
