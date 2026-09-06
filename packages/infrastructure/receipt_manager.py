"""The receipt manager: every receipt and invoice a search pulled, kept.

A receipt search reads the mailbox, judges what came back and answers, and
until now that was the end of it: the rows lived for one reply. This module
keeps them. Each row the search counted becomes a stored receipt with its
amount, its date, its kind (receipt or invoice) and the file the vendor
attached; each row the judge was not sure about is stored as a question for
the owner, who answers it with a yes or a no on the receipts page.

The arithmetic - totals by currency, by month, by kind, by vendor - is done
here in code. The page and the exports only show it.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import date
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Iterable

from packages.infrastructure import fx_rates
from packages.infrastructure import receipt_collector
from packages.infrastructure.file_tags import describe_document_kind
from packages.infrastructure.file_tags import parse_tag_date
from packages.infrastructure.receipt_collector import RECEIPT_STATUS_DUPLICATE
from packages.infrastructure.receipt_collector import RECEIPT_STATUS_NOT_A_RECEIPT
from packages.infrastructure.receipt_collector import UNKNOWN_VENDOR_LABEL

# What a stored receipt is to the owner.
RECEIPT_STATUS_CONFIRMED = "confirmed"
# The search was not sure this is a receipt at all; the owner is asked.
RECEIPT_STATUS_UNSURE = "unsure"
# The owner said no. Kept so the same email is never asked about twice.
RECEIPT_STATUS_REJECTED = "rejected"
RECEIPT_STATUSES = (RECEIPT_STATUS_CONFIRMED, RECEIPT_STATUS_UNSURE, RECEIPT_STATUS_REJECTED)

RECEIPT_KIND_RECEIPT = "receipt"
RECEIPT_KIND_INVOICE = "invoice"
RECEIPT_KINDS = (RECEIPT_KIND_RECEIPT, RECEIPT_KIND_INVOICE)

# Where the files a search fetches for the manager are kept, under the
# owner's own output folder: one subfolder per month the receipt is from.
RECEIPT_MANAGER_FOLDER = "Receipt manager"
# How many messages one search goes back to the mailbox for, to fetch the
# file the vendor attached. Each is one mailbox call.
RECEIPT_MANAGER_FETCH_LIMIT = 60
# How many receipts an account keeps before the oldest search stops adding.
RECEIPT_MANAGER_MAX_RECEIPTS = 5000
RECEIPT_MANAGER_MAX_TEXT = 300
RECEIPT_MANAGER_MAX_NOTES = 600

_AMOUNT_RE = re.compile(r"^-?\d{1,12}(?:\.\d{1,2})?$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# -- reading a search's rows -----------------------------------------------


def _clean(value: Any, limit: int = RECEIPT_MANAGER_MAX_TEXT) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text[:limit]


def normalize_amount(value: Any) -> str:
    """An amount as the store keeps it: digits and at most two decimals, or nothing."""

    text = _clean(value).replace(",", "").replace(" ", "")
    if not text:
        return ""
    if text.startswith("+"):
        text = text[1:]
    if not _AMOUNT_RE.match(text):
        try:
            number = float(text)
        except ValueError:
            return ""
        text = f"{number:.2f}"
    return text


def normalize_receipt_date(value: Any) -> str:
    """A date as YYYY-MM-DD, from a mail header, an ISO stamp, or the page's own picker."""

    text = _clean(value)
    if not text:
        return ""
    if _DATE_RE.match(text):
        try:
            date.fromisoformat(text)
        except ValueError:
            return ""
        return text
    moment = parse_tag_date(text)
    if moment is None:
        return ""
    return moment.date().isoformat()


def normalize_status(value: Any) -> str:
    text = _clean(value).lower()
    return text if text in RECEIPT_STATUSES else ""


def normalize_kind(value: Any) -> str:
    text = _clean(value).lower()
    if text in ("invoices",):
        return RECEIPT_KIND_INVOICE
    if text in ("receipts",):
        return RECEIPT_KIND_RECEIPT
    return text if text in RECEIPT_KINDS else ""


def describe_row_kind(row: dict[str, Any]) -> str:
    """Receipt or invoice, from the words on the email and its files.

    A vendor sends both, often for one charge, and which one this is comes
    from what it calls itself: the subject line first, then the file names.
    Nothing that calls itself either is a receipt, the ordinary case.
    """

    names = [
        _clean(item.get("filename") if isinstance(item, dict) else item)
        for item in (row.get("attachments") if isinstance(row.get("attachments"), list) else [])
    ]
    names.extend(_clean(name) for name in (row.get("attachmentNames") if isinstance(row.get("attachmentNames"), list) else []))
    kind = describe_document_kind(row.get("subject"), *names)
    return RECEIPT_KIND_INVOICE if kind == "Invoice" else RECEIPT_KIND_RECEIPT


def classify_collected_row(row: dict[str, Any]) -> str:
    """What the manager keeps this row as, or nothing when it keeps it not at all.

    A row the search counted is a confirmed receipt. A row the judge ruled
    out with a low confidence, or ruled in with one, is a question for the
    owner. A row ruled out with confidence is not kept: it is an advert or a
    delivery note, and the page is for receipts. A second email about a
    payment already counted is not kept either; the counted row names it.
    """

    status = _clean(row.get("status"))
    confidence = _clean(row.get("confidence")).lower()
    if status == RECEIPT_STATUS_DUPLICATE:
        return ""
    if status == RECEIPT_STATUS_NOT_A_RECEIPT:
        return RECEIPT_STATUS_UNSURE if confidence == "low" else ""
    if confidence == "low":
        return RECEIPT_STATUS_UNSURE
    return RECEIPT_STATUS_CONFIRMED


def saved_attachments(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The files a row already has on disk, as the store keeps them."""

    saved: list[dict[str, Any]] = []
    for raw in row.get("attachments") if isinstance(row.get("attachments"), list) else []:
        if not isinstance(raw, dict) or _clean(raw.get("status") or "saved") != "saved":
            continue
        url = _clean(raw.get("url"), 600)
        if not url:
            continue
        saved.append({
            "filename": _clean(raw.get("filename") or raw.get("name")) or Path(url).name,
            "mimeType": _clean(raw.get("mimeType")),
            "size": int(raw.get("size") or 0) if str(raw.get("size") or "").isdigit() else 0,
            "url": url,
        })
    return saved


def build_receipt_record(row: dict[str, Any], *, status: str = "") -> dict[str, Any]:
    """One search row as the record the store keeps."""

    kept_as = normalize_status(status) or classify_collected_row(row) or RECEIPT_STATUS_CONFIRMED
    vendor = _clean(row.get("vendor"))
    if vendor == UNKNOWN_VENDOR_LABEL:
        vendor = ""
    return {
        "status": kept_as,
        "kind": describe_row_kind(row),
        "vendor": vendor,
        "paidTo": _clean(row.get("paidTo")),
        "subject": _clean(row.get("subject")),
        "mailbox": _clean(row.get("mailbox")),
        "messageId": _clean(row.get("sourceRef")),
        "mailDate": _clean(row.get("date")),
        "receiptDate": normalize_receipt_date(row.get("date")),
        "amount": normalize_amount(row.get("amount")),
        "currency": fx_rates.normalize_currency_code(row.get("currency")) or _clean(row.get("currency"), 8).upper(),
        "reason": _clean(row.get("reason")),
        "notes": "",
        "snippet": _clean(row.get("bodyPreview") or row.get("snippet"), RECEIPT_MANAGER_MAX_NOTES),
        "attachments": saved_attachments(row),
        # The names the mail carried, whether or not the files were fetched.
        # They are what says a fetch is worth a mailbox call.
        "attachmentNames": [
            _clean(name)
            for name in (row.get("attachmentNames") if isinstance(row.get("attachmentNames"), list) else [])
            if _clean(name)
        ],
    }


def store_collected_receipts(
    database: Any,
    *,
    user_id: int,
    receipts: Iterable[dict[str, Any]],
    skipped: Iterable[dict[str, Any]] = (),
    fetch_files: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    fetch_limit: int = RECEIPT_MANAGER_FETCH_LIMIT,
) -> dict[str, Any]:
    """Keep what a search found, and go back for the files it did not save.

    ``receipts`` are the rows the search counted; ``skipped`` are the rows it
    set aside, of which only the ones the judge was unsure about are kept.
    ``fetch_files`` is handed a stored record whose email carried files the
    run never saved, and returns the attachments it fetched; it is called at
    most ``fetch_limit`` times, because each call is a trip to the mailbox.

    A receipt the owner has already ruled on keeps their ruling. The search
    may refresh what it read - the subject, the file - but never what they
    decided or the amount they typed in.
    """

    if int(user_id or 0) <= 0:
        return {"stored": 0, "added": 0, "unsure": 0, "filesSaved": 0, "records": []}
    outcome: dict[str, Any] = {"stored": 0, "added": 0, "unsure": 0, "filesSaved": 0, "records": []}
    fetches = 0
    for rows in (receipts, skipped):
        for row in rows:
            if not isinstance(row, dict):
                continue
            kept_as = classify_collected_row(row)
            if not kept_as:
                continue
            record = build_receipt_record(row, status=kept_as)
            names = record.pop("attachmentNames", [])
            try:
                stored, created = database.upsert_account_receipt(user_id=int(user_id), record=record)
            except ValueError as exc:
                print(f"Receipt could not be kept: {exc}", flush=True)
                continue
            if fetch_files is not None and not stored.get("attachments") and names and fetches < int(fetch_limit):
                fetches += 1
                try:
                    fetched = fetch_files(stored) or []
                except Exception as exc:  # A mailbox that will not hand a file over is not a reason to lose the receipt.
                    print(f"Receipt file could not be fetched: {exc}", flush=True)
                    fetched = []
                kept_files = saved_attachments({"attachments": fetched})
                if kept_files:
                    stored = database.set_account_receipt_attachments(
                        user_id=int(user_id), receipt_id=int(stored["id"]), attachments=kept_files,
                    ) or stored
                    outcome["filesSaved"] += len(kept_files)
            outcome["stored"] += 1
            if created:
                outcome["added"] += 1
            if stored.get("status") == RECEIPT_STATUS_UNSURE:
                outcome["unsure"] += 1
            outcome["records"].append(stored)
    return outcome


# -- ranges and figures ------------------------------------------------------


def parse_date_range(from_value: Any, to_value: Any) -> tuple[str, str]:
    """The range a page or an export asked for, as two ISO dates or blanks."""

    start = normalize_receipt_date(from_value)
    end = normalize_receipt_date(to_value)
    if start and end and end < start:
        start, end = end, start
    return start, end


def describe_date_range(start: str, end: str) -> str:
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"from {start}"
    if end:
        return f"up to {end}"
    return "all dates"


def month_key(record: dict[str, Any]) -> str:
    text = _clean(record.get("receiptDate"))
    return text[:7] if _DATE_RE.match(text) else ""


def _amount_value(record: dict[str, Any]) -> float | None:
    try:
        return float(normalize_amount(record.get("amount")))
    except ValueError:
        return None


def summarize_receipt_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Every figure the page and the exports show, worked out once, here.

    Totals are per currency and never added across currencies: 262 shekels
    and 55 dollars are two figures, and the page shows two figures.
    """

    rows = [record for record in records if isinstance(record, dict)]
    confirmed = [record for record in rows if record.get("status") == RECEIPT_STATUS_CONFIRMED]
    totals: dict[str, float] = defaultdict(float)
    by_kind: dict[str, dict[str, Any]] = {
        kind: {"count": 0, "totals": defaultdict(float)} for kind in RECEIPT_KINDS
    }
    by_month: dict[str, dict[str, Any]] = {}
    by_vendor: dict[str, dict[str, Any]] = {}
    missing_amount = 0
    undated = 0
    for record in confirmed:
        amount = _amount_value(record)
        currency = _clean(record.get("currency"), 8)
        kind = normalize_kind(record.get("kind")) or RECEIPT_KIND_RECEIPT
        month = month_key(record)
        vendor = _clean(record.get("paidTo")) or _clean(record.get("vendor")) or UNKNOWN_VENDOR_LABEL
        by_kind[kind]["count"] += 1
        month_bucket = by_month.setdefault(month, {"month": month, "count": 0, "totals": defaultdict(float)})
        month_bucket["count"] += 1
        vendor_bucket = by_vendor.setdefault(vendor, {"vendor": vendor, "count": 0, "totals": defaultdict(float)})
        vendor_bucket["count"] += 1
        if not month:
            undated += 1
        if amount is None or not currency:
            missing_amount += 1
            continue
        totals[currency] += amount
        by_kind[kind]["totals"][currency] += amount
        month_bucket["totals"][currency] += amount
        vendor_bucket["totals"][currency] += amount

    def rounded(values: dict[str, float]) -> dict[str, float]:
        return {code: round(value, 2) for code, value in sorted(values.items())}

    return {
        "count": len(confirmed),
        "unsureCount": sum(1 for record in rows if record.get("status") == RECEIPT_STATUS_UNSURE),
        "rejectedCount": sum(1 for record in rows if record.get("status") == RECEIPT_STATUS_REJECTED),
        "missingAmountCount": missing_amount,
        "undatedCount": undated,
        "totals": rounded(totals),
        "byKind": {
            kind: {"count": bucket["count"], "totals": rounded(bucket["totals"])}
            for kind, bucket in by_kind.items()
        },
        "byMonth": [
            {"month": bucket["month"], "count": bucket["count"], "totals": rounded(bucket["totals"])}
            for bucket in sorted(by_month.values(), key=lambda entry: entry["month"], reverse=True)
        ],
        "byVendor": [
            {"vendor": bucket["vendor"], "count": bucket["count"], "totals": rounded(bucket["totals"])}
            for bucket in sorted(
                by_vendor.values(),
                key=lambda entry: (-sum(entry["totals"].values()), -entry["count"], entry["vendor"].lower()),
            )
        ],
    }


# -- exports -----------------------------------------------------------------


EXPORT_FORMATS = ("csv", "xlsx", "pdf")
EXPORT_COLUMNS = ("Date", "Vendor", "Paid to", "Type", "Amount", "Currency", "Subject", "Mailbox", "File", "Notes")


def export_filename(start: str, end: str, fmt: str) -> str:
    span = f"{start or 'start'}-to-{end or 'today'}" if (start or end) else "all"
    return f"receipts-{span}.{fmt}"


def _format_totals(totals: dict[str, Any]) -> str:
    return ", ".join(f"{float(value):,.2f} {code}" for code, value in sorted(totals.items())) or "none"


def _export_rows(records: Iterable[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in sorted(
        (record for record in records if isinstance(record, dict)),
        key=lambda entry: (_clean(entry.get("receiptDate")) or "0000-00-00", int(entry.get("id") or 0)),
    ):
        files = record.get("attachments") if isinstance(record.get("attachments"), list) else []
        rows.append([
            _clean(record.get("receiptDate")) or _clean(record.get("mailDate")),
            _clean(record.get("vendor")) or UNKNOWN_VENDOR_LABEL,
            _clean(record.get("paidTo")),
            (normalize_kind(record.get("kind")) or RECEIPT_KIND_RECEIPT).capitalize(),
            normalize_amount(record.get("amount")),
            _clean(record.get("currency"), 8),
            _clean(record.get("subject")),
            _clean(record.get("mailbox")),
            ", ".join(_clean(item.get("filename")) for item in files if isinstance(item, dict)),
            _clean(record.get("notes"), RECEIPT_MANAGER_MAX_NOTES),
        ])
    return rows


def _summary_lines(records: list[dict[str, Any]], *, range_label: str) -> list[list[str]]:
    summary = summarize_receipt_records(records)
    lines = [
        ["Period", range_label],
        ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")],
        ["Receipts and invoices", str(summary["count"])],
        ["Receipts", str(summary["byKind"][RECEIPT_KIND_RECEIPT]["count"])],
        ["Invoices", str(summary["byKind"][RECEIPT_KIND_INVOICE]["count"])],
        ["Without an amount", str(summary["missingAmountCount"])],
    ]
    for code, value in summary["totals"].items():
        lines.append([f"Total {code}", f"{value:,.2f}"])
    for kind in RECEIPT_KINDS:
        for code, value in summary["byKind"][kind]["totals"].items():
            lines.append([f"{kind.capitalize()}s {code}", f"{value:,.2f}"])
    for bucket in summary["byMonth"]:
        lines.append([f"Month {bucket['month'] or 'undated'}", f"{bucket['count']} · {_format_totals(bucket['totals'])}"])
    for bucket in summary["byVendor"][:25]:
        lines.append([f"Vendor {bucket['vendor']}", f"{bucket['count']} · {_format_totals(bucket['totals'])}"])
    return lines


def write_receipt_export_csv(records: list[dict[str, Any]], *, range_label: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for row in _export_rows(records):
        writer.writerow(row)
    writer.writerow([])
    for label, value in _summary_lines(records, range_label=range_label):
        writer.writerow([label, value])
    return buffer.getvalue().encode("utf-8-sig")


def write_receipt_export_xlsx(records: list[dict[str, Any]], *, range_label: str) -> bytes:
    """A two-sheet workbook: the receipts, then the figures. Same shape the
    bundle export has always had, so an accountant sees one format."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", receipt_collector._xlsx_content_types())
        archive.writestr("_rels/.rels", receipt_collector._xlsx_root_relationships())
        archive.writestr("xl/workbook.xml", receipt_collector._xlsx_workbook())
        archive.writestr("xl/_rels/workbook.xml.rels", receipt_collector._xlsx_workbook_relationships())
        archive.writestr("xl/styles.xml", receipt_collector._xlsx_styles())
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            receipt_collector._xlsx_sheet(
                [list(EXPORT_COLUMNS), *_export_rows(records)],
                widths=[12, 24, 22, 10, 12, 10, 44, 24, 30, 40],
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            receipt_collector._xlsx_sheet(
                [["Metric", "Value"], *_summary_lines(records, range_label=range_label)],
                widths=[32, 60],
            ),
        )
    return buffer.getvalue()


def write_receipt_export_pdf(records: list[dict[str, Any]], *, range_label: str) -> bytes:
    """A summary an accountant can read: the figures first, then every line."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.pagesizes import landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph
        from reportlab.platypus import SimpleDocTemplate
        from reportlab.platypus import Spacer
        from reportlab.platypus import Table
        from reportlab.platypus import TableStyle
    except ModuleNotFoundError:
        return _write_plain_pdf(records, range_label=range_label)

    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12)
    cell = ParagraphStyle("Cell", parent=body, fontSize=8, leading=10)
    head = ParagraphStyle("Head", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

    def escape(value: Any) -> str:
        return _clean(value, 400).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title="Receipts summary",
    )
    story: list[Any] = [Paragraph("Receipts and invoices", title), Paragraph(escape(f"Period: {range_label}"), body), Spacer(1, 6)]
    summary_rows = [[Paragraph(escape(label), cell), Paragraph(escape(value), cell)] for label, value in _summary_lines(records, range_label=range_label)]
    summary_table = Table(summary_rows, colWidths=[70 * mm, 190 * mm])
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dee7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([summary_table, Spacer(1, 10)])

    table_rows: list[list[Any]] = [[Paragraph(escape(column), head) for column in EXPORT_COLUMNS[:9]]]
    for row in _export_rows(records):
        table_rows.append([Paragraph(escape(value), cell) for value in row[:9]])
    if len(table_rows) == 1:
        table_rows.append([Paragraph("No receipts in this period.", cell)] + [""] * 8)
    table = Table(table_rows, colWidths=[20 * mm, 34 * mm, 30 * mm, 16 * mm, 20 * mm, 16 * mm, 60 * mm, 36 * mm, 41 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172231")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dee7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fb")]),
    ]))
    story.append(table)
    document.build(story)
    return buffer.getvalue()


def _write_plain_pdf(records: list[dict[str, Any]], *, range_label: str) -> bytes:
    """The same summary as plain text pages, for a machine without reportlab."""

    lines = [f"Receipts and invoices - {range_label}", ""]
    lines.extend(f"{label}: {value}" for label, value in _summary_lines(records, range_label=range_label))
    lines.extend(["", " | ".join(EXPORT_COLUMNS[:6])])
    lines.extend(" | ".join(row[:6]) for row in _export_rows(records))

    def pdf_text(value: str) -> str:
        return value.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    page_lines = [lines[index:index + 48] for index in range(0, max(len(lines), 1), 48)] or [[]]
    objects: list[bytes] = []
    page_ids: list[int] = []
    font_id = 3 + 2 * len(page_lines)
    for index, chunk in enumerate(page_lines):
        content = ["BT", "/F1 9 Tf", "40 800 Td", "12 TL"]
        content.extend(f"({pdf_text(line)}) Tj T*" for line in chunk)
        content.append("ET")
        stream = "\n".join(content).encode("latin-1")
        page_id = 3 + 2 * index
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {page_id + 1} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode("latin-1")
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    header = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1"),
    ]
    all_objects = header + objects + [b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(all_objects, start=1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(all_objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(all_objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return output.getvalue()


def write_receipt_export(records: list[dict[str, Any]], *, fmt: str, range_label: str) -> tuple[bytes, str]:
    """The export in one format, and the content type it is served with."""

    kind = _clean(fmt).lower()
    if kind == "xlsx":
        return write_receipt_export_xlsx(records, range_label=range_label), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if kind == "pdf":
        return write_receipt_export_pdf(records, range_label=range_label), "application/pdf"
    return write_receipt_export_csv(records, range_label=range_label), "text/csv; charset=utf-8"
