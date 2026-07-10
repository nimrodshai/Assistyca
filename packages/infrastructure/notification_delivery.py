"""Shared notification delivery helpers for portal-owned automations."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from dataclasses import field
from email.message import EmailMessage
from email.utils import formataddr
from email.utils import parseaddr
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message


DEFAULT_PRODUCT_NAME = "Assistyca"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_TIMEOUT = 10.0
DEFAULT_MAIL_PROVIDER = "smtp"
DEFAULT_WHATSAPP_API_VERSION = "v20.0"
RESEND_API_URL = "https://api.resend.com/emails"


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_email(value: Any) -> str:
    return normalize_text(value).lower()


def parse_bool(value: Any, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_email_address(value: Any) -> str:
    _, address = parseaddr(normalize_text(value))
    normalized = normalize_email(address)
    return normalized if normalized and "@" in normalized else ""


def build_sender_header(name: str, address: str) -> str:
    normalized_address = extract_email_address(address)
    if not normalized_address:
        return ""
    display_name = normalize_text(name)
    return formataddr((display_name, normalized_address)) if display_name else normalized_address


def normalize_mail_provider(value: Any) -> str:
    provider = normalize_text(value).lower()
    if provider in {"smtp", "resend", "auto"}:
        return provider
    return DEFAULT_MAIL_PROVIDER


def describe_resend_error(raw_body: str, status_code: int) -> str:
    message = ""
    raw = normalize_text(raw_body)
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        if isinstance(payload, dict):
            for key in ("message", "error", "name"):
                value = normalize_text(payload.get(key))
                if value:
                    message = value
                    break

            errors = payload.get("errors")
            if not message and isinstance(errors, list) and errors:
                first_error = errors[0]
                if isinstance(first_error, dict):
                    for key in ("message", "field", "code"):
                        value = normalize_text(first_error.get(key))
                        if value:
                            message = value
                            break
                elif isinstance(first_error, str):
                    message = normalize_text(first_error)

        if not message:
            message = raw

    return message or f"Resend returned HTTP {status_code}."


@dataclass
class SmtpDeliveryConfig:
    host: str = ""
    port: int = DEFAULT_SMTP_PORT
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = DEFAULT_PRODUCT_NAME
    use_ssl: bool = False
    starttls: bool = True
    timeout: float = DEFAULT_SMTP_TIMEOUT

    @property
    def configured(self) -> bool:
        return bool(self.host and extract_email_address(self.from_email))


@dataclass
class ResendDeliveryConfig:
    api_key: str = ""
    from_email: str = ""
    from_name: str = DEFAULT_PRODUCT_NAME

    @property
    def configured(self) -> bool:
        return bool(self.api_key and extract_email_address(self.from_email))


@dataclass
class MailDeliveryConfig:
    provider: str = DEFAULT_MAIL_PROVIDER
    product_name: str = DEFAULT_PRODUCT_NAME
    smtp: SmtpDeliveryConfig = field(default_factory=SmtpDeliveryConfig)
    resend: ResendDeliveryConfig = field(default_factory=ResendDeliveryConfig)


def load_mail_delivery_config() -> MailDeliveryConfig:
    return MailDeliveryConfig(
        provider=normalize_mail_provider(os.getenv("PORTAL_MAIL_PROVIDER", DEFAULT_MAIL_PROVIDER)),
        product_name=normalize_text(os.getenv("PORTAL_PRODUCT_NAME")) or DEFAULT_PRODUCT_NAME,
        smtp=SmtpDeliveryConfig(
            host=normalize_text(os.getenv("PORTAL_SMTP_HOST")),
            port=parse_int(os.getenv("PORTAL_SMTP_PORT"), DEFAULT_SMTP_PORT),
            username=normalize_text(os.getenv("PORTAL_SMTP_USERNAME")),
            password=normalize_text(os.getenv("PORTAL_SMTP_PASSWORD")),
            from_email=normalize_text(os.getenv("PORTAL_SMTP_FROM_EMAIL")),
            from_name=normalize_text(os.getenv("PORTAL_SMTP_FROM_NAME")) or DEFAULT_PRODUCT_NAME,
            use_ssl=parse_bool(os.getenv("PORTAL_SMTP_SSL"), default=False),
            starttls=parse_bool(os.getenv("PORTAL_SMTP_STARTTLS"), default=True),
            timeout=float(parse_int(os.getenv("PORTAL_SMTP_TIMEOUT"), int(DEFAULT_SMTP_TIMEOUT))),
        ),
        resend=ResendDeliveryConfig(
            api_key=normalize_text(os.getenv("PORTAL_RESEND_API_KEY")),
            from_email=normalize_text(os.getenv("PORTAL_RESEND_FROM_EMAIL")),
            from_name=normalize_text(os.getenv("PORTAL_RESEND_FROM_NAME")) or DEFAULT_PRODUCT_NAME,
        ),
    )


def email_delivery_available(config: MailDeliveryConfig | None = None) -> bool:
    resolved = config or load_mail_delivery_config()
    provider = normalize_mail_provider(resolved.provider)
    if provider == "resend":
        return resolved.resend.configured
    if provider == "smtp":
        return resolved.smtp.configured
    return resolved.resend.configured or resolved.smtp.configured


def telegram_delivery_available() -> bool:
    return bool(normalize_text(os.getenv("TELEGRAM_BOT_TOKEN")))


def whatsapp_delivery_available() -> bool:
    return bool(normalize_text(os.getenv("WHATSAPP_ACCESS_TOKEN")))


def build_email_message(
    *,
    config: MailDeliveryConfig,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str = "",
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = normalize_text(subject) or f"{config.product_name} notification"
    sender = build_sender_header(
        config.smtp.from_name or config.resend.from_name or config.product_name,
        config.smtp.from_email or config.resend.from_email,
    )
    if not sender:
        raise RuntimeError("Email sender is not configured.")
    recipient = extract_email_address(to_email)
    if not recipient:
        raise RuntimeError("A valid destination email address is required.")

    message["From"] = sender
    message["To"] = recipient
    message.set_content(text_body or "")
    if normalize_text(html_body):
        message.add_alternative(html_body, subtype="html")
    return message


def send_email_notification(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str = "",
    config: MailDeliveryConfig | None = None,
) -> None:
    resolved = config or load_mail_delivery_config()
    provider = normalize_mail_provider(resolved.provider)

    if provider == "resend":
        _send_email_via_resend(
            resolved,
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        return

    if provider == "auto" and resolved.resend.configured:
        _send_email_via_resend(
            resolved,
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        return

    if provider == "auto" and resolved.smtp.configured:
        _send_email_via_smtp(
            resolved,
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        return

    if provider == "smtp":
        _send_email_via_smtp(
            resolved,
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        return

    raise RuntimeError(
        "Email delivery is not configured. Set PORTAL_RESEND_API_KEY and PORTAL_RESEND_FROM_EMAIL, "
        "or PORTAL_SMTP_HOST and PORTAL_SMTP_FROM_EMAIL."
    )


def _send_email_via_smtp(
    config: MailDeliveryConfig,
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    if not config.smtp.configured:
        raise RuntimeError("SMTP is not configured.")

    message = build_email_message(
        config=config,
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
    smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    if config.smtp.use_ssl:
        smtp = smtplib.SMTP_SSL(
            config.smtp.host,
            config.smtp.port,
            timeout=config.smtp.timeout,
            context=ssl.create_default_context(),
        )
    else:
        smtp = smtplib.SMTP(config.smtp.host, config.smtp.port, timeout=config.smtp.timeout)

    try:
        smtp.ehlo()
        if not config.smtp.use_ssl and config.smtp.starttls:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if config.smtp.username:
            smtp.login(config.smtp.username, config.smtp.password)
        smtp.send_message(message)
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass


def _send_email_via_resend(
    config: MailDeliveryConfig,
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    if not config.resend.configured:
        raise RuntimeError("Resend is not configured.")

    sender = build_sender_header(config.resend.from_name, config.resend.from_email)
    if not sender:
        raise RuntimeError("PORTAL_RESEND_FROM_EMAIL must be a valid sender email.")

    recipient = extract_email_address(to_email)
    if not recipient:
        raise RuntimeError("A valid destination email address is required.")

    payload = {
        "from": sender,
        "to": [recipient],
        "subject": normalize_text(subject) or f"{config.product_name} notification",
        "text": text_body or "",
        "html": normalize_text(html_body) or f"<pre>{text_body or ''}</pre>",
    }
    request = urllib_request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.resend.api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"{config.product_name}/1.0",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=config.smtp.timeout) as response:
            response.read()
    except urllib_error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Could not send the email via Resend: {describe_resend_error(raw_body, exc.code)}") from exc
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Could not send the email via Resend: {reason}") from exc


def send_telegram_notification(*, chat_id: str, text: str, bot_token: str | None = None) -> dict[str, Any]:
    resolved_chat_id = normalize_text(chat_id)
    if not resolved_chat_id:
        raise RuntimeError("Telegram delivery requires a chat id.")

    resolved_bot_token = normalize_text(bot_token) or normalize_text(os.getenv("TELEGRAM_BOT_TOKEN"))
    if not resolved_bot_token:
        raise RuntimeError("Telegram delivery is not configured. Set TELEGRAM_BOT_TOKEN.")

    payload = json.dumps(
        {
            "chat_id": resolved_chat_id,
            "text": text or "",
            "disable_web_page_preview": False,
        }
    ).encode("utf-8")
    request = urllib_request.Request(
        f"https://api.telegram.org/bot{resolved_bot_token}/sendMessage",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Assistyca/1.0",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except urllib_error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram rejected the message: {raw_body}") from exc
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Telegram could not be reached: {reason}") from exc

    try:
        payload_obj = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        payload_obj = {}
    if not bool(payload_obj.get("ok")):
        raise RuntimeError(f"Telegram rejected the message: {raw_body or 'unknown error'}")
    return payload_obj if isinstance(payload_obj, dict) else {}


def send_whatsapp_notification(
    *,
    phone_number_id: str,
    recipient_wa_id: str,
    message_text: str,
    access_token: str | None = None,
    api_version: str | None = None,
) -> str:
    resolved_phone_number_id = normalize_text(phone_number_id)
    resolved_recipient = normalize_text(recipient_wa_id)
    resolved_access_token = normalize_text(access_token) or normalize_text(os.getenv("WHATSAPP_ACCESS_TOKEN"))
    resolved_api_version = normalize_text(api_version) or normalize_text(os.getenv("WHATSAPP_API_VERSION")) or DEFAULT_WHATSAPP_API_VERSION

    if not resolved_access_token:
        raise RuntimeError("WhatsApp delivery is not configured. Set WHATSAPP_ACCESS_TOKEN.")
    if not resolved_phone_number_id:
        raise RuntimeError("WhatsApp delivery requires a phone number id.")
    if not resolved_recipient:
        raise RuntimeError("WhatsApp delivery requires a recipient WhatsApp id.")

    return send_whatsapp_message(
        access_token=resolved_access_token,
        phone_number_id=resolved_phone_number_id,
        api_version=resolved_api_version,
        recipient_wa_id=resolved_recipient,
        message_text=message_text,
    )


__all__ = [
    "DEFAULT_MAIL_PROVIDER",
    "DEFAULT_PRODUCT_NAME",
    "DEFAULT_WHATSAPP_API_VERSION",
    "MailDeliveryConfig",
    "ResendDeliveryConfig",
    "SmtpDeliveryConfig",
    "email_delivery_available",
    "extract_email_address",
    "load_mail_delivery_config",
    "normalize_email",
    "normalize_mail_provider",
    "normalize_text",
    "send_email_notification",
    "send_telegram_notification",
    "send_whatsapp_notification",
    "telegram_delivery_available",
    "whatsapp_delivery_available",
]
