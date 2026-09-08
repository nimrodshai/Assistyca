"""Adding to and changing a connected Google Calendar.

Reading needs ``calendar.events.readonly``; writing needs ``calendar.events``.
A calendar connected before the wider grant was asked for still reads, and
the writer names the missing permission instead of failing as if the
calendar had gone.
"""

from __future__ import annotations

import json
import re
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.infrastructure.calendar_summary import CALENDAR_API_URL
from packages.infrastructure.calendar_summary import CALENDAR_TIMEOUT_SECONDS
from packages.infrastructure.calendar_summary import CalendarAuthorizationError
from packages.infrastructure.calendar_summary import CalendarSummaryError
from packages.infrastructure.calendar_summary import _format_event_time
from packages.infrastructure.calendar_summary import _safe_zone
from packages.infrastructure.calendar_summary import normalize_calendar_event
from packages.infrastructure.calendar_summary import normalize_calendar_id
from packages.infrastructure.gmail_send import normalize_addresses

CALENDAR_WRITE_OAUTH_SCOPE = "https://www.googleapis.com/auth/calendar.events"
DEFAULT_EVENT_MINUTES = 60
MAX_TITLE_LENGTH = 300
MAX_DESCRIPTION_LENGTH = 4000
MAX_ATTENDEES = 20
DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


class CalendarWritePermissionError(CalendarAuthorizationError):
    """The calendar is connected, but without permission to change it."""

    code = "calendar_write_permission_required"

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "The calendar is connected for reading only. Connect Google again and allow editing events, then try once more."
        )
        self.code = "calendar_write_permission_required"


class CalendarEventNotFoundError(CalendarSummaryError):
    code = "calendar_event_not_found"

    def __init__(self) -> None:
        super().__init__("That meeting is not in the calendar any more.", code=self.code)


def parse_event_date(value: Any) -> date:
    text = str(value or "").strip()
    match = DATE_PATTERN.match(text)
    if not match:
        raise ValueError("The date has to be YYYY-MM-DD.")
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError as exc:
        raise ValueError("That is not a real date.") from exc


def parse_event_time(value: Any) -> tuple[int, int] | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = TIME_PATTERN.match(text)
    if not match:
        raise ValueError("The time has to be HH:MM in 24-hour form.")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("That is not a real time of day.")
    return hour, minute


def build_event_times(
    *,
    date_text: Any,
    start_time: Any = None,
    end_time: Any = None,
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    """Google's start and end for an event, from a date and optional clock times.

    No start time makes an all-day event. No end time makes it an hour long.
    An end at or before the start is the caller's mistake and is said so.
    """

    day = parse_event_date(date_text)
    start = parse_event_time(start_time)
    end = parse_event_time(end_time)
    zone = _safe_zone(timezone_name)
    zone_name = str(zone.key) if hasattr(zone, "key") else "UTC"
    if start is None:
        if end is not None:
            raise ValueError("An end time needs a start time.")
        return {
            "start": {"date": day.isoformat()},
            "end": {"date": (day + timedelta(days=1)).isoformat()},
            "allDay": True,
        }
    start_at = datetime(day.year, day.month, day.day, start[0], start[1], tzinfo=zone)
    if end is None:
        end_at = start_at + timedelta(minutes=DEFAULT_EVENT_MINUTES)
    else:
        end_at = datetime(day.year, day.month, day.day, end[0], end[1], tzinfo=zone)
        if end_at <= start_at:
            raise ValueError("The end time has to be after the start time.")
    return {
        "start": {"dateTime": start_at.isoformat(), "timeZone": zone_name},
        "end": {"dateTime": end_at.isoformat(), "timeZone": zone_name},
        "allDay": False,
    }


def describe_written_event(event: dict[str, Any], *, calendar_id: str, timezone_name: str) -> dict[str, Any]:
    """The event as the chat reads it back: one flat record plus Google's link."""

    normalized = normalize_calendar_event(event, timezone_name=timezone_name) or {}
    record = {
        "kind": "meeting",
        "eventId": str(event.get("id") or "").strip(),
        "calendarId": calendar_id,
        "when": _format_event_time(normalized) if normalized else "",
        "title": str(event.get("summary") or "").strip(),
        "location": str(event.get("location") or "").strip(),
        "detail": re.sub(r"\s+", " ", str(event.get("description") or "")).strip()[:240],
        "attendees": ", ".join(
            str(person.get("email") or "").strip()
            for person in (event.get("attendees") or [])
            if isinstance(person, dict) and person.get("email")
        ),
        "link": str(event.get("htmlLink") or "").strip(),
        "status": str(event.get("status") or "").strip(),
    }
    return {key: value for key, value in record.items() if value}


class CalendarWriter:
    """Create, change and cancel events in one calendar of a connected account."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = CALENDAR_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def _request_json(
        self,
        url: str,
        access_token: str,
        *,
        method: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            raise CalendarAuthorizationError(
                "Calendar access needs attention: no usable access token is saved. Connect Google again, then try once more."
            )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib_request.Request(url, headers=headers, method=method, data=data)
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib_error.HTTPError as exc:
            if exc.code == 403:
                raise CalendarWritePermissionError() from exc
            if exc.code == 401:
                raise CalendarAuthorizationError(
                    "Calendar access needs attention: Google rejected the saved credential. Connect Google again, then try once more."
                ) from exc
            if exc.code in {404, 410}:
                raise CalendarEventNotFoundError() from exc
            raise CalendarSummaryError(
                "I couldn't change Google Calendar just now. Try again in a moment.",
                code="calendar_provider_error",
            ) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise CalendarSummaryError(
                "I couldn't reach Google Calendar. Check the connection and try again.",
                code="calendar_network_error",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CalendarSummaryError(
                "I couldn't read Google Calendar's answer just now. Try again in a moment.",
                code="calendar_provider_error",
            ) from exc
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _event_url(calendar_id: str, event_id: str = "", *, notify: bool = True) -> str:
        safe_calendar = urllib_parse.quote(normalize_calendar_id(calendar_id), safe="")
        url = f"{CALENDAR_API_URL}/{safe_calendar}/events"
        if event_id:
            url = f"{url}/{urllib_parse.quote(str(event_id).strip(), safe='')}"
        if notify:
            # Attendees hear about it from Google, the way they would if the
            # person had done it by hand.
            url = f"{url}?{urllib_parse.urlencode({'sendUpdates': 'all'})}"
        return url

    def create_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        title: str,
        date_text: str,
        start_time: str | None = None,
        end_time: str | None = None,
        timezone_name: str = "UTC",
        location: str = "",
        description: str = "",
        attendees: list[str] | None = None,
    ) -> dict[str, Any]:
        summary = " ".join(str(title or "").split())[:MAX_TITLE_LENGTH]
        if not summary:
            raise ValueError("The meeting needs a title.")
        times = build_event_times(date_text=date_text, start_time=start_time, end_time=end_time, timezone_name=timezone_name)
        body: dict[str, Any] = {"summary": summary, "start": times["start"], "end": times["end"]}
        if str(location or "").strip():
            body["location"] = " ".join(str(location).split())[:MAX_TITLE_LENGTH]
        if str(description or "").strip():
            body["description"] = str(description).strip()[:MAX_DESCRIPTION_LENGTH]
        guests = normalize_addresses(attendees or [], limit=MAX_ATTENDEES)
        if guests:
            from packages.infrastructure.gmail_send import bare_address

            body["attendees"] = [{"email": bare_address(guest)} for guest in guests]
        created = self._request_json(self._event_url(calendar_id), access_token, method="POST", body=body)
        return describe_written_event(created, calendar_id=normalize_calendar_id(calendar_id), timezone_name=timezone_name)

    def update_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        event_id: str,
        title: str | None = None,
        date_text: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        location: str | None = None,
        description: str | None = None,
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        if not str(event_id or "").strip():
            raise ValueError("Which meeting to change is needed.")
        body: dict[str, Any] = {}
        if title is not None and str(title).strip():
            body["summary"] = " ".join(str(title).split())[:MAX_TITLE_LENGTH]
        if location is not None:
            body["location"] = " ".join(str(location).split())[:MAX_TITLE_LENGTH]
        if description is not None:
            body["description"] = str(description).strip()[:MAX_DESCRIPTION_LENGTH]
        if date_text or start_time or end_time:
            if not date_text:
                # Moving the clock without naming the day: the day stays as
                # it is in Google, so it is read first.
                current = self._request_json(self._event_url(calendar_id, event_id, notify=False), access_token, method="GET")
                current_start = current.get("start") if isinstance(current.get("start"), dict) else {}
                raw = str(current_start.get("dateTime") or current_start.get("date") or "")[:10]
                if not raw:
                    raise CalendarEventNotFoundError()
                date_text = raw
            times = build_event_times(date_text=date_text, start_time=start_time, end_time=end_time, timezone_name=timezone_name)
            body["start"] = times["start"]
            body["end"] = times["end"]
        if not body:
            raise ValueError("Nothing to change was given.")
        updated = self._request_json(self._event_url(calendar_id, event_id), access_token, method="PATCH", body=body)
        return describe_written_event(updated, calendar_id=normalize_calendar_id(calendar_id), timezone_name=timezone_name)

    def cancel_event(self, access_token: str, *, calendar_id: str, event_id: str) -> dict[str, Any]:
        if not str(event_id or "").strip():
            raise ValueError("Which meeting to cancel is needed.")
        self._request_json(self._event_url(calendar_id, event_id), access_token, method="DELETE")
        return {"eventId": str(event_id).strip(), "calendarId": normalize_calendar_id(calendar_id), "cancelled": True}
