"""Tags on the files an agent files away, and where they are kept.

A saved receipt is a PDF in a folder, and a PDF in a folder is only findable
by its name. The name is whatever the vendor called it, so "Render's August
receipt" is not something anyone can search for.

Tags are the missing handle: the vendor, the month, the year, and what the
document is. They live in one small JSON file per folder rather than in the
database, because the folder is already the thing that gets written, copied
and read back - a folder that travels keeps its tags with it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable

# Sits beside the files it describes. The listing endpoint hides it, the same
# way it hides a bundle's manifest.
FILE_TAGS_FILENAME = "tags.json"
FILE_TAGS_VERSION = 1
MAX_TAG_LENGTH = 40
MAX_TAGS_PER_FILE = 12

MONTH_TAGS = (
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_INVOICE_RE = re.compile(r"\binvoices?\b", re.IGNORECASE)
_RECEIPT_RE = re.compile(r"\breceipts?\b", re.IGNORECASE)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_tag(value: Any) -> str:
    """One tag, trimmed to something a person would type into a filter."""

    return _clean(value).replace(",", " ").strip()[:MAX_TAG_LENGTH].strip()


def normalize_tags(values: Any) -> list[str]:
    """A list of tags with the blanks, repeats and nonsense taken out."""

    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = normalize_tag(value)
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
        if len(tags) >= MAX_TAGS_PER_FILE:
            break
    return tags


def parse_tag_date(value: Any) -> datetime | None:
    """The date an email header or a stored row carries, whichever it is."""

    text = _clean(value)
    if not text:
        return None
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def describe_document_kind(*values: Any) -> str:
    """Whether a saved file calls itself an invoice or a receipt.

    Vendors send both, often for the same charge, and the difference is the
    one thing a bookkeeper sorts on. It is read from the words on the file and
    in the subject - never guessed, because a wrong tag is worse than a
    missing one.
    """

    for value in values:
        text = _clean(value)
        if not text:
            continue
        if _INVOICE_RE.search(text):
            return "Invoice"
        if _RECEIPT_RE.search(text):
            return "Receipt"
    return ""


def build_receipt_file_tags(
    *,
    vendor: Any = "",
    subject: Any = "",
    filename: Any = "",
    date_text: Any = "",
) -> list[str]:
    """The tags a receipt PDF gets when it is filed.

    Who it is from, when it is from, and what it is: the three things anyone
    looking for one receipt among a hundred actually knows.
    """

    tags: list[str] = []
    vendor_tag = normalize_tag(vendor)
    if vendor_tag:
        tags.append(vendor_tag)
    moment = parse_tag_date(date_text)
    if moment:
        tags.append(MONTH_TAGS[moment.month])
        tags.append(str(moment.year))
    kind = describe_document_kind(filename, subject)
    if kind:
        tags.append(kind)
    return normalize_tags(tags)


def _tags_path(folder_path: Path) -> Path:
    return Path(folder_path) / FILE_TAGS_FILENAME


def read_file_tags(folder_path: Path) -> dict[str, list[str]]:
    """The tags kept for one folder, by file name.

    A folder with no tag file, or one someone edited into nonsense, reads as a
    folder with no tags. Losing the tags is a worse outcome than a listing
    that shows none, so nothing here raises.
    """

    path = _tags_path(folder_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(files, dict):
        return {}
    tags: dict[str, list[str]] = {}
    for name, values in files.items():
        clean_name = _clean(name)
        clean_tags = normalize_tags(values)
        if clean_name and clean_tags:
            tags[clean_name] = clean_tags
    return tags


def write_file_tags(folder_path: Path, tags_by_file: dict[str, list[str]]) -> bool:
    """Add these tags to the folder's tag file, keeping what is already there.

    Saving the same receipt twice must not drop the tags the first save wrote,
    so this merges rather than replaces.
    """

    folder = Path(folder_path)
    merged = read_file_tags(folder)
    for name, values in (tags_by_file or {}).items():
        clean_name = _clean(name)
        clean_tags = normalize_tags(values)
        if not clean_name or not clean_tags:
            continue
        merged[clean_name] = normalize_tags([*merged.get(clean_name, []), *clean_tags])
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _tags_path(folder).write_text(
            json.dumps({"version": FILE_TAGS_VERSION, "files": merged}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        # The file is filed either way. Tags are how it is found later, not
        # whether it was kept.
        print(f"Writing folder tags failed: {exc}", flush=True)
        return False
    return True


def forget_file_tags(folder_path: Path, names: Iterable[Any]) -> bool:
    """Drop the tags of files the folder no longer holds.

    Writing tags merges, because filing the same receipt twice must not lose
    what the first save recorded. Removal is the one thing that cannot go
    through that door: a tag left behind points at a file nobody can open, and
    fills the folder's filter with names that match nothing.
    """

    folder = Path(folder_path)
    kept = read_file_tags(folder)
    if not kept:
        return False
    gone = {_clean(name).strip("/").casefold() for name in (names or [])}
    gone.discard("")
    remaining = {
        name: tags for name, tags in kept.items() if name.strip("/").casefold() not in gone
    }
    if len(remaining) == len(kept):
        return False
    try:
        _tags_path(folder).write_text(
            json.dumps({"version": FILE_TAGS_VERSION, "files": remaining}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        # The file is gone either way. Its tag is a leftover, not the record.
        print(f"Forgetting folder tags failed: {exc}", flush=True)
        return False
    return True


def collect_folder_tags(tags_by_file: dict[str, list[str]]) -> list[str]:
    """Every tag used in one folder, once each, in alphabetical order."""

    seen: dict[str, str] = {}
    for values in (tags_by_file or {}).values():
        for tag in normalize_tags(values):
            seen.setdefault(tag.lower(), tag)
    return [seen[key] for key in sorted(seen)]
