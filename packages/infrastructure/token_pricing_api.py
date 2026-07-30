from __future__ import annotations

import argparse
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

from packages.infrastructure.openai_pricing import OPENAI_PRICING_MARKDOWN_URL
from packages.infrastructure.openai_pricing import OpenAIModelPrice
from packages.infrastructure.openai_pricing import OpenAIPricingError
from packages.infrastructure.openai_pricing import fetch_openai_pricing_markdown
from packages.infrastructure.openai_pricing import parse_openai_pricing_markdown


DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
SERVICE_NAME = "token-pricing-api"
_CACHE: dict[str, Any] = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def cache_ttl_seconds() -> int:
    raw = os.environ.get("TOKEN_PRICES_CACHE_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_CACHE_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def refresh_secret() -> str:
    return (
        os.environ.get("TOKEN_PRICES_REFRESH_SECRET")
        or os.environ.get("PRICE_REFRESH_SECRET")
        or ""
    ).strip()


def read_request_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    raw_length = handler.headers.get("Content-Length") or "0"
    try:
        length = max(0, int(raw_length))
    except ValueError:
        length = 0
    if not length:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def require_refresh_auth(handler: BaseHTTPRequestHandler) -> None:
    expected = refresh_secret()
    if not expected:
        return
    header = str(handler.headers.get("Authorization") or "").strip()
    provided = ""
    if header.lower().startswith("bearer "):
        provided = header.split(" ", 1)[1].strip()
    provided = provided or str(handler.headers.get("X-Token-Prices-Secret") or "").strip()
    provided = provided or str(handler.headers.get("X-Price-Refresh-Secret") or "").strip()
    if not provided or provided != expected:
        raise PermissionError("Invalid refresh secret")


def serialize_price(price: OpenAIModelPrice) -> dict[str, Any]:
    payload = {
        "provider": "openai",
        "model": price.model_id,
        "displayName": price.display_name,
        "tier": price.tier,
        "input": float(price.input_usd_per_1m_tokens),
        "input_usd_per_1m": float(price.input_usd_per_1m_tokens),
        "inputUsdPer1M": float(price.input_usd_per_1m_tokens),
        "output": float(price.output_usd_per_1m_tokens),
        "output_usd_per_1m": float(price.output_usd_per_1m_tokens),
        "outputUsdPer1M": float(price.output_usd_per_1m_tokens),
    }
    if price.cached_input_usd_per_1m_tokens is not None:
        payload.update(
            {
                "cached_input": float(price.cached_input_usd_per_1m_tokens),
                "cached_input_usd_per_1m": float(price.cached_input_usd_per_1m_tokens),
                "cachedInputUsdPer1M": float(price.cached_input_usd_per_1m_tokens),
            }
        )
    if price.cache_write_usd_per_1m_tokens is not None:
        payload.update(
            {
                "cache_write": float(price.cache_write_usd_per_1m_tokens),
                "cache_write_usd_per_1m": float(price.cache_write_usd_per_1m_tokens),
                "cacheWriteUsdPer1M": float(price.cache_write_usd_per_1m_tokens),
            }
        )
    return payload


def build_price_response(prices: list[OpenAIModelPrice], *, fetched_at: datetime, fetched: bool) -> dict[str, Any]:
    serialized = [serialize_price(price) for price in prices]
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "provider": "openai",
        "currency": "USD",
        "unit": "per_1m_tokens",
        "sourceUrl": OPENAI_PRICING_MARKDOWN_URL,
        "fetched": fetched,
        "fetchedAt": fetched_at.isoformat(),
        "cacheTtlSeconds": cache_ttl_seconds(),
        "prices": serialized,
        "pricesByModel": {
            item["model"]: {
                "input": item.get("input"),
                "cached_input": item.get("cached_input"),
                "cache_write": item.get("cache_write"),
                "output": item.get("output"),
            }
            for item in serialized
        },
    }


def load_prices(*, force_refresh: bool = False) -> dict[str, Any]:
    current_time = now_utc()
    cached_at = _CACHE.get("fetched_at")
    cached_response = _CACHE.get("response")
    if (
        not force_refresh
        and isinstance(cached_at, datetime)
        and isinstance(cached_response, dict)
        and current_time - cached_at < timedelta(seconds=cache_ttl_seconds())
    ):
        response = dict(cached_response)
        response["fetched"] = False
        return response

    source_text = fetch_openai_pricing_markdown()
    prices = parse_openai_pricing_markdown(source_text)
    response = build_price_response(prices, fetched_at=current_time, fetched=True)
    _CACHE["fetched_at"] = current_time
    _CACHE["response"] = response
    return response


def json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Token-Prices-Secret, X-Price-Refresh-Secret")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


class TokenPricingHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - BaseHTTPRequestHandler API
        return

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        json_response(self, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path in {"/", "/api/health"}:
            json_response(
                self,
                {
                    "ok": True,
                    "service": SERVICE_NAME,
                    "time": now_utc().isoformat(),
                },
            )
            return

        if path in {"/api/prices", "/api/prices/openai", "/api/openai/prices"}:
            try:
                force_refresh = str((query.get("refresh") or [""])[0]).lower() in {"1", "true", "yes"}
                json_response(self, load_prices(force_refresh=force_refresh))
            except OpenAIPricingError as exc:
                json_response(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return

        json_response(self, {"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != "/internal/prices/refresh":
            json_response(self, {"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            require_refresh_auth(self)
            read_request_json(self)
            json_response(self, load_prices(force_refresh=True))
        except PermissionError as exc:
            json_response(self, {"ok": False, "error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except OpenAIPricingError as exc:
            json_response(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the standalone token pricing API.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), TokenPricingHandler)
    print(f"{SERVICE_NAME} listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
