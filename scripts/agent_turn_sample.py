#!/usr/bin/env python3
"""Read a sample of real turns the way the weekly report does, by hand.

The server posts this report to the admin feed once a week. This runs the
same sampling and the same judge against a portal database and prints the
report, for reading a week early, for a different window, or for a copy of
the production database pulled down to look at a failure.

    python3 scripts/agent_turn_sample.py --db /var/data/portal.db
    python3 scripts/agent_turn_sample.py --db portal/portal.db --days 1 --size 5

Needs OPENAI_API_KEY for the judge; without it every reply is reported as
unscored, which is still a readable list of what people asked and got.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.infrastructure.agent_turns import AgentTurnSamplingConfig  # noqa: E402
from packages.infrastructure.agent_turns import format_sample_report  # noqa: E402
from packages.infrastructure.agent_turns import score_sample  # noqa: E402
from packages.infrastructure.agent_turns import turn_metrics  # noqa: E402
from packages.infrastructure.portal_db import PortalDatabase  # noqa: E402
from packages.infrastructure.reply_judge import judge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a random sample of recorded assistant turns.")
    parser.add_argument("--db", default=os.getenv("PORTAL_DB_PATH") or str(REPO_ROOT / "portal" / "portal.db"), help="portal database path")
    parser.add_argument("--days", type=int, default=7, help="how many days back to sample from (default 7)")
    parser.add_argument("--size", type=int, default=20, help="how many turns to read (default 20)")
    parser.add_argument("--threshold", type=int, default=3, help="minimum score on every point (default 3)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    args = parser.parse_args()

    database = PortalDatabase(Path(args.db))
    now = datetime.now(timezone.utc)
    config = AgentTurnSamplingConfig(days=max(1, args.days), sample_size=max(1, args.size), threshold=max(0, min(5, args.threshold)))
    report = score_sample(database, judge=judge, now=now, config=config)
    if args.json:
        print(json.dumps({"metrics": turn_metrics(database, now=now), "report": report}, ensure_ascii=False, indent=2))
        return 0
    metrics = turn_metrics(database, now=now)
    for window in ("day", "week"):
        numbers = metrics[window]
        print(
            f"{window:>4}: {numbers['turns']} turns, fallback {numbers['fallbackRate'] * 100:.1f}%, "
            f"incomplete {numbers['incompleteRate'] * 100:.1f}%, tool errors {numbers['toolErrorRate'] * 100:.1f}% {numbers['toolErrorsByCode'] or ''}"
        )
    title, body = format_sample_report(report)
    print()
    print(title)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
