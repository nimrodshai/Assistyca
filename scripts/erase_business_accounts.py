#!/usr/bin/env python3
"""Erase the accounts that were opened for a business.

Assistyca serves only families since 2026-10-13. Every account that was not
opened as a family - the ones from before the register page asked, the ones
that picked Business, the ones a stranger's email opened - is a business
account, and none of them is a real client. This erases them the way the
account's own delete does, through `erase_account`, so nothing is left behind.

Kept whatever the column says: admins, the owner's own account (named by
PORTAL_OPPORTUNITIES_OWNER_EMAIL or --keep), and every account explicitly
opened as a family.

The account type used to live in `users.account_type`; the code no longer
reads it, so this reads the column raw. A database without the column has no
business accounts to erase.

    python3 scripts/erase_business_accounts.py --db /var/data/portal.db          # list only
    python3 scripts/erase_business_accounts.py --db /var/data/portal.db --apply  # erase
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from packages.infrastructure.account_erasure import erase_account  # noqa: E402
from packages.infrastructure.portal_db import PortalDatabase  # noqa: E402
from packages.infrastructure.portal_db import normalize_email  # noqa: E402
from packages.infrastructure.portal_runtime_paths import resolve_portal_agent_output_root  # noqa: E402
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key  # noqa: E402


def business_accounts(db_path: Path, keep: set[str]) -> list[dict[str, str]]:
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "account_type" not in columns:
            return []
        rows = conn.execute(
            "SELECT email, display_name, account_type, is_admin, registered_at FROM users ORDER BY id"
        ).fetchall()
    found = []
    for row in rows:
        email = normalize_email(row["email"])
        if str(row["account_type"] or "").strip().lower() == "family":
            continue
        if int(row["is_admin"] or 0) or email in keep:
            continue
        found.append({
            "email": email,
            "name": str(row["display_name"] or ""),
            "type": str(row["account_type"] or "") or "(none)",
            "registered": str(row["registered_at"] or ""),
        })
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="the portal database file")
    parser.add_argument("--apply", action="store_true", help="erase; without it the accounts are only listed")
    parser.add_argument("--keep", action="append", default=[], help="an email to keep whatever its type (repeatable)")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"No database at {db_path}", file=sys.stderr)
        return 2
    keep = {normalize_email(value) for value in args.keep}
    owner = normalize_email(os.getenv("PORTAL_OPPORTUNITIES_OWNER_EMAIL"))
    if owner:
        keep.add(owner)

    accounts = business_accounts(db_path, keep)
    if not accounts:
        print("No business accounts to erase.")
        return 0
    print(f"{len(accounts)} business account(s):")
    for account in accounts:
        print(f"  {account['email']:40} {account['type']:10} {account['registered'][:10]:10} {account['name']}")
    if not args.apply:
        print("\nListed only. Run again with --apply to erase them.")
        return 0

    database = PortalDatabase(db_path)
    erased = 0
    for account in accounts:
        try:
            result = erase_account(
                database=database,
                email=account["email"],
                root=REPO_ROOT,
                receipt_output_root=resolve_portal_agent_output_root(root=REPO_ROOT, db_path=db_path),
                receipt_owner_key=build_agent_receipt_owner_key(account["email"]),
                db_path=db_path,
            )
        except (KeyError, ValueError) as exc:
            print(f"  could not erase {account['email']}: {exc}")
            continue
        erased += 1
        removed = ", ".join(str(path) for path in result.removed_paths) or "no files"
        print(f"  erased {account['email']} ({removed})")
    print(f"\nErased {erased} of {len(accounts)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
