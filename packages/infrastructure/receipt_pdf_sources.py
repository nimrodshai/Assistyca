"""Fold the sender's own receipt PDF into the receipt report.

Plenty of vendors mail the real receipt as a PDF attachment and leave the email
body as a short covering note. The report is worth far more when those pages sit
right behind our own page for that message than when it only names the file, so
the sender's pages are copied into the report exactly as they arrived.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# A stray 200 page statement should not bury the report it was attached to.
MAX_SOURCE_PDF_PAGES = 20


def is_pdf_attachment(attachment: dict[str, Any]) -> bool:
    mime_type = str(attachment.get("mimeType") or "").strip().lower()
    filename = str(attachment.get("filename") or attachment.get("path") or "").strip()
    return mime_type == "application/pdf" or Path(filename).suffix.lower() == ".pdf"


def collect_source_pdfs(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the readable PDF attachments saved for one receipt row.

    A file that cannot be opened is left out here so the report never promises
    pages that the merge step then fails to add.
    """

    reader_cls = _pdf_reader_class()
    if reader_cls is None:
        return []
    attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
    sources: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("status") != "saved":
            continue
        if not is_pdf_attachment(attachment):
            continue
        path = Path(str(attachment.get("path") or ""))
        page_count = _page_count(reader_cls, path)
        if not page_count:
            continue
        sources.append({
            "path": str(path),
            "filename": str(attachment.get("filename") or path.name),
            "pageCount": min(page_count, MAX_SOURCE_PDF_PAGES),
        })
    return sources


def describe_source_pdf(source: dict[str, Any]) -> str:
    page_count = int(source.get("pageCount") or 0)
    return f"{source.get('filename') or 'receipt.pdf'} ({page_count} page{'' if page_count == 1 else 's'})"


def merge_source_pdfs(report_path: Path, insertions: list[tuple[int, list[str]]]) -> int:
    """Copy attached receipt pages into the report behind the page they belong to.

    ``insertions`` pairs a one-based report page number with the attachment
    paths whose pages follow it. Returns how many pages were added, and leaves
    the report untouched when nothing could be read.
    """

    classes = _pdf_classes()
    if classes is None or not insertions:
        return 0
    reader_cls, writer_cls = classes
    report_reader = _open_pdf(reader_cls, Path(report_path))
    if report_reader is None:
        return 0

    following: dict[int, list[str]] = {}
    for page_number, paths in insertions:
        following.setdefault(int(page_number), []).extend(paths)

    writer = writer_cls()
    added = 0
    try:
        for page_number, page in enumerate(report_reader.pages, start=1):
            writer.add_page(page)
            for path in following.get(page_number, []):
                added += _add_source_pages(writer, reader_cls, Path(path))
    except Exception:
        return 0
    if not added:
        return 0

    merged_path = Path(report_path).with_name(f"{Path(report_path).stem}-merged{Path(report_path).suffix}")
    try:
        with merged_path.open("wb") as handle:
            writer.write(handle)
        merged_path.replace(report_path)
    except Exception:
        merged_path.unlink(missing_ok=True)
        return 0
    return added


def _add_source_pages(writer: Any, reader_cls: Any, path: Path) -> int:
    reader = _open_pdf(reader_cls, path)
    if reader is None:
        return 0
    added = 0
    try:
        for page in list(reader.pages)[:MAX_SOURCE_PDF_PAGES]:
            writer.add_page(page)
            added += 1
    except Exception:
        return added
    return added


def _pdf_classes() -> tuple[Any, Any] | None:
    try:
        from pypdf import PdfReader
        from pypdf import PdfWriter
    except ModuleNotFoundError:
        return None
    return PdfReader, PdfWriter


def _pdf_reader_class() -> Any | None:
    classes = _pdf_classes()
    return classes[0] if classes else None


def _open_pdf(reader_cls: Any, path: Path) -> Any | None:
    """Open a PDF, or return None for anything unreadable.

    Attachments arrive from strangers, so a locked or truncated file is a case
    to skip quietly rather than a reason to lose the whole report.
    """

    if not path.is_file():
        return None
    try:
        reader = reader_cls(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            return None
        if not len(reader.pages):
            return None
        return reader
    except Exception:
        return None


def _page_count(reader_cls: Any, path: Path) -> int:
    reader = _open_pdf(reader_cls, path)
    if reader is None:
        return 0
    try:
        return len(reader.pages)
    except Exception:
        return 0
