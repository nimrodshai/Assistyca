#!/usr/bin/env bash

# Local-only helper for running the portal backend with WhatsApp env vars.
# Copy this file to scripts/run_portal_server.local.sh and replace the placeholders.

export WHATSAPP_APP_SECRET='your-meta-app-secret'
export WHATSAPP_VERIFY_TOKEN='your-meta-verify-token'
export ASSISTYCA_WHATSAPP_ACCESS_TOKEN='your-whatsapp-access-token'
export ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID='your-whatsapp-phone-number-id'
export WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_NAME='notification_message'
export WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_LANGUAGE='en_US'
# Optional when approval links should use a public hostname instead of localhost.
# export PUBLIC_BASE_URL='https://your-portal-host.example.com'
# Optional for the Google Calendar OAuth flow.
# export GOOGLE_OAUTH_CLIENT_ID='your-google-oauth-client-id'
# export GOOGLE_OAUTH_CLIENT_SECRET='your-google-oauth-client-secret'
# export GOOGLE_OAUTH_REDIRECT_URI='http://127.0.0.1:8000/api/oauth/google/calendar/callback'

python3 scripts/run_portal_server.py --port 8000
