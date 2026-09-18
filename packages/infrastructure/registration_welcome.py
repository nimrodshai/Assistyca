"""The first WhatsApp message to someone who registered on the web.

Assistyca speaks first here, before the person has ever written to us, so the
message may only go out as a template Meta has approved. `assistyca_welcome1`
is the only welcome we have, so every registration - business or family -
gets it, with their first name in {{1}} and a fixed line in {{2}}:

    Hi {{1}} 👋 I'm Assistyca and I'm here to help.
    {{2}}
    Tap the action below, or just tell me what you need first.

The greeting and the closing are repeated here as text so the conversation we
keep says exactly what their phone showed. They are a copy of the approved
template, which means the two can drift: if the template is edited in
WhatsApp Manager, edit them here in the same breath.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
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

# {{2}}, word for word as Nimrod gave it, for every registrant.
REGISTRATION_WELCOME_LINE = (
    "Since you\u2019re a software developer, you can tell me things like \u201cwhat did I spend on "
    "software last month?\u201d, \u201cdid the plumber ever send the invoice?\u201d, or \u201csummarise that "
    "long thread in three lines.\u201d"
)


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


def resolve_registration_welcome_template(*, base_url: str = "") -> RegistrationWelcomeTemplate:
    """The template as configured, falling back to the one we had approved.

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


def build_registration_welcome_message(*, name: Any, line: str = REGISTRATION_WELCOME_LINE) -> str:
    """The welcome as their phone will show it, for the conversation we keep."""

    greeting = REGISTRATION_WELCOME_GREETING.format(name=first_name(name) or "there")
    return f"{greeting}\n{line}\n{REGISTRATION_WELCOME_CLOSING}"


def registration_welcome_template_parameters(*, name: Any, line: str = REGISTRATION_WELCOME_LINE) -> list[str]:
    """{{1}} and {{2}}, in that order."""

    return [first_name(name) or "there", flatten_for_template(line)]


__all__ = [
    "DEFAULT_REGISTRATION_WELCOME_HEADER_IMAGE_PATH",
    "DEFAULT_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE",
    "DEFAULT_REGISTRATION_WELCOME_TEMPLATE_NAME",
    "REGISTRATION_WELCOME_CLOSING",
    "REGISTRATION_WELCOME_GREETING",
    "REGISTRATION_WELCOME_LINE",
    "RegistrationWelcomeTemplate",
    "build_registration_welcome_message",
    "is_publicly_fetchable",
    "registration_welcome_template_parameters",
    "resolve_registration_welcome_template",
]
