"""The groupings a spending question is usually really about.

The totals a lookup already computes answer one shape of question: how much,
over this period, to this vendor. Everything else - which vendor is the
biggest, what repeats every month, what is new since last month, what stopped,
which single charge stands out - was left to the model to work out by reading
sixty receipts and doing the sums in its head.

That is the one thing the model should not be doing. The figures belong in
code, where they can be checked and cannot drift; the words belong to the
model. So the groupings are computed here, handed over as settled, and the
reply only has to say which of them answers the question.

Grouping happens inside a currency, never across one. Adding a shekel to a
dollar to find the biggest vendor produces a ranking that is wrong in a way
nobody can see. Where receipts arrive in two currencies, each currency is
grouped on its own and the answer says so.
"""

from __future__ import annotations

import re
from typing import Any

# How many entries a grouping carries. A question about vendors wants the ones
# that matter, and a list past this length stops being an answer and starts
# being the spreadsheet the export already is.
GROUP_LIMIT = 12
# The single receipts worth naming beside a total. Enough to show what the
# money went on, short enough to read.
LARGEST_LIMIT = 5
# A vendor billing in this many of the months read is a subscription rather
# than a purchase.
REPEATING_MIN_MONTHS = 2

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ISO_MONTH_RE = re.compile(r"\b(\d{4})-(\d{1,2})\b")
_TEXT_MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b",
    re.IGNORECASE,
)
_DAY_MONTH_YEAR_RE = re.compile(
    r"\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b",
    re.IGNORECASE,
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _amount(value: Any) -> float | None:
    """The number on a receipt, however the amount field carries it.

    A record holds "19.00 USD" and a row holds "19.00" beside its currency, so
    both shapes reach here. Anything that is not a number is not an amount,
    and a receipt whose total could not be read is left out of a grouping
    rather than counted as zero - zero is a figure, and "unreadable" is not.
    """

    text = _clean(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _currency(*values: Any) -> str:
    for value in values:
        text = _clean(value).upper()
        match = re.search(r"\b([A-Z]{3})\b", text)
        if match:
            return match.group(1)
    return ""


def month_key(*values: Any) -> str:
    """The month a receipt belongs to, as YYYY-MM.

    Dates arrive as mail headers, as the month label a run was given, and as
    whatever the vendor wrote. A receipt whose month cannot be read is grouped
    under nothing rather than under the wrong month.
    """

    for value in values:
        text = _clean(value)
        if not text:
            continue
        iso = _ISO_MONTH_RE.search(text)
        if iso:
            month = int(iso.group(2))
            if 1 <= month <= 12:
                return f"{iso.group(1)}-{month:02d}"
        for pattern in (_DAY_MONTH_YEAR_RE, _TEXT_MONTH_RE):
            named = pattern.search(text)
            if named:
                return f"{named.group(2)}-{_MONTHS[named.group(1).lower()]:02d}"
    return ""


def _entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows as the three things every grouping needs of them."""

    entries: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        amount = _amount(row.get("amount"))
        if amount is None:
            continue
        currency = _currency(row.get("currency"), row.get("amount"))
        if not currency:
            continue
        vendor = _clean(row.get("paidTo")) or _clean(row.get("vendor"))
        entries.append({
            "vendor": vendor or "Unknown vendor",
            "amount": amount,
            "currency": currency,
            "month": month_key(row.get("date"), row.get("month")),
            "subject": _clean(row.get("subject")),
            "date": _clean(row.get("date")),
        })
    return entries


def _round(value: float) -> float:
    return round(value + 0.0, 2)


def group_by_vendor(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What each vendor came to, biggest first, inside its own currency."""

    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (entry["vendor"].casefold(), entry["currency"])
        bucket = totals.setdefault(key, {
            "vendor": entry["vendor"],
            "currency": entry["currency"],
            "total": 0.0,
            "count": 0,
            "months": set(),
        })
        bucket["total"] += entry["amount"]
        bucket["count"] += 1
        if entry["month"]:
            bucket["months"].add(entry["month"])
    ranked = sorted(totals.values(), key=lambda item: (-item["total"], item["vendor"]))
    return [
        {
            "vendor": item["vendor"],
            "currency": item["currency"],
            "total": _round(item["total"]),
            "count": item["count"],
            "months": len(item["months"]),
        }
        for item in ranked[:GROUP_LIMIT]
    ]


def group_by_month(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What each month came to, oldest first, inside its own currency."""

    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        if not entry["month"]:
            continue
        key = (entry["month"], entry["currency"])
        bucket = totals.setdefault(key, {
            "month": entry["month"],
            "currency": entry["currency"],
            "total": 0.0,
            "count": 0,
        })
        bucket["total"] += entry["amount"]
        bucket["count"] += 1
    ordered = sorted(totals.values(), key=lambda item: (item["month"], item["currency"]))
    return [
        {
            "month": item["month"],
            "currency": item["currency"],
            "total": _round(item["total"]),
            "count": item["count"],
        }
        for item in ordered[:GROUP_LIMIT]
    ]


def largest_receipts(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The few single charges worth naming beside a total.

    A month that moved is usually one unusual item rather than everything
    drifting up, and this is where that item shows itself.
    """

    ranked = sorted(entries, key=lambda entry: (-entry["amount"], entry["vendor"]))
    return [
        {
            "vendor": entry["vendor"],
            "amount": _round(entry["amount"]),
            "currency": entry["currency"],
            "date": entry["date"],
            "subject": entry["subject"],
        }
        for entry in ranked[:LARGEST_LIMIT]
    ]


def describe_vendor_movement(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """What repeats, what is new, and what stopped, across the months read.

    Only worth anything over more than one month: a single month has nothing
    to be new against and nothing to have stopped since.
    """

    months = sorted({entry["month"] for entry in entries if entry["month"]})
    if len(months) < 2:
        return {}
    latest = months[-1]
    earlier = set(months[:-1])
    by_vendor: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not entry["month"]:
            continue
        bucket = by_vendor.setdefault(entry["vendor"].casefold(), {
            "vendor": entry["vendor"],
            "months": set(),
        })
        bucket["months"].add(entry["month"])

    repeating: list[str] = []
    started: list[str] = []
    stopped: list[str] = []
    for bucket in sorted(by_vendor.values(), key=lambda item: item["vendor"]):
        seen = bucket["months"]
        if len(seen) >= REPEATING_MIN_MONTHS:
            repeating.append(bucket["vendor"])
        if latest in seen and not (seen & earlier):
            started.append(bucket["vendor"])
        if latest not in seen and (seen & earlier):
            stopped.append(bucket["vendor"])
    movement: dict[str, Any] = {"monthsRead": months}
    if repeating:
        movement["billingInSeveralMonths"] = repeating[:GROUP_LIMIT]
    if started:
        movement["firstSeenInLatestMonth"] = started[:GROUP_LIMIT]
    if stopped:
        movement["absentFromLatestMonth"] = stopped[:GROUP_LIMIT]
    return movement


def group_receipt_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every grouping a spending question is usually about, computed once.

    Handed to the reply as settled figures. Nothing here decides what the
    question was: it offers the shapes, and the answer takes the one it needs.
    """

    entries = _entries(rows)
    if not entries:
        return {}
    groups: dict[str, Any] = {
        "countedReceipts": len(entries),
        "byVendor": group_by_vendor(entries),
    }
    months = group_by_month(entries)
    if len(months) > 1:
        groups["byMonth"] = months
    largest = largest_receipts(entries)
    if len(largest) > 1:
        groups["largestReceipts"] = largest
    movement = describe_vendor_movement(entries)
    if movement:
        groups["vendorMovement"] = movement
    return groups
