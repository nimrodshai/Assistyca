"""The first WhatsApp message to someone who registered on the web.

Assistyca speaks first here, before the person has ever written to us, so the
message may only go out as a template Meta has approved - and in the language
the person typed their name in, since nothing else is known about them yet
(message_language keeps the language from their first message on).

A business gets `assistyca_welcome1`, with their first name in {{1}} and a
fixed line in {{2}}, in English or in Hebrew:

    Hi {{1}} 👋 I'm Assistyca and I'm here to help.
    {{2}}
    Tap the action below, or just tell me what you need first.

A family gets `assistyca_welcome_family`, with their first name in {{1}} and
nothing else, in English or in Hebrew. One name, two languages, on Meta as
here: a new language is a translation added under the name, never a new name.

The earlier family templates (`_english_short`, `_hebrew_short`) are kept only
as the fallback while Meta reviews the new ones: the Hebrew one has a name
baked into its body and no variable at all, so a Hebrew-named family used to
get no welcome; now it gets the English one until the Hebrew translation is
approved, and the Hebrew one from then on with nothing to change here.

The bodies are repeated here as text so the conversation we keep says exactly
what their phone showed. They are copies of the approved templates, read in
WhatsApp Manager on 2026-10-13, which means the two can drift: if a template
is edited there, edit them here in the same breath.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from packages.infrastructure.message_language import LANGUAGE_ENGLISH
from packages.infrastructure.message_language import LANGUAGE_HEBREW
from packages.infrastructure.message_language import normalize_message_language
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.whatsapp_agent_chat import first_name
from packages.infrastructure.whatsapp_agent_chat import flatten_for_template


DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME = "assistyca_welcome1"
# "English" in WhatsApp Manager is `en`. `en_US` is a different template and
# sending it is how the first outside registration got no welcome at all.
DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE = LANGUAGE_ENGLISH
FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family"
# The approved English family welcome from before the name above existed:
# {{1}} only, like the new one. The fallback while Meta reviews the new pair.
LEGACY_FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family_english_short"
# A media header is supplied per message, never once at approval: Meta fetches
# this URL every time we send, so it has to be a public address of ours.
DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH = "/assets/assistyca-whatsapp-header-tagline.png"
# The waving robot Nimrod set on the family templates in WhatsApp Manager.
# Meta shows whatever we send, not what the template was approved with.
FAMILY_WELCOME_HEADER_IMAGE_PATH = "/assets/assistyca-whatsapp-header-family.jpg"

REGISTRATION_WELCOME_GREETING = "Hi {name} 👋 I'm Assistyca and I'm here to help."
REGISTRATION_WELCOME_CLOSING = "Tap the action below, or just tell me what you need first."
# {{2}}, word for word as Nimrod gave it, for every business.
REGISTRATION_WELCOME_LINE = (
    "Since you’re a software developer, you can tell me things like “what did I spend on "
    "software last month?”, “did the plumber ever send the invoice?”, or “summarise that "
    "long thread in three lines.”"
)
HEBREW_REGISTRATION_WELCOME_GREETING = "היי {name} 👋 אני אסיסטיקה ואני כאן כדי לעזור."
HEBREW_REGISTRATION_WELCOME_CLOSING = "לחצו על הכפתור למטה, או פשוט ספרו לי מה אתם צריכים."
HEBREW_REGISTRATION_WELCOME_LINE = (
    "מאחר שאתם מפתחי תוכנה, אפשר לשאול אותי דברים כמו ״כמה הוצאתי על תוכנה בחודש שעבר?״, "
    "״האינסטלטור שלח בסוף חשבונית?״ או ״תסכם לי את השרשור הארוך הזה בשלוש שורות.״"
)

# The family welcomes: the greeting with the name, then the body as it is on
# Meta. The footer ("Didn't register at assistyca.com? Just ignore this
# message.") is the template's own and is not part of the words we keep.
FAMILY_WELCOME_GREETING = "Hi {name} 👋"
FAMILY_WELCOME_BODY = (
    "I'm your new assistant and I'm here to help.\n"
    "First, let's get to know your family. Can you tell me the names of your kids and partner? "
    "Tell me so we could start working on your weekly schedule."
)
HEBREW_FAMILY_WELCOME_GREETING = "היי {name} 👋"
HEBREW_FAMILY_WELCOME_BODY = (
    "אני העוזר החדש שלך!\n"
    "דבר ראשון, אני אשמח להכיר את המשפחה. מה השמות של כולם? לאחר מכן נוכל להתחיל לעבוד על הלו״ז השבועי של כולם."
)

HEBREW_LETTER = re.compile(r"[א-ת]")


def is_hebrew_name(name: Any) -> bool:
    """A name with any Hebrew letter in it was typed in Hebrew."""

    return bool(HEBREW_LETTER.search(normalize_text(name)))


def is_family(kind: Any) -> bool:
    return normalize_text(kind).lower() == "family"


def welcome_language(name: Any) -> str:
    """The language of the welcome: Hebrew for a name typed in Hebrew,
    English for anything else - a name in Cyrillic or Arabic too, since
    those are the two languages the templates exist in."""

    return LANGUAGE_HEBREW if is_hebrew_name(name) else LANGUAGE_ENGLISH


def greeted_name(*, kind: Any = "business", name: Any = "") -> str:
    # A Hebrew name is never empty, so "there" only ever lands in English.
    return first_name(name) or "there"


def build_registration_welcome_message(*, name: Any, kind: Any = "business", language: Any = None) -> str:
    """The welcome as their phone will show it, for the conversation we keep."""

    resolved_language = normalize_message_language(language) or welcome_language(name)
    hebrew = resolved_language == LANGUAGE_HEBREW
    shown_name = greeted_name(kind=kind, name=name)
    if is_family(kind):
        greeting = (HEBREW_FAMILY_WELCOME_GREETING if hebrew else FAMILY_WELCOME_GREETING).format(name=shown_name)
        return f"{greeting}\n{HEBREW_FAMILY_WELCOME_BODY if hebrew else FAMILY_WELCOME_BODY}"
    greeting = (HEBREW_REGISTRATION_WELCOME_GREETING if hebrew else REGISTRATION_WELCOME_GREETING).format(name=shown_name)
    line = HEBREW_REGISTRATION_WELCOME_LINE if hebrew else REGISTRATION_WELCOME_LINE
    closing = HEBREW_REGISTRATION_WELCOME_CLOSING if hebrew else REGISTRATION_WELCOME_CLOSING
    return f"{greeting}\n{line}\n{closing}"


def registration_welcome_template_parameters(*, name: Any, kind: Any = "business", language: Any = None) -> list[str]:
    """{{1}} and, for a business, {{2}}, in that order.

    A count Meta does not expect is refused whole ("(#132000) Number of
    parameters does not match the expected number of params", 2026-09-23),
    and a blank variable too ("(#131008) Required parameter is missing",
    2026-09-24). The counts here are the templates' as read on Meta: the
    business welcome takes two, every family welcome one.
    """

    resolved_language = normalize_message_language(language) or welcome_language(name)
    shown_name = greeted_name(kind=kind, name=name)
    if is_family(kind):
        return [shown_name]
    line = HEBREW_REGISTRATION_WELCOME_LINE if resolved_language == LANGUAGE_HEBREW else REGISTRATION_WELCOME_LINE
    return [shown_name, flatten_for_template(line)]


@dataclass(frozen=True)
class RegistrationWelcomeTemplate:
    """One approved template that can carry the welcome: its name and
    language, the picture on top of it, the variables to fill, and the
    message it puts on their phone."""

    name: str = DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME
    language: str = DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE
    header_image_url: str = ""
    parameters: tuple[str, ...] = ()
    message: str = ""


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


def registration_welcome_plan(
    *, base_url: str = "", kind: Any = "business", name: Any = ""
) -> list[RegistrationWelcomeTemplate]:
    """The templates to try for this registrant, the wanted one first.

    The wanted one is the welcome of their kind in the language of their name.
    Behind it stand the ones Meta approved earlier, for as long as it is still
    reviewing the new: the English business welcome behind the Hebrew one,
    the earlier English family welcome behind both family ones. A send that
    Meta refuses moves on to the next, so the words change but the welcome
    arrives; once the new ones are approved the first send takes and the rest
    are never tried.

    The environment overrides only the business welcome, and names one
    template alone - whoever set it knows what it takes.

    The header image is our own asset, so the address follows the site rather
    than being typed into the environment twice; an explicit URL still wins,
    which is what a locally run portal needs - Meta cannot fetch a picture
    from a laptop.
    """

    site = normalize_text(base_url).rstrip("/")
    public = is_publicly_fetchable(site)
    language = welcome_language(name)

    def entry(template_name: str, template_language: str, header_image_url: str) -> RegistrationWelcomeTemplate:
        return RegistrationWelcomeTemplate(
            name=template_name,
            language=template_language,
            header_image_url=header_image_url,
            parameters=tuple(registration_welcome_template_parameters(name=name, kind=kind, language=template_language)),
            message=build_registration_welcome_message(name=name, kind=kind, language=template_language),
        )

    if is_family(kind):
        header = f"{site}{FAMILY_WELCOME_HEADER_IMAGE_PATH}" if public else ""
        return [
            entry(FAMILY_WELCOME_TEMPLATE_NAME, language, header),
            entry(LEGACY_FAMILY_WELCOME_TEMPLATE_NAME, LANGUAGE_ENGLISH, header),
        ]
    header = normalize_text(os.getenv("WHATSAPP_REGISTRATION_WELCOME_HEADER_IMAGE_URL"))
    if not header:
        header = f"{site}{DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH}" if public else ""
    configured_name = normalize_text(os.getenv("WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_NAME"))
    if configured_name:
        configured_language = (
            normalize_text(os.getenv("WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE"))
            or DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE
        )
        return [entry(configured_name, configured_language, header)]
    plan = [entry(DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME, language, header)]
    if language != LANGUAGE_ENGLISH:
        plan.append(entry(DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME, LANGUAGE_ENGLISH, header))
    return plan


def resolve_registration_welcome_template(
    *, base_url: str = "", kind: Any = "business", name: Any = ""
) -> RegistrationWelcomeTemplate:
    """The template the welcome is meant to go on: the first of the plan."""

    return registration_welcome_plan(base_url=base_url, kind=kind, name=name)[0]


__all__ = [
    "DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH",
    "DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE",
    "DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME",
    "FAMILY_WELCOME_BODY",
    "FAMILY_WELCOME_HEADER_IMAGE_PATH",
    "FAMILY_WELCOME_TEMPLATE_NAME",
    "HEBREW_FAMILY_WELCOME_BODY",
    "HEBREW_REGISTRATION_WELCOME_LINE",
    "LEGACY_FAMILY_WELCOME_TEMPLATE_NAME",
    "REGISTRATION_WELCOME_CLOSING",
    "REGISTRATION_WELCOME_GREETING",
    "REGISTRATION_WELCOME_LINE",
    "RegistrationWelcomeTemplate",
    "build_registration_welcome_message",
    "is_hebrew_name",
    "is_publicly_fetchable",
    "registration_welcome_plan",
    "registration_welcome_template_parameters",
    "resolve_registration_welcome_template",
    "welcome_language",
]
