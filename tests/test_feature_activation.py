from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packages.infrastructure.feature_activation import FeatureActivationConfig
from packages.infrastructure.feature_activation import FeatureActivationService
from packages.infrastructure.portal_db import PortalDatabase


DEFAULT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"
FOLLOW_UP_FEATURE_ID = "whatsapp-business-follow-up-outreach-writer"
MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier"


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

        feature_ids = [feature["featureId"] for feature in features]

        self.assertEqual(feature_ids, [DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID])
        self.assertTrue(all(feature["billingRequired"] for feature in features))
        self.assertTrue(features[0]["requirements"]["requiresWhatsAppConnection"])
        self.assertTrue(features[1]["requirements"]["requiresWhatsAppConnection"])
        self.assertTrue(features[2]["requirements"]["requiresScheduledMonitorConfig"])

    def test_list_feature_states_returns_backend_feature_catalog(self) -> None:
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        result = service.list_feature_states("owner@example.com")

        features_by_id = {feature["featureId"]: feature for feature in result["features"]}

        self.assertEqual(set(features_by_id), {DEFAULT_FEATURE_ID, FOLLOW_UP_FEATURE_ID, MONITOR_FEATURE_ID})
        self.assertEqual(features_by_id[DEFAULT_FEATURE_ID]["name"], "WhatsApp Reply Assistant")
        self.assertEqual(features_by_id[FOLLOW_UP_FEATURE_ID]["name"], "WhatsApp Re-engagement Assistant")
        self.assertEqual(features_by_id[MONITOR_FEATURE_ID]["name"], "Scheduled Web Monitor")
        self.assertTrue(features_by_id[FOLLOW_UP_FEATURE_ID]["billing"]["required"])

    def test_bootstrap_paid_emails_mark_billing_features_entitled(self) -> None:
        paid_database = PortalDatabase(
            Path(self.temp_dir.name) / "paid.db",
            bootstrap_paid_emails={"owner@example.com"},
        )
        service = FeatureActivationService(paid_database, config=FeatureActivationConfig())

        result = service.list_feature_states("owner@example.com")

        features_by_id = {feature["featureId"]: feature for feature in result["features"]}
        self.assertTrue(features_by_id[DEFAULT_FEATURE_ID]["paymentStatus"]["isEntitled"])
        self.assertTrue(features_by_id[FOLLOW_UP_FEATURE_ID]["paymentStatus"]["isEntitled"])
        self.assertTrue(features_by_id[MONITOR_FEATURE_ID]["paymentStatus"]["isEntitled"])

        billing_customer = paid_database.get_billing_customer("owner@example.com")
        self.assertIsNotNone(billing_customer)
        self.assertEqual(billing_customer["subscriptionStatus"], "active")
        self.assertEqual(billing_customer["metadata"]["source"], "bootstrap_paid_emails")

    def test_save_monitor_feature_config_persists_settings_and_marks_setup_ready(self) -> None:
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        with mock.patch.dict(
            os.environ,
            {
                "PORTAL_SMTP_HOST": "smtp.example.com",
                "PORTAL_SMTP_FROM_EMAIL": "alerts@example.com",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ):
            result = service.save_feature_config(
                "owner@example.com",
                feature_id=MONITOR_FEATURE_ID,
                prompt={
                    "toneGuidance": "Crisp and factual.",
                    "replyRules": "Only include source-backed matches.",
                    "businessNotes": "Track legal events in Israel.",
                    "escalationGuidance": "Escalate when a registration deadline is under 7 days away.",
                    "exampleReplies": "Conference opens next week.",
                    "responseStyle": "balanced",
                    "scenario": "monitor",
                },
                settings={
                    "watchItems": [
                        "Criminal defense law conferences in Israel",
                        "Court holidays that affect legal work",
                    ],
                    "intervalDays": 7,
                    "deliveryChannel": "email",
                },
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["setupStatus"]["ready"])
        self.assertTrue(result["feature"]["setupComplete"])
        self.assertEqual(
            result["feature"]["settings"]["watchItems"],
            ["Criminal defense law conferences in Israel", "Court holidays that affect legal work"],
        )
        self.assertEqual(result["feature"]["settings"]["intervalDays"], 7)
        self.assertEqual(result["feature"]["prompt"]["scenario"], "monitor")

        assignment = self.database.get_feature_assignment("owner@example.com", MONITOR_FEATURE_ID)
        self.assertEqual(
            assignment["metadata"]["settings"]["watchItems"],
            ["Criminal defense law conferences in Israel", "Court holidays that affect legal work"],
        )

    def test_save_monitor_feature_config_requires_openai_backend(self) -> None:
        service = FeatureActivationService(self.database, config=FeatureActivationConfig())

        with mock.patch.dict(
            os.environ,
            {
                "PORTAL_SMTP_HOST": "smtp.example.com",
                "PORTAL_SMTP_FROM_EMAIL": "alerts@example.com",
                "OPENAI_API_KEY": "",
            },
            clear=False,
        ):
            result = service.save_feature_config(
                "owner@example.com",
                feature_id=MONITOR_FEATURE_ID,
                settings={
                    "watchItems": ["Legal conferences"],
                    "intervalDays": 7,
                    "deliveryChannel": "email",
                },
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["setupStatus"]["ready"])
        self.assertIn("OPENAI_API_KEY", result["setupStatus"]["message"])

    def test_monitor_activation_requires_saved_config_before_payment(self) -> None:
        client = FakeLemonSqueezyClient(checkout_url="https://checkout.example.com/monitor")
        service = FeatureActivationService(
            self.database,
            config=FeatureActivationConfig(
                checkout_store_id="store_1",
                checkout_variant_id="variant_1",
            ),
            lemon_squeezy_client=client,
        )

        first_result = service.activate_feature(
            "owner@example.com",
            feature_id=MONITOR_FEATURE_ID,
            feature_name="Scheduled Web Monitor",
            channel="Alerts",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(first_result["ok"])
        self.assertEqual(first_result["error"], "setup_required")

        with mock.patch.dict(
            os.environ,
            {
                "PORTAL_SMTP_HOST": "smtp.example.com",
                "PORTAL_SMTP_FROM_EMAIL": "alerts@example.com",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ):
            service.save_feature_config(
                "owner@example.com",
                feature_id=MONITOR_FEATURE_ID,
                settings={
                    "watchItems": [
                        "Legal conferences",
                        "Holiday reminders",
                    ],
                    "intervalDays": 3,
                    "deliveryChannel": "email",
                },
            )
            second_result = service.activate_feature(
                "owner@example.com",
                feature_id=MONITOR_FEATURE_ID,
                feature_name="Scheduled Web Monitor",
                channel="Alerts",
                public_base_url="https://portal.example.com",
            )

        self.assertFalse(second_result["ok"])
        self.assertEqual(second_result["error"], "payment_required")
        self.assertTrue(second_result["setupStatus"]["ready"])

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

        features_by_id = {feature["featureId"]: feature for feature in result["features"]}
        self.assertTrue(features_by_id[DEFAULT_FEATURE_ID]["paymentStatus"]["isEntitled"])
        self.assertEqual(client.list_calls[0]["user_email"], "owner@example.com")

    def test_second_whatsapp_feature_reuses_existing_whatsapp_connection(self) -> None:
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
            feature_id=FOLLOW_UP_FEATURE_ID,
            feature_name="WhatsApp Re-engagement Assistant",
            channel="WhatsApp",
            public_base_url="https://portal.example.com",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "payment_required")
        self.assertTrue(result["setupStatus"]["ready"])

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
