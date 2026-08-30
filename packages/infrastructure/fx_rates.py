"""Reading an amount paid in one currency as an amount in another.

A month of spending is rarely all in one currency. Three charges in shekels
and three in dollars come back as two totals that cannot be added, and the
person who asked how much they paid is left to finish the arithmetic in their
head with a rate they went and looked up somewhere else.

This module goes and looks the rate up instead. It reads the European Central
Bank's daily reference rates, which are published free and without a key, so
nothing here needs a credential or a per-account setting.

A receipt is converted at the rate on the day it was paid, never at today's
rate. What a purchase cost was settled on the day it happened, and re-reading
last March at this morning's rate quietly rewrites history every time the same
question is asked. The bank publishes on working days only, so a receipt dated
on a weekend or a holiday is converted at the last rate published before it -
the rate that was standing when the money moved - and the answer can say which
day that was.

Nothing here raises into an answer. A rate that cannot be read leaves the
amounts exactly as they were paid: two totals in two currencies is still a
true answer, and an invented conversion is not.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Iterable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


# Frankfurter serves the European Central Bank's published rates as JSON. It
# needs no key and stores nothing about who asked, which is why it can sit in
# the answer path without a per-account connection behind it.
DEFAULT_FX_RATES_BASE_URL = "https://api.frankfurter.dev/v1"
DEFAULT_FX_RATES_TIMEOUT_SECONDS = 6.0
DEFAULT_USER_AGENT = "Assistyca/1.0 FxRates"
FX_RATES_SOURCE_NAME = "European Central Bank"
FX_RATES_SOURCE_LABEL = f"{FX_RATES_SOURCE_NAME} daily rates"
# How far back to reach for the last published rate before a given day. A
# weekend is two days and a long national holiday can stretch past a week;
# beyond that, silence means the pair is not published rather than closed.
FX_RATE_LOOKBACK_DAYS = 10
# A rate for a day that has already passed never changes, so it is kept for
# the life of the process. Today's rate can still be republished, and a
# failed read should not be retried once per receipt.
LATEST_RATE_TTL_SECONDS = 900.0
FAILED_RATE_TTL_SECONDS = 120.0
FX_RATE_CACHE_LIMIT = 4096
# The whole span a single answer can ask about. A question covers a month or
# two; a request wider than this is a sign something is wrong upstream.
FX_RATE_MAX_SPAN_DAYS = 800

_CURRENCY_CODE_RE = re.compile(r"^[A-Za-z]{3}$")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# (base, quote, asked date) -> (rate or None, cached at)
_RATE_CACHE: dict[tuple[str, str, str], tuple["FxRate | None", float]] = {}


@dataclass(frozen=True)
class FxRate:
    """One currency read in terms of another, on a named day."""

    base: str
    quote: str
    rate: float
    # The day the bank published this rate, which is not always the day that
    # was asked about.
    rate_date: str
    asked_date: str

    @property
    def is_stale(self) -> bool:
        """True when the day asked about had no rate of its own."""

        return bool(self.asked_date) and self.asked_date != self.rate_date

    def convert(self, amount: float) -> float:
        return round(float(amount) * self.rate, 2)

    def describe(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "quote": self.quote,
            "rate": self.rate,
            "rateDate": self.rate_date,
            "askedDate": self.asked_date,
            "source": FX_RATES_SOURCE_LABEL,
        }


@dataclass
class FxRatesConfig:
    base_url: str = DEFAULT_FX_RATES_BASE_URL
    timeout_seconds: float = DEFAULT_FX_RATES_TIMEOUT_SECONDS
    user_agent: str = DEFAULT_USER_AGENT


def load_fx_rates_config(env: dict[str, str] | None = None) -> FxRatesConfig:
    """Read the rates endpoint from the environment.

    The defaults are a working public endpoint, so this is here to point at a
    mirror or a stub, not because anything has to be configured to run.
    """

    source = env if env is not None else os.environ
    base_url = str(source.get("FX_RATES_BASE_URL") or "").strip() or DEFAULT_FX_RATES_BASE_URL
    try:
        timeout = float(source.get("FX_RATES_TIMEOUT_SECONDS") or DEFAULT_FX_RATES_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_FX_RATES_TIMEOUT_SECONDS
    return FxRatesConfig(
        base_url=base_url.rstrip("/"),
        timeout_seconds=timeout if timeout > 0 else DEFAULT_FX_RATES_TIMEOUT_SECONDS,
        user_agent=str(source.get("FX_RATES_USER_AGENT") or "").strip() or DEFAULT_USER_AGENT,
    )


def normalize_currency_code(value: Any) -> str:
    """A three-letter code, or nothing.

    Amounts arrive carrying whatever the receipt wrote next to the number, so
    anything that is not a currency code is refused here rather than sent to
    the rates endpoint to be refused there.
    """

    text = str(value or "").strip().upper()
    return text if _CURRENCY_CODE_RE.match(text) else ""


def normalize_rate_date(value: Any) -> str:
    """The day an amount belongs to, as YYYY-MM-DD.

    Receipt dates arrive as mail headers, as ISO timestamps, and sometimes as
    a bare day. An unreadable one is not an error: it means this amount is
    converted at the latest published rate instead of its own.
    """

    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date_cls):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        if parsed is not None:
            return parsed.date().isoformat()
    except (IndexError, TypeError, ValueError):
        pass
    match = _ISO_DATE_RE.search(text)
    if not match:
        return ""
    try:
        return date_cls(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return ""


def reset_fx_rate_cache() -> None:
    """Forget every rate read so far."""

    _RATE_CACHE.clear()


def exchange_rate(
    base: Any,
    quote: Any,
    on_date: Any = "",
    *,
    config: FxRatesConfig | None = None,
) -> FxRate | None:
    """One currency in terms of another, on one day."""

    rates = exchange_rates_for_dates(base, quote, [on_date], config=config)
    return rates.get(normalize_rate_date(on_date))


def exchange_rates_for_dates(
    base: Any,
    quote: Any,
    dates: Iterable[Any],
    *,
    config: FxRatesConfig | None = None,
) -> dict[str, FxRate]:
    """Every day's rate for one pair, read in as few requests as possible.

    Sixty receipts spread over a month are sixty different days, and asking
    the endpoint once per receipt would be sixty requests to answer one
    question. The bank publishes a span at a time, so a span is what is read.
    """

    base_code = normalize_currency_code(base)
    quote_code = normalize_currency_code(quote)
    if not base_code or not quote_code:
        return {}
    asked = _unique_dates(dates)
    if not asked:
        return {}
    if base_code == quote_code:
        # The same currency needs no endpoint and no rate that could fail.
        return {
            day: FxRate(base=base_code, quote=quote_code, rate=1.0, rate_date=day, asked_date=day)
            for day in asked
        }

    settings = config or load_fx_rates_config()
    now = _now_seconds()
    found: dict[str, FxRate] = {}
    missing: list[str] = []
    for day in asked:
        cached = _cached_rate(base_code, quote_code, day, now=now)
        if cached is _CACHE_MISS:
            missing.append(day)
        elif cached is not None:
            found[day] = cached  # type: ignore[assignment]
    if not missing:
        return found

    series = _read_rate_series(base_code, quote_code, missing, config=settings)
    if series is None:
        # The endpoint could not be read. Remember that briefly so one broken
        # answer is one failed request, not one per receipt in it.
        for day in missing:
            _remember_rate(base_code, quote_code, day, None, now=now, ttl=FAILED_RATE_TTL_SECONDS)
        return found

    published = sorted(series)
    for day in missing:
        rate_date = _latest_on_or_before(published, day)
        if rate_date is None:
            _remember_rate(base_code, quote_code, day, None, now=now, ttl=FAILED_RATE_TTL_SECONDS)
            continue
        rate = FxRate(
            base=base_code,
            quote=quote_code,
            rate=series[rate_date],
            rate_date=rate_date,
            asked_date=day,
        )
        found[day] = rate
        _remember_rate(base_code, quote_code, day, rate, now=now, ttl=_ttl_for(day))
    return found


def convert_amounts(
    entries: Iterable[dict[str, Any]],
    *,
    target: Any,
    config: FxRatesConfig | None = None,
) -> dict[str, Any]:
    """Add up amounts in several currencies as one figure in the target one.

    Each entry is an amount, the currency it was paid in, and the day it was
    paid. What comes back says how much was converted and how much could not
    be, because an answer that quietly drops the receipts it could not convert
    reads exactly like an answer that converted everything.
    """

    target_code = normalize_currency_code(target)
    if not target_code:
        return _empty_conversion(target_code)

    wanted: dict[str, set[str]] = {}
    prepared: list[tuple[float, str, str]] = []
    for entry in entries:
        amount = _safe_amount(entry.get("amount"))
        currency = normalize_currency_code(entry.get("currency"))
        if amount is None or not currency:
            continue
        day = normalize_rate_date(entry.get("date"))
        prepared.append((amount, currency, day))
        if currency != target_code:
            wanted.setdefault(currency, set()).add(day)
    if not prepared:
        return _empty_conversion(target_code)

    rates: dict[str, dict[str, FxRate]] = {}
    for currency, days in wanted.items():
        rates[currency] = exchange_rates_for_dates(currency, target_code, days, config=config)

    total = 0.0
    converted_count = 0
    # How much of it actually needed a rate. A set where only the amounts
    # already in the target currency came through has not been converted at
    # all, however many of them there were.
    rated_count = 0
    unconverted: dict[str, float] = {}
    unconverted_count = 0
    used: dict[str, FxRate] = {}
    for amount, currency, day in prepared:
        if currency == target_code:
            total += amount
            converted_count += 1
            continue
        rate = rates.get(currency, {}).get(day)
        if rate is None:
            unconverted[currency] = round(unconverted.get(currency, 0.0) + amount, 2)
            unconverted_count += 1
            continue
        total += rate.convert(amount)
        converted_count += 1
        rated_count += 1
        # One rate per currency is enough to say what the conversion used;
        # naming all sixty would bury the answer it is supporting.
        if currency not in used or rate.rate_date > used[currency].rate_date:
            used[currency] = rate
    return {
        "currency": target_code,
        "amount": round(total, 2),
        "convertedCount": converted_count,
        "ratedCount": rated_count,
        "unconvertedTotals": unconverted,
        "unconvertedCount": unconverted_count,
        "rates": {code: rate.describe() for code, rate in sorted(used.items())},
        "source": FX_RATES_SOURCE_LABEL,
    }


def describe_conversion(conversion: dict[str, Any] | None) -> str:
    """The converted total as one sentence, or nothing to say.

    This is the sentence the application can always fall back on. It states
    the figure and what it rests on, and it says when part of the money could
    not be converted rather than folding that silently into the total.
    """

    if not isinstance(conversion, dict):
        return ""
    currency = normalize_currency_code(conversion.get("currency"))
    if not currency or not int(conversion.get("ratedCount") or 0):
        return ""
    amount = _safe_amount(conversion.get("amount"))
    if amount is None:
        return ""
    sentence = f"That comes to about {amount:,.2f} {currency} in total, converted at each receipt's own date."
    leftover = conversion.get("unconvertedTotals") if isinstance(conversion.get("unconvertedTotals"), dict) else {}
    if leftover:
        amounts = " and ".join(f"{value:,.2f} {code}" for code, value in sorted(leftover.items()))
        sentence += f" I could not find a rate for {amounts}, so that is not in the figure."
    return sentence


def describe_rate(rate: FxRate | None) -> str:
    """One rate as a sentence, including the day it really came from.

    A rate is only true of a day, and the day asked about is not always the
    day the bank published one. Saying which day it is keeps "the rate" from
    quietly meaning "some rate near then".
    """

    if rate is None:
        return ""
    published = format_rate_date(rate.rate_date)
    figure = f"1 {rate.base} is {rate.rate:,.4f} {rate.quote}"
    if not rate.asked_date:
        return f"{figure} at the moment, on the {FX_RATES_SOURCE_NAME} rate published on {published}."
    asked = format_rate_date(rate.asked_date)
    if not rate.is_stale:
        return f"On {asked}, 1 {rate.base} was {rate.rate:,.4f} {rate.quote}."
    return (
        f"Nothing was published on {asked}, so the rate standing that day was the one from {published}: "
        f"1 {rate.base} to {rate.rate:,.4f} {rate.quote}."
    )


def format_rate_date(value: Any) -> str:
    """A rate date the way it would be said out loud."""

    day = normalize_rate_date(value)
    if not day:
        return ""
    try:
        return date_cls.fromisoformat(day).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return day


def describe_rate_record(rate: FxRate | None) -> dict[str, str]:
    """The rate as one flat record, for answering a question from it."""

    if rate is None:
        return {}
    record = {
        "kind": "exchange rate",
        "pair": f"{rate.base}/{rate.quote}",
        "rate": f"{rate.rate:,.4f}",
        "date": format_rate_date(rate.rate_date),
        "askedAbout": format_rate_date(rate.asked_date) or "now",
        "source": FX_RATES_SOURCE_LABEL,
    }
    return {key: value for key, value in record.items() if value}


_CACHE_MISS = object()


def _empty_conversion(currency: str) -> dict[str, Any]:
    return {
        "currency": currency,
        "amount": 0.0,
        "convertedCount": 0,
        "ratedCount": 0,
        "unconvertedTotals": {},
        "unconvertedCount": 0,
        "rates": {},
        "source": FX_RATES_SOURCE_LABEL,
    }


def _unique_dates(dates: Iterable[Any]) -> list[str]:
    seen: list[str] = []
    for value in dates:
        day = normalize_rate_date(value)
        if day not in seen:
            seen.append(day)
    return seen


def _read_rate_series(
    base: str,
    quote: str,
    days: list[str],
    *,
    config: FxRatesConfig,
) -> dict[str, float] | None:
    """Every published rate covering the days asked about.

    An empty day means the latest rate, which the endpoint answers on its own.
    Real days are read as one span reaching back far enough to find the last
    publication before the earliest of them.
    """

    dated = sorted(day for day in days if day)
    if not dated:
        payload = _get_json(f"{config.base_url}/latest", base, quote, config=config)
        rate = _single_rate(payload, quote)
        if rate is None:
            return None
        # The latest rate answers for "no date", and for the day it names.
        return {"": rate[1], rate[0]: rate[1]}

    start = _shift_days(dated[0], -FX_RATE_LOOKBACK_DAYS)
    end = dated[-1]
    if not start or _span_days(start, end) > FX_RATE_MAX_SPAN_DAYS:
        return None
    series: dict[str, float] = {}
    payload = _get_json(f"{config.base_url}/{start}..{end}", base, quote, config=config)
    rows = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        return None
    for day, values in rows.items():
        published = normalize_rate_date(day)
        value = _safe_amount((values or {}).get(quote)) if isinstance(values, dict) else None
        if published and value:
            series[published] = value
    if not series:
        return None
    if "" in days:
        # A dateless amount rides along with the latest day in the span.
        series[""] = series[max(series)]
    return series


def _single_rate(payload: dict[str, Any] | None, quote: str) -> tuple[str, float] | None:
    if not isinstance(payload, dict):
        return None
    rates = payload.get("rates")
    value = _safe_amount(rates.get(quote)) if isinstance(rates, dict) else None
    if not value:
        return None
    return normalize_rate_date(payload.get("date")), value


def _get_json(url: str, base: str, quote: str, *, config: FxRatesConfig) -> dict[str, Any] | None:
    query = urllib_parse.urlencode({"base": base, "symbols": quote})
    request = urllib_request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/json", "User-Agent": config.user_agent},
        method="GET",
    )
    try:
        with urllib_request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib_error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"Exchange rate lookup failed for {base}/{quote}: {exc}", flush=True)
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _latest_on_or_before(published: list[str], day: str) -> str | None:
    """The rate that was standing on a given day.

    The bank does not publish at weekends, so the rate a Sunday purchase was
    made at is the one published on the Friday before it.
    """

    if not published:
        return None
    if not day:
        return published[-1]
    candidates = [value for value in published if value and value <= day]
    if candidates:
        return candidates[-1]
    return None


def _cached_rate(base: str, quote: str, day: str, *, now: float) -> Any:
    entry = _RATE_CACHE.get((base, quote, day))
    if entry is None:
        return _CACHE_MISS
    rate, expires_at = entry
    if expires_at and expires_at <= now:
        _RATE_CACHE.pop((base, quote, day), None)
        return _CACHE_MISS
    return rate


def _remember_rate(
    base: str,
    quote: str,
    day: str,
    rate: FxRate | None,
    *,
    now: float,
    ttl: float,
) -> None:
    if len(_RATE_CACHE) >= FX_RATE_CACHE_LIMIT:
        _RATE_CACHE.clear()
    _RATE_CACHE[(base, quote, day)] = (rate, now + ttl if ttl else 0.0)


def _ttl_for(day: str) -> float:
    """A day that has already ended keeps its rate forever."""

    today = datetime.now(timezone.utc).date().isoformat()
    return 0.0 if day and day < today else LATEST_RATE_TTL_SECONDS


def _shift_days(day: str, delta: int) -> str:
    try:
        return (date_cls.fromisoformat(day) + timedelta(days=delta)).isoformat()
    except ValueError:
        return ""


def _span_days(start: str, end: str) -> int:
    try:
        return (date_cls.fromisoformat(end) - date_cls.fromisoformat(start)).days
    except ValueError:
        return 0


def _safe_amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _now_seconds() -> float:
    return datetime.now(timezone.utc).timestamp()


__all__ = [
    "DEFAULT_FX_RATES_BASE_URL",
    "FX_RATES_SOURCE_LABEL",
    "FX_RATES_SOURCE_NAME",
    "FxRate",
    "FxRatesConfig",
    "convert_amounts",
    "describe_conversion",
    "describe_rate",
    "describe_rate_record",
    "exchange_rate",
    "exchange_rates_for_dates",
    "format_rate_date",
    "load_fx_rates_config",
    "normalize_currency_code",
    "normalize_rate_date",
    "reset_fx_rate_cache",
]
