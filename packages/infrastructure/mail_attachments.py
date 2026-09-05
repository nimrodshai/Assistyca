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
ATTACHMENT_NOT_A_RECEIPT_FILE_REASON = "Attachment is not the PDF or image its name says it is, so it was not saved."

# What the first bytes of a real file look like. A mailbox reports a type and
# a name, and both are whatever the sender wrote; the bytes are not.
_PDF_HEADER = b"%PDF-"
_IMAGE_HEADERS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

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


def sniff_attachment_kind(content: bytes) -> str:
    """"pdf", "image", or "" - from the bytes alone."""

    head = bytes(content[:1024] or b"")
    if not head:
        return ""
    # A PDF may open with a little junk before its header; the format allows
    # it and some generators do it. Anywhere in the first kilobyte is fine.
    if _PDF_HEADER in head:
        return "pdf"
    for header, _name in _IMAGE_HEADERS:
        if head.startswith(header):
            return "image"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image"
    return ""


def content_is_receipt_attachment(content: bytes, *, mime_type: str, filename: str) -> bool:
    """Whether the bytes are the PDF or image the message said they were.

    A name and a type are claims; this checks them against the file. A PDF
    that is really a web page, or a picture wearing a .pdf name, is refused
    before it is written into a folder someone will open.
    """

    kind = sniff_attachment_kind(content)
    if not kind:
        return False
    normalized_mime_type = str(mime_type or "").strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    says_pdf = normalized_mime_type in _RECEIPT_ATTACHMENT_MIME_TYPES or suffix == ".pdf"
    says_image = normalized_mime_type.startswith("image/") or suffix in _IMAGE_EXTENSIONS
    if kind == "pdf":
        return says_pdf
    return says_image


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


def skipped_attachment(
    filename: str,
    *,
    mime_type: str,
    size: int,
    reason: str = ATTACHMENT_TOO_LARGE_REASON,
) -> dict[str, object]:
    return {
        "filename": filename,
        "mimeType": mime_type,
        "size": size,
        "status": "skipped",
        "reason": reason,
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
