#!/usr/bin/env bash
set -euo pipefail

python3 scripts/check_package_layout.py
node --check portal/app.js
python3 -m unittest \
  tests.test_task_complexity \
  tests.test_calendar_summary \
  tests.test_receipt_collector \
  tests.test_receipt_judge \
  tests.test_receipt_pairing \
  tests.test_receipt_grouping \
  tests.test_agent_proposals \
  tests.test_account_facts \
  tests.test_agent_folder_contents \
  tests.test_saved_answer_receipts \
  tests.test_saved_files \
  tests.test_file_tags \
  tests.test_answer_composer \
  tests.test_fx_rates \
  tests.test_openai_sampling \
  tests.test_agent_answer_now \
  tests.test_scheduled_monitor \
  tests.test_whatsapp_tool_delivery \
  tests.test_portal_manual_run \
  tests.test_scheduled_actions \
  tests.test_source_actions \
  tests.test_whatsapp_reengagement \
  tests.test_platform_connections \
  tests.test_portal_static_pages
