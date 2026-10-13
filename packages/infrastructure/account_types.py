"""Which features the assistant may use, for every account at once.

Every account is a family's, so there is one set of switches. The house can
switch a feature off, and from then on the assistant does not use it and the
background jobs behind it (inbox watch, mailbox findings) leave everyone
alone. What an account already holds - saved receipts, lists, tasks already
scheduled - stays where it is.

Everything is allowed until someone switches it off. A row is written only
for a switch that was moved, so a feature added here next month starts on
for everyone without a migration.

Some things are never in the grid: connecting and disconnecting a source,
signing out, deleting the account, and forgetting or cancelling something
already set up. Giving something back is never a feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccountFeature:
    feature_id: str
    label: str
    description: str
    # The assistant's tools this feature is. Switched off, they are marked
    # unavailable to the model and refused if it calls them anyway.
    tools: tuple[str, ...] = ()


ACCOUNT_FEATURES: tuple[AccountFeature, ...] = (
    AccountFeature(
        "mail",
        "Mail",
        "Reading the connected mailboxes and sending email from Gmail.",
        ("read_inbox", "send_email"),
    ),
    AccountFeature(
        "calendar",
        "Calendar",
        "Reading the calendar, choosing which calendars count, adding and changing meetings.",
        ("read_calendar", "choose_calendars", "create_calendar_event", "update_calendar_event"),
    ),
    AccountFeature(
        "receipts",
        "Receipts",
        "Finding receipts in the mail and opening the receipts page.",
        ("search_receipts", "open_receipts"),
    ),
    AccountFeature(
        "insurance",
        "Insurance",
        "Saving policies and checking expenses against them for a possible claim.",
        ("save_insurance_policy", "show_insurance_policies", "check_insurance_expense"),
    ),
    AccountFeature(
        "lists",
        "Lists",
        "Shopping lists and to-dos, in the chat and on the lists page.",
        ("create_list", "update_list", "show_lists"),
    ),
    AccountFeature(
        "reminders",
        "Reminders",
        "One-off messages at a time the person names.",
        ("schedule_message",),
    ),
    AccountFeature(
        "standing_actions",
        "Recurring tasks",
        "Tasks the assistant runs by itself on a schedule.",
        ("schedule_task",),
    ),
    AccountFeature(
        "web_search",
        "Web search",
        "Finding things on the web: hotels, concerts, events, restaurants, prices, opening hours.",
        ("search_web",),
    ),
    AccountFeature(
        "news_search",
        "News",
        "The latest news and dated updates on a topic, asked for or every day.",
        ("search_news",),
    ),
    AccountFeature(
        "public_records",
        "Property records",
        "Israeli public records for an address or parcel: gush and helka, the plans covering it, and ordering a Tabu extract.",
        ("look_up_property",),
    ),
    AccountFeature(
        "mailbox_findings",
        "Mailbox findings",
        "Reading a newly connected mailbox unasked and reporting what stands out, then a daily digest.",
        ("show_findings",),
    ),
    AccountFeature(
        "family_week",
        "Family and week",
        "Keeping the family members and their weekly activities, and laying out who is on each drop-off and pickup.",
        ("save_family_member", "save_week_activity", "show_family_week", "set_getting_to_know", "start_birthday_list"),
    ),
    AccountFeature(
        "inbox_watch",
        "Inbox watch",
        "Watching new mail and alerting on WhatsApp about school dates, appointments and replies due, and following an email conversation until it is answered.",
    ),
    AccountFeature(
        "voice_notes",
        "Voice notes",
        "Turning a recorded message into text, in the portal and on WhatsApp.",
    ),
    AccountFeature(
        "group_chat",
        "Group chat",
        "Opening a WhatsApp group the assistant is in, and handing over the link to share with the others.",
        ("create_group_chat",),
    ),
)
ACCOUNT_FEATURES_BY_ID = {feature.feature_id: feature for feature in ACCOUNT_FEATURES}

# Shown on the page as always on, so nobody wonders where they went.
ALWAYS_ON_ABILITIES: tuple[dict[str, str], ...] = (
    {"label": "Connecting and disconnecting sources", "description": "Adding an account, and removing one."},
    {"label": "Signing out and deleting the account", "description": "Leaving is never switched off."},
    {"label": "Remembering and forgetting facts", "description": "What the person told the assistant about themselves."},
    {"label": "Seeing and cancelling what is scheduled", "description": "Anything already set up can be stopped."},
    {"label": "Dismissing findings and archiving policies", "description": "Putting something away stays possible."},
    {"label": "Removing a family member or a weekly activity", "description": "What was kept can be taken out."},
)


def feature_allowed(switches: dict[str, bool] | None, feature_id: str) -> bool:
    """switches is {feature_id: allowed}; anything missing is allowed."""

    return bool((switches or {}).get(feature_id, True))


def blocked_tools(switches: dict[str, bool] | None) -> dict[str, str]:
    """{tool name: feature label} for every tool that is switched off."""

    blocked: dict[str, str] = {}
    for feature in ACCOUNT_FEATURES:
        if not feature_allowed(switches, feature.feature_id):
            for tool in feature.tools:
                blocked[tool] = feature.label
    return blocked


def account_feature_allowed(database: Any, *, feature_id: str) -> bool:
    """For a caller holding only the store. A store that cannot answer (an
    older one, a test double) leaves the feature on: a missing switch never
    takes something away."""

    try:
        switches = database.get_feature_switches()
    except Exception:  # noqa: BLE001 - a store that cannot answer leaves the feature on
        return True
    return feature_allowed(switches, feature_id)


def describe_features(
    switches: dict[str, bool] | None,
    available_tools: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """The admin page's list. A feature whose tools this build does not have
    yet is left out, so a switch never appears for something that is not there."""

    features = [
        feature for feature in ACCOUNT_FEATURES
        if available_tools is None or not feature.tools or any(tool in available_tools for tool in feature.tools)
    ]

    return {
        "features": [
            {
                "featureId": feature.feature_id,
                "label": feature.label,
                "description": feature.description,
                "allowed": feature_allowed(switches, feature.feature_id),
            }
            for feature in features
        ],
        "alwaysOn": list(ALWAYS_ON_ABILITIES),
    }


__all__ = [
    "ACCOUNT_FEATURES",
    "ACCOUNT_FEATURES_BY_ID",
    "ALWAYS_ON_ABILITIES",
    "account_feature_allowed",
    "blocked_tools",
    "describe_features",
    "feature_allowed",
]
