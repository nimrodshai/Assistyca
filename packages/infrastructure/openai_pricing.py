from __future__ import annotations

import ast
import json
import os
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
TOKEN_PRICES_API_OPENAI_PRICES_URL = "https://token-prices-api.onrender.com/api/openai/prices"
TOKEN_PRICES_API_OPENAI_PRICES_URL_ENV = "TOKEN_PRICES_API_OPENAI_PRICES_URL"
DEFAULT_PRICING_REFRESH_DAYS = 1
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
    text = normalize_text(value).replace("$", "").replace(",", "")
    try:
        return Decimal(text)
    except Exception:
        return None


def split_markdown_table_row(line: str) -> list[str]:
    stripped = normalize_text(line)
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def extract_standard_pricing_table_rows(markdown_text: str) -> list[list[str]]:
    lines = markdown_text.splitlines()
    table_start = -1
    for index, line in enumerate(lines):
        if normalize_text(line).lower() == "### standard pricing data":
            table_start = index
            break
    if table_start < 0:
        raise OpenAIPricingError("Could not find the standard pricing table in OpenAI pricing markdown.")

    rows: list[list[str]] = []
    for line in lines[table_start + 1:]:
        stripped = normalize_text(line)
        if not stripped:
            if rows:
                break
            continue
        cells = split_markdown_table_row(stripped)
        if not cells:
            if rows:
                break
            continue
        rows.append(cells)
    if len(rows) < 3:
        raise OpenAIPricingError("OpenAI standard pricing markdown table is missing rows.")
    return rows


def parse_standard_pricing_table(markdown_text: str) -> list[OpenAIModelPrice]:
    rows = extract_standard_pricing_table_rows(markdown_text)
    header = [cell.lower() for cell in rows[0]]
    data_rows = rows[2:]

    def header_index(label: str) -> int:
        try:
            return header.index(label)
        except ValueError as exc:
            raise OpenAIPricingError(f"OpenAI pricing table is missing '{label}'.") from exc

    model_index = header_index("model")
    input_index = header_index("short context input")
    cached_input_index = header_index("short context cached input")
    cache_write_index = header_index("short context cache writes")
    output_index = header_index("short context output")

    prices: list[OpenAIModelPrice] = []
    for row in data_rows:
        if len(row) <= max(model_index, input_index, cached_input_index, cache_write_index, output_index):
            continue
        display_name = normalize_text(row[model_index])
        model_id = normalize_model_id(display_name)
        input_price = parse_decimal(row[input_index])
        output_price = parse_decimal(row[output_index])
        if not model_id or input_price is None or output_price is None:
            continue
        prices.append(
            OpenAIModelPrice(
                model_id=model_id,
                display_name=display_name,
                tier="standard",
                input_usd_per_1m_tokens=input_price,
                output_usd_per_1m_tokens=output_price,
                cached_input_usd_per_1m_tokens=parse_decimal(row[cached_input_index]),
                cache_write_usd_per_1m_tokens=parse_decimal(row[cache_write_index]),
            )
        )

    if not prices:
        raise OpenAIPricingError("OpenAI standard pricing markdown table did not contain usable rows.")
    return prices


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
    try:
        return parse_standard_pricing_table(markdown_text)
    except OpenAIPricingError:
        pass

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


def resolve_token_prices_api_url(url: str | None = None) -> str:
    configured_url = normalize_text(
        url if url is not None else os.getenv(TOKEN_PRICES_API_OPENAI_PRICES_URL_ENV)
    )
    return configured_url or TOKEN_PRICES_API_OPENAI_PRICES_URL


def fetch_token_prices_api_payload(
    *,
    url: str | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    endpoint_url = resolve_token_prices_api_url(url)
    request = urllib_request.Request(
        endpoint_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AssistycaPricingSync/1.0",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        raise OpenAIPricingError(f"Token pricing API returned HTTP {exc.code}.") from exc
    except urllib_error.URLError as exc:
        raise OpenAIPricingError(f"Could not load token pricing API: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAIPricingError("Token pricing API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise OpenAIPricingError("Token pricing API returned an unexpected response.")
    return payload


def first_present_value(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None and value != "":
            return value
    return None


def iter_token_prices_api_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_prices = payload.get("prices")
    if isinstance(raw_prices, list):
        return [dict(row) for row in raw_prices if isinstance(row, dict)]

    prices_by_model = payload.get("pricesByModel") or payload.get("prices_by_model")
    if not isinstance(prices_by_model, dict):
        return []

    rows: list[dict[str, Any]] = []
    for model_name, raw_price in prices_by_model.items():
        if not isinstance(raw_price, dict):
            continue
        row = dict(raw_price)
        row.setdefault("model", model_name)
        rows.append(row)
    return rows


def parse_token_prices_api_response(payload: dict[str, Any]) -> list[OpenAIModelPrice]:
    if not isinstance(payload, dict):
        raise OpenAIPricingError("Token pricing API payload must be an object.")
    if payload.get("ok") is False:
        message = normalize_text(payload.get("error") or payload.get("message"))
        raise OpenAIPricingError(message or "Token pricing API returned an error.")

    prices: list[OpenAIModelPrice] = []
    for row in iter_token_prices_api_rows(payload):
        display_name = normalize_text(
            first_present_value(row, "displayName", "display_name", "name", "model")
        )
        model_id = normalize_model_id(
            first_present_value(row, "model", "modelId", "model_id") or display_name
        )
        if not model_id:
            continue

        input_price = parse_decimal(
            first_present_value(
                row,
                "input",
                "input_usd_per_1m",
                "inputUsdPer1M",
                "inputUsdPer1MTokens",
            )
        )
        output_price = parse_decimal(
            first_present_value(
                row,
                "output",
                "output_usd_per_1m",
                "outputUsdPer1M",
                "outputUsdPer1MTokens",
            )
        )
        if input_price is None or output_price is None:
            continue

        prices.append(
            OpenAIModelPrice(
                model_id=model_id,
                display_name=display_name or model_id,
                tier=normalize_text(row.get("tier")) or "standard",
                input_usd_per_1m_tokens=input_price,
                output_usd_per_1m_tokens=output_price,
                cached_input_usd_per_1m_tokens=parse_decimal(
                    first_present_value(
                        row,
                        "cached_input",
                        "cached_input_usd_per_1m",
                        "cachedInputUsdPer1M",
                        "cachedInputUsdPer1MTokens",
                    )
                ),
                cache_write_usd_per_1m_tokens=parse_decimal(
                    first_present_value(
                        row,
                        "cache_write",
                        "cache_write_usd_per_1m",
                        "cacheWriteUsdPer1M",
                        "cacheWriteUsdPer1MTokens",
                    )
                ),
            )
        )

    if not prices:
        raise OpenAIPricingError("Token pricing API response did not contain usable OpenAI price rows.")
    return prices


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
    api_payload: dict[str, Any] | None = None,
    api_fetcher: Callable[[], dict[str, Any]] | None = None,
    api_url: str | None = None,
    markdown_text: str | None = None,
    fetcher: Callable[[], str] | None = None,
    now: datetime | None = None,
    refresh_days: int = DEFAULT_PRICING_REFRESH_DAYS,
) -> dict[str, Any]:
    current_time = now or now_utc()
    existing_rows = list_openai_model_prices(database)

    should_fetch = (
        api_payload is not None
        or api_fetcher is not None
        or markdown_text is not None
        or rows_need_refresh(
            existing_rows,
            now=current_time,
            refresh_days=refresh_days,
        )
        or rows_are_seed_defaults(existing_rows)
    )

    if not should_fetch:
        return build_snapshot_from_rows(existing_rows)

    prices: list[OpenAIModelPrice]
    source = "token-prices-api"
    source_url = OPENAI_PRICING_MARKDOWN_URL
    endpoint_url = resolve_token_prices_api_url(api_url)
    fetched_at = current_time.isoformat()
    fetched = True
    use_markdown_source = markdown_text is not None or (
        fetcher is not None and api_payload is None and api_fetcher is None
    )

    if use_markdown_source:
        try:
            source_text = markdown_text if markdown_text is not None else (fetcher or fetch_openai_pricing_markdown)()
            prices = parse_openai_pricing_markdown(source_text)
        except OpenAIPricingError:
            if existing_rows and markdown_text is None:
                return build_snapshot_from_rows(existing_rows)
            raise
        source = "openai"
        endpoint_url = ""
    else:
        try:
            payload = (
                api_payload
                if api_payload is not None
                else api_fetcher() if api_fetcher is not None
                else fetch_token_prices_api_payload(url=endpoint_url)
            )
            prices = parse_token_prices_api_response(payload)
            source = normalize_text(payload.get("service")) or "token-prices-api"
            source_url = normalize_text(payload.get("sourceUrl")) or source_url
            fetched_at = normalize_text(payload.get("fetchedAt")) or fetched_at
            fetched = bool(payload.get("fetched", True))
        except Exception as api_exc:
            try:
                source_text = (fetcher or fetch_openai_pricing_markdown)()
                prices = parse_openai_pricing_markdown(source_text)
            except OpenAIPricingError:
                if existing_rows:
                    return build_snapshot_from_rows(existing_rows)
                if isinstance(api_exc, OpenAIPricingError):
                    raise api_exc
                raise OpenAIPricingError(f"Could not load token pricing API: {api_exc}") from api_exc
            source = "openai"
            endpoint_url = ""
            fetched_at = current_time.isoformat()
            fetched = True

    for price in prices:
        current_row = database.get_model_price(price.model_id) or {}
        current_provider = normalize_text(current_row.get("provider"))
        if current_row and current_provider and current_provider != "openai":
            continue
        note_source = endpoint_url or source_url
        database.upsert_model_price(
            price.model_id,
            input_price_cents_per_1k_tokens=usd_per_1m_to_cents_per_1k(price.input_usd_per_1m_tokens),
            output_price_cents_per_1k_tokens=usd_per_1m_to_cents_per_1k(price.output_usd_per_1m_tokens),
            currency="USD",
            provider="openai",
            notes=f"Synced from {note_source} at {current_time.isoformat()}",
            is_active=True,
        )
    representatives = pick_representative_models(prices)
    return {
        "source": source,
        "sourceUrl": source_url,
        "endpointUrl": endpoint_url or None,
        "fetched": fetched,
        "fetchedAt": fetched_at,
        "models": prices,
        "representatives": representatives,
    }


def resolve_current_openai_model_price(
    database: PortalDatabase,
    model_name: str,
    *,
    now: datetime | None = None,
    refresh_days: int = DEFAULT_PRICING_REFRESH_DAYS,
) -> dict[str, Any] | None:
    if not hasattr(database, "get_model_price"):
        return None

    normalized_model_name = normalize_model_id(model_name)
    if not normalized_model_name:
        return None

    current_time = now or now_utc()
    existing_rows = list_openai_model_prices(database)
    existing_row = database.get_model_price(normalized_model_name)
    should_sync = (
        existing_row is None
        or rows_are_seed_defaults(existing_rows)
        or rows_need_refresh(
            existing_rows,
            now=current_time,
            refresh_days=refresh_days,
        )
    )

    if should_sync:
        try:
            sync_openai_model_prices(
                database,
                now=current_time,
                refresh_days=refresh_days,
            )
        except OpenAIPricingError:
            return existing_row

    return database.get_model_price(normalized_model_name) or existing_row


def serialize_pricing_snapshot(
    snapshot: dict[str, Any],
    *,
    input_multiplier: float,
    output_multiplier: float,
) -> dict[str, Any]:
    representatives = snapshot.get("representatives") if isinstance(snapshot.get("representatives"), list) else []
    cards = []
    labels = ["Lean", "Balanced", "Premium"]
    card_copy = {
        "Lean": {
            "description": "For lightweight automations and high-volume tasks where efficiency matters most.",
            "useCases": ["Short prompts", "Extraction", "Classification"],
        },
        "Balanced": {
            "description": "For most day-to-day assistants and workflows that need a strong mix of cost and capability.",
            "useCases": ["Client replies", "Workflow agents", "Daily operations"],
            "featured": True,
            "highlightLabel": "Most popular",
        },
        "Premium": {
            "description": "For the most demanding tasks, deeper reasoning, and higher-stakes outputs.",
            "useCases": ["Deep reasoning", "Long context", "Critical drafting"],
        },
    }
    for index, model in enumerate(representatives):
        if not isinstance(model, OpenAIModelPrice):
            continue
        band = labels[index] if index < len(labels) else f"Tier {index + 1}"
        copy = card_copy.get(band, {})
        cards.append(
            {
                "band": band,
                "modelId": model.model_id,
                "modelName": model.display_name,
                "description": copy.get("description", ""),
                "useCases": copy.get("useCases", []),
                "featured": bool(copy.get("featured")),
                "highlightLabel": normalize_text(copy.get("highlightLabel")),
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
        "endpointUrl": normalize_text(snapshot.get("endpointUrl")) or None,
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
    api_payload: dict[str, Any] | None = None,
    api_fetcher: Callable[[], dict[str, Any]] | None = None,
    api_url: str | None = None,
    markdown_text: str | None = None,
    fetcher: Callable[[], str] | None = None,
    now: datetime | None = None,
    refresh_days: int = DEFAULT_PRICING_REFRESH_DAYS,
) -> dict[str, Any]:
    snapshot = sync_openai_model_prices(
        database,
        api_payload=api_payload,
        api_fetcher=api_fetcher,
        api_url=api_url,
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
    "TOKEN_PRICES_API_OPENAI_PRICES_URL",
    "build_pricing_snapshot_json",
    "fetch_openai_pricing_markdown",
    "fetch_token_prices_api_payload",
    "parse_openai_pricing_markdown",
    "parse_standard_pricing_table",
    "parse_token_prices_api_response",
    "pick_representative_models",
    "resolve_current_openai_model_price",
    "resolve_token_prices_api_url",
    "sync_openai_model_prices",
]
