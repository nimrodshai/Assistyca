"""Small envelope-encryption adapter for user-provided platform credentials.

Credentials are deliberately kept out of browser storage, agent prompts, and
the public connection responses.  The production dependency is ``cryptography``
so AES-GCM provides authenticated encryption; the vault fails closed when the
key or dependency is not configured instead of silently storing plaintext.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
from typing import Any


class CredentialVaultError(RuntimeError):
    """Raised when credentials cannot be safely encrypted or decrypted."""


def _decode_master_key(raw_key: str) -> bytes:
    normalized = str(raw_key or "").strip()
    if not normalized:
        raise CredentialVaultError("Credential encryption is not configured.")

    # Accept a 64-character hex key or a URL-safe base64 encoded 32-byte key.
    if len(normalized) == 64:
        try:
            decoded = bytes.fromhex(normalized)
        except ValueError:
            decoded = b""
        if len(decoded) == 32:
            return decoded

    padded = normalized + ("=" * (-len(normalized) % 4))
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise CredentialVaultError("Credential encryption key must be 32 bytes.") from exc
    if len(decoded) != 32:
        raise CredentialVaultError("Credential encryption key must be 32 bytes.")
    return decoded


class CredentialVault:
    """AES-GCM credential vault backed by an environment-provided master key."""

    VERSION = "v1"
    NONCE_BYTES = 12

    def __init__(self, master_key: str, *, key_version: str = "1") -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.exceptions import InvalidTag
        except ImportError as exc:  # pragma: no cover - exercised in deployment smoke checks
            raise CredentialVaultError(
                "Credential encryption is unavailable. Install the cryptography dependency."
            ) from exc

        self._aesgcm_type = AESGCM
        self._invalid_tag_type = InvalidTag
        self._key = _decode_master_key(master_key)
        self.key_version = str(key_version or "1").strip()[:32] or "1"

    @classmethod
    def from_environment(cls) -> "CredentialVault":
        # PORTAL_CREDENTIALS_KEY is the canonical deployment secret. Keep the
        # longer name as a backwards-compatible alias for local deployments.
        master_key = os.getenv("PORTAL_CREDENTIALS_KEY", "").strip()
        if not master_key:
            master_key = os.getenv("PORTAL_CREDENTIAL_ENCRYPTION_KEY", "").strip()
        return cls(master_key, key_version=os.getenv("PORTAL_CREDENTIALS_KEY_VERSION", "1"))

    def encrypt(self, secret: str) -> str:
        value = str(secret or "")
        if not value:
            raise CredentialVaultError("A credential is required.")

        nonce = secrets.token_bytes(self.NONCE_BYTES)
        ciphertext = self._aesgcm_type(self._key).encrypt(nonce, value.encode("utf-8"), None)
        return ":".join(
            (
                self.VERSION,
                base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
                base64.urlsafe_b64encode(ciphertext).decode("ascii").rstrip("="),
            )
        )

    def decrypt(self, encrypted: str) -> str:
        parts = str(encrypted or "").split(":", 2)
        if len(parts) != 3 or parts[0] != self.VERSION:
            raise CredentialVaultError("Stored credential has an unsupported format.")

        try:
            nonce = base64.urlsafe_b64decode(parts[1] + ("=" * (-len(parts[1]) % 4)))
            ciphertext = base64.urlsafe_b64decode(parts[2] + ("=" * (-len(parts[2]) % 4)))
            plaintext = self._aesgcm_type(self._key).decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError, self._invalid_tag_type) as exc:
            raise CredentialVaultError("Stored credential could not be opened.") from exc

    def fingerprint(self, secret: str) -> str:
        """Return a non-reversible fingerprint for rotation and audit checks."""

        value = str(secret or "").encode("utf-8")
        if not value:
            raise CredentialVaultError("A credential is required.")
        return hashlib.sha256(value).hexdigest()


def credential_hint(secret: str) -> str:
    """Return non-sensitive display metadata without retaining the full secret."""

    value = str(secret or "")
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"


def normalize_platform_connection_metadata(value: Any) -> dict[str, str]:
    """Keep optional metadata intentionally small and non-sensitive."""

    if not isinstance(value, dict):
        return {}
    allowed_keys = {"label", "workspace", "account"}
    return {
        str(key): str(item).strip()[:200]
        for key, item in value.items()
        if str(key) in allowed_keys and str(item or "").strip()
    }
