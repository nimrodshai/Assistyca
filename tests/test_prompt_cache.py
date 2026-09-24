"""What the cache costs and what it saves, where we can see it.

Most of an agent turn is the same on every message: the instructions and the
tool definitions do not change between one WhatsApp reply and the next.
OpenAI serves a repeated prefix from its cache, which is the difference
between paying for that prompt once a conversation and paying for it every
round. Two things make it real rather than hopeful - a key, so an account's
turns land on the same cache, and the cached count coming back, so a change
to the prompt can be shown to have helped instead of assumed to.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.openai_api import OpenAIConfig
from packages.infrastructure.openai_api import OpenAIGateway
from packages.infrastructure.openai_api import OpenAIRequest
from packages.infrastructure.openai_api import extract_openai_usage
from packages.infrastructure.openai_api import prompt_cache_key_for

MODULE = "packages.infrastructure.openai_api"


def _response_body(usage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "model": "test-model",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Answered."}]}],
        "usage": usage or {"input_tokens": 10, "output_tokens": 5},
    }


def _gateway() -> OpenAIGateway:
    return OpenAIGateway(config=OpenAIConfig(api_key="test-key", default_model="test-model"))


class PromptCacheKeyTests(unittest.TestCase):
    def test_the_same_account_always_names_the_same_cache(self) -> None:
        self.assertEqual(prompt_cache_key_for("owner@example.com"), prompt_cache_key_for("Owner@Example.com "))
        self.assertNotEqual(prompt_cache_key_for("owner@example.com"), prompt_cache_key_for("other@example.com"))

    def test_the_key_says_nothing_about_who_the_person_is(self) -> None:
        key = prompt_cache_key_for("owner@example.com")

        self.assertNotIn("owner", key)
        self.assertNotIn("example.com", key)

    def test_no_account_asks_for_no_cache(self) -> None:
        self.assertEqual(prompt_cache_key_for(""), "")

    def test_the_key_goes_out_with_the_request(self) -> None:
        with mock.patch(f"{MODULE}._json_request", return_value=(_response_body(), 200)) as call:
            _gateway().create_response(
                OpenAIRequest(tool_name="portal_agent", prompt="hello", prompt_cache_key="acct-abc")
            )

        self.assertEqual(call.call_args.args[1]["prompt_cache_key"], "acct-abc")

    def test_a_request_without_one_sends_no_key_at_all(self) -> None:
        with mock.patch(f"{MODULE}._json_request", return_value=(_response_body(), 200)) as call:
            _gateway().create_response(OpenAIRequest(tool_name="portal_agent", prompt="hello"))

        self.assertNotIn("prompt_cache_key", call.call_args.args[1])


class CachedTokenTests(unittest.TestCase):
    def test_what_came_from_the_cache_is_counted(self) -> None:
        usage = extract_openai_usage(
            {"usage": {"input_tokens": 15000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 12800}}}
        )

        self.assertEqual(usage["input_tokens"], 15000)
        self.assertEqual(usage["cached_input_tokens"], 12800)

    def test_a_cold_prompt_reads_as_nothing_cached_rather_than_as_missing(self) -> None:
        usage = extract_openai_usage({"usage": {"input_tokens": 15000, "output_tokens": 300}})

        self.assertEqual(usage["cached_input_tokens"], 0)

    def test_the_count_reaches_the_caller(self) -> None:
        body = _response_body({"input_tokens": 15000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 12800}})
        with mock.patch(f"{MODULE}._json_request", return_value=(body, 200)):
            result = _gateway().create_response(OpenAIRequest(tool_name="portal_agent", prompt="hello"))

        self.assertEqual(result.cached_input_tokens, 12800)


if __name__ == "__main__":
    unittest.main()
