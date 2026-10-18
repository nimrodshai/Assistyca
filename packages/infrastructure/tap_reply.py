"""The line that answers a tap on "remind me again".

The tap under a ride word asks for one more word five minutes before
(remind_again). Code does the work - queues the word, or finds it queued
already, or finds the drive too close for a second word - and knows the
time. What the person reads back is written by the model from those facts,
in their language and the gender they use for themselves, the way the rest
of the chat talks; the assembled sentence here stands in when it cannot be
written, and whenever what was written is not a plain acknowledgement: one
line, with the time in it, no question, no link.

Shared by the WhatsApp chat, which builds the facts, and the server route
that writes the line, so the words come from one place.
"""

from __future__ import annotations

import json
import re
from typing import Any

from packages.infrastructure.assistant_voice import ASSISTANT_VOICE
from packages.infrastructure.task_complexity import TaskComplexity

# A short acknowledgement in fixed shape: constrained drafting.
TAP_REPLY_COMPLEXITY = TaskComplexity.MEDIUM
TAP_REPLY_MAX_LENGTH = 140
TAP_REPLY_MAX_OUTPUT_TOKENS = 600
TAP_REPLY_OUTCOMES = ("scheduled", "already", "imminent")
_FORBIDDEN_WORDS = ("openai", "gpt", "llm", "api", "endpoint", "json", "server", "queued", "queue")
_URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)

TAP_REPLY_INSTRUCTIONS = (
    f"{ASSISTANT_VOICE} "
    "You are Assistyca, the assistant for this family, writing one short WhatsApp line. The person just "
    "tapped the button under a ride reminder asking for one more word five minutes before. When outcome "
    "is scheduled it is already set: code queued it for clock. Acknowledge in one short line, the way a "
    "person would - a word and the time, and the child or place if it helps them know which drive. Don't "
    "explain, don't thank, don't ask anything, don't offer anything else. If outcome is already, say it is "
    "already set, without fuss. If outcome is imminent, the drive at clock is only minutes away, so there "
    "is no second word to set: say it is time to head out, with the time. Write it in their language and "
    "the address form given, plain text, one line, and keep clock exactly as written."
)


def tap_reply_fallback(outcome: str, clock: str, language: str) -> str:
    """The assembled line, for when no model can write one."""

    hebrew = language == "he"
    if outcome == "imminent":
        return f"זה כבר ב-{clock} - הגיע הזמן לצאת." if hebrew else f"It's at {clock} - time to head out."
    if outcome == "already":
        return f"כבר מסודר, אזכיר ב-{clock}." if hebrew else f"Already set - I'll remind you at {clock}."
    return f"סגור, אזכיר שוב ב-{clock}." if hebrew else f"Got it - I'll remind you again at {clock}."


def build_tap_reply_prompt(
    *,
    outcome: str,
    clock: str,
    drive_at: str = "",
    about: str = "",
    language: str = "",
    address_form: str = "",
    conversation: list[dict[str, str]] | None = None,
) -> str:
    """The report the line is written from: everything here is something code knows."""

    context = {
        "outcome": outcome,
        "clock": clock,
        "driveAt": drive_at,
        "about": " ".join(str(about or "").split())[:200],
        "language": language or "the language of recentConversation",
        "addressAs": address_form or "not known: wording that reads the same for a man and a woman",
        "recentConversation": [
            {"role": str(item.get("role") or ""), "text": " ".join(str(item.get("text") or "").split())[:300]}
            for item in (conversation or [])[-4:]
            if isinstance(item, dict)
        ],
    }
    return (
        "Write the line for CONTEXT.\n"
        "clock is when the second word goes (for imminent, when the drive is), in their local time; driveAt is "
        "the drive itself. about is the drive in a few words, there so you can name the child or the place "
        "when that helps. Read recentConversation so the line follows on from it.\n\n"
        f"CONTEXT\n{json.dumps(context, ensure_ascii=False)}"
    )


def guard_tap_reply(text: Any, *, clock: str, fallback: str) -> str:
    """Keep the written line only when it is still a plain acknowledgement:
    one line of at most 140 characters, the exact time in it, no question,
    no link and no word about the machinery. Anything else falls back."""

    line = str(text or "").strip()
    if not line or "\n" in line or len(line) > TAP_REPLY_MAX_LENGTH:
        return fallback
    if clock and clock not in line:
        return fallback
    if "?" in line or _URL_PATTERN.search(line):
        return fallback
    lowered = line.lower()
    if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _FORBIDDEN_WORDS):
        return fallback
    return line


__all__ = [
    "TAP_REPLY_COMPLEXITY",
    "TAP_REPLY_INSTRUCTIONS",
    "TAP_REPLY_MAX_LENGTH",
    "TAP_REPLY_MAX_OUTPUT_TOKENS",
    "TAP_REPLY_OUTCOMES",
    "build_tap_reply_prompt",
    "guard_tap_reply",
    "tap_reply_fallback",
]
