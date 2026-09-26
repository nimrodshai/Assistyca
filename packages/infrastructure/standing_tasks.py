"""Standing actions: something the assistant does for the person on a schedule, unasked.

"Give me a summary of my meetings every morning" and "pull my receipts on
the first of the month" are not reminders. A reminder sends the person's own
words back to them at one time; a standing action runs a whole turn of the
assistant - the calendar is read, the receipts are pulled and totalled - and
what it wrote is what arrives, every day or week or month, until the person
says stop.

A standing action is a row in scheduled_actions like any reminder, with
action type ``run_task`` and the schedule in its payload. The scheduled
actions worker picks it up when it is due, hands it to the runner here,
delivers what came back over the same channels a reminder uses, and moves
the row on to its next occurrence instead of finishing it.

The runner puts the task through the agent loop exactly as a message from
the person would go: over loopback with a short-lived session for the
account, with the account's sources and recent conversation, so a standing
action can do anything the chat can do and nothing the chat cannot.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.standing_news import news_window_start

STANDING_TASK_ACTION_TYPE = "run_task"
TASK_FREQUENCIES = ("daily", "weekly", "monthly")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MAX_TASK_INSTRUCTION_LENGTH = 1000
MAX_TASK_TITLE_LENGTH = 80
# Where a standing action's result goes: the phone when the account has
# one, the in-app feed otherwise. Same two channels as a reminder.
SUPPORTED_TASK_CHANNELS = ("whatsapp", "portal")

_TIME_LOCAL_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(normalize_text(timezone_name) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _weekday_index(value: Any) -> int | None:
    """Monday is 0, Sunday is 6; a name in any case or an index both work."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 6 else None
    text = normalize_text(value).lower()
    if not text:
        return None
    if text.isdigit():
        index = int(text)
        return index if 0 <= index <= 6 else None
    for index, name in enumerate(WEEKDAY_NAMES):
        if name.startswith(text[:3]):
            return index
    return None


def normalize_task_schedule(raw: Any) -> dict[str, Any] | None:
    """The schedule as the worker keeps it, or None when it does not say enough.

    Accepts what the tool passes (frequency, timeLocal, weekday, dayOfMonth)
    in either camel or snake case. Weekly needs a weekday; monthly without a
    day means the first of the month.
    """

    if not isinstance(raw, dict):
        return None
    frequency = normalize_text(raw.get("frequency")).lower()
    if frequency not in TASK_FREQUENCIES:
        return None
    time_local = normalize_text(raw.get("timeLocal") or raw.get("time_local"))
    match = _TIME_LOCAL_RE.fullmatch(time_local)
    if not match:
        return None
    schedule: dict[str, Any] = {
        "frequency": frequency,
        "timeLocal": f"{int(match.group(1)):02d}:{int(match.group(2)):02d}",
    }
    if frequency == "weekly":
        weekday = _weekday_index(raw.get("weekday"))
        if weekday is None:
            return None
        schedule["weekday"] = weekday
    elif frequency == "monthly":
        try:
            day = int(raw.get("dayOfMonth") or raw.get("day_of_month") or 1)
        except (TypeError, ValueError):
            return None
        if not 1 <= day <= 31:
            return None
        schedule["dayOfMonth"] = day
    return schedule


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def describe_task_schedule(schedule: dict[str, Any] | None) -> str:
    """The schedule as the person would say it: "every day at 08:00"."""

    normalized = normalize_task_schedule(schedule)
    if normalized is None:
        return ""
    time_local = normalized["timeLocal"]
    frequency = normalized["frequency"]
    if frequency == "daily":
        return f"every day at {time_local}"
    if frequency == "weekly":
        return f"every {WEEKDAY_NAMES[int(normalized['weekday'])].capitalize()} at {time_local}"
    day = int(normalized["dayOfMonth"])
    if day >= 29:
        return f"on the {_ordinal(day)} of every month (or its last day) at {time_local}"
    return f"on the {_ordinal(day)} of every month at {time_local}"


def next_task_run_at(
    schedule: dict[str, Any],
    *,
    timezone_name: str,
    after: datetime | None = None,
) -> datetime | None:
    """The first occurrence strictly after ``after``, as a UTC instant.

    Worked out on the local clock where the person is, so 08:00 stays 08:00
    across a clock change. A monthly day past the end of a short month
    lands on that month's last day.
    """

    normalized = normalize_task_schedule(schedule)
    if normalized is None:
        return None
    zone = _zone(timezone_name)
    reference = (after or datetime.now(timezone.utc)).astimezone(zone)
    hour, minute = (int(part) for part in normalized["timeLocal"].split(":"))
    frequency = normalized["frequency"]

    if frequency == "daily":
        candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= reference:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    if frequency == "weekly":
        days_ahead = (int(normalized["weekday"]) - reference.weekday()) % 7
        candidate = (reference + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= reference:
            candidate = candidate + timedelta(days=7)
        return candidate.astimezone(timezone.utc)

    wanted_day = int(normalized["dayOfMonth"])
    year, month = reference.year, reference.month
    for _ in range(3):
        day = min(wanted_day, calendar.monthrange(year, month)[1])
        candidate = datetime(year, month, day, hour, minute, tzinfo=zone)
        if candidate > reference:
            return candidate.astimezone(timezone.utc)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return None


def is_standing_task(action: dict[str, Any] | None) -> bool:
    if not isinstance(action, dict):
        return False
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    return (
        normalize_text(action.get("actionType")).lower() == STANDING_TASK_ACTION_TYPE
        and normalize_task_schedule(payload.get("schedule")) is not None
    )


def build_task_run_message(
    *, title: str, instruction: str, schedule_text: str, standing: bool = True, may_offer: bool = False,
) -> str:
    """What the loop is asked when a standing action fires.

    The model is told plainly that nobody is typing: the reply is the
    message the person will find, so there is nothing to ask and nothing
    to set up, only the work itself. A one-off run - something the server
    queued once, such as what a mailbox scan found - says so instead of
    claiming a schedule it does not have. may_offer is for a one-off whose
    instruction proposes one action for a yes (an alert offering to put an
    event in the diary): the person may answer, so that question is allowed.
    """

    name = normalize_text(title) or ("standing action" if standing else "action")
    when = f" ({schedule_text})" if schedule_text else ""
    opening = (
        f"The standing action \"{name}\"{when} is running now on its schedule."
        if standing
        else f"The one-off action \"{name}\" is running now."
    )
    if may_offer:
        return (
            f"{opening} The person is not writing; they will read your reply as a message on its own and may "
            "answer it. Write it as the finished result, with no question and no offer except the one the "
            "instruction allows, and nothing set up or scheduled. Do this now: "
            f"{normalize_text(instruction)}"
        )
    quiet = (
        " If the work turns up nothing they need this time - nothing on today, nothing new, nothing to do - "
        "and the instruction does not ask to hear from you even then, set nothingToSend and no message goes: "
        "a message saying there is nothing is one they did not need."
        if standing else ""
    )
    return (
        f"{opening} The person is not writing; "
        "they will read your reply as a message on its own, so write it as the finished result and "
        f"nothing else: no questions, no offers, nothing set up or scheduled.{quiet} Do this now: "
        f"{normalize_text(instruction)}"
    )


class NothingNewToSend(Exception):
    """A recurring run found nothing to send - no news it has not already
    sent, or nothing the person needs today. The scheduler moves the task on
    without sending anything."""


class StandingTaskRunner:
    """Runs one standing action through the agent loop and returns what it wrote."""

    def __init__(
        self,
        *,
        database: Any,
        base_url: str,
        session_token_factory: Callable[[str], str],
    ) -> None:
        self.database = database
        self.base_url = str(base_url or "").rstrip("/")
        self.session_token_factory = session_token_factory

    def _connection_for(self, action: dict[str, Any]) -> dict[str, Any]:
        """The account behind the action, in the shape the chat wants: user
        id, email, and the phone the reply is for when there is one."""

        user_id = int(action.get("userId") or 0)
        if user_id <= 0:
            raise RuntimeError("Standing action is missing a user id.")
        connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        email = normalize_text(connection.get("email"))
        if not email:
            user = self.database.get_user_by_id(user_id) or {}
            email = normalize_text(user.get("email"))
        if not email:
            raise RuntimeError("Standing action does not resolve to an account.")
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        owner_wa_id = normalize_text(payload.get("recipientWaId")) or normalize_text(connection.get("ownerWaId"))
        if not owner_wa_id:
            linked = self.database.list_user_whatsapp_numbers(user_id=user_id)
            owner_wa_id = normalize_text(linked[0].get("waId")) if linked else ""
        return {**connection, "userId": user_id, "email": email, "ownerWaId": owner_wa_id}

    def run(self, action: dict[str, Any]) -> str:
        # Imported here: the chat module imports nearly everything, and the
        # scheduler that holds this runner is imported by the server early.
        from packages.infrastructure.whatsapp_agent_chat import AGENT_CHAT_HISTORY_LIMIT
        from packages.infrastructure.whatsapp_agent_chat import AGENT_RUN_TIMEOUT_SECONDS
        from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat
        from packages.infrastructure.whatsapp_agent_chat import format_agent_reply_for_whatsapp

        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        instruction = normalize_text(payload.get("instruction"))
        if not instruction:
            raise RuntimeError("Standing action has nothing to do: the instruction is missing.")
        connection = self._connection_for(action)
        channel = "whatsapp" if normalize_text(action.get("channel")).lower() == "whatsapp" else "portal"
        user_id = int(connection["userId"])
        # An offer needs somewhere for the yes to land: the WhatsApp chat,
        # with no other question already waiting there. Otherwise the plain
        # instruction runs and the alert only tells.
        offer_instruction = normalize_text(payload.get("offerInstruction"))
        may_offer = bool(
            offer_instruction
            and channel == "whatsapp"
            and not is_standing_task(action)
            and not self.database.get_whatsapp_agent_pending(user_id=user_id)
        )
        if may_offer:
            instruction = offer_instruction
        chat = WhatsAppAgentChat(
            database=self.database,
            connection=connection,
            base_url=self.base_url,
            session_token_factory=self.session_token_factory,
        )
        timezone_name = normalize_text(action.get("timezone")) or chat.timezone_name

        # A nudge that belongs to a group is written in the group's own
        # conversation and with a group's own turn: nothing of the account is
        # readable there, and the room is what it is talking to.
        group = payload.get("group") if isinstance(payload.get("group"), dict) else {}
        group_id = normalize_text(group.get("id"))
        history = self.database.list_recent_whatsapp_agent_messages(
            user_id=user_id, limit=AGENT_CHAT_HISTORY_LIMIT, thread_id=group_id,
        )
        conversation = [{"role": item["role"], "text": item["text"]} for item in history]
        request: dict[str, Any] = {
            "userMessage": build_task_run_message(
                title=normalize_text(payload.get("title")),
                instruction=instruction,
                schedule_text=describe_task_schedule(payload.get("schedule")),
                standing=is_standing_task(action),
                may_offer=may_offer,
            ),
            "conversation": conversation,
            "timezone": timezone_name,
            "channel": channel,
            "toolContext": chat._build_tool_context(),
            "senderWaId": "" if group_id else (chat.owner_wa_id if channel == "whatsapp" else ""),
        }
        if group_id:
            request["group"] = {"id": group_id, "name": normalize_text(group.get("name")), "speaker": ""}
        if is_standing_task(action):
            request["standingTask"] = {
                "actionId": int(action.get("id") or 0),
                "newsSince": news_window_start(action, now=datetime.now(timezone.utc)).isoformat(),
            }
        turn, status = chat._api("POST", "/api/agent/loop", request, timeout=AGENT_RUN_TIMEOUT_SECONDS)
        if status != 200 or not turn.get("ok"):
            code = normalize_text(turn.get("error")) or f"HTTP {status}"
            detail = normalize_text(turn.get("message"))
            raise RuntimeError(f"The assistant could not run the action ({code}{': ' + detail if detail else ''}).")
        if is_standing_task(action) and turn.get("nothingNew"):
            raise NothingNewToSend("Nothing to send this time.")
        news_found = [item for item in turn.get("newsFound") or [] if isinstance(item, dict)]
        if news_found and isinstance(action.get("payload"), dict):
            # Carried to the scheduler, which writes them down once delivered.
            action["payload"]["newsFound"] = news_found
        reply = normalize_text(turn.get("reply"))
        if channel == "whatsapp":
            reply = format_agent_reply_for_whatsapp(reply)
        if not reply:
            raise RuntimeError("The assistant ran the action but wrote nothing to send.")
        if channel == "whatsapp":
            # The result joins the WhatsApp transcript so "which meeting was
            # that?" the next morning has something to refer to - the group's
            # own transcript when the nudge was for a group.
            self.database.save_whatsapp_agent_message(
                user_id=user_id, role="assistant", text=reply, thread_id=group_id,
            )
        pending = turn.get("pendingConfirmation") if isinstance(turn.get("pendingConfirmation"), dict) else None
        approval_id = normalize_text((pending or {}).get("id"))
        if may_offer and approval_id:
            # The same held question the chat keeps when it asks for a yes,
            # so the answer to the alert runs the proposed action as proposed.
            self.database.save_whatsapp_agent_pending(
                user_id=user_id,
                pending={
                    "kind": "tool_confirmation",
                    "approvalId": approval_id,
                    "tool": normalize_text(pending.get("tool")),
                    "question": reply[:500],
                    "askedAt": datetime.now(timezone.utc).isoformat(),
                },
            )
        return reply


__all__ = [
    "MAX_TASK_INSTRUCTION_LENGTH",
    "MAX_TASK_TITLE_LENGTH",
    "NothingNewToSend",
    "STANDING_TASK_ACTION_TYPE",
    "SUPPORTED_TASK_CHANNELS",
    "StandingTaskRunner",
    "TASK_FREQUENCIES",
    "WEEKDAY_NAMES",
    "build_task_run_message",
    "describe_task_schedule",
    "is_standing_task",
    "next_task_run_at",
    "normalize_task_schedule",
]
