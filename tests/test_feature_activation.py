from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.feature_activation import FeatureActivationConfig
from packages.infrastructure.feature_activation import FeatureActivationService
from packages.infrastructure.portal_db import PortalDatabase


DEFAULT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"


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

    def _connect_whatsapp(self) -> None:
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="12345",
            phone_number_id="12345",
            owner_wa_id="15551234567",
            connection_status="connected",
        )

    def test_default_feature_catalog_is_seeded_and_assigned(self) -> None:
        features = self.database.list_assigned_features("owner@example.com")

        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["featureId"], DEFAULT_FEATURE_ID)
        self.assertTrue(features[0]["billingRequired"])
        self.assertTrue(features[0]["requirements"]["requiresWhatsAppConnection"])

    def test_list_feature_states_returns_backend_feature_catalog(self) -> None:
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        result = service.list_feature_states("owner@example.com")

        self.assertEqual(len(result["features"]), 1)
        self.assertEqual(result["features"][0]["featureId"], DEFAULT_FEATURE_ID)
        self.assertEqual(result["features"][0]["name"], "WhatsApp Reply Assistant")
        self.assertTrue(result["features"][0]["billing"]["required"])

    def test_activation_requires_setup_for_whatsapp_features(self) -> None:
        service = FeatureActivationService(
            self.database,
            config=FeatureActivationConfig(checkout_variant_id="123"),
            lemon_squeezy_client=FakeLemonSqueezyClient(checkout_url="https://checkout.example"),
        )

        result = service.activate_feature(
            "owner@example.com",
            feature_id=DEFAULT_FEATURE_ID,
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "setup_required")
        self.assertFalse(result["feature"]["isActive"])

    def test_activation_requires_payment_and_creates_checkout(self) -> None:
        self._connect_whatsapp()
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
            feature_id=DEFAULT_FEATURE_ID,
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "payment_required")
        self.assertEqual(result["paymentStatus"]["checkoutUrl"], "https://checkout.example.com/start")
        self.assertEqual(client.checkout_calls[0]["variant_id"], "variant_1")

    def test_activation_reuses_existing_checkout_for_unpaid_customer(self) -> None:
        self._connect_whatsapp()
        self.database.save_feature_entitlement(
            "owner@example.com",
            feature_id=DEFAULT_FEATURE_ID,
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
            feature_id=DEFAULT_FEATURE_ID,
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "payment_required")
        self.assertEqual(result["paymentStatus"]["checkoutUrl"], "https://checkout.example.com/existing")
        self.assertEqual(client.checkout_calls, [])

    def test_activation_succeeds_for_paying_customer(self) -> None:
        self._connect_whatsapp()
        client = FakeLemonSqueezyClient(
            subscriptions=[
                {
                    "id": "sub_1",
                    "status": "active",
                    "customer_id": "cust_1",
                    "product_id": "prod_1",
                    "variant_id": "variant_1",
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
            feature_id=DEFAULT_FEATURE_ID,
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["feature"]["isActive"])
        self.assertTrue(result["paymentStatus"]["isPayingCustomer"])
        self.assertTrue(result["paymentStatus"]["isEntitled"])
        self.assertEqual(result["paymentStatus"]["subscriptionStatus"], "active")

    def test_activation_rejects_unassigned_feature(self) -> None:
        self.database.upsert_feature(
            "hidden-tool",
            feature_name="Hidden Tool",
            channel="Web",
            mode="Default",
            billing_required=False,
            default_assigned=False,
            is_active=True,
        )
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        result = service.activate_feature(
            "owner@example.com",
            feature_id="hidden-tool",
            feature_name="Hidden Tool",
            channel="Web",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "feature_not_available")

    def test_activation_uses_explicit_feature_requirements_not_id_heuristics(self) -> None:
        self.database.upsert_feature(
            "whatsapp-in-name-but-web",
            feature_name="Web Intake Tool",
            description="A web-only tool that should not require WhatsApp setup.",
            channel="Web",
            mode="Default",
            billing_required=False,
            default_assigned=False,
            is_active=True,
            requirements={"requiresWhatsAppConnection": False},
        )
        self.database.assign_feature_to_user("owner@example.com", "whatsapp-in-name-but-web")
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        result = service.activate_feature(
            "owner@example.com",
            feature_id="whatsapp-in-name-but-web",
            feature_name="Web Intake Tool",
            channel="Web",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["feature"]["isActive"])
        self.assertFalse(result["feature"]["setupStatus"]["required"])

    def test_entitlement_is_feature_specific(self) -> None:
        self._connect_whatsapp()
        self.database.upsert_feature(
            "premium-whatsapp-tool",
            feature_name="Premium WhatsApp Tool",
            channel="WhatsApp",
            mode="Human-reviewed",
            billing_required=True,
            billing_provider="lemon_squeezy",
            billing_variant_id="variant_2",
            default_assigned=False,
            is_active=True,
            requirements={"requiresWhatsAppConnection": True},
        )
        self.database.assign_feature_to_user("owner@example.com", "premium-whatsapp-tool")
        client = FakeLemonSqueezyClient(
            subscriptions=[
                {
                    "id": "sub_1",
                    "status": "active",
                    "customer_id": "cust_1",
                    "product_id": "prod_1",
                    "variant_id": "variant_1",
                    "first_subscription_item": {"id": "item_1"},
                    "urls": {"customer_portal": "https://portal.example.com/billing"},
                }
            ],
            checkout_url="https://checkout.example.com/upgrade",
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
            feature_id="premium-whatsapp-tool",
            feature_name="Premium WhatsApp Tool",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "payment_required")
        self.assertFalse(result["paymentStatus"]["isEntitled"])
        self.assertTrue(result["paymentStatus"]["hasAnyActiveSubscription"])

    def test_list_feature_states_refreshes_payment_after_checkout_return(self) -> None:
        self.database.save_feature_entitlement(
            "owner@example.com",
            feature_id=DEFAULT_FEATURE_ID,
            provider="lemon_squeezy",
            variant_id="variant_1",
            checkout_url="https://checkout.example.com/start",
        )
        client = FakeLemonSqueezyClient(
            subscriptions=[
                {
                    "id": "sub_1",
                    "status": "active",
                    "customer_id": "cust_1",
                    "product_id": "prod_1",
                    "variant_id": "variant_1",
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

        result = service.list_feature_states("owner@example.com")

        self.assertEqual(len(result["features"]), 1)
        self.assertTrue(result["features"][0]["paymentStatus"]["isEntitled"])
        self.assertEqual(client.list_calls[0]["user_email"], "owner@example.com")

    def test_deactivation_is_recorded(self) -> None:
        self.database.set_feature_activation(
            "owner@example.com",
            feature_id=DEFAULT_FEATURE_ID,
            feature_name="WhatsApp Reply Assistant",
            is_active=True,
        )
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        result = service.deactivate_feature(
            "owner@example.com",
            feature_id=DEFAULT_FEATURE_ID,
            feature_name="WhatsApp Reply Assistant",
            channel="WhatsApp",
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["feature"]["isActive"])
        events = self.database.list_feature_activation_events("owner@example.com", DEFAULT_FEATURE_ID)
        self.assertEqual(events[0]["outcome"], "deactivated")


if __name__ == "__main__":
    unittest.main()
