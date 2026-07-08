#!/usr/bin/env bash

# Local-only helper for running the portal backend with WhatsApp env vars.
# Copy this file to scripts/run_portal_server.local.sh and replace the placeholders.

export WHATSAPP_APP_SECRET='your-meta-app-secret'
export WHATSAPP_VERIFY_TOKEN='your-meta-verify-token'
export WHATSAPP_ACCESS_TOKEN='your-whatsapp-access-token'
# Optional when approval links should use a public hostname instead of localhost.
# export PUBLIC_BASE_URL='https://your-portal-host.example.com'

python3 scripts/run_portal_server.py --port 8000
