#!/usr/bin/env python3
"""Portal server with real email OTP authentication.

This server serves the portal static files from the repository root and exposes
JSON endpoints for requesting and verifying one-time passcodes via SMTP or Resend.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
import hmac
import hashlib
from dataclasses import dataclass
from dataclasses import field
from email.message import EmailMessage
from email.utils import formataddr
from email.utils import parseaddr
from functools import partial
from html import escape
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.billing_ledger import load_billing_report
from packages.portal_db import DEFAULT_CURRENCY
from packages.portal_db import DEFAULT_DB_PATH
from packages.portal_db import DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER
from packages.portal_db import DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER
from packages.portal_db import PortalDatabase


EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")
DEFAULT_PRODUCT_NAME = "Assistyca"
DEFAULT_MAIL_PROVIDER = "smtp"
DEFAULT_OTP_TTL_SECONDS = 10 * 60
DEFAULT_SESSION_TTL_SECONDS = 180 * 24 * 60 * 60
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_SMTP_PORT = 587
DEFAULT_BILLING_MULTIPLIER = 1.5
DEFAULT_BILLING_MINIMUM = 29.0
RESEND_API_URL = "https://api.resend.com/emails"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
SESSION_TOKEN_VERSION = 1


@dataclass(slots=True)
class SmtpConfig:
    host: str = ""
    port: int = DEFAULT_SMTP_PORT
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = DEFAULT_PRODUCT_NAME
    use_ssl: bool = False
    starttls: bool = True
    timeout: float = 10.0

    @property
    def configured(self) -> bool:
        return bool(self.host and extract_email_address(self.from_email))


@dataclass(slots=True)
class ResendConfig:
    api_key: str = ""
    from_email: str = ""
    from_name: str = DEFAULT_PRODUCT_NAME

    @property
    def configured(self) -> bool:
        return bool(self.api_key and extract_email_address(self.from_email))


@dataclass(slots=True)
class PortalConfig:
    product_name: str = DEFAULT_PRODUCT_NAME
    mail_provider: str = DEFAULT_MAIL_PROVIDER
    otp_ttl_seconds: int = DEFAULT_OTP_TTL_SECONDS
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    session_secret: str = ""
    db_path: Path = DEFAULT_DB_PATH
    seed_registered_emails: frozenset[str] = field(default_factory=frozenset)
    support_phone: str = ""
    billing_data_path: Path = Path("portal/billing.sample.json")
    billing_markup_multiplier: float = DEFAULT_BILLING_MULTIPLIER
    billing_input_token_price_multiplier: float = DEFAULT_INPUT_TOKEN_PRICE_MULTIPLIER
    billing_output_token_price_multiplier: float = DEFAULT_OUTPUT_TOKEN_PRICE_MULTIPLIER
    billing_minimum_monthly_charge: float = DEFAULT_BILLING_MINIMUM
    billing_currency: str = DEFAULT_CURRENCY
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    resend: ResendConfig = field(default_factory=ResendConfig)


@dataclass(slots=True)
class OtpChallenge:
    email: str
    code_hash: str
    salt: str
    issued_at: float
    expires_at: float
    attempts: int = 0


@dataclass(slots=True)
class PortalSession:
    token: str
    email: str
    issued_at: float
    expires_at: float


class PortalAuthStore:
    def __init__(
        self,
        *,
        otp_ttl_seconds: int,
        session_ttl_seconds: int,
        max_attempts: int,
        session_secret: str,
        registered_email_lookup: Callable[[str], bool],
    ) -> None:
        self.otp_ttl_seconds = otp_ttl_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self.max_attempts = max_attempts
        self.session_secret = session_secret.encode("utf-8") if session_secret else b""
        self.registered_email_lookup = registered_email_lookup
        self._challenges: dict[str, OtpChallenge] = {}
        self._sessions: dict[str, PortalSession] = {}
        self._revoked_tokens: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_registered_email(self, email: str) -> bool:
        normalized_email = normalize_email(email)
        return bool(self.registered_email_lookup(normalized_email))

    def issue_challenge(self, email: str) -> tuple[str, OtpChallenge]:
        normalized_email = normalize_email(email)
        now = time.time()
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_urlsafe(12)
        challenge = OtpChallenge(
            email=normalized_email,
            code_hash=hash_code(salt, code),
            salt=salt,
            issued_at=now,
            expires_at=now + self.otp_ttl_seconds,
            attempts=0,
        )

        with self._lock:
            self._purge_expired_locked(now)
            self._challenges[normalized_email] = challenge

        return code, challenge

    def delete_challenge(self, email: str) -> None:
        normalized_email = normalize_email(email)
        with self._lock:
            self._challenges.pop(normalized_email, None)

    def verify_code(self, email: str, code: str) -> tuple[bool, str, dict[str, Any] | None]:
        normalized_email = normalize_email(email)
        normalized_code = normalize_code(code)
        now = time.time()

        with self._lock:
            if not self.is_registered_email(normalized_email):
                return False, "not_registered", None

            self._purge_expired_locked(now)
            challenge = self._challenges.get(normalized_email)
            if challenge is None:
                return False, "missing_challenge", None

            if now > challenge.expires_at:
                self._challenges.pop(normalized_email, None)
                return False, "expired", None

            if len(normalized_code) != 6:
                return False, "invalid_code", {"message": "Enter the full 6-digit code."}

            if not compare_code(challenge, normalized_code):
                challenge.attempts += 1
                if challenge.attempts >= self.max_attempts:
                    self._challenges.pop(normalized_email, None)
                    return False, "too_many_attempts", {
                        "message": "That code was tried too many times. Send a new one.",
                    }

                attempts_remaining = max(0, self.max_attempts - challenge.attempts)
                return False, "incorrect", {
                    "attemptsRemaining": attempts_remaining,
                    "message": "That code is not correct.",
                }

            self._challenges.pop(normalized_email, None)
            session = PortalSession(
                token="",
                email=normalized_email,
                issued_at=now,
                expires_at=now + self.session_ttl_seconds,
            )
            token = create_session_token(session, self.session_secret) if self.session_secret else secrets.token_urlsafe(32)
            session.token = token
            if not self.session_secret:
                self._sessions[token] = session
            return True, "ok", {
                "token": token,
                "email": session.email,
                "issuedAt": to_millis(session.issued_at),
                "expiresAt": to_millis(session.expires_at),
            }

    def get_session(self, token: str) -> PortalSession | None:
        normalized_token = str(token or "").strip()
        if not normalized_token:
            return None

        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            revoked_expires_at = self._revoked_tokens.get(hash_session_token(normalized_token))
            if revoked_expires_at is not None:
                if now > revoked_expires_at:
                    self._revoked_tokens.pop(hash_session_token(normalized_token), None)
                else:
                    return None

            if self.session_secret:
                session = parse_session_token(normalized_token, self.session_secret)
                if session is not None and self.is_registered_email(session.email):
                    return session
                if session is not None:
                    return None

            session = self._sessions.get(normalized_token)
            if session is None:
                return None

            if not self.is_registered_email(session.email):
                return None

            if now > session.expires_at:
                self._sessions.pop(normalized_token, None)
                return None

            return session

    def revoke_session(self, token: str) -> bool:
        normalized_token = str(token or "").strip()
        if not normalized_token:
            return False

        with self._lock:
            revoked = False
            if self.session_secret:
                session = parse_session_token(normalized_token, self.session_secret, validate_expiry=False)
                if session is not None and time.time() <= session.expires_at:
                    self._revoked_tokens[hash_session_token(normalized_token)] = session.expires_at
                    revoked = True

            return self._sessions.pop(normalized_token, None) is not None or revoked

    def _purge_expired_locked(self, now: float) -> None:
        expired_emails = [email for email, challenge in self._challenges.items() if now > challenge.expires_at]
        for email in expired_emails:
            self._challenges.pop(email, None)

        expired_tokens = [token for token, session in self._sessions.items() if now > session.expires_at]
        for token in expired_tokens:
            self._sessions.pop(token, None)

        expired_revocations = [token_hash for token_hash, expires_at in self._revoked_tokens.items() if now > expires_at]
        for token_hash in expired_revocations:
            self._revoked_tokens.pop(token_hash, None)


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def normalize_code(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def compare_code(challenge: OtpChallenge, code: str) -> bool:
    return secrets.compare_digest(hash_code(challenge.salt, code), challenge.code_hash)


def hash_code(salt: str, code: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"{salt}:{code}".encode("utf-8"))
    return digest.hexdigest()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def encode_token_segment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_token_segment(raw: str) -> bytes:
    padded = str(raw or "").strip()
    if not padded:
        raise ValueError("Missing token segment.")

    padded += "=" * (-len(padded) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def sign_token_segment(payload_segment: str, secret: bytes) -> str:
    signature = hmac.new(secret, payload_segment.encode("ascii"), hashlib.sha256).digest()
    return encode_token_segment(signature)


def create_session_token(session: PortalSession, secret: bytes) -> str:
    if not secret:
        raise ValueError("Session secret is required to create a signed session token.")

    payload = {
        "v": SESSION_TOKEN_VERSION,
        "email": normalize_email(session.email),
        "iat": int(session.issued_at),
        "exp": int(session.expires_at),
    }
    payload_segment = encode_token_segment(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature_segment = sign_token_segment(payload_segment, secret)
    return f"{payload_segment}.{signature_segment}"


def parse_session_token(token: str, secret: bytes, *, validate_expiry: bool = True) -> PortalSession | None:
    normalized_token = str(token or "").strip()
    if not normalized_token or not secret:
        return None

    try:
        payload_segment, signature_segment = normalized_token.split(".", 1)
    except ValueError:
        return None

    expected_signature = sign_token_segment(payload_segment, secret)
    if not secrets.compare_digest(signature_segment, expected_signature):
        return None

    try:
        payload = json.loads(decode_token_segment(payload_segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or payload.get("v") != SESSION_TOKEN_VERSION:
        return None

    email = normalize_email(payload.get("email", ""))
    if not is_valid_email(email):
        return None

    try:
        issued_at = float(payload.get("iat", 0))
        expires_at = float(payload.get("exp", 0))
    except (TypeError, ValueError):
        return None

    if issued_at <= 0 or expires_at <= issued_at:
        return None

    if validate_expiry and time.time() > expires_at:
        return None

    return PortalSession(
        token=normalized_token,
        email=email,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def to_millis(value: float) -> int:
    return int(round(value * 1000))


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email)))


def extract_email_address(value: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    _, parsed_address = parseaddr(raw_value)
    parsed_address = parsed_address.strip()
    if parsed_address and is_valid_email(parsed_address):
        return parsed_address

    if is_valid_email(raw_value):
        return normalize_email(raw_value)

    return ""


def build_sender_header(display_name: str, raw_value: str) -> str:
    address = extract_email_address(raw_value)
    if not address:
        return ""

    parsed_name, _ = parseaddr(str(raw_value or "").strip())
    name = parsed_name.strip() or str(display_name or "").strip()
    if name:
        return formataddr((name, address))

    return address


def read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


def read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    try:
        return int(raw)
    except ValueError:
        return default


def read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    try:
        return float(raw)
    except ValueError:
        return default


def read_email_list_env(name: str) -> frozenset[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return frozenset()

    emails: set[str] = set()
    for chunk in re.split(r"[,;\n]+", raw):
        email = extract_email_address(chunk)
        if email:
            emails.add(normalize_email(email))

    return frozenset(emails)


def load_config() -> PortalConfig:
    provider = normalize_mail_provider(os.getenv("PORTAL_MAIL_PROVIDER", DEFAULT_MAIL_PROVIDER))
    smtp = SmtpConfig(
        host=os.getenv("PORTAL_SMTP_HOST", "").strip(),
        port=read_int_env("PORTAL_SMTP_PORT", DEFAULT_SMTP_PORT),
        username=os.getenv("PORTAL_SMTP_USERNAME", "").strip(),
        password=os.getenv("PORTAL_SMTP_PASSWORD", "").strip(),
        from_email=os.getenv("PORTAL_SMTP_FROM_EMAIL", "").strip(),
        from_name=os.getenv("PORTAL_SMTP_FROM_NAME", DEFAULT_PRODUCT_NAME).strip() or DEFAULT_PRODUCT_NAME,
        use_ssl=read_bool_env("PORTAL_SMTP_SSL", False),
        starttls=read_bool_env("PORTAL_SMTP_STARTTLS", True),
        timeout=float(read_int_env("PORTAL_SMTP_TIMEOUT", 10)),
    )
    resend = ResendConfig(
        api_key=os.getenv("PORTAL_RESEND_API_KEY", "").strip(),
        from_email=os.getenv("PORTAL_RESEND_FROM_EMAIL", "").strip(),
        from_name=os.getenv("PORTAL_RESEND_FROM_NAME", DEFAULT_PRODUCT_NAME).strip() or DEFAULT_PRODUCT_NAME,
    )
    session_secret = resolve_session_secret(
        explicit_secret=os.getenv("PORTAL_SESSION_SECRET", "").strip(),
        smtp=smtp,
        resend=resend,
    )

    db_path = Path(os.getenv("PORTAL_DB_PATH", str(DEFAULT_DB_PATH)).strip() or str(DEFAULT_DB_PATH))
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    billing_data_path = Path(
        os.getenv("PORTAL_BILLING_DATA_PATH", "portal/billing.sample.json").strip()
        or "portal/billing.sample.json"
    )
    if not billing_data_path.is_absolute():
        billing_data_path = Path.cwd() / billing_data_path

    legacy_markup_multiplier = read_float_env("PORTAL_BILLING_MULTIPLIER", DEFAULT_BILLING_MULTIPLIER)
    input_token_price_multiplier = read_float_env(
        "PORTAL_BILLING_INPUT_TOKEN_PRICE_MULTIPLIER",
        legacy_markup_multiplier,
    )
    output_token_price_multiplier = read_float_env(
        "PORTAL_BILLING_OUTPUT_TOKEN_PRICE_MULTIPLIER",
        legacy_markup_multiplier,
    )
    seed_registered_emails = frozenset().union(
        read_email_list_env("PORTAL_DB_SEED_REGISTERED_EMAILS"),
        read_email_list_env("PORTAL_REGISTERED_EMAILS"),
    )

    return PortalConfig(
        product_name=os.getenv("PORTAL_PRODUCT_NAME", DEFAULT_PRODUCT_NAME).strip() or DEFAULT_PRODUCT_NAME,
        mail_provider=provider,
        otp_ttl_seconds=read_int_env("PORTAL_OTP_TTL_SECONDS", DEFAULT_OTP_TTL_SECONDS),
        session_ttl_seconds=read_int_env("PORTAL_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS),
        max_attempts=read_int_env("PORTAL_OTP_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS),
        session_secret=session_secret,
        db_path=db_path,
        seed_registered_emails=seed_registered_emails,
        support_phone=os.getenv("PORTAL_SUPPORT_PHONE", "").strip(),
        billing_data_path=billing_data_path,
        billing_markup_multiplier=legacy_markup_multiplier,
        billing_input_token_price_multiplier=input_token_price_multiplier,
        billing_output_token_price_multiplier=output_token_price_multiplier,
        billing_minimum_monthly_charge=read_float_env("PORTAL_BILLING_MINIMUM_MONTHLY_CHARGE", DEFAULT_BILLING_MINIMUM),
        billing_currency=os.getenv("PORTAL_BILLING_CURRENCY", DEFAULT_CURRENCY).strip() or DEFAULT_CURRENCY,
        smtp=smtp,
        resend=resend,
    )


def normalize_mail_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider in {"smtp", "resend", "auto"}:
        return provider

    return DEFAULT_MAIL_PROVIDER


def resolve_session_secret(*, explicit_secret: str, smtp: SmtpConfig, resend: ResendConfig) -> str:
    if explicit_secret:
        return explicit_secret

    if resend.api_key:
        return resend.api_key

    if smtp.password:
        return smtp.password

    return ""


def build_not_registered_message(config: PortalConfig) -> str:
    support_phone = str(config.support_phone or "").strip()
    if support_phone:
        return f"You are not registered to use this portal. If you want to register, contact me at {support_phone}."

    return "You are not registered to use this portal. If you want to register, contact me."


def build_otp_email_subject(config: PortalConfig) -> str:
    return f"{config.product_name} sign-in code"


def otp_expiry_minutes(config: PortalConfig) -> int:
    return max(1, (config.otp_ttl_seconds + 59) // 60)


def build_otp_email_text(config: PortalConfig, code: str) -> str:
    return "\n".join(
        [
            f"Use this code to sign in to {config.product_name}:",
            "",
            code,
            "",
            f"It expires in {otp_expiry_minutes(config)} minutes.",
            "",
            "If you did not request this code, you can safely ignore this email.",
        ]
    )


def build_otp_email_html(config: PortalConfig, code: str) -> str:
    product_name = escape(config.product_name)
    otp_code = escape(code)
    expiry_minutes = otp_expiry_minutes(config)
    preheader = escape(
        f"Your {config.product_name} sign-in code is {code}. It expires in {expiry_minutes} minutes."
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="light only" />
    <meta name="supported-color-schemes" content="light only" />
    <title>{product_name} sign-in code</title>
  </head>
  <body style="margin:0;padding:0;background-color:#eef4f4;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">
      {preheader}
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef4f4;">
      <tr>
        <td align="center" style="padding:32px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border:1px solid #dce7e6;border-radius:28px;overflow:hidden;">
            <tr>
              <td style="padding:36px 32px 12px;text-align:center;">
                <div style="display:inline-block;padding:8px 14px;border-radius:999px;background:#e8f5f2;color:#0f766e;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;">
                  {product_name}
                </div>
                <h1 style="margin:20px 0 12px;color:#122230;font-family:Arial,sans-serif;font-size:32px;line-height:1.15;font-weight:800;">
                  Your sign-in code
                </h1>
                <p style="margin:0;color:#566575;font-family:Arial,sans-serif;font-size:16px;line-height:1.6;">
                  Enter this one-time code to continue into your workspace.
                </p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:20px 32px 8px;">
                <div style="display:inline-block;min-width:260px;padding:18px 24px;border-radius:20px;background:#f5fbfa;border:1px solid #d9ece8;">
                  <div style="color:#0f766e;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;">
                    One-time code
                  </div>
                  <div style="margin-top:12px;color:#122230;font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;font-size:42px;line-height:1.1;font-weight:700;letter-spacing:0.24em;">
                    {otp_code}
                  </div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px 0;text-align:center;">
                <p style="margin:0;color:#3f5362;font-family:Arial,sans-serif;font-size:16px;line-height:1.6;">
                  This code expires in <strong>{expiry_minutes} minutes</strong>.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px 36px;text-align:center;">
                <p style="margin:0;color:#647482;font-family:Arial,sans-serif;font-size:14px;line-height:1.7;">
                  If you did not request this code, you can safely ignore this email.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def build_otp_email(config: PortalConfig, email: str, code: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = build_otp_email_subject(config)
    from_header = build_sender_header(config.smtp.from_name, config.smtp.from_email)
    if not from_header:
        raise RuntimeError("SMTP sender address is invalid. Set PORTAL_SMTP_FROM_EMAIL to a valid email address.")

    message["From"] = from_header
    message["To"] = email
    message.set_content(build_otp_email_text(config, code))
    message.add_alternative(build_otp_email_html(config, code), subtype="html")
    return message


def send_otp_email_via_smtp(config: PortalConfig, email: str, code: str) -> None:
    if not config.smtp.configured:
        raise RuntimeError("SMTP is not configured. Set PORTAL_SMTP_HOST and PORTAL_SMTP_FROM_EMAIL.")

    message = build_otp_email(config, email, code)

    smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    if config.smtp.use_ssl:
        smtp_factory = smtplib.SMTP_SSL
        context = ssl.create_default_context()
        smtp = smtp_factory(config.smtp.host, config.smtp.port, timeout=config.smtp.timeout, context=context)
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


def describe_resend_error(raw_body: str, status_code: int) -> str:
    message = ""
    raw = str(raw_body or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        if isinstance(payload, dict):
            for key in ("message", "error", "name"):
                value = payload.get(key)
                if value:
                    message = str(value).strip()
                    break

            errors = payload.get("errors")
            if not message and isinstance(errors, list) and errors:
                first_error = errors[0]
                if isinstance(first_error, dict):
                    for key in ("message", "field", "code"):
                        value = first_error.get(key)
                        if value:
                            message = str(value).strip()
                            break
                elif isinstance(first_error, str):
                    message = first_error.strip()

        if not message:
            message = raw

    if not message:
        message = f"Resend returned HTTP {status_code}."

    return message


def send_otp_email_via_resend(config: PortalConfig, email: str, code: str) -> None:
    if not config.resend.configured:
        raise RuntimeError(
            "Resend is not configured. Set PORTAL_RESEND_API_KEY and PORTAL_RESEND_FROM_EMAIL "
            "to a valid sender email."
        )

    from_header = build_sender_header(config.resend.from_name, config.resend.from_email)
    if not from_header:
        raise RuntimeError(
            "PORTAL_RESEND_FROM_EMAIL must be a valid email address or a formatted sender like "
            "'Name <email@example.com>'."
        )

    payload = {
        "from": from_header,
        "to": [email],
        "subject": build_otp_email_subject(config),
        "text": build_otp_email_text(config, code),
        "html": build_otp_email_html(config, code),
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(
        RESEND_API_URL,
        data=body,
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
            return
    except urllib_error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Could not send the code via Resend: {describe_resend_error(raw_body, exc.code)}") from exc
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Could not send the code via Resend: {reason}") from exc


def send_otp_email(config: PortalConfig, email: str, code: str) -> None:
    provider = normalize_mail_provider(config.mail_provider)

    if provider == "resend":
        send_otp_email_via_resend(config, email, code)
        return

    if provider == "auto":
        if config.resend.configured:
            send_otp_email_via_resend(config, email, code)
            return
        if config.smtp.configured:
            send_otp_email_via_smtp(config, email, code)
            return

        raise RuntimeError(
            "No mail provider is configured. Set PORTAL_RESEND_API_KEY and PORTAL_RESEND_FROM_EMAIL, "
            "or PORTAL_SMTP_HOST and PORTAL_SMTP_FROM_EMAIL."
        )

    send_otp_email_via_smtp(config, email, code)


def parse_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    if not raw.strip():
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON body.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object.")

    return parsed


def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    send_api_headers(handler, content_length=len(body))
    handler.end_headers()
    handler.wfile.write(body)


def send_api_headers(handler: SimpleHTTPRequestHandler, *, content_length: int | None = None) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Content-Type", JSON_CONTENT_TYPE)
    handler.send_header("Cache-Control", "no-store")
    if content_length is not None:
        handler.send_header("Content-Length", str(content_length))


class PortalAuthHandler(SimpleHTTPRequestHandler):
    server_version = "PortalAuth/1.0"

    @property
    def config(self) -> PortalConfig:
        return self.server.config  # type: ignore[attr-defined]

    @property
    def store(self) -> PortalAuthStore:
        return self.server.store  # type: ignore[attr-defined]

    @property
    def database(self) -> PortalDatabase:
        return self.server.database  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - BaseHTTPRequestHandler API
        return

    def end_headers(self) -> None:
        if not self.path.startswith("/api/auth/"):
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")

        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith("/api/auth/") or self.path.startswith("/api/billing/"):
            self.send_response(HTTPStatus.NO_CONTENT)
            send_api_headers(self)
            self.end_headers()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith("/api/auth/") or self.path.startswith("/api/billing/"):
            self._handle_api_get()
            return

        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith("/api/auth/") or self.path.startswith("/api/billing/"):
            self._handle_api_post()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_get(self) -> None:
        if self.path.startswith("/api/auth/session"):
            token = self._extract_session_token()
            session = self.store.get_session(token) if token else None
            if session is None:
                json_response(self, HTTPStatus.UNAUTHORIZED, {
                    "ok": False,
                    "signedIn": False,
                    "message": "No valid session.",
                })
                return

            json_response(self, HTTPStatus.OK, {
                "ok": True,
                "signedIn": True,
                "email": session.email,
                "token": session.token,
                "issuedAt": to_millis(session.issued_at),
                "expiresAt": to_millis(session.expires_at),
            })
            return

        if self.path.startswith("/api/billing"):
            token = self._extract_session_token()
            session = self.store.get_session(token) if token else None
            if session is None:
                json_response(self, HTTPStatus.UNAUTHORIZED, {
                    "ok": False,
                    "message": "No valid session.",
                })
                return

            report: dict[str, Any] | None
            try:
                report = self.database.build_billing_report(session.email)
            except Exception:
                report = None

            if report is None:
                report = load_billing_report(
                    self.config.billing_data_path,
                    session.email,
                    markup_multiplier=self.config.billing_markup_multiplier,
                    minimum_monthly_charge=self.config.billing_minimum_monthly_charge,
                    currency=self.config.billing_currency,
                )
                report["sourceLabel"] = "Sample ledger" if report.get("source") == "defaults" else "Billing ledger"
            json_response(self, HTTPStatus.OK, report)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_post(self) -> None:
        if self.path.startswith("/api/auth/otp/request"):
            self._handle_otp_request()
            return

        if self.path.startswith("/api/auth/otp/verify"):
            self._handle_otp_verify()
            return

        if self.path.startswith("/api/auth/logout"):
            self._handle_logout()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_otp_request(self) -> None:
        try:
            payload = parse_json_body(self)
        except ValueError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json", "message": str(exc)})
            return

        email = normalize_email(payload.get("email", ""))
        if not is_valid_email(email):
            json_response(self, HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "invalid_email",
                "message": "Enter a valid email address.",
            })
            return

        if not self.store.is_registered_email(email):
            json_response(self, HTTPStatus.FORBIDDEN, {
                "ok": False,
                "error": "not_registered",
                "message": build_not_registered_message(self.config),
            })
            return

        try:
            try:
                self.database.record_otp_requested(email)
            except Exception:
                pass
            code, challenge = self.store.issue_challenge(email)
            send_otp_email(self.config, email, code)
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.store.delete_challenge(email)
            json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {
                "ok": False,
                "error": "email_delivery_failed",
                "message": f"Could not send the code: {exc}",
            })
            return

        json_response(self, HTTPStatus.OK, {
            "ok": True,
            "email": challenge.email,
            "requestedAt": to_millis(challenge.issued_at),
            "expiresAt": to_millis(challenge.expires_at),
            "expiresInSeconds": self.config.otp_ttl_seconds,
        })

    def _handle_otp_verify(self) -> None:
        try:
            payload = parse_json_body(self)
        except ValueError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json", "message": str(exc)})
            return

        email = normalize_email(payload.get("email", ""))
        code = normalize_code(payload.get("code", ""))

        if not is_valid_email(email):
            json_response(self, HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "invalid_email",
                "message": "Enter a valid email address.",
            })
            return

        ok, error, result = self.store.verify_code(email, code)
        if not ok:
            message = "That code is not correct."
            if result and result.get("message"):
                message = str(result["message"])
            elif error == "missing_challenge":
                message = "Send a fresh code first."
            elif error == "expired":
                message = "That code expired. Send a new one."
            elif error == "not_registered":
                message = build_not_registered_message(self.config)

            status_map = {
                "missing_challenge": HTTPStatus.BAD_REQUEST,
                "expired": HTTPStatus.BAD_REQUEST,
                "invalid_code": HTTPStatus.BAD_REQUEST,
                "incorrect": HTTPStatus.UNAUTHORIZED,
                "too_many_attempts": HTTPStatus.TOO_MANY_REQUESTS,
                "not_registered": HTTPStatus.FORBIDDEN,
            }
            json_response(self, status_map.get(error, HTTPStatus.BAD_REQUEST), {
                "ok": False,
                "error": error,
                "message": message,
                **(result or {}),
            })
            return

        assert result is not None
        try:
            self.database.record_login(email)
        except Exception:
            pass
        json_response(self, HTTPStatus.OK, {
            "ok": True,
            "email": result["email"],
            "sessionToken": result["token"],
            "issuedAt": result["issuedAt"],
            "expiresAt": result["expiresAt"],
        })

    def _handle_logout(self) -> None:
        token = self._extract_session_token()
        if not token:
            try:
                payload = parse_json_body(self)
            except ValueError:
                payload = {}
            token = str(payload.get("token", "")).strip()

        self.store.revoke_session(token)
        json_response(self, HTTPStatus.OK, {"ok": True})

    def _extract_session_token(self) -> str:
        auth_header = str(self.headers.get("Authorization", "")).strip()
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()

        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if query:
            from urllib.parse import parse_qs

            params = parse_qs(query)
            token_values = params.get("token") or []
            if token_values:
                return str(token_values[0]).strip()

        return ""


def create_server(host: str, port: int, root: Path, config: PortalConfig) -> ThreadingHTTPServer:
    handler = partial(PortalAuthHandler, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    server.config = config  # type: ignore[attr-defined]
    server.database = PortalDatabase(
        config.db_path,
        bootstrap_registered_emails=config.seed_registered_emails,
        default_currency=config.billing_currency,
        default_monthly_minimum_cents=max(0, int(round(config.billing_minimum_monthly_charge * 100))),
        default_input_token_price_multiplier=config.billing_input_token_price_multiplier,
        default_output_token_price_multiplier=config.billing_output_token_price_multiplier,
    )  # type: ignore[attr-defined]
    server.store = PortalAuthStore(
        otp_ttl_seconds=config.otp_ttl_seconds,
        session_ttl_seconds=config.session_ttl_seconds,
        max_attempts=config.max_attempts,
        session_secret=config.session_secret,
        registered_email_lookup=server.database.is_registered_email,
    )  # type: ignore[attr-defined]
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the portal static server and OTP API.")
    parser.add_argument("--host", default=os.getenv("PORTAL_HOST", "127.0.0.1"), help="Bind address.")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORTAL_PORT", "8000")), help="Listening port.")
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root. Defaults to the directory two levels above this file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    os.chdir(repo_root)

    config = load_config()
    server = create_server(args.host, args.port, repo_root, config)
    provider = normalize_mail_provider(config.mail_provider)

    print(f"Portal server listening on http://{args.host}:{args.port}/portal/", flush=True)
    print(f"Portal database: {config.db_path}", flush=True)
    registered_count = server.database.count_registered_users()
    if registered_count:
        print(f"Registered users database contains {registered_count} active user(s).", flush=True)
    elif config.seed_registered_emails:
        print(
            f"Database started empty. {len(config.seed_registered_emails)} bootstrap email(s) are configured for first-run seeding.",
            flush=True,
        )
    else:
        print(
            "Registered users database is empty, so OTP requests will be blocked until users are added.",
            flush=True,
        )
    if config.support_phone:
        print(f"Blocked users will be told to contact {config.support_phone}.", flush=True)
    else:
        print("PORTAL_SUPPORT_PHONE is not set, so blocked users will see a generic contact message.", flush=True)
    if config.session_secret:
        print(
            f"Signed sessions enabled. Default session lifetime is {config.session_ttl_seconds // 86400} days.",
            flush=True,
        )
    else:
        print(
            "Session signing is not configured, so sessions will be lost on redeploy. "
            "Set PORTAL_SESSION_SECRET or configure mail credentials with a stable secret.",
            flush=True,
        )

    print(
        f"Default billing plan: {config.billing_input_token_price_multiplier}x input / "
        f"{config.billing_output_token_price_multiplier}x output, "
        f"${config.billing_minimum_monthly_charge:.2f} minimum.",
        flush=True,
    )
    print(
        f"Sample billing fallback: {config.billing_data_path} "
        f"({config.billing_markup_multiplier}x markup, ${config.billing_minimum_monthly_charge:.2f} minimum).",
        flush=True,
    )

    if provider == "resend":
        if config.resend.configured:
            print("Using Resend for OTP delivery.", flush=True)
        else:
            print(
                "Resend is not configured yet. Set PORTAL_RESEND_API_KEY and PORTAL_RESEND_FROM_EMAIL.",
                flush=True,
            )
    elif provider == "auto":
        if config.resend.configured:
            print("Using Resend for OTP delivery.", flush=True)
        elif config.smtp.configured:
            print("Using SMTP for OTP delivery.", flush=True)
        else:
            print(
                "No mail provider is configured yet. Set PORTAL_RESEND_API_KEY and PORTAL_RESEND_FROM_EMAIL, "
                "or PORTAL_SMTP_HOST and PORTAL_SMTP_FROM_EMAIL.",
                flush=True,
            )
    elif config.smtp.configured:
        print("Using SMTP for OTP delivery.", flush=True)
    else:
        print("SMTP is not configured yet. Set PORTAL_SMTP_HOST and PORTAL_SMTP_FROM_EMAIL.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down portal server.", flush=True)
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
