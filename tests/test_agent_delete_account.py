from __future__ import annotations

import unittest

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import _tool_delete_account
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


if __name__ == "__main__":
    unittest.main()
