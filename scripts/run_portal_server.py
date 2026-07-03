#!/usr/bin/env python3
"""Run the portal static server and OTP backend from the repo root."""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.chdir(REPO_ROOT)

from packages.infrastructure.portal_auth.server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
