#!/usr/bin/env python3
"""Guard against drift in the shared package layout."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"
ALLOWED_TOP_LEVEL_DIRS = {"infrastructure", "tools"}

REQUIRED_FILES = [
    PACKAGES_DIR / "infrastructure" / "__init__.py",
    PACKAGES_DIR / "infrastructure" / "billing_ledger.py",
    PACKAGES_DIR / "infrastructure" / "portal_auth" / "__init__.py",
    PACKAGES_DIR / "infrastructure" / "portal_auth" / "server.py",
    PACKAGES_DIR / "infrastructure" / "portal_db.py",
    PACKAGES_DIR / "tools" / "__init__.py",
    PACKAGES_DIR / "tools" / "whatsapp_reply_approval" / "__init__.py",
    PACKAGES_DIR / "tools" / "whatsapp_reply_approval" / "server.py",
]

FORBIDDEN_PATHS = [
    PACKAGES_DIR / "billing_ledger.py",
    PACKAGES_DIR / "portal_auth",
    PACKAGES_DIR / "portal_auth" / "__init__.py",
    PACKAGES_DIR / "portal_auth" / "server.py",
    PACKAGES_DIR / "portal_db.py",
    PACKAGES_DIR / "whatsapp_reply_approval",
    PACKAGES_DIR / "whatsapp_reply_approval" / "__init__.py",
    PACKAGES_DIR / "whatsapp_reply_approval" / "server.py",
]


def relative_paths(paths: list[Path]) -> str:
    return "\n".join(f"- {path.relative_to(REPO_ROOT)}" for path in paths)


def main() -> int:
    errors: list[str] = []

    if not PACKAGES_DIR.exists():
        errors.append("packages/ is missing.")
    else:
        missing_required = [path for path in REQUIRED_FILES if not path.exists()]
        if missing_required:
            errors.append("Missing required shared package files:\n" + relative_paths(sorted(missing_required)))

        present_forbidden = [path for path in FORBIDDEN_PATHS if path.exists()]
        if present_forbidden:
            errors.append("Legacy package paths must be removed:\n" + relative_paths(sorted(present_forbidden)))

        top_level_entries = [
            path
            for path in PACKAGES_DIR.iterdir()
            if not path.name.startswith(".") and path.name != "__pycache__"
        ]

        unexpected_files = [path for path in top_level_entries if path.is_file()]
        if unexpected_files:
            errors.append("Loose files at packages/ root are not allowed:\n" + relative_paths(sorted(unexpected_files)))

        unexpected_dirs = [
            path for path in top_level_entries if path.is_dir() and path.name not in ALLOWED_TOP_LEVEL_DIRS
        ]
        if unexpected_dirs:
            errors.append("Unexpected top-level packages/ directories:\n" + relative_paths(sorted(unexpected_dirs)))

    if errors:
        print("\n\n".join(errors), file=sys.stderr)
        return 1

    print("Package layout OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
