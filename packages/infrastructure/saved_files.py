"""Answers read from the folders the account already keeps.

Everything the agent knew about money, it learned from the mailbox. It filed
the receipts afterwards and then never looked at them again, so "how much did
Render come to in August" went back to Gmail for messages that had already
been read, counted and written down.

A filed folder is not a pile of PDFs. Beside them sits the bundle manifest,
holding the rows exactly as they were counted: vendor, amount, currency, date,
what the charge was for. Reading a folder is reading that file, which makes an
answer from a folder cheaper than the search that produced it and, more to the
point, the same answer - the mailbox can lose a message, and a folder cannot.

A folder with no manifest is not a broken folder. Folders can be made by hand
and filled with anything, so what is known there is the file listing and its
tags. That answers what is in the folder without pretending to know what any
of it cost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.infrastructure.file_tags import FILE_TAGS_FILENAME
from packages.infrastructure.file_tags import read_file_tags
# The name the bundle writer uses. Reading it back from a second definition
# would let the two drift, and a folder whose manifest has been renamed reads
# as a folder with no figures - the quietest possible failure.
from packages.infrastructure.receipt_collector import RECEIPT_MANIFEST_FILENAME

# One question reads a few folders, not a year of them. A span wider than this
# is a question about a period, which the mailbox runner answers.
SAVED_FOLDER_LIMIT = 12
SAVED_FILE_LIMIT = 200


def _clean(value: Any) -> str:
    return str(value or "").strip()


def read_bundle_rows(folder_path: Path) -> list[dict[str, Any]]:
    """The receipt rows a filed folder was written with.

    A folder that has no manifest, or one someone has edited into nonsense,
    reads as a folder with no rows rather than raising. The files are still
    listed either way, and saying "I can see the folder but not its figures"
    is a better answer than an error.
    """

    path = Path(folder_path) / RECEIPT_MANIFEST_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    receipts = raw.get("receipts") if isinstance(raw, dict) else None
    if not isinstance(receipts, list):
        return []
    return [row for row in receipts if isinstance(row, dict)]


def read_bundle_metadata(folder_path: Path) -> dict[str, Any]:
    """What the run that filed this folder recorded about itself."""

    path = Path(folder_path) / RECEIPT_MANIFEST_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    metadata = raw.get("metadata") if isinstance(raw, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def list_folder_files(folder_path: Path) -> list[dict[str, Any]]:
    """Every file in a folder with the tags it is findable by.

    The manifest and the tag file describe the folder rather than being things
    kept in it, so they are left out here the same way the listing endpoint
    leaves them out.
    """

    folder = Path(folder_path)
    if not folder.is_dir():
        return []
    tags_by_file = read_file_tags(folder)
    files: list[dict[str, Any]] = []
    for path in sorted(folder.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.name in (RECEIPT_MANIFEST_FILENAME, FILE_TAGS_FILENAME):
            continue
        name = "/".join(path.relative_to(folder).parts)
        entry: dict[str, Any] = {"name": name}
        tags = tags_by_file.get(name)
        if tags:
            entry["tags"] = list(tags)
        files.append(entry)
        if len(files) >= SAVED_FILE_LIMIT:
            break
    return files


def describe_saved_folder(folder_path: Path, *, folder: str = "") -> dict[str, Any]:
    """One folder as the thing a question is answered from."""

    path = Path(folder_path)
    rows = read_bundle_rows(path)
    files = list_folder_files(path)
    metadata = read_bundle_metadata(path)
    return {
        "folder": _clean(folder),
        "receipts": rows,
        "files": files,
        "fileCount": len(files),
        # What the run was looking for when it filed this. It is the honest
        # answer to "what is in here" for a folder whose files are all called
        # something the vendor chose.
        "query": _clean(metadata.get("query")),
        "monthLabel": _clean(metadata.get("monthLabel")),
        "createdAt": _clean(metadata.get("createdAt")),
    }


def _row_haystack(row: dict[str, Any]) -> str:
    return " ".join(
        _clean(row.get(key))
        for key in ("vendor", "subject", "source", "notes", "detail")
    ).casefold()


def select_saved_rows(
    rows: list[dict[str, Any]],
    *,
    vendor: Any = "",
    kind: Any = "",
) -> list[dict[str, Any]]:
    """The saved rows a question is about.

    Vendor matching is left to the receipt code that already does it for a
    mailbox answer, so this narrows only on what that one does not know: which
    document someone asked for when they said invoices rather than receipts.
    """

    kind_text = _clean(kind).casefold()
    selected = list(rows)
    if kind_text in {"invoice", "invoices"}:
        selected = [row for row in selected if "invoic" in _row_haystack(row)]
    elif kind_text in {"receipt", "receipts"}:
        selected = [row for row in selected if "invoic" not in _row_haystack(row)]
    vendor_text = _clean(vendor).casefold()
    if vendor_text:
        selected = [row for row in selected if vendor_text in _row_haystack(row)]
    return selected


def describe_saved_file_records(folders: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The files themselves, one line each.

    A folder with no manifest still answers "what have I got from Render", and
    this is what that answer is written from: the file, the folder holding it,
    and the handles it was filed under.
    """

    records: list[dict[str, str]] = []
    for entry in folders:
        folder = _clean(entry.get("folder"))
        for item in entry.get("files") or []:
            name = _clean(item.get("name"))
            if not name:
                continue
            record = {"file": name, "folder": folder}
            tags = item.get("tags")
            if tags:
                record["tags"] = ", ".join(_clean(tag) for tag in tags if _clean(tag))
            records.append(record)
    return records


def count_saved_files(folders: list[dict[str, Any]]) -> int:
    return sum(int(entry.get("fileCount") or 0) for entry in folders)
