#!/usr/bin/env python3
"""Reusable WhatsApp reply approval backend.

This module provides a small HTTP server that can:

- receive WhatsApp webhook callbacks
- create a suggested reply from the latest message and thread context
- notify the owner inside WhatsApp when a reply needs approval
- let the owner approve, edit, or skip the reply from WhatsApp

The implementation is intentionally dependency-light so it can run locally
without extra packages and still be deployed as a small shared service.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from string import Template
from typing import Any, Iterable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


DEFAULT_ASSISTANT_CONFIG = {
    "tone_guidance": "Warm, direct, and practical. Keep replies human, short, and grounded.",
    "reply_rules": "Acknowledge the request first. Ask one clarifying question only when needed. Never guess prices or availability.",
    "business_notes": "Service area, hours, pricing hints, and any details the agent should know before replying.",
    "escalation_guidance": "Hand off when the customer is upset, the answer needs a human decision, or the request is urgent.",
    "approval_guidance": "When a WhatsApp message arrives, send the owner a WhatsApp approval card with who sent it, the latest message, and one suggested reply. Keep the final send manual inside WhatsApp.",
    "example_replies": "Good: \"Yes, I can help. What is the address?\"\nBad: \"Sure, anything is possible.\"",
    "response_style": "balanced",
}

PAGE_STYLE = """
<style>
  :root {
    color-scheme: dark;
    --bg: #07111d;
    --bg-2: #0a1726;
    --card: rgba(11, 24, 38, 0.88);
    --card-soft: rgba(17, 36, 54, 0.82);
    --border: rgba(148, 163, 184, 0.18);
    --border-strong: rgba(148, 163, 184, 0.3);
    --text: #f5f7fb;
    --muted: #93a4bc;
    --accent: #6ee7d8;
    --accent-strong: #29c7b6;
    --warn: #f59e0b;
    --danger: #f87171;
    --success: #34d399;
    --bubble-in: rgba(24, 46, 71, 0.98);
    --bubble-out: rgba(23, 59, 55, 0.98);
    --shadow: 0 24px 60px rgba(0, 0, 0, 0.32);
  }

  * {
    box-sizing: border-box;
  }

  body {
    margin: 0;
    min-height: 100vh;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background:
      radial-gradient(circle at top left, rgba(110, 231, 216, 0.12), transparent 35%),
      radial-gradient(circle at top right, rgba(41, 199, 182, 0.12), transparent 28%),
      linear-gradient(180deg, var(--bg), var(--bg-2));
    color: var(--text);
  }

  a {
    color: inherit;
    text-decoration: none;
  }

  .shell {
    width: min(1120px, calc(100vw - 32px));
    margin: 0 auto;
    padding: 28px 0 44px;
  }

  .hero {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 16px;
    align-items: flex-start;
    margin-bottom: 22px;
  }

  .eyebrow {
    margin: 0 0 10px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 12px;
    color: var(--accent);
  }

  h1, h2, h3, p {
    margin-top: 0;
  }

  h1 {
    margin-bottom: 8px;
    font-size: clamp(28px, 4vw, 44px);
    line-height: 1.05;
  }

  .lede {
    max-width: 72ch;
    color: var(--muted);
    line-height: 1.55;
    margin-bottom: 0;
  }

  .banner-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: flex-end;
    align-items: center;
    margin-top: 6px;
  }

  .pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: rgba(15, 27, 41, 0.8);
    color: var(--text);
    font-size: 14px;
    line-height: 1;
  }

  .pill strong {
    font-weight: 700;
  }

  .pill.success {
    border-color: rgba(52, 211, 153, 0.26);
    color: #c8f5e3;
  }

  .pill.warn {
    border-color: rgba(245, 158, 11, 0.28);
    color: #fde0a6;
  }

  .grid {
    display: grid;
    gap: 18px;
  }

  .grid.dashboard {
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  }

  .card {
    background: linear-gradient(180deg, var(--card), rgba(8, 17, 29, 0.92));
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    border-radius: 24px;
    padding: 22px;
    backdrop-filter: blur(18px);
  }

  .card.soft {
    background: linear-gradient(180deg, var(--card-soft), rgba(8, 17, 29, 0.88));
  }

  .card h2,
  .card h3 {
    margin-bottom: 12px;
  }

  .stack {
    display: grid;
    gap: 14px;
  }

  .approval-card {
    display: grid;
    gap: 14px;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    color: var(--muted);
    font-size: 14px;
  }

  .meta .dot {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--border-strong);
  }

  .message-block {
    display: grid;
    gap: 10px;
  }

  .message-label {
    display: inline-flex;
    width: fit-content;
    padding: 7px 11px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.05);
    color: var(--muted);
    font-size: 12px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
  }

  .bubble {
    white-space: pre-wrap;
    border-radius: 18px;
    padding: 14px 16px;
    line-height: 1.5;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .bubble.incoming {
    background: var(--bubble-in);
  }

  .bubble.outgoing {
    background: var(--bubble-out);
  }

  .context-list {
    display: grid;
    gap: 10px;
  }

  .context-item {
    display: grid;
    gap: 4px;
    padding: 12px 14px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.06);
  }

  .context-item.inbound {
    border-color: rgba(41, 199, 182, 0.18);
  }

  .context-item.outbound,
  .context-item.assistant {
    border-color: rgba(110, 231, 216, 0.14);
  }

  .context-role {
    color: var(--muted);
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .form-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }

  .field {
    display: grid;
    gap: 8px;
  }

  .field label {
    color: var(--muted);
    font-size: 14px;
  }

  textarea {
    width: 100%;
    min-height: 170px;
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid var(--border);
    background: rgba(4, 12, 20, 0.82);
    color: var(--text);
    line-height: 1.55;
    font: inherit;
    resize: vertical;
    outline: none;
  }

  textarea:focus {
    border-color: rgba(110, 231, 216, 0.45);
    box-shadow: 0 0 0 4px rgba(41, 199, 182, 0.12);
  }

  .button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 44px;
    padding: 0 16px;
    border-radius: 999px;
    border: 1px solid transparent;
    font: inherit;
    font-weight: 700;
    cursor: pointer;
    transition: transform 120ms ease, border-color 120ms ease, background-color 120ms ease;
  }

  .button:hover {
    transform: translateY(-1px);
  }

  .button.primary {
    background: linear-gradient(135deg, var(--accent), var(--accent-strong));
    color: #05211e;
  }

  .button.ghost {
    background: rgba(255, 255, 255, 0.03);
    border-color: var(--border);
    color: var(--text);
  }

  .button.danger {
    background: rgba(248, 113, 113, 0.08);
    border-color: rgba(248, 113, 113, 0.22);
    color: #fecaca;
  }

  .button-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 4px;
  }

  .pending-list {
    display: grid;
    gap: 18px;
  }

  .pending-card {
    display: grid;
    gap: 14px;
  }

  .pending-card header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
  }

  .pending-card h3 {
    margin-bottom: 4px;
    font-size: 20px;
  }

  .pending-card .reply-preview {
    color: var(--muted);
    font-size: 14px;
    line-height: 1.5;
  }

  .split {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  }

  .notice {
    padding: 14px 16px;
    border-radius: 16px;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.03);
    color: var(--muted);
    line-height: 1.5;
  }

  .notice.success {
    border-color: rgba(52, 211, 153, 0.22);
    color: #c8f5e3;
  }

  .notice.warn {
    border-color: rgba(245, 158, 11, 0.24);
    color: #fde0a6;
  }

  .notice.error {
    border-color: rgba(248, 113, 113, 0.24);
    color: #fecaca;
  }

  .small {
    font-size: 13px;
    color: var(--muted);
  }

  code {
    padding: 0 6px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.06);
  }

  pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: "SFMono-Regular", ui-monospace, "Cascadia Code", Menlo, Consolas, monospace;
    font-size: 13px;
    line-height: 1.55;
    color: #d9e5f4;
  }

  .footer-note {
    margin-top: 16px;
    color: var(--muted);
    font-size: 13px;
  }
</style>
"""

BASE_LAYOUT = Template(
    """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>$title</title>
    $style
  </head>
  <body>
    <main class="shell">
      $body
    </main>
  </body>
</html>
"""
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def get_nested(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def read_json_file(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def slugify(value: str) -> str:
    cleaned = []
    for char in normalize_text(value).lower():
        if char.isalnum():
            cleaned.append(char)
        elif cleaned and cleaned[-1] != "-":
            cleaned.append("-")
    return "".join(cleaned).strip("-") or "client"


def split_lines(value: Any) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def text_has_any(text: str, needles: Iterable[str]) -> bool:
    haystack = text.lower()
    return any(needle in haystack for needle in needles)


def humanize_timestamp(value: str | None) -> str:
    if not value:
        return "just now"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%b %d, %H:%M")
    except ValueError:
        return value


def escape_attr(value: Any) -> str:
    return escape(str(value or ""), quote=True)


def short_ref(value: str, length: int = 6) -> str:
    cleaned = normalize_text(value).replace("-", "")
    if len(cleaned) <= length:
        return cleaned.upper()
    return cleaned[:length].upper()


def normalize_whatsapp_id(value: Any) -> str:
    return re.sub(r"\D", "", normalize_text(value))


@dataclass
class RuntimeConfig:
    client_id: str
    client_name: str
    base_url: str
    verify_token: str
    access_token: str
    phone_number_id: str
    app_secret: str
    api_version: str
    allow_mock_send: bool
    owner_wa_id: str
    data_path: Path
    assistant: dict[str, Any] = field(default_factory=dict)

    @property
    def live_send_enabled(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    @classmethod
    def load(
        cls,
        config_path: Path | None,
        host: str,
        port: int,
        overrides: dict[str, Any] | None = None,
    ) -> "RuntimeConfig":
        overrides = overrides or {}
        file_data = read_json_file(config_path)
        merged = {**file_data, **overrides}

        client = merged.get("client", {}) if isinstance(merged.get("client", {}), dict) else {}
        web = merged.get("web", {}) if isinstance(merged.get("web", {}), dict) else {}
        whatsapp = merged.get("whatsapp", {}) if isinstance(merged.get("whatsapp", {}), dict) else {}
        assistant = merged.get("assistant", {}) if isinstance(merged.get("assistant", {}), dict) else {}
        storage = merged.get("storage", {}) if isinstance(merged.get("storage", {}), dict) else {}

        client_id = normalize_text(
            os.getenv("CLIENT_ID")
            or client.get("id")
            or merged.get("client_id")
            or (config_path.stem if config_path else "client")
        )
        client_name = normalize_text(
            os.getenv("CLIENT_NAME")
            or client.get("name")
            or merged.get("client_name")
            or client_id.replace("-", " ").title()
        )

        if not client_name:
            client_name = client_id.replace("-", " ").title()

        base_url = normalize_text(
            os.getenv("PUBLIC_BASE_URL")
            or web.get("base_url")
            or merged.get("base_url")
            or f"http://{host}:{port}"
        ).rstrip("/")
        if not base_url:
            base_url = f"http://{host}:{port}"

        verify_token = normalize_text(os.getenv("WHATSAPP_VERIFY_TOKEN"))
        access_token = normalize_text(os.getenv("WHATSAPP_ACCESS_TOKEN"))
        phone_number_id = normalize_text(
            os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            or whatsapp.get("phone_number_id")
            or merged.get("phone_number_id")
        )
        app_secret = normalize_text(os.getenv("WHATSAPP_APP_SECRET"))
        owner_wa_id = normalize_text(
            os.getenv("WHATSAPP_OWNER_WA_ID")
            or whatsapp.get("owner_wa_id")
            or merged.get("owner_wa_id")
        )
        api_version = normalize_text(
            os.getenv("WHATSAPP_API_VERSION")
            or whatsapp.get("api_version")
            or merged.get("api_version")
            or "v20.0"
        )
        allow_mock_send = normalize_bool(
            os.getenv("WHATSAPP_ALLOW_MOCK_SEND")
            if os.getenv("WHATSAPP_ALLOW_MOCK_SEND") is not None
            else whatsapp.get("allow_mock_send", merged.get("allow_mock_send", True)),
            default=True,
        )

        default_data_path = os.getenv(
            "WHATSAPP_STORE_PATH",
            str(storage.get("data_path") or merged.get("data_path") or f".agents/whatsapp-reply-approval/{client_id}.json"),
        )
        data_path = Path(default_data_path)
        if not data_path.is_absolute():
            data_path = Path.cwd() / data_path

        assistant_config = {**DEFAULT_ASSISTANT_CONFIG, **assistant}
        assistant_config["tone_guidance"] = normalize_text(assistant_config.get("tone_guidance"))
        assistant_config["reply_rules"] = normalize_text(assistant_config.get("reply_rules"))
        assistant_config["business_notes"] = normalize_text(assistant_config.get("business_notes"))
        assistant_config["escalation_guidance"] = normalize_text(assistant_config.get("escalation_guidance"))
        assistant_config["approval_guidance"] = normalize_text(assistant_config.get("approval_guidance"))
        assistant_config["example_replies"] = normalize_text(assistant_config.get("example_replies"))
        assistant_config["response_style"] = normalize_text(assistant_config.get("response_style") or "balanced").lower()

        return cls(
            client_id=client_id,
            client_name=client_name,
            base_url=base_url,
            verify_token=verify_token,
            access_token=access_token,
            phone_number_id=phone_number_id,
            app_secret=app_secret,
            api_version=api_version,
            allow_mock_send=allow_mock_send,
            owner_wa_id=owner_wa_id,
            data_path=data_path,
            assistant=assistant_config,
        )


class BackendStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"threads": {}, "approvals": {}}

        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {"threads": {}, "approvals": {}}

        if not isinstance(loaded, dict):
            return {"threads": {}, "approvals": {}}

        loaded.setdefault("threads", {})
        loaded.setdefault("approvals", {})
        return loaded

    def save(self) -> None:
        write_json_atomic(self.path, self.data)

    def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            approvals = list(self.data.get("approvals", {}).values())
            if status:
                approvals = [approval for approval in approvals if approval.get("status") == status]
            approvals.sort(key=lambda approval: approval.get("created_at", ""), reverse=True)
            return approvals

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.lock:
            approval = self.data.get("approvals", {}).get(approval_id)
            if approval is None:
                return None
            return json.loads(json.dumps(approval))

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self.lock:
            thread = self.data.get("threads", {}).get(thread_id)
            if thread is None:
                return None
            return json.loads(json.dumps(thread))

    def update_approval(self, approval_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            approvals = self.data.setdefault("approvals", {})
            approval = approvals.get(approval_id)
            if approval is None:
                raise KeyError(f"Unknown approval id: {approval_id}")
            approval.update(updates)
            approval["updated_at"] = now_iso()
            self.save()
            return json.loads(json.dumps(approval))

    def append_approval_message_id(self, approval_id: str, message_id: str) -> dict[str, Any]:
        with self.lock:
            approvals = self.data.setdefault("approvals", {})
            approval = approvals.get(approval_id)
            if approval is None:
                raise KeyError(f"Unknown approval id: {approval_id}")
            message_id = normalize_text(message_id)
            if message_id:
                owner_message_ids = approval.setdefault("owner_message_ids", [])
                if message_id not in owner_message_ids:
                    owner_message_ids.append(message_id)
                approval["owner_last_message_id"] = message_id
                approval["updated_at"] = now_iso()
                self.save()
            return json.loads(json.dumps(approval))

    def mark_pending_edit(self, approval_id: str, prompt_message_id: str | None = None) -> dict[str, Any]:
        updates: dict[str, Any] = {
            "status": "awaiting_edit",
            "owner_state": "awaiting_edit",
            "owner_edit_requested_at": now_iso(),
        }
        if prompt_message_id:
            updates["owner_edit_prompt_message_id"] = normalize_text(prompt_message_id)
        return self.update_approval(approval_id, updates)

    def mark_skipped(self, approval_id: str) -> dict[str, Any]:
        approval = self.update_approval(
            approval_id,
            {
                "status": "skipped",
                "owner_state": "skipped",
                "skipped_at": now_iso(),
            },
        )
        thread = self.data.setdefault("threads", {}).get(approval.get("thread_id"))
        if thread is not None and thread.get("pending_approval_id") == approval_id:
            thread["pending_approval_id"] = ""
            thread["updated_at"] = now_iso()
            self.save()
        return approval

    def find_approval_by_message_id(self, message_id: str) -> dict[str, Any] | None:
        needle = normalize_text(message_id)
        if not needle:
            return None
        with self.lock:
            approvals = list(self.data.get("approvals", {}).values())
            for approval in approvals:
                known_ids = {
                    normalize_text(approval.get("approval_id")),
                    normalize_text(approval.get("source_message_id")),
                    normalize_text(approval.get("sent_message_id")),
                    normalize_text(approval.get("owner_notification_message_id")),
                    normalize_text(approval.get("owner_edit_prompt_message_id")),
                    normalize_text(approval.get("owner_last_message_id")),
                }
                known_ids.update(normalize_text(item) for item in approval.get("owner_message_ids", []))
                if needle in {item for item in known_ids if item}:
                    return json.loads(json.dumps(approval))
            return None

    def find_approval_by_reference(self, reference: str) -> dict[str, Any] | None:
        needle = normalize_text(reference).lstrip("#").lower()
        if not needle:
            return None
        with self.lock:
            approvals = list(self.data.get("approvals", {}).values())
            for approval in approvals:
                approval_id = normalize_text(approval.get("approval_id")).lower()
                if approval_id == needle or approval_id.startswith(needle):
                    return json.loads(json.dumps(approval))
                if short_ref(approval_id).lower() == needle:
                    return json.loads(json.dumps(approval))
            return None

    def record_inbound_message(
        self,
        *,
        thread_id: str,
        sender_name: str,
        sender_wa_id: str,
        message_text: str,
        source_message_id: str,
        message_type: str,
        raw_payload: dict[str, Any],
        config: RuntimeConfig,
    ) -> dict[str, Any]:
        with self.lock:
            threads = self.data.setdefault("threads", {})
            approvals = self.data.setdefault("approvals", {})
            thread = threads.get(thread_id)

            if thread is None:
                thread = {
                    "thread_id": thread_id,
                    "sender_name": sender_name or sender_wa_id,
                    "sender_wa_id": sender_wa_id,
                    "messages": [],
                    "latest_message": "",
                    "latest_message_id": "",
                    "pending_approval_id": "",
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
                threads[thread_id] = thread

            thread["sender_name"] = sender_name or thread.get("sender_name") or sender_wa_id
            thread["sender_wa_id"] = sender_wa_id

            inbound_record = {
                "message_id": source_message_id or f"inbound-{uuid.uuid4().hex}",
                "direction": "inbound",
                "message_type": message_type or "text",
                "text": message_text,
                "timestamp": now_iso(),
                "raw_payload": raw_payload,
            }
            thread.setdefault("messages", []).append(inbound_record)
            thread["latest_message"] = message_text
            thread["latest_message_id"] = inbound_record["message_id"]

            approval_id = uuid.uuid4().hex
            context = build_context(thread, limit=6)
            suggested_reply = generate_suggestion(message_text, context, config.assistant)
            approval_record = {
                "approval_id": approval_id,
                "thread_id": thread_id,
                "sender_name": thread["sender_name"],
                "sender_wa_id": sender_wa_id,
                "latest_message": message_text,
                "message_type": message_type or "text",
                "suggested_reply": suggested_reply,
                "context": context,
                "status": "pending",
                "owner_state": "pending",
                "owner_message_ids": [],
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "sent_message_id": "",
                "source_message_id": inbound_record["message_id"],
                "source_payload": raw_payload,
            }
            approvals[approval_id] = approval_record
            thread["pending_approval_id"] = approval_id
            thread.setdefault("messages", []).append(
                {
                    "message_id": f"suggestion-{approval_id}",
                    "direction": "assistant",
                    "message_type": "suggestion",
                    "text": suggested_reply,
                    "timestamp": now_iso(),
                    "approval_id": approval_id,
                }
            )
            thread["updated_at"] = now_iso()
            self.save()
            return json.loads(json.dumps(approval_record))

    def mark_sent(self, approval_id: str, reply_text: str, sent_message_id: str) -> dict[str, Any]:
        with self.lock:
            approvals = self.data.setdefault("approvals", {})
            approval = approvals.get(approval_id)
            if approval is None:
                raise KeyError(f"Unknown approval id: {approval_id}")

            if approval.get("status") == "sent" and approval.get("sent_message_id"):
                return approval

            approval["status"] = "sent"
            approval["owner_state"] = "sent"
            approval["updated_at"] = now_iso()
            approval["sent_message_id"] = sent_message_id
            approval["sent_text"] = reply_text
            approval["sent_at"] = now_iso()

            thread = self.data.setdefault("threads", {}).get(approval.get("thread_id"))
            if thread is not None:
                thread.setdefault("messages", []).append(
                    {
                        "message_id": sent_message_id or f"outbound-{approval_id}",
                        "direction": "outbound",
                        "message_type": "text",
                        "text": reply_text,
                        "timestamp": now_iso(),
                        "approval_id": approval_id,
                    }
                )
                if thread.get("pending_approval_id") == approval_id:
                    thread["pending_approval_id"] = ""
                thread["updated_at"] = now_iso()

            self.save()
            return json.loads(json.dumps(approval))


def build_context(thread: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    messages = thread.get("messages", [])[-limit:]
    context: list[dict[str, Any]] = []
    for message in messages:
        context.append(
            {
                "direction": message.get("direction", "inbound"),
                "message_type": message.get("message_type", "text"),
                "text": message.get("text", ""),
                "timestamp": message.get("timestamp", ""),
            }
        )
    return context


def generate_suggestion(message_text: str, context: list[dict[str, Any]], assistant: dict[str, Any]) -> str:
    latest_text = normalize_text(message_text)
    lowered = latest_text.lower()
    tone = normalize_text(assistant.get("tone_guidance", "")).lower()
    reply_style = normalize_text(assistant.get("response_style", "balanced")).lower()

    if text_has_any(lowered, ["available today", "available tomorrow", "available", "free today", "calendar", "schedule"]):
        reply = "One sec, checking my calendar right now."
    elif text_has_any(lowered, ["price", "cost", "quote", "how much", "charge", "estimate"]):
        reply = "I can help with that. I just need a couple of details first so I can give you the right price."
    elif text_has_any(lowered, ["urgent", "asap", "right now", "emergency", "stuck", "critical"]):
        reply = "I’m flagging this for immediate human follow-up so someone can help as fast as possible."
    elif text_has_any(lowered, ["resched", "move the appointment", "change the time", "another day"]):
        reply = "Yes, I can check that for you. What time window works best?"
    elif text_has_any(lowered, ["thanks", "thank you", "ok", "okay"]):
        reply = "Of course. I’m checking that now."
    else:
        reply = "Thanks for reaching out. Let me check and I’ll get back to you shortly."

    if ("friendly" in tone or "warm" in tone) and reply.startswith("Thanks for reaching out"):
        reply = f"{reply} Happy to help."

    if reply_style == "detailed":
        if text_has_any(lowered, ["urgent", "emergency"]):
            reply = f"{reply} I’ll make sure a person follows up as soon as possible."
        elif not reply.endswith("right away."):
            reply = f"{reply} Once I confirm, I’ll send the next step right away."

    if context and len(context) > 2 and "check" in reply.lower() and "again" not in reply.lower():
        reply = f"{reply} I’ll keep the thread updated."

    return reply


def verify_whatsapp_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret:
        return True
    if not header:
        return False
    try:
        prefix, provided = header.split("=", 1)
    except ValueError:
        return False
    if prefix.lower() != "sha256":
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, provided.strip())


def send_whatsapp_message(
    *,
    access_token: str,
    phone_number_id: str,
    api_version: str,
    recipient_wa_id: str,
    message_text: str | None = None,
    interactive: dict[str, Any] | None = None,
) -> str:
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_wa_id,
    }
    if interactive is not None:
        payload["type"] = "interactive"
        payload["interactive"] = interactive
    else:
        payload["type"] = "text"
        payload["text"] = {"preview_url": False, "body": message_text or ""}
    request = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp send failed: {exc.code} {error_body}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"WhatsApp send failed: {exc.reason}") from exc

    messages = response_payload.get("messages", [])
    if messages and isinstance(messages, list):
        first_message = messages[0] or {}
        message_id = normalize_text(first_message.get("id"))
        if message_id:
            return message_id

    return f"whatsapp-{uuid.uuid4().hex}"


def render_layout(title: str, body: str, subtitle: str | None = None) -> str:
    heading = f'<p class="eyebrow">WhatsApp Reply Approval Bot</p>' if subtitle is None else f'<p class="eyebrow">{escape(subtitle)}</p>'
    return BASE_LAYOUT.substitute(
        title=escape(title),
        style=PAGE_STYLE,
        body=f"""
        <div class="hero">
          <div>
            {heading}
            <h1>{escape(title)}</h1>
          </div>
        </div>
        {body}
        """,
    )


def render_dashboard(config: RuntimeConfig, approvals: list[dict[str, Any]], request_host: str | None = None) -> str:
    banner = (
        '<span class="pill success">Live send enabled</span>'
        if config.live_send_enabled
        else '<span class="pill warn">Mock send mode</span>'
    )
    helper_text = (
        "Live approvals are sent to the owner in WhatsApp. This page is a debug mirror."
        if not config.live_send_enabled
        else "Incoming WhatsApp messages are routed to the owner in WhatsApp. This page is only a debug mirror."
    )

    if not approvals:
        body = f"""
        <section class="card">
          <h2>No pending approvals yet</h2>
          <p class="lede">
            When WhatsApp webhooks arrive, the backend stores the thread and forwards the approval to WhatsApp.
          </p>
          <div class="notice {'warn' if not config.live_send_enabled else ''}">
            {escape(helper_text)}
          </div>
          <p class="footer-note">
            Webhook endpoint: <code>/webhooks/whatsapp</code> · Debug screen: <code>/approval/&lt;approval_id&gt;</code>
          </p>
        </section>
        """
        return render_layout(f"{config.client_name} · Approvals", body)

    cards = []
    for approval in approvals:
        approval_id = approval["approval_id"]
        sender_name = approval.get("sender_name") or approval.get("sender_wa_id") or "Customer"
        latest_message = approval.get("latest_message", "")
        suggested_reply = approval.get("suggested_reply", "")
        status = approval.get("status", "pending")
        created_at = humanize_timestamp(approval.get("created_at"))
        thread_context = approval.get("context", [])
        context_html = []
        for item in thread_context[-4:]:
            direction = normalize_text(item.get("direction", "inbound"))
            role = "Customer" if direction == "inbound" else "Assistant" if direction == "assistant" else "Owner"
            context_html.append(
                f"""
                <div class="context-item {escape_attr(direction)}">
                  <span class="context-role">{escape(role)} · {escape(direction)}</span>
                  <div>{escape(item.get("text", ""))}</div>
                </div>
                """
            )

        send_button_label = "Send"
        cards.append(
            f"""
            <article class="card pending-card">
              <header>
                <div>
                  <h3>{escape(sender_name)}</h3>
                  <div class="meta">
                    <span>{escape(status.title())}</span>
                    <span class="dot"></span>
                    <span>{escape(created_at)}</span>
                    <span class="dot"></span>
                    <span>{escape(approval.get("sender_wa_id", ""))}</span>
                  </div>
                </div>
                <a class="button ghost" href="/approval/{urllib_parse.quote(approval_id)}">Edit</a>
              </header>

              <div class="split">
                <div class="stack">
                  <div class="message-block">
                    <span class="message-label">Latest message</span>
                    <div class="bubble incoming">{escape(latest_message)}</div>
                  </div>

                  <div class="message-block">
                    <span class="message-label">Suggested reply</span>
                    <div class="bubble outgoing">{escape(suggested_reply)}</div>
                  </div>
                </div>

                <div class="stack">
                  <div class="message-block">
                    <span class="message-label">Conversation context</span>
                    <div class="context-list">
                      {''.join(context_html) if context_html else '<div class="notice">No additional context stored yet.</div>'}
                    </div>
                  </div>
                </div>
              </div>

              <div class="button-row">
                <form method="post" action="/approval/{urllib_parse.quote(approval_id)}/send">
                  <input type="hidden" name="reply_text" value="{escape_attr(suggested_reply)}" />
                  <button class="button primary" type="submit">{escape(send_button_label)}</button>
                </form>
                <a class="button ghost" href="/approval/{urllib_parse.quote(approval_id)}">Edit</a>
              </div>
            </article>
            """
        )

    body = f"""
    <section class="card soft">
      <div class="banner-row">
        {banner}
        <span class="pill">Client: <strong>{escape(config.client_name)}</strong></span>
        <span class="pill">Webhook: <code>/webhooks/whatsapp</code></span>
      </div>
      <p class="lede" style="margin-top: 16px;">
        {escape(helper_text)}
      </p>
    </section>

    <section class="pending-list" style="margin-top: 18px;">
      {''.join(cards)}
    </section>
    """
    return render_layout(f"{config.client_name} · Approvals", body)


def render_approval_page(
    config: RuntimeConfig,
    approval: dict[str, Any],
    thread: dict[str, Any],
    request_host: str | None = None,
    notice: str | None = None,
    notice_kind: str = "success",
) -> str:
    sender_name = approval.get("sender_name") or "Customer"
    sender_wa_id = approval.get("sender_wa_id") or ""
    latest_message = approval.get("latest_message", "")
    suggested_reply = approval.get("suggested_reply", "")
    approval_id = approval.get("approval_id")
    status = approval.get("status", "pending")

    context_items = thread.get("messages", [])[-8:]
    context_html = []
    for item in context_items:
        direction = normalize_text(item.get("direction", "inbound"))
        role = "Customer" if direction == "inbound" else "Assistant" if direction == "assistant" else "Owner"
        context_html.append(
            f"""
            <div class="context-item {escape_attr(direction)}">
              <span class="context-role">{escape(role)} · {escape(direction)}</span>
              <div>{escape(item.get("text", ""))}</div>
            </div>
            """
        )

    base_url = config.base_url.rstrip("/")
    edit_url = f"{base_url}/approval/{urllib_parse.quote(approval_id)}"
    notices = []
    if notice:
        notices.append(f'<div class="notice {escape_attr(notice_kind)}">{escape(notice)}</div>')
    if not config.live_send_enabled:
        notices.append(
            '<div class="notice warn">Live WhatsApp send is not configured yet, so Send will only work once the Meta connection flow has stored the token and phone number ID in the backend.</div>'
        )

    body = f"""
    <section class="grid" style="gap: 18px;">
      <article class="card approval-card">
        <div class="meta">
          <span class="pill">{escape(status.title())}</span>
          <span class="pill">{escape(sender_name)}</span>
          <span class="pill">{escape(sender_wa_id)}</span>
          <span class="pill">Edit URL: <code>{escape(edit_url)}</code></span>
        </div>

        {''.join(notices)}

        <div class="message-block">
          <span class="message-label">Latest message</span>
          <div class="bubble incoming">{escape(latest_message)}</div>
        </div>

        <form method="post" action="/approval/{urllib_parse.quote(str(approval_id))}/send" class="stack">
          <div class="field">
            <label for="reply_text">Suggested reply</label>
            <textarea id="reply_text" name="reply_text">{escape(suggested_reply)}</textarea>
          </div>

          <div class="button-row">
            <button class="button primary" type="submit">Send reply</button>
            <a class="button ghost" href="/">Back to dashboard</a>
          </div>
        </form>
      </article>

      <article class="card">
        <h2>Thread context</h2>
        <p class="lede">The owner can review the recent conversation before sending the final reply.</p>
        <div class="context-list">
          {''.join(context_html) if context_html else '<div class="notice">No conversation history stored yet.</div>'}
        </div>
        <p class="footer-note">
          This page is only a debug mirror. The real approval flow happens in WhatsApp.
        </p>
      </article>
    </section>
    """
    return render_layout(f"Approval · {sender_name}", body)


def render_confirmation_page(config: RuntimeConfig, approval: dict[str, Any]) -> str:
    body = f"""
    <section class="card">
      <div class="notice success">Message sent successfully.</div>
      <h2>Reply sent to {escape(approval.get("sender_name") or "customer")}</h2>
      <p class="lede">
        The reply text was marked as sent and recorded in the conversation thread.
      </p>
      <div class="message-block">
        <span class="message-label">Sent reply</span>
        <div class="bubble outgoing">{escape(approval.get("sent_text") or approval.get("suggested_reply") or "")}</div>
      </div>
      <p class="footer-note">
        Status: {escape(approval.get("status", "sent"))} · WhatsApp message id: <code>{escape(approval.get("sent_message_id", ""))}</code>
      </p>
      <div class="button-row">
        <a class="button ghost" href="/">Back to dashboard</a>
        <a class="button primary" href="/approval/{urllib_parse.quote(approval.get('approval_id', ''))}">Review again</a>
      </div>
    </section>
    """
    return render_layout(f"Sent · {config.client_name}", body)


def parse_form_encoded(body: bytes) -> dict[str, Any]:
    parsed = urllib_parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def parse_json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    loaded = json.loads(body.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def extract_inbound_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if "entry" in payload and isinstance(payload.get("entry"), list):
        for entry in payload.get("entry", []):
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []) or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                contacts = value.get("contacts", [])
                messages = value.get("messages", [])
                metadata = value.get("metadata", {})
                sender_name = ""
                sender_wa_id = ""
                if isinstance(contacts, list) and contacts:
                    contact = contacts[0] if isinstance(contacts[0], dict) else {}
                    sender_wa_id = normalize_text(contact.get("wa_id"))
                    profile = contact.get("profile", {}) if isinstance(contact.get("profile", {}), dict) else {}
                    sender_name = normalize_text(profile.get("name"))
                if isinstance(messages, list):
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        message_type = normalize_text(message.get("type")) or "text"
                        if message_type not in {"text", "image", "audio", "video", "document", "interactive", "location"}:
                            continue
                        message_text = extract_message_text(message)
                        reply_to_message_id = extract_message_context_id(message)
                        interactive_reply = extract_interactive_reply(message)
                        sender_wa_id = sender_wa_id or normalize_text(message.get("from"))
                        sender_name = sender_name or sender_wa_id
                        events.append(
                            {
                                "thread_id": sender_wa_id or normalize_text(message.get("from")),
                                "sender_name": sender_name,
                                "sender_wa_id": sender_wa_id or normalize_text(message.get("from")),
                                "message_text": message_text,
                                "message_type": message_type,
                                "source_message_id": normalize_text(message.get("id")),
                                "timestamp": normalize_text(message.get("timestamp")) or now_iso(),
                                "metadata": metadata,
                                "reply_to_message_id": reply_to_message_id,
                                "interactive_reply": interactive_reply,
                                "message_payload": message,
                                "raw_payload": payload,
                            }
                        )
    elif {"sender", "message"}.issubset(payload.keys()):
        sender = payload.get("sender", {}) if isinstance(payload.get("sender", {}), dict) else {}
        events.append(
            {
                "thread_id": normalize_text(sender.get("wa_id") or sender.get("phone") or sender.get("id") or "local-dev"),
                "sender_name": normalize_text(sender.get("name")) or normalize_text(sender.get("wa_id") or sender.get("phone") or "Customer"),
                "sender_wa_id": normalize_text(sender.get("wa_id") or sender.get("phone") or sender.get("id") or "local-dev"),
                "message_text": normalize_text(payload.get("message")),
                "message_type": normalize_text(payload.get("message_type") or "text"),
                "source_message_id": normalize_text(payload.get("message_id")),
                "timestamp": normalize_text(payload.get("timestamp")) or now_iso(),
                "metadata": {},
                "reply_to_message_id": normalize_text(payload.get("reply_to_message_id")),
                "interactive_reply": {},
                "message_payload": payload,
                "raw_payload": payload,
            }
        )

    return [event for event in events if event.get("thread_id") and event.get("message_text")]


def extract_status_error_message(status_payload: dict[str, Any]) -> str:
    errors = status_payload.get("errors", [])
    if not isinstance(errors, list):
        return ""

    parts: list[str] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        code = normalize_text(item.get("code"))
        title = normalize_text(item.get("title") or item.get("message"))
        details = ""
        error_data = item.get("error_data")
        if isinstance(error_data, dict):
            details = normalize_text(error_data.get("details"))
        chunk = " ".join(part for part in [code, title, details] if part).strip()
        if chunk:
            parts.append(chunk)

    return " | ".join(parts)


def extract_status_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if "entry" not in payload or not isinstance(payload.get("entry"), list):
        return events

    for entry in payload.get("entry", []):
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata", {})
            statuses = value.get("statuses", [])
            if not isinstance(statuses, list):
                continue
            for status_payload in statuses:
                if not isinstance(status_payload, dict):
                    continue
                status_name = normalize_text(status_payload.get("status")).lower()
                message_id = normalize_text(status_payload.get("id"))
                if not status_name or not message_id:
                    continue
                events.append(
                    {
                        "message_id": message_id,
                        "status": status_name,
                        "recipient_wa_id": normalize_text(status_payload.get("recipient_id")),
                        "timestamp": normalize_text(status_payload.get("timestamp")) or now_iso(),
                        "metadata": metadata if isinstance(metadata, dict) else {},
                        "error_message": extract_status_error_message(status_payload),
                        "raw_payload": payload,
                    }
                )

    return events


def extract_message_text(message: dict[str, Any]) -> str:
    text = get_nested(message, "text", "body", default="")
    if text:
        return normalize_text(text)

    button_reply = get_nested(message, "interactive", "button_reply", default={})
    if isinstance(button_reply, dict):
        title = normalize_text(button_reply.get("title"))
        if title:
            return title

    list_reply = get_nested(message, "interactive", "list_reply", default={})
    if isinstance(list_reply, dict):
        title = normalize_text(list_reply.get("title"))
        if title:
            return title

    caption = get_nested(message, "image", "caption", default="")
    if caption:
        return normalize_text(caption)

    if message.get("type") == "location":
        location = message.get("location", {})
        if isinstance(location, dict):
            name = normalize_text(location.get("name"))
            address = normalize_text(location.get("address"))
            return " ".join(part for part in [name, address] if part)

    return f"[{normalize_text(message.get('type') or 'message')}]"


def extract_message_context_id(message: dict[str, Any]) -> str:
    context = message.get("context", {})
    if isinstance(context, dict):
        return normalize_text(context.get("id"))
    return ""


def extract_interactive_reply(message: dict[str, Any]) -> dict[str, str]:
    interactive = message.get("interactive", {})
    if not isinstance(interactive, dict):
        return {"id": "", "title": "", "type": ""}

    button_reply = interactive.get("button_reply")
    if isinstance(button_reply, dict):
        return {
            "id": normalize_text(button_reply.get("id")),
            "title": normalize_text(button_reply.get("title")),
            "type": "button_reply",
        }

    list_reply = interactive.get("list_reply")
    if isinstance(list_reply, dict):
        return {
            "id": normalize_text(list_reply.get("id")),
            "title": normalize_text(list_reply.get("title")),
            "type": "list_reply",
        }

    return {"id": "", "title": "", "type": ""}


def build_owner_notification_text(approval: dict[str, Any]) -> str:
    sender_name = normalize_text(approval.get("sender_name") or approval.get("sender_wa_id") or "Customer")
    latest_message = normalize_text(approval.get("latest_message"))
    suggested_reply = normalize_text(approval.get("suggested_reply"))
    ref = short_ref(approval.get("approval_id", ""))
    lines = [
        f"Approval {ref} for {sender_name}",
        "",
        f"Customer: {latest_message}",
        "",
        f"Suggested reply: {suggested_reply}",
        "",
        "Tap Send to approve, Edit to send a revised reply, or Skip to leave it pending.",
    ]
    context = approval.get("context", [])
    if isinstance(context, list) and context:
        lines.append("")
        lines.append("Recent context:")
        for item in context[-4:]:
            if not isinstance(item, dict):
                continue
            direction = normalize_text(item.get("direction", "inbound"))
            role = "Customer" if direction == "inbound" else "You" if direction == "outbound" else "Bot"
            text = normalize_text(item.get("text"))
            if text:
                lines.append(f"- {role}: {text}")
    return "\n".join(lines)


def build_owner_interactive_payload(approval: dict[str, Any]) -> dict[str, Any]:
    approval_id = normalize_text(approval.get("approval_id"))
    return {
        "type": "button",
        "body": {"text": build_owner_notification_text(approval)},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": f"approval:{approval_id}:send", "title": "Send"}},
                {"type": "reply", "reply": {"id": f"approval:{approval_id}:edit", "title": "Edit"}},
                {"type": "reply", "reply": {"id": f"approval:{approval_id}:skip", "title": "Skip"}},
            ]
        },
    }


def build_owner_edit_prompt_text(approval: dict[str, Any]) -> str:
    sender_name = normalize_text(approval.get("sender_name") or approval.get("sender_wa_id") or "Customer")
    ref = short_ref(approval.get("approval_id", ""))
    return (
        f"Reply with the revised message for {sender_name} (ref {ref}). "
        "I’ll send exactly what you write."
    )


def build_owner_confirmation_text(approval: dict[str, Any], reply_text: str) -> str:
    sender_name = normalize_text(approval.get("sender_name") or approval.get("sender_wa_id") or "Customer")
    ref = short_ref(approval.get("approval_id", ""))
    return f"Sent to {sender_name} (ref {ref}). Used reply: {normalize_text(reply_text)}"


def build_owner_skip_text(approval: dict[str, Any]) -> str:
    sender_name = normalize_text(approval.get("sender_name") or approval.get("sender_wa_id") or "Customer")
    ref = short_ref(approval.get("approval_id", ""))
    return f"Skipped {sender_name} (ref {ref})."


def build_owner_help_text(approval: dict[str, Any] | None = None) -> str:
    if approval is None:
        return (
            "Send me a reply suggestion with Send, edit it with Edit, or skip it with Skip. "
            "If I need a specific approval, reply to the message I sent or include the approval ref."
        )
    sender_name = normalize_text(approval.get("sender_name") or approval.get("sender_wa_id") or "Customer")
    ref = short_ref(approval.get("approval_id", ""))
    return f"For {sender_name} (ref {ref}), tap Send, tap Edit and then send the revised text, or tap Skip."


def parse_owner_command_text(text: str) -> tuple[str, str]:
    normalized = normalize_text(text)
    lower = normalized.lower()
    if not normalized:
        return "help", ""
    if lower in {"send", "approve"}:
        return "send_suggested", ""
    if lower == "edit":
        return "edit_request", ""
    if lower.startswith("send:"):
        return "send_custom", normalized.split(":", 1)[1].strip()
    if lower.startswith("edit:") or lower.startswith("reply:"):
        return "send_custom", normalized.split(":", 1)[1].strip()
    if lower in {"skip", "cancel", "later"}:
        return "skip", ""
    if lower.startswith("send "):
        suffix = normalized.split(" ", 1)[1].strip()
        if suffix:
            return "send_reference_or_custom", suffix
        return "send_suggested", ""
    if lower.startswith("approve "):
        suffix = normalized.split(" ", 1)[1].strip()
        if suffix:
            return "send_reference_or_custom", suffix
        return "send_suggested", ""
    return "help", normalized


class WhatsAppApprovalHandler(BaseHTTPRequestHandler):
    server_version = "WhatsAppApproval/1.0"
    config: RuntimeConfig
    store: BackendStore

    def _config(self) -> RuntimeConfig:
        return self.server.config  # type: ignore[attr-defined]

    def _store(self) -> BackendStore:
        return self.server.store  # type: ignore[attr-defined]

    def is_owner_sender(self, sender_wa_id: str) -> bool:
        owner_wa_id = normalize_whatsapp_id(self._config().owner_wa_id)
        return bool(owner_wa_id and normalize_whatsapp_id(sender_wa_id) == owner_wa_id)

    def send_owner_message(
        self,
        approval: dict[str, Any] | None,
        *,
        message_text: str | None = None,
        interactive: dict[str, Any] | None = None,
    ) -> str:
        config = self._config()
        owner_wa_id = normalize_whatsapp_id(config.owner_wa_id)
        if not owner_wa_id:
            raise RuntimeError("Owner WhatsApp ID is not configured.")

        if config.live_send_enabled:
            message_id = send_whatsapp_message(
                access_token=config.access_token,
                phone_number_id=config.phone_number_id,
                api_version=config.api_version,
                recipient_wa_id=owner_wa_id,
                message_text=message_text,
                interactive=interactive,
            )
        elif config.allow_mock_send:
            message_id = f"mock-{uuid.uuid4().hex}"
        else:
            raise RuntimeError("Live WhatsApp send is not configured. Complete the WhatsApp connection setup in the backend first.")

        if approval is not None and approval.get("approval_id"):
            self._store().append_approval_message_id(approval["approval_id"], message_id)
        return message_id

    def notify_owner_about_approval(self, approval: dict[str, Any]) -> str:
        notification_text = build_owner_notification_text(approval)
        interactive = build_owner_interactive_payload(approval)
        message_id = self.send_owner_message(approval, message_text=notification_text, interactive=interactive)
        self._store().update_approval(
            approval["approval_id"],
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
        self._store().update_approval(
            approval["approval_id"],
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
        self._store().update_approval(
            approval["approval_id"],
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
        self._store().update_approval(
            approval["approval_id"],
            {
                "owner_skip_message_id": message_id,
                "owner_skip_text": skip_text,
                "owner_state": "skipped",
            },
        )
        return message_id

    def resolve_owner_target_approval(self, event: dict[str, Any]) -> dict[str, Any] | None:
        store = self._store()
        context_id = normalize_text(event.get("reply_to_message_id"))
        if context_id:
            approval = store.find_approval_by_message_id(context_id)
            if approval is not None:
                return approval

        interactive_reply = event.get("interactive_reply", {})
        if isinstance(interactive_reply, dict):
            interactive_id = normalize_text(interactive_reply.get("id"))
            if interactive_id:
                match = re.match(r"^approval:([0-9a-f]+):(send|edit|skip)$", interactive_id)
                if match:
                    approval = store.find_approval_by_reference(match.group(1))
                    if approval is not None:
                        return approval
                approval = store.find_approval_by_message_id(interactive_id)
                if approval is not None:
                    return approval

        text = normalize_text(event.get("message_text"))
        ref_match = re.search(r"(?:ref|approval|id)\s*#?([0-9a-f]{6,})", text, flags=re.IGNORECASE)
        if ref_match:
            approval = store.find_approval_by_reference(ref_match.group(1))
            if approval is not None:
                return approval
        if text.startswith("#"):
            approval = store.find_approval_by_reference(text.lstrip("#"))
            if approval is not None:
                return approval

        awaiting_edit = store.list_approvals(status="awaiting_edit")
        if len(awaiting_edit) == 1:
            return awaiting_edit[0]

        pending = store.list_approvals(status="pending")
        if len(pending) == 1 and text.lower() in {"send", "approve", "skip", "cancel", "later"}:
            return pending[0]

        return None

    def handle_customer_event(self, event: dict[str, Any]) -> dict[str, Any]:
        config = self._config()
        approval = self._store().record_inbound_message(
            thread_id=event["thread_id"],
            sender_name=event["sender_name"],
            sender_wa_id=event["sender_wa_id"],
            message_text=event["message_text"],
            source_message_id=event["source_message_id"],
            message_type=event["message_type"],
            raw_payload=event["raw_payload"],
            config=config,
        )
        owner_notification_id = ""
        owner_notification_error = ""
        if config.owner_wa_id:
            try:
                owner_notification_id = self.notify_owner_about_approval(approval)
            except Exception as exc:  # noqa: BLE001 - keep inbound processing resilient
                owner_notification_error = str(exc)
                self._store().update_approval(
                    approval["approval_id"],
                    {
                        "owner_notification_error": owner_notification_error,
                        "owner_state": "pending",
                    },
                )
        stored_approval = self._store().get_approval(approval["approval_id"]) or approval
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
            approval = self._store().find_approval_by_reference(argument)

        if approval is None:
            help_text = build_owner_help_text(None)
            message_id = self.send_owner_message(
                None,
                message_text=help_text,
            )
            return {"type": "owner", "action": "help", "message_id": message_id}

        if command == "help" and approval.get("status") == "awaiting_edit":
            command = "send_custom"
            argument = normalize_text(event.get("message_text"))

        if command == "send_reference_or_custom":
            referenced = self._store().find_approval_by_reference(argument)
            if referenced is not None:
                approval = referenced
                command = "send_suggested"
                argument = ""
            else:
                command = "help"

        approval_id = approval["approval_id"]
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
                    recipient_wa_id=approval.get("sender_wa_id", ""),
                    reply_text=reply_text,
                )
                updated = self._store().mark_sent(approval_id, reply_text, sent_message_id)
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
                    recipient_wa_id=approval.get("sender_wa_id", ""),
                    reply_text=reply_text,
                )
                updated = self._store().mark_sent(approval_id, reply_text, sent_message_id)
                confirmation_id = self.notify_owner_confirmation(updated, reply_text)
                return {
                    "type": "owner",
                    "action": "send_custom",
                    "approval": updated,
                    "sent_message_id": sent_message_id,
                    "confirmation_message_id": confirmation_id,
                }

            if command == "edit_request":
                updated = self._store().mark_pending_edit(approval_id)
                prompt_id = self.notify_owner_edit_prompt(updated)
                return {
                    "type": "owner",
                    "action": "edit_request",
                    "approval": updated,
                    "prompt_message_id": prompt_id,
                }

            if command == "skip":
                updated = self._store().mark_skipped(approval_id)
                confirmation_id = self.notify_owner_skip(updated)
                return {
                    "type": "owner",
                    "action": "skip",
                    "approval": updated,
                    "confirmation_message_id": confirmation_id,
                }
        except Exception as exc:  # noqa: BLE001 - surface failure to owner without dropping the webhook
            error_text = f"Could not complete approval {short_ref(approval_id)}: {exc}"
            if self._config().owner_wa_id:
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

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - BaseHTTPRequestHandler API
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib_parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            self.handle_dashboard()
            return
        if path == "/health":
            self.send_json({"ok": True, "client_id": self._config().client_id})
            return
        if path == "/webhooks/whatsapp":
            self.handle_webhook_verification(parsed)
            return
        if path.startswith("/approval/"):
            self.handle_approval_page(parsed)
            return
        if path.startswith("/api/approvals"):
            self.handle_api_get(parsed)
            return
        if path.startswith("/api/threads"):
            self.handle_api_get(parsed)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib_parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/webhooks/whatsapp":
            self.handle_webhook_ingest()
            return
        if path.startswith("/approval/"):
            self.handle_approval_submit(parsed)
            return
        if path.startswith("/api/approvals"):
            self.handle_api_submit(parsed)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length > 0 else b""

    def send_html(self, html_body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = html_body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def wants_json(self) -> bool:
        accept = self.headers.get("Accept", "")
        return "application/json" in accept

    def handle_dashboard(self) -> None:
        approvals = self._store().list_approvals(status="pending")
        self.send_html(render_dashboard(self._config(), approvals))

    def handle_approval_page(self, parsed: urllib_parse.ParseResult) -> None:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            self.send_error(HTTPStatus.NOT_FOUND, "Approval id missing")
            return
        approval_id = urllib_parse.unquote(parts[1])
        approval = self._store().get_approval(approval_id)
        if approval is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Approval not found")
            return
        thread = self._store().get_thread(approval.get("thread_id")) or {"messages": []}
        query = urllib_parse.parse_qs(parsed.query)
        notice = None
        notice_kind = "success"
        if query.get("sent"):
            notice = "Reply sent successfully."
        elif query.get("error"):
            notice = query.get("error", ["Something went wrong."])[0]
            notice_kind = "error"
        self.send_html(render_approval_page(self._config(), approval, thread, notice=notice, notice_kind=notice_kind))

    def handle_api_get(self, parsed: urllib_parse.ParseResult) -> None:
        path = parsed.path.rstrip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) == 2 and parts[-1] == "approvals":
            status = urllib_parse.parse_qs(parsed.query).get("status", [None])[0]
            self.send_json({
                "approvals": self._store().list_approvals(status=status),
                "client_id": self._config().client_id,
            })
            return
        if len(parts) == 2 and parts[-1] == "threads":
            threads = list(self._store().data.get("threads", {}).values())
            threads.sort(key=lambda thread: thread.get("updated_at", ""), reverse=True)
            self.send_json({"threads": threads, "client_id": self._config().client_id})
            return
        if len(parts) == 3 and parts[-2] == "approvals":
            approval = self._store().get_approval(urllib_parse.unquote(parts[-1]))
            if approval is None:
                self.send_json({"error": "Approval not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(approval)
            return
        if len(parts) == 3 and parts[-2] == "threads":
            thread = self._store().get_thread(urllib_parse.unquote(parts[-1]))
            if thread is None:
                self.send_json({"error": "Thread not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(thread)
            return

        self.send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def handle_api_submit(self, parsed: urllib_parse.ParseResult) -> None:
        path = parsed.path.rstrip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "approvals" or parts[3] != "send":
            self.send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        approval_id = urllib_parse.unquote(parts[2]) if parts[2] else ""
        self._send_approval(approval_id, as_json=True)

    def handle_approval_submit(self, parsed: urllib_parse.ParseResult) -> None:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 3 or parts[0] != "approval" or parts[2] != "send":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        approval_id = urllib_parse.unquote(parts[1])
        self._send_approval(approval_id, as_json=False)

    def _send_approval(self, approval_id: str, as_json: bool) -> None:
        approval = self._store().get_approval(approval_id)
        if approval is None:
            if as_json:
                self.send_json({"error": "Approval not found"}, status=HTTPStatus.NOT_FOUND)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Approval not found")
            return

        body = self.read_body()
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            payload = parse_json_body(body)
        else:
            payload = parse_form_encoded(body)

        reply_text = normalize_text(payload.get("reply_text")) or approval.get("suggested_reply", "")
        if not reply_text:
            error_message = "Reply text is required."
            if as_json:
                self.send_json({"error": error_message}, status=HTTPStatus.BAD_REQUEST)
            else:
                self.send_html(
                    render_approval_page(
                        self._config(),
                        approval,
                        self._store().get_thread(approval.get("thread_id")) or {"messages": []},
                        notice=error_message,
                        notice_kind="error",
                    ),
                    status=HTTPStatus.BAD_REQUEST,
                )
            return

        try:
            sent_message_id = self.send_reply_message(
                recipient_wa_id=approval.get("sender_wa_id", ""),
                reply_text=reply_text,
            )
            updated = self._store().mark_sent(approval_id, reply_text, sent_message_id)
        except Exception as exc:  # noqa: BLE001 - surfaced to user with context
            error_message = str(exc)
            if as_json:
                self.send_json({"error": error_message}, status=HTTPStatus.BAD_GATEWAY)
            else:
                thread = self._store().get_thread(approval.get("thread_id")) or {"messages": []}
                self.send_html(
                    render_approval_page(
                        self._config(),
                        approval,
                        thread,
                        notice=error_message,
                        notice_kind="error",
                    ),
                    status=HTTPStatus.BAD_GATEWAY,
                )
            return

        if as_json:
            self.send_json({"ok": True, "approval": updated, "sent_message_id": sent_message_id})
            return

        self.redirect(f"/approval/{urllib_parse.quote(approval_id)}?sent=1")

    def send_reply_message(self, *, recipient_wa_id: str, reply_text: str) -> str:
        config = self._config()
        if config.live_send_enabled:
            return send_whatsapp_message(
                access_token=config.access_token,
                phone_number_id=config.phone_number_id,
                api_version=config.api_version,
                recipient_wa_id=recipient_wa_id,
                message_text=reply_text,
            )
        if config.allow_mock_send:
            return f"mock-{uuid.uuid4().hex}"
        raise RuntimeError("Live WhatsApp send is not configured. Complete the WhatsApp connection setup in the backend first.")

    def handle_webhook_verification(self, parsed: urllib_parse.ParseResult) -> None:
        query = urllib_parse.parse_qs(parsed.query)
        mode = normalize_text(query.get("hub.mode", [""])[0])
        token = normalize_text(query.get("hub.verify_token", [""])[0])
        challenge = normalize_text(query.get("hub.challenge", [""])[0])
        config = self._config()

        if config.verify_token and token != config.verify_token:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid verify token")
            return

        if mode and mode != "subscribe":
            self.send_error(HTTPStatus.BAD_REQUEST, "Unexpected webhook mode")
            return

        payload = challenge or "ok"
        body = payload.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_webhook_ingest(self) -> None:
        config = self._config()
        body = self.read_body()

        if not verify_whatsapp_signature(config.app_secret, body, self.headers.get("X-Hub-Signature-256")):
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid WhatsApp signature")
            return

        try:
            payload = parse_json_body(body)
        except json.JSONDecodeError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {exc}")
            return

        events = extract_inbound_events(payload)
        approvals = []
        results = []
        for event in events:
            try:
                if self.is_owner_sender(event["sender_wa_id"]):
                    results.append(self.handle_owner_event(event))
                    continue

                result = self.handle_customer_event(event)
                approvals.append(result["approval"])
                results.append(result)
            except Exception as exc:  # noqa: BLE001 - keep webhook resilient
                results.append(
                    {
                        "type": "error",
                        "sender_wa_id": event.get("sender_wa_id", ""),
                        "thread_id": event.get("thread_id", ""),
                        "error": str(exc),
                    }
                )

        response = {
            "ok": True,
            "client_id": config.client_id,
            "received": len(events),
            "approvals": approvals,
            "results": results,
        }
        self.send_json(response)


def build_handler(config: RuntimeConfig, store: BackendStore):
    class BoundHandler(WhatsAppApprovalHandler):
        pass

    BoundHandler.config = config
    BoundHandler.store = store
    return BoundHandler


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the WhatsApp reply approval backend.")
    parser.add_argument("--config", type=Path, default=None, help="Path to backend JSON config.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8001")))
    parser.add_argument("--base-url", default=None, help="Override the public base URL used in approval links.")
    parser.add_argument("--data-path", type=Path, default=None, help="Override the JSON data store path.")
    return parser


def load_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    overrides: dict[str, Any] = {}
    if args.base_url:
        overrides.setdefault("web", {})["base_url"] = args.base_url
    if args.data_path:
        overrides.setdefault("storage", {})["data_path"] = str(args.data_path)

    config = RuntimeConfig.load(args.config, args.host, args.port, overrides=overrides)
    if args.data_path:
        config.data_path = args.data_path if args.data_path.is_absolute() else Path.cwd() / args.data_path
    if args.base_url:
        config.base_url = args.base_url.rstrip("/")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = create_argument_parser()
    args = parser.parse_args(argv)
    config = load_runtime_config(args)
    store = BackendStore(config.data_path)
    handler = build_handler(config, store)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.config = config  # type: ignore[attr-defined]
    server.store = store  # type: ignore[attr-defined]

    print(f"WhatsApp reply approval backend running on http://{args.host}:{args.port}")
    print(f"Dashboard: http://{args.host}:{args.port}/")
    print(f"Webhook:   http://{args.host}:{args.port}/webhooks/whatsapp")
    print(f"Data:      {config.data_path}")
    if config.live_send_enabled:
        print("Mode:      live send enabled")
    else:
        print("Mode:      mock send mode (set access token + phone number ID for live sending)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
