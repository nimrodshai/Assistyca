# Client Config Guide

This repository uses one client config per customer.

Recommended structure:

- `clients/_template/` for the starter template
- `clients/<client-id>/` for each live client
- `packages/tools/` for reusable client-facing tools
- `packages/infrastructure/` for shared backend support like auth, billing, storage, and delivery helpers
- `clients/<client-id>/backend.json` for live WhatsApp backend settings and approval routing

## Field Groups

### `client`

Basic identity and localization settings.

- `id`: stable folder-safe slug
- `name`: display name
- `industry`: the client's business type
- `status`: active, paused, or archived
- `owner`: who manages the account internally
- `timezone`, `locale`, `language`: defaults for the workflow

### `contact`

Primary business contact details.

- `primary_contact_name`
- `primary_contact_email`
- `primary_contact_phone`
- `website`

### `business`

Operational rules the agent should respect.

- `service_area`
- `business_hours`
- `core_services`
- `pricing_notes`
- `service_rules`

### `channels`

How the client talks to the agent.

- `primary`: the main channel, such as `whatsapp`
- `whatsapp.enabled`
- `whatsapp.business_account_id`
- `whatsapp.phone_number_id`
- `whatsapp.display_name`
- `whatsapp.webhook_path`
- `whatsapp.mode`

### `features`

Assigned capabilities that the client should see in the portal.

- `id`: stable slug for the capability
- `name`: display name in the portal
- `status`: active, paused, or draft
- `channel`: where the capability lives, such as `whatsapp`
- `mode`: short label for the operating mode, such as `approval_bot`
- `description`: short summary of what the feature does
- `launch_url`: optional live dashboard or tool URL to open from the portal

### `backend.json`

Runtime settings for the reusable WhatsApp approval backend.

- `client.id` and `client.name`
- `web.base_url`
- `whatsapp.verify_token`
- `whatsapp.access_token`
- `whatsapp.phone_number_id`
- `whatsapp.app_secret`
- `whatsapp.allow_mock_send`
- `assistant.*` guidance fields for reply generation

### `agent`

Behavior and responsibility of the assistant.

- `name`
- `purpose`
- `tone`
- `capabilities`
- `response_policy`

### `knowledge`

Where the agent should read business context from.

- `sources`
- `notes`

### `integrations`

External systems the client uses.

- `calendar`
- `crm`
- `payments`
- `storage`

### `guardrails`

Safety and escalation rules.

- `never_guess_prices`
- `never_share_secrets`
- `never_make_legal_or_medical_claims`
- `escalate_when`

### `ops`

Metadata for your own operations.

- `created_at`
- `updated_at`
- `tags`
- `notes`

## Rule Of Thumb

If a setting changes from client to client, keep it in `client.yaml`.
If a setting is shared across most clients, move it into reusable code under `packages/tools/` or `packages/infrastructure/`.
