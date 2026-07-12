from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
from decimal import ROUND_HALF_UP
import re
from typing import Any
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.portal_db import PortalDatabase


OPENAI_PRICING_MARKDOWN_URL = "https://developers.openai.com/api/docs/pricing.md"
DEFAULT_PRICING_REFRESH_DAYS = 30
USD_PER_1M_QUANT = Decimal("0.0001")
REPRESENTATIVE_MODEL_FAMILY_PREFIX = "gpt-5"


class OpenAIPricingError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAIModelPrice:
    model_id: str
    display_name: str
    tier: str
    input_usd_per_1m_tokens: Decimal
    output_usd_per_1m_tokens: Decimal
    cached_input_usd_per_1m_tokens: Decimal | None = None
    cache_write_usd_per_1m_tokens: Decimal | None = None

    @property
    def total_usd_per_1m_tokens(self) -> Decimal:
        return (self.input_usd_per_1m_tokens + self.output_usd_per_1m_tokens).quantize(
            USD_PER_1M_QUANT,
            rounding=ROUND_HALF_UP,
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_model_id(name: str) -> str:
    match = re.match(r"([a-z0-9][a-z0-9.-]*)", normalize_text(name).lower())
    return match.group(1) if match else ""


def parse_decimal(value: Any) -> Decimal | None:
    if value in {None, "", "-", "Free"}:
        return None
    text = normalize_text(value)
    try:
        return Decimal(text)
    except Exception:
        return None


def usd_per_1m_to_cents_per_1k(value: Decimal) -> float:
    return float((value / Decimal("10")).quantize(USD_PER_1M_QUANT, rounding=ROUND_HALF_UP))


def extract_flagship_standard_rows(markdown_text: str) -> list[list[Any]]:
    marker = 'id="latest-models"'
    start_index = markdown_text.find(marker)
    if start_index < 0:
        raise OpenAIPricingError("Could not find the flagship pricing section in OpenAI pricing markdown.")

    standard_index = markdown_text.find('data-value="standard"', start_index)
    if standard_index < 0:
        raise OpenAIPricingError("Could not find the standard pricing pane in OpenAI pricing markdown.")

    rows_index = markdown_text.find("rows=[", standard_index)
    if rows_index < 0:
        raise OpenAIPricingError("Could not find standard pricing rows in OpenAI pricing markdown.")

    content_start = rows_index + len("rows=[")
    depth = 1
    cursor = content_start
    while cursor < len(markdown_text) and depth > 0:
        char = markdown_text[cursor]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        cursor += 1

    if depth != 0:
        raise OpenAIPricingError("OpenAI pricing markdown rows block is not balanced.")

    body = markdown_text[content_start:cursor - 1]
    sanitized = re.sub(r"\bnull\b", "None", body)
    try:
        rows = ast.literal_eval(f"[{sanitized}]")
    except Exception as exc:
        raise OpenAIPricingError("Could not parse OpenAI pricing rows from markdown.") from exc
    return rows if isinstance(rows, list) else []


def parse_openai_pricing_markdown(markdown_text: str) -> list[OpenAIModelPrice]:
    parsed_rows = extract_flagship_standard_rows(markdown_text)
    prices: list[OpenAIModelPrice] = []
    for row in parsed_rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        display_name = normalize_text(row[0])
        model_id = normalize_model_id(display_name)
        if not model_id:
            continue
        input_price = parse_decimal(row[1])
        output_price = parse_decimal(row[-1])
        if input_price is None or output_price is None:
            continue
        cached_input = parse_decimal(row[2]) if len(row) >= 4 else None
        cache_write = parse_decimal(row[3]) if len(row) >= 5 else None
        prices.append(
            OpenAIModelPrice(
                model_id=model_id,
                display_name=display_name,
                tier="standard",
                input_usd_per_1m_tokens=input_price,
                output_usd_per_1m_tokens=output_price,
                cached_input_usd_per_1m_tokens=cached_input,
                cache_write_usd_per_1m_tokens=cache_write,
            )
        )
    if not prices:
        raise OpenAIPricingError("OpenAI pricing markdown did not contain any usable flagship model rows.")
    return prices


def pick_representative_models(prices: list[OpenAIModelPrice]) -> list[OpenAIModelPrice]:
    family = [price for price in prices if price.model_id.startswith(REPRESENTATIVE_MODEL_FAMILY_PREFIX)]
    candidates = family if len(family) >= 3 else list(prices)
    ordered = sorted(candidates, key=lambda item: (item.total_usd_per_1m_tokens, item.model_id))
    if len(ordered) <= 3:
        return ordered
    middle_index = len(ordered) // 2
    selected = [ordered[0], ordered[middle_index], ordered[-1]]
    deduped: list[OpenAIModelPrice] = []
    seen: set[str] = set()
    for item in selected:
        if item.model_id in seen:
            continue
        seen.add(item.model_id)
        deduped.append(item)
    while len(deduped) < 3:
        for item in ordered:
            if item.model_id in seen:
                continue
            seen.add(item.model_id)
            deduped.append(item)
            if len(deduped) == 3:
                break
    return deduped


def fetch_openai_pricing_markdown(
    *,
    url: str = OPENAI_PRICING_MARKDOWN_URL,
    timeout_seconds: float = 20.0,
) -> str:
    request = urllib_request.Request(
        url,
        headers={
            "Accept": "text/markdown,text/plain;q=0.9,*/*;q=0.8",
            "User-Agent": "AssistycaPricingSync/1.0",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8")
    except urllib_error.URLError as exc:
        raise OpenAIPricingError(f"Could not load OpenAI pricing markdown: {exc}") from exc


def list_openai_model_prices(database: PortalDatabase) -> list[dict[str, Any]]:
    if hasattr(database, "list_model_prices"):
        return database.list_model_prices(provider="openai")
    return []


def rows_are_seed_defaults(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    return all("seeded" in normalize_text(row.get("notes")).lower() for row in rows)


def rows_need_refresh(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    refresh_days: int,
) -> bool:
    if not rows:
        return True
    threshold = now - timedelta(days=max(1, refresh_days))
    for row in rows:
        updated_at_raw = normalize_text(row.get("updatedAt") or row.get("updated_at"))
        if not updated_at_raw:
            return True
        try:
            updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if updated_at.astimezone(timezone.utc) < threshold:
            return True
    return False


def build_snapshot_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prices = [
        OpenAIModelPrice(
            model_id=normalize_model_id(row.get("model_name") or row.get("modelName")),
            display_name=normalize_text(row.get("model_name") or row.get("modelName")),
            tier="standard",
            input_usd_per_1m_tokens=Decimal(str(row.get("input_price_cents_per_1k_tokens") or 0)) * Decimal("10"),
            output_usd_per_1m_tokens=Decimal(str(row.get("output_price_cents_per_1k_tokens") or 0)) * Decimal("10"),
        )
        for row in rows
        if normalize_model_id(row.get("model_name") or row.get("modelName"))
    ]
    representatives = pick_representative_models(prices)
    fetched_at = ""
    if rows:
        fetched_at = max(
            (
                normalize_text(row.get("updatedAt") or row.get("updated_at"))
                for row in rows
            ),
            default="",
        )
    return {
        "source": "database",
        "sourceUrl": OPENAI_PRICING_MARKDOWN_URL,
        "fetched": False,
        "fetchedAt": fetched_at or None,
        "models": prices,
        "representatives": representatives,
    }


def sync_openai_model_prices(
    database: PortalDatabase,
    *,
    markdown_text: str | None = None,
    fetcher: Callable[[], str] | None = None,
    now: datetime | None = None,
    refresh_days: int = DEFAULT_PRICING_REFRESH_DAYS,
) -> dict[str, Any]:
    current_time = now or now_utc()
    existing_rows = list_openai_model_prices(database)

    should_fetch = markdown_text is not None or rows_need_refresh(
        existing_rows,
        now=current_time,
        refresh_days=refresh_days,
    ) or rows_are_seed_defaults(existing_rows)

    if not should_fetch:
        return build_snapshot_from_rows(existing_rows)

    try:
        source_text = markdown_text if markdown_text is not None else (fetcher or fetch_openai_pricing_markdown)()
    except OpenAIPricingError:
        if existing_rows and markdown_text is None:
            return build_snapshot_from_rows(existing_rows)
        raise

    prices = parse_openai_pricing_markdown(source_text)
    for price in prices:
        current_row = database.get_model_price(price.model_id) or {}
        current_provider = normalize_text(current_row.get("provider"))
        if current_row and current_provider and current_provider != "openai":
            continue
        database.upsert_model_price(
            price.model_id,
            input_price_cents_per_1k_tokens=usd_per_1m_to_cents_per_1k(price.input_usd_per_1m_tokens),
            output_price_cents_per_1k_tokens=usd_per_1m_to_cents_per_1k(price.output_usd_per_1m_tokens),
            currency="USD",
            provider="openai",
            notes=f"Synced from {OPENAI_PRICING_MARKDOWN_URL} at {current_time.isoformat()}",
            is_active=True,
        )
    representatives = pick_representative_models(prices)
    return {
        "source": "openai",
        "sourceUrl": OPENAI_PRICING_MARKDOWN_URL,
        "fetched": True,
        "fetchedAt": current_time.isoformat(),
        "models": prices,
        "representatives": representatives,
    }


def serialize_pricing_snapshot(
    snapshot: dict[str, Any],
    *,
    input_multiplier: float,
    output_multiplier: float,
) -> dict[str, Any]:
    representatives = snapshot.get("representatives") if isinstance(snapshot.get("representatives"), list) else []
    cards = []
    labels = ["Lean", "Balanced", "Premium"]
    for index, model in enumerate(representatives):
        if not isinstance(model, OpenAIModelPrice):
            continue
        cards.append(
            {
                "band": labels[index] if index < len(labels) else f"Tier {index + 1}",
                "modelId": model.model_id,
                "modelName": model.display_name,
                "openai": {
                    "inputUsdPer1MTokens": float(model.input_usd_per_1m_tokens),
                    "outputUsdPer1MTokens": float(model.output_usd_per_1m_tokens),
                },
                "ours": {
                    "inputUsdPer1MTokens": float(
                        (model.input_usd_per_1m_tokens * Decimal(str(input_multiplier))).quantize(
                            USD_PER_1M_QUANT,
                            rounding=ROUND_HALF_UP,
                        )
                    ),
                    "outputUsdPer1MTokens": float(
                        (model.output_usd_per_1m_tokens * Decimal(str(output_multiplier))).quantize(
                            USD_PER_1M_QUANT,
                            rounding=ROUND_HALF_UP,
                        )
                    ),
                },
                "totalOpenAIUsdPer1MTokens": float(model.total_usd_per_1m_tokens),
                "totalOurUsdPer1MTokens": float(
                    (
                        model.input_usd_per_1m_tokens * Decimal(str(input_multiplier))
                        + model.output_usd_per_1m_tokens * Decimal(str(output_multiplier))
                    ).quantize(USD_PER_1M_QUANT, rounding=ROUND_HALF_UP)
                ),
            }
        )
    return {
        "ok": True,
        "source": normalize_text(snapshot.get("source")) or "database",
        "sourceUrl": normalize_text(snapshot.get("sourceUrl")) or OPENAI_PRICING_MARKDOWN_URL,
        "fetchedAt": snapshot.get("fetchedAt"),
        "refreshWindowDays": DEFAULT_PRICING_REFRESH_DAYS,
        "inputMultiplier": float(input_multiplier),
        "outputMultiplier": float(output_multiplier),
        "cards": cards,
    }


def build_pricing_snapshot_json(
    database: PortalDatabase,
    *,
    input_multiplier: float,
    output_multiplier: float,
    markdown_text: str | None = None,
    fetcher: Callable[[], str] | None = None,
    now: datetime | None = None,
    refresh_days: int = DEFAULT_PRICING_REFRESH_DAYS,
) -> dict[str, Any]:
    snapshot = sync_openai_model_prices(
        database,
        markdown_text=markdown_text,
        fetcher=fetcher,
        now=now,
        refresh_days=refresh_days,
    )
    return serialize_pricing_snapshot(
        snapshot,
        input_multiplier=input_multiplier,
        output_multiplier=output_multiplier,
    )


__all__ = [
    "DEFAULT_PRICING_REFRESH_DAYS",
    "OPENAI_PRICING_MARKDOWN_URL",
    "OpenAIModelPrice",
    "OpenAIPricingError",
    "build_pricing_snapshot_json",
    "fetch_openai_pricing_markdown",
    "parse_openai_pricing_markdown",
    "pick_representative_models",
    "sync_openai_model_prices",
]
