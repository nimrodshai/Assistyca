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
- Store the WABA ID and phone number ID in backend config, not in the customer-facing portal.
- Keep the Meta app secrets only in the backend deployment environment as `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, and `WHATSAPP_APP_SECRET`.
- Use one webhook endpoint for all tenants, then route each event by WABA ID or phone number ID.

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

For shared SaaS deployments, the backend should prefer the `WHATSAPP_*` environment variables so the browser never sees the Meta app secrets.

### WhatsApp Reply Assistant Template

When a customer sends a new WhatsApp message, the backend records an approval and notifies the owner. By default, that owner alert uses WhatsApp interactive reply buttons. To send an approved template instead, configure:

- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_NAME`: approved Meta template name, such as `new_reply_for_review`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_LANGUAGE`: template language code. For Meta's generic English translation, use `en`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_BUTTON_INDEX`: URL button index, usually `0`.
- `WHATSAPP_REPLY_ASSISTANT_TEMPLATE_URL_MODE`: use `path` when the Meta template URL is like `https://www.assistyca.com/{{1}}`; use `full` when the template expects the full review URL as `{{1}}`.

The template must have one body variable for the sender name and one dynamic URL button variable for the approval link.

### Send Mode

- If `WHATSAPP_ACCESS_TOKEN` and `whatsapp.phone_number_id` are set, `Send` calls the real WhatsApp Cloud API.
- If they are missing and `whatsapp.allow_mock_send` is true, the backend simulates the send so local development still works.

The token and phone number ID are backend-owned outputs of the customer connection flow; the portal should not ask the customer to type them in.

## Webhook Setup

The WhatsApp webhook verification endpoint is:

```text
/webhooks/whatsapp
```

Meta will send the standard verification query parameters to that route. The backend also verifies the `X-Hub-Signature-256` header when `WHATSAPP_APP_SECRET` is configured.

## Edit Flow

The dashboard’s `Edit` action opens the hosted approval page for the selected approval record. The approval page contains the draft reply in a textarea, so the owner can revise it before pressing `Send`.
