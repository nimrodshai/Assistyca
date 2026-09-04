"""A reply the model did not finish.

A reasoning model thinks inside its output budget. When the thinking uses all
of it the API answers with no text and a status of incomplete, and a gateway
that does not read the status hands an empty string on to a caller that then
fails to parse it and blames the model. The gateway reads the status.
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
from packages.infrastructure.openai_api import OpenAIIncompleteError
from packages.infrastructure.openai_api import OpenAIRequest

MODULE = "packages.infrastructure.openai_api"


def _incomplete_body(text: str = "") -> dict[str, Any]:
    output: list[dict[str, Any]] = [{"type": "reasoning", "summary": []}]
    if text:
        output.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return {
        "id": "resp_cut",
        "model": "test-model",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": output,
        "usage": {"input_tokens": 10, "output_tokens": 250},
    }


def _complete_body() -> dict[str, Any]:
    return {
        "id": "resp_ok",
        "model": "test-model",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"reply":"Answered."}'}]}],
        "usage": {"input_tokens": 10, "output_tokens": 40},
    }


def _gateway() -> OpenAIGateway:
    return OpenAIGateway(config=OpenAIConfig(api_key="test-key", default_model="test-model"))


class IncompleteReplyTests(unittest.TestCase):
    def test_a_cut_off_reply_is_retried_once_with_double_the_budget(self) -> None:
        with mock.patch(f"{MODULE}._json_request", side_effect=[(_incomplete_body(), 200), (_complete_body(), 200)]) as sent:
            result = _gateway().create_response(OpenAIRequest(tool_name="t", prompt="p", max_output_tokens=250))

        self.assertEqual(result.output_text, '{"reply":"Answered."}')
        budgets = [call.args[1].get("max_output_tokens") for call in sent.call_args_list]
        self.assertEqual(budgets, [250, 500])

    def test_still_empty_after_the_retry_is_an_error_not_an_empty_string(self) -> None:
        with mock.patch(f"{MODULE}._json_request", side_effect=[(_incomplete_body(), 200), (_incomplete_body(), 200)]):
            with self.assertRaises(OpenAIIncompleteError):
                _gateway().create_response(OpenAIRequest(tool_name="t", prompt="p", max_output_tokens=250))

    def test_partial_text_after_the_retry_is_kept(self) -> None:
        # A plain-text caller can use half a summary; only nothing is useless.
        with mock.patch(f"{MODULE}._json_request", side_effect=[(_incomplete_body(), 200), (_incomplete_body("Half a"), 200)]):
            result = _gateway().create_response(OpenAIRequest(tool_name="t", prompt="p", max_output_tokens=250))

        self.assertEqual(result.output_text, "Half a")

    def test_no_budget_means_no_retry(self) -> None:
        # Without a cap of ours to raise there is nothing to change on a second try.
        with mock.patch(f"{MODULE}._json_request", side_effect=[(_incomplete_body(), 200)]) as sent:
            with self.assertRaises(OpenAIIncompleteError):
                _gateway().create_response(OpenAIRequest(tool_name="t", prompt="p"))
        self.assertEqual(sent.call_count, 1)

    def test_a_complete_reply_is_not_touched(self) -> None:
        with mock.patch(f"{MODULE}._json_request", side_effect=[(_complete_body(), 200)]) as sent:
            result = _gateway().create_response(OpenAIRequest(tool_name="t", prompt="p", max_output_tokens=250))
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(result.output_text, '{"reply":"Answered."}')


if __name__ == "__main__":
    unittest.main()
