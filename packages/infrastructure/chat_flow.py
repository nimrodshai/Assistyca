"""What the opening of the conversation is for, per kind of account.

An account registers as a business or as a family, and the two want
different things from their first days here.

A business gets little out of the assistant until its mail and its calendar
are connected: the invoices, the receipts to chase, the replies due, the
meetings and the free hours all live in there. So until both are in, every
conversation carries one offer to connect what is missing - once, worded as
the thing it would let the assistant do for them, and dropped the moment
they say not now.

A family is the other way round. Nothing they came for is in a mailbox: it
is who is at home, when each child comes back, who drives to ballet on
Tuesday and who is collecting. That is asked for and kept here, in the
conversation, never read out of a calendar, and the asking goes on until the
week is whole - code works out what is still missing rather than leaving the
assistant to decide it has heard enough. Only once the week is in does the
assistant suggest connecting a calendar and a mailbox, as the extra they
are for a family, and nothing they have is ever held back until they do.

Where each of those stands is kept on the account, so someone who said not
now is not asked again the next morning, and a family whose week is already
in is never taken back to the beginning.

Nothing here touches the database or the network: the caller hands in the
account's kind, its profile row and what is connected, and gets back the
block the assistant reads and the rules that go with it.
"""

from __future__ import annotations

from typing import Any
from typing import Iterable

from packages.infrastructure.account_types import normalize_account_type
from packages.infrastructure.household import GETTING_TO_KNOW_STATUSES
from packages.infrastructure.household import clean
from packages.infrastructure.household import week_setup_gaps

# The two an account is asked to connect, in the order they are worth asking
# for. Drive and the write permissions are not part of the opening: they are
# asked for by the tool that needs them, when it needs them.
CONNECT_SOURCES = ("mailbox", "calendar")

# The goals an opening can have. "family" is getting to know them; "connect"
# is the offer to connect the mail and the calendar; "done" is an account
# with nothing left to open with, which still says what kind it is.
FLOW_GOALS = ("family", "connect", "done")
FLOW_STATUSES = GETTING_TO_KNOW_STATUSES
# How many of the week's gaps travel with the block. They are asked about one
# at a time, and a list long enough to read as a form is the thing this flow
# exists to avoid.
MAX_WEEK_GAPS_SHOWN = 8


def describe_chat_flow(
    *,
    account_type: Any,
    profile: dict[str, Any] | None,
    connected: Iterable[str],
    today: str,
    family_flow_allowed: bool = True,
    household_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Where this account's opening stands, as the assistant reads it each turn.

    family_flow_allowed is false when the house switched the family and week
    feature off for this kind of account: the tools that keep a family are
    refused, so there is nothing to get to know either, and a family account
    opens on connecting like a business.

    household_block is the family as the assistant reads it. What it is for
    here is the list of what the week still lacks: code works that out from
    what is kept, so the asking ends when the week is actually ready rather
    than when the conversation happens to run out of steam.
    """

    kind = normalize_account_type(account_type)
    profile = profile or {}
    missing = [source for source in CONNECT_SOURCES if source not in set(connected or ())]
    gaps = week_gaps(household_block)

    if kind == "family" and family_flow_allowed:
        status = _status(profile.get("gettingToKnow"))
        if status != "done":
            flow = _flow("family", kind, status, profile.get("askAgainOn"), today)
            flow["weekReady"] = not gaps
            if gaps:
                flow["weekGaps"] = gaps
            return flow

    connect_status = _status(profile.get("connectOffer"))
    if missing and connect_status != "done":
        flow = _flow("connect", kind, connect_status, profile.get("connectAskAgainOn"), today)
        flow["notConnected"] = missing
        if kind == "family" and family_flow_allowed:
            # A week they have called finished is never reopened as a round of
            # questions, but what nobody is down for still travels, so it can
            # be raised on the day it matters.
            flow["weekReady"] = not gaps
            if gaps:
                flow["weekGaps"] = gaps
        return flow

    flow = {"accountType": kind, "goal": "done"}
    if kind == "family" and family_flow_allowed:
        flow["weekReady"] = not gaps
        if gaps:
            flow["weekGaps"] = gaps
    return flow


def week_gaps(household_block: dict[str, Any] | None) -> list[dict[str, Any]]:
    """What the week still lacks, as the assistant is shown it: a few at most,
    because a question at a time is how it is asked anyway."""

    if not isinstance(household_block, dict):
        return []
    return week_setup_gaps(household_block.get("members"), household_block.get("week"))[:MAX_WEEK_GAPS_SHOWN]


def _status(value: Any) -> str:
    status = clean(value).lower()
    return status if status in FLOW_STATUSES else "not_started"


def _flow(goal: str, account_type: str, status: str, ask_again_on: Any, today: str) -> dict[str, Any]:
    """askNow is the whole point of the postponed status: it is false while a
    "not now" is still standing, and true again on the day it named."""

    ask_again = clean(ask_again_on)[:10]
    flow: dict[str, Any] = {
        "accountType": account_type,
        "goal": goal,
        "status": status,
        "askNow": status != "postponed" or not ask_again or ask_again <= str(today or "")[:10],
    }
    if ask_again:
        flow["askAgainOn"] = ask_again
    return flow


# -- the rules that travel with the block --------------------------------------

# A family account reads the same instructions as a business one, which are
# written for someone running a business. This puts them right, and stays
# with the account for good - long after the opening is over.
FAMILY_ACCOUNT_RULES = (
    "This account registered as a family, not a business. What you help them run is their household and "
    "their week: the people in it, where the children are each day, who drives and who collects, the "
    "errands and the appointments and what the week costs them. Read every mention of their business in "
    "these instructions as their household, and knownFacts as what they told you about their family life. "
    "Never call them a business, never speak of their customers or their clients, and when a message is "
    "not something you help with, name something you could do for their week instead.\n"
)

_FAMILY_GETTING_TO_KNOW = (
    "Getting to know this family is the work, not the preamble to it. What you are here to carry is their "
    "week: which child is where on each day, what time it ends, and - the whole point - who takes them and "
    "who collects them, so that everybody is where they need to be and nothing is remembered at the last "
    "minute. None of that comes from a calendar or a mailbox, and you never ask for either while you are "
    "learning it; it comes from them, here, in this conversation, and you keep asking until the week is "
    "whole.\n"
    "CONTEXT.household is what you already hold. CONTEXT.chatFlow.weekGaps is what the week is still "
    "missing, worked out from what is kept and written in the order to ask: 'people' means you know nobody "
    "yet; 'week' names a child with nothing in their week; 'days', 'times', 'drop_off' and 'pick_up' name "
    "an activity that has no days, no finishing time, or nobody down to take or to collect. Answer whatever "
    "they wrote first, then ask about the first gap - one question in a message, warmly and briefly, never "
    "a list and never a form. Start with the people: whether there is a partner and their name, then each "
    "child's name, then each one's birthday, which is worth having for its own sake (an age is enough when "
    "they would rather not say). Then, child by child: school or kindergarten - which days, what time it "
    "ends, who takes them in the morning and who collects them - and then each regular activity after "
    "school, what it is, which days, what time, where, who drives there and who picks up. When they name a "
    "person who is not in household, that is somebody new: save them too, so you know who the pickups "
    "belong to.\n"
    "Save every answer the moment it is given with save_family_member and save_week_activity; several "
    "answers in one message are all saved, and a correction is saved over what it corrects. Nobody has to "
    "have a partner or children, and nothing has to be answered: take what they give and skip what they "
    "pass on. Anything they have already told you earlier in the conversation is answered - save it and "
    "carry on from there, rather than putting the same question to them a second time.\n"
    "Call set_getting_to_know with in_progress when you ask the first question, and again when they pick it "
    "up after putting it off. When they say not now, later, or that they are busy, call it with postponed, "
    "say in a few words that it can wait, and stop asking; while chatFlow.askNow is false do not raise it "
    "at all, and when it is true again ask once, lightly, whether now is a good time to carry on. While "
    "chatFlow.weekGaps is not empty the week cannot be run for them, so do not call done - the one "
    "exception is when they say that is everything, which is always theirs to say. When the last gap "
    "closes, or they close it for you, call set_getting_to_know with done, show the week back in a few "
    "short lines with anything nobody is down for named plainly, and say in one line what you will now do "
    "with it without being asked: each morning what the day holds and who is on what, the evening before "
    "when tomorrow still has nobody down for a pickup, and a word to whoever is driving before it is time "
    "to leave. After done, never start asking about the family again.\n"
)

_CONNECT_OPENING = {
    "business": (
        "Almost everything worth doing for this business is behind their mail and their calendar: the "
        "invoices and receipts, the replies that are due, the meetings and the hours that are actually "
        "free. Getting those two connected is the one thing to make progress on in these first "
        "conversations. CONTEXT.chatFlow.notConnected says which is still missing."
    ),
    "family": (
        "Their family and their week are in, and their week is yours to run from here - it lives with you, "
        "not in a calendar, and nothing about it waits on anything being connected. So a calendar and a "
        "mailbox are an extra, worth one offer and nothing more: their week laid into their own diary, an "
        "invitation the other parent actually gets, the mail from school and the clubs read for the dates "
        "that matter, the bills and receipts gathered without them looking. CONTEXT.chatFlow.notConnected "
        "says which is still missing. Never say, or imply, that you cannot help them until they connect "
        "something; everything they came for already works. If household has no email for the other parent "
        "and an invitation is what they want, ask for it in the same breath as the calendar and save it on "
        "them with save_family_member."
    ),
}

_CONNECT_RULES = (
    "Answer whatever they wrote first. Then, once in a conversation - never in every message, never twice "
    "in a row, and never as a list of features - offer to connect what is missing: one line saying the "
    "thing it would let you do that they would actually want, fitted to them from knownFacts and to what "
    "they have been asking you for, then call connect_link and put the link on its own line exactly as "
    "given. Call set_connect_offer with in_progress when you make that offer. When they connect one and "
    "not the other, the next offer is for the other one alone, and says what that one adds. When they say "
    "not now, later, or leave it, call set_connect_offer with postponed, say in a few words that it can "
    "wait and that they can connect it whenever they like, and stop offering; while chatFlow.askNow is "
    "false do not bring connecting up at all unless they raise it. When both are connected, call "
    "set_connect_offer with done, and say in one line the first thing you will do with them now - then do "
    "it if they say yes.\n"
)


def chat_flow_rules(flow: dict[str, Any] | None) -> str:
    """The lines about this account's kind and its opening, for this turn."""

    if not flow:
        return ""
    account_type = normalize_account_type(flow.get("accountType"))
    goal = str(flow.get("goal") or "done")
    rules = FAMILY_ACCOUNT_RULES if account_type == "family" else ""
    if goal == "family":
        return f"{rules}{_FAMILY_GETTING_TO_KNOW}"
    if goal == "connect":
        return f"{rules}{_CONNECT_OPENING[account_type]} {_CONNECT_RULES}"
    return rules


__all__ = [
    "CONNECT_SOURCES",
    "MAX_WEEK_GAPS_SHOWN",
    "week_gaps",
    "FAMILY_ACCOUNT_RULES",
    "FLOW_GOALS",
    "FLOW_STATUSES",
    "chat_flow_rules",
    "describe_chat_flow",
]
