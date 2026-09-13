"""Policy normalization and conservative receipt-to-coverage matching.

The original policy is the authority.  The structured coverage beside it is
an index: useful for finding the few clauses worth reading, but never a
replacement for those clauses.  This module deliberately returns potential
claims rather than coverage decisions; an insurer can still apply definitions,
conditions and facts that are not present on a receipt.
"""

from __future__ import annotations

import re
from datetime import date
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any


INSURANCE_POLICY_STATUSES = ("active", "expired", "cancelled")
INSURANCE_REVIEW_STATUSES = ("unreviewed", "reviewed")
INSURANCE_MATCH_STATUSES = (
    "likely_worth_claiming",
    "possible_more_information_needed",
    "deductible_may_exceed_expense",
)
MAX_COVERAGES_PER_VERSION = 100
MAX_EVIDENCE_QUOTE_LENGTH = 1200

_CATEGORY_ALIASES = {
    "auto": "vehicle",
    "automobile": "vehicle",
    "car": "vehicle",
    "collision": "vehicle",
    "roadside": "vehicle",
    "towing": "vehicle",
    "doctor": "medical",
    "dental": "medical",
    "health": "medical",
    "healthcare": "medical",
    "hospital": "medical",
    "pharmacy": "medical",
    "pet": "veterinary",
    "vet": "veterinary",
    "property": "home",
    "house": "home",
    "flight": "travel",
    "hotel": "travel",
    "baggage": "travel",
    "cybersecurity": "cyber",
    "professional indemnity": "professional_liability",
    "errors and omissions": "professional_liability",
    "e&o": "professional_liability",
    "public liability": "general_liability",
}

_TOKEN_RE = re.compile(r"[\w&]+", re.UNICODE)


def clean_text(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def normalize_iso_date(value: Any, *, field: str, required: bool = False) -> str:
    text = clean_text(value, 20)
    if not text:
        if required:
            raise ValueError(f"{field} is required.")
        return ""
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD.") from exc


def normalize_money(value: Any, *, field: str) -> str:
    text = clean_text(value, 40).replace(",", "")
    if not text:
        return ""
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a number.") from exc
    if amount < 0:
        raise ValueError(f"{field} cannot be negative.")
    return format(amount.quantize(Decimal("0.01")), "f")


def normalize_currency(value: Any) -> str:
    currency = clean_text(value, 3).upper()
    if currency and (len(currency) != 3 or not currency.isalpha()):
        raise ValueError("Currency must be a three-letter code such as USD or ILS.")
    return currency


def normalize_category(value: Any) -> str:
    text = clean_text(value, 80).casefold().replace("-", " ").replace("_", " ")
    text = " ".join(text.split())
    canonical = _CATEGORY_ALIASES.get(text, text)
    return canonical.replace(" ", "_")


def _text_list(value: Any, *, limit: int = 30, item_limit: int = 300) -> list[str]:
    values = value if isinstance(value, list) else []
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = clean_text(raw, item_limit)
        folded = text.casefold()
        if text and folded not in seen:
            output.append(text)
            seen.add(folded)
        if len(output) >= limit:
            break
    return output


def normalize_coverage(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    category = normalize_category(raw.get("category"))
    summary = clean_text(raw.get("summary"), 1000)
    if not category or not summary:
        raise ValueError("Each coverage needs a category and summary.")

    evidence_raw = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    evidence = {
        "section": clean_text(evidence_raw.get("section"), 200),
        "pages": clean_text(evidence_raw.get("pages"), 80),
        "quote": clean_text(evidence_raw.get("quote"), MAX_EVIDENCE_QUOTE_LENGTH),
    }
    evidence = {key: item for key, item in evidence.items() if item}

    limit_amount = normalize_money(raw.get("limitAmount"), field="Coverage limit")
    deductible_amount = normalize_money(raw.get("deductibleAmount"), field="Coverage deductible")
    currency = normalize_currency(raw.get("currency"))
    try:
        deadline_days = int(raw.get("claimDeadlineDays") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Claim deadline must be a number of days.") from exc
    if deadline_days < 0 or deadline_days > 3650:
        raise ValueError("Claim deadline must be between 0 and 3650 days.")

    coverage: dict[str, Any] = {
        "category": category,
        "summary": summary,
        "coveredSubjects": _text_list(raw.get("coveredSubjects"), limit=20, item_limit=160),
        "conditions": _text_list(raw.get("conditions")),
        "exclusions": _text_list(raw.get("exclusions")),
        "limitAmount": limit_amount,
        "deductibleAmount": deductible_amount,
        "currency": currency,
        "claimDeadlineDays": deadline_days,
        "evidence": evidence,
    }
    return coverage


def normalize_coverages(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, list) else []
    if len(values) > MAX_COVERAGES_PER_VERSION:
        raise ValueError(f"A policy version can hold at most {MAX_COVERAGES_PER_VERSION} coverages.")
    return [normalize_coverage(entry) for entry in values]


def normalize_policy_version(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    effective_from = normalize_iso_date(raw.get("effectiveFrom"), field="Effective-from date", required=True)
    effective_to = normalize_iso_date(raw.get("effectiveTo"), field="Effective-to date")
    if effective_to and effective_to < effective_from:
        raise ValueError("Effective-to date cannot be before effective-from date.")
    return {
        "effectiveFrom": effective_from,
        "effectiveTo": effective_to,
        "summary": clean_text(raw.get("summary"), 4000),
        "coverages": normalize_coverages(raw.get("coverages")),
        "reviewStatus": (
            clean_text(raw.get("reviewStatus"), 20).casefold()
            if clean_text(raw.get("reviewStatus"), 20).casefold() in INSURANCE_REVIEW_STATUSES
            else "unreviewed"
        ),
        "sourceName": clean_text(raw.get("sourceName"), 240),
        "sourceMimeType": clean_text(raw.get("sourceMimeType"), 100).casefold(),
        "sourceReference": clean_text(raw.get("sourceReference"), 1000),
        "sourceText": str(raw.get("sourceText") or "")[:250_000],
    }


def normalize_expense(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    amount_value = raw.get("amount")
    currency_value = raw.get("currency")
    amount_text = clean_text(amount_value, 60)
    if not clean_text(currency_value, 3):
        combined = re.fullmatch(r"([+-]?[0-9][0-9,.]*)\s+([A-Za-z]{3})", amount_text)
        if combined:
            amount_value = combined.group(1)
            currency_value = combined.group(2)
    expense_date = ""
    raw_date = clean_text(raw.get("date"), 100)
    if raw_date:
        try:
            expense_date = normalize_iso_date(raw_date, field="Expense date")
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw_date)
                expense_date = parsed.date().isoformat() if parsed is not None else ""
            except (IndexError, TypeError, ValueError):
                expense_date = ""
    return {
        "date": expense_date,
        "amount": normalize_money(amount_value, field="Expense amount"),
        "currency": normalize_currency(currency_value),
        "category": normalize_category(raw.get("category")),
        "description": clean_text(raw.get("description"), 1000),
        "vendor": clean_text(raw.get("vendor"), 240),
        "subject": clean_text(raw.get("subject"), 240),
        "receiptReference": clean_text(raw.get("receiptReference"), 500),
    }


def version_applies_on(version: dict[str, Any], event_date: str) -> bool:
    """Whether this immutable policy version was in force on an event date."""

    if not event_date:
        return True
    start = clean_text(version.get("effectiveFrom"), 10)
    end = clean_text(version.get("effectiveTo"), 10)
    return bool(start and start <= event_date and (not end or event_date <= end))


def choose_applicable_version(versions: list[dict[str, Any]], event_date: str) -> dict[str, Any] | None:
    candidates = [version for version in versions if version_applies_on(version, event_date)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (clean_text(item.get("effectiveFrom"), 10), int(item.get("versionNumber") or 0)))


def _tokens(*values: Any) -> set[str]:
    words: set[str] = set()
    for value in values:
        normalized = clean_text(value, 2000).casefold().replace("_", " ").replace("-", " ")
        for word in _TOKEN_RE.findall(normalized):
            if len(word) < 3:
                continue
            words.add(word)
            alias = _CATEGORY_ALIASES.get(word)
            if alias:
                words.update(alias.replace("_", " ").split())
    return words


def _category_score(expense: dict[str, Any], policy: dict[str, Any], coverage: dict[str, Any]) -> tuple[float, str]:
    wanted = normalize_category(expense.get("category"))
    offered = normalize_category(coverage.get("category"))
    if wanted and wanted == offered:
        return 0.96, f"The expense category matches the {offered.replace('_', ' ')} coverage."

    expense_tokens = _tokens(wanted, expense.get("description"), expense.get("vendor"), expense.get("subject"))
    coverage_tokens = _tokens(offered, coverage.get("summary"), " ".join(coverage.get("coveredSubjects") or []))
    subject_tokens = _tokens(policy.get("policyType"), policy.get("coveredSubject"))
    overlap = expense_tokens.intersection(coverage_tokens | subject_tokens)
    if wanted and normalize_category(wanted) == normalize_category(policy.get("policyType")):
        return 0.86, f"The expense matches the policy type and its {offered.replace('_', ' ')} coverage."
    if overlap:
        named = ", ".join(sorted(overlap)[:3])
        return min(0.78, 0.60 + 0.06 * len(overlap)), f"The receipt and coverage share relevant details: {named}."
    return 0.0, ""


def _as_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if str(value or "").strip() else None
    except InvalidOperation:
        return None


def _claim_deadline(event_date: str, days: int) -> str:
    if not event_date or days <= 0:
        return ""
    try:
        return (date.fromisoformat(event_date) + timedelta(days=days)).isoformat()
    except ValueError:
        return ""


def match_expense_to_policy(policy: dict[str, Any], version: dict[str, Any], expense: dict[str, Any]) -> list[dict[str, Any]]:
    """Potential coverages in one applicable version, strongest first."""

    normalized_expense = normalize_expense(expense)
    expense_amount = _as_decimal(normalized_expense.get("amount"))
    expense_currency = normalized_expense.get("currency")
    matches: list[dict[str, Any]] = []
    for coverage in version.get("coverages") or []:
        if not isinstance(coverage, dict):
            continue
        score, reason = _category_score(normalized_expense, policy, coverage)
        if score <= 0:
            continue

        evidence = coverage.get("evidence") if isinstance(coverage.get("evidence"), dict) else {}
        evidence_present = bool(evidence.get("section") or evidence.get("pages") or evidence.get("quote"))
        source_backed = evidence_present and bool(version.get("sourceStored"))
        deductible = _as_decimal(coverage.get("deductibleAmount"))
        coverage_currency = clean_text(coverage.get("currency"), 3).upper()
        same_currency = not expense_currency or not coverage_currency or expense_currency == coverage_currency

        status = "likely_worth_claiming"
        notes: list[str] = []
        if expense_amount is not None and deductible is not None and same_currency and expense_amount <= deductible:
            status = "deductible_may_exceed_expense"
            notes.append("The receipt amount does not exceed the recorded deductible.")
        elif (
            not source_backed
            or clean_text(version.get("reviewStatus"), 20) != "reviewed"
            or not normalized_expense.get("date")
            or coverage.get("conditions")
            or coverage.get("exclusions")
        ):
            status = "possible_more_information_needed"
            if not source_backed:
                notes.append("This match comes from the saved summary; the original source and a supporting clause are not both attached yet.")
            if clean_text(version.get("reviewStatus"), 20) != "reviewed":
                notes.append("The structured policy interpretation has not been human-reviewed yet.")
            if not normalized_expense.get("date"):
                notes.append("The receipt date is missing, so the policy version in force on the event date still needs to be confirmed.")
            if coverage.get("conditions"):
                notes.append("The policy records conditions that still need to be checked against the event.")
            if coverage.get("exclusions"):
                notes.append("The policy records exclusions that still need to be checked; a receipt alone cannot settle them.")
        if expense_amount is None:
            notes.append("The receipt amount is not known.")

        deadline_days = int(coverage.get("claimDeadlineDays") or 0)
        deadline_estimate = _claim_deadline(normalized_expense.get("date"), deadline_days)
        if deadline_estimate:
            notes.append(
                "The filing-date estimate uses the receipt date as the event date; confirm the policy's actual trigger date."
            )
        match = {
            "status": status,
            "confidence": round(score, 2),
            "reason": reason,
            "notes": notes,
            "policyId": int(policy.get("id") or 0),
            "policyName": clean_text(policy.get("name"), 240),
            "insurer": clean_text(policy.get("insurer"), 240),
            "policyType": clean_text(policy.get("policyType"), 80),
            "coveredSubject": clean_text(policy.get("coveredSubject"), 240),
            "versionId": int(version.get("id") or 0),
            "versionNumber": int(version.get("versionNumber") or 0),
            "effectiveFrom": clean_text(version.get("effectiveFrom"), 10),
            "effectiveTo": clean_text(version.get("effectiveTo"), 10),
            "coverageCategory": clean_text(coverage.get("category"), 80),
            "coverageSummary": clean_text(coverage.get("summary"), 1000),
            "limitAmount": clean_text(coverage.get("limitAmount"), 40),
            "deductibleAmount": clean_text(coverage.get("deductibleAmount"), 40),
            "currency": coverage_currency,
            "conditions": list(coverage.get("conditions") or []),
            "exclusions": list(coverage.get("exclusions") or []),
            "evidence": evidence,
            "evidenceStatus": "source_backed" if source_backed else "summary_only",
            "claimDeadlineDays": deadline_days,
            "claimDeadlineEstimate": deadline_estimate,
            "claimDeadlineBasis": "receipt_date_assumed_event_date" if deadline_estimate else "",
            "sourceName": clean_text(version.get("sourceName"), 240),
            "sourceReference": clean_text(version.get("sourceReference"), 1000),
            "reviewStatus": clean_text(version.get("reviewStatus"), 20),
        }
        matches.append(match)
    return sorted(matches, key=lambda item: (-float(item["confidence"]), item["policyName"].casefold()))


def match_expense_to_policies(policies: list[dict[str, Any]], expense: dict[str, Any]) -> dict[str, Any]:
    """Find potential claims among policies that are active today."""

    normalized_expense = normalize_expense(expense)
    matches: list[dict[str, Any]] = []
    inactive_for_date: list[str] = []
    today = date.today().isoformat()
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        if clean_text(policy.get("status"), 20) != "active" or policy.get("archivedAt"):
            continue
        versions = [entry for entry in (policy.get("versions") or []) if isinstance(entry, dict)]
        # A forgotten status update must not leave a date-ended policy matching
        # receipts forever. Historical versions stay available only when the
        # policy itself still has a version in force today.
        if choose_applicable_version(versions, today) is None:
            continue
        selection_date = normalized_expense.get("date") or today
        version = choose_applicable_version(versions, selection_date)
        if version is None:
            inactive_for_date.append(clean_text(policy.get("name"), 240))
            continue
        matches.extend(match_expense_to_policy(policy, version, normalized_expense))

    matches.sort(key=lambda item: (-float(item["confidence"]), item["policyName"].casefold()))
    return {
        "expense": normalized_expense,
        "matches": matches,
        "matchCount": len(matches),
        "status": "potential_claims_found" if matches else "no_relevant_policy",
        "policiesOutsideExpenseDate": [name for name in inactive_for_date if name],
        "guidance": (
            "These are screening results, not coverage decisions. Read the cited policy wording and confirm "
            "the event facts, deductible, exclusions, notice deadline and insurer requirements before filing."
        ),
    }


__all__ = [
    "INSURANCE_MATCH_STATUSES",
    "INSURANCE_POLICY_STATUSES",
    "INSURANCE_REVIEW_STATUSES",
    "choose_applicable_version",
    "match_expense_to_policies",
    "match_expense_to_policy",
    "normalize_coverages",
    "normalize_expense",
    "normalize_policy_version",
    "version_applies_on",
]
