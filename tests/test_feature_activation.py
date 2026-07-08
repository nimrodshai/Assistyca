from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.feature_activation import FeatureActivationConfig
from packages.infrastructure.feature_activation import FeatureActivationService
from packages.infrastructure.portal_db import PortalDatabase


class FakeLemonSqueezyClient:
    def __init__(self, *, subscriptions: list[dict[str, object]] | None = None, checkout_url: str = "") -> None:
        self.subscriptions = subscriptions or []
        self.checkout_url = checkout_url
        self.list_calls: list[dict[str, object]] = []
        self.checkout_calls: list[dict[str, object]] = []

    def list_subscriptions(self, **kwargs):
        self.list_calls.append(kwargs)
        return {"items": list(self.subscriptions)}

    def create_checkout(self, **kwargs):
        self.checkout_calls.append(kwargs)
        return {"id": "checkout_123", "url": self.checkout_url}


class FeatureActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(db_path)
        self.database.register_user("owner@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_activation_requires_setup_for_whatsapp_features(self) -> None:
        service = FeatureActivationService(
            self.database,
            config=FeatureActivationConfig(checkout_variant_id="123"),
            lemon_squeezy_client=FakeLemonSqueezyClient(checkout_url="https://checkout.example"),
        )

        result = service.activate_feature(
            "owner@example.com",
            feature_id="whatsapp-business-reply-suggestion-assistant",
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "setup_required")
        self.assertFalse(result["feature"]["isActive"])

    def test_activation_requires_payment_and_creates_checkout(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        client = FakeLemonSqueezyClient(checkout_url="https://checkout.example.com/start")
        service = FeatureActivationService(
            self.database,
            config=FeatureActivationConfig(
                checkout_store_id="store_1",
                checkout_variant_id="variant_1",
            ),
            lemon_squeezy_client=client,
        )

        result = service.activate_feature(
            "owner@example.com",
            feature_id="whatsapp-business-reply-suggestion-assistant",
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "payment_required")
        self.assertEqual(result["paymentStatus"]["checkoutUrl"], "https://checkout.example.com/start")
        self.assertEqual(client.checkout_calls[0]["variant_id"], "variant_1")

    def test_activation_reuses_existing_checkout_for_unpaid_customer(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        self.database.save_billing_customer(
            "owner@example.com",
            provider="lemon_squeezy",
            variant_id="variant_1",
            checkout_url="https://checkout.example.com/existing",
        )
        client = FakeLemonSqueezyClient(checkout_url="https://checkout.example.com/new")
        service = FeatureActivationService(
            self.database,
            config=FeatureActivationConfig(
                checkout_store_id="store_1",
                checkout_variant_id="variant_1",
            ),
            lemon_squeezy_client=client,
        )

        result = service.activate_feature(
            "owner@example.com",
            feature_id="whatsapp-business-reply-suggestion-assistant",
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "payment_required")
        self.assertEqual(result["paymentStatus"]["checkoutUrl"], "https://checkout.example.com/existing")
        self.assertEqual(client.checkout_calls, [])

    def test_activation_succeeds_for_paying_customer(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
        )
        client = FakeLemonSqueezyClient(
            subscriptions=[
                {
                    "id": "sub_1",
                    "status": "active",
                    "customer_id": "cust_1",
                    "product_id": "prod_1",
                    "variant_id": "var_1",
                    "first_subscription_item": {"id": "item_1"},
                    "urls": {"customer_portal": "https://portal.example.com/billing"},
                }
            ],
            checkout_url="https://checkout.example.com/start",
        )
        service = FeatureActivationService(
            self.database,
            config=FeatureActivationConfig(
                checkout_store_id="store_1",
                checkout_variant_id="variant_1",
            ),
            lemon_squeezy_client=client,
        )

        result = service.activate_feature(
            "owner@example.com",
            feature_id="whatsapp-business-reply-suggestion-assistant",
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["feature"]["isActive"])
        self.assertTrue(result["paymentStatus"]["isPayingCustomer"])
        self.assertEqual(result["paymentStatus"]["subscriptionStatus"], "active")

    def test_deactivation_is_recorded(self) -> None:
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id="tool-1",
            feature_name="Tool 1",
            is_active=True,
        )
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        result = service.deactivate_feature(
            "owner@example.com",
            feature_id="tool-1",
            feature_name="Tool 1",
            channel="Web",
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["feature"]["isActive"])
        events = self.database.list_feature_activation_events("owner@example.com", "tool-1")
        self.assertEqual(events[0]["outcome"], "deactivated")


if __name__ == "__main__":
    unittest.main()
