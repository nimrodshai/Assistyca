"""Paying to keep the assistant once the trial is over.

A family account has no email, so a payment is matched to the account by the
id its checkout carried, never by the address typed at checkout. These tests
pin that, the signed payment link, and what counts as paying.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS
from packages.infrastructure.agent_loop import TRIAL_ENDED_TOOLS
from packages.infrastructure.agent_loop import build_loop_context_text
from packages.infrastructure.family_billing import pay_code
from packages.infrastructure.family_billing import subscription_is_paying
from packages.infrastructure.family_billing import subscription_record_from_event
from packages.infrastructure.family_billing import user_id_from_pay_code
from packages.infrastructure.lemon_squeezy_api import build_webhook_signature
from packages.infrastructure.lemon_squeezy_api import parse_webhook_event
from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.trial_access import build_trial_expired_message
from packages.infrastructure.trial_access import describe_trial


SECRET = b"family-billing-test-secret-0123456789"
SIGNING_SECRET = "lemon-signing-secret"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def subscription_event(event_name: str, *, user_id: str = "7", status: str = "active", ends_at: str = "") -> dict:
    return {
        "meta": {"event_name": event_name, "custom_data": {"user_id": user_id} if user_id else {}},
        "data": {
            "type": "subscriptions",
            "id": "sub-1",
            "attributes": {
                "customer_id": 55,
                "status": status,
                "status_formatted": status.title(),
                "product_id": 9,
                "variant_id": 10,
                "renews_at": "2026-11-18T12:00:00Z",
                "ends_at": ends_at or None,
                "test_mode": True,
                "first_subscription_item": {"id": 77},
                "urls": {"customer_portal": "https://assistyca.lemonsqueezy.com/billing?x=1"},
            },
        },
    }


class PayCodeTests(unittest.TestCase):
    def test_a_code_names_its_account_and_nothing_else(self) -> None:
        code = pay_code(42, SECRET)
        self.assertEqual(user_id_from_pay_code(code, SECRET), 42)
        self.assertLessEqual(len(code), 16)

    def test_a_code_the_server_did_not_sign_opens_nothing(self) -> None:
        code = pay_code(42, SECRET)
        # Another account's id with this account's signature.
        forged = pay_code(43, SECRET)[:-10] + code[-10:]
        self.assertEqual(user_id_from_pay_code(forged, SECRET), 0)
        self.assertEqual(user_id_from_pay_code(code, b"another-secret-entirely-000000000"), 0)
        self.assertEqual(user_id_from_pay_code("", SECRET), 0)
        self.assertEqual(user_id_from_pay_code("not-a-code!", SECRET), 0)


class PayingTests(unittest.TestCase):
    def test_a_running_subscription_pays(self) -> None:
        for status in ("active", "on_trial", "past_due"):
            with self.subTest(status=status):
                self.assertTrue(subscription_is_paying({"subscriptionStatus": status}, now=NOW))

    def test_a_cancelled_subscription_pays_until_the_month_is_over(self) -> None:
        later = {"subscriptionStatus": "cancelled", "metadata": {"endsAt": "2026-10-30T00:00:00Z"}}
        over = {"subscriptionStatus": "cancelled", "metadata": {"endsAt": "2026-10-01T00:00:00Z"}}
        self.assertTrue(subscription_is_paying(later, now=NOW))
        self.assertFalse(subscription_is_paying(over, now=NOW))

    def test_nothing_or_an_expired_subscription_does_not_pay(self) -> None:
        for record in (None, {}, {"subscriptionStatus": "expired"}, {"subscriptionStatus": "unpaid"}):
            with self.subTest(record=record):
                self.assertFalse(subscription_is_paying(record, now=NOW))


class EventTests(unittest.TestCase):
    def _event(self, payload: dict):
        return parse_webhook_event(json.dumps(payload))

    def test_a_subscription_event_names_the_account_its_checkout_carried(self) -> None:
        record = subscription_record_from_event(self._event(subscription_event("subscription_created")))
        self.assertEqual(record["userId"], 7)
        self.assertEqual(record["subscriptionStatus"], "active")
        self.assertEqual(record["externalSubscriptionId"], "sub-1")
        self.assertEqual(record["customerPortalUrl"], "https://assistyca.lemonsqueezy.com/billing?x=1")

    def test_an_event_without_an_account_or_about_an_order_is_ignored(self) -> None:
        self.assertIsNone(subscription_record_from_event(self._event(subscription_event("subscription_created", user_id=""))))
        order = subscription_event("order_created")
        order["data"]["type"] = "orders"
        self.assertIsNone(subscription_record_from_event(self._event(order)))


class WordsTests(unittest.TestCase):
    def test_the_floor_for_a_finished_trial_carries_the_link_when_there_is_one(self) -> None:
        words = build_trial_expired_message(pay_link="https://assistyca.com/pay/abc", price_label="$4.90 a month")
        self.assertIn("https://assistyca.com/pay/abc", words)
        self.assertIn("$4.90 a month", words)
        self.assertNotIn("Settings", words)
        self.assertNotIn("Settings", build_trial_expired_message())

    def test_a_finished_trial_offers_the_way_to_pay_as_well_as_the_way_out(self) -> None:
        self.assertEqual(TRIAL_ENDED_TOOLS, {"delete_account", "sign_out", "disconnect", "payment_link"})

    def test_the_price_is_answered_when_asked_and_said_once_near_the_end(self) -> None:
        text = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="UTC", today="2026-10-18",
            tool_context={}, facts=[], channel="whatsapp",
            billing={"onTrial": True, "daysLeft": 2, "price": "$4.90 a month", "paying": False},
        )
        self.assertIn("CONTEXT.billing says this account is on its free trial", text)
        self.assertIn('"daysLeft":2', text)
        quiet = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="UTC", today="2026-10-18",
            tool_context={}, facts=[], channel="whatsapp",
        )
        self.assertNotIn("free trial", quiet)
        self.assertIn("payment_link", AGENT_LOOP_INSTRUCTIONS + text)


BILLING_ENV = {
    "LEMON_SQUEEZY_API_KEY": "test-key",
    "LEMON_SQUEEZY_STORE_ID": "1",
    "LEMON_SQUEEZY_VARIANT_ID": "2",
    "LEMON_SQUEEZY_SIGNING_SECRET": SIGNING_SECRET,
    "LEMON_SQUEEZY_TEST_MODE": "true",
    "ASSISTYCA_PRICE_LABEL": "$4.90 a month",
}


class _NoRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


class BillingServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = mock.patch.dict(os.environ, BILLING_ENV)
        self.env.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server(
            "127.0.0.1", 0, Path(__file__).resolve().parents[1],
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="billing-test-secret-0123456789abcdef"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("family@example.com")
        self.user = self.database.get_user("family@example.com") or {}
        self.opener = urllib_request.build_opener(_NoRedirect)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()
        self.env.stop()

    def _get(self, path: str) -> tuple[int, str]:
        try:
            with self.opener.open(f"{self.base_url}{path}", timeout=15) as response:
                return int(response.status), response.headers.get("Location") or ""
        except urllib_error.HTTPError as exc:
            return int(exc.code), exc.headers.get("Location") or ""

    def _webhook(self, payload: dict, *, signature: str | None = None) -> int:
        body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            f"{self.base_url}/webhooks/lemon-squeezy", data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Signature": build_webhook_signature(body, SIGNING_SECRET) if signature is None else signature,
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=15) as response:
                return int(response.status)
        except urllib_error.HTTPError as exc:
            return int(exc.code)

    def _code(self) -> str:
        return pay_code(int(self.user["id"]), self.server.store.session_secret)

    def test_the_pay_link_opens_a_checkout_made_for_this_account(self) -> None:
        with mock.patch(
            "packages.infrastructure.lemon_squeezy_api.LemonSqueezyClient.create_checkout",
            return_value={"url": "https://assistyca.lemonsqueezy.com/checkout/custom/abc"},
        ) as checkout:
            status, location = self._get(f"/pay/{self._code()}")
        self.assertEqual(status, 302)
        self.assertEqual(location, "https://assistyca.lemonsqueezy.com/checkout/custom/abc")
        kwargs = checkout.call_args.kwargs
        self.assertEqual(kwargs["checkout_data"], {"custom": {"user_id": str(self.user["id"])}})
        self.assertEqual(kwargs["variant_id"], "2")
        self.assertTrue(kwargs["test_mode"])

    def test_a_link_this_server_did_not_sign_opens_nothing(self) -> None:
        with mock.patch("packages.infrastructure.lemon_squeezy_api.LemonSqueezyClient.create_checkout") as checkout:
            status, _ = self._get("/pay/1abcdefghjk")
        self.assertEqual(status, 404)
        checkout.assert_not_called()

    def test_a_signed_event_marks_the_account_paying_and_a_forged_one_is_refused(self) -> None:
        user_id = str(self.user["id"])
        self.assertEqual(self._webhook(subscription_event("subscription_created", user_id=user_id), signature="0" * 64), 403)
        self.assertIsNone(self.database.get_billing_customer("family@example.com", include_inactive=True))

        self.assertEqual(self._webhook(subscription_event("subscription_created", user_id=user_id)), 200)
        customer = self.database.get_billing_customer("family@example.com", include_inactive=True)
        self.assertEqual(customer["subscriptionStatus"], "active")
        self.assertTrue(subscription_is_paying(customer))

        # Paying already: the same link goes to where it is managed, so a
        # second tap never buys twice.
        with mock.patch("packages.infrastructure.lemon_squeezy_api.LemonSqueezyClient.create_checkout") as checkout:
            status, location = self._get(f"/pay/{self._code()}")
        self.assertEqual((status, location), (302, "https://assistyca.lemonsqueezy.com/billing?x=1"))
        checkout.assert_not_called()

    def test_an_admin_sees_each_clients_payment_link(self) -> None:
        # For paying on a family's behalf, or trying the checkout on staging.
        self.database.register_user("boss@example.com", is_admin=True)
        code, _ = self.server.store.issue_challenge("boss@example.com")
        _, _, result = self.server.store.verify_code("boss@example.com", code)
        request = urllib_request.Request(
            f"{self.base_url}/api/admin/users",
            headers={"Authorization": f"Bearer {(result or {}).get('token')}"},
        )
        with urllib_request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        listed = next(user for user in payload["users"] if user["email"] == "family@example.com")
        self.assertTrue(listed["paymentStatus"]["payLink"].endswith(f"/pay/{self._code()}"))

    def test_a_paid_account_is_let_through_after_its_trial(self) -> None:
        self.database.set_user_trial("family@example.com", trial_days=2)
        with self.database._connection() as conn:  # noqa: SLF001 - fixture setup
            conn.execute(
                "UPDATE users SET trial_started_at = ? WHERE id = ?",
                ((datetime.now(timezone.utc) - timedelta(days=5)).isoformat(), int(self.user["id"])),
            )
            conn.commit()
        user = self.database.get_user("family@example.com") or {}

        def allowed() -> bool:
            customer = self.database.get_billing_customer("family@example.com", include_inactive=True)
            return bool(describe_trial(user, is_paying=subscription_is_paying(customer))["allowed"])

        self.assertFalse(allowed())
        self.assertEqual(self._webhook(subscription_event("subscription_created", user_id=str(self.user["id"]))), 200)
        self.assertTrue(allowed())


if __name__ == "__main__":
    unittest.main()
