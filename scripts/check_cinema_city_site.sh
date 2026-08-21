#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="$ROOT_DIR/clients/CinemaCity/site"
PNPM_BIN="${PNPM_BIN:-pnpm}"

if ! command -v "$PNPM_BIN" >/dev/null 2>&1; then
  BUNDLED_PNPM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm"
  if [[ -x "$BUNDLED_PNPM" ]]; then
    PNPM_BIN="$BUNDLED_PNPM"
  else
    echo "pnpm was not found. Set PNPM_BIN to a pnpm executable." >&2
    exit 1
  fi
fi

cd "$SITE_DIR"
export PNPM_BIN

echo "Checking Cinema City site in $SITE_DIR"
"$PNPM_BIN" lint
"$PNPM_BIN" test
"$PNPM_BIN" build

if [[ "${1:-}" == "--e2e" ]]; then
  "$PNPM_BIN" test:e2e
fi
