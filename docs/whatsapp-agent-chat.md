# WhatsApp Agent Conversation

The portal chat has a WhatsApp counterpart: a client texts the Assistyca
number from their own registered phone and talks to the same agent that runs
the portal chat. The web flow is unchanged; this is a second front door onto
the same agent.

## How a message is routed

Every inbound webhook event to the Assistyca sender number from a known
`owner_wa_id` resolves to a portal user (`platform_owner_alert` route). From
there the split is:

1. **Approval flow keeps everything that is plainly its own**: interactive
   button taps, replies that target an approval, approval refs, re-engagement
   report requests, and bare commands (`Send`, `Skip`, `Edit`, ...) while an
   approval is pending or awaiting an edit.
2. **Everything else is a conversation with the agent.** Before this flow,
   those messages got generic help text.

The split lives in `_whatsapp_owner_event_targets_approvals`
(`packages/infrastructure/portal_auth/server.py`); the conversation itself in
`packages/infrastructure/whatsapp_agent_chat.py`.

## How a turn runs

The browser is the orchestrator for the web chat, so the WhatsApp flow closes
the same loop on the server:

1. The transcript lives in SQLite (`whatsapp_agent_messages`), and the
   proposal the conversation is currently discussing in `whatsapp_agent_state`.
2. The handler mints a 15-minute signed session token for the resolved owner
   and calls the existing agent endpoints over loopback HTTP —
   `/api/agent/turn` (with `channel: "whatsapp"`, which switches the prompt to
   text-message rules), `/api/agent/proposals/run` and
   `/api/agent/answer/compose` for `answer_now` lookups, and
   `/api/scheduled-actions` when a scheduled-message proposal is approved with
   a plain "yes".
3. The reply is reshaped for WhatsApp (single-asterisk bold, links written
   out, bullets) and sent to the owner through the Assistyca sender number.
   Replies always answer an inbound message, so they sit inside Meta's
   24-hour service window and need no template.

Proposal types other than `scheduled-message` are held in the conversation but
still finish their setup in the portal; the agent says so rather than
pretending otherwise. Account facts (remember/forget) work exactly as on the
web because the same `/api/agent/turn` handler applies them.

The user's timezone defaults from their phone country code
(`infer_timezone_from_wa_id`), so "text me at 12:40" schedules against their
local clock.

## Configuration

- `WHATSAPP_AGENT_CHAT_ENABLED` — set to `0` to restore the old behaviour
  (owner messages that target nothing get help text). Defaults to on.
- Requires `PORTAL_SESSION_SECRET` (already required for portal sign-in) and
  the Assistyca sender credentials (`ASSISTYCA_WHATSAPP_ACCESS_TOKEN`,
  `ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID`) for live replies;
  `WHATSAPP_ALLOW_MOCK_SEND=1` simulates sends in development.
- The user must have a WhatsApp connection with a saved `owner_wa_id`, and
  that number must be unique across workspaces (ambiguous numbers are not
  routed).

## Tests

`tests/test_whatsapp_agent_chat.py` drives the whole loop the way Meta does —
signed webhook POSTs against a running portal server — with the model and the
WhatsApp send mocked at their module seams.
