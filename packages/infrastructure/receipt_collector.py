"""Receipt collector export helpers for Gmail-backed batch actions."""

from __future__ import annotations

import html
import json
import re
import zipfile
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from email.utils import parseaddr
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from xml.sax.saxutils import escape as xml_escape

from packages.infrastructure import receipt_pdf_sources

RECEIPT_EXPORT_VERSION = 1
RECEIPT_EXCEL_FILENAME = "receipts.xlsx"
RECEIPT_PDF_FILENAME = "receipt-report.pdf"
RECEIPT_MANIFEST_FILENAME = "bundle.json"
# What a receipt row is called when the sender's name cannot be read.
UNKNOWN_VENDOR_LABEL = "Unknown vendor"
# Vendor slice colours, in fixed order, from the validated categorical palette.
RECEIPT_CHART_COLORS = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
)
RECEIPT_OTHER_COLOR = "#8b95a3"
RECEIPT_PREVIOUS_COLOR = "#9fb0c4"
RECEIPT_INK = "#172231"
RECEIPT_BODY_INK = "#4c5c70"
RECEIPT_MUTED_INK = "#5e6d80"
RECEIPT_CARD_BG = "#f5f8fb"
RECEIPT_RULE = "#d7dee7"
RECEIPT_VENDOR_LIMIT = 6
# Enough of the email body to read the receipt itself, not the footer below it.
RECEIPT_BODY_PREVIEW_CHARS = 900
MONTH_FOLDER_LABELS = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_BAD_PATH_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9 ._-]+")
_WHITESPACE_RE = re.compile(r"\s+")
_AMOUNT_NUMBER = r"\d[\d,]*(?:\.\d{1,2})?"
_CURRENCY_CODES = "USD|EUR|GBP|ILS|NIS"
_CURRENCY_SIGNS = "[$" + chr(8364) + chr(163) + chr(8362) + "]"
_CURRENCY_SIGN_CODES = {"$": "USD", chr(8364): "EUR", chr(163): "GBP", chr(8362): "ILS"}
_AMOUNT_PATTERNS = (
    re.compile(rf"(?P<currency>{_CURRENCY_CODES})\s*(?P<amount>{_AMOUNT_NUMBER})", re.IGNORECASE),
    re.compile(rf"(?P<amount>{_AMOUNT_NUMBER})\s*(?P<currency>{_CURRENCY_CODES})\b", re.IGNORECASE),
    re.compile(rf"(?P<currency>{_CURRENCY_SIGNS})\s*(?P<amount>{_AMOUNT_NUMBER})"),
    re.compile(rf"(?P<amount>{_AMOUNT_NUMBER})\s*(?P<currency>{_CURRENCY_SIGNS})"),
)


@dataclass(frozen=True)
class _AmountClaim:
    """One number in the text laying claim to one currency marker."""

    start: int
    end: int
    amount_span: tuple[int, int]
    currency_span: tuple[int, int]
    amount: str
    currency: str

    @property
    def marker_leads_amount(self) -> bool:
        return self.currency_span[0] < self.amount_span[0]

    @property
    def marker_touches_amount(self) -> bool:
        if self.marker_leads_amount:
            return self.currency_span[1] == self.amount_span[0]
        return self.amount_span[1] == self.currency_span[0]


# A receipt body quotes plenty of numbers - item prices, VAT, loyalty points.
# The one worth reporting is the one sitting next to a total label, so those
# labels are tried first and only then the first amount anywhere in the text.
_TOTAL_LABEL_PATTERNS = (
    re.compile(
        r"(grand total|order total|total charged|total paid|total due|total amount|"
        r"amount charged|amount paid|amount due|invoice total|you paid|you were charged)",
        re.IGNORECASE,
    ),
    re.compile(r"\btotals?\b", re.IGNORECASE),
)
_TOTAL_LABEL_WINDOW = 80
# The mailbox search is six broad words matched over the whole message, and
# Gmail's word search reaches inside attachments: a signed agreement whose PDF
# says "statement" or "expenses" comes back from a receipt search. Deciding
# what is actually a receipt therefore uses the email's own words only - the
# attachment text is never read here.
_RECEIPT_EVIDENCE_RE = re.compile(
    "|".join((
        r"\breceipts?\b",
        r"\binvoiced?\b",
        r"\binvoices\b",
        r"\bpaid\b",
        r"\bpayments?\b",
        r"\bcharged\b",
        r"\brefunds?\b",
        r"\bsubtotal\b",
        r"\bcheckout\b",
        r"\bpurchased?\b",
        r"\bbilled\b",
        r"\bbilling\b",
        r"\byour order\b",
        r"\border (?:total|confirmation|number|summary)\b",
        r"\btransaction (?:id|details|receipt)\b",
        r"\bsubscription (?:payment|renewal|renewed)\b",
        "\u05e7\u05d1\u05dc\u05d4",
        "\u05d7\u05e9\u05d1\u05d5\u05e0\u05d9\u05ea",
        "\u05ea\u05e9\u05dc\u05d5\u05dd",
    )),
    re.IGNORECASE,
)
RECEIPT_STATUS_READY = "Ready"
RECEIPT_STATUS_REVIEW = "Needs review"
RECEIPT_STATUS_NOT_A_RECEIPT = "Not a receipt"


def format_receipt_folder_month(year: int, month: int) -> str:
    """Return the compact month label used in receipt folders."""

    safe_month = max(1, min(12, int(month or 1)))
    return f"{MONTH_FOLDER_LABELS[safe_month]}{int(year):04d}"


def normalize_receipt_output_folder(
    value: Any = "",
    *,
    month_value: tuple[int, int] | None = None,
) -> str:
    """Normalize a logical receipt folder while preventing path traversal."""

    month_label = format_receipt_folder_month(*month_value) if month_value else ""
    raw = str(value or "").strip()
    if not raw:
        raw = f"Receipts/{month_label or 'Unsorted'}"
    if month_label:
        for token in ("{RunMonth}", "{runMonth}", "{{RunMonth}}", "{{run_month}}", "<RunMonth>", "RunMonth"):
            raw = raw.replace(token, month_label)
    raw = raw.replace("\\", "/")

    safe_segments = _safe_folder_segments(raw)
    if not safe_segments:
        safe_segments = ["Receipts", month_label or "Unsorted"]
    return "/".join(safe_segments) + "/"


def create_receipt_bundle(
    items: list[dict[str, Any]],
    *,
    output_root: Path,
    owner_key: str,
    output_folder: Any = "",
    month_value: tuple[int, int] | None = None,
    query: str = "",
    created_at: datetime | None = None,
    url_prefix: str = "/output/agent_receipts",
) -> dict[str, Any]:
    """Write Excel and PDF receipt exports, returning artifact metadata."""

    created = created_at or datetime.now(timezone.utc)
    logical_folder = normalize_receipt_output_folder(output_folder, month_value=month_value)
    safe_owner_key = _safe_owner_key(owner_key)
    folder_path = resolve_receipt_bundle_folder(
        output_root,
        owner_key=safe_owner_key,
        output_folder=logical_folder,
        month_value=None,
    )
    folder_path.mkdir(parents=True, exist_ok=True)

    rows, skipped_rows = split_receipt_rows(extract_receipt_rows(items))
    metadata = {
        "createdAt": created.isoformat(),
        "outputFolder": logical_folder,
        "monthLabel": format_receipt_month_label(month_value) if month_value else "",
        "query": str(query or "").strip(),
        "receiptCount": len(rows),
        "reviewCount": sum(1 for row in rows if row["status"] != RECEIPT_STATUS_READY),
        "skippedCount": len(skipped_rows),
        # Named rather than counted, so a receipt wrongly left out is visible.
        "skipped": [
            {
                "vendor": row["vendor"],
                "subject": row["subject"],
                "source": row["source"],
                "date": row["date"],
            }
            for row in skipped_rows
        ],
        "summary": summarize_receipt_rows(rows),
        "exportVersion": RECEIPT_EXPORT_VERSION,
    }
    previous = load_previous_receipt_summary(
        output_root,
        owner_key=safe_owner_key,
        output_folder=logical_folder,
        month_value=month_value,
    )
    if previous:
        metadata["previous"] = previous

    excel_path = folder_path / RECEIPT_EXCEL_FILENAME
    pdf_path = folder_path / RECEIPT_PDF_FILENAME
    manifest_path = folder_path / RECEIPT_MANIFEST_FILENAME
    write_receipts_xlsx(excel_path, rows, metadata)
    write_receipts_pdf(pdf_path, rows, metadata)
    manifest_path.write_text(
        json.dumps({"metadata": metadata, "receipts": rows, "skipped": skipped_rows}, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    base_url = build_receipt_bundle_base_url(
        owner_key=safe_owner_key,
        output_folder=logical_folder,
        month_value=None,
        url_prefix=url_prefix,
    )
    return {
        "outputFolder": logical_folder,
        "folderPath": str(folder_path),
        "receiptCount": len(rows),
        "reviewCount": metadata["reviewCount"],
        "skippedCount": len(skipped_rows),
        "artifacts": {
            "excel": {
                "name": RECEIPT_EXCEL_FILENAME,
                "path": str(excel_path),
                "url": f"{base_url}/{RECEIPT_EXCEL_FILENAME}",
            },
            "pdf": {
                "name": RECEIPT_PDF_FILENAME,
                "path": str(pdf_path),
                "url": f"{base_url}/{RECEIPT_PDF_FILENAME}",
            },
            "manifest": {
                "name": RECEIPT_MANIFEST_FILENAME,
                "path": str(manifest_path),
                "url": f"{base_url}/{RECEIPT_MANIFEST_FILENAME}",
            },
        },
    }


def resolve_receipt_bundle_folder(
    output_root: Path,
    *,
    owner_key: str,
    output_folder: Any = "",
    month_value: tuple[int, int] | None = None,
) -> Path:
    logical_folder = normalize_receipt_output_folder(output_folder, month_value=month_value)
    folder_path = Path(output_root) / _safe_owner_key(owner_key)
    for segment in _safe_folder_segments(logical_folder):
        folder_path /= segment
    return folder_path


def build_receipt_bundle_base_url(
    *,
    owner_key: str,
    output_folder: Any = "",
    month_value: tuple[int, int] | None = None,
    url_prefix: str = "/output/agent_receipts",
) -> str:
    logical_folder = normalize_receipt_output_folder(output_folder, month_value=month_value)
    return "/".join([
        str(url_prefix or "/output/agent_receipts").rstrip("/"),
        urllib_parse.quote(_safe_owner_key(owner_key)),
        *_quote_url_segments(logical_folder),
    ])


def format_receipt_month_label(month_value: tuple[int, int] | None) -> str:
    """Return the readable month label used on the summary page."""

    if not month_value:
        return ""
    year, month = int(month_value[0]), int(month_value[1])
    safe_month = max(1, min(12, month))
    return f"{MONTH_FOLDER_LABELS[safe_month]} {year:04d}"


def summarize_receipt_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll receipt rows up into the totals the summary page charts."""

    vendor_spend: dict[str, dict[str, dict[str, float]]] = {}
    vendor_counts: Counter[str] = Counter()
    missing_amounts = 0
    for row in rows:
        vendor = _clean_text(row.get("vendor")) or UNKNOWN_VENDOR_LABEL
        vendor_counts[vendor] += 1
        currency = _clean_text(row.get("currency"))
        try:
            amount = float(_clean_text(row.get("amount")).replace(",", ""))
        except ValueError:
            amount = None
        if not currency or amount is None:
            missing_amounts += 1
            continue
        bucket = vendor_spend.setdefault(currency, {}).setdefault(vendor, {"amount": 0.0, "count": 0})
        bucket["amount"] += amount
        bucket["count"] += 1
    return {
        "receiptCount": len(rows),
        "totals": _currency_totals(rows),
        "vendorSpend": vendor_spend,
        "vendorCounts": dict(vendor_counts.most_common()),
        "missingAmountCount": missing_amounts,
    }


def filter_receipt_rows_by_vendor(rows: list[dict[str, Any]], vendor: Any) -> list[dict[str, Any]]:
    """Keep the receipts that belong to one named vendor.

    The mailbox search casts a wide net on purpose, so narrowing to the vendor
    the question actually named happens here rather than in the query.
    """

    needle = _clean_text(vendor).lower()
    if not needle:
        return list(rows)
    return [
        row for row in rows
        if needle in " ".join([
            _clean_text(row.get("vendor")),
            _clean_text(row.get("subject")),
            _clean_text(row.get("source")),
        ]).lower()
    ]


def answer_receipt_question(
    items: list[dict[str, Any]],
    *,
    vendor: Any = "",
    month_label: str = "",
) -> dict[str, Any]:
    """Answer a one-off spending question, writing no files.

    A question asked in chat wants a sentence back, not an export bundle, so
    the rows are summed in memory and nothing is saved anywhere.
    """

    receipts, _ = split_receipt_rows(extract_receipt_rows(items))
    matched = filter_receipt_rows_by_vendor(receipts, vendor)
    summary = summarize_receipt_rows(matched)
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}

    vendor_label = _clean_text(vendor)
    where = f" to {vendor_label}" if vendor_label else ""
    when = f" in {month_label}" if month_label else ""
    count = len(matched)
    receipt_word = "receipt" if count == 1 else "receipts"

    if not count:
        answer = f"I couldn't find any receipts{where}{when}."
    elif not totals:
        answer = (
            f"I found {count} {receipt_word}{where}{when}, but none of them named an amount I could read."
        )
    else:
        amounts = " and ".join(f"{value:,.2f} {code}" for code, value in totals.items())
        answer = f"You paid {amounts}{where}{when}, across {count} {receipt_word}."
        missing = int(summary.get("missingAmountCount") or 0)
        if missing:
            missing_word = "receipt" if missing == 1 else "receipts"
            answer += f" Another {missing} {missing_word} named no amount I could read."

    return {
        "answer": answer,
        "receiptCount": count,
        "totals": totals,
        "vendor": vendor_label,
        "monthLabel": month_label,
        "missingAmountCount": int(summary.get("missingAmountCount") or 0),
        # The emails the total was read from. An answer run writes no files,
        # so keeping the answer afterwards has to be able to go back for the
        # receipts themselves, and these say which messages those are.
        "sources": describe_receipt_sources(matched),
    }


def describe_receipt_sources(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Name the messages behind a set of receipt rows."""

    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        message_id = _clean_text(row.get("sourceRef"))
        mailbox = _clean_text(row.get("mailbox"))
        if not message_id or (message_id, mailbox) in seen:
            continue
        seen.add((message_id, mailbox))
        vendor = _clean_text(row.get("vendor"))
        sources.append({
            "messageId": message_id,
            "mailbox": mailbox,
            # A row with no readable sender is named "Unknown vendor" for the
            # report's sake, which is not a name to put on a saved file.
            "vendor": "" if vendor == UNKNOWN_VENDOR_LABEL else vendor,
            "subject": _clean_text(row.get("subject")),
            "date": _clean_text(row.get("date")),
        })
    return sources


def load_previous_receipt_summary(
    output_root: Path,
    *,
    owner_key: str,
    output_folder: Any,
    month_value: tuple[int, int] | None,
) -> dict[str, Any] | None:
    """Read last month's bundle so the report can compare the two months."""

    if not month_value:
        return None
    current_label = format_receipt_folder_month(*month_value)
    previous_value = _previous_month_value(month_value)
    previous_label = format_receipt_folder_month(*previous_value)
    segments = _safe_folder_segments(normalize_receipt_output_folder(output_folder, month_value=month_value))
    if current_label not in segments:
        # Every run writes into the same folder, so there is no earlier month to read.
        return None
    previous_segments = [previous_label if segment == current_label else segment for segment in segments]
    manifest_path = Path(output_root) / _safe_owner_key(owner_key)
    for segment in previous_segments:
        manifest_path /= segment
    manifest_path /= RECEIPT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    previous_rows = payload.get("receipts") if isinstance(payload, dict) else None
    if not isinstance(previous_rows, list) or not previous_rows:
        return None
    summary = summarize_receipt_rows([row for row in previous_rows if isinstance(row, dict)])
    summary["monthLabel"] = format_receipt_month_label(previous_value)
    summary["outputFolder"] = "/".join(previous_segments) + "/"
    return summary


def build_receipt_spend_view(
    summary: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    limit: int = RECEIPT_VENDOR_LIMIT,
) -> dict[str, Any]:
    """Rank vendors by spend in the busiest currency, with last month alongside."""

    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    previous_totals = (previous or {}).get("totals")
    previous_totals = previous_totals if isinstance(previous_totals, dict) else {}
    currency = _busiest_currency(totals) or _busiest_currency(previous_totals)
    spend = _vendor_spend_for(summary, currency)
    previous_spend = _vendor_spend_for(previous or {}, currency)
    counts = summary.get("vendorCounts") if isinstance(summary.get("vendorCounts"), dict) else {}

    names = set(counts) | set(spend) | set(previous_spend)
    ranked = sorted(
        names,
        key=lambda name: (
            -spend.get(name, (0.0, 0))[0],
            -previous_spend.get(name, (0.0, 0))[0],
            -int(counts.get(name) or 0),
            name.lower(),
        ),
    )
    total = float(totals.get(currency) or 0.0)
    previous_total = float(previous_totals.get(currency) or 0.0)

    entries: list[dict[str, Any]] = []
    for index, name in enumerate(ranked[:limit]):
        amount = spend.get(name, (0.0, 0))[0]
        entries.append({
            "vendor": name,
            "amount": amount,
            "count": int(counts.get(name) or spend.get(name, (0.0, 0))[1]),
            "previous": previous_spend.get(name, (0.0, 0))[0],
            "share": (amount / total * 100) if total else 0.0,
            "color": RECEIPT_CHART_COLORS[index % len(RECEIPT_CHART_COLORS)],
        })
    remainder = ranked[limit:]
    if remainder:
        amount = sum(spend.get(name, (0.0, 0))[0] for name in remainder)
        entries.append({
            "vendor": f"Other ({len(remainder)} vendor{'s' if len(remainder) > 1 else ''})",
            "amount": amount,
            "count": sum(int(counts.get(name) or 0) for name in remainder),
            "previous": sum(previous_spend.get(name, (0.0, 0))[0] for name in remainder),
            "share": (amount / total * 100) if total else 0.0,
            "color": RECEIPT_OTHER_COLOR,
        })
    return {
        "currency": currency,
        "total": total,
        "previousTotal": previous_total,
        "entries": entries,
        "otherCurrencies": {code: value for code, value in totals.items() if code != currency},
    }


def _previous_month_value(month_value: tuple[int, int]) -> tuple[int, int]:
    year, month = int(month_value[0]), int(month_value[1])
    if month <= 1:
        return (year - 1, 12)
    return (year, month - 1)


def _busiest_currency(totals: dict[str, Any]) -> str:
    if not totals:
        return ""
    return max(totals.items(), key=lambda item: float(item[1] or 0.0))[0]


def _vendor_spend_for(summary: dict[str, Any], currency: str) -> dict[str, tuple[float, int]]:
    spend = summary.get("vendorSpend") if isinstance(summary.get("vendorSpend"), dict) else {}
    bucket = spend.get(currency) if isinstance(spend.get(currency), dict) else {}
    result: dict[str, tuple[float, int]] = {}
    for vendor, values in bucket.items():
        if not isinstance(values, dict):
            continue
        try:
            result[str(vendor)] = (float(values.get("amount") or 0.0), int(values.get("count") or 0))
        except (TypeError, ValueError):
            continue
    return result


def extract_receipt_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items or [], start=1):
        source = item if isinstance(item, dict) else {}
        subject = _clean_text(source.get("subject")) or "(no subject)"
        # Both providers hand the preview back HTML-escaped, so an address
        # like "Ra&#39;anana" has to be unescaped before it is shown.
        snippet = _clean_text(html.unescape(str(source.get("snippet") or "")))
        sender = _clean_text(source.get("from"))
        vendor = _extract_vendor(sender)
        body_text = _clean_text(source.get("bodyText"))
        # The subject and the preview rarely carry the total; the body does.
        own_text = " ".join(part for part in (subject, snippet, body_text) if part)
        amount, currency = _extract_amount(own_text)
        date = _clean_text(source.get("date"))
        source_ref = _clean_text(source.get("id") or source.get("threadId"))
        # The preview is one clipped line; the body is what the receipt says.
        body_preview = _short_text(body_text, RECEIPT_BODY_PREVIEW_CHARS) if len(body_text) > len(snippet) else snippet
        # A message the search returned still has to look like a receipt in
        # its own right before it is counted as one.
        if not (amount or _RECEIPT_EVIDENCE_RE.search(own_text)):
            status = RECEIPT_STATUS_NOT_A_RECEIPT
        elif vendor and amount:
            status = RECEIPT_STATUS_READY
        else:
            status = RECEIPT_STATUS_REVIEW
        attachments = _extract_receipt_attachments(source)
        image_attachments = [
            attachment
            for attachment in attachments
            if attachment.get("status") == "saved" and _is_image_attachment(attachment)
        ]
        saved_count = sum(1 for attachment in attachments if attachment.get("status") == "saved")
        notes = "Source email recorded. No receipt image attachment was available."
        if image_attachments:
            notes = f"{len(image_attachments)} receipt image(s) saved."
        elif saved_count:
            notes = f"{saved_count} receipt attachment(s) saved."
        if not amount:
            notes = "No amount detected. Review the source email or attachment."
        if status == RECEIPT_STATUS_NOT_A_RECEIPT:
            notes = (
                "The mailbox search matched this message, but the email itself names no "
                "amount and reads nothing like a receipt. Left out of the totals."
            )
        rows.append({
            "index": str(index),
            "date": date,
            "vendor": vendor or UNKNOWN_VENDOR_LABEL,
            "subject": subject,
            # Which mailbox this arrived in, so a receipt can still be fetched
            # again later from the account that holds it.
            "mailbox": _clean_text(source.get("mailbox")),
            "amount": amount,
            "currency": currency,
            "source": sender or "Gmail",
            "sourceRef": source_ref,
            "status": status,
            "notes": notes,
            "snippet": snippet,
            "bodyPreview": body_preview,
            "attachmentCount": str(len(attachments)),
            "attachments": attachments,
            "imageAttachments": image_attachments,
        })
    return rows


def split_receipt_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate the real receipts from what the search net dragged in.

    Both lists are renumbered from 1, so "Receipt 3" in the report means the
    third receipt rather than the third search hit.
    """

    receipts = [row for row in rows if row.get("status") != RECEIPT_STATUS_NOT_A_RECEIPT]
    skipped = [row for row in rows if row.get("status") == RECEIPT_STATUS_NOT_A_RECEIPT]
    for position, row in enumerate(receipts, start=1):
        row["index"] = str(position)
    for position, row in enumerate(skipped, start=1):
        row["index"] = str(position)
    return receipts, skipped


def write_receipts_xlsx(path: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    receipt_headers = ["#", "Date", "Vendor", "Subject", "Amount", "Currency", "Status", "Source", "Source ref", "Attachments", "Notes"]
    receipt_values = [
        [
            row["index"],
            row["date"],
            row["vendor"],
            row["subject"],
            row["amount"],
            row["currency"],
            row["status"],
            row["source"],
            row["sourceRef"],
            _format_attachment_list(row),
            row["notes"],
        ]
        for row in rows
    ]
    summary_values = [
        ["Generated at", str(metadata.get("createdAt") or "")],
        ["Output folder", str(metadata.get("outputFolder") or "")],
        ["Search query", str(metadata.get("query") or "")],
        ["Candidate receipts", str(metadata.get("receiptCount") or 0)],
        ["Needs review", str(metadata.get("reviewCount") or 0)],
        ["Not counted as receipts", str(metadata.get("skippedCount") or 0)],
    ]
    for currency, total in _currency_totals(rows).items():
        summary_values.append([f"Total {currency}", f"{total:.2f}"])

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _xlsx_content_types())
        archive.writestr("_rels/.rels", _xlsx_root_relationships())
        archive.writestr("xl/workbook.xml", _xlsx_workbook())
        archive.writestr("xl/_rels/workbook.xml.rels", _xlsx_workbook_relationships())
        archive.writestr("xl/styles.xml", _xlsx_styles())
        archive.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet([receipt_headers, *receipt_values], widths=[6, 24, 22, 44, 14, 12, 16, 30, 22, 34, 42]))
        archive.writestr("xl/worksheets/sheet2.xml", _xlsx_sheet([["Metric", "Value"], *summary_values], widths=[24, 70]))


def write_receipts_pdf(path: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Flowable
        from reportlab.platypus import Image as ReportImage
        from reportlab.platypus import PageBreak
        from reportlab.platypus import Paragraph
        from reportlab.platypus import SimpleDocTemplate
        from reportlab.platypus import Spacer
        from reportlab.platypus import Table
        from reportlab.platypus import TableStyle
    except ModuleNotFoundError:
        _write_basic_receipts_pdf(path, rows, metadata)
        return

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReceiptTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        spaceAfter=10,
        textColor=colors.HexColor("#172231"),
    )
    heading_style = ParagraphStyle(
        "ReceiptHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        spaceBefore=8,
        spaceAfter=8,
        textColor=colors.HexColor("#172231"),
    )
    body_style = ParagraphStyle(
        "ReceiptBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4c5c70"),
    )
    small_style = ParagraphStyle(
        "ReceiptSmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#5e6d80"),
    )

    cell_style = ParagraphStyle(
        "ReceiptCell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        spaceBefore=0,
        spaceAfter=0,
        textColor=colors.HexColor("#2c3a4b"),
    )
    cell_center_style = ParagraphStyle("ReceiptCellCenter", parent=cell_style, alignment=1)
    cell_right_style = ParagraphStyle("ReceiptCellRight", parent=cell_style, alignment=2)
    header_cell_style = ParagraphStyle(
        "ReceiptHeaderCell",
        parent=cell_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    header_center_style = ParagraphStyle("ReceiptHeaderCenter", parent=header_cell_style, alignment=1)
    header_right_style = ParagraphStyle("ReceiptHeaderRight", parent=header_cell_style, alignment=2)

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Receipt report",
    )
    story: list[Any] = []
    story.append(Paragraph("Receipt report", title_style))
    story.append(Paragraph(_pdf_escape(f"Folder: {metadata.get('outputFolder') or ''}"), body_style))
    story.append(Paragraph(_pdf_escape(f"Generated: {_format_generated_at(metadata.get('createdAt'))}"), small_style))
    story.append(Spacer(1, 8))

    # Every cell is a Paragraph so long vendors and sender addresses wrap inside
    # their column instead of running across the one beside it.
    table_rows: list[list[Any]] = [[
        Paragraph("#", header_center_style),
        Paragraph("Date", header_cell_style),
        Paragraph("Vendor", header_cell_style),
        Paragraph("Amount", header_right_style),
        Paragraph("Status", header_cell_style),
        Paragraph("Source", header_cell_style),
    ]]
    for row in rows:
        table_rows.append([
            Paragraph(_pdf_escape(row["index"]), cell_center_style),
            Paragraph(_pdf_escape(_format_receipt_date(row["date"])), cell_style),
            Paragraph(_pdf_escape(row["vendor"]), cell_style),
            Paragraph(_pdf_escape(_format_amount(row) or "Not found"), cell_right_style),
            Paragraph(_pdf_escape(row["status"]), cell_style),
            Paragraph(_pdf_escape(row["source"]), cell_style),
        ])
    empty_state = len(table_rows) == 1
    if empty_state:
        table_rows.append([Paragraph("No candidate receipts found.", cell_style)] + [""] * 5)
    # The widths add up to the 182mm between the page margins, so nothing is
    # pushed off the right edge.
    table = Table(
        table_rows,
        colWidths=[8 * mm, 30 * mm, 34 * mm, 22 * mm, 22 * mm, 66 * mm],
        repeatRows=1,
    )
    table.setStyle(_receipt_table_style(colors, TableStyle))
    if empty_state:
        # The message reads across the whole table rather than down the "#" column.
        table.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1))]))
    story.append(table)
    story.extend(_skipped_story(metadata, Paragraph, Spacer, heading_style, small_style))

    story.append(PageBreak())
    story.extend(_receipt_summary_story(rows, metadata, {
        "title": title_style,
        "heading": heading_style,
        "body": body_style,
        "small": small_style,
    }))

    # Where each receipt section landed, so the sender's own pages can be
    # merged in behind it once the layout is settled.
    page_marks: dict[str, int] = {}
    source_pdfs = {row["index"]: receipt_pdf_sources.collect_source_pdfs(row) for row in rows}
    page_mark_cls = _page_mark_flowable(Flowable)

    for row in rows:
        story.append(PageBreak())
        story.append(page_mark_cls(page_marks, row["index"]))
        story.append(Paragraph(_pdf_escape(f"Receipt {row['index']}: {row['vendor']}"), title_style))
        story.append(Paragraph(_pdf_escape(row["subject"]), heading_style))
        details = [
            ("Date", _format_receipt_date(row["date"])),
            ("Amount", _format_amount(row)),
            ("Status", row["status"]),
            ("Source", row["source"]),
            ("Source ref", row["sourceRef"]),
        ]
        for label, value in details:
            story.append(Paragraph(_pdf_escape(f"{label}: {value or 'Not available'}"), body_style))
        story.append(Spacer(1, 10))
        story.append(Paragraph("From the email", heading_style))
        story.append(Paragraph(
            _pdf_escape(row.get("bodyPreview") or row["snippet"] or "No email text was available."),
            body_style,
        ))
        story.append(Spacer(1, 12))
        image_attachments = row.get("imageAttachments") if isinstance(row.get("imageAttachments"), list) else []
        if image_attachments:
            story.append(Paragraph("Receipt image", heading_style))
            for attachment in image_attachments:
                image_path = Path(str(attachment.get("path") or ""))
                image = _build_reportlab_image(
                    image_path,
                    image_reader_cls=ImageReader,
                    image_cls=ReportImage,
                    max_width=170 * mm,
                    max_height=190 * mm,
                )
                if image is None:
                    story.append(Paragraph(_pdf_escape(f"Saved image: {attachment.get('filename') or image_path.name}"), small_style))
                    continue
                story.append(image)
                story.append(Spacer(1, 8))
        sources = source_pdfs.get(row["index"]) or []
        if sources:
            story.append(Paragraph("Receipt from the sender", heading_style))
            story.append(Paragraph(
                _pdf_escape(
                    "The sender's own receipt follows on the next page(s): "
                    + ", ".join(receipt_pdf_sources.describe_source_pdf(source) for source in sources)
                ),
                small_style,
            ))
        if not image_attachments and not sources:
            attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
            attachment_note = _format_attachment_list(row)
            if attachments and attachment_note:
                story.append(Paragraph(_pdf_escape(f"Saved attachment(s): {attachment_note}"), small_style))
            else:
                story.append(Paragraph("The sender attached no receipt file. The email above is the record.", small_style))

    document.build(story)
    receipt_pdf_sources.merge_source_pdfs(
        path,
        _source_pdf_insertions(rows, source_pdfs, page_marks, getattr(document, "page", 0)),
    )


def _receipt_summary_story(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    styles: dict[str, Any],
) -> list[Any]:
    """Build the spending summary page: headline cards, a vendor pie and last month."""

    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph
    from reportlab.platypus import Spacer
    from reportlab.platypus import Table
    from reportlab.platypus import TableStyle

    summary = metadata.get("summary")
    summary = summary if isinstance(summary, dict) else summarize_receipt_rows(rows)
    previous = metadata.get("previous")
    previous = previous if isinstance(previous, dict) else None
    view = build_receipt_spend_view(summary, previous)

    currency = view["currency"]
    total = float(view["total"])
    previous_total = float(view["previousTotal"])
    entries = view["entries"]
    month_label = _clean_text(metadata.get("monthLabel")) or "This month"
    previous_label = _clean_text((previous or {}).get("monthLabel"))
    receipt_count = int(metadata.get("receiptCount") or summary.get("receiptCount") or 0)
    review_count = int(metadata.get("reviewCount") or 0)
    vendor_count = len(summary.get("vendorCounts") or {})
    missing_amounts = int(summary.get("missingAmountCount") or 0)

    page_title_style = ParagraphStyle(
        "ReceiptSummaryTitle",
        parent=styles["title"],
        fontSize=18,
        leading=22,
        spaceAfter=6,
    )
    story: list[Any] = [Paragraph("Where the money went", page_title_style)]
    subtitle = f"{month_label}, compared with {previous_label}" if previous_label else month_label
    story.append(Paragraph(_pdf_escape(subtitle), styles["small"]))
    story.append(Spacer(1, 10))

    # Four headline numbers, each on its own card.
    if currency and total:
        spend_value = f"{currency} {total:,.2f}"
    elif receipt_count:
        spend_value = "Not detected"
    else:
        spend_value = "None"
    cards = [
        (spend_value, "Total paid", _spend_delta_note(total, previous_total, currency, previous_label)),
        (str(receipt_count), "Receipts found", _count_delta_note(receipt_count, previous, previous_label)),
        (str(vendor_count), "Vendors paid", ""),
        (str(review_count), "Need review", "" if not missing_amounts else f"{missing_amounts} without an amount"),
    ]
    note_style = ParagraphStyle(
        "ReceiptCardNote",
        parent=styles["small"],
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor(RECEIPT_MUTED_INK),
    )
    card_rows = [
        [card[0] for card in cards],
        [card[1] for card in cards],
        [Paragraph(_pdf_escape(card[2]), note_style) if card[2] else "" for card in cards],
    ]
    card_table = Table(card_rows, colWidths=[45.5 * mm] * 4, hAlign="LEFT")
    card_style = [
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(RECEIPT_CARD_BG)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 15),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(RECEIPT_INK)),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, 1), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor(RECEIPT_BODY_INK)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 8),
        ("LINEABOVE", (0, 0), (-1, 0), 1.4, colors.HexColor(RECEIPT_CHART_COLORS[0])),
        # A white gutter between the cards keeps them reading as four tiles.
        ("LINEAFTER", (0, 0), (-2, -1), 4, colors.white),
    ]
    card_table.setStyle(TableStyle(card_style))
    story.append(card_table)
    story.append(Spacer(1, 10))

    # Who we paid, as a share of the month.
    money_label = f" ({currency})" if currency else ""
    pie_entries = [entry for entry in entries if float(entry["amount"]) > 0]
    if pie_entries and total > 0:
        story.append(Paragraph(_pdf_escape(f"Who we paid{money_label}"), styles["heading"]))
        drawing = Drawing(172, 120)
        pie = Pie()
        pie.x = 8
        pie.y = 6
        pie.width = 110
        pie.height = 110
        pie.data = [float(entry["amount"]) for entry in pie_entries]
        pie.slices.strokeColor = colors.white
        pie.slices.strokeWidth = 1.5
        for index, entry in enumerate(pie_entries):
            pie.slices[index].fillColor = colors.HexColor(entry["color"])
        drawing.add(pie)

        legend_rows = [["", "Vendor", "Paid", "Share"]]
        for entry in pie_entries:
            legend_rows.append([
                "",
                _short_text(entry["vendor"], 26),
                f"{float(entry['amount']):,.2f}",
                f"{float(entry['share']):.0f}%",
            ])
        legend = Table(legend_rows, colWidths=[5 * mm, 46 * mm, 26 * mm, 16 * mm], hAlign="LEFT")
        legend_style = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(RECEIPT_MUTED_INK)),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(RECEIPT_INK)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(RECEIPT_RULE)),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 6),
        ]
        for index, entry in enumerate(pie_entries, start=1):
            legend_style.append(("BACKGROUND", (0, index), (0, index), colors.HexColor(entry["color"])))
        legend.setStyle(TableStyle(legend_style))

        pie_block = Table([[drawing, legend]], colWidths=[62 * mm, 120 * mm], hAlign="LEFT")
        pie_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(pie_block)
    elif receipt_count:
        story.append(Paragraph("Who we paid", styles["heading"]))
        story.append(Paragraph(
            "No amounts were detected in this month's receipts, so there is nothing to chart yet. "
            "The vendor list below shows what was found.",
            styles["body"],
        ))
        story.append(Spacer(1, 6))
    else:
        story.append(Paragraph("Who we paid", styles["heading"]))
        story.append(Paragraph("No receipts were found for this month.", styles["body"]))

    # The same numbers as a table, so nothing rests on colour alone.
    if entries:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Vendor breakdown", styles["heading"]))
    if previous_label:
        breakdown_rows = [[
            "Vendor",
            "Receipts",
            f"{month_label}{money_label}",
            "Share",
            f"{previous_label}{money_label}",
            "Change",
        ]]
        breakdown_widths = [54 * mm, 20 * mm, 32 * mm, 16 * mm, 32 * mm, 28 * mm]
    else:
        breakdown_rows = [["Vendor", "Receipts", f"Paid{money_label}", "Share"]]
        breakdown_widths = [74 * mm, 26 * mm, 46 * mm, 36 * mm]
    for entry in entries:
        amount = float(entry["amount"])
        row = [
            _short_text(entry["vendor"], 34),
            str(entry["count"]) if entry["count"] else "-",
            f"{amount:,.2f}" if amount else "-",
            f"{float(entry['share']):.0f}%" if amount else "-",
        ]
        if previous_label:
            previous_amount = float(entry["previous"])
            row.append(f"{previous_amount:,.2f}" if previous_amount else "-")
            row.append(_delta_label(amount, previous_amount))
        breakdown_rows.append(row)
    breakdown = Table(breakdown_rows, colWidths=breakdown_widths, hAlign="LEFT", repeatRows=1)
    breakdown.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(RECEIPT_INK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(RECEIPT_INK)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(RECEIPT_CARD_BG)]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(RECEIPT_RULE)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    if entries:
        story.append(breakdown)

    # Side by side with last month, so a rise or a drop is obvious per vendor.
    chart_entries = [
        entry for entry in entries
        if float(entry["amount"]) > 0 or float(entry["previous"]) > 0
    ][:4]
    if previous_label and chart_entries:
        story.append(Spacer(1, 10))
        story.append(Paragraph(_pdf_escape(f"{month_label} against {previous_label}"), styles["heading"]))
        story.append(Paragraph(_pdf_escape(_spend_headline(total, previous_total, currency, month_label, previous_label)), styles["body"]))
        story.append(Spacer(1, 6))
        ordered = list(reversed(chart_entries))
        bar_height = 21 * len(ordered)
        drawing = Drawing(500, bar_height + 34)
        chart = HorizontalBarChart()
        chart.x = 108
        chart.y = 24
        chart.width = 356
        chart.height = bar_height
        chart.data = [
            [float(entry["previous"]) for entry in ordered],
            [float(entry["amount"]) for entry in ordered],
        ]
        chart.categoryAxis.categoryNames = [_short_text(entry["vendor"], 20) for entry in ordered]
        chart.categoryAxis.labels.fontName = "Helvetica"
        chart.categoryAxis.labels.fontSize = 8
        chart.categoryAxis.labels.fillColor = colors.HexColor(RECEIPT_INK)
        chart.categoryAxis.strokeColor = colors.HexColor(RECEIPT_RULE)
        chart.valueAxis.valueMin = 0
        chart.valueAxis.labels.fontName = "Helvetica"
        chart.valueAxis.labels.fontSize = 7
        chart.valueAxis.labels.fillColor = colors.HexColor(RECEIPT_MUTED_INK)
        chart.valueAxis.strokeColor = colors.HexColor(RECEIPT_RULE)
        chart.valueAxis.gridStrokeColor = colors.HexColor(RECEIPT_RULE)
        chart.valueAxis.gridStrokeWidth = 0.3
        chart.valueAxis.visibleGrid = 1
        chart.groupSpacing = 7
        chart.barSpacing = 1
        chart.bars.strokeWidth = 0
        chart.bars.strokeColor = None
        chart.bars[0].fillColor = colors.HexColor(RECEIPT_PREVIOUS_COLOR)
        chart.bars[1].fillColor = colors.HexColor(RECEIPT_CHART_COLORS[0])
        chart.barLabelFormat = _bar_label
        chart.barLabels.fontName = "Helvetica"
        chart.barLabels.fontSize = 7
        chart.barLabels.fillColor = colors.HexColor(RECEIPT_MUTED_INK)
        chart.barLabels.boxAnchor = "w"
        chart.barLabels.dx = 4
        drawing.add(chart)
        story.append(drawing)

        legend = Table(
            [["", month_label, "", previous_label]],
            colWidths=[5 * mm, 28 * mm, 5 * mm, 28 * mm],
            hAlign="LEFT",
        )
        legend.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(RECEIPT_CHART_COLORS[0])),
            ("BACKGROUND", (2, 0), (2, 0), colors.HexColor(RECEIPT_PREVIOUS_COLOR)),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(RECEIPT_BODY_INK)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (2, 0), (2, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 5),
            ("RIGHTPADDING", (2, 0), (2, 0), 5),
        ]))
        story.append(legend)

    notes = []
    if missing_amounts:
        notes.append(f"{missing_amounts} receipt(s) had no amount we could read. Open them in the pages that follow.")
    other_currencies = view.get("otherCurrencies") or {}
    if other_currencies:
        extra = ", ".join(f"{code} {float(value):,.2f}" for code, value in sorted(other_currencies.items()))
        notes.append(f"Also paid in other currencies: {extra}.")
    if not previous_label:
        notes.append("No report was found for the month before, so there is nothing to compare against yet.")
    query = _clean_text(metadata.get("query"))
    if query:
        notes.append(f"Search: {query}")
    if notes:
        story.append(Spacer(1, 8))
        story.append(Paragraph(_pdf_escape(" ".join(notes)), styles["small"]))
    return story


def _bar_label(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    # Two decimals so a bar label never disagrees with the table above it.
    return f"{amount:,.2f}" if amount else ""


def _spend_delta_note(total: float, previous_total: float, currency: str, previous_label: str) -> str:
    if not previous_label or not previous_total:
        return ""
    difference = total - previous_total
    if abs(difference) < 0.005:
        return f"Same as {previous_label}"
    direction = "more" if difference > 0 else "less"
    percent = abs(difference) / previous_total * 100
    return f"{currency} {abs(difference):,.2f} {direction} ({percent:.0f}%) than {previous_label}"


def _count_delta_note(receipt_count: int, previous: dict[str, Any] | None, previous_label: str) -> str:
    if not previous_label or not previous:
        return ""
    return f"{int(previous.get('receiptCount') or 0)} in {previous_label}"


def _delta_label(amount: float, previous_amount: float) -> str:
    if not previous_amount and not amount:
        return "-"
    if not previous_amount:
        return "new"
    if not amount:
        return "stopped"
    difference = amount - previous_amount
    if abs(difference) < 0.005:
        return "same"
    return f"{'+' if difference > 0 else '-'}{abs(difference):,.2f}"


def _spend_headline(total: float, previous_total: float, currency: str, month_label: str, previous_label: str) -> str:
    if not previous_total:
        return f"{previous_label} has no amounts on record, so only {month_label} is charted."
    difference = total - previous_total
    if abs(difference) < 0.005:
        return f"{month_label} came to {currency} {total:,.2f}, the same as {previous_label}."
    direction = "more" if difference > 0 else "less"
    percent = abs(difference) / previous_total * 100
    return (
        f"{month_label} came to {currency} {total:,.2f}, "
        f"{currency} {abs(difference):,.2f} {direction} than {previous_label} ({percent:.0f}%)."
    )


def _write_basic_receipts_pdf(path: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    pages: list[list[str]] = []
    first_page = [
        "Receipt report",
        f"Folder: {metadata.get('outputFolder') or ''}",
        f"Generated: {_format_generated_at(metadata.get('createdAt'))}",
        "",
        "# | Date | Vendor | Amount | Status | Source",
    ]
    if rows:
        for row in rows:
            first_page.append(
                " | ".join([
                    row["index"],
                    _short_text(_format_receipt_date(row["date"]), 20),
                    _short_text(row["vendor"], 24),
                    _format_amount(row),
                    row["status"],
                    _short_text(row["source"], 28),
                ])
            )
    else:
        first_page.append("No candidate receipts found.")
    skipped_lines = _skipped_lines(metadata)
    if skipped_lines:
        first_page.extend(["", "Not counted as receipts", *skipped_lines])
    pages.append(first_page)

    summary = metadata.get("summary")
    summary = summary if isinstance(summary, dict) else summarize_receipt_rows(rows)
    previous = metadata.get("previous")
    previous = previous if isinstance(previous, dict) else None
    view = build_receipt_spend_view(summary, previous)
    currency = view["currency"]
    total = float(view["total"])
    previous_total = float(view["previousTotal"])
    month_label = _clean_text(metadata.get("monthLabel")) or "This month"
    previous_label = _clean_text((previous or {}).get("monthLabel"))
    missing_amounts = int(summary.get("missingAmountCount") or 0)

    summary_page = [
        "Where the money went",
        f"{month_label}, compared with {previous_label}" if previous_label else month_label,
        "",
        f"Total paid: {currency} {total:,.2f}" if currency and total else "Total paid: not detected",
        f"Receipts found: {metadata.get('receiptCount') or 0}",
        f"Vendors paid: {len(summary.get('vendorCounts') or {})}",
        f"Need review: {metadata.get('reviewCount') or 0}",
    ]
    if previous_label:
        summary_page.append(_spend_headline(total, previous_total, currency, month_label, previous_label))
    summary_page.extend(["", "Who we paid"])
    for entry in view["entries"]:
        amount = float(entry["amount"])
        share = float(entry["share"])
        # A bar of hashes stands in for the pie when reportlab is unavailable.
        bar = "#" * max(0, min(20, int(round(share / 5))))
        paid = f"{currency} {amount:,.2f} ({share:.0f}%) {bar}".rstrip() if amount else "no amount read"
        line = f"{_short_text(entry['vendor'], 26)}: {paid}"
        if previous_label:
            previous_amount = float(entry["previous"])
            was = f"{previous_amount:,.2f}" if previous_amount else "-"
            line = f"{line} | {previous_label}: {was} | {_delta_label(amount, previous_amount)}"
        summary_page.append(line)
    if missing_amounts:
        summary_page.extend(["", f"{missing_amounts} receipt(s) had no amount we could read."])
    other_currencies = view.get("otherCurrencies") or {}
    if other_currencies:
        summary_page.append(
            "Also paid in other currencies: "
            + ", ".join(f"{code} {float(value):,.2f}" for code, value in sorted(other_currencies.items()))
        )
    query = str(metadata.get("query") or "").strip()
    if query:
        summary_page.extend(["", "Search query", query])
    pages.append(summary_page)

    for row in rows:
        pages.append([
            f"Receipt {row['index']}: {row['vendor']}",
            row["subject"],
            f"Date: {_format_receipt_date(row['date']) or 'Not available'}",
            f"Amount: {_format_amount(row) or 'Not available'}",
            f"Status: {row['status']}",
            f"Source: {row['source']}",
            f"Source ref: {row['sourceRef'] or 'Not available'}",
            "",
            "Source preview",
            row.get("bodyPreview") or row["snippet"] or "No email text was available.",
            "",
            _format_attachment_list(row) or "No receipt image attachment was available. The source message is recorded for review.",
        ])

    _write_simple_pdf(path, pages)
    # This writer lays out the cover, the summary, then one page per receipt, so
    # the page each sender's PDF follows can simply be counted.
    insertions = [
        (3 + position, [source["path"] for source in receipt_pdf_sources.collect_source_pdfs(row)])
        for position, row in enumerate(rows)
    ]
    receipt_pdf_sources.merge_source_pdfs(path, [(page, paths) for page, paths in insertions if paths])


def _safe_folder_segments(value: str) -> list[str]:
    segments: list[str] = []
    for raw_segment in str(value or "").replace("\\", "/").split("/"):
        segment = _sanitize_path_segment(raw_segment)
        if segment:
            segments.append(segment)
    return segments[:8]


def _sanitize_path_segment(value: Any) -> str:
    segment = _WHITESPACE_RE.sub(" ", str(value or "").strip())
    segment = _BAD_PATH_SEGMENT_RE.sub("-", segment).strip(" .-_")
    if not segment or segment in {".", ".."}:
        return ""
    return segment[:80]


def _safe_owner_key(value: Any) -> str:
    return _sanitize_path_segment(value) or "workspace"


def _extract_receipt_attachments(source: dict[str, Any]) -> list[dict[str, str]]:
    raw_attachments = source.get("attachments")
    if raw_attachments is None:
        raw_attachments = source.get("receiptImages") or source.get("images")
    if not isinstance(raw_attachments, list):
        return []

    attachments: list[dict[str, str]] = []
    for raw_attachment in raw_attachments:
        if isinstance(raw_attachment, str):
            path = _clean_text(raw_attachment)
            if not path:
                continue
            attachments.append({
                "filename": Path(path).name,
                "path": path,
                "mimeType": "",
                "status": "saved",
            })
            continue
        if not isinstance(raw_attachment, dict):
            continue
        filename = _clean_text(raw_attachment.get("filename") or raw_attachment.get("name"))
        path = _clean_text(raw_attachment.get("path"))
        url = _clean_text(raw_attachment.get("url"))
        mime_type = _clean_text(raw_attachment.get("mimeType") or raw_attachment.get("contentType"))
        status = _clean_text(raw_attachment.get("status")) or "saved"
        reason = _clean_text(raw_attachment.get("reason"))
        if not any((filename, path, url)):
            continue
        attachment = {
            "filename": filename or Path(path or url).name,
            "path": path,
            "url": url,
            "mimeType": mime_type,
            "status": status,
        }
        if reason:
            attachment["reason"] = reason
        attachments.append(attachment)
    return attachments


def _is_image_attachment(attachment: dict[str, str]) -> bool:
    mime_type = str(attachment.get("mimeType") or "").strip().lower()
    filename = str(attachment.get("filename") or attachment.get("path") or "").strip()
    return mime_type.startswith("image/") or Path(filename).suffix.lower() in {".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _format_attachment_list(row: dict[str, Any]) -> str:
    attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
    names = [
        str(attachment.get("filename") or Path(str(attachment.get("path") or "")).name).strip()
        for attachment in attachments
        if isinstance(attachment, dict)
    ]
    return ", ".join(name for name in names if name)


def _quote_url_segments(logical_folder: str) -> list[str]:
    return [urllib_parse.quote(segment) for segment in _safe_folder_segments(logical_folder)]


def _clean_text(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


def _format_generated_at(value: Any) -> str:
    """Render the bundle timestamp without the machine-readable tail."""

    text = _clean_text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    return parsed.strftime("%d %b %Y, %H:%M")


def _format_receipt_date(value: Any) -> str:
    """Render a mail date header as something a person reads at a glance."""

    text = _clean_text(value)
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
    except (IndexError, TypeError, ValueError):
        return text
    if parsed is None:
        return text
    return parsed.strftime("%d %b %Y, %H:%M")


def _short_text(value: Any, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _pdf_escape(value: Any) -> str:
    return html.escape(_clean_text(value))


def _extract_vendor(sender: str) -> str:
    if not sender:
        return ""
    display_name, email_address = parseaddr(sender)
    display_name = _clean_text(display_name).strip('"')
    if display_name:
        return display_name
    if "@" in email_address:
        return email_address.split("@", 1)[1].lower()
    return _clean_text(sender)


def _extract_amount(value: str) -> tuple[str, str]:
    text = str(value or "")
    matches = _find_amounts(text)
    if not matches:
        return "", ""
    labelled = _amount_beside_total_label(text, matches)
    if labelled:
        return labelled
    _, amount, currency = matches[0]
    return amount, currency


def _find_amounts(text: str) -> list[tuple[int, str, str]]:
    """Return every currency amount in the text as (position, amount, currency)."""

    claims: list[_AmountClaim] = []
    for pattern in _AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            amount = _normalize_amount(match.group("amount"))
            currency = _currency_code(match.group("currency"))
            if amount and currency:
                claims.append(
                    _AmountClaim(
                        start=match.start(),
                        end=match.end(),
                        amount_span=match.span("amount"),
                        currency_span=match.span("currency"),
                        amount=amount,
                        currency=currency,
                    )
                )
    claims = _settle_shared_currency_markers(claims)
    claims.sort(key=lambda claim: (claim.start, -claim.end))
    found: list[tuple[int, str, str]] = []
    covered_until = -1
    for claim in claims:
        # "$40 USD" matches two patterns over the same number; keep it once.
        if claim.start < covered_until:
            continue
        covered_until = claim.end
        found.append((claim.start, claim.amount, claim.currency))
    return found


def _settle_shared_currency_markers(claims: list[_AmountClaim]) -> list[_AmountClaim]:
    """Keep one claimant per currency marker: the number the marker belongs to.

    A date printed beside a price leaves two numbers reaching for the same
    marker - "30 July 2026 \u20aa65.90" offers the year to the shekel sign on
    its left, and the year wins on position alone. The marker is printed hard
    against 65.90, so that is the amount; when it touches neither number it
    belongs to the number that follows it, the way prices are normally set.
    """

    by_marker: dict[tuple[int, int], list[_AmountClaim]] = defaultdict(list)
    for claim in claims:
        by_marker[claim.currency_span].append(claim)
    kept: list[_AmountClaim] = []
    for claimants in by_marker.values():
        kept.append(min(claimants, key=_currency_claim_rank))
    return kept


def _currency_claim_rank(claim: _AmountClaim) -> tuple[int, int]:
    """Order claimants on a shared marker: touching first, then marker-first."""

    return (0 if claim.marker_touches_amount else 1, 0 if claim.marker_leads_amount else 1)


def _amount_beside_total_label(text: str, matches: list[tuple[int, str, str]]) -> tuple[str, str] | None:
    for label_pattern in _TOTAL_LABEL_PATTERNS:
        labels = list(label_pattern.finditer(text))
        # The grand total is normally the last one quoted, below the line items.
        for label in reversed(labels):
            for start, amount, currency in matches:
                if label.end() <= start <= label.end() + _TOTAL_LABEL_WINDOW:
                    return amount, currency
    return None


def _currency_code(value: str) -> str:
    raw_currency = str(value or "").strip().upper()
    if raw_currency in _CURRENCY_SIGN_CODES:
        return _CURRENCY_SIGN_CODES[raw_currency]
    return "ILS" if raw_currency == "NIS" else raw_currency


def _normalize_amount(value: str) -> str:
    amount = str(value or "").replace(",", "").strip()
    try:
        return f"{float(amount):.2f}"
    except ValueError:
        return amount


def _format_amount(row: dict[str, Any]) -> str:
    amount = str(row.get("amount") or "").strip()
    currency = str(row.get("currency") or "").strip()
    return f"{currency} {amount}".strip()


def _currency_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        currency = str(row.get("currency") or "").strip()
        amount = str(row.get("amount") or "").strip()
        if not currency or not amount:
            continue
        try:
            totals[currency] += float(amount.replace(",", ""))
        except ValueError:
            continue
    return dict(sorted(totals.items()))


def _page_mark_flowable(flowable_cls: Any) -> Any:
    """Build a zero-height flowable that records the page it is drawn on.

    The sender's own pages have to follow the receipt they belong to, and only
    the finished layout knows which report page that turned out to be.
    """

    class _PageMark(flowable_cls):  # type: ignore[misc, valid-type]
        width = 0
        height = 0

        def __init__(self, marks: dict[str, int], key: str) -> None:
            super().__init__()
            self._marks = marks
            self._key = key

        def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
            return 0, 0

        def draw(self) -> None:
            self._marks[self._key] = self.canv.getPageNumber()

    return _PageMark


def _source_pdf_insertions(
    rows: list[dict[str, Any]],
    source_pdfs: dict[str, list[dict[str, Any]]],
    page_marks: dict[str, int],
    last_page: int,
) -> list[tuple[int, list[str]]]:
    """Pair each receipt with the report page its attached PDF follows."""

    starts = [(row["index"], page_marks.get(row["index"], 0)) for row in rows]
    insertions: list[tuple[int, list[str]]] = []
    for position, (index, start_page) in enumerate(starts):
        sources = source_pdfs.get(index) or []
        if not sources or start_page <= 0:
            continue
        next_start = next((page for _, page in starts[position + 1:] if page > 0), 0)
        # A receipt that spilled onto a second page keeps its pages together.
        end_page = next_start - 1 if next_start else int(last_page or start_page)
        insertions.append((max(start_page, end_page), [str(source["path"]) for source in sources]))
    return insertions


def _build_reportlab_image(
    path: Path,
    *,
    image_reader_cls: Any,
    image_cls: Any,
    max_width: float,
    max_height: float,
) -> Any | None:
    if not path.is_file():
        return None
    try:
        width, height = image_reader_cls(str(path)).getSize()
        if width <= 0 or height <= 0:
            return None
        scale = min(max_width / width, max_height / height, 1)
        return image_cls(str(path), width=width * scale, height=height * scale)
    except Exception:
        return None


def _skipped_lines(metadata: dict[str, Any]) -> list[str]:
    """Name what the search returned that was not a receipt."""

    skipped = metadata.get("skipped") if isinstance(metadata.get("skipped"), list) else []
    lines: list[str] = []
    for entry in skipped:
        if not isinstance(entry, dict):
            continue
        vendor = _clean_text(entry.get("vendor")) or "Unknown sender"
        subject = _clean_text(entry.get("subject")) or "(no subject)"
        lines.append(f"{vendor} - {subject}")
    return lines


def _skipped_story(
    metadata: dict[str, Any],
    paragraph_cls: Any,
    spacer_cls: Any,
    heading_style: Any,
    small_style: Any,
) -> list[Any]:
    lines = _skipped_lines(metadata)
    if not lines:
        return []
    story: list[Any] = [
        spacer_cls(1, 12),
        paragraph_cls("Not counted as receipts", heading_style),
        paragraph_cls(
            "The mailbox search matches whole messages, attachments included, so these "
            "came back without being receipts. They are named here rather than dropped "
            "quietly, and they are in none of the totals.",
            small_style,
        ),
    ]
    story.extend(paragraph_cls(_pdf_escape(line), small_style) for line in lines)
    return story


def _receipt_table_style(colors: Any, table_style_cls: Any) -> Any:
    return table_style_cls([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172231")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dee7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fb")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])


def _xlsx_content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""


def _xlsx_root_relationships() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _xlsx_workbook() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Receipts" sheetId="1" r:id="rId1"/>
    <sheet name="Summary" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>"""


def _xlsx_workbook_relationships() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _xlsx_styles() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _xlsx_sheet(rows: list[list[Any]], *, widths: list[int]) -> str:
    column_xml = "".join(
        f'<col min="{index}" max="{index}" width="{max(6, int(width))}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = f"{_xlsx_column_name(column_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            cells.append(
                f'<c r="{ref}" t="inlineStr"{style}><is><t>{xml_escape(str(value or ""))}</t></is></c>'
            )
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{column_xml}</cols>"
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _xlsx_column_name(index: int) -> str:
    name = ""
    value = max(1, int(index))
    while value:
        value, remainder = divmod(value - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _write_simple_pdf(path: Path, pages: list[list[str]]) -> None:
    page_count = max(1, len(pages))
    page_object_ids = [4 + (index * 2) for index in range(page_count)]
    content_object_ids = [5 + (index * 2) for index in range(page_count)]
    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        (
            "2 0 obj\n"
            f"<< /Type /Pages /Count {page_count} /Kids "
            f"[{' '.join(f'{object_id} 0 R' for object_id in page_object_ids)}] >>\n"
            "endobj\n"
        ).encode("ascii"),
        b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    for index, page_lines in enumerate(pages or [["Receipt report"]]):
        page_object_id = page_object_ids[index]
        content_object_id = content_object_ids[index]
        stream = _pdf_page_stream(page_lines)
        objects.append(
            (
                f"{page_object_id} 0 obj\n"
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_object_id} 0 R >>\n"
                "endobj\n"
            ).encode("ascii")
        )
        objects.append(
            (
                f"{content_object_id} 0 obj\n"
                f"<< /Length {len(stream)} >>\n"
                "stream\n"
            ).encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        )

    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for object_bytes in objects:
        offsets.append(len(body))
        body.extend(object_bytes)
    xref_position = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_position}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(body))


def _pdf_page_stream(lines: list[str]) -> bytes:
    commands = ["BT"]
    output_lines = _wrap_pdf_lines(lines)
    y_position = 796
    for index, line in enumerate(output_lines[:48]):
        font_size = 18 if index == 0 else 10
        line_spacing = 20 if index == 0 else 14
        commands.append(f"/F1 {font_size} Tf")
        commands.append(f"1 0 0 1 54 {y_position} Tm")
        commands.append(f"({_pdf_literal_escape(line)}) Tj")
        y_position -= line_spacing
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", errors="replace")


def _wrap_pdf_lines(lines: list[str]) -> list[str]:
    wrapped: list[str] = []
    for raw_line in lines:
        text = _clean_text(raw_line)
        if not text:
            wrapped.append("")
            continue
        while len(text) > 94:
            split_at = text.rfind(" ", 0, 94)
            split_at = split_at if split_at > 20 else 94
            wrapped.append(text[:split_at].rstrip())
            text = text[split_at:].strip()
        wrapped.append(text)
    return wrapped


def _pdf_literal_escape(value: str) -> str:
    return str(value or "").encode("latin-1", errors="replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
