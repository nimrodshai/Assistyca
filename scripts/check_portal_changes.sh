#!/usr/bin/env bash
set -euo pipefail

python3 scripts/check_package_layout.py
node --check portal/app.js
python3 -m unittest \
  tests.test_whatsapp_tool_delivery \
  tests.test_portal_manual_run \
  tests.test_scheduled_actions \
  tests.test_whatsapp_reengagement \
  tests.test_portal_static_pages
