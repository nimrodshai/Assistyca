#!/usr/bin/env bash
set -euo pipefail

portal_url="${1:-https://assistyca.com/portal/}"
previous_last_modified="${2:-}"
timeout_seconds="${3:-600}"
poll_seconds="${4:-10}"

if ! [[ "${timeout_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  echo "timeout_seconds must be a positive integer" >&2
  exit 2
fi
if ! [[ "${poll_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  echo "poll_seconds must be a positive integer" >&2
  exit 2
fi

started_at="$(date +%s)"
deadline="$((started_at + timeout_seconds))"
attempt=0

while true; do
  attempt="$((attempt + 1))"
  headers=""
  status_code=""
  last_modified=""
  if headers="$(curl -I -LsS --max-time 20 "${portal_url}")"; then
    status_code="$(printf '%s\n' "${headers}" | awk '/^HTTP\// { code = $2 } END { print code }')"
    last_modified="$(printf '%s\n' "${headers}" | awk 'BEGIN { IGNORECASE = 1 } /^last-modified:/ { sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); value = $0 } END { print value }')"
  fi

  echo "attempt=${attempt} status=${status_code:-unknown} last_modified=${last_modified:-missing}"
  if [[ "${status_code}" == "200" ]] \
    && [[ -z "${previous_last_modified}" || ( -n "${last_modified}" && "${last_modified}" != "${previous_last_modified}" ) ]]; then
    echo "Portal deployment is live at ${portal_url}"
    exit 0
  fi

  now="$(date +%s)"
  if (( now >= deadline )); then
    echo "Timed out waiting for a new healthy portal deployment at ${portal_url}" >&2
    exit 1
  fi
  sleep "${poll_seconds}"
done
