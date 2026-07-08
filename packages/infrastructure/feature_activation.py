"""Centralized feature activation decisions and analytics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from packages.infrastructure.lemon_squeezy_api import LemonSqueezyClient
from packages.infrastructure.lemon_squeezy_api import LemonSqueezyConfigurationError
from packages.infrastructure.lemon_squeezy_api import LemonSqueezyRequestError
from packages.infrastructure.lemon_squeezy_api import load_lemon_squeezy_config
from packages.infrastructure.portal_db import PortalDatabase


ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "on_trial"})
WHATSAPP_CHANNELS = frozenset({"whatsapp"})
DEFAULT_PRODUCT_NAME = "Assistyca"


@dataclass
class FeatureActivationConfig:
    billing_provider: str = "lemon_squeezy"
    checkout_store_id: str = ""
    checkout_variant_id: str = ""
    checkout_redirect_url: str = ""
    checkout_button_color: str = "#17958a"
    checkout_locale: str = "en"
    test_mode: bool = False
    product_name: str = DEFAULT_PRODUCT_NAME


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def parse_bool(value: Any, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def load_feature_activation_config(
    *,
    billing_provider: str | None = None,
    checkout_store_id: str | None = None,
    checkout_variant_id: str | None = None,
    checkout_redirect_url: str | None = None,
    checkout_button_color: str | None = None,
    checkout_locale: str | None = None,
    test_mode: bool | None = None,
    product_name: str | None = None,
) -> FeatureActivationConfig:
    return FeatureActivationConfig(
        billing_provider=normalize_text(
            billing_provider if billing_provider is not None else os.getenv("FEATURE_ACTIVATION_BILLING_PROVIDER")
        )
        or "lemon_squeezy",
        checkout_store_id=normalize_text(
            checkout_store_id
            if checkout_store_id is not None
            else os.getenv("LEMON_SQUEEZY_ACTIVATION_STORE_ID") or os.getenv("LEMON_SQUEEZY_STORE_ID")
        ),
        checkout_variant_id=normalize_text(
            checkout_variant_id
            if checkout_variant_id is not None
            else os.getenv("LEMON_SQUEEZY_ACTIVATION_VARIANT_ID") or os.getenv("LEMON_SQUEEZY_VARIANT_ID")
        ),
        checkout_redirect_url=normalize_text(
            checkout_redirect_url
            if checkout_redirect_url is not None
            else os.getenv("LEMON_SQUEEZY_ACTIVATION_REDIRECT_URL")
        ),
        checkout_button_color=normalize_text(
            checkout_button_color
            if checkout_button_color is not None
            else os.getenv("LEMON_SQUEEZY_ACTIVATION_BUTTON_COLOR")
        )
        or "#17958a",
        checkout_locale=normalize_text(
            checkout_locale
            if checkout_locale is not None
            else os.getenv("LEMON_SQUEEZY_ACTIVATION_CHECKOUT_LOCALE")
        )
        or "en",
        test_mode=parse_bool(
            test_mode if test_mode is not None else os.getenv("LEMON_SQUEEZY_ACTIVATION_TEST_MODE"),
            default=parse_bool(os.getenv("LEMON_SQUEEZY_TEST_MODE"), default=False),
        ),
        product_name=normalize_text(
            product_name
            if product_name is not None
            else os.getenv("PORTAL_PRODUCT_NAME") or os.getenv("LEMON_SQUEEZY_ACTIVATION_PRODUCT_NAME")
        )
        or DEFAULT_PRODUCT_NAME,
    )


class FeatureActivationService:
    def __init__(
        self,
        database: PortalDatabase,
        *,
        config: FeatureActivationConfig | None = None,
        lemon_squeezy_client: Any | None = None,
    ) -> None:
        self.database = database
        self.config = config or load_feature_activation_config()
        self.lemon_squeezy_client = lemon_squeezy_client

    @classmethod
    def from_env(
        cls,
        database: PortalDatabase,
        *,
        config: FeatureActivationConfig | None = None,
    ) -> "FeatureActivationService":
        resolved_config = config or load_feature_activation_config()
        lemon_squeezy_client: LemonSqueezyClient | None = None
        if resolved_config.billing_provider == "lemon_squeezy":
            lemon_config = load_lemon_squeezy_config(store_id=resolved_config.checkout_store_id)
            if lemon_config.api_key:
                try:
                    lemon_squeezy_client = LemonSqueezyClient(lemon_config)
                except LemonSqueezyConfigurationError:
                    lemon_squeezy_client = None
        return cls(database, config=resolved_config, lemon_squeezy_client=lemon_squeezy_client)

    def list_feature_states(self, email: str) -> dict[str, Any]:
        return {
            "features": self.database.list_feature_activations(email),
            "paymentStatus": self._resolve_payment_status(email, refresh_remote=False),
        }

    def activate_feature(
        self,
        email: str,
        *,
        feature_id: str,
        feature_name: str = "",
        channel: str = "",
        public_base_url: str = "",
    ) -> dict[str, Any]:
        normalized_feature_id = normalize_text(feature_id)
        normalized_feature_name = normalize_text(feature_name)
        normalized_channel = normalize_text(channel)

        self.database.record_feature_activation_event(
            email,
            feature_id=normalized_feature_id,
            feature_name=normalized_feature_name,
            event_name="activation_requested",
            outcome="started",
            metadata={"channel": normalized_channel},
        )

        setup_status = self._resolve_setup_status(email, feature_id=normalized_feature_id, channel=normalized_channel)
        if not setup_status["ready"]:
            self.database.record_feature_activation_event(
                email,
                feature_id=normalized_feature_id,
                feature_name=normalized_feature_name,
                event_name="activation_blocked",
                outcome="setup_required",
                reason="setup_incomplete",
                metadata=setup_status,
            )
            feature = self.database.set_feature_activation(
                email,
                feature_id=normalized_feature_id,
                feature_name=normalized_feature_name,
                is_active=False,
                metadata={"channel": normalized_channel, "setupRequired": True},
            )
            return {
                "ok": False,
                "error": "setup_required",
                "message": setup_status["message"],
                "feature": feature,
                "setupStatus": setup_status,
                "paymentStatus": self._resolve_payment_status(email, refresh_remote=False),
            }

        payment_status = self._resolve_payment_status(
            email,
            refresh_remote=True,
            feature_id=normalized_feature_id,
            feature_name=normalized_feature_name,
            public_base_url=public_base_url,
        )
        if not payment_status["isPayingCustomer"]:
            self.database.record_feature_activation_event(
                email,
                feature_id=normalized_feature_id,
                feature_name=normalized_feature_name,
                event_name="activation_blocked",
                outcome="payment_required",
                reason=normalize_text(payment_status.get("subscriptionStatus")) or "not_paying",
                metadata=payment_status,
            )
            feature = self.database.set_feature_activation(
                email,
                feature_id=normalized_feature_id,
                feature_name=normalized_feature_name,
                is_active=False,
                metadata={
                    "channel": normalized_channel,
                    "paymentRequired": True,
                    "checkoutUrl": payment_status.get("checkoutUrl", ""),
                },
            )
            return {
                "ok": False,
                "error": "payment_required",
                "message": payment_status["message"],
                "feature": feature,
                "paymentStatus": payment_status,
                "setupStatus": setup_status,
            }

        feature = self.database.set_feature_activation(
            email,
            feature_id=normalized_feature_id,
            feature_name=normalized_feature_name,
            is_active=True,
            metadata={
                "channel": normalized_channel,
                "billingProvider": payment_status.get("provider", ""),
                "subscriptionStatus": payment_status.get("subscriptionStatus", ""),
            },
        )
        self.database.record_feature_activation_event(
            email,
            feature_id=normalized_feature_id,
            feature_name=normalized_feature_name,
            event_name="activation_changed",
            outcome="activated",
            metadata={
                "channel": normalized_channel,
                "provider": payment_status.get("provider", ""),
                "subscriptionStatus": payment_status.get("subscriptionStatus", ""),
            },
        )
        return {
            "ok": True,
            "message": "Tool activated.",
            "feature": feature,
            "paymentStatus": payment_status,
            "setupStatus": setup_status,
        }

    def deactivate_feature(
        self,
        email: str,
        *,
        feature_id: str,
        feature_name: str = "",
        channel: str = "",
    ) -> dict[str, Any]:
        normalized_feature_id = normalize_text(feature_id)
        normalized_feature_name = normalize_text(feature_name)
        normalized_channel = normalize_text(channel)
        feature = self.database.set_feature_activation(
            email,
            feature_id=normalized_feature_id,
            feature_name=normalized_feature_name,
            is_active=False,
            metadata={"channel": normalized_channel},
        )
        self.database.record_feature_activation_event(
            email,
            feature_id=normalized_feature_id,
            feature_name=normalized_feature_name,
            event_name="activation_changed",
            outcome="deactivated",
            metadata={"channel": normalized_channel},
        )
        return {
            "ok": True,
            "message": "Tool turned off.",
            "feature": feature,
            "paymentStatus": self._resolve_payment_status(email, refresh_remote=False),
        }

    def _resolve_setup_status(self, email: str, *, feature_id: str, channel: str) -> dict[str, Any]:
        normalized_channel = normalize_text(channel).lower()
        normalized_feature_id = normalize_text(feature_id).lower()
        if normalized_channel not in WHATSAPP_CHANNELS and "whatsapp" not in normalized_feature_id:
            return {
                "required": False,
                "ready": True,
                "message": "",
            }

        connection = self.database.get_whatsapp_connection(email) or {}
        ready = bool(
            normalize_text(connection.get("phoneNumberId"))
            and normalize_text(connection.get("ownerWaId"))
            and normalize_text(connection.get("connectionStatus")) == "connected"
        )
        return {
            "required": True,
            "ready": ready,
            "connectionStatus": normalize_text(connection.get("connectionStatus")) or "not_connected",
            "message": "" if ready else "Finish WhatsApp setup before activating this tool.",
        }

    def _resolve_payment_status(
        self,
        email: str,
        *,
        refresh_remote: bool,
        feature_id: str = "",
        feature_name: str = "",
        public_base_url: str = "",
    ) -> dict[str, Any]:
        stored = self.database.get_billing_customer(email) or {}
        if not refresh_remote:
            return self._format_payment_status(stored, checkout_required=not self._is_paying_record(stored))

        resolved = dict(stored)
        if self.config.billing_provider == "lemon_squeezy" and self.lemon_squeezy_client is not None:
            remote = self._refresh_from_lemon_squeezy(email)
            if remote:
                resolved = remote

        if self._is_paying_record(resolved):
            return self._format_payment_status(resolved, checkout_required=False)

        checkout_url = normalize_text(resolved.get("checkoutUrl"))
        if not checkout_url:
            checkout_url = self._create_checkout_url(
                email,
                feature_id=feature_id,
                feature_name=feature_name,
                public_base_url=public_base_url,
            )
            if checkout_url:
                resolved = self.database.save_billing_customer(
                    email,
                    provider=self.config.billing_provider,
                    variant_id=self.config.checkout_variant_id,
                    checkout_url=checkout_url,
                    metadata={
                        **(resolved.get("metadata") if isinstance(resolved.get("metadata"), dict) else {}),
                        "lastCheckoutFeatureId": normalize_text(feature_id),
                        "lastCheckoutFeatureName": normalize_text(feature_name),
                    },
                )

        return self._format_payment_status(resolved, checkout_required=True)

    def _refresh_from_lemon_squeezy(self, email: str) -> dict[str, Any]:
        existing = self.database.get_billing_customer(email) or {}
        existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
        try:
            response = self.lemon_squeezy_client.list_subscriptions(user_email=email, page_size=10)
        except LemonSqueezyRequestError:
            return existing

        items = response.get("items") if isinstance(response, dict) else []
        subscriptions = items if isinstance(items, list) else []
        selected = None
        for subscription in subscriptions:
            if normalize_text(subscription.get("status")) in ACTIVE_SUBSCRIPTION_STATUSES:
                selected = subscription
                break
        if selected is None and subscriptions:
            selected = subscriptions[0]

        if selected is None:
            return self.database.save_billing_customer(
                email,
                provider=self.config.billing_provider,
                external_customer_id=normalize_text(existing.get("externalCustomerId")),
                product_id=normalize_text(existing.get("productId")),
                variant_id=normalize_text(existing.get("variantId")) or self.config.checkout_variant_id,
                subscription_status="",
                checkout_url=normalize_text(existing.get("checkoutUrl")),
                customer_portal_url=normalize_text(existing.get("customerPortalUrl")),
                metadata={
                    **existing_metadata,
                    "source": "lemonsqueezy_api",
                },
            )

        urls = selected.get("urls") if isinstance(selected.get("urls"), dict) else {}
        first_item = selected.get("first_subscription_item") if isinstance(selected.get("first_subscription_item"), dict) else {}
        return self.database.save_billing_customer(
            email,
            provider=self.config.billing_provider,
            external_customer_id=normalize_text(selected.get("customer_id")),
            external_subscription_id=normalize_text(selected.get("id")),
            external_subscription_item_id=normalize_text(first_item.get("id")),
            subscription_status=normalize_text(selected.get("status")),
            product_id=normalize_text(selected.get("product_id")),
            variant_id=normalize_text(selected.get("variant_id")) or normalize_text(existing.get("variantId")) or self.config.checkout_variant_id,
            checkout_url=normalize_text(existing.get("checkoutUrl")),
            customer_portal_url=normalize_text(urls.get("customer_portal")) or normalize_text(existing.get("customerPortalUrl")),
            metadata={
                **existing_metadata,
                "source": "lemonsqueezy_api",
                "userEmail": normalize_text(selected.get("user_email")),
                "statusFormatted": normalize_text(selected.get("status_formatted")),
                "renewsAt": normalize_text(selected.get("renews_at")),
            },
        )

    def _create_checkout_url(
        self,
        email: str,
        *,
        feature_id: str,
        feature_name: str,
        public_base_url: str,
    ) -> str:
        if self.config.billing_provider != "lemon_squeezy" or self.lemon_squeezy_client is None:
            return ""
        if not self.config.checkout_variant_id:
            return ""

        redirect_url = normalize_text(self.config.checkout_redirect_url)
        if not redirect_url and normalize_text(public_base_url):
            redirect_url = f"{normalize_text(public_base_url).rstrip('/')}/portal/#features"

        try:
            checkout = self.lemon_squeezy_client.create_checkout(
                store_id=self.config.checkout_store_id,
                variant_id=self.config.checkout_variant_id,
                product_options={"redirect_url": redirect_url} if redirect_url else None,
                checkout_options={
                    "button_color": self.config.checkout_button_color,
                    "locale": self.config.checkout_locale,
                },
                checkout_data={
                    "email": normalize_text(email),
                    "custom": {
                        "portal_email": normalize_text(email),
                        "feature_id": normalize_text(feature_id),
                        "feature_name": normalize_text(feature_name),
                    },
                },
                test_mode=self.config.test_mode,
            )
        except LemonSqueezyRequestError:
            return ""

        return normalize_text(checkout.get("url"))

    def _is_paying_record(self, record: dict[str, Any] | None) -> bool:
        payload = record if isinstance(record, dict) else {}
        return normalize_text(payload.get("subscriptionStatus")) in ACTIVE_SUBSCRIPTION_STATUSES

    def _format_payment_status(self, record: dict[str, Any] | None, *, checkout_required: bool) -> dict[str, Any]:
        payload = record if isinstance(record, dict) else {}
        is_paying_customer = self._is_paying_record(payload)
        checkout_url = normalize_text(payload.get("checkoutUrl"))

        if is_paying_customer:
            message = "Payment is active."
        elif checkout_url:
            message = "Add your card details before activating this tool."
        else:
            message = "Payment is required before activating this tool."

        return {
            "provider": normalize_text(payload.get("provider")) or self.config.billing_provider,
            "isPayingCustomer": is_paying_customer,
            "subscriptionStatus": normalize_text(payload.get("subscriptionStatus")),
            "checkoutRequired": bool(checkout_required and not is_paying_customer),
            "checkoutUrl": checkout_url,
            "customerPortalUrl": normalize_text(payload.get("customerPortalUrl")),
            "message": message,
        }
