"""How a family pays to keep the assistant once the trial is over.

A family account has no email, so the payment cannot be matched to the
account by the address the buyer types at checkout. Instead the checkout is
made for one account and carries its id, and every subscription event Lemon
Squeezy sends back carries that id again. Matching by id means a parent can
pay with whatever email they like, and a partner can pay for the family.

The link the assistant sends is short and stable - /pay/<code> - and the
checkout itself is made when it is opened, not when the link is written:
Lemon Squeezy checkouts can expire, and a link sent on day ten should still
work on day fifteen. The code is signed rather than stored, so there is no
table of payment links to keep, and it can only ever pay for its own account.

What counts as paying is decided here once, for the trial gate and the admin
view alike. A cancelled subscription keeps the account running until the
month already paid for is over, and a card that failed is given the days
Lemon Squeezy spends retrying it before anything is switched off.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from packages.infrastructure.lemon_squeezy_api import LemonSqueezyClient
from packages.infrastructure.lemon_squeezy_api import LemonSqueezyWebhookEvent
from packages.infrastructure.lemon_squeezy_api import load_lemon_squeezy_config


BILLING_PROVIDER = "lemon_squeezy"
PAY_PAGE_PREFIX = "/pay/"

# Lemon Squeezy's subscription statuses. "past_due" is a renewal whose card
# failed and is being retried; the family keeps the assistant meanwhile.
PAYING_STATUSES = frozenset({"active", "on_trial", "past_due"})
# Cancelled, but paid until ends_at.
PAID_UNTIL_END_STATUSES = frozenset({"cancelled"})

# The events that describe a subscription. Payment events describe an
# invoice instead, and each one is followed by a subscription_updated, so
# they carry nothing this needs.
SUBSCRIPTION_EVENTS = frozenset({
    "subscription_created",
    "subscription_updated",
    "subscription_cancelled",
    "subscription_resumed",
    "subscription_expired",
    "subscription_paused",
    "subscription_unpaused",
})

_CODE_SIGNATURE_LENGTH = 10


@dataclass(frozen=True)
class FamilyBillingConfig:
    variant_id: str = ""
    store_id: str = ""
    price_label: str = ""
    test_mode: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.variant_id and self.store_id)


def load_family_billing_config() -> FamilyBillingConfig:
    lemon = load_lemon_squeezy_config()
    return FamilyBillingConfig(
        variant_id=str(os.getenv("LEMON_SQUEEZY_VARIANT_ID") or "").strip(),
        store_id=lemon.store_id,
        # What the assistant may say the price is, as the person reads it
        # ("$4.90 a month"). Kept beside the variant so the two are changed
        # together; empty means the assistant does not name a price.
        price_label=str(os.getenv("ASSISTYCA_PRICE_LABEL") or "").strip(),
        test_mode=lemon.test_mode,
    )


def _signature(user_id: int, secret: bytes) -> str:
    digest = hmac.new(secret, f"pay:{int(user_id)}".encode("ascii"), hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").lower()[:_CODE_SIGNATURE_LENGTH]


def _base36(number: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    number = int(number)
    if number <= 0:
        return "0"
    out = ""
    while number:
        number, rest = divmod(number, 36)
        out = alphabet[rest] + out
    return out


def pay_code(user_id: int, secret: bytes) -> str:
    """The short code in an account's payment link: the account, and a
    signature that only the server can make for it."""

    if int(user_id) <= 0 or not secret:
        return ""
    return f"{_base36(user_id)}{_signature(user_id, secret)}"


def user_id_from_pay_code(code: str, secret: bytes) -> int:
    """The account a payment link was made for, or 0 when the code was not
    made by this server."""

    clean = str(code or "").strip().lower()
    if not secret or len(clean) <= _CODE_SIGNATURE_LENGTH:
        return 0
    head, signature = clean[:-_CODE_SIGNATURE_LENGTH], clean[-_CODE_SIGNATURE_LENGTH:]
    try:
        user_id = int(head, 36)
    except ValueError:
        return 0
    if user_id <= 0 or not hmac.compare_digest(signature, _signature(user_id, secret)):
        return 0
    return user_id


def create_family_checkout_url(
    client: LemonSqueezyClient,
    config: FamilyBillingConfig,
    *,
    user_id: int,
    redirect_url: str,
) -> str:
    """A fresh checkout for one account. The account id rides in the
    checkout's custom data and comes back on every subscription event."""

    checkout = client.create_checkout(
        variant_id=config.variant_id,
        store_id=config.store_id,
        product_options={"redirect_url": redirect_url} if redirect_url else None,
        checkout_data={"custom": {"user_id": str(int(user_id))}},
        test_mode=config.test_mode,
    )
    return str(checkout.get("url") or "").strip()


def fresh_customer_portal_url(client: LemonSqueezyClient, subscription_id: str) -> str:
    """Where a paying family manages or cancels their subscription, asked of
    Lemon Squeezy now: the address it gives is signed for about a day, so
    the one a webhook brought last month has likely run out."""

    subscription = client.retrieve_subscription(subscription_id)
    urls = subscription.get("urls") if isinstance(subscription.get("urls"), dict) else {}
    return str(urls.get("customer_portal") or "").strip()


def _parse_moment(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def subscription_is_paying(customer: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """Whether a billing record keeps the account running today."""

    record = customer or {}
    status = str(record.get("subscriptionStatus") or "").strip().lower()
    if status in PAYING_STATUSES:
        return True
    if status in PAID_UNTIL_END_STATUSES:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        ends_at = _parse_moment(metadata.get("endsAt"))
        return bool(ends_at and ends_at > (now or datetime.now(timezone.utc)))
    return False


def account_subscription(subscriptions: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any] | None:
    """The one subscription that stands for an account when it has several -
    both parents paid, say. One that is running wins over one cancelled and
    running out, which wins over one that has ended; the latest change
    breaks a tie. So the account pays while any of them does, and the pay
    link manages a subscription that is still being charged."""

    def rank(record: dict[str, Any]) -> int:
        status = str(record.get("subscriptionStatus") or "").strip().lower()
        if status in PAYING_STATUSES:
            return 2
        return 1 if subscription_is_paying(record, now=now) else 0

    best: dict[str, Any] | None = None
    for record in subscriptions or ():
        # Listed latest change first, so the first of a rank is kept.
        if best is None or rank(record) > rank(best):
            best = record
    return best


def subscription_record_from_event(event: LemonSqueezyWebhookEvent) -> dict[str, Any] | None:
    """What a subscription event says about the account it was bought for,
    or None when the event is not about a subscription or names no account."""

    if event.event_name not in SUBSCRIPTION_EVENTS or event.resource_type != "subscriptions":
        return None
    custom = event.meta.get("custom_data") if isinstance(event.meta.get("custom_data"), dict) else {}
    try:
        user_id = int(str(custom.get("user_id") or "0").strip())
    except ValueError:
        user_id = 0
    if user_id <= 0:
        return None
    attributes = event.attributes
    urls = attributes.get("urls") if isinstance(attributes.get("urls"), dict) else {}
    first_item = attributes.get("first_subscription_item")
    first_item = first_item if isinstance(first_item, dict) else {}
    return {
        "userId": user_id,
        "provider": BILLING_PROVIDER,
        "externalCustomerId": str(attributes.get("customer_id") or ""),
        "externalSubscriptionId": event.resource_id,
        "externalSubscriptionItemId": str(first_item.get("id") or ""),
        "subscriptionStatus": str(attributes.get("status") or "").strip().lower(),
        "productId": str(attributes.get("product_id") or ""),
        "variantId": str(attributes.get("variant_id") or ""),
        "customerPortalUrl": str(urls.get("customer_portal") or ""),
        "metadata": {
            "source": "lemonsqueezy_webhook",
            "event": event.event_name,
            "statusFormatted": str(attributes.get("status_formatted") or ""),
            "renewsAt": str(attributes.get("renews_at") or ""),
            "endsAt": str(attributes.get("ends_at") or ""),
            "testMode": bool(attributes.get("test_mode")),
        },
    }


__all__ = [
    "BILLING_PROVIDER",
    "account_subscription",
    "FamilyBillingConfig",
    "PAY_PAGE_PREFIX",
    "PAYING_STATUSES",
    "SUBSCRIPTION_EVENTS",
    "create_family_checkout_url",
    "fresh_customer_portal_url",
    "load_family_billing_config",
    "pay_code",
    "subscription_is_paying",
    "subscription_record_from_event",
    "user_id_from_pay_code",
]
