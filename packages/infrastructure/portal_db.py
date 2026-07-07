from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from decimal import ROUND_HALF_UP
from pathlib import Path
import re
from typing import Any
from typing import Iterable


DEFAULT_DB_PATH = Path("portal/portal.db")
DEFAULT_CURRENCY = "USD"
DEFAULT_MONTHLY_MINIMUM_CENTS = 5000
DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER = 1.5
DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER = 1.5
RAW_CENTS_QUANT = Decimal("0.0001")
USD_QUANT = Decimal("0.01")


@dataclass
class BillingPlan:
    currency: str = DEFAULT_CURRENCY
    monthly_minimum_cents: int = DEFAULT_MONTHLY_MINIMUM_CENTS
    input_token_price_multiplier: float = DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER
    output_token_price_multiplier: float = DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    registered_at TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    last_login_at TEXT,
    last_otp_requested_at TEXT,
    last_otp_verified_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
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

CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_month ON usage_events(user_id, billing_month, used_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_model ON usage_events(user_id, model_name, used_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_prices_is_active ON model_prices(is_active);
"""


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


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


class PortalDatabase:
    def __init__(
        self,
        path: Path | str = DEFAULT_DB_PATH,
        *,
        bootstrap_registered_emails: Iterable[str] = (),
        bootstrap_admin_emails: Iterable[str] = (),
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
        self._init_lock = threading.Lock()
        self._initialize()

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
                conn.executescript(SCHEMA_SQL)
                self._migrate_users_table(conn)
                self._migrate_user_billing_table(conn)
                self._migrate_usage_events_table(conn)
                self._ensure_usage_events_tool_indexes(conn)
                if self.bootstrap_registered_emails and self.count_registered_users(conn) == 0:
                    self._seed_registered_emails(conn, self.bootstrap_registered_emails)
                if self.bootstrap_admin_emails:
                    self._seed_admin_emails(conn, self.bootstrap_admin_emails)

    def _migrate_users_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_admin" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

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
                    notes,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_email,
                    registered_value,
                    normalize_text(display_name),
                    1 if is_active else 0,
                    1 if is_admin else 0,
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
                        notes = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        normalize_text(display_name),
                        1 if is_active else 0,
                        1 if is_admin else 0,
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
                u.last_login_at,
                u.last_otp_requested_at,
                u.last_otp_verified_at,
                u.notes,
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
                "registeredAt": payload.get("registered_at"),
                "lastLoginAt": payload.get("last_login_at"),
                "lastOtpRequestedAt": payload.get("last_otp_requested_at"),
                "lastOtpVerifiedAt": payload.get("last_otp_verified_at"),
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
            "registered_at",
            "last_login_at",
            "last_otp_requested_at",
            "last_otp_verified_at",
        ):
            payload.pop(key, None)
        payload.pop("billing_currency", None)
        payload.pop("monthly_minimum_cents", None)
        payload.pop("input_token_price_multiplier", None)
        payload.pop("output_token_price_multiplier", None)
        return payload

    def count_registered_users(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is not None:
            row = conn.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1").fetchone()
            return int(row["count"] or 0) if row else 0

        with self._connection() as fresh_conn:
            row = fresh_conn.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1").fetchone()
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
                u.last_login_at,
                u.last_otp_requested_at,
                u.last_otp_verified_at,
                u.notes,
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
                    "registeredAt": payload.get("registered_at"),
                    "lastLoginAt": payload.get("last_login_at"),
                    "lastOtpRequestedAt": payload.get("last_otp_requested_at"),
                    "lastOtpVerifiedAt": payload.get("last_otp_verified_at"),
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
                "registered_at",
                "last_login_at",
                "last_otp_requested_at",
                "last_otp_verified_at",
                "notes",
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
            return self._load_user_row(conn, normalized_email) or {}

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
        input_multiplier = float(
            billing.get("inputTokenPriceMultiplier") or self.default_billing_plan.input_token_price_multiplier
        )
        output_multiplier = float(
            billing.get("outputTokenPriceMultiplier") or self.default_billing_plan.output_token_price_multiplier
        )

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
            raw_charge = to_decimal(event.get("rawChargeCents"))

            month_row["tokensUsed"] += input_tokens + output_tokens
            month_row["inputTokensUsed"] += input_tokens
            month_row["outputTokensUsed"] += output_tokens
            month_row["baseCostCents"] += raw_charge
            month_row["inputChargeCents"] += input_charge
            month_row["outputChargeCents"] += output_charge
            month_row["usageCount"] += 1
            month_row["usageDates"].add(usage_date)

            tool_row["tokensUsed"] += input_tokens + output_tokens
            tool_row["inputTokensUsed"] += input_tokens
            tool_row["outputTokensUsed"] += output_tokens
            tool_row["baseCostCents"] += raw_charge
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
            model_row["baseCostCents"] += raw_charge
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
                tool_raw_total = tool_row["baseCostCents"]
                tool_row["baseCostUsd"] = cents_to_usd(tool_raw_total)
                tool_row["chargeUsd"] = cents_to_usd(tool_raw_total)
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
            month_usage_charge_cents = sum(Decimal(str(tool["chargeUsd"])) * Decimal("100") for tool in tool_rows)
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
            "sourceLabel": "Latest billing snapshot",
            "markupMultiplier": input_multiplier,
            "inputTokenPriceMultiplier": input_multiplier,
            "outputTokenPriceMultiplier": output_multiplier,
            "minimumMonthlyCharge": round(minimum_monthly_cents / 100, 2),
            "registeredAt": user.get("registeredAt"),
            "billingPlan": {
                "currency": currency,
                "monthlyMinimumCents": minimum_monthly_cents,
                "inputTokenPriceMultiplier": input_multiplier,
                "outputTokenPriceMultiplier": output_multiplier,
            },
            "currentMonth": current_month,
            "history": history,
            "asOf": now_iso(),
        }
