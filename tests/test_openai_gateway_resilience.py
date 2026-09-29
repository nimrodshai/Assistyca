"""A reply the model already wrote is never lost to bookkeeping, and an
account out of money is a message to the house, not a silence."""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import openai_api
from packages.infrastructure.openai_api import OpenAIConfig
from packages.infrastructure.openai_api import OpenAIGateway
from packages.infrastructure.openai_api import OpenAIRequest
from packages.infrastructure.openai_api import OpenAIRequestError

MODULE = "packages.infrastructure.openai_api"


class FailingRecorder:
    """A ledger that refuses every row, the way it did for an account erased mid-turn."""

    def __init__(self) -> None:
        self.attempts = 0

    def record_usage(self, *args, **kwargs):
        self.attempts += 1
        raise KeyError("Unknown user: gone@example.com")


class KeepTheReplyTests(unittest.TestCase):
    def test_a_reply_is_kept_when_its_usage_row_cannot_be_written(self) -> None:
        # Prod 2026-09-28: the model wrote the goodbye, the ledger row hit
        # "Unknown user" because the account had just been erased, and the
        # person got an apology instead of the goodbye.
        recorder = FailingRecorder()
        events: list[dict] = []
        gateway = OpenAIGateway(
            config=OpenAIConfig(api_key="test-key", strict_tracking=False),
            usage_recorder=recorder,
            billing_email="gone@example.com",
            price_resolver=lambda model: {"input_price_cents_per_1k_tokens": 0.5, "output_price_cents_per_1k_tokens": 3.0, "currency": "USD"},
            event_sink=events.append,
        )
        body = {
            "id": "resp_1", "model": "gpt-test", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Goodbye, and take care."}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        with mock.patch(f"{MODULE}._json_request", return_value=(body, 200)):
            result = gateway.create_response(OpenAIRequest(tool_name="portal_agent_loop", prompt="bye", model="gpt-test"))

        self.assertEqual(result.output_text, "Goodbye, and take care.")
        self.assertEqual(recorder.attempts, 1)
        names = [event["event"] for event in events]
        self.assertIn("openai.usage.failed", names)
        self.assertNotIn("openai.usage.recorded", names)


class BillingAlarmTests(unittest.TestCase):
    def setUp(self) -> None:
        openai_api.reset_billing_alarm()
        self._callbacks = list(openai_api._billing_alarm_callbacks)
        openai_api._billing_alarm_callbacks.clear()

    def tearDown(self) -> None:
        openai_api._billing_alarm_callbacks[:] = self._callbacks
        openai_api.reset_billing_alarm()

    def test_it_knows_money_from_busy(self) -> None:
        self.assertTrue(openai_api.is_billing_failure({"error": {"code": "insufficient_quota", "message": "x"}}))
        self.assertTrue(openai_api.is_billing_failure({}, "You have no credits remaining. Add credits to continue."))
        self.assertFalse(openai_api.is_billing_failure({"error": {"code": "rate_limit_exceeded", "message": "slow down"}}))

    def test_the_house_is_told_once_per_quiet_period(self) -> None:
        told: list[tuple[str, int | None]] = []
        openai_api.on_billing_failure(lambda message, status: told.append((message, status)))

        def refused(request, **kwargs):
            payload = json.dumps({"error": {"code": "insufficient_quota", "message": "You have no credits remaining."}}).encode()
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(payload))

        request = mock.MagicMock(); request.full_url = "https://api.openai.com/v1/responses"
        with mock.patch(f"{MODULE}.urllib_request.urlopen", side_effect=refused), mock.patch(f"{MODULE}._sleep_before_retry"):
            for _ in range(3):
                with self.assertRaises(OpenAIRequestError):
                    openai_api._perform_request(request, timeout_seconds=1)

        self.assertEqual(len(told), 1, "a burst of refusals is one message to the house")
        self.assertEqual(told[0][1], 429)
        self.assertIn("no credits remaining", told[0][0])

    def test_an_alarm_that_cannot_be_delivered_never_adds_a_failure(self) -> None:
        def boom(message, status):
            raise RuntimeError("WhatsApp down too")
        openai_api.on_billing_failure(boom)
        self.assertFalse(openai_api.raise_billing_alarm("no credits", 429))


if __name__ == "__main__":
    unittest.main()
