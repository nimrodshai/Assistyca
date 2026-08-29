"""Receipt collector export helpers for Gmail-backed batch actions."""

from __future__ import annotations

import html
import json
import re
import zipfile
from collections import Counter
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from email.utils import parseaddr
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from xml.sax.saxutils import escape as xml_escape

RECEIPT_EXPORT_VERSION = 1
RECEIPT_EXCEL_FILENAME = "receipts.xlsx"
RECEIPT_PDF_FILENAME = "receipt-report.pdf"
RECEIPT_MANIFEST_FILENAME = "bundle.json"
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

    rows = extract_receipt_rows(items)
    metadata = {
        "createdAt": created.isoformat(),
        "outputFolder": logical_folder,
        "query": str(query or "").strip(),
        "receiptCount": len(rows),
        "reviewCount": sum(1 for row in rows if row["status"] != "Ready"),
        "exportVersion": RECEIPT_EXPORT_VERSION,
    }

    excel_path = folder_path / RECEIPT_EXCEL_FILENAME
    pdf_path = folder_path / RECEIPT_PDF_FILENAME
    manifest_path = folder_path / RECEIPT_MANIFEST_FILENAME
    write_receipts_xlsx(excel_path, rows, metadata)
    write_receipts_pdf(pdf_path, rows, metadata)
    manifest_path.write_text(
        json.dumps({"metadata": metadata, "receipts": rows}, indent=2, ensure_ascii=True),
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


def extract_receipt_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items or [], start=1):
        source = item if isinstance(item, dict) else {}
        subject = _clean_text(source.get("subject")) or "(no subject)"
        snippet = _clean_text(source.get("snippet"))
        sender = _clean_text(source.get("from"))
        vendor = _extract_vendor(sender)
        body_text = _clean_text(source.get("bodyText"))
        # The subject and the preview rarely carry the total; the body does.
        amount, currency = _extract_amount(" ".join(part for part in (subject, snippet, body_text) if part))
        date = _clean_text(source.get("date"))
        source_ref = _clean_text(source.get("id") or source.get("threadId"))
        status = "Ready" if vendor and amount else "Needs review"
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
        rows.append({
            "index": str(index),
            "date": date,
            "vendor": vendor or "Unknown vendor",
            "subject": subject,
            "amount": amount,
            "currency": currency,
            "source": sender or "Gmail",
            "sourceRef": source_ref,
            "status": status,
            "notes": notes,
            "snippet": snippet,
            "attachmentCount": str(len(attachments)),
            "attachments": attachments,
            "imageAttachments": image_attachments,
        })
    return rows


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

    story.append(PageBreak())
    story.append(Paragraph("Summary", title_style))
    story.append(Paragraph(_pdf_escape(f"{metadata.get('receiptCount') or 0} candidate receipt(s) found."), body_style))
    story.append(Paragraph(_pdf_escape(f"{metadata.get('reviewCount') or 0} row(s) need review."), body_style))
    query = str(metadata.get("query") or "").strip()
    if query:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Search query", heading_style))
        story.append(Paragraph(_pdf_escape(query), body_style))
    totals = _currency_totals(rows)
    if totals:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Totals by currency", heading_style))
        for currency, total in totals.items():
            story.append(Paragraph(_pdf_escape(f"{currency}: {total:.2f}"), body_style))
    vendors = Counter(row["vendor"] for row in rows if row.get("vendor"))
    if vendors:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Top vendors", heading_style))
        for vendor, count in vendors.most_common(6):
            story.append(Paragraph(_pdf_escape(f"{vendor}: {count}"), body_style))

    for row in rows:
        story.append(PageBreak())
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
        story.append(Paragraph("Source preview", heading_style))
        story.append(Paragraph(_pdf_escape(row["snippet"] or "No email preview was available."), body_style))
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
        else:
            attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
            attachment_note = _format_attachment_list(row)
            if attachments and attachment_note:
                story.append(Paragraph(_pdf_escape(f"Saved attachment(s): {attachment_note}"), small_style))
            else:
                story.append(Paragraph("No receipt image attachment was available. The source message is recorded for review.", small_style))

    document.build(story)


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
    pages.append(first_page)

    summary_page = [
        "Summary",
        f"{metadata.get('receiptCount') or 0} candidate receipt(s) found.",
        f"{metadata.get('reviewCount') or 0} row(s) need review.",
    ]
    query = str(metadata.get("query") or "").strip()
    if query:
        summary_page.extend(["", "Search query", query])
    totals = _currency_totals(rows)
    if totals:
        summary_page.extend(["", "Totals by currency"])
        for currency, total in totals.items():
            summary_page.append(f"{currency}: {total:.2f}")
    vendors = Counter(row["vendor"] for row in rows if row.get("vendor"))
    if vendors:
        summary_page.extend(["", "Top vendors"])
        for vendor, count in vendors.most_common(6):
            summary_page.append(f"{vendor}: {count}")
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
            row["snippet"] or "No email preview was available.",
            "",
            _format_attachment_list(row) or "No receipt image attachment was available. The source message is recorded for review.",
        ])

    _write_simple_pdf(path, pages)


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

    matches: list[tuple[int, int, str, str]] = []
    for pattern in _AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            amount = _normalize_amount(match.group("amount"))
            currency = _currency_code(match.group("currency"))
            if amount and currency:
                matches.append((match.start(), match.end(), amount, currency))
    matches.sort(key=lambda item: (item[0], -item[1]))
    found: list[tuple[int, str, str]] = []
    covered_until = -1
    for start, end, amount, currency in matches:
        # "$40 USD" matches two patterns over the same number; keep it once.
        if start < covered_until:
            continue
        covered_until = end
        found.append((start, amount, currency))
    return found


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
