"""Readable message body text shared by the Gmail and Outlook readers.

A receipt total is almost always in the body of the email, not in the subject
or in the short preview both providers hand back. Flattening the body to plain
text here means the receipt collector reads the same words no matter which
mailbox a receipt arrived from.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from typing import Any

MAX_BODY_TEXT_CHARS = 20000

_HTML_HIDDEN_RE = re.compile(r"(?is)<(script|style|head)[^>]*>.*?</\1>")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def collapse_whitespace(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def decode_base64url(value: Any) -> str:
    """Decode a Gmail base64url body part, or return "" when it is unusable."""

    text = str(value or "").strip()
    if not text:
        return ""
    padding = "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode(text + padding)
    except (binascii.Error, ValueError):
        return ""
    return raw.decode("utf-8", errors="replace")


def html_to_text(value: Any) -> str:
    """Flatten an HTML body into the words a person would read on screen."""

    text = str(value or "")
    if not text:
        return ""
    text = _HTML_HIDDEN_RE.sub(" ", text)
    # Every tag becomes a space so a total sitting in its own table cell does
    # not end up glued to the label in the cell before it.
    text = _HTML_TAG_RE.sub(" ", text)
    return collapse_whitespace(html.unescape(text))


def limit_body_text(value: Any) -> str:
    """Trim body text to the slice worth scanning for an amount."""

    return collapse_whitespace(value)[:MAX_BODY_TEXT_CHARS]
