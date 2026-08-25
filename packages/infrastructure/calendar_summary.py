"""Read-only calendar summaries for portal actions.

The portal stores provider credentials encrypted at rest.  This module accepts
the decrypted credential only at the point of execution, calls the Google
Calendar read API, and returns a deterministic summary without sending meeting
contents to a language model.  Keeping the first runner deterministic avoids
unexpected token spend and makes a manual run easy to diagnose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from datetime import timezone
import json
import re
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3/calendars"
CALENDAR_MAX_EVENTS = 100
CALENDAR_TIMEOUT_SECONDS = 20


class CalendarSummaryError(RuntimeError):
    """A safe, user-facing calendar runner error."""

    def __init__(self, message: str, *, code: str = "calendar_summary_failed") -> None:
        super().__init__(message)
        self.code = code


class CalendarAuthorizationError(CalendarSummaryError):
    """The stored credential cannot read calendar events."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="calendar_authorization_failed")


@dataclass(frozen=True)
class CalendarDateRange:
    label: str
    start: datetime
    end: datetime

    @property
    def start_date(self) -> date:
        return self.start.date()

    @property
    def end_date(self) -> date:
        # The API end is exclusive, while the user-facing label is inclusive.
        return (self.end - timedelta(days=1)).date()


def _safe_zone(timezone_name: str | None) -> ZoneInfo:
    normalized = str(timezone_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _start_of_day(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, dt_time.min, tzinfo=zone)


def _parse_explicit_date_range(value: str, zone: ZoneInfo) -> CalendarDateRange | None:
    match = re.search(
        r"(?P<start>\d{4}-\d{1,2}-\d{1,2})\s*(?:to|through|until|[-–])\s*(?P<end>\d{4}-\d{1,2}-\d{1,2})",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        start_date = date.fromisoformat(match.group("start"))
        end_date = date.fromisoformat(match.group("end"))
    except ValueError as exc:
        raise CalendarSummaryError("The meeting date range is not valid. Choose a range such as next week.", code="invalid_date_range") from exc
    if end_date < start_date:
        raise CalendarSummaryError("The meeting date range ends before it starts. Choose a valid range.", code="invalid_date_range")
    return CalendarDateRange(
        label=f"{start_date.isoformat()} to {end_date.isoformat()}",
        start=_start_of_day(start_date, zone),
        end=_start_of_day(end_date + timedelta(days=1), zone),
    )


def parse_calendar_date_range(
    value: str | None,
    *,
    timezone_name: str | None = "UTC",
    now: datetime | None = None,
) -> CalendarDateRange:
    """Resolve the portal's friendly date ranges into an API interval."""

    zone = _safe_zone(timezone_name)
    current = (now or datetime.now(zone)).astimezone(zone)
    today = current.date()
    normalized = re.sub(r"\s+", " ", str(value or "next week").strip().lower())
    explicit = _parse_explicit_date_range(normalized, zone)
    if explicit:
        return explicit

    if normalized in {"today", "this day"}:
        start_date, end_date = today, today
    elif normalized in {"tomorrow", "next day"}:
        start_date = end_date = today + timedelta(days=1)
    elif normalized in {"this week", "this calendar week"}:
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif normalized in {"next week", "next calendar week"}:
        start_date = today - timedelta(days=today.weekday()) + timedelta(days=7)
        end_date = start_date + timedelta(days=6)
    elif normalized in {"this month", "current month"}:
        start_date = today.replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
    elif normalized in {"next month"}:
        start_date = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
    else:
        raise CalendarSummaryError(
            "I couldn’t understand that meeting date range. Choose today, this week, next week, or a specific range.",
            code="invalid_date_range",
        )

    return CalendarDateRange(
        label=f"{start_date.isoformat()} to {end_date.isoformat()}",
        start=_start_of_day(start_date, zone),
        end=_start_of_day(end_date + timedelta(days=1), zone),
    )


def _event_datetime(value: Any, zone: ZoneInfo, *, end: bool = False) -> datetime | None:
    if not isinstance(value, dict):
        return None
    raw = str(value.get("dateTime") or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(zone)
    raw_date = str(value.get("date") or "").strip()
    if raw_date:
        try:
            return _start_of_day(date.fromisoformat(raw_date), zone)
        except ValueError:
            return None
    return None


def normalize_calendar_event(event: dict[str, Any], *, timezone_name: str | None = "UTC") -> dict[str, Any] | None:
    zone = _safe_zone(timezone_name)
    start = _event_datetime(event.get("start"), zone)
    end = _event_datetime(event.get("end"), zone, end=True)
    if start is None:
        return None
    return {
        "id": str(event.get("id") or "").strip(),
        "title": str(event.get("summary") or "Untitled meeting").strip() or "Untitled meeting",
        "start": start,
        "end": end,
        "location": str(event.get("location") or "").strip(),
        "description": str(event.get("description") or "").strip(),
        "allDay": bool(event.get("start", {}).get("date")) if isinstance(event.get("start"), dict) else False,
    }


def _format_event_time(event: dict[str, Any]) -> str:
    start = event["start"]
    if event.get("allDay"):
        return start.strftime("%a, %b %-d · all day")
    end = event.get("end")
    start_label = start.strftime("%a, %b %-d · %-I:%M %p")
    if isinstance(end, datetime) and end.date() == start.date():
        return f"{start_label}–{end.strftime('%-I:%M %p')}"
    return start_label


def _display_range(date_range: CalendarDateRange) -> str:
    start = date_range.start
    end = date_range.end - timedelta(days=1)
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.strftime('%b %-d')}–{end.strftime('%-d, %Y')}"
        return f"{start.strftime('%b %-d')}–{end.strftime('%b %-d, %Y')}"
    return f"{start.strftime('%b %-d, %Y')}–{end.strftime('%b %-d, %Y')}"


def build_calendar_summary(events: list[dict[str, Any]], date_range: CalendarDateRange) -> str:
    """Build a concise portal-safe summary from normalized event records."""

    header = f"Meeting summary · {_display_range(date_range)}"
    if not events:
        return f"{header}\n\nNo meetings found in this range."

    lines = [header, "", f"{len(events)} meeting{'s' if len(events) != 1 else ''}:"]
    for event in events[:CALENDAR_MAX_EVENTS]:
        detail = f"• {_format_event_time(event)} — {event['title']}"
        if event.get("location"):
            detail += f" · {event['location']}"
        lines.append(detail[:500])
        description = re.sub(r"\s+", " ", str(event.get("description") or "")).strip()
        if description:
            lines.append(f"  {description[:240]}")
    if len(events) > CALENDAR_MAX_EVENTS:
        lines.append(f"…and {len(events) - CALENDAR_MAX_EVENTS} more.")
    return "\n".join(lines)


class CalendarSummaryRunner:
    """Fetch and summarize a connected Google Calendar using read-only access."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = CALENDAR_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def fetch_events(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        date_range: CalendarDateRange,
    ) -> list[dict[str, Any]]:
        token = str(access_token or "").strip()
        if not token:
            raise CalendarAuthorizationError(
                "Calendar access needs attention: no usable access token is saved. Reconnect Calendar with Google read-only access, then run it again."
            )
        safe_calendar_id = str(calendar_id or "primary").strip() or "primary"
        # Calendar IDs are provider data, not a URL supplied by the user. Keep
        # the default primary calendar unless a future OAuth flow supplies one.
        if safe_calendar_id != "primary":
            safe_calendar_id = "primary"
        params = urllib_parse.urlencode({
            "timeMin": date_range.start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "timeMax": date_range.end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(CALENDAR_MAX_EVENTS),
        })
        encoded_calendar_id = urllib_parse.quote(safe_calendar_id, safe="")
        url = f"{CALENDAR_API_URL}/{encoded_calendar_id}/events?{params}"
        request = urllib_request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib_error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise CalendarAuthorizationError(
                    "Calendar access needs attention: Google rejected the saved credential or its permissions. Reconnect with a Google OAuth token that grants read-only Calendar access, then run it again."
                ) from exc
            raise CalendarSummaryError(
                f"Google Calendar returned an error ({exc.code}). Try again or reconnect Calendar.",
                code="calendar_provider_error",
            ) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise CalendarSummaryError(
                "I couldn’t reach Google Calendar. Check the connection and try the run again.",
                code="calendar_network_error",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CalendarSummaryError(
                "Google Calendar returned an unreadable response. Try again or reconnect Calendar.",
                code="calendar_provider_error",
            ) from exc

        if not isinstance(payload, dict):
            raise CalendarSummaryError("Google Calendar returned an invalid response.", code="calendar_provider_error")
        raw_events = payload.get("items") if isinstance(payload.get("items"), list) else []
        events = [
            normalized
            for item in raw_events
            if isinstance(item, dict)
            for normalized in [normalize_calendar_event(item, timezone_name=str(date_range.start.tzinfo or "UTC"))]
            if normalized is not None
        ]
        events.sort(key=lambda item: item["start"])
        return events

    def run(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        time_window: str = "next week",
        timezone_name: str = "UTC",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        date_range = parse_calendar_date_range(time_window, timezone_name=timezone_name, now=now)
        events = self.fetch_events(access_token, calendar_id=calendar_id, date_range=date_range)
        return {
            "message": build_calendar_summary(events, date_range),
            "summary": build_calendar_summary(events, date_range),
            "eventCount": len(events),
            "dateRange": {
                "label": date_range.label,
                "display": _display_range(date_range),
                "start": date_range.start.isoformat(),
                "end": date_range.end.isoformat(),
            },
        }
