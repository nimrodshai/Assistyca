#!/usr/bin/env bash
set -euo pipefail

python3 scripts/check_package_layout.py
node --check portal/app.js
python3 -m unittest \
  tests.test_task_complexity \
  tests.test_calendar_summary \
  tests.test_receipt_collector \
  tests.test_agent_proposals \
  tests.test_scheduled_monitor \
  tests.test_whatsapp_tool_delivery \
  tests.test_portal_manual_run \
  tests.test_scheduled_actions \
  tests.test_source_actions \
  tests.test_whatsapp_reengagement \
  tests.test_platform_connections \
  tests.test_portal_static_pages
