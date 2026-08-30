"""Temperature, and what happens when a model will not take one.

Wording that varies is what keeps a chat from reading like a form, so the
conversational calls ask for it. Which models accept temperature changes with
every release, and a refusal is about the knob rather than the request, so it
must never be what a client sees.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import openai_api
from packages.infrastructure.openai_api import OpenAIConfig
from packages.infrastructure.openai_api import OpenAIGateway
from packages.infrastructure.openai_api import OpenAIRequest
from packages.infrastructure.openai_api import OpenAIRequestError
from packages.infrastructure.openai_api import is_unsupported_sampling_error
from packages.infrastructure.openai_api import strip_sampling_controls

MODULE = "packages.infrastructure.openai_api"


def _response_body() -> dict[str, Any]:
    return {
        "id": "resp_1",
        "model": "test-model",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Answered."}]}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _gateway() -> OpenAIGateway:
    return OpenAIGateway(config=OpenAIConfig(api_key="test-key", default_model="test-model"))


def _request(**kwargs: Any) -> OpenAIRequest:
    return OpenAIRequest(tool_name="portal_agent", prompt="hello", **kwargs)


class SamplingControlDetectionTests(unittest.TestCase):
    def test_a_refusal_about_temperature_is_recognised(self) -> None:
        error = OpenAIRequestError(
            "Unsupported parameter: 'temperature' is not supported with this model.",
            status_code=400,
        )

        self.assertTrue(is_unsupported_sampling_error(error))

    def test_a_refusal_about_anything_else_is_left_alone(self) -> None:
        # Retrying a genuinely bad request without temperature would just fail
        # again, one round trip later.
        error = OpenAIRequestError("Invalid value for 'model'.", status_code=400)

        self.assertFalse(is_unsupported_sampling_error(error))

    def test_a_server_error_is_not_read_as_a_refusal(self) -> None:
        error = OpenAIRequestError("temperature service unavailable", status_code=503)

        self.assertFalse(is_unsupported_sampling_error(error))

    def test_stripping_reports_whether_there_was_anything_to_strip(self) -> None:
        payload = {"model": "m", "temperature": 0.9, "top_p": 1}

        self.assertTrue(strip_sampling_controls(payload))
        self.assertEqual(payload, {"model": "m"})
        self.assertFalse(strip_sampling_controls(payload))


class SamplingControlRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        openai_api._MODELS_REFUSING_SAMPLING_CONTROLS.clear()
        self.addCleanup(openai_api._MODELS_REFUSING_SAMPLING_CONTROLS.clear)

    def test_a_temperature_reaches_the_model_that_takes_one(self) -> None:
        with mock.patch(f"{MODULE}._json_request", return_value=(_response_body(), 200)) as call:
            _gateway().create_response(_request(temperature=0.9))

        self.assertEqual(call.call_args.args[1]["temperature"], 0.9)

    def test_a_model_that_refuses_still_answers(self) -> None:
        # The request itself was fine. Losing the reply over the knob would
        # turn a working answer into an error the client can do nothing about.
        refusal = OpenAIRequestError(
            "Unsupported parameter: 'temperature' is not supported with this model.",
            status_code=400,
        )
        with mock.patch(
            f"{MODULE}._json_request",
            side_effect=[refusal, (_response_body(), 200)],
        ) as call:
            result = _gateway().create_response(_request(temperature=0.9))

        self.assertEqual(result.output_text, "Answered.")
        self.assertEqual(call.call_count, 2)
        self.assertNotIn("temperature", call.call_args.args[1])

    def test_a_model_that_refused_once_is_not_asked_again(self) -> None:
        refusal = OpenAIRequestError("Unsupported parameter: 'temperature'.", status_code=400)
        with mock.patch(f"{MODULE}._json_request", side_effect=[refusal, (_response_body(), 200)]):
            _gateway().create_response(_request(temperature=0.9))

        with mock.patch(f"{MODULE}._json_request", return_value=(_response_body(), 200)) as call:
            _gateway().create_response(_request(temperature=0.9))

        self.assertEqual(call.call_count, 1)
        self.assertNotIn("temperature", call.call_args.args[1])

    def test_a_real_failure_is_still_a_failure(self) -> None:
        with mock.patch(
            f"{MODULE}._json_request",
            side_effect=OpenAIRequestError("Invalid request.", status_code=400),
        ) as call:
            with self.assertRaises(OpenAIRequestError):
                _gateway().create_response(_request(temperature=0.9))

        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
