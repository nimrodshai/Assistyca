# WhatsApp Agent Conversation

The portal chat has a WhatsApp counterpart: a client texts the Assistyca
number from their own registered phone and talks to the same agent that runs
the portal chat. The web flow is unchanged; this is a second front door onto
the same agent.

## How a message is routed

An inbound webhook event to the Assistyca sender number resolves to a portal
user in one of three ways, all giving the `platform_owner_alert` route:

* **A linked number** in `user_whatsapp_numbers` — the normal path, and the
  only one that scales. Anyone can link their own phone; see below. This runs
  *before* the client-connection lookup, because the Assistyca number and a
  client's number can be the same number while Assistyca is its own first
  customer, and reading those messages as customer traffic would file them for
  approval instead of answering them.
* **A number configured on the server** — `ASSISTYCA_WHATSAPP_OWNER_NUMBERS`,
  as `number:email` pairs. A bootstrap for before any number is linked, and a
  way back in if linking ever breaks. Not the mechanism to build on.
* **A saved `owner_wa_id`** on a client's WhatsApp connection, as before.

An inbound message from a phone none of those recognise is dropped with
`No portal workspace is connected to this phone number ID` and nothing is sent
back — unless it carries a claim code. From there the split is:

1. **Approval flow keeps everything that is plainly its own**: interactive
   button taps, replies that target an approval, approval refs, re-engagement
   report requests, and bare commands (`Send`, `Skip`, `Edit`, ...) while an
   approval is pending or awaiting an edit.
2. **Everything else is a conversation with the agent.** Before this flow,
   those messages got generic help text.

The split lives in `_whatsapp_owner_event_targets_approvals`
(`packages/infrastructure/portal_auth/server.py`); the conversation itself in
`packages/infrastructure/whatsapp_agent_chat.py`.

## Linking a phone

A phone proves itself rather than being typed in. `POST
/api/whatsapp/my-numbers/code` issues a six-character code for the signed-in
account, good for fifteen minutes, one live code per account. The person sends
that code to the Assistyca number from the phone they want to use; the webhook
recognises it, links the number that actually sent it, and replies to say so.
From then on that phone reaches the agent directly.

This is why possession is proved instead of trusted: `user_whatsapp_numbers`
is keyed on the number, so whoever holds an entry receives that phone's
conversations. Letting someone type a number into a form would let them point
another person's WhatsApp at their own account.

Consequences that follow from the same rule: a code is single-use and dies on
its expiry; a number already linked to one account is never moved to another
by a code (it resolves to its own account before the claim step is reached, and
the store refuses the move underneath that anyway); and `DELETE
/api/whatsapp/my-numbers/<wa_id>` unlinks a phone, because a permission that
cannot be taken back is not a permission.

A message from an unknown number that is *not* a valid code is answered with
silence, not an explanation. Ordinary words can have the shape of a code, and
replying to every stranger would make the number a paid inbox for anyone who
found it. A code that was genuinely issued but is expired or spent does get a
reply, because that is somebody trying to connect rather than somebody talking.

`ASSISTYCA_WHATSAPP_DISPLAY_NUMBER` holds the Assistyca number in plain digits.
It is only used to build the `wa.me` tap-to-open link returned alongside a
code; without it the code still works, typed by hand.

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

A scheduled message created this way is also **delivered** over WhatsApp: the
scheduled-actions worker sends `whatsapp`-channel messages through the
Assistyca sender using the approved scheduled-notification template (so the
send works outside the 24-hour window), and falls back to the in-app feed —
recording `deliveredVia` in the action payload — when WhatsApp delivery is not
configured or the send fails.

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

## Testing without Meta

`scripts/whatsapp_simulator.py` runs the whole flow with Meta faked out. The
signature check, routing, agent turn, runners and database are all real; only
the Graph API call is replaced, so outbound messages are printed instead of
sent and inbound ones are built into Meta's own JSON shape and signed the same
way.

```bash
python3 scripts/whatsapp_simulator.py                        # chat as the owner
python3 scripts/whatsapp_simulator.py --from 14155550123     # chat as a stranger
python3 scripts/whatsapp_simulator.py --message "hi" --canned  # one shot, no model
```

It prints the routing decision under each reply, which is the part a real
handset cannot show you and is usually the answer when a message goes
unanswered. `--canned` skips the model when what you are testing is routing;
without it the turn uses the real model and needs `OPENAI_API_KEY`. `--db`
keeps the database between runs so the conversation is remembered.

Note what a stranger sees today: nothing at all. An unknown number resolves to
no account, the webhook records `No portal workspace is connected to this phone
number ID`, and no reply is sent. Any invite flow has to add a path for
unknown senders.

## Tests

`tests/test_whatsapp_agent_chat.py` drives the whole loop the way Meta does —
signed webhook POSTs against a running portal server — with the model and the
WhatsApp send mocked at their module seams.
