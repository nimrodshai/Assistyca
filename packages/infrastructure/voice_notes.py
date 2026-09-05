"""Voice notes: a message someone spoke instead of typed.

The recording arrives from the portal composer or as a WhatsApp voice
message. Either way it becomes words here, through the OpenAI gateway, and
those words are the message: the turn that follows never knows the
difference. What this module owns is the shape of a note the assistant
accepts and the one call that turns it into text.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from packages.infrastructure.openai_api import OpenAIError
from packages.infrastructure.openai_api import call_openai_transcription
from packages.infrastructure.openai_api import load_openai_config
from packages.infrastructure.task_complexity import resolve_transcription_model


# The containers browsers record into and WhatsApp delivers. A recording in
# anything else is refused before it is decoded.
VOICE_NOTE_MIME_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/x-m4a",
        "audio/aac",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/flac",
        "audio/amr",
    }
)
# Two minutes of speech in a compressed container is well under a megabyte;
# the cap leaves room for an uncompressed recording of the same length.
VOICE_NOTE_MAX_BYTES = 5 * 1024 * 1024
VOICE_NOTE_MAX_SECONDS = 120
# What the transcript keeps of a spoken message.
VOICE_NOTE_MARKER = "[voice note]"
TRANSCRIPTION_TOOL_NAME = "voice_note_transcription"
TRANSCRIPTION_TIMEOUT_SECONDS = 60.0

_DATA_URL = re.compile(r"^data:(?P<mime>[a-z0-9.+/-]+)(?:;[^,]*)?;base64,(?P<data>.*)$", re.IGNORECASE | re.DOTALL)


class VoiceNoteError(RuntimeError):
    """A voice note that could not be taken in, with a reason in plain words."""


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_voice_note_mime_type(value: Any) -> str:
    """The container type without its codec parameters, lower-cased, or an
    empty string when it is not one the assistant reads."""

    mime_type = normalize_text(value).split(";")[0].strip().lower()
    return mime_type if mime_type in VOICE_NOTE_MIME_TYPES else ""


def normalize_voice_note(value: Any) -> dict[str, Any]:
    """The recording a request carries, decoded and checked.

    Takes either a data URL or a bare base64 body beside its type. Returns
    an empty dict for anything that is not a readable recording, so a caller
    can tell "no voice note" from "a broken one" only by asking for the
    reason through `describe_voice_note_problem`.
    """

    if not isinstance(value, dict):
        return {}
    data = ""
    mime_type = ""
    data_url = normalize_text(value.get("dataUrl"))
    if data_url:
        match = _DATA_URL.match(data_url)
        if not match:
            return {}
        mime_type = normalize_voice_note_mime_type(match.group("mime"))
        data = match.group("data")
    else:
        mime_type = normalize_voice_note_mime_type(value.get("mimeType"))
        data = normalize_text(value.get("audioBase64"))
    if not mime_type or not data:
        return {}
    if len(data) > VOICE_NOTE_MAX_BYTES * 4 // 3 + 4:
        return {}
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return {}
    if not raw or len(raw) > VOICE_NOTE_MAX_BYTES:
        return {}
    duration = value.get("durationSeconds")
    try:
        duration_seconds = max(0.0, float(duration or 0))
    except (TypeError, ValueError):
        duration_seconds = 0.0
    return {
        "mimeType": mime_type,
        "audioBytes": raw,
        "size": len(raw),
        "fileName": normalize_text(value.get("fileName"))[:120],
        "durationSeconds": round(duration_seconds, 1),
    }


def describe_voice_note_problem(value: Any) -> str:
    """Why a request that carried a voice note did not carry a readable one."""

    if not isinstance(value, dict):
        return "There is no voice note in this request."
    data_url = normalize_text(value.get("dataUrl"))
    mime_type = normalize_text(value.get("mimeType")).split(";")[0].lower()
    if data_url:
        match = _DATA_URL.match(data_url)
        mime_type = match.group("mime").lower() if match else ""
        if not match:
            return "The recording is not a base64 data URL."
    if mime_type not in VOICE_NOTE_MIME_TYPES:
        return f"Recordings in {mime_type or 'that format'} are not supported."
    return f"The recording is empty, unreadable, or larger than {VOICE_NOTE_MAX_BYTES // (1024 * 1024)} MB."


def transcribe_voice_note(
    note: dict[str, Any],
    *,
    billing_email: str,
    usage_recorder: Any | None = None,
    price_resolver: Any | None = None,
    language: str = "",
    source: str = "portal",
) -> str:
    """The words in a voice note, or a `VoiceNoteError` saying why there are none.

    The call is billed to the account like a model turn. Tracking is not
    strict here: a transcription model whose price is not yet in the table
    still answers, and the skipped charge shows in the log.
    """

    audio = bytes(note.get("audioBytes") or b"") if isinstance(note, dict) else b""
    if not audio:
        raise VoiceNoteError("There is no recording to transcribe.")
    model = resolve_transcription_model("OPENAI_TRANSCRIPTION_MODEL")
    try:
        result = call_openai_transcription(
            tool_name=TRANSCRIPTION_TOOL_NAME,
            tool_id="portal_agent",
            audio_bytes=audio,
            mime_type=normalize_text(note.get("mimeType")) or "audio/webm",
            file_name=normalize_text(note.get("fileName")),
            billing_email=billing_email,
            model=model,
            language=language,
            timeout_seconds=TRANSCRIPTION_TIMEOUT_SECONDS,
            usage_recorder=usage_recorder,
            price_resolver=price_resolver,
            config=load_openai_config(strict_tracking=False, include_prompt_in_metadata=False),
            metadata={
                "source": source,
                "audioBytes": len(audio),
                "durationSeconds": note.get("durationSeconds") or 0,
            },
        )
    except OpenAIError as exc:
        raise VoiceNoteError(exc.message) from exc
    text = normalize_text(result.text)
    if not text:
        raise VoiceNoteError("The recording had no words in it.")
    return text


def voice_note_transcript_text(text: str) -> str:
    """What the transcript keeps of a spoken message: its words, and that
    they were spoken. A later turn only needs to know it was a voice note."""

    clean = normalize_text(text)
    return f"{clean} {VOICE_NOTE_MARKER}".strip() if clean else VOICE_NOTE_MARKER


__all__ = [
    "TRANSCRIPTION_TOOL_NAME",
    "VOICE_NOTE_MARKER",
    "VOICE_NOTE_MAX_BYTES",
    "VOICE_NOTE_MAX_SECONDS",
    "VOICE_NOTE_MIME_TYPES",
    "VoiceNoteError",
    "describe_voice_note_problem",
    "normalize_voice_note",
    "normalize_voice_note_mime_type",
    "transcribe_voice_note",
    "voice_note_transcript_text",
]
