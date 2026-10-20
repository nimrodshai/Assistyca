from __future__ import annotations

import unittest

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import _tool_delete_account
from packages.infrastructure.agent_loop import describe_delete_account
from tests.test_agent_news_search import _Database


class DeleteAccountToolTests(unittest.TestCase):
    def _run(self, response: dict) -> dict:
        context = LoopContext(
            api=lambda *args, **kwargs: (response, 200),
            database=_Database(),
            email="owner@example.com",
            user_id=1,
            timezone_name="Asia/Jerusalem",
            channel="whatsapp",
        )
        return _tool_delete_account(context, {})

    def test_an_ordinary_account_is_reported_gone(self) -> None:
        result = self._run({"ok": True, "registeredAgain": False})
        self.assertIn("are gone", result["note"])

    def test_a_house_address_is_reported_as_emptied_not_gone(self) -> None:
        # The server registers a seeded address again at once, so telling the
        # person the account is gone is contradicted by their next sign-in.
        result = self._run({"ok": True, "registeredAgain": True})
        self.assertIn("an empty account under it stays", result["note"])
        self.assertNotIn("are gone", result["note"])

    def test_a_subscription_that_could_not_be_cancelled_is_said_and_nothing_is_gone(self) -> None:
        context = LoopContext(
            api=lambda *args, **kwargs: ({"ok": False, "error": "billing_not_cancelled"}, 503),
            database=_Database(), email="owner@example.com", user_id=1, timezone_name="Asia/Jerusalem",
        )
        result = _tool_delete_account(context, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "billing_not_cancelled")
        self.assertIn("nothing was deleted", result["error"]["whatHappened"])

    def test_a_payment_already_stopped_is_said_and_never_called_unchanged(self) -> None:
        context = LoopContext(
            api=lambda *args, **kwargs: (
                {"ok": False, "error": "billing_not_cancelled", "subscriptionsCancelled": 1, "subscriptionsNotCancelled": 1}, 503,
            ),
            database=_Database(), email="owner@example.com", user_id=1, timezone_name="Asia/Jerusalem",
        )
        result = _tool_delete_account(context, {})
        self.assertEqual(result["error"]["code"], "billing_not_cancelled")
        self.assertEqual((result["error"]["paymentsStopped"], result["error"]["paymentsStillCharging"]), (1, 1))
        self.assertNotIn("exactly as it was", result["error"]["whatHappened"])
        self.assertIn("already stopped", result["error"]["whatHappened"])

    def test_the_question_says_the_subscription_ends_with_the_account(self) -> None:
        context = LoopContext(
            api=None, database=_Database(), email="owner@example.com", user_id=1, timezone_name="Asia/Jerusalem",
            billing={"onTrial": False, "paying": True},
        )
        self.assertIn("will not be charged again", describe_delete_account(context))


if __name__ == "__main__":
    unittest.main()
