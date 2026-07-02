#!/usr/bin/env python3
"""Create a starter technical/product spec JSON file from the reusable template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "clients" / "_template" / "technical-spec" / "spec.json"


def load_template() -> dict[str, Any]:
    with TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def apply_meta_overrides(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    meta = spec.setdefault("meta", {})
    for key in ("title", "client_name", "project_name", "prepared_by", "date", "status", "language"):
        value = getattr(args, key)
        if value:
            meta[key] = value
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a starter technical/product spec JSON file.")
    parser.add_argument("output", type=Path, help="Path to write the JSON file.")
    parser.add_argument("--title", default=None, help="Spec title.")
    parser.add_argument("--client-name", default=None, help="Client display name.")
    parser.add_argument("--project-name", default=None, help="Project name.")
    parser.add_argument("--prepared-by", default=None, help="Prepared by name.")
    parser.add_argument("--date", default=None, help="Spec date in YYYY-MM-DD format.")
    parser.add_argument("--status", default=None, help="Spec status.")
    parser.add_argument("--language", default=None, help="Language code.")
    args = parser.parse_args()

    spec = apply_meta_overrides(load_template(), args)
    args.output = args.output.expanduser().resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
