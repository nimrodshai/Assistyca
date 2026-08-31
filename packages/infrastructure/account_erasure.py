"""One path that removes everything the portal holds for an account.

Deleting a customer used to mean deleting their database rows, and the rest of
what we stored -- the receipt bundles the agent wrote to disk, the contact form
they filled in before they had an account, the grant they handed us at the
provider -- outlived the account it belonged to. Erasure requests do not stop
at one table, so neither does this.

The provider call is injected rather than imported: deciding which vendor can
be revoked and how is the server's business, and this module must stay
importable without it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Callable

from packages.infrastructure.portal_db import normalize_email
from packages.infrastructure.whatsapp_portal_service import delete_portal_whatsapp_store_for_connection
from packages.infrastructure.whatsapp_portal_service import portal_whatsapp_store_path_for_connection


RevokeGrant = Callable[[dict[str, str]], "tuple[bool, str]"]


@dataclass
class AccountErasure:
    """What a single erasure actually removed, for the response and the log."""

    user: dict[str, Any]
    removed_paths: list[Path] = field(default_factory=list)
    failed_paths: list[Path] = field(default_factory=list)
    revoked_grants: int = 0
    revocation_warnings: list[str] = field(default_factory=list)
    contact_submissions_removed: int = 0


def erase_account(
    *,
    database: Any,
    email: str,
    root: Path,
    receipt_output_root: Path | None = None,
    receipt_owner_key: str = "",
    whatsapp_store_cache: dict[str, Any] | None = None,
    whatsapp_store_lock: Any | None = None,
    revoke_grant: RevokeGrant | None = None,
) -> AccountErasure:
    """Delete the account named by ``email`` and everything stored under it.

    Raises ``KeyError`` when no such account exists. Provider revocation and
    file deletion are best effort: a provider outage or a stubborn folder is
    reported on the result, never a reason to leave the rows behind.
    """

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("Email is required.")

    user = database.get_user(normalized_email)
    if user is None:
        raise KeyError(f"Unknown user: {normalized_email}")

    result = AccountErasure(user=user)
    user_id = int(user.get("id") or 0)

    # Revoke before deleting: the ciphertext is the only way back to the grant,
    # and the row that holds it is about to go.
    if revoke_grant is not None:
        grants = database.list_platform_connection_secret_records(
            normalized_email,
            include_statuses=(),
            include_inactive_user=True,
        )
        for record in _distinct_grants(grants):
            revoked, warning = revoke_grant(record)
            if revoked:
                result.revoked_grants += 1
            if warning:
                result.revocation_warnings.append(warning)

    whatsapp_connection = database.get_whatsapp_connection(normalized_email) or {
        "userId": user_id,
        "email": normalized_email,
    }
    # The helper drops the cached store whether or not a file is there, so it
    # runs either way; only a file that existed counts as something removed.
    store_path = portal_whatsapp_store_path_for_connection(root, whatsapp_connection)
    store_existed = store_path.exists()
    try:
        removed_store = delete_portal_whatsapp_store_for_connection(
            root=root,
            connection=whatsapp_connection,
            store_cache=whatsapp_store_cache,
            store_lock=whatsapp_store_lock,
        )
    except OSError:
        result.failed_paths.append(store_path)
    else:
        if store_existed:
            result.removed_paths.append(Path(removed_store))

    owner_root = _receipt_owner_root(receipt_output_root, receipt_owner_key)
    if owner_root is not None and owner_root.is_dir():
        try:
            shutil.rmtree(owner_root)
        except OSError:
            result.failed_paths.append(owner_root)
        else:
            result.removed_paths.append(owner_root)

    result.contact_submissions_removed = database.delete_contact_opportunities_for_email(normalized_email)
    database.delete_user(normalized_email)
    return result


def _distinct_grants(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """One record per grant.

    A single Google sign-in can back a mailbox, a calendar, and a drive at
    once. Those rows share a refresh token, so revoking each of them in turn
    would tell the user three times that Google refused the second and third
    call.
    """

    seen: set[str] = set()
    distinct: list[dict[str, str]] = []
    for record in records:
        key = str(record.get("secretFingerprint") or "").strip() or str(record.get("secretCiphertext") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        distinct.append(record)
    return distinct


def _receipt_owner_root(output_root: Path | None, owner_key: str) -> Path | None:
    """The one folder under the receipt root that belongs to this account."""

    key = str(owner_key or "").strip()
    if output_root is None or not key:
        return None
    # The key names a single folder. Anything with a separator in it would
    # point the delete somewhere else entirely.
    if key in {".", ".."} or "/" in key or "\\" in key:
        raise ValueError(f"Invalid receipt owner key: {owner_key!r}")
    return Path(output_root).resolve() / key
