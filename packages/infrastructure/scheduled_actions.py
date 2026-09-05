from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timezone
import os
import threading
from typing import Any
from typing import Callable

from packages.infrastructure.list_due_nudges import describe_due
from packages.infrastructure.notification_delivery import deliver_portal_notification
from packages.infrastructure.notification_delivery import send_whatsapp_notification
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import normalize_text


DEFAULT_SCHEDULED_ACTION_POLL_SECONDS = 10
DEFAULT_SCHEDULED_ACTION_BATCH_SIZE = 25
DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_NAME = "notification_message"
DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_LANGUAGE = "en_US"
# A message the owner asked to receive on WhatsApp goes out on WhatsApp; the
# in-app feed carries everything else and is the fallback when WhatsApp
# delivery is not configured. The WhatsApp agent conversation made "text me at
# 12:40" a promise about the phone, not the portal.
SUPPORTED_SEND_CHANNELS = {"portal", "whatsapp"}
OWNER_RECIPIENT_REFS = {"", "me", "owner", "you", "connected_owner", "account_owner"}


@dataclass(frozen=True)
class ScheduledActionConfig:
    enabled: bool = True
    poll_seconds: int = DEFAULT_SCHEDULED_ACTION_POLL_SECONDS
    batch_size: int = DEFAULT_SCHEDULED_ACTION_BATCH_SIZE
    whatsapp_template_name: str = DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_NAME
    whatsapp_template_language: str = DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_LANGUAGE


def parse_bool_env(value: str | None, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def parse_int_env(value: str | None, default: int) -> int:
    try:
        return int(normalize_text(value) or default)
    except (TypeError, ValueError):
        return default


def load_scheduled_action_config() -> ScheduledActionConfig:
    return ScheduledActionConfig(
        enabled=parse_bool_env(os.getenv("PORTAL_SCHEDULED_ACTIONS_ENABLED"), True),
        poll_seconds=max(
            1,
            parse_int_env(os.getenv("PORTAL_SCHEDULED_ACTIONS_POLL_SECONDS"), DEFAULT_SCHEDULED_ACTION_POLL_SECONDS),
        ),
        batch_size=max(
            1,
            parse_int_env(os.getenv("PORTAL_SCHEDULED_ACTIONS_BATCH_SIZE"), DEFAULT_SCHEDULED_ACTION_BATCH_SIZE),
        ),
        whatsapp_template_name=(
            normalize_text(os.getenv("WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_NAME"))
            or DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_NAME
        ),
        whatsapp_template_language=(
            normalize_text(os.getenv("WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_LANGUAGE"))
            or DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_LANGUAGE
        ),
    )


def describe_list_for_message(record: dict[str, Any], *, limit: int = 40) -> str:
    """The list as lines of text: the name, then what is still on it."""

    name = normalize_text(record.get("name")) or "Your list"
    items = [item for item in (record.get("items") or []) if isinstance(item, dict)]
    if record.get("kind") == "todo":
        items = [item for item in items if not item.get("done")]
    if not items:
        return f"{name}: nothing left on it." if record.get("kind") == "todo" else f"{name}: empty."
    lines = [f"{name}:"]
    today = date.today()
    for item in items[:limit]:
        due = describe_due(item.get("dueOn"), today) if record.get("kind") == "todo" else ""
        lines.append(f"• {normalize_text(item.get('text'))}{f' ({due})' if due else ''}")
    if len(items) > limit:
        lines.append(f"…and {len(items) - limit} more")
    return "\n".join(lines)


class ScheduledActionScheduler:
    def __init__(
        self,
        database: PortalDatabase,
        *,
        config: ScheduledActionConfig | None = None,
    ) -> None:
        self.database = database
        self.config = config or load_scheduled_action_config()

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

        # Release claims abandoned by a crashed or redeployed worker before picking
        # up new work, otherwise those rows stay 'running' forever and the message
        # is never sent.
        try:
            recovered = self.database.requeue_stale_scheduled_actions(now=reference)
        except Exception:  # noqa: BLE001 - recovery must never block dispatch
            recovered = 0

        actions = self.database.list_due_scheduled_actions(
            now=reference,
            limit=self.config.batch_size,
        )
        processed = 0
        sent = 0
        failed = 0

        for due_action in actions:
            claimed = self.database.claim_scheduled_action(int(due_action.get("id") or 0))
            if not claimed:
                continue

            processed += 1
            try:
                provider_message_id = self._dispatch(claimed)
            except Exception as exc:  # noqa: BLE001 - keep later due actions moving
                failed += 1
                self.database.finish_scheduled_action(
                    action_id=int(claimed.get("id") or 0),
                    status="failed",
                    last_error=str(exc),
                    payload={
                        **(claimed.get("payload") if isinstance(claimed.get("payload"), dict) else {}),
                        "failedAt": datetime.now(timezone.utc).isoformat(),
                    },
                )
                continue

            sent += 1
            self.database.finish_scheduled_action(
                action_id=int(claimed.get("id") or 0),
                status="sent",
                provider_message_id=provider_message_id,
                payload={
                    **(claimed.get("payload") if isinstance(claimed.get("payload"), dict) else {}),
                    "sentAt": datetime.now(timezone.utc).isoformat(),
                },
            )

        return {
            "ok": True,
            "due": len(actions),
            "processed": processed,
            "sent": sent,
            "failed": failed,
            "recovered": recovered,
        }

    def _dispatch(self, action: dict[str, Any]) -> str:
        action_type = normalize_text(action.get("actionType")).lower()
        channel = normalize_text(action.get("channel")).lower()
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        if action_type != "send_message":
            raise RuntimeError(f"Unsupported scheduled action type: {action_type}")

        message_text = normalize_text(payload.get("messageText") or payload.get("text"))
        if not message_text:
            raise RuntimeError("Scheduled message text is missing.")
        message_text = self._attach_list(action, payload, message_text)

        if channel == "whatsapp":
            try:
                provider_message_id = self._deliver_whatsapp(action, message_text)
                payload["deliveredVia"] = "whatsapp"
                return provider_message_id
            except Exception as exc:  # noqa: BLE001 - the message still has to arrive somewhere
                # A configured send that fails should still reach the owner.
                # The feed is durable and always available, and the payload
                # says openly which channel actually carried the message.
                payload["deliveredVia"] = "portal_fallback"
                payload["whatsappDeliveryError"] = str(exc)
                return self._deliver_in_app(action, message_text)

        payload["deliveredVia"] = "portal"
        return self._deliver_in_app(action, message_text)

    def _attach_list(self, action: dict[str, Any], payload: dict[str, Any], message_text: str) -> str:
        """A reminder about a list carries the list as it is now, not as it
        was when the reminder was set. What is ticked off stays off it."""

        try:
            list_id = int(payload.get("listId") or 0)
        except (TypeError, ValueError):
            list_id = 0
        if list_id <= 0:
            return message_text
        record = self.database.get_account_list(user_id=int(action.get("userId") or 0), list_id=list_id)
        if record is None:
            payload["listMissing"] = True
            return f"{message_text}\n\n(The list this was about is no longer there.)"
        return f"{message_text}\n\n{describe_list_for_message(record)}"

    def _deliver_whatsapp(self, action: dict[str, Any], message_text: str) -> str:
        """Send the scheduled message to the owner over WhatsApp.

        Uses the approved scheduled-notification template so the send works
        outside Meta's 24-hour service window, which is the normal case for a
        message scheduled hours ahead.
        """

        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        recipient_ref = normalize_text(payload.get("recipientWaId") or action.get("recipientRef"))
        if recipient_ref.lower() in OWNER_RECIPIENT_REFS:
            user_id = int(action.get("userId") or 0)
            if user_id <= 0:
                raise RuntimeError("Scheduled WhatsApp message is missing a user id.")
            connection = self.database.get_whatsapp_connection_by_user_id(user_id)
            if not connection:
                raise RuntimeError("No WhatsApp notification recipient is configured for this account.")
            recipient_ref = normalize_text(connection.get("ownerWaId"))

        if not recipient_ref:
            raise RuntimeError("WhatsApp recipient is missing.")

        return send_whatsapp_notification(
            recipient_wa_id=recipient_ref,
            message_text=message_text,
            template_name=self.config.whatsapp_template_name,
            template_language=self.config.whatsapp_template_language,
        )

    def _deliver_in_app(self, action: dict[str, Any], message_text: str) -> str:
        """Deliver the result to the owner's in-app notification feed."""

        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        user_id = int(action.get("userId") or 0)
        if user_id <= 0:
            raise RuntimeError("Scheduled action is missing a user id.")

        action_id = str(action.get("id") or "")
        title = normalize_text(payload.get("title")) or normalize_text(payload.get("label")) or "Scheduled action completed"

        notification = deliver_portal_notification(
            self.database,
            user_id=user_id,
            title=title,
            body=message_text,
            kind="scheduled_action",
            tone="success",
            source="scheduled_actions",
            feature_id=normalize_text(payload.get("featureId")),
            action_id=action_id,
            result_url=normalize_text(payload.get("resultUrl")),
            dedupe_key=f"scheduled-action:{action_id}" if action_id else "",
            metadata={
                "runAt": action.get("runAt"),
                "timezone": normalize_text(action.get("timezone")),
                "attemptCount": int(action.get("attemptCount") or 0),
            },
        )
        return f"portal-notification-{int(notification.get('id') or 0)}"

    def serve_forever(
        self,
        stop_event: threading.Event,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        logger = log or (lambda _message: None)
        while not stop_event.is_set():
            try:
                summary = self.run_pending()
                if int(summary.get("processed") or 0) > 0:
                    logger(
                        "[scheduled-actions] "
                        f"processed={summary.get('processed')} sent={summary.get('sent')} failed={summary.get('failed')}"
                    )
            except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
                logger(f"[scheduled-actions] error: {exc}")
            stop_event.wait(max(1, int(self.config.poll_seconds)))


__all__ = [
    "DEFAULT_SCHEDULED_ACTION_BATCH_SIZE",
    "DEFAULT_SCHEDULED_ACTION_POLL_SECONDS",
    "DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_LANGUAGE",
    "DEFAULT_SCHEDULED_WHATSAPP_TEMPLATE_NAME",
    "ScheduledActionConfig",
    "ScheduledActionScheduler",
    "describe_list_for_message",
    "load_scheduled_action_config",
]
