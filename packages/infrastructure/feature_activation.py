"""Centralized feature activation decisions and analytics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any

from packages.infrastructure.lemon_squeezy_api import LemonSqueezyClient
from packages.infrastructure.lemon_squeezy_api import LemonSqueezyConfigurationError
from packages.infrastructure.lemon_squeezy_api import LemonSqueezyRequestError
from packages.infrastructure.lemon_squeezy_api import load_lemon_squeezy_config
from packages.tools.scheduled_monitor.monitor import MONITOR_FEATURE_ID
from packages.tools.scheduled_monitor.monitor import build_monitor_setup_status
from packages.tools.scheduled_monitor.monitor import normalize_monitor_settings
from packages.tools.scheduled_monitor.monitor import resolve_next_monitor_slot
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.whatsapp_reengagement import REENGAGEMENT_FEATURE_ID
from packages.infrastructure.whatsapp_reengagement import normalize_reengagement_settings
from packages.infrastructure.whatsapp_reengagement import resolve_next_reengagement_slot
from packages.infrastructure.whatsapp_reengagement import resolve_timezone
from packages.infrastructure.whatsapp_tool_delivery import normalize_whatsapp_tool_delivery_settings


ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "on_trial"})
WHATSAPP_REPLY_ASSISTANT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant"
DEFAULT_PRODUCT_NAME = "Assistyca"
DEFAULT_PAYMENT_STATUS_CACHE_TTL_SECONDS = 120


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
    payment_status_cache_ttl_seconds: int = DEFAULT_PAYMENT_STATUS_CACHE_TTL_SECONDS


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_bool(value: Any, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_datetime(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


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
    payment_status_cache_ttl_seconds: int | None = None,
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
        payment_status_cache_ttl_seconds=max(
            0,
            safe_int(
                payment_status_cache_ttl_seconds
                if payment_status_cache_ttl_seconds is not None
                else os.getenv("FEATURE_ACTIVATION_PAYMENT_STATUS_CACHE_TTL_SECONDS"),
                default=DEFAULT_PAYMENT_STATUS_CACHE_TTL_SECONDS,
            ),
        )
        or DEFAULT_PAYMENT_STATUS_CACHE_TTL_SECONDS,
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
        self._subscription_cache: dict[str, list[dict[str, Any]] | None] = {}

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
        assigned_features = self.database.list_assigned_features(email)
        feature_states: list[dict[str, Any]] = []
        payment_summary: dict[str, Any] | None = None

        for feature in assigned_features:
            feature_state = self._build_feature_state(
                email,
                feature,
                refresh_payment=self._should_refresh_feature_payment(email, feature),
            )
            feature_states.append(feature_state)
            if payment_summary is None and bool(feature_state.get("billing", {}).get("required")):
                payment_summary = feature_state.get("paymentStatus")

        return {
            "features": feature_states,
            "paymentStatus": payment_summary or self._default_payment_status(),
        }

    def save_feature_config(
        self,
        email: str,
        *,
        feature_id: str,
        prompt: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        feature = self._require_assigned_feature(email, feature_id)
        if feature is None:
            return {
                "ok": False,
                "error": "feature_not_available",
                "message": "This tool is not available for this account.",
            }

        normalized_feature_id = normalize_text(feature.get("featureId"))
        assignment = self.database.get_feature_assignment(email, normalized_feature_id) or {}
        existing_metadata = assignment.get("metadata") if isinstance(assignment.get("metadata"), dict) else {}

        prompt_payload = prompt if isinstance(prompt, dict) else (
            existing_metadata.get("prompt") if isinstance(existing_metadata.get("prompt"), dict) else {}
        )
        settings_payload = settings if isinstance(settings, dict) else (
            existing_metadata.get("settings") if isinstance(existing_metadata.get("settings"), dict) else {}
        )
        if normalized_feature_id == MONITOR_FEATURE_ID:
            settings_payload = normalize_monitor_settings(settings_payload)
        elif normalized_feature_id == REENGAGEMENT_FEATURE_ID:
            settings_payload = normalize_reengagement_settings(settings_payload)
        elif normalized_feature_id == WHATSAPP_REPLY_ASSISTANT_FEATURE_ID:
            had_delivery_setting = any(
                key in settings_payload
                for key in ("deliveryChannels", "delivery_channels", "deliveryChannel", "delivery_channel")
            )
            settings_payload = {
                **settings_payload,
                **normalize_whatsapp_tool_delivery_settings(settings_payload),
            }
            if not had_delivery_setting:
                settings_payload["deliveryChannels"] = ["portal"]

        metadata_payload = {
            **existing_metadata,
            "prompt": prompt_payload,
            "settings": settings_payload,
        }
        if normalized_feature_id in {"scheduled-web-monitor-notifier", REENGAGEMENT_FEATURE_ID}:
            metadata_payload["settingsSavedAt"] = now_iso()

        self.database.save_feature_assignment_metadata(
            email,
            normalized_feature_id,
            metadata=metadata_payload,
        )
        updated_feature = self._require_assigned_feature(email, normalized_feature_id) or feature
        feature_state = self._build_feature_state(email, updated_feature, refresh_payment=False)
        return {
            "ok": True,
            "message": "Tool settings saved.",
            "feature": feature_state,
            "setupStatus": feature_state.get("setupStatus", {}),
            "paymentStatus": feature_state.get("paymentStatus", self._default_payment_status()),
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
        del feature_name, channel
        feature = self._require_assigned_feature(email, feature_id)
        if feature is None:
            return {
                "ok": False,
                "error": "feature_not_available",
                "message": "This tool is not available for this account.",
            }

        feature_name_value = normalize_text(feature.get("name"))
        channel_value = normalize_text(feature.get("channel"))
        feature_id_value = normalize_text(feature.get("featureId"))

        self.database.record_feature_activation_event(
            email,
            feature_id=feature_id_value,
            feature_name=feature_name_value,
            event_name="activation_requested",
            outcome="started",
            metadata={"channel": channel_value},
        )

        setup_status = self._resolve_setup_status(email, feature=feature)
        if not setup_status["ready"]:
            self.database.record_feature_activation_event(
                email,
                feature_id=feature_id_value,
                feature_name=feature_name_value,
                event_name="activation_blocked",
                outcome="setup_required",
                reason="setup_incomplete",
                metadata=setup_status,
            )
            self.database.set_feature_activation(
                email,
                feature_id=feature_id_value,
                feature_name=feature_name_value,
                is_active=False,
                metadata={"channel": channel_value, "setupRequired": True},
            )
            feature_state = self._build_feature_state(
                email,
                feature,
                refresh_payment=False,
                setup_status=setup_status,
            )
            return {
                "ok": False,
                "error": "setup_required",
                "message": setup_status["message"],
                "feature": feature_state,
                "setupStatus": setup_status,
                "paymentStatus": feature_state.get("paymentStatus", self._default_payment_status()),
            }

        payment_status = self._resolve_payment_status(
            email,
            feature=feature,
            refresh_remote=True,
            public_base_url=public_base_url,
        )
        if not payment_status["isEntitled"]:
            self.database.record_feature_activation_event(
                email,
                feature_id=feature_id_value,
                feature_name=feature_name_value,
                event_name="activation_blocked",
                outcome="payment_required",
                reason=normalize_text(payment_status.get("entitlementStatus")) or "not_entitled",
                metadata=payment_status,
            )
            self.database.set_feature_activation(
                email,
                feature_id=feature_id_value,
                feature_name=feature_name_value,
                is_active=False,
                metadata={
                    "channel": channel_value,
                    "paymentRequired": True,
                    "checkoutUrl": payment_status.get("checkoutUrl", ""),
                },
            )
            feature_state = self._build_feature_state(
                email,
                feature,
                refresh_payment=False,
                setup_status=setup_status,
                payment_status=payment_status,
            )
            return {
                "ok": False,
                "error": "payment_required",
                "message": payment_status["message"],
                "feature": feature_state,
                "paymentStatus": payment_status,
                "setupStatus": setup_status,
            }

        self.database.set_feature_activation(
            email,
            feature_id=feature_id_value,
            feature_name=feature_name_value,
            is_active=True,
            metadata={
                "channel": channel_value,
                "billingProvider": payment_status.get("provider", ""),
                "entitlementStatus": payment_status.get("entitlementStatus", ""),
                "subscriptionStatus": payment_status.get("subscriptionStatus", ""),
            },
        )
        self.database.record_feature_activation_event(
            email,
            feature_id=feature_id_value,
            feature_name=feature_name_value,
            event_name="activation_changed",
            outcome="activated",
            metadata={
                "channel": channel_value,
                "provider": payment_status.get("provider", ""),
                "entitlementStatus": payment_status.get("entitlementStatus", ""),
                "subscriptionStatus": payment_status.get("subscriptionStatus", ""),
            },
        )
        feature_state = self._build_feature_state(
            email,
            feature,
            refresh_payment=False,
            setup_status=setup_status,
            payment_status=payment_status,
        )
        return {
            "ok": True,
            "message": "Tool activated.",
            "feature": feature_state,
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
        del feature_name, channel
        feature = self._require_assigned_feature(email, feature_id)
        if feature is None:
            return {
                "ok": False,
                "error": "feature_not_available",
                "message": "This tool is not available for this account.",
            }

        feature_name_value = normalize_text(feature.get("name"))
        channel_value = normalize_text(feature.get("channel"))
        feature_id_value = normalize_text(feature.get("featureId"))
        self.database.set_feature_activation(
            email,
            feature_id=feature_id_value,
            feature_name=feature_name_value,
            is_active=False,
            metadata={"channel": channel_value},
        )
        self.database.record_feature_activation_event(
            email,
            feature_id=feature_id_value,
            feature_name=feature_name_value,
            event_name="activation_changed",
            outcome="deactivated",
            metadata={"channel": channel_value},
        )
        feature_state = self._build_feature_state(email, feature, refresh_payment=False)
        return {
            "ok": True,
            "message": "Tool turned off.",
            "feature": feature_state,
            "paymentStatus": feature_state.get("paymentStatus", self._default_payment_status()),
        }

    def _require_assigned_feature(self, email: str, feature_id: str) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            return None
        return self.database.get_assigned_feature(email, normalized_feature_id)

    def _build_feature_state(
        self,
        email: str,
        feature: dict[str, Any],
        *,
        refresh_payment: bool,
        public_base_url: str = "",
        setup_status: dict[str, Any] | None = None,
        payment_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        feature_id = normalize_text(feature.get("featureId"))
        activation = self.database.get_feature_activation(email, feature_id) or {}
        assignment = feature.get("assignment") if isinstance(feature.get("assignment"), dict) else {}
        assignment_metadata = assignment.get("metadata") if isinstance(assignment.get("metadata"), dict) else {}
        saved_prompt = assignment_metadata.get("prompt") if isinstance(assignment_metadata.get("prompt"), dict) else {}
        saved_settings = assignment_metadata.get("settings") if isinstance(assignment_metadata.get("settings"), dict) else {}
        resolved_prompt = {
            **(feature.get("prompt") if isinstance(feature.get("prompt"), dict) else {}),
            **saved_prompt,
        }
        resolved_settings = dict(saved_settings) if isinstance(saved_settings, dict) else {}
        if feature_id == MONITOR_FEATURE_ID:
            resolved_settings = normalize_monitor_settings(resolved_settings)
        elif feature_id == REENGAGEMENT_FEATURE_ID:
            resolved_settings = normalize_reengagement_settings(resolved_settings)
        elif feature_id == WHATSAPP_REPLY_ASSISTANT_FEATURE_ID:
            had_delivery_setting = any(
                key in resolved_settings
                for key in ("deliveryChannels", "delivery_channels", "deliveryChannel", "delivery_channel")
            )
            resolved_settings = {
                **resolved_settings,
                **normalize_whatsapp_tool_delivery_settings(resolved_settings),
            }
            if not had_delivery_setting:
                resolved_settings["deliveryChannels"] = ["portal"]
        resolved_setup_status = setup_status or self._resolve_setup_status(email, feature=feature)
        resolved_payment_status = payment_status or self._resolve_payment_status(
            email,
            feature=feature,
            refresh_remote=refresh_payment,
            public_base_url=public_base_url,
        )

        is_active = bool(activation.get("isActive"))
        schedule_state = {}
        if feature_id == MONITOR_FEATURE_ID:
            settings_saved_at = normalize_text(assignment_metadata.get("settingsSavedAt"))
            last_run = self.database.get_latest_feature_monitor_run(
                user_id=int(assignment.get("userId") or activation.get("userId") or 0),
                feature_id=feature_id,
            )
            next_run = resolve_next_monitor_slot(
                now=datetime.now(timezone.utc),
                settings=resolved_settings,
                activated_at=normalize_text(activation.get("activatedAt")),
                settings_saved_at=settings_saved_at,
                last_scheduled_for=normalize_text(last_run.get("scheduledFor")) if last_run else "",
            )
            schedule_state = {
                "settingsSavedAt": settings_saved_at,
                "lastRunAt": normalize_text(last_run.get("scheduledFor")) if last_run else "",
                "lastRunStatus": normalize_text(last_run.get("status")) if last_run else "",
                "nextRunAt": next_run.isoformat() if is_active and next_run else "",
            }
            resolved_setup_status = {
                **resolved_setup_status,
                **schedule_state,
            }
        elif feature_id == REENGAGEMENT_FEATURE_ID:
            settings_saved_at = normalize_text(assignment_metadata.get("settingsSavedAt"))
            last_run = self.database.get_latest_whatsapp_reengagement_run(
                user_id=int(assignment.get("userId") or activation.get("userId") or 0),
                feature_id=feature_id,
            )
            tz = resolve_timezone(normalize_text(resolved_settings.get("scheduleTimezone")))
            next_run = resolve_next_reengagement_slot(
                now=datetime.now(timezone.utc),
                settings=resolved_settings,
                tz=tz,
            )
            schedule_state = {
                "settingsSavedAt": settings_saved_at,
                "lastRunAt": normalize_text(last_run.get("scheduledFor")) if last_run else "",
                "lastRunStatus": normalize_text(last_run.get("status")) if last_run else "",
                "nextRunAt": next_run.isoformat() if is_active and next_run else "",
            }
            resolved_setup_status = {
                **resolved_setup_status,
                **schedule_state,
            }
        setup_complete = bool(
            is_active
            or not resolved_setup_status.get("required")
            or resolved_setup_status.get("ready")
        )

        return {
            "id": feature_id,
            "featureId": feature_id,
            "name": normalize_text(feature.get("name")),
            "featureName": normalize_text(feature.get("name")),
            "description": normalize_text(feature.get("description")),
            "channel": normalize_text(feature.get("channel")),
            "mode": normalize_text(feature.get("mode")),
            "launchUrl": normalize_text(feature.get("launchUrl")),
            "status": "active" if is_active else "non-active",
            "isActive": is_active,
            "activated": is_active,
            "activatedAt": activation.get("activatedAt"),
            "deactivatedAt": activation.get("deactivatedAt"),
            "settingsSavedAt": schedule_state.get("settingsSavedAt", ""),
            "lastRunAt": schedule_state.get("lastRunAt", ""),
            "lastRunStatus": schedule_state.get("lastRunStatus", ""),
            "nextRunAt": schedule_state.get("nextRunAt", ""),
            "setupComplete": setup_complete,
            "setupStatus": resolved_setup_status,
            "paymentStatus": resolved_payment_status,
            "billing": {
                "required": bool(feature.get("billingRequired")),
                "provider": normalize_text(feature.get("billingProvider")) or self.config.billing_provider,
                "storeId": normalize_text(feature.get("billingStoreId")),
                "productId": normalize_text(feature.get("billingProductId")),
                "variantId": normalize_text(feature.get("billingVariantId")),
            },
            "requirements": dict(feature.get("requirements") or {}),
            "pricing": dict(feature.get("pricing") or {}),
            "prompt": resolved_prompt,
            "settings": resolved_settings,
            "assignment": dict(assignment or {}),
            "metadata": dict(feature.get("metadata") or {}),
        }

    def _resolve_setup_status(self, email: str, *, feature: dict[str, Any]) -> dict[str, Any]:
        requirements = feature.get("requirements") if isinstance(feature.get("requirements"), dict) else {}
        feature_id = normalize_text(feature.get("featureId"))
        assignment = feature.get("assignment") if isinstance(feature.get("assignment"), dict) else {}
        assignment_metadata = assignment.get("metadata") if isinstance(assignment.get("metadata"), dict) else {}
        settings = assignment_metadata.get("settings") if isinstance(assignment_metadata.get("settings"), dict) else {}
        requires_whatsapp_connection = bool(requirements.get("requiresWhatsAppConnection"))
        requires_monitor_config = bool(requirements.get("requiresScheduledMonitorConfig"))
        if not requires_whatsapp_connection and not requires_monitor_config:
            return {
                "required": False,
                "ready": True,
                "message": "",
            }

        connection = self.database.get_whatsapp_connection(email) or {}
        access_token_ready = bool(normalize_text(connection.get("accessToken")))
        ready = bool(
            normalize_text(connection.get("businessAccountId"))
            and normalize_text(connection.get("phoneNumberId"))
            and normalize_text(connection.get("ownerWaId"))
            and normalize_text(connection.get("connectionStatus")) == "connected"
            and access_token_ready
        )
        if feature_id == MONITOR_FEATURE_ID or requires_monitor_config:
            return build_monitor_setup_status(
                settings,
                user_email=email,
                whatsapp_connection=connection,
            )

        return {
            "required": True,
            "ready": ready,
            "requirementKey": "requiresWhatsAppConnection",
            "connectionStatus": normalize_text(connection.get("connectionStatus")) or "not_connected",
            "message": "" if ready else "Finish WhatsApp setup before activating this tool.",
        }

    def _should_refresh_feature_payment(self, email: str, feature: dict[str, Any]) -> bool:
        if not bool(feature.get("billingRequired")):
            return False
        if normalize_text(feature.get("billingProvider")) != "lemon_squeezy":
            return False
        if self.lemon_squeezy_client is None:
            return False

        entitlement = self.database.get_feature_entitlement(email, normalize_text(feature.get("featureId"))) or {}
        if self._is_stale_record(entitlement):
            return True
        if self._is_entitled_record(entitlement):
            return False
        return bool(normalize_text(entitlement.get("checkoutUrl"))) or not entitlement

    def _resolve_payment_status(
        self,
        email: str,
        *,
        feature: dict[str, Any],
        refresh_remote: bool,
        public_base_url: str = "",
    ) -> dict[str, Any]:
        if not bool(feature.get("billingRequired")):
            return self._default_payment_status(feature=feature, entitled=True, not_required=True)

        feature_id = normalize_text(feature.get("featureId"))
        stored = self.database.get_feature_entitlement(email, feature_id) or {}
        if not refresh_remote:
            return self._format_payment_status(feature, stored, checkout_required=not self._is_entitled_record(stored))

        resolved = dict(stored)
        if normalize_text(feature.get("billingProvider")) == "lemon_squeezy" and self.lemon_squeezy_client is not None:
            remote = self._refresh_feature_entitlement_from_lemon_squeezy(email, feature)
            if remote:
                resolved = remote

        if self._is_entitled_record(resolved):
            return self._format_payment_status(feature, resolved, checkout_required=False)

        checkout_url = normalize_text(resolved.get("checkoutUrl"))
        if not checkout_url:
            checkout_url = self._create_checkout_url(
                email,
                feature=feature,
                public_base_url=public_base_url,
            )
            if checkout_url:
                resolved = self.database.save_feature_entitlement(
                    email,
                    feature_id=feature_id,
                    provider=normalize_text(feature.get("billingProvider")) or self.config.billing_provider,
                    external_customer_id=normalize_text(resolved.get("externalCustomerId")),
                    external_subscription_id=normalize_text(resolved.get("externalSubscriptionId")),
                    external_subscription_item_id=normalize_text(resolved.get("externalSubscriptionItemId")),
                    entitlement_status=normalize_text(resolved.get("entitlementStatus")),
                    product_id=normalize_text(resolved.get("productId")) or normalize_text(feature.get("billingProductId")),
                    variant_id=normalize_text(resolved.get("variantId")) or normalize_text(feature.get("billingVariantId")),
                    checkout_url=checkout_url,
                    customer_portal_url=normalize_text(resolved.get("customerPortalUrl")),
                    metadata={
                        **(resolved.get("metadata") if isinstance(resolved.get("metadata"), dict) else {}),
                        "lastCheckoutFeatureId": feature_id,
                        "lastCheckoutFeatureName": normalize_text(feature.get("name")),
                    },
                )

        return self._format_payment_status(feature, resolved, checkout_required=True)

    def _list_remote_subscriptions(self, email: str) -> list[dict[str, Any]] | None:
        normalized_email = normalize_text(email).lower()
        if normalized_email in self._subscription_cache:
            return self._subscription_cache[normalized_email]

        try:
            response = self.lemon_squeezy_client.list_subscriptions(user_email=normalized_email, page_size=50)
        except LemonSqueezyRequestError:
            self._subscription_cache[normalized_email] = None
            return None

        items = response.get("items") if isinstance(response, dict) else []
        subscriptions = items if isinstance(items, list) else []
        self._subscription_cache[normalized_email] = subscriptions
        self._sync_account_billing_customer(normalized_email, subscriptions)
        return subscriptions

    def _sync_account_billing_customer(self, email: str, subscriptions: list[dict[str, Any]]) -> None:
        existing = self.database.get_billing_customer(email) or {}
        existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}

        selected = None
        for subscription in subscriptions:
            if normalize_text(subscription.get("status")) in ACTIVE_SUBSCRIPTION_STATUSES:
                selected = subscription
                break
        if selected is None and subscriptions:
            selected = subscriptions[0]

        if selected is None:
            self.database.save_billing_customer(
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
            return

        urls = selected.get("urls") if isinstance(selected.get("urls"), dict) else {}
        first_item = selected.get("first_subscription_item") if isinstance(selected.get("first_subscription_item"), dict) else {}
        self.database.save_billing_customer(
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

    def _refresh_feature_entitlement_from_lemon_squeezy(self, email: str, feature: dict[str, Any]) -> dict[str, Any]:
        feature_id = normalize_text(feature.get("featureId"))
        existing = self.database.get_feature_entitlement(email, feature_id) or {}
        existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
        subscriptions = self._list_remote_subscriptions(email)
        if subscriptions is None:
            return existing

        matching_subscriptions = self._filter_subscriptions_for_feature(subscriptions, feature)
        selected = None
        for subscription in matching_subscriptions:
            if normalize_text(subscription.get("status")) in ACTIVE_SUBSCRIPTION_STATUSES:
                selected = subscription
                break
        if selected is None and matching_subscriptions:
            selected = matching_subscriptions[0]

        has_any_active_subscription = any(
            normalize_text(subscription.get("status")) in ACTIVE_SUBSCRIPTION_STATUSES
            for subscription in subscriptions
        )

        if selected is None:
            return self.database.save_feature_entitlement(
                email,
                feature_id=feature_id,
                provider=normalize_text(feature.get("billingProvider")) or self.config.billing_provider,
                external_customer_id=normalize_text(existing.get("externalCustomerId")),
                product_id=normalize_text(feature.get("billingProductId")) or normalize_text(existing.get("productId")),
                variant_id=normalize_text(feature.get("billingVariantId")) or normalize_text(existing.get("variantId")),
                entitlement_status="upgrade_required" if has_any_active_subscription else "",
                checkout_url=normalize_text(existing.get("checkoutUrl")),
                customer_portal_url=normalize_text(existing.get("customerPortalUrl")),
                metadata={
                    **existing_metadata,
                    "source": "lemonsqueezy_api",
                    "hasAnyActiveSubscription": has_any_active_subscription,
                },
            )

        urls = selected.get("urls") if isinstance(selected.get("urls"), dict) else {}
        first_item = selected.get("first_subscription_item") if isinstance(selected.get("first_subscription_item"), dict) else {}
        entitlement_status = normalize_text(selected.get("status"))
        return self.database.save_feature_entitlement(
            email,
            feature_id=feature_id,
            provider=normalize_text(feature.get("billingProvider")) or self.config.billing_provider,
            external_customer_id=normalize_text(selected.get("customer_id")),
            external_subscription_id=normalize_text(selected.get("id")),
            external_subscription_item_id=normalize_text(first_item.get("id")),
            entitlement_status=entitlement_status,
            product_id=normalize_text(selected.get("product_id")) or normalize_text(feature.get("billingProductId")),
            variant_id=normalize_text(selected.get("variant_id")) or normalize_text(feature.get("billingVariantId")),
            checkout_url=normalize_text(existing.get("checkoutUrl")),
            customer_portal_url=normalize_text(urls.get("customer_portal")) or normalize_text(existing.get("customerPortalUrl")),
            metadata={
                **existing_metadata,
                "source": "lemonsqueezy_api",
                "hasAnyActiveSubscription": has_any_active_subscription,
                "userEmail": normalize_text(selected.get("user_email")),
                "statusFormatted": normalize_text(selected.get("status_formatted")),
                "renewsAt": normalize_text(selected.get("renews_at")),
            },
        )

    def _filter_subscriptions_for_feature(
        self,
        subscriptions: list[dict[str, Any]],
        feature: dict[str, Any],
    ) -> list[dict[str, Any]]:
        billing_variant_id = normalize_text(feature.get("billingVariantId"))
        billing_product_id = normalize_text(feature.get("billingProductId"))

        if billing_variant_id:
            return [
                subscription
                for subscription in subscriptions
                if normalize_text(subscription.get("variant_id")) == billing_variant_id
            ]
        if billing_product_id:
            return [
                subscription
                for subscription in subscriptions
                if normalize_text(subscription.get("product_id")) == billing_product_id
            ]
        return list(subscriptions)

    def _create_checkout_url(
        self,
        email: str,
        *,
        feature: dict[str, Any],
        public_base_url: str,
    ) -> str:
        if normalize_text(feature.get("billingProvider")) != "lemon_squeezy" or self.lemon_squeezy_client is None:
            return ""

        store_id = normalize_text(feature.get("billingStoreId")) or self.config.checkout_store_id
        variant_id = normalize_text(feature.get("billingVariantId")) or self.config.checkout_variant_id
        if not variant_id:
            return ""

        redirect_url = normalize_text(self.config.checkout_redirect_url)
        if not redirect_url and normalize_text(public_base_url):
            redirect_url = f"{normalize_text(public_base_url).rstrip('/')}/portal/#features"

        try:
            checkout = self.lemon_squeezy_client.create_checkout(
                store_id=store_id,
                variant_id=variant_id,
                product_options={"redirect_url": redirect_url} if redirect_url else None,
                checkout_options={
                    "button_color": self.config.checkout_button_color,
                    "locale": self.config.checkout_locale,
                },
                checkout_data={
                    "email": normalize_text(email),
                    "custom": {
                        "portal_email": normalize_text(email),
                        "feature_id": normalize_text(feature.get("featureId")),
                        "feature_name": normalize_text(feature.get("name")),
                    },
                },
                test_mode=self.config.test_mode,
            )
        except LemonSqueezyRequestError:
            return ""

        return normalize_text(checkout.get("url"))

    def _is_entitled_record(self, record: dict[str, Any] | None) -> bool:
        payload = record if isinstance(record, dict) else {}
        return normalize_text(payload.get("entitlementStatus")) in ACTIVE_SUBSCRIPTION_STATUSES

    def _is_stale_record(self, record: dict[str, Any] | None) -> bool:
        payload = record if isinstance(record, dict) else {}
        moment = parse_datetime(payload.get("lastCheckedAt"))
        if moment is None:
            return True
        age_seconds = (datetime.now(timezone.utc) - moment).total_seconds()
        return age_seconds >= float(self.config.payment_status_cache_ttl_seconds)

    def _default_payment_status(
        self,
        *,
        feature: dict[str, Any] | None = None,
        entitled: bool = False,
        not_required: bool = False,
    ) -> dict[str, Any]:
        provider = normalize_text(feature.get("billingProvider")) if isinstance(feature, dict) else ""
        feature_id = normalize_text(feature.get("featureId")) if isinstance(feature, dict) else ""
        billing_required = bool(feature.get("billingRequired")) if isinstance(feature, dict) else False
        message = ""
        if not_required:
            message = "Payment is not required for this tool."
        elif entitled:
            message = "Payment is active for this tool."

        return {
            "featureId": feature_id,
            "provider": provider or self.config.billing_provider,
            "billingRequired": billing_required,
            "isPayingCustomer": entitled,
            "isEntitled": entitled,
            "subscriptionStatus": "not_required" if not_required else "",
            "entitlementStatus": "not_required" if not_required else "",
            "checkoutRequired": False,
            "checkoutUrl": "",
            "customerPortalUrl": "",
            "hasAnyActiveSubscription": False,
            "message": message,
        }

    def _format_payment_status(
        self,
        feature: dict[str, Any],
        record: dict[str, Any] | None,
        *,
        checkout_required: bool,
    ) -> dict[str, Any]:
        payload = record if isinstance(record, dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        is_entitled = self._is_entitled_record(payload)
        checkout_url = normalize_text(payload.get("checkoutUrl"))
        has_any_active_subscription = bool(metadata.get("hasAnyActiveSubscription"))
        billing_required = bool(feature.get("billingRequired"))

        if not billing_required:
            return self._default_payment_status(feature=feature, entitled=True, not_required=True)

        if is_entitled:
            message = "Payment is active for this tool."
        elif has_any_active_subscription:
            message = "Your current plan does not unlock this tool yet."
        elif checkout_url:
            message = "Add your card details before activating this tool."
        else:
            message = "Payment is required before activating this tool."

        entitlement_status = normalize_text(payload.get("entitlementStatus"))
        return {
            "featureId": normalize_text(feature.get("featureId")),
            "provider": normalize_text(payload.get("provider")) or normalize_text(feature.get("billingProvider")) or self.config.billing_provider,
            "billingRequired": billing_required,
            "isPayingCustomer": is_entitled,
            "isEntitled": is_entitled,
            "subscriptionStatus": entitlement_status,
            "entitlementStatus": entitlement_status,
            "checkoutRequired": bool(checkout_required and billing_required and not is_entitled),
            "checkoutUrl": checkout_url,
            "customerPortalUrl": normalize_text(payload.get("customerPortalUrl")),
            "hasAnyActiveSubscription": has_any_active_subscription,
            "message": message,
        }
