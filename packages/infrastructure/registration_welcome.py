"""The first WhatsApp message to someone who registered on the web.

Assistyca speaks first here, before the person has ever written to us, so the
message may only go out as a template Meta has approved - and in the language
the person typed their name in, since nothing else is known about them yet
(message_language keeps the language from their first message on).

The welcome is `assistyca_welcome_family_hello`, with their first name in
{{1}} and nothing else, in English or in Hebrew, and no picture on top. One
name, two languages, on Meta as here: a new language is a translation added
under the name, never a new name. It was submitted as Utility on 2026-10-15:
the earlier welcomes were moved to Marketing by Meta, and Meta stops
marketing templates to people who never wrote to us (131049).

The earlier family templates (`assistyca_welcome_family`, then the English
`_english_short`) stand behind it while Meta reviews it: a template still
under review is refused whole, and an older welcome is better than none.
Once it is approved the first send takes and the fallbacks are never tried.

The bodies are repeated here as text so the conversation we keep says exactly
what their phone showed. They are copies of the approved templates, read in
WhatsApp Manager on 2026-10-13, which means the two can drift: if a template
is edited there, edit them here in the same breath.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from packages.infrastructure.message_language import LANGUAGE_ENGLISH
from packages.infrastructure.message_language import LANGUAGE_HEBREW
from packages.infrastructure.message_language import normalize_message_language
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.whatsapp_agent_chat import first_name


FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family_hello"
# The approved Marketing welcome, with the picture on top: the first fallback.
MARKETING_FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family"
# The approved English family welcome from before the name above existed:
# {{1}} only, like the new one. The fallback while Meta reviews the new pair.
LEGACY_FAMILY_WELCOME_TEMPLATE_NAME = "assistyca_welcome_family_english_short"
# A media header is supplied per message, never once at approval: Meta fetches
# this URL every time we send, so it has to be a public address of ours. The
# waving robot Nimrod set on the family templates in WhatsApp Manager; Meta
# shows whatever we send, not what the template was approved with.
FAMILY_WELCOME_HEADER_IMAGE_PATH = "/assets/assistyca-whatsapp-header-family.jpg"

# The welcome as submitted on 2026-10-15, with the name in it.
FAMILY_HELLO = (
    "Hi {name}, it's Assistyca 👋 You're all signed up, and I'm really glad you're here.\n\n"
    "To build your family's weekly schedule, I'd like to get to know everyone first. "
    "Who lives at home with you? Names and the kids' ages are plenty."
)
HEBREW_FAMILY_HELLO = (
    "היי {name}, כאן Assistyca 👋 ההרשמה הושלמה, וטוב שהגעת.\n\n"
    "כדי לבנות את הלו״ז השבועי של המשפחה, אשמח להכיר קודם את כולם. מי גר איתך בבית? מספיק שמות וגילאי הילדים."
)

# The earlier family welcomes: the greeting with the name, then the body as
# it is on Meta. The footer ("Didn't register at assistyca.com? Just ignore
# this message.") is the template's own and is not part of the words we keep.
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


def welcome_language(name: Any) -> str:
    """The language of the welcome: Hebrew for a name typed in Hebrew,
    English for anything else - a name in Cyrillic or Arabic too, since
    those are the two languages the templates exist in."""

    return LANGUAGE_HEBREW if is_hebrew_name(name) else LANGUAGE_ENGLISH


def greeted_name(name: Any = "") -> str:
    # A Hebrew name is never empty, so "there" only ever lands in English.
    return first_name(name) or "there"


def build_registration_welcome_message(
    *, name: Any, language: Any = None, template_name: str = FAMILY_WELCOME_TEMPLATE_NAME,
) -> str:
    """The welcome as their phone will show it, for the conversation we keep:
    the words of whichever template carried it."""

    resolved_language = normalize_message_language(language) or welcome_language(name)
    hebrew = resolved_language == LANGUAGE_HEBREW
    shown_name = greeted_name(name)
    if template_name == FAMILY_WELCOME_TEMPLATE_NAME:
        return (HEBREW_FAMILY_HELLO if hebrew else FAMILY_HELLO).format(name=shown_name)
    greeting = (HEBREW_FAMILY_WELCOME_GREETING if hebrew else FAMILY_WELCOME_GREETING).format(name=shown_name)
    return f"{greeting}\n{HEBREW_FAMILY_WELCOME_BODY if hebrew else FAMILY_WELCOME_BODY}"


def registration_welcome_template_parameters(*, name: Any, language: Any = None) -> list[str]:
    """{{1}}, and nothing else.

    A count Meta does not expect is refused whole ("(#132000) Number of
    parameters does not match the expected number of params", 2026-09-23),
    and a blank variable too ("(#131008) Required parameter is missing",
    2026-09-24). Every family welcome takes one variable, as read on Meta.
    """

    return [greeted_name(name)]


@dataclass(frozen=True)
class RegistrationWelcomeTemplate:
    """One approved template that can carry the welcome: its name and
    language, the picture on top of it, the variables to fill, and the
    message it puts on their phone."""

    name: str = FAMILY_WELCOME_TEMPLATE_NAME
    language: str = LANGUAGE_ENGLISH
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


def registration_welcome_plan(*, base_url: str = "", name: Any = "") -> list[RegistrationWelcomeTemplate]:
    """The templates to try for this registrant, the wanted one first.

    The wanted one is the welcome in the language of their name. Behind it
    stands the one Meta approved earlier, for as long as it is still
    reviewing the new. A send that Meta refuses moves on to the next, so the
    words change but the welcome arrives.

    The header image is our own asset, so the address follows the site rather
    than being typed into the environment; a locally run portal sends without
    it, because Meta cannot fetch a picture from a laptop.
    """

    site = normalize_text(base_url).rstrip("/")
    header = f"{site}{FAMILY_WELCOME_HEADER_IMAGE_PATH}" if is_publicly_fetchable(site) else ""
    language = welcome_language(name)

    def entry(template_name: str, template_language: str, *, picture: bool = True) -> RegistrationWelcomeTemplate:
        return RegistrationWelcomeTemplate(
            name=template_name,
            language=template_language,
            # A picture sent to a template made without one is refused.
            header_image_url=header if picture else "",
            parameters=tuple(registration_welcome_template_parameters(name=name, language=template_language)),
            message=build_registration_welcome_message(name=name, language=template_language, template_name=template_name),
        )

    return [
        entry(FAMILY_WELCOME_TEMPLATE_NAME, language, picture=False),
        entry(MARKETING_FAMILY_WELCOME_TEMPLATE_NAME, language),
        entry(LEGACY_FAMILY_WELCOME_TEMPLATE_NAME, LANGUAGE_ENGLISH),
    ]


def resolve_registration_welcome_template(*, base_url: str = "", name: Any = "") -> RegistrationWelcomeTemplate:
    """The template the welcome is meant to go on: the first of the plan."""

    return registration_welcome_plan(base_url=base_url, name=name)[0]


__all__ = [
    "FAMILY_WELCOME_BODY",
    "FAMILY_WELCOME_HEADER_IMAGE_PATH",
    "FAMILY_WELCOME_TEMPLATE_NAME",
    "HEBREW_FAMILY_WELCOME_BODY",
    "FAMILY_HELLO",
    "HEBREW_FAMILY_HELLO",
    "LEGACY_FAMILY_WELCOME_TEMPLATE_NAME",
    "MARKETING_FAMILY_WELCOME_TEMPLATE_NAME",
    "RegistrationWelcomeTemplate",
    "build_registration_welcome_message",
    "is_hebrew_name",
    "is_publicly_fetchable",
    "registration_welcome_plan",
    "registration_welcome_template_parameters",
    "resolve_registration_welcome_template",
    "welcome_language",
]
