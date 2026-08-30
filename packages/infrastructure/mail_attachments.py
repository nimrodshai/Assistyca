"""Attachment naming and saving shared by the Gmail and Outlook readers.

Both providers hand back the same kinds of files for a receipt run, and the
receipt bundle should not be able to tell which mailbox a PDF arrived from.
Keeping the naming here means one mailbox cannot produce file names the other
never would.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from urllib import parse as urllib_parse

MAX_RECEIPT_ATTACHMENTS_PER_MESSAGE = 10
MAX_RECEIPT_ATTACHMENT_BYTES = 8 * 1024 * 1024
ATTACHMENT_TOO_LARGE_REASON = "Attachment is too large to include in the receipt bundle."

_ATTACHMENT_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._ -]+")
_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_RECEIPT_ATTACHMENT_MIME_TYPES = {"application/pdf"}


def is_receipt_attachment(mime_type: str, filename: str) -> bool:
    normalized_mime_type = str(mime_type or "").strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    return (
        normalized_mime_type.startswith("image/")
        or normalized_mime_type in _RECEIPT_ATTACHMENT_MIME_TYPES
        or suffix in _IMAGE_EXTENSIONS
        or suffix == ".pdf"
    )


def safe_attachment_filename(
    filename: str,
    *,
    fallback: str,
    mime_type: str,
    message_id: str,
    part_index: int,
    name_prefix: str = "",
) -> str:
    """Name one saved attachment.

    A bundle names files after the message they came from, because the report
    beside them is what a reader goes through. A file saved on its own into a
    folder someone browses is named after the vendor instead, since there is
    no report there to look it up in.
    """

    raw_name = Path(str(filename or "").replace("\\", "/")).name.strip()
    if not raw_name:
        extension = mimetypes.guess_extension(str(mime_type or "").split(";", 1)[0].strip()) or ".bin"
        if extension == ".jpe":
            extension = ".jpg"
        raw_name = f"{fallback}{extension}"
    stem = Path(raw_name).stem.strip() or fallback
    suffix = Path(raw_name).suffix.lower() or ".bin"
    stem = _ATTACHMENT_FILENAME_RE.sub("-", stem).strip(" .-_") or fallback
    readable_prefix = _ATTACHMENT_FILENAME_RE.sub("-", str(name_prefix or "")).strip(" .-_")[:40].strip()
    if readable_prefix:
        return f"{readable_prefix} - {stem[:50]}{suffix}"
    message_fragment = _ATTACHMENT_FILENAME_RE.sub("-", str(message_id or "message"))[:12].strip(" .-_") or "message"
    return f"{message_fragment}-{part_index:02d}-{stem[:50]}{suffix}"


def deduplicate_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 100):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{datetime.now().timestamp():.0f}{suffix}")


def decode_base64_attachment(value: str, *, url_safe: bool) -> bytes:
    """Decode attachment bytes.

    Gmail sends URL-safe base64; Graph sends the standard alphabet. Padding is
    restored either way because both providers strip it in some responses.
    """

    data = str(value or "").strip()
    if not data:
        raise ValueError("missing attachment data")
    padding = "=" * (-len(data) % 4)
    decoder = base64.urlsafe_b64decode if url_safe else base64.b64decode
    try:
        return decoder(f"{data}{padding}".encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("invalid attachment data") from exc


def skipped_attachment(filename: str, *, mime_type: str, size: int) -> dict[str, object]:
    return {
        "filename": filename,
        "mimeType": mime_type,
        "size": size,
        "status": "skipped",
        "reason": ATTACHMENT_TOO_LARGE_REASON,
    }


def save_attachment(
    content: bytes,
    *,
    output_dir: Path,
    filename: str,
    mime_type: str,
    url_prefix: str = "",
) -> dict[str, object]:
    file_path = deduplicate_path(output_dir / filename)
    file_path.write_bytes(content)
    attachment: dict[str, object] = {
        "filename": file_path.name,
        "mimeType": mime_type,
        "size": len(content),
        "path": str(file_path),
        "status": "saved",
    }
    if url_prefix:
        attachment["url"] = f"{str(url_prefix).rstrip('/')}/{urllib_parse.quote(file_path.name)}"
    return attachment
