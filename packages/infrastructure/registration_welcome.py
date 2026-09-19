"""The first WhatsApp message to someone who registered on the web.

Assistyca speaks first here, before the person has ever written to us, so the
message may only go out as a template Meta has approved. A business gets
`assistyca_welcome1`, with their first name in {{1}} and a fixed line in {{2}}:

    Hi {{1}} 👋 I'm Assistyca and I'm here to help.
    {{2}}
    Tap the action below, or just tell me what you need first.

A family gets a family welcome instead, and the one in their language: a name
typed in Hebrew gets `assistyca_welcome_family_1_hebrew`, any other name
`assistyca_welcome_family_1`. Same two variables, a family line in {{2}}.

The greeting and the closing are repeated here as text so the conversation we
keep says exactly what their phone showed. They are a copy of the approved
template, which means the two can drift: if the template is edited in
WhatsApp Manager, edit them here in the same breath.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.whatsapp_agent_chat import first_name
from packages.infrastructure.whatsapp_agent_chat import flatten_for_template


DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME = "assistyca_welcome1"
# "English" in WhatsApp Manager is `en`. `en_US` is a different template and
# sending it is how the first outside registration got no welcome at all.
DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE = "en"
# A media header is supplied per message, never once at approval: Meta fetches
# this URL every time we send, so it has to be a public address of ours.
DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH = "/assets/assistyca-whatsapp-header-tagline.png"

REGISTRATION_WELCOME_GREETING = "Hi {name} 👋 I'm Assistyca and I'm here to help."
REGISTRATION_WELCOME_CLOSING = "Tap the action below, or just tell me what you need first."

# {{2}}, word for word as Nimrod gave it, for every business.
REGISTRATION_WELCOME_LINE = (
    "Since you\u2019re a software developer, you can tell me things like \u201cwhat did I spend on "
    "software last month?\u201d, \u201cdid the plumber ever send the invoice?\u201d, or \u201csummarise that "
    "long thread in three lines.\u201d"
)


# The family welcomes. {{2}} is word for word as Nimrod gave it; the greeting
# and closing are copies of the approved bodies, kept in step by hand.
FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family_1"
FAMILY_WELCOME_GREETING = "Hi {name} 👋 I'm your new assistant and I'm here to take a few things off your plate."
FAMILY_WELCOME_CLOSING = (
    "But first, let's get to know the names in your family. Tell me, and we'll start working on "
    "your weekly schedule."
)
FAMILY_WELCOME_LINE = (
    'No more "Did you remember to take Noah to soccer?". I\'ll keep track of who\'s '
    "taking who, and remind them in time."
)

HEBREW_FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family_1_hebrew"
HEBREW_FAMILY_WELCOME_TEMPLATE_LANGUAGE = "he"
HEBREW_FAMILY_WELCOME_GREETING = "היי {name} 👋 אני אסיסטיקה, ואני כאן כדי להקל על השבוע שלך."
HEBREW_FAMILY_WELCOME_CLOSING = "אבל קודם, נכיר את המשפחה: מה השמות של כולם? ספרו לי ונתחיל לעבוד על הלו״ז השבועי."
HEBREW_FAMILY_WELCOME_LINE = (
    'בואו נשים סוף להודעות כמו "זכרת לקחת את יוני לכדורגל?". אני אעקוב מי לוקח את מי, '
    "ואזכיר להם בזמן."
)

HEBREW_LETTER = re.compile(r"[\u05d0-\u05ea]")


def is_hebrew_name(name: Any) -> bool:
    """A name with any Hebrew letter in it was typed in Hebrew."""

    return bool(HEBREW_LETTER.search(normalize_text(name)))


def is_family(kind: Any) -> bool:
    return normalize_text(kind).lower() == "family"


def welcome_copy(*, kind: Any, name: Any) -> tuple[str, str, str]:
    """The greeting, the {{2}} line and the closing of the welcome they get."""

    if not is_family(kind):
        return REGISTRATION_WELCOME_GREETING, REGISTRATION_WELCOME_LINE, REGISTRATION_WELCOME_CLOSING
    if is_hebrew_name(name):
        return HEBREW_FAMILY_WELCOME_GREETING, HEBREW_FAMILY_WELCOME_LINE, HEBREW_FAMILY_WELCOME_CLOSING
    return FAMILY_WELCOME_GREETING, FAMILY_WELCOME_LINE, FAMILY_WELCOME_CLOSING


def greeted_name(*, kind: Any, name: Any) -> str:
    # A Hebrew name is never empty, so "there" only ever lands in English.
    return first_name(name) or "there"


@dataclass(frozen=True)
class RegistrationWelcomeTemplate:
    """Which approved template carries the welcome, and the image on top of it."""

    name: str = DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME
    language: str = DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE
    header_image_url: str = ""


# Addresses only this machine can reach: Meta fetches the picture from the
# open internet, and an image it cannot fetch fails the whole message, not
# just the header. A portal run on a laptop sends the welcome without it.
PRIVATE_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def is_publicly_fetchable(url: str) -> bool:
    site = normalize_text(url).lower()
    if not site.startswith("https://"):
        return False
    host = site[len("https://"):].split("/")[0].split(":")[0]
    return bool(host) and host not in PRIVATE_HOSTS and not host.endswith(".local")


def resolve_registration_welcome_template(
    *, base_url: str = "", kind: Any = "business", name: Any = ""
) -> RegistrationWelcomeTemplate:
    """The template for this registrant, as configured or as approved.

    A family's template is chosen by the language of the name they typed; the
    environment overrides only the business welcome.

    The header image is our own asset, so the address follows the site rather
    than being typed into the environment twice; an explicit URL still wins,
    which is what a locally run portal needs - Meta cannot fetch a picture
    from a laptop.
    """

    header_image_url = normalize_text(os.getenv("WHATSAPP_REGISTRATION_WELCOME_HEADER_IMAGE_URL"))
    if not header_image_url:
        site = normalize_text(base_url).rstrip("/")
        header_image_url = (
            f"{site}{DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH}" if is_publicly_fetchable(site) else ""
        )
    if is_family(kind):
        hebrew = is_hebrew_name(name)
        return RegistrationWelcomeTemplate(
            name=HEBREW_FAMILY_WELCOME_TEMPLATE_NAME if hebrew else FAMILY_WELCOME_TEMPLATE_NAME,
            language=HEBREW_FAMILY_WELCOME_TEMPLATE_LANGUAGE if hebrew else DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE,
            header_image_url=header_image_url,
        )
    return RegistrationWelcomeTemplate(
        name=(
            normalize_text(os.getenv("WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_NAME"))
            or DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME
        ),
        language=(
            normalize_text(os.getenv("WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE"))
            or DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE
        ),
        header_image_url=header_image_url,
    )


def build_registration_welcome_message(*, name: Any, kind: Any = "business") -> str:
    """The welcome as their phone will show it, for the conversation we keep."""

    greeting, line, closing = welcome_copy(kind=kind, name=name)
    greeting = greeting.format(name=greeted_name(kind=kind, name=name))
    if is_family(kind):
        return f"{greeting}\n\n{line}\n\n{closing}"
    return f"{greeting}\n{line}\n{closing}"


def registration_welcome_template_parameters(*, name: Any, kind: Any = "business") -> list[str]:
    """{{1}} and {{2}}, in that order."""

    _, line, _ = welcome_copy(kind=kind, name=name)
    return [greeted_name(kind=kind, name=name), flatten_for_template(line)]


__all__ = [
    "FAMILY_WELCOME_LINE",
    "FAMILY_WELCOME_TEMPLATE_NAME",
    "HEBREW_FAMILY_WELCOME_LINE",
    "HEBREW_FAMILY_WELCOME_TEMPLATE_NAME",
    "DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH",
    "DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE",
    "DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME",
    "REGISTRATION_WELCOME_CLOSING",
    "REGISTRATION_WELCOME_GREETING",
    "REGISTRATION_WELCOME_LINE",
    "RegistrationWelcomeTemplate",
    "build_registration_welcome_message",
    "is_hebrew_name",
    "is_publicly_fetchable",
    "registration_welcome_template_parameters",
    "resolve_registration_welcome_template",
]
