from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

from packages.infrastructure.portal_runtime_paths import resolve_portal_whatsapp_store_root
from packages.tools.whatsapp_reply_approval.server import DEFAULT_ASSISTANT_CONFIG
from packages.tools.whatsapp_reply_approval.server import BackendStore
from packages.tools.whatsapp_reply_approval.server import RuntimeConfig
from packages.tools.whatsapp_reply_approval.server import build_owner_confirmation_text
from packages.tools.whatsapp_reply_approval.server import build_owner_edit_prompt_text
from packages.tools.whatsapp_reply_approval.server import build_owner_help_text
from packages.tools.whatsapp_reply_approval.server import build_owner_interactive_payload
from packages.tools.whatsapp_reply_approval.server import build_owner_notification_text
from packages.tools.whatsapp_reply_approval.server import build_owner_skip_text
from packages.tools.whatsapp_reply_approval.server import extract_inbound_events
from packages.tools.whatsapp_reply_approval.server import normalize_bool
from packages.tools.whatsapp_reply_approval.server import normalize_text
from packages.tools.whatsapp_reply_approval.server import normalize_whatsapp_id
from packages.tools.whatsapp_reply_approval.server import parse_owner_command_text
from packages.tools.whatsapp_reply_approval.server import render_approval_page
from packages.tools.whatsapp_reply_approval.server import render_dashboard
from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message
from packages.tools.whatsapp_reply_approval.server import short_ref
from packages.tools.whatsapp_reply_approval.server import verify_whatsapp_signature


def build_portal_runtime_config(
    *,
    client_id: str,
    client_name: str,
    base_url: str,
    phone_number_id: str,
    owner_wa_id: str,
    data_path: Path,
    assistant: dict[str, Any] | None = None,
) -> RuntimeConfig:
    assistant_config = {**DEFAULT_ASSISTANT_CONFIG, **(assistant or {})}
    return RuntimeConfig(
        client_id=normalize_text(client_id) or "portal-user",
        client_name=normalize_text(client_name) or "Portal User",
        base_url=normalize_text(base_url).rstrip("/"),
        verify_token=normalize_text(os.getenv("WHATSAPP_VERIFY_TOKEN")),
        access_token=normalize_text(os.getenv("WHATSAPP_ACCESS_TOKEN")),
        phone_number_id=normalize_text(phone_number_id),
        app_secret=normalize_text(os.getenv("WHATSAPP_APP_SECRET")),
        api_version=normalize_text(os.getenv("WHATSAPP_API_VERSION") or "v20.0"),
        allow_mock_send=normalize_bool(os.getenv("WHATSAPP_ALLOW_MOCK_SEND"), default=True),
        owner_wa_id=normalize_text(owner_wa_id),
        data_path=data_path,
        assistant=assistant_config,
    )


def portal_whatsapp_store_path_for_connection(root: Path, connection: dict[str, Any]) -> Path:
    user_id = int(connection.get("userId") or 0)
    if user_id > 0:
        identifier = f"user-{user_id}"
    else:
        identifier = (
            re.sub(r"[^a-z0-9]+", "-", str(connection.get("email") or "portal-user").lower()).strip("-")
            or "portal-user"
        )
    store_root = resolve_portal_whatsapp_store_root(root=root)
    return store_root / f"{identifier}.json"


def delete_portal_whatsapp_store_for_connection(
    *,
    root: Path,
    connection: dict[str, Any],
    store_cache: dict[str, BackendStore] | None = None,
    store_lock: Any | None = None,
) -> Path:
    data_path = portal_whatsapp_store_path_for_connection(root, connection).resolve()
    cache_key = str(data_path)

    if store_cache is not None:
        if store_lock is None:
            store_cache.pop(cache_key, None)
        else:
            with store_lock:
                store_cache.pop(cache_key, None)

    try:
        data_path.unlink()
    except FileNotFoundError:
        pass

    return data_path


def build_portal_service_from_connection(
    *,
    root: Path,
    connection: dict[str, Any],
    base_url: str,
    store_cache: dict[str, BackendStore] | None = None,
    store_lock: Any | None = None,
) -> "PortalWhatsAppService":
    metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
    assistant = metadata.get("assistant") if isinstance(metadata.get("assistant"), dict) else None
    data_path = portal_whatsapp_store_path_for_connection(root, connection)
    config = build_portal_runtime_config(
        client_id=f"portal-user-{int(connection.get('userId') or 0) or 'unknown'}",
        client_name=normalize_text(connection.get("displayName"))
        or normalize_text(connection.get("verifiedName"))
        or normalize_text(connection.get("email"))
        or "Portal user",
        base_url=normalize_text(base_url).rstrip("/"),
        phone_number_id=normalize_text(connection.get("phoneNumberId")),
        owner_wa_id=normalize_text(connection.get("ownerWaId")),
        data_path=data_path,
        assistant=assistant,
    )

    if store_cache is None:
        return PortalWhatsAppService(config, BackendStore(data_path))

    resolved_path = data_path.resolve()
    cache_key = str(resolved_path)
    if store_lock is None:
        store = store_cache.get(cache_key)
        if store is None:
            store = BackendStore(resolved_path)
            store_cache[cache_key] = store
    else:
        with store_lock:
            store = store_cache.get(cache_key)
            if store is None:
                store = BackendStore(resolved_path)
                store_cache[cache_key] = store

    return PortalWhatsAppService(config, store)


def build_sample_owner_notification_text(client_name: str) -> str:
    workspace_label = normalize_text(client_name) or "your workspace"
    lines = [
        "Sample reply alert from Assistyca",
        "",
        f"This is a test message for {workspace_label}.",
        "",
        "Example customer: Maya Cohen",
        "Example message: Hi, are you available tomorrow afternoon?",
        "Example suggested reply: Hi Maya, yes, I can help. What time works best for you?",
        "",
        "Nothing was sent to a customer. This sample only confirms we can reach your WhatsApp.",
    ]
    return "\n".join(lines)


class PortalWhatsAppService:
    def __init__(self, config: RuntimeConfig, store: BackendStore):
        self.config = config
        self.store = store

    def is_owner_sender(self, sender_wa_id: str) -> bool:
        owner_wa_id = normalize_whatsapp_id(self.config.owner_wa_id)
        return bool(owner_wa_id and normalize_whatsapp_id(sender_wa_id) == owner_wa_id)

    def verify_signature(self, body: bytes, signature_header: str | None) -> bool:
        return verify_whatsapp_signature(self.config.app_secret, body, signature_header)

    def send_owner_message(
        self,
        approval: dict[str, Any] | None,
        *,
        message_text: str | None = None,
        interactive: dict[str, Any] | None = None,
    ) -> str:
        owner_wa_id = normalize_whatsapp_id(self.config.owner_wa_id)
        if not owner_wa_id:
            raise RuntimeError("Owner WhatsApp ID is not configured.")

        if self.config.live_send_enabled:
            message_id = send_whatsapp_message(
                access_token=self.config.access_token,
                phone_number_id=self.config.phone_number_id,
                api_version=self.config.api_version,
                recipient_wa_id=owner_wa_id,
                message_text=message_text,
                interactive=interactive,
            )
        elif self.config.allow_mock_send:
            message_id = f"mock-{uuid.uuid4().hex}"
        else:
            raise RuntimeError("Live WhatsApp send is not configured.")

        if approval is not None and approval.get("approval_id"):
            self.store.append_approval_message_id(str(approval["approval_id"]), message_id)
        return message_id

    def notify_owner_about_approval(self, approval: dict[str, Any]) -> str:
        notification_text = build_owner_notification_text(approval)
        interactive = build_owner_interactive_payload(approval)
        message_id = self.send_owner_message(approval, message_text=notification_text, interactive=interactive)
        self.store.update_approval(
            str(approval["approval_id"]),
            {
                "owner_notification_message_id": message_id,
                "owner_notification_text": notification_text,
                "owner_state": "pending",
            },
        )
        return message_id

    def notify_owner_edit_prompt(self, approval: dict[str, Any]) -> str:
        prompt_text = build_owner_edit_prompt_text(approval)
        message_id = self.send_owner_message(approval, message_text=prompt_text)
        self.store.update_approval(
            str(approval["approval_id"]),
            {
                "owner_edit_prompt_message_id": message_id,
                "owner_edit_prompt_text": prompt_text,
                "owner_state": "awaiting_edit",
            },
        )
        return message_id

    def notify_owner_confirmation(self, approval: dict[str, Any], reply_text: str) -> str:
        confirmation_text = build_owner_confirmation_text(approval, reply_text)
        message_id = self.send_owner_message(approval, message_text=confirmation_text)
        self.store.update_approval(
            str(approval["approval_id"]),
            {
                "owner_confirmation_message_id": message_id,
                "owner_confirmation_text": confirmation_text,
                "owner_state": "sent",
            },
        )
        return message_id

    def notify_owner_skip(self, approval: dict[str, Any]) -> str:
        skip_text = build_owner_skip_text(approval)
        message_id = self.send_owner_message(approval, message_text=skip_text)
        self.store.update_approval(
            str(approval["approval_id"]),
            {
                "owner_skip_message_id": message_id,
                "owner_skip_text": skip_text,
                "owner_state": "skipped",
            },
        )
        return message_id

    def send_sample_owner_message(self) -> tuple[str, str]:
        if not self.config.live_send_enabled:
            raise RuntimeError(
                "Finish WhatsApp setup with a working backend access token before sending a sample."
            )

        message_text = build_sample_owner_notification_text(self.config.client_name)
        message_id = self.send_owner_message(None, message_text=message_text)
        return message_id, message_text

    def resolve_owner_target_approval(self, event: dict[str, Any]) -> dict[str, Any] | None:
        context_id = normalize_text(event.get("reply_to_message_id"))
        if context_id:
            approval = self.store.find_approval_by_message_id(context_id)
            if approval is not None:
                return approval

        interactive_reply = event.get("interactive_reply", {})
        if isinstance(interactive_reply, dict):
            interactive_id = normalize_text(interactive_reply.get("id"))
            if interactive_id:
                match = re.match(r"^approval:([0-9a-f]+):(send|edit|skip)$", interactive_id)
                if match:
                    approval = self.store.find_approval_by_reference(match.group(1))
                    if approval is not None:
                        return approval
                approval = self.store.find_approval_by_message_id(interactive_id)
                if approval is not None:
                    return approval

        text = normalize_text(event.get("message_text"))
        ref_match = re.search(r"(?:ref|approval|id)\s*#?([0-9a-f]{6,})", text, flags=re.IGNORECASE)
        if ref_match:
            approval = self.store.find_approval_by_reference(ref_match.group(1))
            if approval is not None:
                return approval
        if text.startswith("#"):
            approval = self.store.find_approval_by_reference(text.lstrip("#"))
            if approval is not None:
                return approval

        awaiting_edit = self.store.list_approvals(status="awaiting_edit")
        if len(awaiting_edit) == 1:
            return awaiting_edit[0]

        pending = self.store.list_approvals(status="pending")
        if len(pending) == 1 and text.lower() in {"send", "approve", "skip", "cancel", "later"}:
            return pending[0]

        return None

    def send_reply_message(self, *, recipient_wa_id: str, reply_text: str) -> str:
        if self.config.live_send_enabled:
            return send_whatsapp_message(
                access_token=self.config.access_token,
                phone_number_id=self.config.phone_number_id,
                api_version=self.config.api_version,
                recipient_wa_id=recipient_wa_id,
                message_text=reply_text,
            )
        if self.config.allow_mock_send:
            return f"mock-{uuid.uuid4().hex}"
        raise RuntimeError("Live WhatsApp send is not configured.")

    def handle_customer_event(self, event: dict[str, Any]) -> dict[str, Any]:
        approval = self.store.record_inbound_message(
            thread_id=str(event["thread_id"]),
            sender_name=str(event["sender_name"]),
            sender_wa_id=str(event["sender_wa_id"]),
            message_text=str(event["message_text"]),
            source_message_id=str(event["source_message_id"]),
            message_type=str(event["message_type"]),
            raw_payload=event["raw_payload"],
            config=self.config,
        )
        owner_notification_id = ""
        owner_notification_error = ""
        if self.config.owner_wa_id:
            try:
                owner_notification_id = self.notify_owner_about_approval(approval)
            except Exception as exc:  # noqa: BLE001
                owner_notification_error = str(exc)
                self.store.update_approval(
                    str(approval["approval_id"]),
                    {
                        "owner_notification_error": owner_notification_error,
                        "owner_state": "pending",
                    },
                )
        stored_approval = self.store.get_approval(str(approval["approval_id"])) or approval
        return {
            "type": "customer",
            "approval": stored_approval,
            "owner_notification_message_id": owner_notification_id,
            "owner_notification_error": owner_notification_error,
        }

    def handle_owner_event(self, event: dict[str, Any]) -> dict[str, Any]:
        approval = self.resolve_owner_target_approval(event)
        command, argument = parse_owner_command_text(event.get("message_text", ""))
        interactive_reply = event.get("interactive_reply", {})
        if isinstance(interactive_reply, dict):
            interactive_id = normalize_text(interactive_reply.get("id"))
            if interactive_id.endswith(":send"):
                command = "send_suggested"
                argument = ""
            elif interactive_id.endswith(":edit"):
                command = "edit_request"
                argument = ""
            elif interactive_id.endswith(":skip"):
                command = "skip"
                argument = ""

        if approval is None and command == "send_reference_or_custom":
            approval = self.store.find_approval_by_reference(argument)

        if approval is None:
            help_text = build_owner_help_text(None)
            message_id = self.send_owner_message(None, message_text=help_text)
            return {"type": "owner", "action": "help", "message_id": message_id}

        if command == "help" and approval.get("status") == "awaiting_edit":
            command = "send_custom"
            argument = normalize_text(event.get("message_text"))

        if command == "send_reference_or_custom":
            referenced = self.store.find_approval_by_reference(argument)
            if referenced is not None:
                approval = referenced
                command = "send_suggested"
                argument = ""
            else:
                command = "help"

        approval_id = str(approval["approval_id"])
        current_status = normalize_text(approval.get("status"))
        if current_status in {"sent", "skipped"}:
            status_text = (
                f"Approval {short_ref(approval_id)} was already sent."
                if current_status == "sent"
                else f"Approval {short_ref(approval_id)} was skipped."
            )
            message_id = self.send_owner_message(approval, message_text=status_text)
            return {
                "type": "owner",
                "action": "already_sent" if current_status == "sent" else "already_skipped",
                "approval": approval,
                "message_id": message_id,
            }

        try:
            if command == "send_suggested":
                reply_text = normalize_text(approval.get("suggested_reply"))
                if not reply_text:
                    raise RuntimeError("Suggested reply is empty.")
                sent_message_id = self.send_reply_message(
                    recipient_wa_id=normalize_text(approval.get("sender_wa_id")),
                    reply_text=reply_text,
                )
                updated = self.store.mark_sent(approval_id, reply_text, sent_message_id)
                confirmation_id = self.notify_owner_confirmation(updated, reply_text)
                return {
                    "type": "owner",
                    "action": "send_suggested",
                    "approval": updated,
                    "sent_message_id": sent_message_id,
                    "confirmation_message_id": confirmation_id,
                }

            if command == "send_custom":
                reply_text = normalize_text(argument or event.get("message_text"))
                if not reply_text:
                    raise RuntimeError("Edited reply text is empty.")
                sent_message_id = self.send_reply_message(
                    recipient_wa_id=normalize_text(approval.get("sender_wa_id")),
                    reply_text=reply_text,
                )
                updated = self.store.mark_sent(approval_id, reply_text, sent_message_id)
                confirmation_id = self.notify_owner_confirmation(updated, reply_text)
                return {
                    "type": "owner",
                    "action": "send_custom",
                    "approval": updated,
                    "sent_message_id": sent_message_id,
                    "confirmation_message_id": confirmation_id,
                }

            if command == "edit_request":
                updated = self.store.mark_pending_edit(approval_id)
                prompt_id = self.notify_owner_edit_prompt(updated)
                return {
                    "type": "owner",
                    "action": "edit_request",
                    "approval": updated,
                    "prompt_message_id": prompt_id,
                }

            if command == "skip":
                updated = self.store.mark_skipped(approval_id)
                confirmation_id = self.notify_owner_skip(updated)
                return {
                    "type": "owner",
                    "action": "skip",
                    "approval": updated,
                    "confirmation_message_id": confirmation_id,
                }
        except Exception as exc:  # noqa: BLE001
            error_text = f"Could not complete approval {short_ref(approval_id)}: {exc}"
            if self.config.owner_wa_id:
                try:
                    self.send_owner_message(approval, message_text=error_text)
                except Exception:
                    pass
            return {
                "type": "owner",
                "action": "error",
                "approval": approval,
                "error": str(exc),
            }

        help_text = build_owner_help_text(approval)
        message_id = self.send_owner_message(approval, message_text=help_text)
        return {"type": "owner", "action": "help", "approval": approval, "message_id": message_id}

    def process_webhook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        events = extract_inbound_events(payload)
        approvals: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        for event in events:
            try:
                if self.is_owner_sender(str(event["sender_wa_id"])):
                    results.append(self.handle_owner_event(event))
                    continue

                result = self.handle_customer_event(event)
                approvals.append(result["approval"])
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "type": "error",
                        "sender_wa_id": event.get("sender_wa_id", ""),
                        "thread_id": event.get("thread_id", ""),
                        "error": str(exc),
                    }
                )

        return {
            "ok": True,
            "client_id": self.config.client_id,
            "received": len(events),
            "approvals": approvals,
            "results": results,
        }

    def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_approvals(status=status)

    def list_threads(self) -> list[dict[str, Any]]:
        threads = list(self.store.data.get("threads", {}).values())
        threads.sort(key=lambda thread: thread.get("updated_at", ""), reverse=True)
        return threads

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return self.store.get_approval(approval_id)

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        return self.store.get_thread(thread_id)

    def render_dashboard_html(self) -> str:
        approvals = self.store.list_approvals(status="pending")
        return render_dashboard(self.config, approvals)

    def render_approval_page_html(
        self,
        approval_id: str,
        *,
        notice: str | None = None,
        notice_kind: str = "success",
    ) -> str:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise KeyError(f"Unknown approval id: {approval_id}")
        thread = self.store.get_thread(str(approval.get("thread_id"))) or {"messages": []}
        return render_approval_page(self.config, approval, thread, notice=notice, notice_kind=notice_kind)

    def send_approval(self, approval_id: str, reply_text: str) -> tuple[dict[str, Any], str]:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise KeyError(f"Unknown approval id: {approval_id}")

        normalized_reply_text = normalize_text(reply_text) or normalize_text(approval.get("suggested_reply"))
        if not normalized_reply_text:
            raise ValueError("Reply text is required.")

        sent_message_id = self.send_reply_message(
            recipient_wa_id=normalize_text(approval.get("sender_wa_id")),
            reply_text=normalized_reply_text,
        )
        updated = self.store.mark_sent(approval_id, normalized_reply_text, sent_message_id)
        return updated, sent_message_id
