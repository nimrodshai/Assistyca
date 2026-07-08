"""Shared helpers for Lemon Squeezy billing flows.

This module keeps Lemon Squeezy request construction, webhook verification,
and usage-based billing helpers in one reusable place for shared services.
It is intentionally dependency-light and uses the standard library only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


DEFAULT_LEMON_SQUEEZY_API_BASE = "https://api.lemonsqueezy.com/v1"
DEFAULT_LEMON_SQUEEZY_TIMEOUT_SECONDS = 30.0
JSON_API_CONTENT_TYPE = "application/vnd.api+json"
DEFAULT_USER_AGENT = "Assistyca/1.0 LemonSqueezy"
ALLOWED_USAGE_RECORD_ACTIONS = frozenset({"increment", "set"})


class LemonSqueezyError(RuntimeError):
    """Base error for Lemon Squeezy gateway failures."""

    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class LemonSqueezyConfigurationError(LemonSqueezyError):
    """Raised when the Lemon Squeezy gateway cannot be configured safely."""


class LemonSqueezyRequestError(LemonSqueezyError):
    """Raised when a Lemon Squeezy API request fails."""

    def __init__(
        self,
        message: str,
        *,
        details: str = "",
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.status_code = status_code
        self.payload = payload if isinstance(payload, dict) else {}


class LemonSqueezySignatureError(LemonSqueezyError):
    """Raised when a Lemon Squeezy webhook signature cannot be verified."""


@dataclass
class LemonSqueezyConfig:
    api_key: str = ""
    store_id: str = ""
    signing_secret: str = ""
    api_base_url: str = DEFAULT_LEMON_SQUEEZY_API_BASE
    timeout_seconds: float = DEFAULT_LEMON_SQUEEZY_TIMEOUT_SECONDS
    test_mode: bool = False
    user_agent: str = DEFAULT_USER_AGENT

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class LemonSqueezyWebhookEvent:
    event_name: str
    resource_id: str
    resource_type: str
    attributes: dict[str, Any]
    relationships: dict[str, Any]
    links: dict[str, Any]
    meta: dict[str, Any]
    payload: dict[str, Any]

    @property
    def resource(self) -> dict[str, Any]:
        flattened = {
            "id": self.resource_id,
            "type": self.resource_type,
            "attributes": dict(self.attributes),
            "relationships": dict(self.relationships),
            "links": dict(self.links),
        }
        flattened.update(self.attributes)
        return flattened


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def safe_positive_int(value: Any) -> int:
    return max(0, safe_int(value))


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_bool(value: Any, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_api_base_url(value: Any) -> str:
    base_url = normalize_text(value) or DEFAULT_LEMON_SQUEEZY_API_BASE
    return base_url.rstrip("/")


def load_lemon_squeezy_config(
    *,
    api_key: str | None = None,
    store_id: str | None = None,
    signing_secret: str | None = None,
    api_base_url: str | None = None,
    timeout_seconds: float | None = None,
    test_mode: bool | None = None,
    user_agent: str | None = None,
) -> LemonSqueezyConfig:
    return LemonSqueezyConfig(
        api_key=normalize_text(api_key if api_key is not None else os.getenv("LEMON_SQUEEZY_API_KEY")),
        store_id=normalize_text(store_id if store_id is not None else os.getenv("LEMON_SQUEEZY_STORE_ID")),
        signing_secret=normalize_text(
            signing_secret if signing_secret is not None else os.getenv("LEMON_SQUEEZY_SIGNING_SECRET")
        ),
        api_base_url=normalize_api_base_url(
            api_base_url if api_base_url is not None else os.getenv("LEMON_SQUEEZY_API_BASE_URL")
        ),
        timeout_seconds=safe_float(
            timeout_seconds if timeout_seconds is not None else os.getenv("LEMON_SQUEEZY_TIMEOUT_SECONDS")
        )
        or DEFAULT_LEMON_SQUEEZY_TIMEOUT_SECONDS,
        test_mode=parse_bool(
            test_mode if test_mode is not None else os.getenv("LEMON_SQUEEZY_TEST_MODE"),
            default=False,
        ),
        user_agent=normalize_text(user_agent if user_agent is not None else os.getenv("LEMON_SQUEEZY_USER_AGENT"))
        or DEFAULT_USER_AGENT,
    )


def extract_error_message(payload: dict[str, Any], *, status_code: int | None = None) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list):
        messages: list[str] = []
        for raw_error in errors:
            if not isinstance(raw_error, dict):
                continue
            detail = normalize_text(raw_error.get("detail"))
            title = normalize_text(raw_error.get("title"))
            code = normalize_text(raw_error.get("code"))
            message = detail or title or code
            if message and message not in messages:
                messages.append(message)
        if messages:
            return "; ".join(messages)

    for key in ("message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if status_code in {401, 403}:
        return "Lemon Squeezy rejected the API credentials."
    if status_code == 404:
        return "Lemon Squeezy could not find the requested resource."
    if status_code == 422:
        return "Lemon Squeezy rejected the request payload."
    return ""


def json_api_headers(*, api_key: str, user_agent: str) -> dict[str, str]:
    return {
        "Accept": JSON_API_CONTENT_TYPE,
        "Content-Type": JSON_API_CONTENT_TYPE,
        "Authorization": f"Bearer {api_key}",
        "User-Agent": normalize_text(user_agent) or DEFAULT_USER_AGENT,
    }


def build_relationship(resource_type: str, resource_id: Any) -> dict[str, Any]:
    normalized_id = normalize_text(resource_id)
    if not normalized_id:
        raise ValueError(f"{resource_type.rstrip('s').replace('-', ' ')} ID is required.")

    return {
        "data": {
            "type": resource_type,
            "id": normalized_id,
        }
    }


def flatten_resource_object(resource: Any) -> dict[str, Any]:
    if not isinstance(resource, dict):
        return {}

    attributes = resource.get("attributes")
    attribute_payload = dict(attributes) if isinstance(attributes, dict) else {}
    relationships = resource.get("relationships")
    links = resource.get("links")

    flattened = {
        "id": normalize_text(resource.get("id")),
        "type": normalize_text(resource.get("type")),
        "attributes": attribute_payload,
        "relationships": dict(relationships) if isinstance(relationships, dict) else {},
        "links": dict(links) if isinstance(links, dict) else {},
    }
    flattened.update(attribute_payload)
    return flattened


def extract_single_resource(payload: dict[str, Any]) -> dict[str, Any]:
    resource = flatten_resource_object(payload.get("data"))
    if not resource:
        raise LemonSqueezyRequestError(
            "Lemon Squeezy returned an unexpected response.",
            details=json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
    return resource


def extract_resource_list(payload: dict[str, Any]) -> dict[str, Any]:
    raw_items = payload.get("data")
    items = [flatten_resource_object(item) for item in raw_items] if isinstance(raw_items, list) else []
    meta = payload.get("meta")
    links = payload.get("links")
    return {
        "items": items,
        "meta": dict(meta) if isinstance(meta, dict) else {},
        "links": dict(links) if isinstance(links, dict) else {},
        "raw": payload,
    }


def normalize_webhook_signature(signature: str) -> str:
    return normalize_text(signature).lower()


def build_webhook_signature(raw_body: bytes | str, signing_secret: str) -> str:
    secret = normalize_text(signing_secret)
    if not secret:
        raise ValueError("Lemon Squeezy signing secret is required.")

    body = raw_body if isinstance(raw_body, bytes) else str(raw_body or "").encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return digest.lower()


def verify_webhook_signature(*, raw_body: bytes | str, signature: str, signing_secret: str) -> bool:
    expected_signature = build_webhook_signature(raw_body, signing_secret)
    provided_signature = normalize_webhook_signature(signature)
    return bool(provided_signature) and hmac.compare_digest(expected_signature, provided_signature)


def require_valid_webhook_signature(*, raw_body: bytes | str, signature: str, signing_secret: str) -> None:
    if not normalize_text(signing_secret):
        raise LemonSqueezySignatureError("Lemon Squeezy signing secret is not configured.")
    if not normalize_text(signature):
        raise LemonSqueezySignatureError("Lemon Squeezy webhook signature is missing.")
    if not verify_webhook_signature(raw_body=raw_body, signature=signature, signing_secret=signing_secret):
        raise LemonSqueezySignatureError("Lemon Squeezy webhook signature is invalid.")


def parse_webhook_event(
    raw_body: bytes | str,
    *,
    signature: str = "",
    signing_secret: str = "",
) -> LemonSqueezyWebhookEvent:
    if signature or signing_secret:
        require_valid_webhook_signature(
            raw_body=raw_body,
            signature=signature,
            signing_secret=signing_secret,
        )

    body = raw_body if isinstance(raw_body, bytes) else str(raw_body or "").encode("utf-8")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LemonSqueezyRequestError("Lemon Squeezy webhook payload is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise LemonSqueezyRequestError("Lemon Squeezy webhook payload must be a JSON object.")

    meta = payload.get("meta")
    meta_payload = dict(meta) if isinstance(meta, dict) else {}
    resource = payload.get("data")
    flattened = flatten_resource_object(resource)

    return LemonSqueezyWebhookEvent(
        event_name=normalize_text(meta_payload.get("event_name")),
        resource_id=normalize_text(flattened.get("id")),
        resource_type=normalize_text(flattened.get("type")),
        attributes=dict(flattened.get("attributes") or {}),
        relationships=dict(flattened.get("relationships") or {}),
        links=dict(flattened.get("links") or {}),
        meta=meta_payload,
        payload=payload,
    )


class LemonSqueezyClient:
    """Small JSON:API client for hosted checkout and subscription workflows."""

    def __init__(self, config: LemonSqueezyConfig) -> None:
        if not isinstance(config, LemonSqueezyConfig):
            raise TypeError("Lemon Squeezy config must be a LemonSqueezyConfig instance.")
        if not config.api_key:
            raise LemonSqueezyConfigurationError("Lemon Squeezy API key is required.")
        self.config = config

    @classmethod
    def from_env(cls, **overrides: Any) -> LemonSqueezyClient:
        return cls(load_lemon_squeezy_config(**overrides))

    def create_checkout(
        self,
        *,
        variant_id: str,
        store_id: str = "",
        custom_price: int | None = None,
        product_options: dict[str, Any] | None = None,
        checkout_options: dict[str, Any] | None = None,
        checkout_data: dict[str, Any] | None = None,
        expires_at: str | None = None,
        preview: bool = False,
        test_mode: bool | None = None,
    ) -> dict[str, Any]:
        resolved_store_id = normalize_text(store_id) or self.config.store_id
        resolved_variant_id = normalize_text(variant_id)
        if not resolved_store_id:
            raise LemonSqueezyConfigurationError(
                "Lemon Squeezy store ID is required. Set LEMON_SQUEEZY_STORE_ID or pass store_id."
            )
        if not resolved_variant_id:
            raise ValueError("Lemon Squeezy variant ID is required.")

        attributes: dict[str, Any] = {}
        if custom_price is not None:
            custom_price_value = safe_positive_int(custom_price)
            if custom_price_value <= 0:
                raise ValueError("Lemon Squeezy custom_price must be a positive integer in cents.")
            attributes["custom_price"] = custom_price_value
        if isinstance(product_options, dict) and product_options:
            attributes["product_options"] = product_options
        if isinstance(checkout_options, dict) and checkout_options:
            attributes["checkout_options"] = checkout_options
        if isinstance(checkout_data, dict) and checkout_data:
            attributes["checkout_data"] = checkout_data
        if normalize_text(expires_at):
            attributes["expires_at"] = normalize_text(expires_at)
        if preview:
            attributes["preview"] = True

        resolved_test_mode = self.config.test_mode if test_mode is None else bool(test_mode)
        if resolved_test_mode:
            attributes["test_mode"] = True

        payload = {
            "data": {
                "type": "checkouts",
                "attributes": attributes,
                "relationships": {
                    "store": build_relationship("stores", resolved_store_id),
                    "variant": build_relationship("variants", resolved_variant_id),
                },
            }
        }
        response = self._request("POST", "/checkouts", body=payload)
        return extract_single_resource(response)

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        normalized_subscription_id = normalize_text(subscription_id)
        if not normalized_subscription_id:
            raise ValueError("Lemon Squeezy subscription ID is required.")

        response = self._request("GET", f"/subscriptions/{urllib_parse.quote(normalized_subscription_id, safe='')}")
        return extract_single_resource(response)

    def list_subscriptions(
        self,
        *,
        store_id: str = "",
        order_id: str = "",
        order_item_id: str = "",
        product_id: str = "",
        variant_id: str = "",
        user_email: str = "",
        status: str = "",
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        filters = {
            "store_id": store_id,
            "order_id": order_id,
            "order_item_id": order_item_id,
            "product_id": product_id,
            "variant_id": variant_id,
            "user_email": user_email,
            "status": status,
        }
        for key, value in filters.items():
            normalized_value = normalize_text(value)
            if normalized_value:
                query[f"filter[{key}]"] = normalized_value

        if page is not None:
            page_value = safe_positive_int(page)
            if page_value <= 0:
                raise ValueError("Lemon Squeezy page must be a positive integer.")
            query["page[number]"] = page_value

        if page_size is not None:
            page_size_value = safe_positive_int(page_size)
            if page_size_value <= 0:
                raise ValueError("Lemon Squeezy page_size must be a positive integer.")
            query["page[size]"] = page_size_value

        response = self._request("GET", "/subscriptions", query=query)
        return extract_resource_list(response)

    def create_usage_record(
        self,
        *,
        subscription_item_id: str,
        quantity: int,
        action: str = "increment",
    ) -> dict[str, Any]:
        resolved_subscription_item_id = normalize_text(subscription_item_id)
        if not resolved_subscription_item_id:
            raise ValueError("Lemon Squeezy subscription item ID is required.")

        quantity_value = safe_positive_int(quantity)
        if quantity_value <= 0:
            raise ValueError("Lemon Squeezy usage quantity must be a positive integer.")

        resolved_action = normalize_text(action).lower() or "increment"
        if resolved_action not in ALLOWED_USAGE_RECORD_ACTIONS:
            raise ValueError("Lemon Squeezy usage action must be 'increment' or 'set'.")

        payload = {
            "data": {
                "type": "usage-records",
                "attributes": {
                    "quantity": quantity_value,
                    "action": resolved_action,
                },
                "relationships": {
                    "subscription-item": build_relationship("subscription-items", resolved_subscription_item_id),
                },
            }
        }
        response = self._request("POST", "/usage-records", body=payload)
        return extract_single_resource(response)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        method_value = normalize_text(method).upper() or "GET"
        path_value = path if str(path).startswith("/") else f"/{path}"
        url = f"{self.config.api_base_url}{path_value}"
        if isinstance(query, dict) and query:
            url = f"{url}?{urllib_parse.urlencode(query, doseq=True)}"

        encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib_request.Request(
            url,
            data=encoded_body,
            method=method_value,
            headers=json_api_headers(api_key=self.config.api_key, user_agent=self.config.user_agent),
        )

        try:
            with urllib_request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            payload = parse_response_json(raw_body)
            raise LemonSqueezyRequestError(
                extract_error_message(payload, status_code=exc.code)
                or "Lemon Squeezy could not complete the request.",
                details=raw_body,
                status_code=exc.code,
                payload=payload if payload else None,
            ) from exc
        except urllib_error.URLError as exc:
            reason = normalize_text(getattr(exc, "reason", "")) or "The network request failed."
            raise LemonSqueezyRequestError(
                "Lemon Squeezy did not respond. Check the network connection and try again.",
                details=reason,
            ) from exc

        payload = parse_response_json(raw_body)
        if not payload:
            raise LemonSqueezyRequestError("Lemon Squeezy returned an empty response.", details=raw_body)
        return payload


def parse_response_json(raw_body: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}

