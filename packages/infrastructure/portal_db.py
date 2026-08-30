from __future__ import annotations

import json
import hashlib
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
from decimal import ROUND_HALF_UP
from pathlib import Path
import re
from typing import Any
from typing import Iterable

from packages.infrastructure.feature_catalog import load_default_feature_catalog


DEFAULT_DB_PATH = Path("portal/portal.db")
DEFAULT_CURRENCY = "USD"
DEFAULT_MONTHLY_MINIMUM_CENTS = 5000
DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER = 1.5
DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER = 1.5
BOOTSTRAP_ACTIVE_SUBSCRIPTION_STATUS = "active"
# A claimed row whose worker has not reported back within this window is treated as
# abandoned (crash, redeploy, or killed daemon thread) and returned to the queue.
STALE_CLAIM_SECONDS = 15 * 60
MAX_SCHEDULED_ACTION_ATTEMPTS = 3
VALID_CLIENT_TYPES = ("paying", "demo", "qa")
RAW_CENTS_QUANT = Decimal("0.0001")
USD_QUANT = Decimal("0.01")
DEFAULT_MODEL_PRICE_PROVIDER = "openai"
DEFAULT_MODEL_PRICE_NOTES = (
    "OpenAI standard short-context pricing seeded from "
    "https://developers.openai.com/api/docs/pricing on 2026-07-12."
)
DEFAULT_MODEL_PRICES = (
    {
        "model_name": "gpt-5.5",
        "input_usd_per_1m_tokens": 5.0,
        "output_usd_per_1m_tokens": 30.0,
    },
    {
        "model_name": "gpt-5.4",
        "input_usd_per_1m_tokens": 2.5,
        "output_usd_per_1m_tokens": 15.0,
    },
    {
        "model_name": "gpt-5.4-mini",
        "input_usd_per_1m_tokens": 0.75,
        "output_usd_per_1m_tokens": 4.5,
    },
    {
        "model_name": "gpt-5.4-nano",
        "input_usd_per_1m_tokens": 0.2,
        "output_usd_per_1m_tokens": 1.25,
    },
)
USER_OWNED_TABLES = (
    "notifications",
    "feature_activation_events",
    "feature_activations",
    "feature_entitlements",
    "feature_monitor_notifications",
    "feature_monitor_runs",
    "scheduled_actions",
    "source_actions",
    "platform_connections",
    "feature_assignments",
    "billing_customers",
    "whatsapp_reengagement_notifications",
    "whatsapp_reengagement_runs",
    "whatsapp_conversation_messages",
    "whatsapp_conversations",
    "whatsapp_approval_index",
    "whatsapp_connections",
    "usage_events",
    "user_billing",
)


@dataclass
class BillingPlan:
    currency: str = DEFAULT_CURRENCY
    monthly_minimum_cents: int = DEFAULT_MONTHLY_MINIMUM_CENTS
    input_token_price_multiplier: float = DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER
    output_token_price_multiplier: float = DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER


# Generic app connections intentionally store only encrypted credential
# ciphertext. The encryption key lives outside SQLite in the deployment
# secret manager; this table is never serialized into agent prompts.
#
# Kept out of SCHEMA_SQL so the bootstrap and the multi-mailbox rebuild in
# _widen_platform_connection_uniqueness share one definition.
PLATFORM_CONNECTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS platform_connections (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    auth_type TEXT NOT NULL DEFAULT 'api_token',
    secret_ciphertext TEXT NOT NULL,
    key_version TEXT NOT NULL DEFAULT '1',
    secret_fingerprint TEXT NOT NULL DEFAULT '',
    secret_hint TEXT NOT NULL DEFAULT '',
    connection_status TEXT NOT NULL DEFAULT 'connected',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    account_address TEXT NOT NULL DEFAULT '',
    account_label TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- A user may hold several mailboxes, so uniqueness is per account rather
    -- than per platform. Single-account platforms leave account_address empty,
    -- which keeps their old one-row-per-platform behaviour intact.
    --
    -- The provider is part of that identity because Gmail and Outlook share
    -- the email platform and can report the same address: a personal Microsoft
    -- account may be registered under a Gmail address. Without it, connecting
    -- one provider overwrites the other's mailbox, credential and all.
    UNIQUE(user_id, platform, provider, account_address),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    registered_at TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    client_type TEXT NOT NULL DEFAULT '',
    last_login_at TEXT,
    last_otp_requested_at TEXT,
    last_otp_verified_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_billing (
    user_id INTEGER PRIMARY KEY,
    currency TEXT NOT NULL DEFAULT 'USD',
    monthly_minimum_cents INTEGER NOT NULL DEFAULT 5000,
    input_token_price_multiplier REAL NOT NULL DEFAULT 1.5,
    output_token_price_multiplier REAL NOT NULL DEFAULT 1.5,
    effective_from TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_prices (
    model_name TEXT PRIMARY KEY,
    currency TEXT NOT NULL DEFAULT 'USD',
    input_price_cents_per_1k_tokens REAL NOT NULL DEFAULT 0,
    output_price_cents_per_1k_tokens REAL NOT NULL DEFAULT 0,
    provider TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tool_id TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL,
    billing_month TEXT NOT NULL,
    used_at TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    input_price_cents_per_1k_tokens REAL NOT NULL DEFAULT 0,
    output_price_cents_per_1k_tokens REAL NOT NULL DEFAULT 0,
    input_token_price_multiplier REAL NOT NULL DEFAULT 1.5,
    output_token_price_multiplier REAL NOT NULL DEFAULT 1.5,
    input_charge_cents REAL NOT NULL DEFAULT 0,
    output_charge_cents REAL NOT NULL DEFAULT 0,
    raw_charge_cents REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contact_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    business TEXT NOT NULL DEFAULT '',
    business_summary TEXT NOT NULL DEFAULT '',
    pain_summary TEXT NOT NULL DEFAULT '',
    suggested_tool TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '',
    urgency TEXT NOT NULL DEFAULT 'medium',
    urgency_score INTEGER NOT NULL DEFAULT 50,
    source_page TEXT NOT NULL DEFAULT '',
    request_country TEXT NOT NULL DEFAULT '',
    contact_message TEXT NOT NULL DEFAULT '',
    transcript_json TEXT NOT NULL DEFAULT '[]',
    intake_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS whatsapp_connections (
    user_id INTEGER PRIMARY KEY,
    business_account_id TEXT NOT NULL DEFAULT '',
    phone_number_id TEXT NOT NULL DEFAULT '',
    access_token TEXT NOT NULL DEFAULT '',
    access_token_ciphertext TEXT NOT NULL DEFAULT '',
    access_token_key_version TEXT NOT NULL DEFAULT '1',
    access_token_fingerprint TEXT NOT NULL DEFAULT '',
    owner_wa_id TEXT NOT NULL DEFAULT '',
    display_phone_number TEXT NOT NULL DEFAULT '',
    verified_name TEXT NOT NULL DEFAULT '',
    connection_status TEXT NOT NULL DEFAULT 'not_connected',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    connected_at TEXT,
    last_tested_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS whatsapp_approval_index (
    approval_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    phone_number_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS whatsapp_conversations (
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    sender_name TEXT NOT NULL DEFAULT '',
    sender_wa_id TEXT NOT NULL DEFAULT '',
    last_message_text TEXT NOT NULL DEFAULT '',
    last_message_id TEXT NOT NULL DEFAULT '',
    last_message_direction TEXT NOT NULL DEFAULT '',
    last_message_at TEXT,
    last_inbound_at TEXT,
    last_outbound_at TEXT,
    last_reengagement_notified_at TEXT,
    last_reengagement_notified_for_message_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, conversation_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS whatsapp_conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'inbound',
    message_type TEXT NOT NULL DEFAULT 'text',
    text TEXT NOT NULL DEFAULT '',
    message_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS whatsapp_reengagement_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT NOT NULL,
    conversations_checked INTEGER NOT NULL DEFAULT 0,
    notifications_sent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS whatsapp_reengagement_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    feature_id TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    owner_message_id TEXT NOT NULL DEFAULT '',
    draft_text TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS billing_customers (
    user_id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT '',
    external_customer_id TEXT NOT NULL DEFAULT '',
    external_subscription_id TEXT NOT NULL DEFAULT '',
    external_subscription_item_id TEXT NOT NULL DEFAULT '',
    subscription_status TEXT NOT NULL DEFAULT '',
    product_id TEXT NOT NULL DEFAULT '',
    variant_id TEXT NOT NULL DEFAULT '',
    checkout_url TEXT NOT NULL DEFAULT '',
    customer_portal_url TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS features (
    feature_id TEXT PRIMARY KEY,
    feature_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    launch_url TEXT NOT NULL DEFAULT '',
    billing_required INTEGER NOT NULL DEFAULT 0,
    billing_provider TEXT NOT NULL DEFAULT '',
    billing_store_id TEXT NOT NULL DEFAULT '',
    billing_product_id TEXT NOT NULL DEFAULT '',
    billing_variant_id TEXT NOT NULL DEFAULT '',
    default_assigned INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    prompt_json TEXT NOT NULL DEFAULT '{}',
    pricing_json TEXT NOT NULL DEFAULT '{}',
    requirements_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_assignments (
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL,
    is_assigned INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    assigned_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, feature_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(feature_id) REFERENCES features(feature_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feature_entitlements (
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    external_customer_id TEXT NOT NULL DEFAULT '',
    external_subscription_id TEXT NOT NULL DEFAULT '',
    external_subscription_item_id TEXT NOT NULL DEFAULT '',
    entitlement_status TEXT NOT NULL DEFAULT '',
    product_id TEXT NOT NULL DEFAULT '',
    variant_id TEXT NOT NULL DEFAULT '',
    checkout_url TEXT NOT NULL DEFAULT '',
    customer_portal_url TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, feature_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(feature_id) REFERENCES features(feature_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feature_activations (
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL,
    feature_name TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT,
    deactivated_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, feature_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feature_activation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL DEFAULT '',
    feature_name TEXT NOT NULL DEFAULT '',
    event_name TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feature_monitor_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT NOT NULL,
    findings_count INTEGER NOT NULL DEFAULT 0,
    notifications_sent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feature_monitor_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    feature_id TEXT NOT NULL DEFAULT '',
    item_key TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT NOT NULL,
    delivery_channel TEXT NOT NULL DEFAULT '',
    delivery_target TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    event_date TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    message_text TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'info',
    tone TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    feature_id TEXT NOT NULL DEFAULT '',
    action_id TEXT NOT NULL DEFAULT '',
    result_url TEXT NOT NULL DEFAULT '',
    dedupe_key TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    read_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scheduled_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action_type TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    recipient_ref TEXT NOT NULL DEFAULT '',
    run_at TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    provider_message_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT NOT NULL DEFAULT '',
    claimed_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source_type TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    file_bytes BLOB,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_sha256 TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    interval_minutes INTEGER NOT NULL DEFAULT 1440,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    status TEXT NOT NULL DEFAULT 'active',
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    last_run_status TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    last_http_status INTEGER,
    last_content_type TEXT NOT NULL DEFAULT '',
    last_content_hash TEXT NOT NULL DEFAULT '',
    last_content_size INTEGER NOT NULL DEFAULT 0,
    run_count INTEGER NOT NULL DEFAULT 0,
    claimed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_month ON usage_events(user_id, billing_month, used_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_model ON usage_events(user_id, model_name, used_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_prices_is_active ON model_prices(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_connections_phone_number_id
ON whatsapp_connections(phone_number_id)
WHERE phone_number_id <> '';
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_owner_wa_id
ON whatsapp_connections(owner_wa_id)
WHERE owner_wa_id <> '';
CREATE INDEX IF NOT EXISTS idx_platform_connections_user_status
ON platform_connections(user_id, connection_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_whatsapp_approval_index_user_id
ON whatsapp_approval_index(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_whatsapp_conversations_user_updated
ON whatsapp_conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_whatsapp_conversations_user_last_message
ON whatsapp_conversations(user_id, last_message_at ASC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_conversation_messages_user_message
ON whatsapp_conversation_messages(user_id, message_id)
WHERE message_id <> '';
CREATE INDEX IF NOT EXISTS idx_whatsapp_conversation_messages_thread
ON whatsapp_conversation_messages(user_id, conversation_id, message_at ASC, id ASC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_reengagement_runs_user_schedule
ON whatsapp_reengagement_runs(user_id, feature_id, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_whatsapp_reengagement_notifications_user_thread
ON whatsapp_reengagement_notifications(user_id, conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_customers_provider_status
ON billing_customers(provider, subscription_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_features_active_sort
ON features(is_active, sort_order, feature_name);
CREATE INDEX IF NOT EXISTS idx_source_actions_due
ON source_actions(status, next_run_at ASC);
CREATE INDEX IF NOT EXISTS idx_source_actions_user
ON source_actions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_assignments_user_assigned
ON feature_assignments(user_id, is_assigned, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_entitlements_user_status
ON feature_entitlements(user_id, entitlement_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_activations_user_active
ON feature_activations(user_id, is_active, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_activation_events_user_feature
ON feature_activation_events(user_id, feature_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_monitor_runs_user_schedule
ON feature_monitor_runs(user_id, feature_id, scheduled_for);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_monitor_notifications_user_item
ON feature_monitor_notifications(user_id, feature_id, item_key);
CREATE INDEX IF NOT EXISTS idx_feature_monitor_notifications_user_schedule
ON feature_monitor_notifications(user_id, feature_id, scheduled_for DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
ON notifications(user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
ON notifications(user_id, read_at, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_user_dedupe
ON notifications(user_id, dedupe_key) WHERE dedupe_key <> '';
CREATE INDEX IF NOT EXISTS idx_scheduled_actions_due
ON scheduled_actions(status, run_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_scheduled_actions_user_created
ON scheduled_actions(user_id, created_at DESC);
"""


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def notification_search_tokens(value: Any) -> list[str]:
    """Split a notification search box into the words it has to match.

    Kept to a handful of short tokens: the query comes from a box the owner is
    still typing in, so it is a filter, not a query language.
    """

    tokens: list[str] = []
    for token in re.split(r"\s+", normalize_text(value).lower()):
        cleaned = token.strip()
        if cleaned and cleaned not in tokens:
            tokens.append(cleaned[:80])
        if len(tokens) >= 6:
            break
    return tokens


def normalize_whatsapp_lookup_id(value: Any) -> str:
    digits = re.sub(r"\D+", "", normalize_text(value))
    if len(digits) == 10 and digits.startswith("05"):
        return f"972{digits[1:]}"
    return digits


def normalize_user_profile(value: Any) -> dict[str, str]:
    payload = value if isinstance(value, dict) else {}
    return {
        "businessSummary": normalize_text(payload.get("businessSummary"))[:4000],
        "customerNotes": normalize_text(payload.get("customerNotes"))[:4000],
        "assistantGuidance": normalize_text(payload.get("assistantGuidance"))[:4000],
    }


def normalize_client_type(value: Any) -> str:
    normalized = normalize_text(value).lower().replace(" ", "_").replace("-", "_")
    if normalized in VALID_CLIENT_TYPES:
        return normalized
    return ""


def humanize_identifier(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return "Unassigned tool"

    cleaned = re.sub(r"[-_]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Unassigned tool"


def extract_tool_context(metadata: dict[str, Any] | None, tool_id: str | None = None) -> tuple[str, str]:
    payload = metadata if isinstance(metadata, dict) else {}
    tool_record = payload.get("tool") if isinstance(payload.get("tool"), dict) else {}
    feature_record = payload.get("feature") if isinstance(payload.get("feature"), dict) else {}

    id_candidates = (
        tool_id,
        payload.get("tool_id"),
        payload.get("toolId"),
        payload.get("feature_id"),
        payload.get("featureId"),
        tool_record.get("id"),
        tool_record.get("tool_id"),
        tool_record.get("toolId"),
        tool_record.get("feature_id"),
        tool_record.get("featureId"),
        feature_record.get("id"),
        feature_record.get("tool_id"),
        feature_record.get("toolId"),
        feature_record.get("feature_id"),
        feature_record.get("featureId"),
    )
    name_candidates = (
        payload.get("tool_name"),
        payload.get("toolName"),
        payload.get("feature_name"),
        payload.get("featureName"),
        payload.get("name"),
        tool_record.get("name"),
        tool_record.get("tool_name"),
        tool_record.get("toolName"),
        feature_record.get("name"),
        feature_record.get("tool_name"),
        feature_record.get("toolName"),
    )

    resolved_tool_id = next((normalize_text(candidate) for candidate in id_candidates if normalize_text(candidate)), "") or "unassigned"
    resolved_tool_name = next((normalize_text(candidate) for candidate in name_candidates if normalize_text(candidate)), "") or humanize_identifier(resolved_tool_id)
    return resolved_tool_id, resolved_tool_name


def to_decimal(value: Any, default: str = "0") -> Decimal:
    text = normalize_text(value)
    if not text:
        text = default

    try:
        return Decimal(text)
    except Exception:
        return Decimal(default)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        text = normalize_text(value)
        if not text:
            return datetime.now(timezone.utc)

        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment


def month_key_for(moment: datetime | None = None) -> str:
    reference = moment or datetime.now().astimezone()
    return reference.astimezone().strftime("%Y-%m")


def month_sort_key(month_key: str) -> tuple[int, int]:
    try:
        year_text, month_text = str(month_key or "").split("-", 1)
        return int(year_text), int(month_text)
    except (TypeError, ValueError):
        return (0, 0)


def month_label(month_key: str) -> str:
    try:
        parsed = datetime.strptime(month_key, "%Y-%m")
        return parsed.strftime("%B %Y")
    except ValueError:
        return month_key or "Unknown month"


def cents_to_usd(value: Any) -> float:
    cents = to_decimal(value)
    return float((cents / Decimal("100")).quantize(USD_QUANT, rounding=ROUND_HALF_UP))


def cents_per_1k_tokens_from_usd_per_1m_tokens(value: Any) -> float:
    usd_per_1m_tokens = to_decimal(value)
    return float((usd_per_1m_tokens / Decimal("10")).quantize(RAW_CENTS_QUANT, rounding=ROUND_HALF_UP))


def calculate_charge_cents(tokens: Any, price_cents_per_1k_tokens: Any, multiplier: Any) -> Decimal:
    token_count = to_decimal(tokens)
    price = to_decimal(price_cents_per_1k_tokens)
    factor = to_decimal(multiplier, "1")
    charge = (token_count / Decimal("1000")) * price * factor
    return charge.quantize(RAW_CENTS_QUANT, rounding=ROUND_HALF_UP)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {key: row[key] for key in row.keys()}


def _load_json_dict(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return dict(raw_value)
    try:
        payload = json.loads(raw_value) if raw_value else {}
    except (TypeError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _load_json_list(raw_value: Any) -> list[Any]:
    if isinstance(raw_value, list):
        return list(raw_value)
    try:
        payload = json.loads(raw_value) if raw_value else []
    except (TypeError, json.JSONDecodeError):
        payload = []
    return payload if isinstance(payload, list) else []


class PortalDatabase:
    def __init__(
        self,
        path: Path | str = DEFAULT_DB_PATH,
        *,
        bootstrap_registered_emails: Iterable[str] = (),
        bootstrap_admin_emails: Iterable[str] = (),
        bootstrap_paid_emails: Iterable[str] = (),
        default_currency: str = DEFAULT_CURRENCY,
        default_monthly_minimum_cents: int = DEFAULT_MONTHLY_MINIMUM_CENTS,
        default_input_token_price_multiplier: float = DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER,
        default_output_token_price_multiplier: float = DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.default_billing_plan = BillingPlan(
            currency=str(default_currency or DEFAULT_CURRENCY).strip() or DEFAULT_CURRENCY,
            monthly_minimum_cents=max(0, int(default_monthly_minimum_cents)),
            input_token_price_multiplier=float(default_input_token_price_multiplier or DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER),
            output_token_price_multiplier=float(default_output_token_price_multiplier or DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER),
        )
        self.bootstrap_registered_emails = tuple(
            sorted({email for email in (normalize_email(value) for value in bootstrap_registered_emails) if email})
        )
        self.bootstrap_admin_emails = tuple(
            sorted({email for email in (normalize_email(value) for value in bootstrap_admin_emails) if email})
        )
        self.bootstrap_paid_emails = tuple(
            sorted({email for email in (normalize_email(value) for value in bootstrap_paid_emails) if email})
        )
        self._init_lock = threading.Lock()
        self.credential_vault: Any = None
        self._initialize()

    def set_credential_vault(self, vault: Any) -> None:
        """Attach the process-local credential vault used by provider adapters."""

        self.credential_vault = vault

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._init_lock:
            with self._connection() as conn:
                conn.executescript(PLATFORM_CONNECTIONS_TABLE_SQL)
                conn.executescript(SCHEMA_SQL)
                self._migrate_users_table(conn)
                self._migrate_user_billing_table(conn)
                self._migrate_usage_events_table(conn)
                self._migrate_whatsapp_connections_table(conn)
                self._migrate_platform_connections_table(conn)
                self._ensure_usage_events_tool_indexes(conn)
                self._ensure_contact_opportunities_indexes(conn)
                self._seed_default_model_prices(conn)
                if self.bootstrap_registered_emails and self.count_registered_users(conn) == 0:
                    self._seed_registered_emails(conn, self.bootstrap_registered_emails)
                if self.bootstrap_admin_emails:
                    self._seed_admin_emails(conn, self.bootstrap_admin_emails)
                self._sync_feature_catalog(conn)
                if self.bootstrap_paid_emails:
                    self._seed_paid_emails(conn, self.bootstrap_paid_emails)
                self._ensure_default_feature_assignments(conn)

    def _sync_feature_catalog(self, conn: sqlite3.Connection) -> None:
        for feature in load_default_feature_catalog():
            self._upsert_feature_record(
                conn,
                feature_id=feature.get("featureId"),
                feature_name=feature.get("name"),
                description=feature.get("description"),
                channel=feature.get("channel"),
                mode=feature.get("mode"),
                launch_url=feature.get("launchUrl"),
                billing_required=bool(feature.get("billing", {}).get("required")),
                billing_provider=feature.get("billing", {}).get("provider"),
                billing_store_id=feature.get("billing", {}).get("storeId"),
                billing_product_id=feature.get("billing", {}).get("productId"),
                billing_variant_id=feature.get("billing", {}).get("variantId"),
                default_assigned=bool(feature.get("defaultAssigned", True)),
                is_active=bool(feature.get("isActive", True)),
                sort_order=feature.get("sortOrder"),
                prompt=feature.get("prompt"),
                pricing=feature.get("pricing"),
                requirements=feature.get("requirements"),
                metadata=feature.get("metadata"),
            )

    def _ensure_default_feature_assignments(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id FROM users WHERE is_active = 1").fetchall()
        for row in rows:
            self._ensure_default_feature_assignments_for_user(conn, int(row["id"]))

    def _ensure_default_feature_assignments_for_user(self, conn: sqlite3.Connection, user_id: int) -> None:
        if user_id <= 0:
            return

        now = now_iso()
        conn.execute(
            """
            INSERT INTO feature_assignments (
                user_id,
                feature_id,
                is_assigned,
                metadata_json,
                assigned_at,
                updated_at
            )
            SELECT ?, f.feature_id, 1, '{}', ?, ?
            FROM features AS f
            LEFT JOIN feature_assignments AS a
                ON a.user_id = ? AND a.feature_id = f.feature_id
            WHERE f.is_active = 1
              AND f.default_assigned = 1
              AND a.feature_id IS NULL
            """,
            (user_id, now, now, user_id),
        )

    def _migrate_users_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_admin" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "client_type" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN client_type TEXT NOT NULL DEFAULT ''")
        if "profile_json" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN profile_json TEXT NOT NULL DEFAULT '{}'")

    def _migrate_user_billing_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(user_billing)").fetchall()
        }
        if "monthly_minimum_cents" not in columns:
            return

        old_defaults = (1490, 2900)
        if self.default_billing_plan.monthly_minimum_cents in old_defaults:
            return

        placeholders = ", ".join("?" for _ in old_defaults)
        conn.execute(
            f"""
            UPDATE user_billing
            SET monthly_minimum_cents = ?, updated_at = ?
            WHERE monthly_minimum_cents IN ({placeholders})
            """,
            (
                self.default_billing_plan.monthly_minimum_cents,
                now_iso(),
                *old_defaults,
            ),
        )

    def _migrate_usage_events_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(usage_events)").fetchall()
        }
        if "tool_id" not in columns:
            conn.execute("ALTER TABLE usage_events ADD COLUMN tool_id TEXT NOT NULL DEFAULT ''")

    def _migrate_whatsapp_connections_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(whatsapp_connections)").fetchall()
        }
        if "access_token" not in columns:
            conn.execute("ALTER TABLE whatsapp_connections ADD COLUMN access_token TEXT NOT NULL DEFAULT ''")
        if "access_token_ciphertext" not in columns:
            conn.execute("ALTER TABLE whatsapp_connections ADD COLUMN access_token_ciphertext TEXT NOT NULL DEFAULT ''")
        if "access_token_key_version" not in columns:
            conn.execute("ALTER TABLE whatsapp_connections ADD COLUMN access_token_key_version TEXT NOT NULL DEFAULT '1'")
        if "access_token_fingerprint" not in columns:
            conn.execute("ALTER TABLE whatsapp_connections ADD COLUMN access_token_fingerprint TEXT NOT NULL DEFAULT ''")

    def _migrate_platform_connections_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(platform_connections)").fetchall()
        }
        if "key_version" not in columns:
            conn.execute("ALTER TABLE platform_connections ADD COLUMN key_version TEXT NOT NULL DEFAULT '1'")
        if "secret_fingerprint" not in columns:
            conn.execute("ALTER TABLE platform_connections ADD COLUMN secret_fingerprint TEXT NOT NULL DEFAULT ''")
        if "account_address" not in columns:
            conn.execute("ALTER TABLE platform_connections ADD COLUMN account_address TEXT NOT NULL DEFAULT ''")
        if "account_label" not in columns:
            conn.execute("ALTER TABLE platform_connections ADD COLUMN account_label TEXT NOT NULL DEFAULT ''")
        self._widen_platform_connection_uniqueness(conn)

    def _widen_platform_connection_uniqueness(self, conn: sqlite3.Connection) -> None:
        """Widen UNIQUE(user_id, platform) to include provider and address.

        Databases created before multi-mailbox support carry a table-level
        UNIQUE(user_id, platform), which makes connecting a second mailbox
        overwrite the first. The first widening added the account address,
        which is still not enough on its own: Gmail and Outlook share the email
        platform and can report the same address, so a Microsoft connect
        overwrote a Google mailbox that had one. SQLite cannot drop a table
        constraint, so the table is rebuilt once per widening.

        Rows keep their account_address, which preserves one-row-per-platform
        for every single-account platform and for a legacy mailbox until it is
        next identified. Their provider is backfilled from the metadata that
        has always carried it, so a legacy row is identified rather than left
        beside a new one.
        """

        table_sql = ""
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'platform_connections'"
        ).fetchall():
            table_sql = normalize_text(row["sql"])
        # Test for the widened constraint, not for the columns: the ADD COLUMN
        # calls above already put account_address into this SQL, so a column
        # check here would always report the rebuild as done.
        if not table_sql or "UNIQUE(user_id, platform, provider, account_address)" in table_sql:
            return

        conn.execute("ALTER TABLE platform_connections RENAME TO platform_connections_legacy")
        conn.executescript(PLATFORM_CONNECTIONS_TABLE_SQL)
        # The provider column does not exist on either legacy shape, so rows
        # arrive unidentified and are filled in below. Copying them with an
        # empty provider cannot collide: it is the identity they already had.
        conn.execute(
            """
            INSERT INTO platform_connections (
                id, user_id, platform, auth_type, secret_ciphertext,
                key_version, secret_fingerprint, secret_hint,
                connection_status, metadata_json, account_address, account_label,
                connected_at, updated_at
            )
            SELECT id, user_id, platform, auth_type, secret_ciphertext,
                   key_version, secret_fingerprint, secret_hint,
                   connection_status, metadata_json, account_address, account_label,
                   connected_at, updated_at
            FROM platform_connections_legacy
            """
        )
        conn.execute("DROP TABLE platform_connections_legacy")
        self._backfill_platform_connection_providers(conn)

    def _backfill_platform_connection_providers(self, conn: sqlite3.Connection) -> None:
        """Copy each row's provider out of its metadata and into its own column.

        The metadata has named the provider since the first Gmail connection,
        so this identifies every row a rebuild carried over. Filling a provider
        in only ever tells two rows apart, so no row can collide with another.
        """

        rows = conn.execute(
            "SELECT id, metadata_json FROM platform_connections WHERE provider = ''"
        ).fetchall()
        for row in rows:
            metadata = _load_json_dict(row["metadata_json"])
            provider = normalize_text(metadata.get("provider")).lower()
            if not provider:
                continue
            conn.execute(
                "UPDATE platform_connections SET provider = ? WHERE id = ?",
                (provider, normalize_text(row["id"])),
            )

    def _ensure_usage_events_tool_indexes(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(usage_events)").fetchall()
        }
        if "tool_id" not in columns:
            return

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usage_events_user_tool_month
            ON usage_events(user_id, tool_id, billing_month, used_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usage_events_user_tool_model
            ON usage_events(user_id, tool_id, model_name, used_at DESC)
            """
        )

    def _ensure_contact_opportunities_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contact_opportunities_urgency_created
            ON contact_opportunities(urgency_score DESC, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contact_opportunities_created
            ON contact_opportunities(created_at DESC)
            """
        )

    def _seed_default_model_prices(self, conn: sqlite3.Connection) -> None:
        now = now_iso()
        for record in DEFAULT_MODEL_PRICES:
            model_name = normalize_text(record.get("model_name"))
            if not model_name:
                continue
            existing = conn.execute(
                "SELECT 1 FROM model_prices WHERE model_name = ?",
                (model_name,),
            ).fetchone()
            if existing is not None:
                continue
            conn.execute(
                """
                INSERT INTO model_prices (
                    model_name,
                    currency,
                    input_price_cents_per_1k_tokens,
                    output_price_cents_per_1k_tokens,
                    provider,
                    notes,
                    is_active,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    model_name,
                    self.default_billing_plan.currency,
                    cents_per_1k_tokens_from_usd_per_1m_tokens(record.get("input_usd_per_1m_tokens")),
                    cents_per_1k_tokens_from_usd_per_1m_tokens(record.get("output_usd_per_1m_tokens")),
                    DEFAULT_MODEL_PRICE_PROVIDER,
                    DEFAULT_MODEL_PRICE_NOTES,
                    now,
                    now,
                ),
            )

    def _seed_registered_emails(self, conn: sqlite3.Connection, emails: Iterable[str]) -> None:
        now = now_iso()
        for email in emails:
            normalized_email = normalize_email(email)
            if not normalized_email:
                continue

            user_id = self._upsert_user(
                conn,
                normalized_email,
                registered_at=now,
                display_name="",
                is_active=True,
                notes="",
                is_admin=False,
                update_profile=False,
            )
            self._ensure_user_billing(
                conn,
                user_id,
                currency=self.default_billing_plan.currency,
                monthly_minimum_cents=self.default_billing_plan.monthly_minimum_cents,
                input_token_price_multiplier=self.default_billing_plan.input_token_price_multiplier,
                output_token_price_multiplier=self.default_billing_plan.output_token_price_multiplier,
                effective_from=now,
                updated_at=now,
            )

    def _seed_admin_emails(self, conn: sqlite3.Connection, emails: Iterable[str]) -> None:
        now = now_iso()
        for email in emails:
            normalized_email = normalize_email(email)
            if not normalized_email:
                continue

            user_id = self._upsert_user(
                conn,
                normalized_email,
                registered_at=now,
                display_name="",
                is_active=True,
                notes="",
                is_admin=True,
                update_profile=False,
            )
            self._ensure_user_billing(
                conn,
                user_id,
                currency=self.default_billing_plan.currency,
                monthly_minimum_cents=self.default_billing_plan.monthly_minimum_cents,
                input_token_price_multiplier=self.default_billing_plan.input_token_price_multiplier,
                output_token_price_multiplier=self.default_billing_plan.output_token_price_multiplier,
                effective_from=now,
                updated_at=now,
            )

    def _seed_paid_emails(self, conn: sqlite3.Connection, emails: Iterable[str]) -> None:
        feature_rows = conn.execute(
            """
            SELECT
                feature_id,
                billing_provider,
                billing_product_id,
                billing_variant_id
            FROM features
            WHERE is_active = 1
              AND billing_required = 1
            ORDER BY sort_order ASC, feature_id ASC
            """
        ).fetchall()
        if not feature_rows:
            return

        now = now_iso()
        for email in emails:
            normalized_email = normalize_email(email)
            if not normalized_email:
                continue

            user_id = self._upsert_user(
                conn,
                normalized_email,
                registered_at=now,
                display_name="",
                is_active=True,
                notes="",
                is_admin=False,
                update_profile=False,
            )
            self._ensure_user_billing(
                conn,
                user_id,
                currency=self.default_billing_plan.currency,
                monthly_minimum_cents=self.default_billing_plan.monthly_minimum_cents,
                input_token_price_multiplier=self.default_billing_plan.input_token_price_multiplier,
                output_token_price_multiplier=self.default_billing_plan.output_token_price_multiplier,
                effective_from=now,
                updated_at=now,
            )

            billing_metadata_json = json.dumps(
                {
                    "source": "bootstrap_paid_emails",
                    "seededEmail": normalized_email,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            existing_billing = conn.execute(
                "SELECT created_at FROM billing_customers WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            billing_created_at = (
                existing_billing["created_at"]
                if existing_billing and existing_billing["created_at"]
                else now
            )
            conn.execute(
                """
                INSERT INTO billing_customers (
                    user_id,
                    provider,
                    external_customer_id,
                    external_subscription_id,
                    external_subscription_item_id,
                    subscription_status,
                    product_id,
                    variant_id,
                    checkout_url,
                    customer_portal_url,
                    last_checked_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, '', '', '', ?, '', '', '', '', ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    provider = excluded.provider,
                    subscription_status = excluded.subscription_status,
                    last_checked_at = excluded.last_checked_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    "bootstrap",
                    BOOTSTRAP_ACTIVE_SUBSCRIPTION_STATUS,
                    now,
                    billing_metadata_json,
                    billing_created_at,
                    now,
                ),
            )

            for row in feature_rows:
                feature_id = normalize_text(row["feature_id"])
                if not feature_id:
                    continue

                entitlement_metadata_json = json.dumps(
                    {
                        "source": "bootstrap_paid_emails",
                        "seededEmail": normalized_email,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
                existing_entitlement = conn.execute(
                    "SELECT created_at FROM feature_entitlements WHERE user_id = ? AND feature_id = ?",
                    (user_id, feature_id),
                ).fetchone()
                entitlement_created_at = (
                    existing_entitlement["created_at"]
                    if existing_entitlement and existing_entitlement["created_at"]
                    else now
                )
                conn.execute(
                    """
                    INSERT INTO feature_entitlements (
                        user_id,
                        feature_id,
                        provider,
                        external_customer_id,
                        external_subscription_id,
                        external_subscription_item_id,
                        entitlement_status,
                        product_id,
                        variant_id,
                        checkout_url,
                        customer_portal_url,
                        last_checked_at,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, '', '', '', ?, ?, ?, '', '', ?, ?, ?, ?)
                    ON CONFLICT(user_id, feature_id) DO UPDATE SET
                        provider = excluded.provider,
                        entitlement_status = excluded.entitlement_status,
                        product_id = excluded.product_id,
                        variant_id = excluded.variant_id,
                        last_checked_at = excluded.last_checked_at,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        feature_id,
                        normalize_text(row["billing_provider"]) or "bootstrap",
                        BOOTSTRAP_ACTIVE_SUBSCRIPTION_STATUS,
                        normalize_text(row["billing_product_id"]),
                        normalize_text(row["billing_variant_id"]),
                        now,
                        entitlement_metadata_json,
                        entitlement_created_at,
                        now,
                    ),
                )

    def _upsert_user(
        self,
        conn: sqlite3.Connection,
        email: str,
        *,
        registered_at: str | None = None,
        display_name: str = "",
        is_active: bool = True,
        notes: str = "",
        is_admin: bool = False,
        client_type: str | None = None,
        update_profile: bool = True,
    ) -> int:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        existing = conn.execute("SELECT id, registered_at FROM users WHERE email = ?", (normalized_email,)).fetchone()
        now = now_iso()
        if existing is None:
            registered_value = registered_at or now
            conn.execute(
                """
                INSERT INTO users (
                    email,
                    registered_at,
                    display_name,
                    is_active,
                    is_admin,
                    client_type,
                    notes,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_email,
                    registered_value,
                    normalize_text(display_name),
                    1 if is_active else 0,
                    1 if is_admin else 0,
                    normalize_client_type(client_type),
                    normalize_text(notes),
                    now,
                    now,
                ),
            )
        else:
            if update_profile:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?,
                        is_active = ?,
                        is_admin = ?,
                        client_type = COALESCE(NULLIF(?, ''), client_type),
                        notes = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        normalize_text(display_name),
                        1 if is_active else 0,
                        1 if is_admin else 0,
                        normalize_client_type(client_type),
                        normalize_text(notes),
                        now,
                        int(existing["id"]),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET is_active = ?,
                        is_admin = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        1 if is_active else 0,
                        1 if is_admin else 0,
                        now,
                        int(existing["id"]),
                    ),
                )

        user_row = conn.execute("SELECT id FROM users WHERE email = ?", (normalized_email,)).fetchone()
        if user_row is None:
            raise RuntimeError("Could not load the user record after saving it.")

        return int(user_row["id"])

    def _ensure_user_billing(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        *,
        currency: str,
        monthly_minimum_cents: int,
        input_token_price_multiplier: float,
        output_token_price_multiplier: float,
        effective_from: str,
        updated_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_billing (
                user_id,
                currency,
                monthly_minimum_cents,
                input_token_price_multiplier,
                output_token_price_multiplier,
                effective_from,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                normalize_text(currency) or self.default_billing_plan.currency,
                max(0, int(monthly_minimum_cents)),
                float(input_token_price_multiplier),
                float(output_token_price_multiplier),
                effective_from,
                updated_at,
            ),
        )

    def _load_user_row(self, conn: sqlite3.Connection, email: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return None

        row = conn.execute(
            """
            SELECT
                u.id,
                u.email,
                u.registered_at,
                u.display_name,
                u.is_active,
                u.is_admin,
                u.client_type,
                u.last_login_at,
                u.last_otp_requested_at,
                u.last_otp_verified_at,
                u.notes,
                u.profile_json,
                u.created_at,
                u.updated_at,
                COALESCE(b.currency, ?) AS billing_currency,
                COALESCE(b.monthly_minimum_cents, ?) AS monthly_minimum_cents,
                COALESCE(b.input_token_price_multiplier, ?) AS input_token_price_multiplier,
                COALESCE(b.output_token_price_multiplier, ?) AS output_token_price_multiplier
            FROM users AS u
            LEFT JOIN user_billing AS b
                ON b.user_id = u.id
            WHERE u.email = ?
            """,
            (
                self.default_billing_plan.currency,
                self.default_billing_plan.monthly_minimum_cents,
                self.default_billing_plan.input_token_price_multiplier,
                self.default_billing_plan.output_token_price_multiplier,
                normalized_email,
            ),
        ).fetchone()
        if row is None:
            return None

        usage_stats = conn.execute(
            """
            SELECT COUNT(*) AS usage_count, MAX(used_at) AS last_usage_at
            FROM usage_events
            WHERE user_id = ?
            """,
            (int(row["id"]),),
        ).fetchone()

        payload = _row_to_dict(row) or {}
        payload.update(
            {
                "email": normalize_email(payload.get("email")),
                "displayName": normalize_text(payload.get("display_name")),
                "isActive": bool(payload.get("is_active")),
                "isAdmin": bool(payload.get("is_admin")),
                "clientType": normalize_client_type(payload.get("client_type")),
                "registeredAt": payload.get("registered_at"),
                "lastLoginAt": payload.get("last_login_at"),
                "lastOtpRequestedAt": payload.get("last_otp_requested_at"),
                "lastOtpVerifiedAt": payload.get("last_otp_verified_at"),
                "profile": normalize_user_profile(_load_json_dict(payload.get("profile_json"))),
                "usageCount": int(usage_stats["usage_count"] or 0) if usage_stats else 0,
                "lastUsageAt": usage_stats["last_usage_at"] if usage_stats else None,
                "billing": {
                    "currency": normalize_text(payload.get("billing_currency")) or self.default_billing_plan.currency,
                    "monthlyMinimumCents": int(payload.get("monthly_minimum_cents") or self.default_billing_plan.monthly_minimum_cents),
                    "inputTokenPriceMultiplier": float(
                        payload.get("input_token_price_multiplier")
                        or self.default_billing_plan.input_token_price_multiplier
                    ),
                    "outputTokenPriceMultiplier": float(
                        payload.get("output_token_price_multiplier")
                        or self.default_billing_plan.output_token_price_multiplier
                    ),
                },
            }
        )
        for key in (
            "display_name",
            "is_active",
            "is_admin",
            "client_type",
            "registered_at",
            "last_login_at",
            "last_otp_requested_at",
            "last_otp_verified_at",
            "profile_json",
        ):
            payload.pop(key, None)
        payload.pop("billing_currency", None)
        payload.pop("monthly_minimum_cents", None)
        payload.pop("input_token_price_multiplier", None)
        payload.pop("output_token_price_multiplier", None)
        return payload

    def _load_contact_opportunity_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        payload = _row_to_dict(row)
        if not payload:
            return None

        return {
            "id": int(payload.get("id") or 0),
            "createdAt": normalize_text(payload.get("created_at")),
            "updatedAt": normalize_text(payload.get("updated_at")),
            "status": normalize_text(payload.get("status")) or "new",
            "name": normalize_text(payload.get("name")),
            "email": normalize_email(payload.get("email")),
            "phone": normalize_text(payload.get("phone")),
            "business": normalize_text(payload.get("business")),
            "businessSummary": normalize_text(payload.get("business_summary")),
            "painSummary": normalize_text(payload.get("pain_summary")),
            "suggestedTool": normalize_text(payload.get("suggested_tool")),
            "difficulty": normalize_text(payload.get("difficulty")),
            "urgency": normalize_text(payload.get("urgency")) or "medium",
            "urgencyScore": int(payload.get("urgency_score") or 0),
            "sourcePage": normalize_text(payload.get("source_page")),
            "requestCountry": normalize_text(payload.get("request_country")),
            "contactMessage": normalize_text(payload.get("contact_message")),
            "transcript": _load_json_list(payload.get("transcript_json")),
            "intake": _load_json_dict(payload.get("intake_json")),
            "metadata": _load_json_dict(payload.get("metadata_json")),
        }

    def _load_whatsapp_connection_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int | None = None,
        email: str | None = None,
        phone_number_id: str | None = None,
        owner_wa_id: str | None = None,
    ) -> dict[str, Any] | None:
        where_clauses: list[str] = ["u.is_active = 1"]
        params: list[Any] = []

        if user_id is not None:
            where_clauses.append("u.id = ?")
            params.append(int(user_id))
        elif email is not None:
            normalized_email = normalize_email(email)
            if not normalized_email:
                return None
            where_clauses.append("u.email = ?")
            params.append(normalized_email)
        elif phone_number_id is not None:
            normalized_phone_number_id = normalize_text(phone_number_id)
            if not normalized_phone_number_id:
                return None
            where_clauses.append("w.phone_number_id = ?")
            params.append(normalized_phone_number_id)
        elif owner_wa_id is not None:
            normalized_owner_wa_id = normalize_whatsapp_lookup_id(owner_wa_id)
            if not normalized_owner_wa_id:
                return None
            where_clauses.append("w.owner_wa_id = ?")
            params.append(normalized_owner_wa_id)
        else:
            return None

        row = conn.execute(
            f"""
            SELECT
                u.id AS user_id,
                u.email,
                u.display_name,
                w.business_account_id,
                w.phone_number_id,
                w.access_token,
                w.access_token_ciphertext,
                w.owner_wa_id,
                w.display_phone_number,
                w.verified_name,
                w.connection_status,
                w.metadata_json,
                w.connected_at,
                w.last_tested_at,
                w.created_at,
                w.updated_at
            FROM whatsapp_connections AS w
            INNER JOIN users AS u
                ON u.id = w.user_id
            WHERE {" AND ".join(where_clauses)}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        access_token = normalize_text(payload.get("access_token"))
        if not access_token and self.credential_vault is not None:
            ciphertext = normalize_text(payload.get("access_token_ciphertext"))
            if ciphertext:
                try:
                    access_token = normalize_text(self.credential_vault.decrypt(ciphertext))
                except Exception:
                    access_token = ""
        metadata = payload.get("metadata_json")
        try:
            metadata_payload = json.loads(metadata) if metadata else {}
        except json.JSONDecodeError:
            metadata_payload = {}

        return {
            "userId": int(payload.get("user_id") or 0),
            "email": normalize_email(payload.get("email")),
            "displayName": normalize_text(payload.get("display_name")),
            "businessAccountId": normalize_text(payload.get("business_account_id")),
            "phoneNumberId": normalize_text(payload.get("phone_number_id")),
            "accessToken": access_token,
            "accessTokenConfigured": bool(access_token),
            "ownerWaId": normalize_text(payload.get("owner_wa_id")),
            "displayPhoneNumber": normalize_text(payload.get("display_phone_number")),
            "verifiedName": normalize_text(payload.get("verified_name")),
            "connectionStatus": normalize_text(payload.get("connection_status")) or "not_connected",
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "connectedAt": payload.get("connected_at"),
            "lastTestedAt": payload.get("last_tested_at"),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_platform_connection_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        connection_id: str | None = None,
        platform: str | None = None,
    ) -> dict[str, Any] | None:
        if user_id <= 0:
            return None

        where = ["user_id = ?"]
        params: list[Any] = [int(user_id)]
        if connection_id:
            where.append("id = ?")
            params.append(normalize_text(connection_id))
        elif platform:
            where.append("platform = ?")
            params.append(normalize_text(platform).lower())
        else:
            return None

        row = conn.execute(
            f"""
            SELECT id, user_id, platform, provider, auth_type, secret_hint,
                   connection_status, metadata_json, account_address, account_label,
                   connected_at, updated_at
            FROM platform_connections
            WHERE {" AND ".join(where)}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        return {
            "id": normalize_text(payload.get("id")),
            "userId": int(payload.get("user_id") or 0),
            "platform": normalize_text(payload.get("platform")),
            # The provider is half of what a connection is: the email platform
            # holds both Gmail and Outlook, so a caller given the platform alone
            # cannot tell whose mailbox it is looking at.
            "provider": normalize_text(payload.get("provider")).lower(),
            "authType": normalize_text(payload.get("auth_type")) or "api_token",
            "secretHint": normalize_text(payload.get("secret_hint")),
            "connectionStatus": normalize_text(payload.get("connection_status")) or "connected",
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "accountAddress": normalize_text(payload.get("account_address")),
            "accountLabel": normalize_text(payload.get("account_label")),
            "connectedAt": normalize_text(payload.get("connected_at")),
            "updatedAt": normalize_text(payload.get("updated_at")),
            "hasCredential": True,
        }

    def _load_whatsapp_conversation_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        normalized_conversation_id = normalize_text(conversation_id)
        if user_id <= 0 or not normalized_conversation_id:
            return None

        row = conn.execute(
            """
            SELECT *
            FROM whatsapp_conversations
            WHERE user_id = ? AND conversation_id = ?
            LIMIT 1
            """,
            (int(user_id), normalized_conversation_id),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        metadata_payload = _load_json_dict(payload.get("metadata_json"))
        message_count_row = conn.execute(
            """
            SELECT COUNT(*) AS message_count
            FROM whatsapp_conversation_messages
            WHERE user_id = ? AND conversation_id = ?
            """,
            (int(user_id), normalized_conversation_id),
        ).fetchone()
        return {
            "userId": int(payload.get("user_id") or 0),
            "conversationId": normalize_text(payload.get("conversation_id")),
            "senderName": normalize_text(payload.get("sender_name")),
            "senderWaId": normalize_text(payload.get("sender_wa_id")),
            "lastMessageText": normalize_text(payload.get("last_message_text")),
            "lastMessageId": normalize_text(payload.get("last_message_id")),
            "lastMessageDirection": normalize_text(payload.get("last_message_direction")),
            "lastMessageAt": payload.get("last_message_at"),
            "lastInboundAt": payload.get("last_inbound_at"),
            "lastOutboundAt": payload.get("last_outbound_at"),
            "lastReengagementNotifiedAt": payload.get("last_reengagement_notified_at"),
            "lastReengagementNotifiedForMessageAt": payload.get("last_reengagement_notified_for_message_at"),
            "messageCount": int(message_count_row["message_count"] or 0) if message_count_row is not None else 0,
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_whatsapp_reengagement_run_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        normalized_scheduled_for = normalize_text(scheduled_for)
        if user_id <= 0 or not normalized_feature_id or not normalized_scheduled_for:
            return None

        row = conn.execute(
            """
            SELECT *
            FROM whatsapp_reengagement_runs
            WHERE user_id = ? AND feature_id = ? AND scheduled_for = ?
            LIMIT 1
            """,
            (int(user_id), normalized_feature_id, normalized_scheduled_for),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        metadata_payload = _load_json_dict(payload.get("metadata_json"))
        return {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "featureId": normalize_text(payload.get("feature_id")),
            "scheduledFor": payload.get("scheduled_for"),
            "conversationsChecked": int(payload.get("conversations_checked") or 0),
            "notificationsSent": int(payload.get("notifications_sent") or 0),
            "status": normalize_text(payload.get("status")),
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_scheduled_action_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        payload = _row_to_dict(row)
        if not payload:
            return None

        return {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "actionType": normalize_text(payload.get("action_type")),
            "channel": normalize_text(payload.get("channel")),
            "recipientRef": normalize_text(payload.get("recipient_ref")),
            "runAt": payload.get("run_at"),
            "timezone": normalize_text(payload.get("timezone")),
            "status": normalize_text(payload.get("status")) or "pending",
            "attemptCount": int(payload.get("attempt_count") or 0),
            "providerMessageId": normalize_text(payload.get("provider_message_id")),
            "payload": _load_json_dict(payload.get("payload_json")),
            "lastError": normalize_text(payload.get("last_error")),
            "claimedAt": payload.get("claimed_at"),
            "completedAt": payload.get("completed_at"),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_notification_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        payload = _row_to_dict(row)
        if not payload:
            return None

        read_at = payload.get("read_at")
        return {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "kind": normalize_text(payload.get("kind")) or "info",
            "tone": normalize_text(payload.get("tone")) or "info",
            "title": normalize_text(payload.get("title")),
            "body": payload.get("body") or "",
            "source": normalize_text(payload.get("source")),
            "featureId": normalize_text(payload.get("feature_id")),
            "actionId": normalize_text(payload.get("action_id")),
            "resultUrl": normalize_text(payload.get("result_url")),
            "dedupeKey": normalize_text(payload.get("dedupe_key")),
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "readAt": read_at,
            "read": bool(read_at),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _resolve_user_id(
        self,
        conn: sqlite3.Connection,
        email: str,
        *,
        include_inactive: bool = False,
    ) -> int:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        query = "SELECT id FROM users WHERE email = ?"
        if not include_inactive:
            query += " AND is_active = 1"
        user_row = conn.execute(
            query,
            (normalized_email,),
        ).fetchone()
        if user_row is None:
            raise KeyError(f"Unknown user: {normalized_email}")

        return int(user_row["id"])

    def _resolve_active_user_id(self, conn: sqlite3.Connection, email: str) -> int:
        return self._resolve_user_id(conn, email, include_inactive=False)

    def _load_billing_customer_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int | None = None,
        email: str | None = None,
        include_inactive: bool = False,
    ) -> dict[str, Any] | None:
        if user_id is None:
            if email is None:
                return None
            try:
                user_id = self._resolve_user_id(conn, email, include_inactive=include_inactive)
            except (KeyError, ValueError):
                return None

        row = conn.execute(
            """
            SELECT
                b.user_id,
                u.email,
                b.provider,
                b.external_customer_id,
                b.external_subscription_id,
                b.external_subscription_item_id,
                b.subscription_status,
                b.product_id,
                b.variant_id,
                b.checkout_url,
                b.customer_portal_url,
                b.last_checked_at,
                b.metadata_json,
                b.created_at,
                b.updated_at
            FROM billing_customers AS b
            INNER JOIN users AS u
                ON u.id = b.user_id
            WHERE b.user_id = ?
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        metadata = payload.get("metadata_json")
        try:
            metadata_payload = json.loads(metadata) if metadata else {}
        except json.JSONDecodeError:
            metadata_payload = {}

        return {
            "userId": int(payload.get("user_id") or 0),
            "email": normalize_email(payload.get("email")),
            "provider": normalize_text(payload.get("provider")),
            "externalCustomerId": normalize_text(payload.get("external_customer_id")),
            "externalSubscriptionId": normalize_text(payload.get("external_subscription_id")),
            "externalSubscriptionItemId": normalize_text(payload.get("external_subscription_item_id")),
            "subscriptionStatus": normalize_text(payload.get("subscription_status")),
            "productId": normalize_text(payload.get("product_id")),
            "variantId": normalize_text(payload.get("variant_id")),
            "checkoutUrl": normalize_text(payload.get("checkout_url")),
            "customerPortalUrl": normalize_text(payload.get("customer_portal_url")),
            "lastCheckedAt": payload.get("last_checked_at"),
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_feature_activation_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        feature_id: str,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            return None

        row = conn.execute(
            """
            SELECT
                fa.user_id,
                u.email,
                fa.feature_id,
                fa.feature_name,
                fa.is_active,
                fa.activated_at,
                fa.deactivated_at,
                fa.metadata_json,
                fa.created_at,
                fa.updated_at
            FROM feature_activations AS fa
            INNER JOIN users AS u
                ON u.id = fa.user_id
            WHERE fa.user_id = ? AND fa.feature_id = ?
            LIMIT 1
            """,
            (int(user_id), normalized_feature_id),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        metadata = payload.get("metadata_json")
        try:
            metadata_payload = json.loads(metadata) if metadata else {}
        except json.JSONDecodeError:
            metadata_payload = {}

        return {
            "userId": int(payload.get("user_id") or 0),
            "email": normalize_email(payload.get("email")),
            "featureId": normalize_text(payload.get("feature_id")),
            "featureName": normalize_text(payload.get("feature_name")),
            "isActive": bool(payload.get("is_active")),
            "status": "active" if bool(payload.get("is_active")) else "non-active",
            "activatedAt": payload.get("activated_at"),
            "deactivatedAt": payload.get("deactivated_at"),
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _upsert_feature_record(
        self,
        conn: sqlite3.Connection,
        *,
        feature_id: Any,
        feature_name: Any = "",
        description: Any = "",
        channel: Any = "",
        mode: Any = "",
        launch_url: Any = "",
        billing_required: bool = False,
        billing_provider: Any = "",
        billing_store_id: Any = "",
        billing_product_id: Any = "",
        billing_variant_id: Any = "",
        default_assigned: bool = True,
        is_active: bool = True,
        sort_order: Any = 100,
        prompt: dict[str, Any] | None = None,
        pricing: dict[str, Any] | None = None,
        requirements: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        now = now_iso()
        prompt_json = json.dumps(prompt or {}, ensure_ascii=True, sort_keys=True)
        pricing_json = json.dumps(pricing or {}, ensure_ascii=True, sort_keys=True)
        requirements_json = json.dumps(requirements or {}, ensure_ascii=True, sort_keys=True)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        existing = conn.execute(
            "SELECT created_at FROM features WHERE feature_id = ?",
            (normalized_feature_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing and existing["created_at"] else now

        conn.execute(
            """
            INSERT INTO features (
                feature_id,
                feature_name,
                description,
                channel,
                mode,
                launch_url,
                billing_required,
                billing_provider,
                billing_store_id,
                billing_product_id,
                billing_variant_id,
                default_assigned,
                is_active,
                sort_order,
                prompt_json,
                pricing_json,
                requirements_json,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feature_id) DO UPDATE SET
                feature_name = excluded.feature_name,
                description = excluded.description,
                channel = excluded.channel,
                mode = excluded.mode,
                launch_url = excluded.launch_url,
                billing_required = excluded.billing_required,
                billing_provider = excluded.billing_provider,
                billing_store_id = excluded.billing_store_id,
                billing_product_id = excluded.billing_product_id,
                billing_variant_id = excluded.billing_variant_id,
                default_assigned = excluded.default_assigned,
                is_active = excluded.is_active,
                sort_order = excluded.sort_order,
                prompt_json = excluded.prompt_json,
                pricing_json = excluded.pricing_json,
                requirements_json = excluded.requirements_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                normalized_feature_id,
                normalize_text(feature_name) or humanize_identifier(normalized_feature_id),
                normalize_text(description),
                normalize_text(channel),
                normalize_text(mode),
                normalize_text(launch_url),
                1 if billing_required else 0,
                normalize_text(billing_provider),
                normalize_text(billing_store_id),
                normalize_text(billing_product_id),
                normalize_text(billing_variant_id),
                1 if default_assigned else 0,
                1 if is_active else 0,
                int(sort_order or 100),
                prompt_json,
                pricing_json,
                requirements_json,
                metadata_json,
                created_at,
                now,
            ),
        )
        return self._load_feature_row(conn, feature_id=normalized_feature_id) or {}

    def _load_feature_row(
        self,
        conn: sqlite3.Connection,
        *,
        feature_id: str,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            return None

        row = conn.execute(
            """
            SELECT
                feature_id,
                feature_name,
                description,
                channel,
                mode,
                launch_url,
                billing_required,
                billing_provider,
                billing_store_id,
                billing_product_id,
                billing_variant_id,
                default_assigned,
                is_active,
                sort_order,
                prompt_json,
                pricing_json,
                requirements_json,
                metadata_json,
                created_at,
                updated_at
            FROM features
            WHERE feature_id = ?
            LIMIT 1
            """,
            (normalized_feature_id,),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        return {
            "featureId": normalize_text(payload.get("feature_id")),
            "name": normalize_text(payload.get("feature_name")) or humanize_identifier(payload.get("feature_id")),
            "description": normalize_text(payload.get("description")),
            "channel": normalize_text(payload.get("channel")),
            "mode": normalize_text(payload.get("mode")),
            "launchUrl": normalize_text(payload.get("launch_url")),
            "billingRequired": bool(payload.get("billing_required")),
            "billingProvider": normalize_text(payload.get("billing_provider")),
            "billingStoreId": normalize_text(payload.get("billing_store_id")),
            "billingProductId": normalize_text(payload.get("billing_product_id")),
            "billingVariantId": normalize_text(payload.get("billing_variant_id")),
            "defaultAssigned": bool(payload.get("default_assigned")),
            "isCatalogActive": bool(payload.get("is_active")),
            "sortOrder": int(payload.get("sort_order") or 100),
            "prompt": _load_json_dict(payload.get("prompt_json")),
            "pricing": _load_json_dict(payload.get("pricing_json")),
            "requirements": _load_json_dict(payload.get("requirements_json")),
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_feature_assignment_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        feature_id: str,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0 or not normalized_feature_id:
            return None

        row = conn.execute(
            """
            SELECT
                fa.user_id,
                u.email,
                fa.feature_id,
                fa.is_assigned,
                fa.metadata_json,
                fa.assigned_at,
                fa.updated_at
            FROM feature_assignments AS fa
            INNER JOIN users AS u
                ON u.id = fa.user_id
            WHERE fa.user_id = ? AND fa.feature_id = ?
            LIMIT 1
            """,
            (user_id, normalized_feature_id),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        return {
            "userId": int(payload.get("user_id") or 0),
            "email": normalize_email(payload.get("email")),
            "featureId": normalize_text(payload.get("feature_id")),
            "isAssigned": bool(payload.get("is_assigned")),
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "assignedAt": payload.get("assigned_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def _load_feature_entitlement_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        feature_id: str,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0 or not normalized_feature_id:
            return None

        row = conn.execute(
            """
            SELECT
                fe.user_id,
                u.email,
                fe.feature_id,
                fe.provider,
                fe.external_customer_id,
                fe.external_subscription_id,
                fe.external_subscription_item_id,
                fe.entitlement_status,
                fe.product_id,
                fe.variant_id,
                fe.checkout_url,
                fe.customer_portal_url,
                fe.last_checked_at,
                fe.metadata_json,
                fe.created_at,
                fe.updated_at
            FROM feature_entitlements AS fe
            INNER JOIN users AS u
                ON u.id = fe.user_id
            WHERE fe.user_id = ? AND fe.feature_id = ?
            LIMIT 1
            """,
            (user_id, normalized_feature_id),
        ).fetchone()
        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        return {
            "userId": int(payload.get("user_id") or 0),
            "email": normalize_email(payload.get("email")),
            "featureId": normalize_text(payload.get("feature_id")),
            "provider": normalize_text(payload.get("provider")),
            "externalCustomerId": normalize_text(payload.get("external_customer_id")),
            "externalSubscriptionId": normalize_text(payload.get("external_subscription_id")),
            "externalSubscriptionItemId": normalize_text(payload.get("external_subscription_item_id")),
            "entitlementStatus": normalize_text(payload.get("entitlement_status")),
            "productId": normalize_text(payload.get("product_id")),
            "variantId": normalize_text(payload.get("variant_id")),
            "checkoutUrl": normalize_text(payload.get("checkout_url")),
            "customerPortalUrl": normalize_text(payload.get("customer_portal_url")),
            "lastCheckedAt": payload.get("last_checked_at"),
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def count_registered_users(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is not None:
            row = conn.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1").fetchone()
            return int(row["count"] or 0) if row else 0

        with self._connection() as fresh_conn:
            row = fresh_conn.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1").fetchone()
            return int(row["count"] or 0) if row else 0

    def count_admin_users(self, conn: sqlite3.Connection | None = None, *, include_inactive: bool = False) -> int:
        where_clause = "WHERE is_admin = 1"
        if not include_inactive:
            where_clause += " AND is_active = 1"

        if conn is not None:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM users {where_clause}").fetchone()
            return int(row["count"] or 0) if row else 0

        with self._connection() as fresh_conn:
            row = fresh_conn.execute(f"SELECT COUNT(*) AS count FROM users {where_clause}").fetchone()
            return int(row["count"] or 0) if row else 0

    def list_registered_emails(self) -> frozenset[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT email FROM users WHERE is_active = 1 ORDER BY email ASC"
            ).fetchall()

        return frozenset(normalize_email(row["email"]) for row in rows if normalize_email(row["email"]))

    def is_registered_email(self, email: str) -> bool:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return False

        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE email = ? AND is_active = 1 LIMIT 1",
                (normalized_email,),
            ).fetchone()

        return row is not None

    def list_users(self, include_inactive: bool = True) -> list[dict[str, Any]]:
        where_clause = "" if include_inactive else "WHERE u.is_active = 1"
        query = f"""
            SELECT
                u.id,
                u.email,
                u.registered_at,
                u.display_name,
                u.is_active,
                u.is_admin,
                u.client_type,
                u.last_login_at,
                u.last_otp_requested_at,
                u.last_otp_verified_at,
                u.notes,
                u.profile_json,
                u.created_at,
                u.updated_at,
                COALESCE(b.currency, ?) AS billing_currency,
                COALESCE(b.monthly_minimum_cents, ?) AS monthly_minimum_cents,
                COALESCE(b.input_token_price_multiplier, ?) AS input_token_price_multiplier,
                COALESCE(b.output_token_price_multiplier, ?) AS output_token_price_multiplier,
                COALESCE(stats.usage_count, 0) AS usage_count,
                stats.last_usage_at
            FROM users AS u
            LEFT JOIN user_billing AS b
                ON b.user_id = u.id
            LEFT JOIN (
                SELECT
                    user_id,
                    COUNT(*) AS usage_count,
                    MAX(used_at) AS last_usage_at
                FROM usage_events
                GROUP BY user_id
            ) AS stats
                ON stats.user_id = u.id
            {where_clause}
            ORDER BY u.registered_at DESC, u.email ASC
        """

        with self._connection() as conn:
            rows = conn.execute(
                query,
                (
                    self.default_billing_plan.currency,
                    self.default_billing_plan.monthly_minimum_cents,
                    self.default_billing_plan.input_token_price_multiplier,
                    self.default_billing_plan.output_token_price_multiplier,
                ),
            ).fetchall()

        users: list[dict[str, Any]] = []
        for row in rows:
            payload = _row_to_dict(row) or {}
            payload.update(
                {
                    "email": normalize_email(payload.get("email")),
                    "displayName": normalize_text(payload.get("display_name")),
                    "isActive": bool(payload.get("is_active")),
                    "isAdmin": bool(payload.get("is_admin")),
                    "clientType": normalize_client_type(payload.get("client_type")),
                    "registeredAt": payload.get("registered_at"),
                    "lastLoginAt": payload.get("last_login_at"),
                    "lastOtpRequestedAt": payload.get("last_otp_requested_at"),
                    "lastOtpVerifiedAt": payload.get("last_otp_verified_at"),
                    "profile": normalize_user_profile(_load_json_dict(payload.get("profile_json"))),
                    "usageCount": int(payload.get("usage_count") or 0),
                    "lastUsageAt": payload.get("last_usage_at"),
                    "billing": {
                        "currency": normalize_text(payload.get("billing_currency")) or self.default_billing_plan.currency,
                        "monthlyMinimumCents": int(
                            payload.get("monthly_minimum_cents") or self.default_billing_plan.monthly_minimum_cents
                        ),
                        "inputTokenPriceMultiplier": float(
                            payload.get("input_token_price_multiplier")
                            or self.default_billing_plan.input_token_price_multiplier
                        ),
                        "outputTokenPriceMultiplier": float(
                            payload.get("output_token_price_multiplier")
                            or self.default_billing_plan.output_token_price_multiplier
                        ),
                    },
                }
            )
            for key in (
                "display_name",
                "is_active",
                "is_admin",
                "client_type",
                "registered_at",
                "last_login_at",
                "last_otp_requested_at",
                "last_otp_verified_at",
                "notes",
                "profile_json",
                "created_at",
                "updated_at",
                "billing_currency",
                "monthly_minimum_cents",
                "input_token_price_multiplier",
                "output_token_price_multiplier",
                "usage_count",
                "last_usage_at",
            ):
                payload.pop(key, None)
            users.append(payload)

        return users

    def register_user(
        self,
        email: str,
        *,
        display_name: str = "",
        notes: str = "",
        is_active: bool = True,
        is_admin: bool = False,
        client_type: str | None = None,
        registered_at: str | datetime | None = None,
        currency: str | None = None,
        monthly_minimum_cents: int | None = None,
        input_token_price_multiplier: float | None = None,
        output_token_price_multiplier: float | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        moment = now_iso() if registered_at is None else parse_datetime(registered_at).isoformat()
        with self._connection() as conn:
            user_id = self._upsert_user(
                conn,
                normalized_email,
                registered_at=moment,
                display_name=display_name,
                is_active=is_active,
                notes=notes,
                is_admin=is_admin,
                client_type=client_type,
            )
            self._ensure_user_billing(
                conn,
                user_id,
                currency=currency or self.default_billing_plan.currency,
                monthly_minimum_cents=
                    self.default_billing_plan.monthly_minimum_cents
                    if monthly_minimum_cents is None
                    else int(monthly_minimum_cents),
                input_token_price_multiplier=
                    self.default_billing_plan.input_token_price_multiplier
                    if input_token_price_multiplier is None
                    else float(input_token_price_multiplier),
                output_token_price_multiplier=
                    self.default_billing_plan.output_token_price_multiplier
                    if output_token_price_multiplier is None
                    else float(output_token_price_multiplier),
                effective_from=moment,
                updated_at=moment,
            )
            self._ensure_default_feature_assignments_for_user(conn, user_id)
            return self._load_user_row(conn, normalized_email) or {}

    def create_contact_opportunity(
        self,
        *,
        name: str = "",
        email: str = "",
        phone: str = "",
        business: str = "",
        business_summary: str = "",
        pain_summary: str = "",
        suggested_tool: str = "",
        difficulty: str = "",
        urgency: str = "medium",
        urgency_score: int = 50,
        source_page: str = "",
        request_country: str = "",
        contact_message: str = "",
        transcript: list[dict[str, Any]] | None = None,
        intake: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            normalized_urgency_score = int(urgency_score)
        except (TypeError, ValueError):
            normalized_urgency_score = 50
        normalized_urgency_score = max(0, min(100, normalized_urgency_score))

        transcript_payload = transcript if isinstance(transcript, list) else []
        intake_payload = intake if isinstance(intake, dict) else {}
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        moment = now_iso()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO contact_opportunities (
                    created_at,
                    updated_at,
                    status,
                    name,
                    email,
                    phone,
                    business,
                    business_summary,
                    pain_summary,
                    suggested_tool,
                    difficulty,
                    urgency,
                    urgency_score,
                    source_page,
                    request_country,
                    contact_message,
                    transcript_json,
                    intake_json,
                    metadata_json
                ) VALUES (?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    moment,
                    moment,
                    normalize_text(name),
                    normalize_email(email),
                    normalize_text(phone),
                    normalize_text(business),
                    normalize_text(business_summary),
                    normalize_text(pain_summary),
                    normalize_text(suggested_tool),
                    normalize_text(difficulty),
                    normalize_text(urgency) or "medium",
                    normalized_urgency_score,
                    normalize_text(source_page),
                    normalize_text(request_country),
                    normalize_text(contact_message),
                    json.dumps(transcript_payload, ensure_ascii=True, sort_keys=True),
                    json.dumps(intake_payload, ensure_ascii=True, sort_keys=True),
                    json.dumps(metadata_payload, ensure_ascii=True, sort_keys=True),
                ),
            )
            row = conn.execute(
                "SELECT * FROM contact_opportunities WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()

        return self._load_contact_opportunity_row(row) or {}

    def list_contact_opportunities(self, *, limit: int = 200) -> list[dict[str, Any]]:
        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError):
            normalized_limit = 200
        normalized_limit = max(1, min(500, normalized_limit))

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM contact_opportunities
                ORDER BY urgency_score DESC, created_at DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()

        return [
            opportunity
            for opportunity in (self._load_contact_opportunity_row(row) for row in rows)
            if opportunity is not None
        ]

    def update_user_identity(
        self,
        current_email: str,
        *,
        email: str,
        display_name: str = "",
    ) -> dict[str, Any]:
        normalized_current_email = normalize_email(current_email)
        normalized_email = normalize_email(email)
        if not normalized_current_email:
            raise ValueError("Current email is required.")
        if not normalized_email:
            raise ValueError("Email is required.")

        with self._connection() as conn:
            user = self._load_user_row(conn, normalized_current_email)
            if user is None:
                raise KeyError(f"Unknown user: {normalized_current_email}")

            existing = conn.execute(
                "SELECT id FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            user_id = int(user.get("id") or 0)
            if existing is not None and int(existing["id"] or 0) != user_id:
                raise ValueError("That email is already registered.")

            conn.execute(
                """
                UPDATE users
                SET email = ?,
                    display_name = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_email,
                    normalize_text(display_name),
                    now_iso(),
                    user_id,
                ),
            )
            return self._load_user_row(conn, normalized_email) or {}

    def update_user_client_type(self, email: str, *, client_type: str) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_client_type = normalize_client_type(client_type)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_client_type:
            raise ValueError("Client type must be paying, demo, or qa.")

        with self._connection() as conn:
            user = self._load_user_row(conn, normalized_email)
            if user is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            conn.execute(
                """
                UPDATE users
                SET client_type = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_client_type,
                    now_iso(),
                    int(user.get("id") or 0),
                ),
            )
            return self._load_user_row(conn, normalized_email) or {}

    def delete_user(self, email: str) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        with self._connection() as conn:
            user = self._load_user_row(conn, normalized_email)
            if user is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            user_id = int(user.get("id") or 0)
            if user_id > 0:
                existing_tables = {
                    str(row["name"])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
                for table_name in USER_OWNED_TABLES:
                    if table_name in existing_tables:
                        conn.execute(f"DELETE FROM {table_name} WHERE user_id = ?", (user_id,))

            conn.execute("DELETE FROM users WHERE email = ?", (normalized_email,))
            return user

    def set_user_billing(
        self,
        email: str,
        *,
        currency: str | None = None,
        monthly_minimum_cents: int | None = None,
        input_token_price_multiplier: float | None = None,
        output_token_price_multiplier: float | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        now = now_iso()
        with self._connection() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", (normalized_email,)).fetchone()
            if user_row is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            conn.execute(
                """
                INSERT INTO user_billing (
                    user_id,
                    currency,
                    monthly_minimum_cents,
                    input_token_price_multiplier,
                    output_token_price_multiplier,
                    effective_from,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    currency = excluded.currency,
                    monthly_minimum_cents = excluded.monthly_minimum_cents,
                    input_token_price_multiplier = excluded.input_token_price_multiplier,
                    output_token_price_multiplier = excluded.output_token_price_multiplier,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_row["id"]),
                    normalize_text(currency) or self.default_billing_plan.currency,
                    self.default_billing_plan.monthly_minimum_cents
                    if monthly_minimum_cents is None
                    else int(monthly_minimum_cents),
                    self.default_billing_plan.input_token_price_multiplier
                    if input_token_price_multiplier is None
                    else float(input_token_price_multiplier),
                    self.default_billing_plan.output_token_price_multiplier
                    if output_token_price_multiplier is None
                    else float(output_token_price_multiplier),
                    now,
                    now,
                ),
            )
            return self._load_user_row(conn, normalized_email) or {}

    def upsert_model_price(
        self,
        model_name: str,
        *,
        input_price_cents_per_1k_tokens: float = 0.0,
        output_price_cents_per_1k_tokens: float = 0.0,
        currency: str = DEFAULT_CURRENCY,
        provider: str = "",
        notes: str = "",
        is_active: bool = True,
    ) -> dict[str, Any]:
        normalized_model_name = normalize_text(model_name)
        if not normalized_model_name:
            raise ValueError("Model name is required.")

        now = now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO model_prices (
                    model_name,
                    currency,
                    input_price_cents_per_1k_tokens,
                    output_price_cents_per_1k_tokens,
                    provider,
                    notes,
                    is_active,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_name) DO UPDATE SET
                    currency = excluded.currency,
                    input_price_cents_per_1k_tokens = excluded.input_price_cents_per_1k_tokens,
                    output_price_cents_per_1k_tokens = excluded.output_price_cents_per_1k_tokens,
                    provider = excluded.provider,
                    notes = excluded.notes,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_model_name,
                    normalize_text(currency) or self.default_billing_plan.currency,
                    float(input_price_cents_per_1k_tokens),
                    float(output_price_cents_per_1k_tokens),
                    normalize_text(provider),
                    normalize_text(notes),
                    1 if is_active else 0,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM model_prices WHERE model_name = ?",
                (normalized_model_name,),
            ).fetchone()
            return _row_to_dict(row) or {}

    def get_model_price(self, model_name: str) -> dict[str, Any] | None:
        normalized_model_name = normalize_text(model_name)
        if not normalized_model_name:
            return None

        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM model_prices WHERE model_name = ? AND is_active = 1",
                (normalized_model_name,),
            ).fetchone()

        return _row_to_dict(row)

    def list_model_prices(self, *, provider: str = "", active_only: bool = True) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        normalized_provider = normalize_text(provider)
        if normalized_provider:
            clauses.append("provider = ?")
            params.append(normalized_provider)

        if active_only:
            clauses.append("is_active = 1")

        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            "SELECT * FROM model_prices"
            f"{where_sql} "
            "ORDER BY input_price_cents_per_1k_tokens ASC, output_price_cents_per_1k_tokens ASC, model_name ASC"
        )

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()

        return [_row_to_dict(row) for row in rows if row is not None]

    def record_otp_requested(self, email: str) -> None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return

        now = now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET last_otp_requested_at = ?,
                    updated_at = ?
                WHERE email = ? AND is_active = 1
                """,
                (now, now, normalized_email),
            )

    def record_login(self, email: str) -> None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return

        now = now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET last_login_at = ?,
                    last_otp_verified_at = ?,
                    updated_at = ?
                WHERE email = ? AND is_active = 1
                """,
                (now, now, now, normalized_email),
            )

    def get_whatsapp_connection(self, email: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return None

        with self._connection() as conn:
            return self._load_whatsapp_connection_row(conn, email=normalized_email)

    def delete_whatsapp_connection(self, email: str) -> bool:
        """Remove the authenticated user's WhatsApp credentials and metadata."""

        normalized_email = normalize_email(email)
        if not normalized_email:
            return False

        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                user_id = 0
            if user_id <= 0:
                return False
            cursor = conn.execute(
                "DELETE FROM whatsapp_connections WHERE user_id = ?",
                (user_id,),
            )
            return cursor.rowcount > 0

    def migrate_whatsapp_access_tokens(self) -> int:
        """Move legacy plaintext WhatsApp tokens into the configured vault."""

        vault = self.credential_vault
        if vault is None:
            return 0

        migrated = 0
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id, access_token FROM whatsapp_connections WHERE access_token <> ''"
            ).fetchall()
            for row in rows:
                token = normalize_text(row["access_token"])
                if not token:
                    continue
                encrypted = vault.encrypt(token)
                # Verify the envelope before clearing the compatibility field.
                if vault.decrypt(encrypted) != token:
                    continue
                conn.execute(
                    """
                    UPDATE whatsapp_connections
                    SET access_token = '',
                        access_token_ciphertext = ?,
                        access_token_key_version = ?,
                        access_token_fingerprint = ?,
                        updated_at = ?
                    WHERE user_id = ? AND access_token = ?
                    """,
                    (
                        encrypted,
                        vault.key_version,
                        vault.fingerprint(token),
                        now_iso(),
                        int(row["user_id"]),
                        token,
                    ),
                )
                migrated += 1
        return migrated

    def list_platform_connections(self, email: str) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return []

        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                user_id = 0
            if user_id <= 0:
                return []
            rows = conn.execute(
                """
                SELECT id, user_id, platform, auth_type, secret_hint,
                       connection_status, metadata_json, connected_at, updated_at
                FROM platform_connections
                WHERE user_id = ?
                ORDER BY updated_at DESC, platform ASC
                """,
                (user_id,),
            ).fetchall()
            return [
                item
                for item in (
                    self._load_platform_connection_row(
                        conn,
                        user_id=user_id,
                        connection_id=normalize_text(row["id"]),
                    )
                    for row in rows
                )
                if item
            ]

    def get_platform_connection_ciphertext(
        self,
        email: str,
        platform: str,
        *,
        include_statuses: tuple[str, ...] = ("connected",),
    ) -> str | None:
        """Return ciphertext for server-side tools; never serialize this to the portal."""

        normalized_email = normalize_email(email)
        normalized_platform = normalize_text(platform).lower()
        if not normalized_email or not normalized_platform:
            return None

        statuses = tuple(
            normalized_status
            for normalized_status in (
                normalize_text(status).lower() for status in include_statuses
            )
            if normalized_status
        )
        if not statuses:
            return None

        placeholders = ", ".join("?" for _ in statuses)
        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                return None
            row = conn.execute(
                f"""
                SELECT secret_ciphertext
                FROM platform_connections
                WHERE user_id = ? AND platform = ? AND connection_status IN ({placeholders})
                LIMIT 1
                """,
                (user_id, normalized_platform, *statuses),
            ).fetchone()
            return normalize_text(row["secret_ciphertext"]) if row else None

    def list_platform_connection_secret_records(
        self,
        email: str,
        platform: str,
        *,
        include_statuses: tuple[str, ...] = ("connected",),
    ) -> list[dict[str, str]]:
        """Return every account on a platform, with ciphertext, for server-side runs.

        This is the multi-account counterpart of
        ``get_platform_connection_ciphertext``. Callers must keep
        ``secretCiphertext`` inside the server process; it is never serialized
        to the portal or into an agent prompt. Ordering is stable so a fan-out
        reads a user's mailboxes in the same order every run.
        """

        normalized_email = normalize_email(email)
        normalized_platform = normalize_text(platform).lower()
        if not normalized_email or not normalized_platform:
            return []

        statuses = tuple(
            normalized_status
            for normalized_status in (
                normalize_text(status).lower() for status in include_statuses
            )
            if normalized_status
        )
        if not statuses:
            return []

        placeholders = ", ".join("?" for _ in statuses)
        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                return []
            if user_id <= 0:
                return []
            rows = conn.execute(
                f"""
                SELECT id, platform, auth_type, secret_ciphertext,
                       account_address, account_label, connection_status, metadata_json
                FROM platform_connections
                WHERE user_id = ? AND platform = ? AND connection_status IN ({placeholders})
                ORDER BY account_address ASC, connected_at ASC, id ASC
                """,
                (user_id, normalized_platform, *statuses),
            ).fetchall()
            return [
                {
                    "id": normalize_text(row["id"]),
                    "platform": normalize_text(row["platform"]).lower(),
                    "authType": normalize_text(row["auth_type"]).lower() or "api_token",
                    "secretCiphertext": normalize_text(row["secret_ciphertext"]),
                    "accountAddress": normalize_text(row["account_address"]),
                    "accountLabel": normalize_text(row["account_label"]),
                    "connectionStatus": normalize_text(row["connection_status"]).lower() or "connected",
                    "metadata": _load_json_dict(row["metadata_json"]),
                }
                for row in rows
            ]

    def set_platform_connection_account(
        self,
        email: str,
        *,
        connection_id: str,
        account_address: str = "",
        account_label: str = "",
    ) -> dict[str, Any] | None:
        """Name one connection's account, ignoring a change that would collide.

        Used to identify a mailbox saved before addresses were captured, and to
        let a user rename an account from the portal.
        """

        normalized_email = normalize_email(email)
        normalized_id = normalize_text(connection_id)
        if not normalized_email or not normalized_id:
            return None

        normalized_address = normalize_email(account_address) or normalize_text(account_address).lower()
        normalized_label = normalize_text(account_label)
        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                return None
            row = conn.execute(
                "SELECT platform, provider, account_address FROM platform_connections WHERE user_id = ? AND id = ? LIMIT 1",
                (user_id, normalized_id),
            ).fetchone()
            if row is None:
                return None

            if normalized_address and normalized_address != normalize_text(row["account_address"]):
                # Only this provider's own rows can clash. Two providers may
                # hold the same address, so the platform alone would refuse a
                # name that the connections themselves have room for.
                clash = conn.execute(
                    """
                    SELECT id FROM platform_connections
                    WHERE user_id = ? AND platform = ? AND provider = ? AND account_address = ? AND id <> ?
                    LIMIT 1
                    """,
                    (
                        user_id,
                        normalize_text(row["platform"]).lower(),
                        normalize_text(row["provider"]).lower(),
                        normalized_address,
                        normalized_id,
                    ),
                ).fetchone()
                if clash is not None:
                    # That account is already connected under another row.
                    # Leaving both intact beats silently merging two credentials.
                    return None

            conn.execute(
                """
                UPDATE platform_connections
                SET account_address = CASE WHEN ? <> '' THEN ? ELSE account_address END,
                    account_label = CASE WHEN ? <> '' THEN ? ELSE account_label END,
                    updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    normalized_address,
                    normalized_address,
                    normalized_label,
                    normalized_label,
                    now_iso(),
                    user_id,
                    normalized_id,
                ),
            )
            return self._load_platform_connection_row(
                conn,
                user_id=user_id,
                connection_id=normalized_id,
            )

    def get_platform_connection_secret_record(
        self,
        email: str,
        connection_id: str,
    ) -> dict[str, str] | None:
        """Return one connection's encrypted secret for server-side lifecycle work.

        This method is intentionally separate from the public connection
        serializer. Callers must keep ``secretCiphertext`` inside the server;
        it is only used to revoke a provider credential before the row is
        removed.
        """

        normalized_email = normalize_email(email)
        normalized_id = normalize_text(connection_id)
        if not normalized_email or not normalized_id:
            return None

        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                return None
            if user_id <= 0:
                return None
            row = conn.execute(
                """
                SELECT id, platform, auth_type, secret_ciphertext, secret_fingerprint, connection_status
                FROM platform_connections
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, normalized_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "id": normalize_text(row["id"]),
                "platform": normalize_text(row["platform"]).lower(),
                "authType": normalize_text(row["auth_type"]).lower() or "api_token",
                "secretCiphertext": normalize_text(row["secret_ciphertext"]),
                "secretFingerprint": normalize_text(row["secret_fingerprint"]),
                "connectionStatus": normalize_text(row["connection_status"]).lower() or "connected",
            }

    def count_platform_connections_with_secret_fingerprint(
        self,
        email: str,
        secret_fingerprint: str,
    ) -> int:
        normalized_email = normalize_email(email)
        normalized_fingerprint = normalize_text(secret_fingerprint)
        if not normalized_email or not normalized_fingerprint:
            return 0

        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                return 0
            row = conn.execute(
                """
                SELECT COUNT(*) AS connection_count
                FROM platform_connections
                WHERE user_id = ? AND secret_fingerprint = ?
                """,
                (user_id, normalized_fingerprint),
            ).fetchone()
            return int(row["connection_count"] or 0) if row else 0

    def _platform_connection_row_to_reuse(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        platform: str,
        provider: str,
        account_address: str,
    ) -> sqlite3.Row | None:
        """The row a connect should write over, if this account already has one.

        This provider's own row comes first. A row that names no provider is
        taken as this one's too: it predates the column, and claiming it keeps
        a reconnect replacing a row rather than piling a second one beside it.
        A row belonging to a different provider is never returned, which is how
        connecting Outlook stops overwriting a Gmail mailbox.
        """

        return conn.execute(
            """
            SELECT id, connected_at
            FROM platform_connections
            WHERE user_id = ? AND platform = ? AND account_address = ?
              AND provider IN (?, '')
            ORDER BY CASE WHEN provider = ? THEN 0 ELSE 1 END, connected_at ASC, id ASC
            LIMIT 1
            """,
            (user_id, platform, account_address, provider, provider),
        ).fetchone()

    def save_platform_connection(
        self,
        email: str,
        *,
        platform: str,
        auth_type: str,
        secret_ciphertext: str,
        secret_hint: str,
        key_version: str = "1",
        secret_fingerprint: str = "",
        metadata: dict[str, Any] | None = None,
        connection_status: str = "connected",
        account_address: str = "",
        account_label: str = "",
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_platform = normalize_text(platform).lower()
        # The account address identifies which of a user's several accounts
        # this row is. Single-account platforms pass nothing and keep one row.
        normalized_address = normalize_email(account_address) or normalize_text(account_address).lower()
        normalized_label = normalize_text(account_label)
        normalized_auth_type = normalize_text(auth_type).lower() or "api_token"
        normalized_ciphertext = normalize_text(secret_ciphertext)
        normalized_hint = normalize_text(secret_hint)
        normalized_status = normalize_text(connection_status).lower() or "connected"
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_platform:
            raise ValueError("Platform is required.")
        if not normalized_ciphertext:
            raise ValueError("Encrypted credential is required.")
        if normalized_status not in {"connected", "needs_verification", "needs_attention", "disconnected"}:
            raise ValueError("Unsupported connection status.")

        metadata_payload = _load_json_dict(metadata)
        metadata_json = json.dumps(metadata_payload, ensure_ascii=True, sort_keys=True)
        # Which reader this row belongs to. Gmail and Outlook are both the
        # email platform, so the provider is what tells one account's mailboxes
        # apart when the addresses cannot: a personal Microsoft account may be
        # registered under a Gmail address.
        normalized_provider = normalize_text(metadata_payload.get("provider")).lower()
        now = now_iso()
        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            existing = self._platform_connection_row_to_reuse(
                conn,
                user_id=user_id,
                platform=normalized_platform,
                provider=normalized_provider,
                account_address=normalized_address,
            )
            if existing is None and normalized_address:
                # A row saved before addresses were captured is unidentified.
                # The connect happening now is the best identification available,
                # so adopt that row instead of leaving a stale duplicate beside
                # the new one. Rows that already carry an address are untouched,
                # so a genuine second mailbox still lands as its own row.
                existing = self._platform_connection_row_to_reuse(
                    conn,
                    user_id=user_id,
                    platform=normalized_platform,
                    provider=normalized_provider,
                    account_address="",
                )
            connection_id = normalize_text(existing["id"]) if existing else ""
            connected_at = normalize_text(existing["connected_at"]) if existing else ""
            if not connection_id:
                # Public ids must not reveal row counts or be guessable.
                connection_id = f"pc_{secrets.token_urlsafe(18)}"
            if not connected_at:
                connected_at = now

            conn.execute(
                """
                INSERT INTO platform_connections (
                    id, user_id, platform, auth_type, secret_ciphertext,
                    key_version, secret_fingerprint,
                    secret_hint, connection_status, metadata_json,
                    account_address, account_label, provider,
                    connected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                -- The row to reuse was already resolved above, so the conflict
                -- target is the id. Keying it on (user_id, platform) would
                -- collapse a second mailbox back onto the first.
                ON CONFLICT(id) DO UPDATE SET
                    auth_type = excluded.auth_type,
                    secret_ciphertext = excluded.secret_ciphertext,
                    key_version = excluded.key_version,
                    secret_fingerprint = excluded.secret_fingerprint,
                    secret_hint = excluded.secret_hint,
                    connection_status = excluded.connection_status,
                    metadata_json = excluded.metadata_json,
                    account_address = excluded.account_address,
                    account_label = excluded.account_label,
                    provider = excluded.provider,
                    updated_at = excluded.updated_at
                """,
                (
                    connection_id,
                    user_id,
                    normalized_platform,
                    normalized_auth_type,
                    normalized_ciphertext,
                    normalize_text(key_version) or "1",
                    normalize_text(secret_fingerprint),
                    normalized_hint,
                    normalized_status,
                    metadata_json,
                    normalized_address,
                    normalized_label,
                    normalized_provider,
                    connected_at,
                    now,
                ),
            )
            return self._load_platform_connection_row(
                conn,
                user_id=user_id,
                connection_id=connection_id,
            ) or {}

    def update_platform_connection_status(
        self,
        email: str,
        *,
        platform: str = "",
        connection_id: str = "",
        connection_status: str,
        metadata_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update non-secret connection health metadata after provider validation.

        Pass ``connection_id`` to flag one specific account. Passing only
        ``platform`` still resolves to a single row, which is right for
        single-account platforms but would pick an arbitrary mailbox once a
        user has several.
        """

        normalized_email = normalize_email(email)
        normalized_platform = normalize_text(platform).lower()
        normalized_id = normalize_text(connection_id)
        normalized_status = normalize_text(connection_status).lower()
        if not normalized_email or (not normalized_platform and not normalized_id):
            return None
        if normalized_status not in {"connected", "needs_verification", "needs_attention", "disconnected"}:
            raise ValueError("Unsupported connection status.")

        updates = _load_json_dict(metadata_updates)
        now = now_iso()
        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            where = "id = ?" if normalized_id else "platform = ?"
            row = conn.execute(
                f"""
                SELECT id, metadata_json, connected_at
                FROM platform_connections
                WHERE user_id = ? AND {where}
                LIMIT 1
                """,
                (user_id, normalized_id or normalized_platform),
            ).fetchone()
            if row is None:
                return None

            metadata = _load_json_dict(row["metadata_json"])
            metadata.update(updates)
            connected_at = normalize_text(row["connected_at"]) or now
            conn.execute(
                """
                UPDATE platform_connections
                SET connection_status = ?, metadata_json = ?, connected_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    normalized_status,
                    json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                    connected_at,
                    now,
                    normalize_text(row["id"]),
                    user_id,
                ),
            )
            return self._load_platform_connection_row(
                conn,
                user_id=user_id,
                connection_id=normalize_text(row["id"]),
            )

    def delete_platform_connection(self, email: str, *, connection_id: str = "", platform: str = "") -> bool:
        normalized_email = normalize_email(email)
        normalized_id = normalize_text(connection_id)
        normalized_platform = normalize_text(platform).lower()
        if not normalized_email or not normalized_id and not normalized_platform:
            return False

        with self._connection() as conn:
            try:
                user_id = self._resolve_active_user_id(conn, normalized_email)
            except (KeyError, ValueError):
                user_id = 0
            if user_id <= 0:
                return False
            where = "id = ?" if normalized_id else "platform = ?"
            value = normalized_id or normalized_platform
            cursor = conn.execute(
                f"DELETE FROM platform_connections WHERE user_id = ? AND {where}",
                (user_id, value),
            )
            return cursor.rowcount > 0

    def get_user(self, email: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return None

        with self._connection() as conn:
            return self._load_user_row(conn, normalized_email)

    def update_user_profile(self, email: str, *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        normalized_profile = normalize_user_profile(profile)
        with self._connection() as conn:
            user = self._load_user_row(conn, normalized_email)
            if user is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            conn.execute(
                """
                UPDATE users
                SET profile_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(normalized_profile, ensure_ascii=True, sort_keys=True),
                    now_iso(),
                    int(user.get("id") or 0),
                ),
            )
            return self._load_user_row(conn, normalized_email) or {}

    def save_whatsapp_message(
        self,
        *,
        conversation_id: str,
        direction: str,
        text: str,
        email: str | None = None,
        user_id: int | None = None,
        sender_name: str = "",
        sender_wa_id: str = "",
        message_id: str = "",
        message_type: str = "text",
        message_at: str | datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_conversation_id = normalize_text(conversation_id)
        normalized_direction = normalize_text(direction).lower() or "inbound"
        normalized_text_value = normalize_text(text)
        normalized_message_id = normalize_text(message_id)
        normalized_message_type = normalize_text(message_type) or "text"
        normalized_sender_name = normalize_text(sender_name)
        normalized_sender_wa_id = normalize_text(sender_wa_id)
        if not normalized_conversation_id:
            raise ValueError("Conversation id is required.")
        if normalized_direction not in {"inbound", "outbound"}:
            raise ValueError("Direction must be inbound or outbound.")
        if not normalized_text_value:
            raise ValueError("Message text is required.")

        message_moment = parse_datetime(message_at) if message_at is not None else datetime.now(timezone.utc)
        message_at_value = message_moment.astimezone(timezone.utc).isoformat()
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        metadata_json = json.dumps(metadata_payload, ensure_ascii=True, sort_keys=True)
        now = now_iso()

        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    raise ValueError("Email or user id is required.")
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)

            if normalized_message_id:
                existing_message = conn.execute(
                    """
                    SELECT id
                    FROM whatsapp_conversation_messages
                    WHERE user_id = ? AND message_id = ?
                    LIMIT 1
                    """,
                    (resolved_user_id, normalized_message_id),
                ).fetchone()
                if existing_message is not None:
                    conversation = self._load_whatsapp_conversation_row(
                        conn,
                        user_id=resolved_user_id,
                        conversation_id=normalized_conversation_id,
                    )
                    return {
                        "userId": resolved_user_id,
                        "conversationId": normalized_conversation_id,
                        "messageId": normalized_message_id,
                        "direction": normalized_direction,
                        "messageType": normalized_message_type,
                        "text": normalized_text_value,
                        "messageAt": message_at_value,
                        "metadata": dict(metadata_payload),
                        "conversation": conversation or {},
                        "isDuplicate": True,
                    }

            existing_conversation = self._load_whatsapp_conversation_row(
                conn,
                user_id=resolved_user_id,
                conversation_id=normalized_conversation_id,
            ) or {}
            conversation_metadata = (
                existing_conversation.get("metadata")
                if isinstance(existing_conversation.get("metadata"), dict)
                else {}
            )
            merged_conversation_metadata = {
                **conversation_metadata,
                **metadata_payload,
            }

            last_message_at = normalize_text(existing_conversation.get("lastMessageAt"))
            last_inbound_at = normalize_text(existing_conversation.get("lastInboundAt"))
            last_outbound_at = normalize_text(existing_conversation.get("lastOutboundAt"))

            resolved_sender_name = normalized_sender_name or normalize_text(existing_conversation.get("senderName"))
            resolved_sender_wa_id = normalized_sender_wa_id or normalize_text(existing_conversation.get("senderWaId"))
            created_at = existing_conversation.get("createdAt") or now

            updated_values = {
                "sender_name": resolved_sender_name,
                "sender_wa_id": resolved_sender_wa_id,
                "last_message_text": normalize_text(existing_conversation.get("lastMessageText")),
                "last_message_id": normalize_text(existing_conversation.get("lastMessageId")),
                "last_message_direction": normalize_text(existing_conversation.get("lastMessageDirection")),
                "last_message_at": existing_conversation.get("lastMessageAt"),
                "last_inbound_at": existing_conversation.get("lastInboundAt"),
                "last_outbound_at": existing_conversation.get("lastOutboundAt"),
            }

            if not last_message_at or message_at_value >= last_message_at:
                updated_values["last_message_text"] = normalized_text_value
                updated_values["last_message_id"] = normalized_message_id
                updated_values["last_message_direction"] = normalized_direction
                updated_values["last_message_at"] = message_at_value

            if normalized_direction == "inbound" and (not last_inbound_at or message_at_value >= last_inbound_at):
                updated_values["last_inbound_at"] = message_at_value
            if normalized_direction == "outbound" and (not last_outbound_at or message_at_value >= last_outbound_at):
                updated_values["last_outbound_at"] = message_at_value

            conn.execute(
                """
                INSERT INTO whatsapp_conversations (
                    user_id,
                    conversation_id,
                    sender_name,
                    sender_wa_id,
                    last_message_text,
                    last_message_id,
                    last_message_direction,
                    last_message_at,
                    last_inbound_at,
                    last_outbound_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, conversation_id) DO UPDATE SET
                    sender_name = excluded.sender_name,
                    sender_wa_id = excluded.sender_wa_id,
                    last_message_text = excluded.last_message_text,
                    last_message_id = excluded.last_message_id,
                    last_message_direction = excluded.last_message_direction,
                    last_message_at = excluded.last_message_at,
                    last_inbound_at = excluded.last_inbound_at,
                    last_outbound_at = excluded.last_outbound_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_user_id,
                    normalized_conversation_id,
                    updated_values["sender_name"],
                    updated_values["sender_wa_id"],
                    updated_values["last_message_text"],
                    updated_values["last_message_id"],
                    updated_values["last_message_direction"],
                    updated_values["last_message_at"],
                    updated_values["last_inbound_at"],
                    updated_values["last_outbound_at"],
                    json.dumps(merged_conversation_metadata, ensure_ascii=True, sort_keys=True),
                    created_at,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO whatsapp_conversation_messages (
                    user_id,
                    conversation_id,
                    message_id,
                    direction,
                    message_type,
                    text,
                    message_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_user_id,
                    normalized_conversation_id,
                    normalized_message_id,
                    normalized_direction,
                    normalized_message_type,
                    normalized_text_value,
                    message_at_value,
                    metadata_json,
                    now,
                    now,
                ),
            )

            conversation = self._load_whatsapp_conversation_row(
                conn,
                user_id=resolved_user_id,
                conversation_id=normalized_conversation_id,
            ) or {}
            return {
                "userId": resolved_user_id,
                "conversationId": normalized_conversation_id,
                "messageId": normalized_message_id,
                "direction": normalized_direction,
                "messageType": normalized_message_type,
                "text": normalized_text_value,
                "messageAt": message_at_value,
                "metadata": dict(metadata_payload),
                "conversation": conversation,
                "isDuplicate": False,
            }

    def save_whatsapp_messages_batch(
        self,
        *,
        messages: Iterable[dict[str, Any]],
        email: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        normalized_messages: list[dict[str, Any]] = []
        now = now_iso()

        for source in messages:
            if not isinstance(source, dict):
                continue

            conversation_id = normalize_text(source.get("conversationId") or source.get("conversation_id"))
            direction = normalize_text(source.get("direction")).lower() or "inbound"
            text = normalize_text(source.get("text"))
            message_id = normalize_text(source.get("messageId") or source.get("message_id"))
            message_type = normalize_text(source.get("messageType") or source.get("message_type")) or "text"
            sender_name = normalize_text(source.get("senderName") or source.get("sender_name"))
            sender_wa_id = normalize_text(source.get("senderWaId") or source.get("sender_wa_id"))
            message_at = source.get("messageAt") or source.get("message_at")
            metadata_payload = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}

            if not conversation_id:
                raise ValueError("Conversation id is required.")
            if direction not in {"inbound", "outbound"}:
                raise ValueError("Direction must be inbound or outbound.")
            if not text:
                raise ValueError("Message text is required.")

            message_moment = parse_datetime(message_at) if message_at is not None else datetime.now(timezone.utc)
            normalized_messages.append(
                {
                    "conversation_id": conversation_id,
                    "direction": direction,
                    "text": text,
                    "message_id": message_id,
                    "message_type": message_type,
                    "sender_name": sender_name,
                    "sender_wa_id": sender_wa_id,
                    "message_at": message_moment.astimezone(timezone.utc).isoformat(),
                    "metadata": dict(metadata_payload),
                    "metadata_json": json.dumps(metadata_payload, ensure_ascii=True, sort_keys=True),
                }
            )

        if not normalized_messages:
            return {
                "messagesSaved": 0,
                "duplicates": 0,
                "conversations": [],
            }

        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    raise ValueError("Email or user id is required.")
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)

            messages_saved = 0
            duplicates = 0
            conversation_payloads: dict[str, dict[str, Any]] = {}

            for message in normalized_messages:
                conversation_id = message["conversation_id"]
                payload = conversation_payloads.setdefault(
                    conversation_id,
                    {
                        "sender_name": "",
                        "sender_wa_id": "",
                        "metadata": {},
                    },
                )
                if message["sender_name"]:
                    payload["sender_name"] = message["sender_name"]
                if message["sender_wa_id"]:
                    payload["sender_wa_id"] = message["sender_wa_id"]
                payload["metadata"] = {
                    **payload["metadata"],
                    **message["metadata"],
                }

                existing_message = None
                if message["message_id"]:
                    existing_message = conn.execute(
                        """
                        SELECT id, conversation_id
                        FROM whatsapp_conversation_messages
                        WHERE user_id = ? AND message_id = ?
                        LIMIT 1
                        """,
                        (resolved_user_id, message["message_id"]),
                    ).fetchone()

                if existing_message is not None:
                    duplicates += 1
                    existing_conversation_id = normalize_text(existing_message["conversation_id"])
                    if existing_conversation_id and existing_conversation_id != conversation_id:
                        conversation_payloads.setdefault(
                            existing_conversation_id,
                            {
                                "sender_name": "",
                                "sender_wa_id": "",
                                "metadata": {},
                            },
                        )
                    conn.execute(
                        """
                        UPDATE whatsapp_conversation_messages
                        SET conversation_id = ?,
                            direction = ?,
                            message_type = ?,
                            text = ?,
                            message_at = ?,
                            metadata_json = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            conversation_id,
                            message["direction"],
                            message["message_type"],
                            message["text"],
                            message["message_at"],
                            message["metadata_json"],
                            now,
                            int(existing_message["id"]),
                        ),
                    )
                    continue

                conn.execute(
                    """
                    INSERT INTO whatsapp_conversation_messages (
                        user_id,
                        conversation_id,
                        message_id,
                        direction,
                        message_type,
                        text,
                        message_at,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_user_id,
                        conversation_id,
                        message["message_id"],
                        message["direction"],
                        message["message_type"],
                        message["text"],
                        message["message_at"],
                        message["metadata_json"],
                        now,
                        now,
                    ),
                )
                messages_saved += 1

            conversations: list[dict[str, Any]] = []
            for conversation_id, payload in conversation_payloads.items():
                existing_conversation = self._load_whatsapp_conversation_row(
                    conn,
                    user_id=resolved_user_id,
                    conversation_id=conversation_id,
                ) or {}
                last_message = conn.execute(
                    """
                    SELECT message_id, direction, text, message_at
                    FROM whatsapp_conversation_messages
                    WHERE user_id = ? AND conversation_id = ?
                    ORDER BY message_at DESC, id DESC
                    LIMIT 1
                    """,
                    (resolved_user_id, conversation_id),
                ).fetchone()
                if last_message is None:
                    conn.execute(
                        """
                        DELETE FROM whatsapp_conversations
                        WHERE user_id = ? AND conversation_id = ?
                        """,
                        (resolved_user_id, conversation_id),
                    )
                    continue

                last_inbound = conn.execute(
                    """
                    SELECT MAX(message_at) AS message_at
                    FROM whatsapp_conversation_messages
                    WHERE user_id = ? AND conversation_id = ? AND direction = 'inbound'
                    """,
                    (resolved_user_id, conversation_id),
                ).fetchone()
                last_outbound = conn.execute(
                    """
                    SELECT MAX(message_at) AS message_at
                    FROM whatsapp_conversation_messages
                    WHERE user_id = ? AND conversation_id = ? AND direction = 'outbound'
                    """,
                    (resolved_user_id, conversation_id),
                ).fetchone()

                existing_metadata = (
                    existing_conversation.get("metadata")
                    if isinstance(existing_conversation.get("metadata"), dict)
                    else {}
                )
                merged_metadata = {
                    **existing_metadata,
                    **payload["metadata"],
                }
                sender_name = normalize_text(payload.get("sender_name")) or normalize_text(existing_conversation.get("senderName"))
                sender_wa_id = normalize_text(payload.get("sender_wa_id")) or normalize_text(existing_conversation.get("senderWaId"))
                created_at = existing_conversation.get("createdAt") or now

                conn.execute(
                    """
                    INSERT INTO whatsapp_conversations (
                        user_id,
                        conversation_id,
                        sender_name,
                        sender_wa_id,
                        last_message_text,
                        last_message_id,
                        last_message_direction,
                        last_message_at,
                        last_inbound_at,
                        last_outbound_at,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, conversation_id) DO UPDATE SET
                        sender_name = excluded.sender_name,
                        sender_wa_id = excluded.sender_wa_id,
                        last_message_text = excluded.last_message_text,
                        last_message_id = excluded.last_message_id,
                        last_message_direction = excluded.last_message_direction,
                        last_message_at = excluded.last_message_at,
                        last_inbound_at = excluded.last_inbound_at,
                        last_outbound_at = excluded.last_outbound_at,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        resolved_user_id,
                        conversation_id,
                        sender_name,
                        sender_wa_id,
                        normalize_text(last_message["text"]),
                        normalize_text(last_message["message_id"]),
                        normalize_text(last_message["direction"]),
                        last_message["message_at"],
                        last_inbound["message_at"] if last_inbound is not None else None,
                        last_outbound["message_at"] if last_outbound is not None else None,
                        json.dumps(merged_metadata, ensure_ascii=True, sort_keys=True),
                        created_at,
                        now,
                    ),
                )
                conversation = self._load_whatsapp_conversation_row(
                    conn,
                    user_id=resolved_user_id,
                    conversation_id=conversation_id,
                )
                if conversation is not None:
                    conversations.append(conversation)

            return {
                "messagesSaved": messages_saved,
                "duplicates": duplicates,
                "conversations": conversations,
            }

    def delete_whatsapp_manual_import_messages(
        self,
        conversation_id: str,
        *,
        email: str | None = None,
        user_id: int | None = None,
        import_file_name: str = "",
    ) -> dict[str, Any]:
        normalized_conversation_id = normalize_text(conversation_id)
        if not normalized_conversation_id:
            raise ValueError("Conversation id is required.")
        normalized_import_file_name = normalize_text(import_file_name)

        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    raise ValueError("Email or user id is required.")
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)

            rows = conn.execute(
                """
                SELECT id, metadata_json
                FROM whatsapp_conversation_messages
                WHERE user_id = ? AND conversation_id = ?
                """,
                (resolved_user_id, normalized_conversation_id),
            ).fetchall()
            manual_message_ids: list[int] = []
            for row in rows:
                metadata = _load_json_dict(row["metadata_json"])
                if metadata.get("source") != "manual_import":
                    continue
                if (
                    normalized_import_file_name
                    and normalize_text(metadata.get("importFileName")) != normalized_import_file_name
                ):
                    continue
                manual_message_ids.append(int(row["id"]))

            if manual_message_ids:
                conn.executemany(
                    """
                    DELETE FROM whatsapp_conversation_messages
                    WHERE user_id = ? AND id = ?
                    """,
                    [(resolved_user_id, message_id) for message_id in manual_message_ids],
                )
                conn.execute(
                    """
                    DELETE FROM whatsapp_reengagement_notifications
                    WHERE user_id = ? AND conversation_id = ?
                    """,
                    (resolved_user_id, normalized_conversation_id),
                )

                remaining = conn.execute(
                    """
                    SELECT COUNT(*) AS message_count
                    FROM whatsapp_conversation_messages
                    WHERE user_id = ? AND conversation_id = ?
                    """,
                    (resolved_user_id, normalized_conversation_id),
                ).fetchone()
                if remaining is None or int(remaining["message_count"] or 0) <= 0:
                    conn.execute(
                        """
                        DELETE FROM whatsapp_conversations
                        WHERE user_id = ? AND conversation_id = ?
                        """,
                        (resolved_user_id, normalized_conversation_id),
                    )

            return {
                "conversationId": normalized_conversation_id,
                "messagesDeleted": len(manual_message_ids),
            }

    def delete_whatsapp_conversation(
        self,
        conversation_id: str,
        *,
        email: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        normalized_conversation_id = normalize_text(conversation_id)
        if not normalized_conversation_id:
            raise ValueError("Conversation id is required.")

        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    raise ValueError("Email or user id is required.")
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)

            conversation = self._load_whatsapp_conversation_row(
                conn,
                user_id=resolved_user_id,
                conversation_id=normalized_conversation_id,
            )
            if conversation is None:
                raise KeyError(f"Unknown WhatsApp conversation: {normalized_conversation_id}")

            message_count_row = conn.execute(
                """
                SELECT COUNT(*) AS message_count
                FROM whatsapp_conversation_messages
                WHERE user_id = ? AND conversation_id = ?
                """,
                (resolved_user_id, normalized_conversation_id),
            ).fetchone()
            notification_count_row = conn.execute(
                """
                SELECT COUNT(*) AS notification_count
                FROM whatsapp_reengagement_notifications
                WHERE user_id = ? AND conversation_id = ?
                """,
                (resolved_user_id, normalized_conversation_id),
            ).fetchone()

            conn.execute(
                """
                DELETE FROM whatsapp_conversation_messages
                WHERE user_id = ? AND conversation_id = ?
                """,
                (resolved_user_id, normalized_conversation_id),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_reengagement_notifications
                WHERE user_id = ? AND conversation_id = ?
                """,
                (resolved_user_id, normalized_conversation_id),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_conversations
                WHERE user_id = ? AND conversation_id = ?
                """,
                (resolved_user_id, normalized_conversation_id),
            )

            return {
                **conversation,
                "messagesDeleted": int(message_count_row["message_count"] or 0) if message_count_row else 0,
                "notificationsDeleted": (
                    int(notification_count_row["notification_count"] or 0)
                    if notification_count_row
                    else 0
                ),
            }

    def get_whatsapp_conversation(
        self,
        conversation_id: str,
        *,
        email: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        normalized_conversation_id = normalize_text(conversation_id)
        if not normalized_conversation_id:
            return None

        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    return None
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)
            return self._load_whatsapp_conversation_row(
                conn,
                user_id=resolved_user_id,
                conversation_id=normalized_conversation_id,
            )

    def list_whatsapp_conversations(
        self,
        *,
        email: str | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    return []
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)

            rows = conn.execute(
                """
                SELECT conversation_id
                FROM whatsapp_conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC, conversation_id ASC
                """,
                (resolved_user_id,),
            ).fetchall()

            conversations: list[dict[str, Any]] = []
            for row in rows:
                record = self._load_whatsapp_conversation_row(
                    conn,
                    user_id=resolved_user_id,
                    conversation_id=row["conversation_id"],
                )
                if record is not None:
                    conversations.append(record)
            return conversations

    def list_whatsapp_conversation_messages(
        self,
        conversation_id: str,
        *,
        email: str | None = None,
        user_id: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized_conversation_id = normalize_text(conversation_id)
        if not normalized_conversation_id:
            return []

        with self._connection() as conn:
            resolved_user_id = int(user_id or 0)
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    return []
                resolved_user_id = self._resolve_active_user_id(conn, normalized_email)

            params: list[Any] = [resolved_user_id, normalized_conversation_id]
            limit_clause = ""
            if limit is not None and int(limit) > 0:
                limit_clause = " LIMIT ?"
                params.append(int(limit))

            rows = conn.execute(
                f"""
                SELECT
                    message_id,
                    direction,
                    message_type,
                    text,
                    message_at,
                    metadata_json,
                    created_at,
                    updated_at
                FROM whatsapp_conversation_messages
                WHERE user_id = ?
                  AND conversation_id = ?
                ORDER BY message_at DESC, id DESC
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()

            messages: list[dict[str, Any]] = []
            for row in reversed(rows):
                payload = _row_to_dict(row) or {}
                metadata_payload = _load_json_dict(payload.get("metadata_json"))
                messages.append(
                    {
                        "messageId": normalize_text(payload.get("message_id")),
                        "direction": normalize_text(payload.get("direction")),
                        "messageType": normalize_text(payload.get("message_type")),
                        "text": normalize_text(payload.get("text")),
                        "messageAt": payload.get("message_at"),
                        "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
                        "createdAt": payload.get("created_at"),
                        "updatedAt": payload.get("updated_at"),
                    }
                )
            return messages

    def upsert_feature(
        self,
        feature_id: str,
        *,
        feature_name: str = "",
        description: str = "",
        channel: str = "",
        mode: str = "",
        launch_url: str = "",
        billing_required: bool = False,
        billing_provider: str = "",
        billing_store_id: str = "",
        billing_product_id: str = "",
        billing_variant_id: str = "",
        default_assigned: bool = True,
        is_active: bool = True,
        sort_order: int = 100,
        prompt: dict[str, Any] | None = None,
        pricing: dict[str, Any] | None = None,
        requirements: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connection() as conn:
            return self._upsert_feature_record(
                conn,
                feature_id=feature_id,
                feature_name=feature_name,
                description=description,
                channel=channel,
                mode=mode,
                launch_url=launch_url,
                billing_required=billing_required,
                billing_provider=billing_provider,
                billing_store_id=billing_store_id,
                billing_product_id=billing_product_id,
                billing_variant_id=billing_variant_id,
                default_assigned=default_assigned,
                is_active=is_active,
                sort_order=sort_order,
                prompt=prompt,
                pricing=pricing,
                requirements=requirements,
                metadata=metadata,
            )

    def get_feature(self, feature_id: str) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            return None

        with self._connection() as conn:
            return self._load_feature_row(conn, feature_id=normalized_feature_id)

    def list_features(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        with self._connection() as conn:
            query = """
                SELECT feature_id
                FROM features
            """
            params: list[Any] = []
            if not include_inactive:
                query += " WHERE is_active = 1"
            query += " ORDER BY sort_order ASC, feature_name ASC, feature_id ASC"
            rows = conn.execute(query, tuple(params)).fetchall()

            features: list[dict[str, Any]] = []
            for row in rows:
                record = self._load_feature_row(conn, feature_id=row["feature_id"])
                if record is not None:
                    features.append(record)
        return features

    def get_feature_assignment(self, email: str, feature_id: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email or not normalized_feature_id:
            return None

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            return self._load_feature_assignment_row(conn, user_id=user_id, feature_id=normalized_feature_id)

    def list_feature_assignments(
        self,
        email: str,
        *,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return []

        with self._connection() as conn:
            user_id = self._resolve_user_id(conn, normalized_email, include_inactive=include_inactive)
            rows = conn.execute(
                """
                SELECT feature_id
                FROM feature_assignments
                WHERE user_id = ?
                ORDER BY updated_at DESC, feature_id ASC
                """,
                (user_id,),
            ).fetchall()

            assignments: list[dict[str, Any]] = []
            for row in rows:
                record = self._load_feature_assignment_row(conn, user_id=user_id, feature_id=row["feature_id"])
                if record is not None:
                    assignments.append(record)
        return assignments

    def assign_feature_to_user(
        self,
        email: str,
        feature_id: str,
        *,
        is_assigned: bool = True,
        metadata: dict[str, Any] | None = None,
        assigned_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        assigned_at_value = parse_datetime(assigned_at).isoformat() if assigned_at is not None else now

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            feature = self._load_feature_row(conn, feature_id=normalized_feature_id)
            if feature is None:
                raise KeyError(f"Unknown feature: {normalized_feature_id}")

            existing = conn.execute(
                "SELECT assigned_at FROM feature_assignments WHERE user_id = ? AND feature_id = ?",
                (user_id, normalized_feature_id),
            ).fetchone()
            resolved_assigned_at = existing["assigned_at"] if existing and existing["assigned_at"] else assigned_at_value

            conn.execute(
                """
                INSERT INTO feature_assignments (
                    user_id,
                    feature_id,
                    is_assigned,
                    metadata_json,
                    assigned_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id) DO UPDATE SET
                    is_assigned = excluded.is_assigned,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    normalized_feature_id,
                    1 if is_assigned else 0,
                    metadata_json,
                    resolved_assigned_at,
                    now,
                ),
            )
            return self._load_feature_assignment_row(conn, user_id=user_id, feature_id=normalized_feature_id) or {}

    def save_feature_assignment_metadata(
        self,
        email: str,
        feature_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            existing = conn.execute(
                """
                SELECT is_assigned, assigned_at
                FROM feature_assignments
                WHERE user_id = ? AND feature_id = ?
                LIMIT 1
                """,
                (user_id, normalized_feature_id),
            ).fetchone()
            if existing is None:
                feature = self._load_feature_row(conn, feature_id=normalized_feature_id)
                if feature is None:
                    raise KeyError(f"Unknown feature: {normalized_feature_id}")
                assigned_at = now
                is_assigned = 1
            else:
                assigned_at = existing["assigned_at"] or now
                is_assigned = 1 if bool(existing["is_assigned"]) else 0

            conn.execute(
                """
                INSERT INTO feature_assignments (
                    user_id,
                    feature_id,
                    is_assigned,
                    metadata_json,
                    assigned_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id) DO UPDATE SET
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    normalized_feature_id,
                    is_assigned,
                    metadata_json,
                    assigned_at,
                    now,
                ),
            )
            return self._load_feature_assignment_row(conn, user_id=user_id, feature_id=normalized_feature_id) or {}

    def set_user_feature_assignments(
        self,
        email: str,
        feature_ids: Iterable[str],
        *,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        requested_feature_ids = []
        seen_feature_ids: set[str] = set()
        for feature_id in feature_ids:
            normalized_feature_id = normalize_text(feature_id)
            if not normalized_feature_id or normalized_feature_id in seen_feature_ids:
                continue
            seen_feature_ids.add(normalized_feature_id)
            requested_feature_ids.append(normalized_feature_id)

        now = now_iso()
        with self._connection() as conn:
            user_id = self._resolve_user_id(conn, normalized_email, include_inactive=include_inactive)
            active_features = conn.execute(
                """
                SELECT feature_id
                FROM features
                WHERE is_active = 1
                ORDER BY sort_order ASC, feature_name ASC, feature_id ASC
                """,
            ).fetchall()
            active_feature_ids = [normalize_text(row["feature_id"]) for row in active_features if normalize_text(row["feature_id"])]
            active_feature_id_set = set(active_feature_ids)

            unknown_feature_ids = [feature_id for feature_id in requested_feature_ids if feature_id not in active_feature_id_set]
            if unknown_feature_ids:
                raise KeyError(f"Unknown feature ids: {', '.join(sorted(unknown_feature_ids))}")

            existing_rows = conn.execute(
                """
                SELECT feature_id, assigned_at, metadata_json
                FROM feature_assignments
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
            existing_assignment_data = {
                normalize_text(row["feature_id"]): {
                    "assigned_at": row["assigned_at"],
                    "metadata_json": normalize_text(row["metadata_json"]) or "{}",
                }
                for row in existing_rows
                if normalize_text(row["feature_id"])
            }

            requested_feature_id_set = set(requested_feature_ids)
            for active_feature_id in active_feature_ids:
                existing_assignment = existing_assignment_data.get(active_feature_id) or {}
                assigned_at = existing_assignment.get("assigned_at") or now
                metadata_json = normalize_text(existing_assignment.get("metadata_json")) or "{}"
                conn.execute(
                    """
                    INSERT INTO feature_assignments (
                        user_id,
                        feature_id,
                        is_assigned,
                        metadata_json,
                        assigned_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, feature_id) DO UPDATE SET
                        is_assigned = excluded.is_assigned,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        active_feature_id,
                        1 if active_feature_id in requested_feature_id_set else 0,
                        metadata_json,
                        assigned_at,
                        now,
                    ),
                )

            rows = conn.execute(
                """
                SELECT feature_id
                FROM feature_assignments
                WHERE user_id = ?
                ORDER BY updated_at DESC, feature_id ASC
                """,
                (user_id,),
            ).fetchall()

            assignments: list[dict[str, Any]] = []
            for row in rows:
                assignment = self._load_feature_assignment_row(conn, user_id=user_id, feature_id=row["feature_id"])
                if assignment is not None:
                    assignments.append(assignment)
            return assignments

    def get_assigned_feature(self, email: str, feature_id: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email or not normalized_feature_id:
            return None

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            row = conn.execute(
                """
                SELECT f.feature_id
                FROM features AS f
                INNER JOIN feature_assignments AS a
                    ON a.feature_id = f.feature_id
                WHERE a.user_id = ?
                  AND a.feature_id = ?
                  AND a.is_assigned = 1
                  AND f.is_active = 1
                LIMIT 1
                """,
                (user_id, normalized_feature_id),
            ).fetchone()
            if row is None:
                return None
            feature = self._load_feature_row(conn, feature_id=normalized_feature_id) or {}
            assignment = self._load_feature_assignment_row(conn, user_id=user_id, feature_id=normalized_feature_id)
            if assignment is not None:
                feature["assignment"] = assignment
            return feature

    def list_assigned_features(self, email: str) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return []

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            rows = conn.execute(
                """
                SELECT f.feature_id
                FROM features AS f
                INNER JOIN feature_assignments AS a
                    ON a.feature_id = f.feature_id
                WHERE a.user_id = ?
                  AND a.is_assigned = 1
                  AND f.is_active = 1
                ORDER BY f.sort_order ASC, f.feature_name ASC, f.feature_id ASC
                """,
                (user_id,),
            ).fetchall()

            features: list[dict[str, Any]] = []
            for row in rows:
                feature = self._load_feature_row(conn, feature_id=row["feature_id"])
                if feature is None:
                    continue
                assignment = self._load_feature_assignment_row(conn, user_id=user_id, feature_id=row["feature_id"])
                if assignment is not None:
                    feature["assignment"] = assignment
                features.append(feature)
        return features

    def get_whatsapp_connection_by_phone_number_id(self, phone_number_id: str) -> dict[str, Any] | None:
        normalized_phone_number_id = normalize_text(phone_number_id)
        if not normalized_phone_number_id:
            return None

        with self._connection() as conn:
            return self._load_whatsapp_connection_row(conn, phone_number_id=normalized_phone_number_id)

    def get_whatsapp_connection_by_owner_wa_id(self, owner_wa_id: str) -> dict[str, Any] | None:
        normalized_owner_wa_id = normalize_whatsapp_lookup_id(owner_wa_id)
        if not normalized_owner_wa_id:
            return None

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT u.id AS user_id
                FROM whatsapp_connections AS w
                INNER JOIN users AS u
                    ON u.id = w.user_id
                WHERE u.is_active = 1
                  AND w.owner_wa_id = ?
                ORDER BY w.updated_at DESC, u.id ASC
                LIMIT 2
                """,
                (normalized_owner_wa_id,),
            ).fetchall()
            if len(rows) != 1:
                return None
            return self._load_whatsapp_connection_row(conn, user_id=int(rows[0]["user_id"]))

    def get_whatsapp_connection_by_user_id(self, user_id: int) -> dict[str, Any] | None:
        if user_id <= 0:
            return None

        with self._connection() as conn:
            return self._load_whatsapp_connection_row(conn, user_id=user_id)

    def update_whatsapp_connection_metadata(
        self,
        *,
        email: str | None = None,
        user_id: int | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        updates = metadata_updates if isinstance(metadata_updates, dict) else {}
        if not updates:
            return self.get_whatsapp_connection_by_user_id(int(user_id or 0)) if user_id else self.get_whatsapp_connection(email or "")

        with self._connection() as conn:
            connection = None
            if user_id is not None and int(user_id) > 0:
                connection = self._load_whatsapp_connection_row(conn, user_id=int(user_id))
            elif email is not None:
                connection = self._load_whatsapp_connection_row(conn, email=email)

            if connection is None:
                return None

            current_metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
            merged_metadata = {
                **current_metadata,
                **updates,
            }

            conn.execute(
                """
                UPDATE whatsapp_connections
                SET metadata_json = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    json.dumps(merged_metadata, ensure_ascii=True, sort_keys=True),
                    now_iso(),
                    int(connection.get("userId") or 0),
                ),
            )
            return self._load_whatsapp_connection_row(conn, user_id=int(connection.get("userId") or 0))

    def list_active_feature_monitor_targets(self, feature_id: str) -> list[dict[str, Any]]:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            return []

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    u.id AS user_id,
                    u.email,
                    u.display_name,
                    u.profile_json,
                    f.prompt_json,
                    fa.metadata_json AS assignment_metadata_json,
                    act.activated_at,
                    act.updated_at AS activation_updated_at,
                    act.metadata_json AS activation_metadata_json,
                    w.phone_number_id,
                    w.access_token,
                    w.owner_wa_id,
                    w.connection_status
                FROM feature_activations AS act
                INNER JOIN users AS u
                    ON u.id = act.user_id
                INNER JOIN feature_assignments AS fa
                    ON fa.user_id = u.id AND fa.feature_id = act.feature_id
                INNER JOIN features AS f
                    ON f.feature_id = act.feature_id
                LEFT JOIN whatsapp_connections AS w
                    ON w.user_id = u.id
                WHERE u.is_active = 1
                  AND act.feature_id = ?
                  AND act.is_active = 1
                  AND fa.is_assigned = 1
                ORDER BY u.id ASC
                """,
                (normalized_feature_id,),
            ).fetchall()

            targets: list[dict[str, Any]] = []
            for row in rows:
                payload = _row_to_dict(row) or {}
                prompt_payload = _load_json_dict(payload.get("prompt_json"))
                assignment_metadata = _load_json_dict(payload.get("assignment_metadata_json"))
                activation_metadata = _load_json_dict(payload.get("activation_metadata_json"))
                settings_payload = assignment_metadata.get("settings") if isinstance(assignment_metadata.get("settings"), dict) else {}
                prompt_overrides = assignment_metadata.get("prompt") if isinstance(assignment_metadata.get("prompt"), dict) else {}
                targets.append(
                    {
                        "userId": int(payload.get("user_id") or 0),
                        "email": normalize_email(payload.get("email")),
                        "displayName": normalize_text(payload.get("display_name")),
                        "profile": normalize_user_profile(_load_json_dict(payload.get("profile_json"))),
                        "featureId": normalized_feature_id,
                        "prompt": {
                            **(prompt_payload if isinstance(prompt_payload, dict) else {}),
                            **prompt_overrides,
                        },
                        "settings": settings_payload if isinstance(settings_payload, dict) else {},
                        "settingsSavedAt": normalize_text(assignment_metadata.get("settingsSavedAt")),
                        "activatedAt": payload.get("activated_at"),
                        "activationUpdatedAt": payload.get("activation_updated_at"),
                        "activationMetadata": activation_metadata if isinstance(activation_metadata, dict) else {},
                        "phoneNumberId": normalize_text(payload.get("phone_number_id")),
                        "accessToken": normalize_text(payload.get("access_token")),
                        "accessTokenConfigured": bool(normalize_text(payload.get("access_token"))),
                        "ownerWaId": normalize_text(payload.get("owner_wa_id")),
                        "whatsappConnection": {
                            "phoneNumberId": normalize_text(payload.get("phone_number_id")),
                            "accessToken": normalize_text(payload.get("access_token")),
                            "accessTokenConfigured": bool(normalize_text(payload.get("access_token"))),
                            "ownerWaId": normalize_text(payload.get("owner_wa_id")),
                            "connectionStatus": normalize_text(payload.get("connection_status")),
                        },
                    }
                )
            return targets

    def list_active_whatsapp_reengagement_targets(self, feature_id: str) -> list[dict[str, Any]]:
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_feature_id:
            return []

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    u.id AS user_id,
                    u.email,
                    u.display_name,
                    u.profile_json,
                    w.business_account_id,
                    w.phone_number_id,
                    w.access_token,
                    w.owner_wa_id,
                    w.display_phone_number,
                    w.verified_name,
                    w.connection_status,
                    w.metadata_json,
                    w.connected_at,
                    w.last_tested_at,
                    act.activated_at,
                    act.updated_at AS activation_updated_at,
                    act.metadata_json AS activation_metadata_json,
                    assign.metadata_json AS assignment_metadata_json
                FROM feature_activations AS act
                INNER JOIN users AS u
                    ON u.id = act.user_id
                INNER JOIN whatsapp_connections AS w
                    ON w.user_id = u.id
                INNER JOIN feature_assignments AS assign
                    ON assign.user_id = u.id AND assign.feature_id = act.feature_id
                WHERE u.is_active = 1
                  AND act.feature_id = ?
                  AND act.is_active = 1
                  AND assign.is_assigned = 1
                  AND w.connection_status = 'connected'
                  AND w.phone_number_id <> ''
                  AND w.owner_wa_id <> ''
                ORDER BY u.id ASC
                """,
                (normalized_feature_id,),
            ).fetchall()

            targets: list[dict[str, Any]] = []
            for row in rows:
                payload = _row_to_dict(row) or {}
                connection_metadata = _load_json_dict(payload.get("metadata_json"))
                activation_metadata = _load_json_dict(payload.get("activation_metadata_json"))
                assignment_metadata = _load_json_dict(payload.get("assignment_metadata_json"))
                settings_payload = assignment_metadata.get("settings") if isinstance(assignment_metadata.get("settings"), dict) else {}
                targets.append(
                    {
                        "userId": int(payload.get("user_id") or 0),
                        "email": normalize_email(payload.get("email")),
                        "displayName": normalize_text(payload.get("display_name")),
                        "profile": normalize_user_profile(_load_json_dict(payload.get("profile_json"))),
                        "businessAccountId": normalize_text(payload.get("business_account_id")),
                        "phoneNumberId": normalize_text(payload.get("phone_number_id")),
                        "accessToken": normalize_text(payload.get("access_token")),
                        "accessTokenConfigured": bool(normalize_text(payload.get("access_token"))),
                        "ownerWaId": normalize_text(payload.get("owner_wa_id")),
                        "displayPhoneNumber": normalize_text(payload.get("display_phone_number")),
                        "verifiedName": normalize_text(payload.get("verified_name")),
                        "connectionStatus": normalize_text(payload.get("connection_status")),
                        "metadata": connection_metadata if isinstance(connection_metadata, dict) else {},
                        "settings": settings_payload if isinstance(settings_payload, dict) else {},
                        "connectedAt": payload.get("connected_at"),
                        "lastTestedAt": payload.get("last_tested_at"),
                        "featureId": normalized_feature_id,
                        "activatedAt": payload.get("activated_at"),
                        "activationUpdatedAt": payload.get("activation_updated_at"),
                        "activationMetadata": activation_metadata if isinstance(activation_metadata, dict) else {},
                    }
                )
            return targets

    def get_whatsapp_reengagement_target(
        self,
        email: str,
        feature_id: str,
        *,
        require_active: bool = True,
    ) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email or not normalized_feature_id:
            return None

        active_clause = ""
        if require_active:
            active_clause = """
                  AND act.is_active = 1
                  AND w.connection_status = 'connected'
                  AND w.phone_number_id <> ''
                  AND w.owner_wa_id <> ''
            """

        with self._connection() as conn:
            row = conn.execute(
                f"""
                SELECT
                    u.id AS user_id,
                    u.email,
                    u.display_name,
                    u.profile_json,
                    w.business_account_id,
                    w.phone_number_id,
                    w.access_token,
                    w.owner_wa_id,
                    w.display_phone_number,
                    w.verified_name,
                    w.connection_status,
                    w.metadata_json,
                    w.connected_at,
                    w.last_tested_at,
                    act.activated_at,
                    act.updated_at AS activation_updated_at,
                    act.metadata_json AS activation_metadata_json,
                    assign.metadata_json AS assignment_metadata_json
                FROM users AS u
                INNER JOIN feature_assignments AS assign
                    ON assign.user_id = u.id
                INNER JOIN features AS f
                    ON f.feature_id = assign.feature_id
                LEFT JOIN feature_activations AS act
                    ON act.user_id = u.id AND act.feature_id = assign.feature_id
                LEFT JOIN whatsapp_connections AS w
                    ON w.user_id = u.id
                WHERE u.is_active = 1
                  AND u.email = ?
                  AND assign.feature_id = ?
                  AND assign.is_assigned = 1
                  AND f.is_active = 1
                  {active_clause}
                LIMIT 1
                """,
                (normalized_email, normalized_feature_id),
            ).fetchone()

        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        connection_metadata = _load_json_dict(payload.get("metadata_json"))
        activation_metadata = _load_json_dict(payload.get("activation_metadata_json"))
        assignment_metadata = _load_json_dict(payload.get("assignment_metadata_json"))
        settings_payload = assignment_metadata.get("settings") if isinstance(assignment_metadata.get("settings"), dict) else {}
        return {
            "userId": int(payload.get("user_id") or 0),
            "email": normalize_email(payload.get("email")),
            "displayName": normalize_text(payload.get("display_name")),
            "profile": normalize_user_profile(_load_json_dict(payload.get("profile_json"))),
            "businessAccountId": normalize_text(payload.get("business_account_id")),
            "phoneNumberId": normalize_text(payload.get("phone_number_id")),
            "accessToken": normalize_text(payload.get("access_token")),
            "accessTokenConfigured": bool(normalize_text(payload.get("access_token"))),
            "ownerWaId": normalize_text(payload.get("owner_wa_id")),
            "displayPhoneNumber": normalize_text(payload.get("display_phone_number")),
            "verifiedName": normalize_text(payload.get("verified_name")),
            "connectionStatus": normalize_text(payload.get("connection_status")) or "not_connected",
            "metadata": connection_metadata if isinstance(connection_metadata, dict) else {},
            "settings": settings_payload if isinstance(settings_payload, dict) else {},
            "settingsSavedAt": normalize_text(assignment_metadata.get("settingsSavedAt")),
            "connectedAt": payload.get("connected_at"),
            "lastTestedAt": payload.get("last_tested_at"),
            "featureId": normalized_feature_id,
            "activatedAt": payload.get("activated_at"),
            "activationUpdatedAt": payload.get("activation_updated_at"),
            "activationMetadata": activation_metadata if isinstance(activation_metadata, dict) else {},
        }

    def scan_whatsapp_reengagement_conversations(
        self,
        *,
        user_id: int,
        cutoff_at: str | datetime,
        include_already_notified: bool = False,
    ) -> dict[str, Any]:
        if user_id <= 0:
            return {
                "conversations": [],
                "savedConversationsCount": 0,
                "skippedCounts": {
                    "missingTimestamp": 0,
                    "recentActivity": 0,
                    "alreadyNotified": 0,
                },
            }

        cutoff_moment = parse_datetime(cutoff_at).astimezone(timezone.utc)
        saved_conversations = self.list_whatsapp_conversations(user_id=user_id)
        due_conversations: list[dict[str, Any]] = []
        skipped_counts = {
            "missingTimestamp": 0,
            "recentActivity": 0,
            "alreadyNotified": 0,
        }

        for conversation in saved_conversations:
            activity_at = normalize_text(conversation.get("lastInboundAt")) or normalize_text(conversation.get("lastMessageAt"))
            if not activity_at:
                skipped_counts["missingTimestamp"] += 1
                continue

            activity_moment = parse_datetime(activity_at).astimezone(timezone.utc)
            if activity_moment > cutoff_moment:
                skipped_counts["recentActivity"] += 1
                continue

            notified_for = normalize_text(conversation.get("lastReengagementNotifiedForMessageAt"))
            if (
                not include_already_notified
                and notified_for
                and parse_datetime(notified_for).astimezone(timezone.utc) >= activity_moment
            ):
                skipped_counts["alreadyNotified"] += 1
                continue

            due_conversations.append(conversation)

        due_conversations.sort(
            key=lambda conversation: (
                parse_datetime(
                    normalize_text(conversation.get("lastInboundAt")) or normalize_text(conversation.get("lastMessageAt"))
                ).astimezone(timezone.utc),
                normalize_text(conversation.get("conversationId")),
            )
        )
        return {
            "conversations": due_conversations,
            "savedConversationsCount": len(saved_conversations),
            "skippedCounts": skipped_counts,
        }

    def list_due_whatsapp_reengagement_conversations(
        self,
        *,
        user_id: int,
        cutoff_at: str | datetime,
    ) -> list[dict[str, Any]]:
        scan = self.scan_whatsapp_reengagement_conversations(
            user_id=user_id,
            cutoff_at=cutoff_at,
        )
        return list(scan.get("conversations") or [])

    def get_whatsapp_reengagement_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str | datetime,
    ) -> dict[str, Any] | None:
        if user_id <= 0:
            return None

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        with self._connection() as conn:
            return self._load_whatsapp_reengagement_run_row(
                conn,
                user_id=int(user_id),
                feature_id=feature_id,
                scheduled_for=scheduled_for_value,
            )

    def get_latest_whatsapp_reengagement_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        before_scheduled_for: str | datetime | None = None,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0 or not normalized_feature_id:
            return None

        query = """
                SELECT scheduled_for
                FROM whatsapp_reengagement_runs
                WHERE user_id = ? AND feature_id = ?
                """
        params: list[Any] = [int(user_id), normalized_feature_id]
        if before_scheduled_for is not None:
            query += " AND scheduled_for < ?"
            params.append(parse_datetime(before_scheduled_for).astimezone(timezone.utc).isoformat())
        query += """
                ORDER BY scheduled_for DESC
                LIMIT 1
                """
        with self._connection() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        return self.get_whatsapp_reengagement_run(
            user_id=int(user_id),
            feature_id=normalized_feature_id,
            scheduled_for=row["scheduled_for"],
        )

    def claim_whatsapp_reengagement_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str | datetime,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically reserve a re-engagement slot, or return None if already taken.

        Mirrors claim_feature_monitor_run. The previous flow read the run row, did
        minutes of OpenAI drafting, sent the owner report, and only then wrote the
        marker -- so a restart or a concurrent trigger in that gap produced a
        duplicate owner report and duplicate OpenAI spend.
        """

        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO whatsapp_reengagement_runs (
                    user_id,
                    feature_id,
                    scheduled_for,
                    conversations_checked,
                    notifications_sent,
                    status,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, 0, 0, 'running', ?, ?, ?)
                ON CONFLICT(user_id, feature_id, scheduled_for) DO NOTHING
                """,
                (
                    int(user_id),
                    normalized_feature_id,
                    scheduled_for_value,
                    metadata_json,
                    now,
                    now,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            return self._load_whatsapp_reengagement_run_row(
                conn,
                user_id=int(user_id),
                feature_id=normalized_feature_id,
                scheduled_for=scheduled_for_value,
            )

    def release_stale_whatsapp_reengagement_runs(
        self,
        *,
        older_than_seconds: int = STALE_CLAIM_SECONDS,
        now: str | datetime | None = None,
    ) -> int:
        """Drop abandoned 'running' re-engagement claims so the slot can retry."""

        reference = parse_datetime(now or now_iso()).astimezone(timezone.utc)
        cutoff = (reference - timedelta(seconds=max(1, int(older_than_seconds)))).isoformat()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM whatsapp_reengagement_runs
                WHERE status = 'running'
                  AND updated_at <= ?
                """,
                (cutoff,),
            )
            return int(cursor.rowcount or 0)

    def save_whatsapp_reengagement_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str | datetime,
        conversations_checked: int = 0,
        notifications_sent: int = 0,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()

        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT id, created_at
                FROM whatsapp_reengagement_runs
                WHERE user_id = ? AND feature_id = ? AND scheduled_for = ?
                LIMIT 1
                """,
                (int(user_id), normalized_feature_id, scheduled_for_value),
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now

            conn.execute(
                """
                INSERT INTO whatsapp_reengagement_runs (
                    user_id,
                    feature_id,
                    scheduled_for,
                    conversations_checked,
                    notifications_sent,
                    status,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id, scheduled_for) DO UPDATE SET
                    conversations_checked = excluded.conversations_checked,
                    notifications_sent = excluded.notifications_sent,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    normalized_feature_id,
                    scheduled_for_value,
                    max(0, int(conversations_checked)),
                    max(0, int(notifications_sent)),
                    normalize_text(status) or "completed",
                    metadata_json,
                    created_at,
                    now,
                ),
            )
            return self._load_whatsapp_reengagement_run_row(
                conn,
                user_id=int(user_id),
                feature_id=normalized_feature_id,
                scheduled_for=scheduled_for_value,
            ) or {}

    def save_whatsapp_reengagement_notification(
        self,
        *,
        user_id: int,
        conversation_id: str,
        feature_id: str,
        scheduled_for: str | datetime,
        owner_message_id: str = "",
        draft_text: str = "",
        source: str = "",
        model_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_conversation_id = normalize_text(conversation_id)
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_conversation_id:
            raise ValueError("Conversation id is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()

        with self._connection() as conn:
            conversation = self._load_whatsapp_conversation_row(
                conn,
                user_id=int(user_id),
                conversation_id=normalized_conversation_id,
            )
            if conversation is None:
                raise KeyError(f"Unknown conversation: {normalized_conversation_id}")

            last_message_at = normalize_text(conversation.get("lastInboundAt")) or normalize_text(conversation.get("lastMessageAt"))
            if not last_message_at:
                raise ValueError("Conversation has no last message timestamp.")

            conn.execute(
                """
                INSERT INTO whatsapp_reengagement_notifications (
                    user_id,
                    conversation_id,
                    feature_id,
                    scheduled_for,
                    last_message_at,
                    owner_message_id,
                    draft_text,
                    source,
                    model_name,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    normalized_conversation_id,
                    normalized_feature_id,
                    scheduled_for_value,
                    last_message_at,
                    normalize_text(owner_message_id),
                    normalize_text(draft_text),
                    normalize_text(source),
                    normalize_text(model_name),
                    metadata_json,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE whatsapp_conversations
                SET last_reengagement_notified_at = ?,
                    last_reengagement_notified_for_message_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND conversation_id = ?
                """,
                (
                    now,
                    last_message_at,
                    now,
                    int(user_id),
                    normalized_conversation_id,
                ),
            )

            row = conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    conversation_id,
                    feature_id,
                    scheduled_for,
                    last_message_at,
                    owner_message_id,
                    draft_text,
                    source,
                    model_name,
                    metadata_json,
                    created_at
                FROM whatsapp_reengagement_notifications
                WHERE id = last_insert_rowid()
                """,
            ).fetchone()

        payload = _row_to_dict(row) or {}
        metadata_payload = _load_json_dict(payload.get("metadata_json"))
        return {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "conversationId": normalize_text(payload.get("conversation_id")),
            "featureId": normalize_text(payload.get("feature_id")),
            "scheduledFor": payload.get("scheduled_for"),
            "lastMessageAt": payload.get("last_message_at"),
            "ownerMessageId": normalize_text(payload.get("owner_message_id")),
            "draftText": normalize_text(payload.get("draft_text")),
            "source": normalize_text(payload.get("source")),
            "modelName": normalize_text(payload.get("model_name")),
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "createdAt": payload.get("created_at"),
        }

    def create_scheduled_action(
        self,
        *,
        user_id: int,
        action_type: str,
        channel: str,
        recipient_ref: str,
        run_at: str | datetime,
        timezone_name: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_action_type = normalize_text(action_type)
        normalized_channel = normalize_text(channel).lower()
        normalized_recipient_ref = normalize_text(recipient_ref)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_action_type:
            raise ValueError("Action type is required.")
        if not normalized_channel:
            raise ValueError("Channel is required.")

        run_at_value = parse_datetime(run_at).astimezone(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO scheduled_actions (
                    user_id,
                    action_type,
                    channel,
                    recipient_ref,
                    run_at,
                    timezone,
                    status,
                    attempt_count,
                    payload_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (
                    int(user_id),
                    normalized_action_type,
                    normalized_channel,
                    normalized_recipient_ref,
                    run_at_value,
                    normalize_text(timezone_name),
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM scheduled_actions WHERE id = ? LIMIT 1",
                (int(cursor.lastrowid or 0),),
            ).fetchone()

        action = self._load_scheduled_action_row(row)
        if action is None:
            raise RuntimeError("Scheduled action was not saved.")
        return action

    def get_scheduled_action(self, action_id: int) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0:
            return None

        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_actions WHERE id = ? LIMIT 1",
                (int(action_id),),
            ).fetchone()
        return self._load_scheduled_action_row(row)

    def list_scheduled_actions_for_user(
        self,
        user_id: int,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if int(user_id or 0) <= 0:
            return []

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scheduled_actions
                WHERE user_id = ?
                ORDER BY
                    CASE WHEN status IN ('pending', 'running') THEN 0 ELSE 1 END ASC,
                    CASE WHEN status IN ('pending', 'running') THEN run_at END ASC,
                    CASE WHEN status NOT IN ('pending', 'running') THEN COALESCE(completed_at, updated_at) END DESC,
                    id DESC
                LIMIT ?
                """,
                (int(user_id), max(1, min(250, int(limit or 100)))),
            ).fetchall()
        return [
            action
            for action in (self._load_scheduled_action_row(row) for row in rows)
            if action is not None
        ]

    def list_due_scheduled_actions(
        self,
        *,
        now: str | datetime | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        reference = parse_datetime(now or now_iso()).astimezone(timezone.utc).isoformat()
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scheduled_actions
                WHERE status = 'pending'
                  AND run_at <= ?
                ORDER BY run_at ASC, id ASC
                LIMIT ?
                """,
                (reference, max(1, min(100, int(limit or 25)))),
            ).fetchall()
        return [
            action
            for action in (self._load_scheduled_action_row(row) for row in rows)
            if action is not None
        ]

    def claim_scheduled_action(self, action_id: int) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0:
            return None

        now = now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE scheduled_actions
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    claimed_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'pending'
                """,
                (now, now, int(action_id)),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM scheduled_actions WHERE id = ? LIMIT 1",
                (int(action_id),),
            ).fetchone()
        return self._load_scheduled_action_row(row)

    # ------------------------------------------------------------------
    # In-app notifications
    #
    # This is the single delivery surface for everything an action produces.
    # Rows are durable and server-side, so a notification survives a tab close
    # and is visible from any device the owner signs in on.
    # ------------------------------------------------------------------

    def save_notification(
        self,
        *,
        user_id: int,
        title: str,
        body: str = "",
        kind: str = "info",
        tone: str = "info",
        source: str = "",
        feature_id: str = "",
        action_id: str = "",
        result_url: str = "",
        dedupe_key: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        """Insert a notification, or refresh the existing one with the same key.

        `dedupe_key` lets a caller be re-run safely -- a retried monitor run or a
        replayed scheduled action updates its notification in place instead of
        stacking duplicates in the feed. An updated notification is marked unread
        again so the owner sees the new state.
        """

        if int(user_id or 0) <= 0:
            raise ValueError("User id is required.")

        normalized_title = normalize_text(title)
        if not normalized_title:
            raise ValueError("Notification title is required.")

        now = parse_datetime(created_at or now_iso()).astimezone(timezone.utc).isoformat()
        normalized_dedupe = normalize_text(dedupe_key)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)

        with self._connection() as conn:
            if normalized_dedupe:
                existing = conn.execute(
                    "SELECT id FROM notifications WHERE user_id = ? AND dedupe_key = ? LIMIT 1",
                    (int(user_id), normalized_dedupe),
                ).fetchone()
                if existing is not None:
                    conn.execute(
                        """
                        UPDATE notifications
                        SET kind = ?, tone = ?, title = ?, body = ?, source = ?,
                            feature_id = ?, action_id = ?, result_url = ?,
                            metadata_json = ?, read_at = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            normalize_text(kind) or "info",
                            normalize_text(tone) or "info",
                            normalized_title,
                            body or "",
                            normalize_text(source),
                            normalize_text(feature_id),
                            normalize_text(action_id),
                            normalize_text(result_url),
                            metadata_json,
                            now,
                            int(existing["id"]),
                        ),
                    )
                    row = conn.execute(
                        "SELECT * FROM notifications WHERE id = ? LIMIT 1",
                        (int(existing["id"]),),
                    ).fetchone()
                    return self._load_notification_row(row) or {}

            cursor = conn.execute(
                """
                INSERT INTO notifications (
                    user_id, kind, tone, title, body, source, feature_id,
                    action_id, result_url, dedupe_key, metadata_json,
                    read_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    int(user_id),
                    normalize_text(kind) or "info",
                    normalize_text(tone) or "info",
                    normalized_title,
                    body or "",
                    normalize_text(source),
                    normalize_text(feature_id),
                    normalize_text(action_id),
                    normalize_text(result_url),
                    normalized_dedupe,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = ? LIMIT 1",
                (int(cursor.lastrowid or 0),),
            ).fetchone()
            return self._load_notification_row(row) or {}

    def list_notifications(
        self,
        *,
        user_id: int,
        limit: int = 50,
        unread_only: bool = False,
        before_id: int = 0,
        search: str = "",
    ) -> list[dict[str, Any]]:
        """Return one page of the feed, newest first.

        `before_id` pages backwards through the feed: pass the id of the oldest
        row already held and the next page picks up below it. Paging on the id
        rather than an offset means a notification arriving mid-scroll cannot
        shift the page boundary and hide a row.

        `search` matches title and body. Every word has to appear somewhere in
        the two, in any order, so a half-typed query still narrows the feed the
        way an autocomplete does.
        """

        if int(user_id or 0) <= 0:
            return []

        clauses = ["user_id = ?"]
        values: list[Any] = [int(user_id)]
        if unread_only:
            clauses.append("read_at IS NULL")
        if int(before_id or 0) > 0:
            clauses.append("id < ?")
            values.append(int(before_id))
        for token in notification_search_tokens(search):
            clauses.append("(LOWER(title) LIKE ? OR LOWER(body) LIKE ?)")
            pattern = f"%{token}%"
            values.extend([pattern, pattern])
        values.append(max(1, min(200, int(limit or 50))))

        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM notifications
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return [item for item in (self._load_notification_row(row) for row in rows) if item is not None]

    def count_unread_notifications(self, *, user_id: int) -> int:
        if int(user_id or 0) <= 0:
            return 0
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM notifications WHERE user_id = ? AND read_at IS NULL",
                (int(user_id),),
            ).fetchone()
        return int(row["total"] or 0) if row else 0

    def mark_notification_read(self, *, user_id: int, notification_id: int) -> dict[str, Any] | None:
        """Mark one notification read. Scoped by user_id so an id alone is not enough."""

        if int(user_id or 0) <= 0 or int(notification_id or 0) <= 0:
            return None

        now = now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE notifications
                SET read_at = COALESCE(read_at, ?), updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, now, int(notification_id), int(user_id)),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = ? LIMIT 1",
                (int(notification_id),),
            ).fetchone()
            return self._load_notification_row(row)

    def mark_all_notifications_read(self, *, user_id: int) -> int:
        if int(user_id or 0) <= 0:
            return 0
        now = now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE notifications SET read_at = ?, updated_at = ? WHERE user_id = ? AND read_at IS NULL",
                (now, now, int(user_id)),
            )
            return int(cursor.rowcount or 0)

    def requeue_stale_scheduled_actions(
        self,
        *,
        older_than_seconds: int = STALE_CLAIM_SECONDS,
        max_attempts: int = MAX_SCHEDULED_ACTION_ATTEMPTS,
        now: str | datetime | None = None,
    ) -> int:
        """Return abandoned 'running' rows to 'pending' so they are retried.

        A claim is only ever released by finish_scheduled_action, so a process that
        dies mid-dispatch -- including every redeploy, since the server uses daemon
        threads -- used to strand the row permanently and the message was never
        sent. Rows that have exhausted their attempts are failed explicitly instead
        of being retried forever.
        """

        reference = parse_datetime(now or now_iso()).astimezone(timezone.utc)
        cutoff = (reference - timedelta(seconds=max(1, int(older_than_seconds)))).isoformat()
        timestamp = reference.isoformat()

        with self._connection() as conn:
            exhausted = conn.execute(
                """
                UPDATE scheduled_actions
                SET status = 'failed',
                    last_error = 'Abandoned while running and out of retry attempts.',
                    updated_at = ?
                WHERE status = 'running'
                  AND claimed_at IS NOT NULL
                  AND claimed_at <= ?
                  AND attempt_count >= ?
                """,
                (timestamp, cutoff, max(1, int(max_attempts))),
            )
            requeued = conn.execute(
                """
                UPDATE scheduled_actions
                SET status = 'pending',
                    claimed_at = NULL,
                    updated_at = ?
                WHERE status = 'running'
                  AND claimed_at IS NOT NULL
                  AND claimed_at <= ?
                  AND attempt_count < ?
                """,
                (timestamp, cutoff, max(1, int(max_attempts))),
            )
            return int(exhausted.rowcount or 0) + int(requeued.rowcount or 0)

    def requeue_stale_source_actions(
        self,
        *,
        older_than_seconds: int = STALE_CLAIM_SECONDS,
        now: str | datetime | None = None,
    ) -> int:
        """Return abandoned 'running' source actions to 'active'."""

        reference = parse_datetime(now or now_iso()).astimezone(timezone.utc)
        cutoff = (reference - timedelta(seconds=max(1, int(older_than_seconds)))).isoformat()
        timestamp = reference.isoformat()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE source_actions
                SET status = 'active',
                    claimed_at = NULL,
                    updated_at = ?
                WHERE status = 'running'
                  AND claimed_at IS NOT NULL
                  AND claimed_at <= ?
                """,
                (timestamp, cutoff),
            )
            return int(cursor.rowcount or 0)

    def release_stale_feature_monitor_runs(
        self,
        *,
        older_than_seconds: int = STALE_CLAIM_SECONDS,
        now: str | datetime | None = None,
    ) -> int:
        """Drop abandoned 'running' monitor claims so the slot can be retried.

        The claim is the row itself, so releasing it means deleting it. Completed
        and failed runs are left untouched.
        """

        reference = parse_datetime(now or now_iso()).astimezone(timezone.utc)
        cutoff = (reference - timedelta(seconds=max(1, int(older_than_seconds)))).isoformat()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM feature_monitor_runs
                WHERE status = 'running'
                  AND updated_at <= ?
                """,
                (cutoff,),
            )
            return int(cursor.rowcount or 0)

    def finish_scheduled_action(
        self,
        *,
        action_id: int,
        status: str,
        provider_message_id: str = "",
        last_error: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        normalized_status = normalize_text(status).lower()
        if int(action_id or 0) <= 0:
            return None
        if normalized_status not in {"sent", "failed", "cancelled"}:
            raise ValueError("Scheduled action status must be sent, failed, or cancelled.")

        now = now_iso()
        fields = [
            "status = ?",
            "provider_message_id = ?",
            "last_error = ?",
            "completed_at = ?",
            "updated_at = ?",
        ]
        params: list[Any] = [
            normalized_status,
            normalize_text(provider_message_id),
            normalize_text(last_error)[:2000],
            now,
            now,
        ]
        if payload is not None:
            fields.append("payload_json = ?")
            params.append(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        params.append(int(action_id))

        with self._connection() as conn:
            conn.execute(
                f"""
                UPDATE scheduled_actions
                SET {", ".join(fields)}
                WHERE id = ?
                """,
                tuple(params),
            )
            row = conn.execute(
                "SELECT * FROM scheduled_actions WHERE id = ? LIMIT 1",
                (int(action_id),),
            ).fetchone()
        return self._load_scheduled_action_row(row)

    def update_scheduled_action_delivery_status(
        self,
        *,
        provider_message_id: str,
        status: str,
        last_error: str = "",
        event_at: str | datetime | None = None,
    ) -> dict[str, Any] | None:
        normalized_message_id = normalize_text(provider_message_id)
        normalized_status = normalize_text(status).lower()
        if not normalized_message_id or normalized_status not in {"sent", "delivered", "read", "failed"}:
            return None

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM scheduled_actions
                WHERE provider_message_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (normalized_message_id,),
            ).fetchone()
            action = self._load_scheduled_action_row(row)
            if action is None:
                return None

            current_status = normalize_text(action.get("status")).lower()
            status_rank = {"sent": 1, "delivered": 2, "read": 3, "failed": 4, "cancelled": 5}
            if status_rank.get(current_status, 0) > status_rank.get(normalized_status, 0):
                return action

            try:
                delivery_event_at = parse_datetime(event_at or now_iso()).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                delivery_event_at = now_iso()
            action_payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            next_payload = {
                **action_payload,
                "deliveryStatus": normalized_status,
                "deliveryUpdatedAt": delivery_event_at,
            }
            next_payload[f"{normalized_status}At"] = delivery_event_at
            updated_at = now_iso()
            conn.execute(
                """
                UPDATE scheduled_actions
                SET status = ?,
                    last_error = ?,
                    payload_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_status,
                    normalize_text(last_error)[:2000] if normalized_status == "failed" else "",
                    json.dumps(next_payload, ensure_ascii=True, sort_keys=True),
                    updated_at,
                    int(action.get("id") or 0),
                ),
            )
            updated_row = conn.execute(
                "SELECT * FROM scheduled_actions WHERE id = ? LIMIT 1",
                (int(action.get("id") or 0),),
            ).fetchone()
        return self._load_scheduled_action_row(updated_row)

    def _load_source_action_row(self, row: sqlite3.Row | None, *, include_bytes: bool = False) -> dict[str, Any] | None:
        payload = _row_to_dict(row)
        if not payload:
            return None
        result: dict[str, Any] = {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "sourceType": normalize_text(payload.get("source_type")),
            "sourceUrl": normalize_text(payload.get("source_url")),
            "fileName": normalize_text(payload.get("file_name")),
            "mimeType": normalize_text(payload.get("mime_type")),
            "fileSize": int(payload.get("file_size") or 0),
            "fileSha256": normalize_text(payload.get("file_sha256")),
            "label": normalize_text(payload.get("label")),
            "intervalMinutes": max(1, int(payload.get("interval_minutes") or 1440)),
            "timezone": normalize_text(payload.get("timezone")) or "UTC",
            "status": normalize_text(payload.get("status")) or "active",
            "nextRunAt": payload.get("next_run_at"),
            "lastRunAt": payload.get("last_run_at"),
            "lastRunStatus": normalize_text(payload.get("last_run_status")),
            "lastError": normalize_text(payload.get("last_error")),
            "lastHttpStatus": payload.get("last_http_status"),
            "lastContentType": normalize_text(payload.get("last_content_type")),
            "lastContentHash": normalize_text(payload.get("last_content_hash")),
            "lastContentSize": int(payload.get("last_content_size") or 0),
            "runCount": int(payload.get("run_count") or 0),
            "claimedAt": payload.get("claimed_at"),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }
        if include_bytes:
            result["fileBytes"] = payload.get("file_bytes") or b""
        return result

    def create_source_action(
        self,
        *,
        user_id: int,
        source_type: str,
        source_url: str = "",
        file_name: str = "",
        mime_type: str = "",
        file_bytes: bytes | None = None,
        label: str = "",
        interval_minutes: int = 1440,
        timezone_name: str = "UTC",
        next_run_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        normalized_type = normalize_text(source_type).lower()
        if user_id <= 0:
            raise ValueError("User id is required.")
        if normalized_type not in {"url", "file"}:
            raise ValueError("Source type must be url or file.")
        normalized_url = normalize_text(source_url)
        normalized_file_name = normalize_text(file_name)
        raw_bytes = bytes(file_bytes or b"")
        if normalized_type == "url" and not normalized_url:
            raise ValueError("Source URL is required.")
        if normalized_type == "file" and not raw_bytes:
            raise ValueError("Source file is required.")
        if not 5 <= int(interval_minutes or 0) <= 30 * 24 * 60:
            raise ValueError("Interval must be between 5 minutes and 30 days.")

        now = datetime.now(timezone.utc)
        next_run = parse_datetime(next_run_at or (now + timedelta(minutes=int(interval_minutes)))).astimezone(timezone.utc)
        created_at = now_iso()
        digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else ""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_actions (
                    user_id, source_type, source_url, file_name, mime_type,
                    file_bytes, file_size, file_sha256, label, interval_minutes,
                    timezone, status, next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    int(user_id), normalized_type, normalized_url, normalized_file_name,
                    normalize_text(mime_type), sqlite3.Binary(raw_bytes) if raw_bytes else None,
                    len(raw_bytes), digest, normalize_text(label)[:240], max(5, int(interval_minutes)),
                    normalize_text(timezone_name) or "UTC", next_run.isoformat(), created_at, created_at,
                ),
            )
            row = conn.execute("SELECT * FROM source_actions WHERE id = ? LIMIT 1", (int(cursor.lastrowid or 0),)).fetchone()
        action = self._load_source_action_row(row)
        if action is None:
            raise RuntimeError("Source action was not saved.")
        return action

    def get_source_action(self, action_id: int, *, include_bytes: bool = False) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM source_actions WHERE id = ? LIMIT 1", (int(action_id),)).fetchone()
        return self._load_source_action_row(row, include_bytes=include_bytes)

    def list_source_actions_for_user(self, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        if int(user_id or 0) <= 0:
            return []
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM source_actions
                WHERE user_id = ?
                ORDER BY CASE
                  WHEN status IN ('active', 'running') THEN 0
                  WHEN status = 'paused' THEN 1
                  ELSE 2
                END, next_run_at ASC, id DESC
                LIMIT ?
                """,
                (int(user_id), max(1, min(250, int(limit or 100)))),
            ).fetchall()
        return [item for item in (self._load_source_action_row(row) for row in rows) if item is not None]

    def list_due_source_actions(self, *, now: str | datetime | None = None, limit: int = 25) -> list[dict[str, Any]]:
        reference = parse_datetime(now or now_iso()).astimezone(timezone.utc).isoformat()
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM source_actions
                WHERE status = 'active' AND next_run_at <= ?
                ORDER BY next_run_at ASC, id ASC
                LIMIT ?
                """,
                (reference, max(1, min(100, int(limit or 25)))),
            ).fetchall()
        return [item for item in (self._load_source_action_row(row) for row in rows) if item is not None]

    def claim_source_action(self, action_id: int, *, force: bool = False) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0:
            return None
        now = now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE source_actions
                SET status = 'running', claimed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'active'{'' if force else ' AND next_run_at <= ?'}
                """,
                (now, now, int(action_id), *(() if force else (now,))),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute("SELECT * FROM source_actions WHERE id = ? LIMIT 1", (int(action_id),)).fetchone()
        return self._load_source_action_row(row)

    def finish_source_action(
        self,
        *,
        action_id: int,
        status: str,
        last_run_status: str,
        last_error: str = "",
        last_http_status: int | None = None,
        last_content_type: str = "",
        last_content_hash: str = "",
        last_content_size: int = 0,
        next_run_at: str | datetime | None = None,
    ) -> dict[str, Any] | None:
        normalized_status = normalize_text(status).lower()
        if normalized_status not in {"active", "cancelled"}:
            raise ValueError("Source action status must be active or cancelled.")
        now = now_iso()
        next_run = parse_datetime(next_run_at).astimezone(timezone.utc).isoformat() if next_run_at else None
        status_field = "status = CASE WHEN status IN ('paused', 'cancelled') THEN status ELSE ? END"
        fields = [
            status_field, "last_run_at = ?", "last_run_status = ?", "last_error = ?",
            "last_http_status = ?", "last_content_type = ?", "last_content_hash = ?",
            "last_content_size = ?", "run_count = run_count + 1", "claimed_at = NULL", "updated_at = ?",
        ]
        params: list[Any] = [normalized_status, now, normalize_text(last_run_status), normalize_text(last_error)[:2000], last_http_status, normalize_text(last_content_type)[:200], normalize_text(last_content_hash), max(0, int(last_content_size or 0)), now]
        if next_run:
            fields.insert(1, "next_run_at = ?")
            params.insert(1, next_run)
        with self._connection() as conn:
            conn.execute(f"UPDATE source_actions SET {', '.join(fields)} WHERE id = ?", (*params, int(action_id)))
            row = conn.execute("SELECT * FROM source_actions WHERE id = ? LIMIT 1", (int(action_id),)).fetchone()
        return self._load_source_action_row(row)

    def cancel_source_action(self, action_id: int, *, user_id: int) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0 or int(user_id or 0) <= 0:
            return None
        with self._connection() as conn:
            conn.execute(
                "UPDATE source_actions SET status = 'cancelled', last_error = '', updated_at = ? WHERE id = ? AND user_id = ? AND status <> 'cancelled'",
                (now_iso(), int(action_id), int(user_id)),
            )
            row = conn.execute("SELECT * FROM source_actions WHERE id = ? AND user_id = ? LIMIT 1", (int(action_id), int(user_id))).fetchone()
        return self._load_source_action_row(row)

    def pause_source_action(self, action_id: int, *, user_id: int) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0 or int(user_id or 0) <= 0:
            return None
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE source_actions
                SET status = 'paused', claimed_at = NULL, last_error = '', updated_at = ?
                WHERE id = ? AND user_id = ? AND status IN ('active', 'running')
                """,
                (now_iso(), int(action_id), int(user_id)),
            )
            row = conn.execute(
                "SELECT * FROM source_actions WHERE id = ? AND user_id = ? LIMIT 1",
                (int(action_id), int(user_id)),
            ).fetchone()
        return self._load_source_action_row(row)

    def resume_source_action(self, action_id: int, *, user_id: int) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0 or int(user_id or 0) <= 0:
            return None
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE source_actions
                SET status = 'active', claimed_at = NULL, last_error = '', updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'paused'
                """,
                (now_iso(), int(action_id), int(user_id)),
            )
            row = conn.execute(
                "SELECT * FROM source_actions WHERE id = ? AND user_id = ? LIMIT 1",
                (int(action_id), int(user_id)),
            ).fetchone()
        return self._load_source_action_row(row)

    def update_source_action_schedule(
        self,
        *,
        action_id: int,
        user_id: int,
        interval_minutes: int,
        next_run_at: str | datetime | None = None,
    ) -> dict[str, Any] | None:
        if int(action_id or 0) <= 0 or int(user_id or 0) <= 0:
            return None
        interval = int(interval_minutes or 0)
        if not 5 <= interval <= 30 * 24 * 60:
            raise ValueError("Interval must be between 5 minutes and 30 days.")
        now = datetime.now(timezone.utc)
        # A caller that names the date and hour of the next check owns the
        # schedule from there; without one the cadence starts over from now.
        next_run = (
            parse_datetime(next_run_at).astimezone(timezone.utc).isoformat()
            if next_run_at
            else (now + timedelta(minutes=interval)).isoformat()
        )
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE source_actions
                SET interval_minutes = ?, next_run_at = ?,
                    status = CASE WHEN status IN ('cancelled', 'paused') THEN status ELSE 'active' END,
                    claimed_at = NULL, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (interval, next_run, now.isoformat(), int(action_id), int(user_id)),
            )
            row = conn.execute(
                "SELECT * FROM source_actions WHERE id = ? AND user_id = ? LIMIT 1",
                (int(action_id), int(user_id)),
            ).fetchone()
        return self._load_source_action_row(row)

    def get_feature_monitor_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str | datetime,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0 or not normalized_feature_id:
            return None

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM feature_monitor_runs
                WHERE user_id = ? AND feature_id = ? AND scheduled_for = ?
                LIMIT 1
                """,
                (int(user_id), normalized_feature_id, scheduled_for_value),
            ).fetchone()
        payload = _row_to_dict(row) or {}
        if not payload:
            return None
        return {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "featureId": normalize_text(payload.get("feature_id")),
            "scheduledFor": payload.get("scheduled_for"),
            "findingsCount": int(payload.get("findings_count") or 0),
            "notificationsSent": int(payload.get("notifications_sent") or 0),
            "status": normalize_text(payload.get("status")),
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at"),
        }

    def get_latest_feature_monitor_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        before_scheduled_for: str | datetime | None = None,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0 or not normalized_feature_id:
            return None

        query = """
                SELECT scheduled_for
                FROM feature_monitor_runs
                WHERE user_id = ? AND feature_id = ?
                """
        params: list[Any] = [int(user_id), normalized_feature_id]
        if before_scheduled_for is not None:
            query += " AND scheduled_for < ?"
            params.append(parse_datetime(before_scheduled_for).astimezone(timezone.utc).isoformat())
        query += """
                ORDER BY scheduled_for DESC
                LIMIT 1
                """
        with self._connection() as conn:
            row = conn.execute(
                query,
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        return self.get_feature_monitor_run(
            user_id=int(user_id),
            feature_id=normalized_feature_id,
            scheduled_for=row["scheduled_for"],
        )

    def claim_feature_monitor_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str | datetime,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feature_monitor_runs (
                    user_id,
                    feature_id,
                    scheduled_for,
                    findings_count,
                    notifications_sent,
                    status,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, 0, 0, 'running', ?, ?, ?)
                ON CONFLICT(user_id, feature_id, scheduled_for) DO NOTHING
                """,
                (
                    int(user_id),
                    normalized_feature_id,
                    scheduled_for_value,
                    metadata_json,
                    now,
                    now,
                ),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_feature_monitor_run(
            user_id=int(user_id),
            feature_id=normalized_feature_id,
            scheduled_for=scheduled_for_value,
        )

    def save_feature_monitor_run(
        self,
        *,
        user_id: int,
        feature_id: str,
        scheduled_for: str | datetime,
        findings_count: int = 0,
        notifications_sent: int = 0,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT created_at
                FROM feature_monitor_runs
                WHERE user_id = ? AND feature_id = ? AND scheduled_for = ?
                LIMIT 1
                """,
                (int(user_id), normalized_feature_id, scheduled_for_value),
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now
            conn.execute(
                """
                INSERT INTO feature_monitor_runs (
                    user_id,
                    feature_id,
                    scheduled_for,
                    findings_count,
                    notifications_sent,
                    status,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id, scheduled_for) DO UPDATE SET
                    findings_count = excluded.findings_count,
                    notifications_sent = excluded.notifications_sent,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    normalized_feature_id,
                    scheduled_for_value,
                    max(0, int(findings_count)),
                    max(0, int(notifications_sent)),
                    normalize_text(status) or "completed",
                    metadata_json,
                    created_at,
                    now,
                ),
            )
        return self.get_feature_monitor_run(
            user_id=int(user_id),
            feature_id=normalized_feature_id,
            scheduled_for=scheduled_for_value,
        ) or {}

    def get_feature_monitor_notification(
        self,
        *,
        user_id: int,
        feature_id: str,
        item_key: str,
    ) -> dict[str, Any] | None:
        normalized_feature_id = normalize_text(feature_id)
        normalized_item_key = normalize_text(item_key)
        if user_id <= 0 or not normalized_feature_id or not normalized_item_key:
            return None

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM feature_monitor_notifications
                WHERE user_id = ? AND feature_id = ? AND item_key = ?
                LIMIT 1
                """,
                (int(user_id), normalized_feature_id, normalized_item_key),
            ).fetchone()
        payload = _row_to_dict(row) or {}
        if not payload:
            return None
        return {
            "id": int(payload.get("id") or 0),
            "userId": int(payload.get("user_id") or 0),
            "featureId": normalize_text(payload.get("feature_id")),
            "itemKey": normalize_text(payload.get("item_key")),
            "scheduledFor": payload.get("scheduled_for"),
            "deliveryChannel": normalize_text(payload.get("delivery_channel")),
            "deliveryTarget": normalize_text(payload.get("delivery_target")),
            "title": normalize_text(payload.get("title")),
            "eventDate": normalize_text(payload.get("event_date")),
            "sourceUrl": normalize_text(payload.get("source_url")),
            "sourceName": normalize_text(payload.get("source_name")),
            "messageText": normalize_text(payload.get("message_text")),
            "metadata": _load_json_dict(payload.get("metadata_json")),
            "createdAt": payload.get("created_at"),
        }

    def list_feature_monitor_notifications(
        self,
        *,
        user_id: int,
        feature_id: str,
        since_scheduled_for: str | datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        normalized_feature_id = normalize_text(feature_id)
        if user_id <= 0 or not normalized_feature_id:
            return []

        query = """
                SELECT *
                FROM feature_monitor_notifications
                WHERE user_id = ? AND feature_id = ?
                """
        params: list[Any] = [int(user_id), normalized_feature_id]
        if since_scheduled_for is not None:
            query += " AND scheduled_for >= ?"
            params.append(parse_datetime(since_scheduled_for).astimezone(timezone.utc).isoformat())
        query += """
                ORDER BY scheduled_for DESC, id DESC
                LIMIT ?
                """
        params.append(max(1, int(limit)))

        notifications: list[dict[str, Any]] = []
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        for row in rows:
            payload = _row_to_dict(row) or {}
            if not payload:
                continue
            notifications.append(
                {
                    "id": int(payload.get("id") or 0),
                    "userId": int(payload.get("user_id") or 0),
                    "featureId": normalize_text(payload.get("feature_id")),
                    "itemKey": normalize_text(payload.get("item_key")),
                    "scheduledFor": payload.get("scheduled_for"),
                    "deliveryChannel": normalize_text(payload.get("delivery_channel")),
                    "deliveryTarget": normalize_text(payload.get("delivery_target")),
                    "title": normalize_text(payload.get("title")),
                    "eventDate": normalize_text(payload.get("event_date")),
                    "sourceUrl": normalize_text(payload.get("source_url")),
                    "sourceName": normalize_text(payload.get("source_name")),
                    "messageText": normalize_text(payload.get("message_text")),
                    "metadata": _load_json_dict(payload.get("metadata_json")),
                    "createdAt": payload.get("created_at"),
                }
            )
        return notifications

    def save_feature_monitor_notification(
        self,
        *,
        user_id: int,
        feature_id: str,
        item_key: str,
        scheduled_for: str | datetime,
        delivery_channel: str = "",
        delivery_target: str = "",
        title: str = "",
        event_date: str = "",
        source_url: str = "",
        source_name: str = "",
        message_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_feature_id = normalize_text(feature_id)
        normalized_item_key = normalize_text(item_key)
        if user_id <= 0:
            raise ValueError("User id is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")
        if not normalized_item_key:
            raise ValueError("Item key is required.")

        scheduled_for_value = parse_datetime(scheduled_for).astimezone(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT created_at
                FROM feature_monitor_notifications
                WHERE user_id = ? AND feature_id = ? AND item_key = ?
                LIMIT 1
                """,
                (int(user_id), normalized_feature_id, normalized_item_key),
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now
            conn.execute(
                """
                INSERT INTO feature_monitor_notifications (
                    user_id,
                    feature_id,
                    item_key,
                    scheduled_for,
                    delivery_channel,
                    delivery_target,
                    title,
                    event_date,
                    source_url,
                    source_name,
                    message_text,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id, item_key) DO UPDATE SET
                    scheduled_for = excluded.scheduled_for,
                    delivery_channel = excluded.delivery_channel,
                    delivery_target = excluded.delivery_target,
                    title = excluded.title,
                    event_date = excluded.event_date,
                    source_url = excluded.source_url,
                    source_name = excluded.source_name,
                    message_text = excluded.message_text,
                    metadata_json = excluded.metadata_json
                """,
                (
                    int(user_id),
                    normalized_feature_id,
                    normalized_item_key,
                    scheduled_for_value,
                    normalize_text(delivery_channel),
                    normalize_text(delivery_target),
                    normalize_text(title),
                    normalize_text(event_date),
                    normalize_text(source_url),
                    normalize_text(source_name),
                    normalize_text(message_text),
                    metadata_json,
                    created_at,
                ),
            )
        return self.get_feature_monitor_notification(
            user_id=int(user_id),
            feature_id=normalized_feature_id,
            item_key=normalized_item_key,
        ) or {}

    def update_user_status(self, email: str, *, is_active: bool) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        with self._connection() as conn:
            user = self._load_user_row(conn, normalized_email)
            if user is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            user_id = int(user.get("id") or 0)
            if (
                not is_active
                and bool(user.get("isActive"))
                and bool(user.get("isAdmin"))
                and self.count_admin_users(conn) <= 1
            ):
                raise ValueError("Add another admin before disabling the last admin account.")

            now = now_iso()
            conn.execute(
                """
                UPDATE users
                SET is_active = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if is_active else 0,
                    now,
                    user_id,
                ),
            )
            if is_active:
                self._ensure_default_feature_assignments_for_user(conn, user_id)

            return self._load_user_row(conn, normalized_email) or {}

    def get_billing_customer(self, email: str, *, include_inactive: bool = False) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return None

        with self._connection() as conn:
            return self._load_billing_customer_row(
                conn,
                email=normalized_email,
                include_inactive=include_inactive,
            )

    def save_billing_customer(
        self,
        email: str,
        *,
        provider: str = "",
        external_customer_id: str = "",
        external_subscription_id: str = "",
        external_subscription_item_id: str = "",
        subscription_status: str = "",
        product_id: str = "",
        variant_id: str = "",
        checkout_url: str = "",
        customer_portal_url: str = "",
        last_checked_at: str | datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        checked_at_value = parse_datetime(last_checked_at).isoformat() if last_checked_at is not None else now

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            existing = conn.execute(
                "SELECT created_at FROM billing_customers WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now

            conn.execute(
                """
                INSERT INTO billing_customers (
                    user_id,
                    provider,
                    external_customer_id,
                    external_subscription_id,
                    external_subscription_item_id,
                    subscription_status,
                    product_id,
                    variant_id,
                    checkout_url,
                    customer_portal_url,
                    last_checked_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    provider = excluded.provider,
                    external_customer_id = excluded.external_customer_id,
                    external_subscription_id = excluded.external_subscription_id,
                    external_subscription_item_id = excluded.external_subscription_item_id,
                    subscription_status = excluded.subscription_status,
                    product_id = excluded.product_id,
                    variant_id = excluded.variant_id,
                    checkout_url = excluded.checkout_url,
                    customer_portal_url = excluded.customer_portal_url,
                    last_checked_at = excluded.last_checked_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    normalize_text(provider),
                    normalize_text(external_customer_id),
                    normalize_text(external_subscription_id),
                    normalize_text(external_subscription_item_id),
                    normalize_text(subscription_status),
                    normalize_text(product_id),
                    normalize_text(variant_id),
                    normalize_text(checkout_url),
                    normalize_text(customer_portal_url),
                    checked_at_value,
                    metadata_json,
                    created_at,
                    now,
                ),
            )

            return self._load_billing_customer_row(conn, user_id=user_id) or {}

    def get_feature_entitlement(self, email: str, feature_id: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email or not normalized_feature_id:
            return None

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            return self._load_feature_entitlement_row(conn, user_id=user_id, feature_id=normalized_feature_id)

    def save_feature_entitlement(
        self,
        email: str,
        *,
        feature_id: str,
        provider: str = "",
        external_customer_id: str = "",
        external_subscription_id: str = "",
        external_subscription_item_id: str = "",
        entitlement_status: str = "",
        product_id: str = "",
        variant_id: str = "",
        checkout_url: str = "",
        customer_portal_url: str = "",
        last_checked_at: str | datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        checked_at_value = parse_datetime(last_checked_at).isoformat() if last_checked_at is not None else now

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            feature = self._load_feature_row(conn, feature_id=normalized_feature_id)
            if feature is None:
                raise KeyError(f"Unknown feature: {normalized_feature_id}")

            existing = conn.execute(
                "SELECT created_at FROM feature_entitlements WHERE user_id = ? AND feature_id = ?",
                (user_id, normalized_feature_id),
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now

            conn.execute(
                """
                INSERT INTO feature_entitlements (
                    user_id,
                    feature_id,
                    provider,
                    external_customer_id,
                    external_subscription_id,
                    external_subscription_item_id,
                    entitlement_status,
                    product_id,
                    variant_id,
                    checkout_url,
                    customer_portal_url,
                    last_checked_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id) DO UPDATE SET
                    provider = excluded.provider,
                    external_customer_id = excluded.external_customer_id,
                    external_subscription_id = excluded.external_subscription_id,
                    external_subscription_item_id = excluded.external_subscription_item_id,
                    entitlement_status = excluded.entitlement_status,
                    product_id = excluded.product_id,
                    variant_id = excluded.variant_id,
                    checkout_url = excluded.checkout_url,
                    customer_portal_url = excluded.customer_portal_url,
                    last_checked_at = excluded.last_checked_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    normalized_feature_id,
                    normalize_text(provider),
                    normalize_text(external_customer_id),
                    normalize_text(external_subscription_id),
                    normalize_text(external_subscription_item_id),
                    normalize_text(entitlement_status),
                    normalize_text(product_id),
                    normalize_text(variant_id),
                    normalize_text(checkout_url),
                    normalize_text(customer_portal_url),
                    checked_at_value,
                    metadata_json,
                    created_at,
                    now,
                ),
            )
            return self._load_feature_entitlement_row(conn, user_id=user_id, feature_id=normalized_feature_id) or {}

    def list_feature_entitlements(self, email: str) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return []

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            rows = conn.execute(
                """
                SELECT feature_id
                FROM feature_entitlements
                WHERE user_id = ?
                ORDER BY updated_at DESC, feature_id ASC
                """,
                (user_id,),
            ).fetchall()

            entitlements: list[dict[str, Any]] = []
            for row in rows:
                record = self._load_feature_entitlement_row(conn, user_id=user_id, feature_id=row["feature_id"])
                if record is not None:
                    entitlements.append(record)
        return entitlements

    def get_feature_activation(self, email: str, feature_id: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email or not normalized_feature_id:
            return None

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            return self._load_feature_activation_row(conn, user_id=user_id, feature_id=normalized_feature_id)

    def list_feature_activations(self, email: str) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return []

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            rows = conn.execute(
                """
                SELECT feature_id
                FROM feature_activations
                WHERE user_id = ?
                ORDER BY updated_at DESC, feature_id ASC
                """,
                (user_id,),
            ).fetchall()

            activations: list[dict[str, Any]] = []
            for row in rows:
                record = self._load_feature_activation_row(conn, user_id=user_id, feature_id=row["feature_id"])
                if record is not None:
                    activations.append(record)

        return activations

    def save_whatsapp_connection(
        self,
        email: str,
        *,
        business_account_id: str = "",
        phone_number_id: str = "",
        access_token: str | None = None,
        owner_wa_id: str = "",
        display_phone_number: str = "",
        verified_name: str = "",
        connection_status: str = "configured",
        metadata: dict[str, Any] | None = None,
        connected_at: str | datetime | None = None,
        tested_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        connected_at_value = parse_datetime(connected_at).isoformat() if connected_at is not None else None
        tested_at_value = parse_datetime(tested_at).isoformat() if tested_at is not None else now

        with self._connection() as conn:
            user_row = conn.execute(
                "SELECT id FROM users WHERE email = ? AND is_active = 1",
                (normalized_email,),
            ).fetchone()
            if user_row is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            user_id = int(user_row["id"])
            existing = conn.execute(
                "SELECT created_at, connected_at, access_token, access_token_ciphertext FROM whatsapp_connections WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            created_at = existing["created_at"] if existing and existing["created_at"] else now
            resolved_connected_at = (
                connected_at_value
                or (existing["connected_at"] if existing and existing["connected_at"] else None)
                or now
            )
            resolved_access_token = normalize_text(access_token)
            if access_token is None and existing is not None:
                resolved_access_token = normalize_text(existing["access_token"])
                if not resolved_access_token and self.credential_vault is not None:
                    ciphertext = normalize_text(existing["access_token_ciphertext"])
                    if ciphertext:
                        try:
                            resolved_access_token = normalize_text(self.credential_vault.decrypt(ciphertext))
                        except Exception:
                            resolved_access_token = ""

            stored_access_token = resolved_access_token
            stored_access_token_ciphertext = ""
            stored_access_token_key_version = "1"
            stored_access_token_fingerprint = ""
            if self.credential_vault is not None and resolved_access_token:
                stored_access_token_ciphertext = self.credential_vault.encrypt(resolved_access_token)
                stored_access_token_key_version = self.credential_vault.key_version
                stored_access_token_fingerprint = self.credential_vault.fingerprint(resolved_access_token)
                stored_access_token = ""

            conn.execute(
                """
                INSERT INTO whatsapp_connections (
                    user_id,
                    business_account_id,
                    phone_number_id,
                    access_token,
                    access_token_ciphertext,
                    access_token_key_version,
                    access_token_fingerprint,
                    owner_wa_id,
                    display_phone_number,
                    verified_name,
                    connection_status,
                    metadata_json,
                    connected_at,
                    last_tested_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    business_account_id = excluded.business_account_id,
                    phone_number_id = excluded.phone_number_id,
                    access_token = excluded.access_token,
                    access_token_ciphertext = excluded.access_token_ciphertext,
                    access_token_key_version = excluded.access_token_key_version,
                    access_token_fingerprint = excluded.access_token_fingerprint,
                    owner_wa_id = excluded.owner_wa_id,
                    display_phone_number = excluded.display_phone_number,
                    verified_name = excluded.verified_name,
                    connection_status = excluded.connection_status,
                    metadata_json = excluded.metadata_json,
                    connected_at = excluded.connected_at,
                    last_tested_at = excluded.last_tested_at,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    normalize_text(business_account_id),
                    normalize_text(phone_number_id),
                    stored_access_token,
                    stored_access_token_ciphertext,
                    stored_access_token_key_version,
                    stored_access_token_fingerprint,
                    normalize_whatsapp_lookup_id(owner_wa_id),
                    normalize_text(display_phone_number),
                    normalize_text(verified_name),
                    normalize_text(connection_status) or "configured",
                    metadata_json,
                    resolved_connected_at,
                    tested_at_value,
                    created_at,
                    now,
                ),
            )

            return self._load_whatsapp_connection_row(conn, user_id=user_id) or {}

    def set_feature_activation(
        self,
        email: str,
        *,
        feature_id: str,
        feature_name: str = "",
        is_active: bool,
        metadata: dict[str, Any] | None = None,
        activated_at: str | datetime | None = None,
        deactivated_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            existing = conn.execute(
                "SELECT created_at, activated_at, deactivated_at FROM feature_activations WHERE user_id = ? AND feature_id = ?",
                (user_id, normalized_feature_id),
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now
            activated_at_value = (
                parse_datetime(activated_at).isoformat() if activated_at is not None
                else (
                    (existing["activated_at"] if existing and existing["activated_at"] and bool(is_active) else None)
                    or (now if bool(is_active) else None)
                )
            )
            deactivated_at_value = (
                parse_datetime(deactivated_at).isoformat() if deactivated_at is not None
                else (now if not bool(is_active) else None)
            )

            conn.execute(
                """
                INSERT INTO feature_activations (
                    user_id,
                    feature_id,
                    feature_name,
                    is_active,
                    activated_at,
                    deactivated_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, feature_id) DO UPDATE SET
                    feature_name = excluded.feature_name,
                    is_active = excluded.is_active,
                    activated_at = excluded.activated_at,
                    deactivated_at = excluded.deactivated_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    normalized_feature_id,
                    normalize_text(feature_name),
                    1 if is_active else 0,
                    activated_at_value,
                    deactivated_at_value,
                    metadata_json,
                    created_at,
                    now,
                ),
            )

            return self._load_feature_activation_row(conn, user_id=user_id, feature_id=normalized_feature_id) or {}

    def record_feature_activation_event(
        self,
        email: str,
        *,
        feature_id: str,
        feature_name: str = "",
        event_name: str,
        outcome: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        normalized_event_name = normalize_text(event_name)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_feature_id:
            raise ValueError("Feature id is required.")
        if not normalized_event_name:
            raise ValueError("Event name is required.")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True)
        now = now_iso()
        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            conn.execute(
                """
                INSERT INTO feature_activation_events (
                    user_id,
                    feature_id,
                    feature_name,
                    event_name,
                    outcome,
                    reason,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    normalized_feature_id,
                    normalize_text(feature_name),
                    normalized_event_name,
                    normalize_text(outcome),
                    normalize_text(reason),
                    metadata_json,
                    now,
                ),
            )
            event_id = int(conn.execute("SELECT last_insert_rowid() AS event_id").fetchone()["event_id"])
            row = conn.execute(
                """
                SELECT
                    e.id,
                    e.feature_id,
                    e.feature_name,
                    e.event_name,
                    e.outcome,
                    e.reason,
                    e.metadata_json,
                    e.created_at,
                    u.email
                FROM feature_activation_events AS e
                INNER JOIN users AS u
                    ON u.id = e.user_id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()

        payload = _row_to_dict(row) or {}
        metadata_blob = payload.get("metadata_json")
        try:
            metadata_payload = json.loads(metadata_blob) if metadata_blob else {}
        except json.JSONDecodeError:
            metadata_payload = {}

        return {
            "id": int(payload.get("id") or 0),
            "email": normalize_email(payload.get("email")),
            "featureId": normalize_text(payload.get("feature_id")),
            "featureName": normalize_text(payload.get("feature_name")),
            "eventName": normalize_text(payload.get("event_name")),
            "outcome": normalize_text(payload.get("outcome")),
            "reason": normalize_text(payload.get("reason")),
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
            "createdAt": payload.get("created_at"),
        }

    def list_feature_activation_events(self, email: str, feature_id: str = "") -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        normalized_feature_id = normalize_text(feature_id)
        if not normalized_email:
            return []

        with self._connection() as conn:
            user_id = self._resolve_active_user_id(conn, normalized_email)
            params: list[Any] = [user_id]
            query = """
                SELECT
                    e.id,
                    e.feature_id,
                    e.feature_name,
                    e.event_name,
                    e.outcome,
                    e.reason,
                    e.metadata_json,
                    e.created_at,
                    u.email
                FROM feature_activation_events AS e
                INNER JOIN users AS u
                    ON u.id = e.user_id
                WHERE e.user_id = ?
            """
            if normalized_feature_id:
                query += " AND e.feature_id = ?"
                params.append(normalized_feature_id)
            query += " ORDER BY e.created_at DESC, e.id DESC"

            rows = conn.execute(query, tuple(params)).fetchall()

        events: list[dict[str, Any]] = []
        for row in rows:
            payload = _row_to_dict(row) or {}
            metadata_blob = payload.get("metadata_json")
            try:
                metadata_payload = json.loads(metadata_blob) if metadata_blob else {}
            except json.JSONDecodeError:
                metadata_payload = {}
            events.append(
                {
                    "id": int(payload.get("id") or 0),
                    "email": normalize_email(payload.get("email")),
                    "featureId": normalize_text(payload.get("feature_id")),
                    "featureName": normalize_text(payload.get("feature_name")),
                    "eventName": normalize_text(payload.get("event_name")),
                    "outcome": normalize_text(payload.get("outcome")),
                    "reason": normalize_text(payload.get("reason")),
                    "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
                    "createdAt": payload.get("created_at"),
                }
            )

        return events

    def map_whatsapp_approval(
        self,
        approval_id: str,
        *,
        email: str | None = None,
        user_id: int | None = None,
        phone_number_id: str = "",
    ) -> dict[str, Any]:
        normalized_approval_id = normalize_text(approval_id)
        if not normalized_approval_id:
            raise ValueError("Approval id is required.")

        resolved_user_id = int(user_id or 0)
        now = now_iso()

        with self._connection() as conn:
            if resolved_user_id <= 0:
                normalized_email = normalize_email(email)
                if not normalized_email:
                    raise ValueError("Email or user id is required.")
                user_row = conn.execute(
                    "SELECT id FROM users WHERE email = ? AND is_active = 1",
                    (normalized_email,),
                ).fetchone()
                if user_row is None:
                    raise KeyError(f"Unknown user: {normalized_email}")
                resolved_user_id = int(user_row["id"])

            conn.execute(
                """
                INSERT INTO whatsapp_approval_index (
                    approval_id,
                    user_id,
                    phone_number_id,
                    created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    phone_number_id = excluded.phone_number_id
                """,
                (
                    normalized_approval_id,
                    resolved_user_id,
                    normalize_text(phone_number_id),
                    now,
                ),
            )

            row = conn.execute(
                """
                SELECT
                    i.approval_id,
                    i.user_id,
                    i.phone_number_id,
                    i.created_at,
                    u.email
                FROM whatsapp_approval_index AS i
                INNER JOIN users AS u
                    ON u.id = i.user_id
                WHERE i.approval_id = ?
                """,
                (normalized_approval_id,),
            ).fetchone()

        payload = _row_to_dict(row) or {}
        return {
            "approvalId": normalize_text(payload.get("approval_id")),
            "userId": int(payload.get("user_id") or 0),
            "phoneNumberId": normalize_text(payload.get("phone_number_id")),
            "createdAt": payload.get("created_at"),
            "email": normalize_email(payload.get("email")),
        }

    def get_whatsapp_approval_owner(self, approval_id: str) -> dict[str, Any] | None:
        normalized_approval_id = normalize_text(approval_id)
        if not normalized_approval_id:
            return None

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    i.approval_id,
                    i.user_id,
                    i.phone_number_id,
                    i.created_at,
                    u.email
                FROM whatsapp_approval_index AS i
                INNER JOIN users AS u
                    ON u.id = i.user_id
                WHERE i.approval_id = ?
                LIMIT 1
                """,
                (normalized_approval_id,),
            ).fetchone()

        if row is None:
            return None

        payload = _row_to_dict(row) or {}
        return {
            "approvalId": normalize_text(payload.get("approval_id")),
            "userId": int(payload.get("user_id") or 0),
            "phoneNumberId": normalize_text(payload.get("phone_number_id")),
            "createdAt": payload.get("created_at"),
            "email": normalize_email(payload.get("email")),
        }

    def record_usage(
        self,
        email: str,
        model_name: str,
        *,
        tool_id: str | None = None,
        used_at: str | datetime | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        input_price_cents_per_1k_tokens: float | None = None,
        output_price_cents_per_1k_tokens: float | None = None,
        input_token_price_multiplier: float | None = None,
        output_token_price_multiplier: float | None = None,
        currency: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        normalized_model_name = normalize_text(model_name)
        if not normalized_email:
            raise ValueError("Email is required.")
        if not normalized_model_name:
            raise ValueError("Model name is required.")

        moment = parse_datetime(used_at) if used_at is not None else datetime.now(timezone.utc)
        billing_month = month_key_for(moment)
        metadata_payload = dict(metadata or {}) if isinstance(metadata, dict) else {}
        resolved_tool_id, resolved_tool_name = extract_tool_context(metadata_payload, tool_id)
        metadata_payload.setdefault("tool_id", resolved_tool_id)
        metadata_payload.setdefault("tool_name", resolved_tool_name)
        metadata_json = json.dumps(metadata_payload, ensure_ascii=True, sort_keys=True)
        now = now_iso()

        with self._connection() as conn:
            user_row = conn.execute(
                "SELECT id FROM users WHERE email = ? AND is_active = 1",
                (normalized_email,),
            ).fetchone()
            if user_row is None:
                raise KeyError(f"Unknown user: {normalized_email}")

            billing_row = conn.execute(
                """
                SELECT currency, monthly_minimum_cents, input_token_price_multiplier, output_token_price_multiplier
                FROM user_billing
                WHERE user_id = ?
                """,
                (int(user_row["id"]),),
            ).fetchone()
            plan_currency = normalize_text(currency) or (
                billing_row["currency"] if billing_row and billing_row["currency"] else self.default_billing_plan.currency
            )
            plan_input_multiplier = float(
                input_token_price_multiplier
                if input_token_price_multiplier is not None
                else (billing_row["input_token_price_multiplier"] if billing_row else self.default_billing_plan.input_token_price_multiplier)
            )
            plan_output_multiplier = float(
                output_token_price_multiplier
                if output_token_price_multiplier is not None
                else (billing_row["output_token_price_multiplier"] if billing_row else self.default_billing_plan.output_token_price_multiplier)
            )

            price_row = self.get_model_price(normalized_model_name)
            if price_row is None:
                if input_price_cents_per_1k_tokens is None and output_price_cents_per_1k_tokens is None:
                    raise ValueError(f"Unknown model price for {normalized_model_name}.")

            plan_input_price = (
                input_price_cents_per_1k_tokens
                if input_price_cents_per_1k_tokens is not None
                else (price_row["input_price_cents_per_1k_tokens"] if price_row else 0.0)
            )
            plan_output_price = (
                output_price_cents_per_1k_tokens
                if output_price_cents_per_1k_tokens is not None
                else (price_row["output_price_cents_per_1k_tokens"] if price_row else 0.0)
            )

            input_charge_cents = calculate_charge_cents(input_tokens, plan_input_price, plan_input_multiplier)
            output_charge_cents = calculate_charge_cents(output_tokens, plan_output_price, plan_output_multiplier)
            raw_charge_cents = (input_charge_cents + output_charge_cents).quantize(RAW_CENTS_QUANT, rounding=ROUND_HALF_UP)

            conn.execute(
                """
                INSERT INTO usage_events (
                    user_id,
                    tool_id,
                    model_name,
                    billing_month,
                    used_at,
                    input_tokens,
                    output_tokens,
                    input_price_cents_per_1k_tokens,
                    output_price_cents_per_1k_tokens,
                    input_token_price_multiplier,
                    output_token_price_multiplier,
                    input_charge_cents,
                    output_charge_cents,
                    raw_charge_cents,
                    currency,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_row["id"]),
                    resolved_tool_id,
                    normalized_model_name,
                    billing_month,
                    moment.astimezone(timezone.utc).isoformat(),
                    max(0, int(input_tokens)),
                    max(0, int(output_tokens)),
                    float(plan_input_price),
                    float(plan_output_price),
                    float(plan_input_multiplier),
                    float(plan_output_multiplier),
                    float(input_charge_cents),
                    float(output_charge_cents),
                    float(raw_charge_cents),
                    plan_currency,
                    metadata_json,
                    now,
                ),
            )
            event_id = int(conn.execute("SELECT last_insert_rowid() AS event_id").fetchone()["event_id"])
            row = conn.execute("SELECT * FROM usage_events WHERE id = ?", (event_id,)).fetchone()

        result = _row_to_dict(row) or {}
        result.update(
            {
                "email": normalized_email,
                "toolId": resolved_tool_id,
                "toolName": resolved_tool_name,
                "model": normalized_model_name,
                "usedAt": result.get("used_at"),
                "billingMonth": result.get("billing_month"),
                "inputTokens": int(result.get("input_tokens") or 0),
                "outputTokens": int(result.get("output_tokens") or 0),
                "inputPriceCentsPer1kTokens": float(result.get("input_price_cents_per_1k_tokens") or 0),
                "outputPriceCentsPer1kTokens": float(result.get("output_price_cents_per_1k_tokens") or 0),
                "inputTokenPriceMultiplier": float(result.get("input_token_price_multiplier") or 1),
                "outputTokenPriceMultiplier": float(result.get("output_token_price_multiplier") or 1),
                "inputChargeCents": float(result.get("input_charge_cents") or 0),
                "outputChargeCents": float(result.get("output_charge_cents") or 0),
                "rawChargeCents": float(result.get("raw_charge_cents") or 0),
                "currency": normalize_text(result.get("currency")) or plan_currency,
                "metadata": json.loads(result.get("metadata_json") or "{}"),
            }
        )
        return result

    def list_usage_events(self, email: str) -> list[dict[str, Any]]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return []

        with self._connection() as conn:
            user_row = conn.execute(
                "SELECT id FROM users WHERE email = ? AND is_active = 1",
                (normalized_email,),
            ).fetchone()
            if user_row is None:
                return []

            rows = conn.execute(
                """
                SELECT *
                FROM usage_events
                WHERE user_id = ?
                ORDER BY used_at ASC, id ASC
                """,
                (int(user_row["id"]),),
            ).fetchall()

        events: list[dict[str, Any]] = []
        for row in rows:
            payload = _row_to_dict(row) or {}
            metadata = json.loads(payload.get("metadata_json") or "{}")
            resolved_tool_id, resolved_tool_name = extract_tool_context(metadata, payload.get("tool_id"))
            payload.update(
                {
                    "email": normalized_email,
                    "toolId": resolved_tool_id,
                    "toolName": resolved_tool_name,
                    "model": payload.get("model_name"),
                    "usedAt": payload.get("used_at"),
                    "billingMonth": payload.get("billing_month"),
                    "inputTokens": int(payload.get("input_tokens") or 0),
                    "outputTokens": int(payload.get("output_tokens") or 0),
                    "inputPriceCentsPer1kTokens": float(payload.get("input_price_cents_per_1k_tokens") or 0),
                    "outputPriceCentsPer1kTokens": float(payload.get("output_price_cents_per_1k_tokens") or 0),
                    "inputTokenPriceMultiplier": float(payload.get("input_token_price_multiplier") or 1),
                    "outputTokenPriceMultiplier": float(payload.get("output_token_price_multiplier") or 1),
                    "inputChargeCents": float(payload.get("input_charge_cents") or 0),
                    "outputChargeCents": float(payload.get("output_charge_cents") or 0),
                    "rawChargeCents": float(payload.get("raw_charge_cents") or 0),
                    "currency": normalize_text(payload.get("currency")) or self.default_billing_plan.currency,
                    "metadata": metadata,
                }
            )
            payload.pop("metadata_json", None)
            events.append(payload)

        return events

    def build_billing_report(
        self,
        email: str,
        *,
        reference_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return None

        with self._connection() as conn:
            user = self._load_user_row(conn, normalized_email)
            if user is None:
                return None

            events = self.list_usage_events(normalized_email)

        billing = user["billing"]
        currency = normalize_text(billing.get("currency")) or self.default_billing_plan.currency
        minimum_monthly_cents = int(billing.get("monthlyMinimumCents") or self.default_billing_plan.monthly_minimum_cents)

        month_rows: dict[str, dict[str, Any]] = {}
        for event in events:
            month_key = normalize_text(event.get("billingMonth")) or month_key_for(parse_datetime(event.get("usedAt")))
            tool_id = normalize_text(event.get("toolId") or event.get("tool_id") or event.get("metadata", {}).get("tool_id")) or "unassigned"
            tool_name = normalize_text(event.get("toolName") or event.get("tool_name") or event.get("metadata", {}).get("tool_name")) or humanize_identifier(tool_id)
            month_row = month_rows.setdefault(
                month_key,
                {
                    "month": month_key,
                    "label": month_label(month_key),
                    "tokensUsed": 0,
                    "inputTokensUsed": 0,
                    "outputTokensUsed": 0,
                    "baseCostCents": Decimal("0"),
                    "inputChargeCents": Decimal("0"),
                    "outputChargeCents": Decimal("0"),
                    "currency": currency,
                    "usageCount": 0,
                    "usageDates": set(),
                    "toolsById": {},
                },
            )

            tool_row = month_row["toolsById"].setdefault(
                tool_id,
                {
                    "toolId": tool_id,
                    "toolName": tool_name,
                    "tokensUsed": 0,
                    "inputTokensUsed": 0,
                    "outputTokensUsed": 0,
                    "baseCostCents": Decimal("0"),
                    "inputChargeCents": Decimal("0"),
                    "outputChargeCents": Decimal("0"),
                    "usageCount": 0,
                    "usageDates": set(),
                    "firstUsedAt": None,
                    "lastUsedAt": None,
                    "modelsByName": {},
                },
            )

            model_name = normalize_text(event.get("model")) or "Unknown model"
            model_row = tool_row["modelsByName"].setdefault(
                model_name,
                {
                    "model": model_name,
                    "tokensUsed": 0,
                    "inputTokensUsed": 0,
                    "outputTokensUsed": 0,
                    "baseCostCents": Decimal("0"),
                    "inputChargeCents": Decimal("0"),
                    "outputChargeCents": Decimal("0"),
                    "usageCount": 0,
                    "usageDates": set(),
                    "firstUsedAt": None,
                    "lastUsedAt": None,
                },
            )

            used_at = parse_datetime(event.get("usedAt"))
            usage_date = used_at.astimezone().strftime("%Y-%m-%d")
            input_tokens = max(0, int(event.get("inputTokens") or 0))
            output_tokens = max(0, int(event.get("outputTokens") or 0))
            input_charge = to_decimal(event.get("inputChargeCents"))
            output_charge = to_decimal(event.get("outputChargeCents"))
            input_base_cost = calculate_charge_cents(
                input_tokens,
                event.get("inputPriceCentsPer1kTokens"),
                1,
            )
            output_base_cost = calculate_charge_cents(
                output_tokens,
                event.get("outputPriceCentsPer1kTokens"),
                1,
            )
            base_cost = input_base_cost + output_base_cost

            month_row["tokensUsed"] += input_tokens + output_tokens
            month_row["inputTokensUsed"] += input_tokens
            month_row["outputTokensUsed"] += output_tokens
            month_row["baseCostCents"] += base_cost
            month_row["inputChargeCents"] += input_charge
            month_row["outputChargeCents"] += output_charge
            month_row["usageCount"] += 1
            month_row["usageDates"].add(usage_date)

            tool_row["tokensUsed"] += input_tokens + output_tokens
            tool_row["inputTokensUsed"] += input_tokens
            tool_row["outputTokensUsed"] += output_tokens
            tool_row["baseCostCents"] += base_cost
            tool_row["inputChargeCents"] += input_charge
            tool_row["outputChargeCents"] += output_charge
            tool_row["usageCount"] += 1
            tool_row["usageDates"].add(usage_date)
            tool_row["firstUsedAt"] = (
                used_at.isoformat()
                if tool_row["firstUsedAt"] is None or used_at < parse_datetime(tool_row["firstUsedAt"])
                else tool_row["firstUsedAt"]
            )
            tool_row["lastUsedAt"] = (
                used_at.isoformat()
                if tool_row["lastUsedAt"] is None or used_at > parse_datetime(tool_row["lastUsedAt"])
                else tool_row["lastUsedAt"]
            )

            model_row["tokensUsed"] += input_tokens + output_tokens
            model_row["inputTokensUsed"] += input_tokens
            model_row["outputTokensUsed"] += output_tokens
            model_row["baseCostCents"] += base_cost
            model_row["inputChargeCents"] += input_charge
            model_row["outputChargeCents"] += output_charge
            model_row["usageCount"] += 1
            model_row["usageDates"].add(usage_date)
            model_row["firstUsedAt"] = (
                used_at.isoformat()
                if model_row["firstUsedAt"] is None or used_at < parse_datetime(model_row["firstUsedAt"])
                else model_row["firstUsedAt"]
            )
            model_row["lastUsedAt"] = (
                used_at.isoformat()
                if model_row["lastUsedAt"] is None or used_at > parse_datetime(model_row["lastUsedAt"])
                else model_row["lastUsedAt"]
            )

        summaries: list[dict[str, Any]] = []
        minimum_cents_decimal = Decimal(minimum_monthly_cents)
        for month_key, month_row in month_rows.items():
            tool_rows: list[dict[str, Any]] = []
            for tool_row in month_row.pop("toolsById").values():
                tool_base_total = tool_row["baseCostCents"]
                tool_charge_total = tool_row["inputChargeCents"] + tool_row["outputChargeCents"]
                tool_row["baseCostUsd"] = cents_to_usd(tool_base_total)
                tool_row["chargeUsd"] = cents_to_usd(tool_charge_total)
                tool_row["minimumApplied"] = False
                tool_row["usageDates"] = sorted(tool_row["usageDates"])

                model_rows: list[dict[str, Any]] = []
                for model_row in tool_row.pop("modelsByName").values():
                    model_raw_total = model_row["baseCostCents"]
                    model_row["baseCostUsd"] = cents_to_usd(model_raw_total)
                    model_row["inputChargeUsd"] = cents_to_usd(model_row["inputChargeCents"])
                    model_row["outputChargeUsd"] = cents_to_usd(model_row["outputChargeCents"])
                    model_row["chargeUsd"] = cents_to_usd(model_row["inputChargeCents"] + model_row["outputChargeCents"])
                    model_row["usageDates"] = sorted(model_row["usageDates"])
                    model_rows.append(
                        {
                            "model": model_row["model"],
                            "tokensUsed": int(model_row["tokensUsed"]),
                            "inputTokensUsed": int(model_row["inputTokensUsed"]),
                            "outputTokensUsed": int(model_row["outputTokensUsed"]),
                            "baseCostUsd": round(float(model_row["baseCostUsd"]), 2),
                            "inputChargeUsd": round(float(model_row["inputChargeUsd"]), 2),
                            "outputChargeUsd": round(float(model_row["outputChargeUsd"]), 2),
                            "chargeUsd": round(float(model_row["chargeUsd"]), 2),
                            "usageCount": int(model_row["usageCount"]),
                            "usageDates": list(model_row["usageDates"]),
                            "firstUsedAt": model_row["firstUsedAt"],
                            "lastUsedAt": model_row["lastUsedAt"],
                        }
                    )

                model_rows.sort(key=lambda row: (-row["tokensUsed"], str(row["model"]).lower()))
                tool_rows.append(
                    {
                        "toolId": tool_row["toolId"],
                        "toolName": tool_row["toolName"],
                        "tokensUsed": int(tool_row["tokensUsed"]),
                        "inputTokensUsed": int(tool_row["inputTokensUsed"]),
                        "outputTokensUsed": int(tool_row["outputTokensUsed"]),
                        "baseCostUsd": round(float(tool_row["baseCostUsd"]), 2),
                        "inputChargeUsd": round(float(cents_to_usd(tool_row["inputChargeCents"])), 2),
                        "outputChargeUsd": round(float(cents_to_usd(tool_row["outputChargeCents"])), 2),
                        "chargeUsd": round(float(tool_row["chargeUsd"]), 2),
                        "minimumApplied": bool(tool_row["minimumApplied"]),
                        "usageCount": int(tool_row["usageCount"]),
                        "usageDates": list(tool_row["usageDates"]),
                        "firstUsedAt": tool_row["firstUsedAt"],
                        "lastUsedAt": tool_row["lastUsedAt"],
                        "models": model_rows,
                    }
                )

            tool_rows.sort(key=lambda row: (-row["tokensUsed"], str(row["toolName"]).lower()))
            month_raw_total = month_row["baseCostCents"]
            month_usage_charge_cents = month_row["inputChargeCents"] + month_row["outputChargeCents"]
            month_charge_cents = month_usage_charge_cents if month_usage_charge_cents >= minimum_cents_decimal else minimum_cents_decimal
            month_row["baseCostUsd"] = cents_to_usd(month_raw_total)
            month_row["chargeUsd"] = cents_to_usd(month_charge_cents)
            month_row["usageChargeUsd"] = cents_to_usd(month_usage_charge_cents)
            month_row["minimumApplied"] = month_charge_cents > month_usage_charge_cents
            month_row["usageDates"] = sorted(month_row["usageDates"])
            flat_models = [model for tool in tool_rows for model in tool["models"]]

            summaries.append(
                {
                    "month": month_key,
                    "label": month_row["label"],
                    "tokensUsed": int(month_row["tokensUsed"]),
                    "inputTokensUsed": int(month_row["inputTokensUsed"]),
                    "outputTokensUsed": int(month_row["outputTokensUsed"]),
                    "baseCostUsd": round(float(month_row["baseCostUsd"]), 2),
                    "inputChargeUsd": round(float(cents_to_usd(month_row["inputChargeCents"])), 2),
                    "outputChargeUsd": round(float(cents_to_usd(month_row["outputChargeCents"])), 2),
                    "usageChargeUsd": round(float(month_row["usageChargeUsd"]), 2),
                    "chargeUsd": round(float(month_row["chargeUsd"]), 2),
                    "minimumApplied": bool(month_row["minimumApplied"]),
                    "currency": currency,
                    "usageCount": int(month_row["usageCount"]),
                    "usageDates": list(month_row["usageDates"]),
                    "toolCount": len(tool_rows),
                    "tools": tool_rows,
                    "models": flat_models,
                }
            )

        summaries.sort(key=lambda row: month_sort_key(str(row.get("month", ""))), reverse=True)

        current_key = month_key_for(reference_time)
        current_month = next((row for row in summaries if row["month"] == current_key), None)
        if current_month is None:
            current_month = {
                "month": current_key,
                "label": month_label(current_key),
                "tokensUsed": 0,
                "inputTokensUsed": 0,
                "outputTokensUsed": 0,
                "baseCostUsd": 0.0,
                "inputChargeUsd": 0.0,
                "outputChargeUsd": 0.0,
                "usageChargeUsd": 0.0,
                "chargeUsd": cents_to_usd(Decimal(minimum_monthly_cents)),
                "minimumApplied": True,
                "currency": currency,
                "usageCount": 0,
                "usageDates": [],
                "toolCount": 0,
                "tools": [],
                "models": [],
            }

        history = [row for row in summaries if month_sort_key(str(row.get("month", ""))) < month_sort_key(current_key)]

        return {
            "ok": True,
            "email": normalized_email,
            "currency": currency,
            "source": "database",
            "sourceLabel": "Latest billing data",
            "minimumMonthlyCharge": round(minimum_monthly_cents / 100, 2),
            "registeredAt": user.get("registeredAt"),
            "billingPlan": {
                "currency": currency,
                "monthlyMinimumCents": minimum_monthly_cents,
            },
            "currentMonth": current_month,
            "history": history,
            "asOf": now_iso(),
        }
