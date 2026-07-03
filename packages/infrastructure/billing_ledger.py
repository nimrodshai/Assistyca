from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CURRENCY = "USD"
MONTH_KEY_RE = re.compile(r"^\d{4}-\d{2}$")


def read_json_file(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return loaded if isinstance(loaded, dict) else {}


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def current_month_key(reference: datetime | None = None) -> str:
    moment = reference or datetime.now().astimezone()
    return moment.strftime("%Y-%m")


def normalize_month_key(value: Any, fallback: str | None = None) -> str:
    text = normalize_text(value)
    if MONTH_KEY_RE.match(text):
        return text

    if fallback and MONTH_KEY_RE.match(fallback):
        return fallback

    return current_month_key()


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


def resolve_model_base_cost(raw_model: dict[str, Any]) -> float:
    explicit_cost = raw_model.get("base_cost_usd")
    if explicit_cost is None:
        explicit_cost = raw_model.get("baseCostUsd")
    if explicit_cost is None:
        explicit_cost = raw_model.get("cost_usd")
    if explicit_cost is None:
        explicit_cost = raw_model.get("costUsd")

    if explicit_cost is not None:
        return max(0.0, safe_float(explicit_cost))

    tokens = safe_int(
        raw_model.get("tokens")
        if raw_model.get("tokens") is not None
        else raw_model.get("token_count")
    )

    token_value = raw_model.get("token_value_usd")
    if token_value is None:
        token_value = raw_model.get("tokenValueUsd")
    if token_value is None:
        token_value = raw_model.get("unit_cost_usd")
    if token_value is None:
        token_value = raw_model.get("unitCostUsd")
    if token_value is None:
        token_value = raw_model.get("value_per_token_usd")
    if token_value is None:
        token_value = raw_model.get("valuePerTokenUsd")

    if token_value is None:
        return 0.0

    return max(0.0, tokens * safe_float(token_value))


def summarize_model_rows(raw_models: Any) -> list[dict[str, Any]]:
    models = raw_models if isinstance(raw_models, list) else []
    aggregated: dict[str, dict[str, Any]] = {}

    for raw_model in models:
        if not isinstance(raw_model, dict):
            continue

        model_name = normalize_text(raw_model.get("model") or raw_model.get("name")) or "Unknown model"
        entry = aggregated.setdefault(
            model_name,
            {
                "model": model_name,
                "tokensUsed": 0,
                "baseCostUsd": 0.0,
            },
        )
        entry["tokensUsed"] += safe_int(raw_model.get("tokens") or raw_model.get("token_count"))
        entry["baseCostUsd"] += resolve_model_base_cost(raw_model)

    summarized = []
    for row in aggregated.values():
        summarized.append(
            {
                "model": row["model"],
                "tokensUsed": int(row["tokensUsed"]),
                "baseCostUsd": round(float(row["baseCostUsd"]), 2),
            }
        )

    summarized.sort(key=lambda row: (-row["tokensUsed"], str(row["model"]).lower()))
    return summarized


def summarize_month(
    raw_month: dict[str, Any],
    *,
    markup_multiplier: float,
    minimum_monthly_charge: float,
    currency: str = DEFAULT_CURRENCY,
    fallback_month_key: str | None = None,
) -> dict[str, Any]:
    month_key = normalize_month_key(raw_month.get("month"), fallback=fallback_month_key)
    models = summarize_model_rows(raw_month.get("models"))
    tokens_used = sum(int(model["tokensUsed"]) for model in models)
    base_cost_usd = round(sum(float(model["baseCostUsd"]) for model in models), 2)
    raw_charge = round(base_cost_usd * markup_multiplier, 2)
    charge_usd = round(max(raw_charge, minimum_monthly_charge), 2)
    minimum_applied = charge_usd == round(minimum_monthly_charge, 2) and raw_charge < minimum_monthly_charge

    return {
        "month": month_key,
        "label": month_label(month_key),
        "tokensUsed": tokens_used,
        "baseCostUsd": base_cost_usd,
        "chargeUsd": charge_usd,
        "minimumApplied": minimum_applied,
        "currency": currency,
        "models": models,
    }


def _resolve_source_record(data: dict[str, Any], email: str) -> tuple[dict[str, Any], str]:
    accounts = data.get("accounts")
    normalized_email = normalize_email(email)
    if isinstance(accounts, dict):
        account = accounts.get(normalized_email)
        if isinstance(account, dict):
            return account, "account"

    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        return defaults, "defaults"

    if isinstance(data.get("months"), list):
        return data, "defaults"

    return {}, "empty"


def build_billing_report(
    data: dict[str, Any],
    email: str,
    *,
    markup_multiplier: float = 1.5,
    minimum_monthly_charge: float = 29.0,
    currency: str = DEFAULT_CURRENCY,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    normalized_email = normalize_email(email)
    source_record, source = _resolve_source_record(data, normalized_email)
    months = source_record.get("months") if isinstance(source_record, dict) else []
    month_rows = months if isinstance(months, list) else []
    current_key = current_month_key(reference_time)
    registered_at = normalize_text(source_record.get("registeredAt")) if isinstance(source_record, dict) else ""

    summaries: list[dict[str, Any]] = []
    for raw_month in month_rows:
        if not isinstance(raw_month, dict):
            continue

        summary = summarize_month(
            raw_month,
            markup_multiplier=markup_multiplier,
            minimum_monthly_charge=minimum_monthly_charge,
            currency=currency,
        )
        summaries.append(summary)

    summaries.sort(key=lambda row: month_sort_key(str(row.get("month", ""))), reverse=True)

    current_month = next((row for row in summaries if row["month"] == current_key), None)
    if current_month is None:
        current_month = summarize_month(
            {"month": current_key, "models": []},
            markup_multiplier=markup_multiplier,
            minimum_monthly_charge=minimum_monthly_charge,
            currency=currency,
            fallback_month_key=current_key,
        )

    history = [row for row in summaries if month_sort_key(str(row.get("month", ""))) < month_sort_key(current_key)]

    return {
        "ok": True,
        "email": normalized_email,
        "currency": currency,
        "markupMultiplier": markup_multiplier,
        "minimumMonthlyCharge": round(minimum_monthly_charge, 2),
        "source": source,
        "registeredAt": registered_at,
        "currentMonth": current_month,
        "history": history,
        "asOf": datetime.now().astimezone().isoformat(),
    }


def load_billing_report(
    path: Path | None,
    email: str,
    *,
    markup_multiplier: float = 1.5,
    minimum_monthly_charge: float = 29.0,
    currency: str = DEFAULT_CURRENCY,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    data = read_json_file(path)
    return build_billing_report(
        data,
        email,
        markup_multiplier=markup_multiplier,
        minimum_monthly_charge=minimum_monthly_charge,
        currency=currency,
        reference_time=reference_time,
    )
