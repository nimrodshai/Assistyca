#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.portal_db import DEFAULT_DB_PATH  # noqa: E402
from packages.portal_db import PortalDatabase  # noqa: E402
from packages.portal_db import normalize_email  # noqa: E402


def load_database(path: str | None) -> PortalDatabase:
    db_path = Path(path or os.getenv("PORTAL_DB_PATH", str(DEFAULT_DB_PATH)))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path

    bootstrap_emails: set[str] = set()
    for env_name in ("PORTAL_DB_SEED_REGISTERED_EMAILS", "PORTAL_REGISTERED_EMAILS"):
        raw = os.getenv(env_name, "")
        if not raw.strip():
            continue

        for chunk in re.split(r"[,;\n]+", raw):
            email = normalize_email(chunk)
            if email:
                bootstrap_emails.add(email)

    return PortalDatabase(db_path, bootstrap_registered_emails=bootstrap_emails)


def format_billing(user: dict[str, object]) -> str:
    billing = user.get("billing") if isinstance(user.get("billing"), dict) else {}
    currency = str(billing.get("currency") or "USD")
    minimum = float(billing.get("monthlyMinimumCents") or 0) / 100
    input_multiplier = float(billing.get("inputTokenPriceMultiplier") or 1.5)
    output_multiplier = float(billing.get("outputTokenPriceMultiplier") or 1.5)
    if abs(input_multiplier - output_multiplier) < 0.0001:
        policy = f"{input_multiplier:.1f}x token price"
    else:
        policy = f"{input_multiplier:.1f}x input / {output_multiplier:.1f}x output"

    return f"{policy} · {currency} {minimum:.2f} minimum"


def command_list_users(args: argparse.Namespace) -> int:
    database = load_database(args.db_path)
    users = database.list_users(include_inactive=args.include_inactive)

    if args.json:
        print(json.dumps(users, indent=2, ensure_ascii=True))
        return 0

    if not users:
        print("No registered users found.")
        return 0

    for user in users:
        status = "active" if user.get("isActive") else "inactive"
        print(
            f"{user.get('email')} | registered {user.get('registeredAt')} | {status} | "
            f"usage {int(user.get('usageCount') or 0)} | {format_billing(user)}"
        )

    return 0


def command_show_user(args: argparse.Namespace) -> int:
    database = load_database(args.db_path)
    target_email = normalize_email(args.email)
    users = [user for user in database.list_users(include_inactive=True) if user.get("email") == target_email]
    if not users:
        print(f"Unknown user: {args.email}", file=sys.stderr)
        return 1

    user = users[0]
    payload = {
        "user": user,
        "usageEvents": database.list_usage_events(args.email),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def command_list_usage(args: argparse.Namespace) -> int:
    database = load_database(args.db_path)
    events = database.list_usage_events(args.email)
    if args.json:
        print(json.dumps(events, indent=2, ensure_ascii=True))
        return 0

    if not events:
        print(f"No usage recorded for {args.email}.")
        return 0

    for event in events:
        print(
            f"{event.get('usedAt')} | {event.get('model')} | "
            f"{int(event.get('inputTokens') or 0) + int(event.get('outputTokens') or 0)} tokens | "
            f"{float(event.get('rawChargeCents') or 0) / 100:.4f} USD"
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the portal SQLite database.")
    parser.add_argument("--db-path", default=None, help="Optional path to the SQLite database.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_users = subparsers.add_parser("list-users", help="List registered users.")
    list_users.add_argument("--include-inactive", action="store_true", help="Show inactive users too.")
    list_users.add_argument("--json", action="store_true", help="Output JSON instead of text.")
    list_users.set_defaults(func=command_list_users)

    show_user = subparsers.add_parser("show-user", help="Show one user and their usage history.")
    show_user.add_argument("email", help="Registered email address.")
    show_user.set_defaults(func=command_show_user)

    list_usage = subparsers.add_parser("list-usage", help="List recorded usage events for one user.")
    list_usage.add_argument("email", help="Registered email address.")
    list_usage.add_argument("--json", action="store_true", help="Output JSON instead of text.")
    list_usage.set_defaults(func=command_list_usage)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
