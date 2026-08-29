# WhatsApp Reply Approval Backend

This repository now has a reusable backend service for the WhatsApp reply approval flow.

## Why A Server Is Required

For a real WhatsApp integration, Meta must be able to reach a public webhook URL when a new message arrives. That means the production version needs a server, not only the local static portal.

You can still develop locally. The usual pattern is:

1. Run the backend on `localhost`.
2. Expose it with a tunnel during testing if you want WhatsApp to hit it.
3. Point the Meta webhook callback at the tunnel or production URL.

## SaaS Connection Pattern

For a multi-tenant product, the usual setup is:

- Create one Meta app for the whole product.
- Let each customer connect their own WhatsApp Business Account through Embedded Signup.
- Store each connected WABA ID, phone number ID, and customer access token server-side through the portal connection flow. The customer token must include WhatsApp messaging access plus WABA management access so the backend can subscribe the WABA webhook.
- Keep shared app secrets only in the backend deployment environment as `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET`.
- Keep Assistyca-owned sender credentials in the backend deployment environment as `ASSISTYCA_WHATSAPP_ACCESS_TOKEN` and, if overriding the built-in default, `ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID`.
- Use one webhook endpoint for all tenants, then route each event by WABA ID or phone number ID.

## Coexistence (Owner Keeps WhatsApp On Their Phone)

Most owners will not delete WhatsApp from their handset to sign up. Coexistence
lets the WhatsApp Business app and the Cloud API share one number, so the owner
keeps chatting normally while we watch.

How it differs from the migration flow:

- The signup popup is launched with `featureType: "whatsapp_business_app_onboarding"`,
  which adds a "connect your existing WhatsApp Business account" option.
- The number is **never** registered. `register_whatsapp_phone_number` is skipped
  entirely when the browser reports `onboarding_type: "coexistence"`; calling it
  would move the number onto the API and take it off the phone.
- The connection is stored with `metadata.onboarding = "coexistence"`.

Requirements on the customer's side:

- The number must be on the **WhatsApp Business app** (v2.24.17+), not the
  consumer WhatsApp app.
- Group chats, disappearing messages, view-once, live location, calls, and the
  catalog/orders tools do not sync. Broadcast lists become read-only.
- Throughput on a coexistence number is fixed at 20 messages/sec.

### Webhook Fields To Enable

These must be subscribed in the Meta App Dashboard webhook config, alongside
`messages`. Without them the connection succeeds but nothing arrives:

- `smb_message_echoes` -- messages the owner sends from their own phone.
- `history` -- up to 180 days of past conversation, backfilled in chunks when
  the number is first connected. Media asset ids only resolve for messages
  within 14 days of onboarding.
- `smb_app_state_sync` -- contact changes. Received but not yet stored.

### How Coexistence Traffic Is Handled

`extract_coexistence_events` parses these fields and `record_coexistence_message`
stores them. Both halves of the conversation land in the normal thread, keyed by
the customer, with `direction` derived by comparing each message's `from` against
the business number.

Coexistence messages never create an approval, and never reach
`handle_owner_event`. That matters: `handle_owner_event` reads messages from the
owner as approval commands, so routing echoes there would treat ordinary replies
to customers as instructions.

## What The Backend Does

- Receives inbound WhatsApp webhooks.
- Extracts the sender, latest message, and basic thread context.
- Drafts a suggested reply.
- Shows a dashboard of pending approvals.
- Opens a hosted approval page where the owner can edit the reply.
- Sends the final reply only after manual approval.

## Files

- `packages/tools/whatsapp_reply_approval/server.py` contains the reusable backend server.
- `scripts/run_whatsapp_backend.py` starts the server from the repo root.
- `clients/_template/backend.json` is the starter config for new clients.
- `clients/demo-handyman/backend.json` is the demo config in this repo.

## Local Run

```bash
python3 scripts/run_whatsapp_backend.py --config clients/demo-handyman/backend.json
```

By default the server listens on `http://127.0.0.1:8001`.

## Endpoints

- `GET /` dashboard of pending approvals
- `GET /approval/<approval_id>` hosted edit screen
- `POST /approval/<approval_id>/send` send the edited reply
- `GET /webhooks/whatsapp` webhook verification
- `POST /webhooks/whatsapp` webhook ingest
- `GET /api/approvals` and `GET /api/approvals/<approval_id>` JSON APIs

## Configuration

The JSON config is intentionally small and reusable.

- `client.id` and `client.name`
- `web.base_url`
- `whatsapp.phone_number_id`
- `whatsapp.owner_wa_id` for the owner WhatsApp number that should receive approvals
- `whatsapp.allow_mock_send`
- `assistant.tone_guidance`
- `assistant.reply_rules`
- `assistant.business_notes`
- `assistant.escalation_guidance`
- `assistant.approval_guidance`
- `assistant.example_replies`
- `assistant.response_style`

For shared SaaS deployments, client access tokens are saved server-side and never returned to the browser after save. The Assistyca sender token stays in deployment environment variables and is only used for owner alerts.

### WhatsApp Reply Assistant Template

When a customer sends a new WhatsApp message, the backend records an approval and notifies the owner. By default, that owner alert uses WhatsApp interactive reply buttons. To send an approved template instead, configure:

- `WHATSAPP_REPLY_ASSISTANT_FIRST_TEMPLATE_NAME`: approved Meta template for the first reply-assistant prompt sent for a contact. Defaults to `whatsapp_reply_assistant_1`.
- `WHATSAPP_REPLY_ASSISTANT_REPEAT_TEMPLATE_NAME`: approved Meta template for later reply-assistant prompts sent for the same contact. Defaults to `whatsapp_reply_assistant_2`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_NAME`: legacy single-template fallback, such as `new_reply_for_review`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_LANGUAGE`: template language code. For Meta's generic English translation, use `en`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_INDEX`: template button index, usually `0`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_TYPE`: use `quick_reply` for the "Sure!" flow, or `url` for a dynamic review link.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_ACTION`: quick-reply payload action. Use `generate` for the "Sure!" flow.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_DISABLE_BUTTON_INDEX`: first-template quick-reply button index for contact opt-out. Defaults to `1`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_DISABLE_BUTTON_ACTION`: quick-reply payload action for contact opt-out. Defaults to `disable_contact`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_URL_MODE`: only used for URL buttons. Use `path` when the Meta template URL is like `https://www.assistyca.com/{{1}}`; use `full` when the template expects the full review URL as `{{1}}`.

For the "Sure!" flow, both templates must have one body variable for the sender name. `whatsapp_reply_assistant_1` must have a quick reply at index `0` for `Sure!` and a quick reply at index `1` for `Never ask for this contact again`. `whatsapp_reply_assistant_2` only needs the `Sure!` quick reply at index `0`. When the owner taps `Sure!`, the inbound webhook opens the WhatsApp service window and the backend sends the generated reply review controls as a regular interactive message. When the owner taps `Never ask for this contact again`, the backend disables future reply suggestions for that contact and stores later inbound messages without creating approvals.

For the URL flow, the template must have one body variable for the sender name and one dynamic URL button variable for the approval link.

### WhatsApp Re-engagement Report Template

Re-engagement reports use a template prompt when the owner is outside the 24-hour WhatsApp service window. The backend stores the generated report, sends the template, and sends the full details only after the owner taps the quick reply.

- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_NAME`: approved Meta template for re-engagement report prompts. Defaults to `whatsapp_reengagement_report_prompt`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_LANGUAGE`: template language code. Defaults to `en`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_BUTTON_INDEX`: quick-reply button index. Defaults to `0`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_BUTTON_ACTION`: quick-reply payload action. Defaults to `send`.

The approved template must have one body variable and one quick reply button. Suggested body text:

```text
Assistyca has a re-engagement update: {{1}}. Want me to send the details?
```

Suggested quick reply button text:

```text
Send details
```

The backend fills `{{1}}` with text such as `we found 2 people who have not been reached in a long time`, and the quick-reply payload is generated as `reengagement:<report-id>:send`.

### Send Mode

- Approved replies to customers use the client connection's saved access token and phone number ID.
- Owner alerts use the Assistyca sender token and the Assistyca phone number ID when configured. The default sender ID is `1186653017865246`, overrideable with `ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID`. If no Assistyca sender token is configured, owner alerts fall back to the client's saved WhatsApp connection token and phone number ID.
- Scheduled assistant notifications always use the Assistyca sender credentials from the backend environment. They send `WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_NAME` (default `notification_message`) in `WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_LANGUAGE` (default `en_US`) and fill the template's `{{1}}` body variable with the requested message.
- If they are missing and `whatsapp.allow_mock_send` is true, the backend simulates the send so local development still works.

## Webhook Setup

The WhatsApp webhook verification endpoint is:

```text
/webhooks/whatsapp
```

Meta will send the standard verification query parameters to that route. The backend also verifies the `X-Hub-Signature-256` header when `WHATSAPP_APP_SECRET` is configured.

## Edit Flow

The dashboard’s `Edit` action opens the hosted approval page for the selected approval record. The approval page contains the draft reply in a textarea, so the owner can revise it before pressing `Send`.
