"""How often a vendor charges, and whether the charging is still going on.

"Am I paying for PlayStation Plus?" is not a question about a total. It is a
question about now, and a receipt on its own cannot answer it: 550 shekels in
May is a live subscription if it is billed once a year and a cancelled one if
it is billed every month. What settles it is the rhythm - how far apart the
charges sit, what the receipt calls the period, and how long it has been since
the last one.

None of that is a judgement, so all of it is worked out here and the deciding
is left to whoever reads it. Where the receipts cannot settle the rhythm this
says so plainly rather than picking the likelier answer: an unsure answer that
admits it can be checked against the vendor's published price, or handed back
to the person, who knows what they signed up for.
"""

from __future__ import annotations

import re
from datetime import date
from datetime import datetime
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

# How many charges travel with the rhythm. Enough to show the pattern and to
# name the last few dates; a year of monthly billing is twelve.
SUBSCRIPTION_MAX_CHARGES = 12

CADENCE_WEEKLY = "weekly"
CADENCE_MONTHLY = "monthly"
CADENCE_QUARTERLY = "quarterly"
CADENCE_YEARLY = "yearly"
CADENCE_UNCLEAR = "unclear"

# What a gap between two charges has to be to count as one of the rhythms
# people are actually billed on. A gap outside all of them is a rhythm this
# does not recognise, which is said rather than rounded to the nearest one.
_GAP_RANGES = (
    (CADENCE_WEEKLY, 5, 9),
    (CADENCE_MONTHLY, 24, 38),
    (CADENCE_QUARTERLY, 80, 100),
    (CADENCE_YEARLY, 330, 400),
)

# The period a receipt names in its own words. A plan sold as "12 months" is a
# yearly charge however the bill is dated, and a line saying "per month" is the
# vendor telling us the rhythm outright.
_PERIOD_PATTERNS = (
    (CADENCE_YEARLY, re.compile(
        r"\b(?:12[\s-]?months?|1[\s-]?year|one[\s-]?year|annual(?:ly)?|yearly|per\s+year|/\s?yr|12[\s-]?month\s+membership)\b",
        re.IGNORECASE,
    )),
    (CADENCE_YEARLY, re.compile("שנתי|לשנה|למשך שנה")),
    (CADENCE_MONTHLY, re.compile(
        r"\b(?:monthly|per\s+month|a\s+month|/\s?mo\b|1[\s-]?month|one[\s-]?month|month(?:ly)?\s+(?:plan|subscription|membership))\b",
        re.IGNORECASE,
    )),
    (CADENCE_MONTHLY, re.compile("חודשי|לחודש")),
    (CADENCE_QUARTERLY, re.compile(r"\b(?:quarterly|3[\s-]?months?|per\s+quarter)\b", re.IGNORECASE)),
    (CADENCE_WEEKLY, re.compile(r"\b(?:weekly|per\s+week|/\s?wk\b)\b", re.IGNORECASE)),
)

# A renewal date the vendor printed. It says the subscription was alive when
# the receipt was written, and when the next charge was meant to land.
_RENEWAL_PATTERNS = (
    re.compile(r"\b(?:renews?|renewal|next\s+(?:payment|charge|billing)|next\s+bill(?:ed)?)\b", re.IGNORECASE),
    re.compile("מתחדש|חידוש"),
)
# Words a vendor uses when the subscription has been stopped. One of these on
# the newest receipt outweighs any rhythm the dates suggest.
_ENDED_PATTERNS = (
    re.compile(r"\b(?:cancell?ed|cancellation|refunded|subscription\s+(?:ended|expired)|will\s+not\s+renew)\b", re.IGNORECASE),
    re.compile("בוטל|ביטול"),
)

# How long past a due date a charge may be before the rhythm is treated as
# broken. Cards fail and vendors bill late, so a few days late is still a
# running subscription; a month late on a monthly plan is not.
_GRACE_DAYS = {
    CADENCE_WEEKLY: 4,
    CADENCE_MONTHLY: 12,
    CADENCE_QUARTERLY: 20,
    CADENCE_YEARLY: 35,
}

_AMOUNT_RE = re.compile(r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<currency>[A-Z]{3})?")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _read_date(value: Any) -> date | None:
    """The day a receipt carries, from a mail header or a plain date."""

    text = _clean(value)
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (IndexError, TypeError, ValueError):
        parsed = None
    if parsed is None:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text[:10], pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.date()


def _read_amount(value: Any) -> tuple[str, str]:
    """The number and the currency a record's amount line carries."""

    text = _clean(value)
    if not text:
        return "", ""
    match = _AMOUNT_RE.search(text.upper())
    if not match:
        return "", ""
    amount = match.group("amount").replace(",", "")
    return amount, match.group("currency") or ""


def _record_text(record: dict[str, Any]) -> str:
    return " ".join(
        _clean(record.get(key))
        for key in ("subject", "detail", "vendor", "paidTo")
        if _clean(record.get(key))
    )


def _period_in_words(text: str) -> tuple[str, str]:
    """The billing period the receipt names, and the words that named it."""

    for cadence, pattern in _PERIOD_PATTERNS:
        match = pattern.search(text)
        if match:
            return cadence, _clean(match.group(0))
    return "", ""


def _cadence_for_gap(days: int) -> str:
    """The rhythm a gap of this many days belongs to, if it belongs to one."""

    for cadence, low, high in _GAP_RANGES:
        if low <= days <= high:
            return cadence
    return ""


_MONTHS_AHEAD = {CADENCE_MONTHLY: 1, CADENCE_QUARTERLY: 3, CADENCE_YEARLY: 12}


def _next_due(last: date, cadence: str) -> date | None:
    """When the next charge falls, counted the way a vendor counts it.

    A monthly plan billed on the 6th is billed on the 6th again, not thirty
    days later, and a yearly one lands on the same date next year. Counting in
    days instead drifts, and a drifting due date turns a subscription that is
    running into one that looks overdue.
    """

    if cadence == CADENCE_WEEKLY:
        return date.fromordinal(last.toordinal() + 7)
    months = _MONTHS_AHEAD.get(cadence)
    if not months:
        return None
    month = last.month - 1 + months
    year = last.year + month // 12
    month = month % 12 + 1
    day = last.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


def read_subscription_rhythm(
    records: Any,
    *,
    vendor: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """What the receipts say about how often this vendor charges.

    ``records`` are the flat receipt lines an answer already carries - a date,
    an amount, a subject and enough of the body to read. Anything without a
    date it can place is left out of the rhythm and counted, because a charge
    with no date cannot sit in a sequence.
    """

    reference = today or datetime.now(timezone.utc).date()
    charges: list[dict[str, Any]] = []
    undated = 0
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        when = _read_date(record.get("date"))
        if when is None:
            undated += 1
            continue
        amount, currency = _read_amount(record.get("amount"))
        charges.append({
            "date": when.isoformat(),
            "amount": amount,
            "currency": currency,
            "subject": _clean(record.get("subject"))[:200],
            "text": _record_text(record),
            "day": when,
        })
    charges.sort(key=lambda entry: entry["day"], reverse=True)

    if not charges:
        return {
            "vendor": _clean(vendor),
            "chargeCount": 0,
            "undatedChargeCount": undated,
            "cadence": CADENCE_UNCLEAR,
            "cadenceFrom": "",
            "settled": False,
            "unsettled": ["whether anything is being paid at all"],
        }

    newest = charges[0]
    oldest = charges[-1]
    gaps = [
        (charges[index]["day"] - charges[index + 1]["day"]).days
        for index in range(len(charges) - 1)
    ]
    # Two receipts for one payment land days apart and would read as a weekly
    # subscription. A gap too short to be a billing period is not one.
    spacing = [gap for gap in gaps if gap >= 4]
    typical_gap = _median(spacing) if spacing else 0
    from_gaps = _cadence_for_gap(typical_gap) if typical_gap else ""

    newest_text = newest["text"]
    from_words, words = _period_in_words(newest_text)
    if not from_words:
        from_words, words = _period_in_words(" ".join(charge["text"] for charge in charges))

    # The dates are what the vendor actually did, so they lead. Where the
    # wording disagrees with them neither is dropped: both go back, and the
    # rhythm is reported as something the receipts did not settle.
    cadence = from_gaps or from_words or CADENCE_UNCLEAR
    sources: list[str] = []
    if from_gaps:
        sources.append("the gaps between the charges")
    if from_words:
        sources.append("the period the receipt names")

    # A subscription charges the same amount every time, so amounts that move
    # are a reason to doubt the rhythm. Receipts whose amount could not be read
    # say nothing either way and are left out of the comparison.
    amounts = {(charge["amount"], charge["currency"]) for charge in charges if charge["amount"]}
    amounts_agree = len(amounts) <= 1

    ended = any(pattern.search(newest_text) for pattern in _ENDED_PATTERNS)
    renewal_mentioned = any(pattern.search(newest_text) for pattern in _RENEWAL_PATTERNS)

    days_since = (reference - newest["day"]).days
    next_expected = ""
    still_running: bool | None = None
    due = _next_due(newest["day"], cadence)
    if due is not None:
        next_expected = due.isoformat()
        # A charge that has not landed yet is a subscription that is running.
        # One overdue by more than the grace is one that has stopped.
        still_running = (reference - due).days <= _GRACE_DAYS.get(cadence, 14)
    if ended:
        still_running = False

    unsettled: list[str] = []
    if cadence == CADENCE_UNCLEAR:
        unsettled.append("how often this is billed")
    if from_gaps and from_words and from_gaps != from_words:
        unsettled.append(
            f"the dates are {from_gaps} but the receipt says {from_words}"
        )
    if len(charges) == 1 and not from_words:
        unsettled.append("only one charge was found, so there is no rhythm to read")
    if not amounts_agree:
        unsettled.append("the amounts are not all the same")
    if still_running is None:
        unsettled.append("whether it is still running")

    return {
        "vendor": _clean(vendor),
        "chargeCount": len(charges),
        "undatedChargeCount": undated,
        # Newest first, because "when did I last pay for this" is the question
        # underneath almost every question about a subscription.
        "charges": [
            {
                "date": charge["date"],
                "amount": f"{charge['amount']} {charge['currency']}".strip(),
                "subject": charge["subject"],
            }
            for charge in charges[:SUBSCRIPTION_MAX_CHARGES]
        ],
        "firstCharge": oldest["date"],
        "lastCharge": newest["date"],
        "daysSinceLastCharge": days_since,
        "cadence": cadence,
        "cadenceFrom": " and ".join(sources),
        "cadenceInWords": words,
        "typicalGapDays": typical_gap,
        "amountsAgree": amounts_agree,
        "lastAmount": f"{newest['amount']} {newest['currency']}".strip(),
        "nextExpected": next_expected,
        "stillRunning": still_running,
        "vendorSaysCancelled": ended,
        "vendorNamedARenewal": renewal_mentioned,
        # Everything the receipts could not settle. An empty list is the only
        # thing that makes this answer safe to state flatly.
        "unsettled": unsettled,
        "settled": not unsettled,
    }


__all__ = [
    "CADENCE_MONTHLY",
    "CADENCE_QUARTERLY",
    "CADENCE_UNCLEAR",
    "CADENCE_WEEKLY",
    "CADENCE_YEARLY",
    "SUBSCRIPTION_MAX_CHARGES",
    "read_subscription_rhythm",
]
