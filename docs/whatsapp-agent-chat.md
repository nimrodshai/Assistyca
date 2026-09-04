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

A message from an unknown number that is *not* a valid code is treated as a
signup (see below) when signup is on, and answered with silence when it is off.
A code that was genuinely issued but is expired or spent always gets a reply,
because that is somebody trying to connect rather than somebody talking.

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

While step 2 runs, the phone shows "typing…". Meta's typing indicator is a
status on the inbound message (it also marks it read), so it needs that
message's id and nothing comes back to record. Meta clears it after 25
seconds or when the reply lands, whichever is first, and a turn that runs a
model can outlast that, so `assistyca_typing` renews it every 20 seconds from
a background thread until the block that sends the reply ends. The signup
concierge does the same around its model call. A failed indicator is logged
and not retried; the reply is never held back by it. In mock-send mode
nothing is sent to Meta.

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
- A phone reaches the agent once it is linked to an account — by signing up
  over WhatsApp, by sending a claim code, or by a saved `owner_wa_id` on a
  client connection. A number is only ever linked to one account.

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

A stranger texting is the signup flow: run it with `--from` and a number the
database has never seen. With `PORTAL_WHATSAPP_SIGNUP_ENABLED=0` the same
message is dropped with `No portal workspace is connected to this phone number
ID` and nothing is sent back.

## Tests

`tests/test_whatsapp_agent_chat.py` drives the whole loop the way Meta does —
signed webhook POSTs against a running portal server — with the model and the
WhatsApp send mocked at their module seams.

## Signing up by texting

A phone nobody knows can open an account in the conversation. The public link
is one link, forever — `https://wa.me/<number>?text=Hi%20Assistyca` — and
anyone who taps it (or simply texts the number) is answered, not handed a form.

The pre-account replies are written by a small model (`whatsapp_signup_concierge`,
the cheapest tier, unbilled — house cost, exactly as the About-page intake agent
is) from a fixed summary of what Assistyca does. Someone who asks "how can you
help me?" gets that answered, and in the same message is told an email is
needed to set up their account. The steer gets firmer each turn rather than
being repeated. The fixed sentence stands in whenever the model does not.

Two things the model is never allowed to be: the source of the email, and a
narrator of one. The address is found in code from what the person typed; a
model reply that contains an address is discarded for the fixed line, so no
model can cause an account or quote one back. Every message is read as the
answer. A new address creates the account
with the default free trial (see `docs/free-trials.md`), links the phone that
has been texting all along, and welcomes them; from then on that phone is an
ordinary client talking to the agent. If their opening message already
contains an address, the question is skipped.

An address that **already has an account is refused**, and they are pointed at
a portal-issued code instead. Without that refusal, typing someone else's
address would attach a stranger's phone to their workspace.

A claim code always wins over signup, because an existing client linking a
second phone is texting from a number we do not know either.

Five turns without an email and the signup is abandoned for a day: more
messages — and more model calls — from us would only cost money. Nothing else is ever sent to a phone
that is not mid-signup.

### Bounding it

The free trial bounds what one account can cost. Two more settings bound how
many accounts a day can open:

* `PORTAL_WHATSAPP_SIGNUP_ENABLED` — the kill switch. Defaults to on; `0`
  restores the old silence to unknown numbers.
* `PORTAL_WHATSAPP_SIGNUP_DAILY_CAP` — signups that may *start* in any
  24 hours. Defaults to `50`; `0` removes the cap. Past it the door closes
  quietly and `whatsapp_signup_capped` is logged.

`GET /api/admin/whatsapp/signup` shows the link, the switch, the cap, today's
started and completed counts, and the default trial length — so the state of
the public door is one request away.

## Connecting Gmail or Outlook from WhatsApp

Nobody is sent to the portal to connect an account. When a connection is
needed - right after signup, or whenever the agent is asked something that
needs the inbox or calendar - the person gets a sign-in link in the chat:
Google for a Gmail address, Microsoft for an Outlook one, both for a company
domain that could be either. The link has `login_hint` set so the right account
is already picked.

The portal's OAuth states are bound to a browser session, and a phone opening a
link from WhatsApp has none. So these links carry a different state, signed
with the same secret, holding the account, the phone, and what finishing should
do (`channel: "whatsapp"`). Both callbacks check for that state **before**
requiring a session; a state with a bad signature is ignored and falls through
to the browser path, which rejects it with its own message. WhatsApp states
live thirty minutes rather than ten, because switching apps and back takes
longer than a popup.

After the sign-in the browser lands on a one-sentence page with a way back to
WhatsApp - never on the portal - and the same sentence is sent as a message.

### Proving an account is yours

If someone signs up with an address that already has an account, they are not
sent to Settings for a code. They are sent the sign-in link for that address's
provider with `purpose: "link_account"`. Completing it proves they own the
mailbox behind the address, and therefore the account, so the phone is linked
on the spot. The provider's own account address is the proof: nothing is saved
and nothing is linked until it has been read back from Google or Microsoft and
found equal to the address they claimed. Without that check, a stranger could
attach their own mailbox to someone else's workspace by typing that someone's
email.

### What the agent may say

`toolContext.connectLinks` holds the only URLs the agent may ever send, and the
prompt tells it to repeat the matching one verbatim on its own line and never
to invent another or mention a portal. The links are minted per turn for the
linked account and phone, so one forwarded to somebody else connects nothing of
theirs to anything of ours. `build_connect_links_line` and
`build_link_existing_account_text` choose which link to show; the model never
composes a URL.

### Where the portal is still mentioned, and why

The rule is that a WhatsApp user is never sent to a website. Four replies still
name one, each for a reason worth knowing rather than a gap nobody noticed:

* **No sign-in provider configured.** With neither Google nor Microsoft OAuth
  set up there is nothing to prove account ownership with, so an address that
  already has an account falls back to "get a code from Settings". Configuring
  either provider removes this.
* **A claim code that expired or was already used.** These codes originate in
  the portal by design (linking a *second* phone to an account you are already
  signed into). At the moment the dead code arrives we know a phone and nothing
  else - not which account it was for - so a sign-in link cannot be minted.
* **Approving a proposal other than a scheduled message**, and **answering a
  receipt look-alike question**: two v1 limits of the conversation itself,
  noted under "How a turn runs". Both are about porting more of the browser's
  dispatch to the server, not about links.

## One message, one answer

Meta redelivers a webhook it did not get a quick answer to, and a reply that
runs a model and reads a calendar is never quick. Every inbound message to the
Assistyca number is therefore claimed by its WhatsApp message id in
`whatsapp_processed_messages` before anything else happens; a redelivery is
answered `duplicate` and does nothing. (Traffic to a client's own number keeps
its existing dedupe in `save_whatsapp_message`.) The proper next step is to
acknowledge the webhook before doing the work; this makes the redelivery
harmless in the meantime.

## Choosing calendars from the phone

Reading a calendar needs to know *which* calendars, and on the web a picker
appears for that. On WhatsApp the question is a **picker** - a list message
headed "Which calendars should I read?", one row per calendar with a dot in
that calendar's colour (`color_dot` maps Google's hex to the nearest emoji
circle; greys go to ⚫/⚪ by lightness rather than hue, or graphite would read
as brown). No numbered text goes beside it; the words-only list is sent only
if the picker itself cannot be.

WhatsApp's list picks one row per tap and cannot be edited afterwards, and
Meta offers no multi-select list (the real checkbox UI is a WhatsApp Flow,
which needs a published Flow and so sits behind business verification). So
the picker **behaves like checkboxes**: each tap toggles a calendar and a
fresh picker arrives with the ticks updated and a "✅ Done" row on top whose
description names the current choice; "All calendars" is one tap; Done saves.
Nothing is saved until Done or All. Words still work too - `1, 3`, the names,
or `all`. Row titles are capped at 24 characters, so an address-labelled
calendar shows the part before the `@` with the full address beneath.

It is asked at the natural moment: when Google connects and returns more than
one calendar, the "connected" message is followed by the picker rather than
letting the first real question run into it; one calendar is selected
silently. If a question does run into it later, the question is **held** in
`whatsapp_agent_state.pending_json` (with the ticks so far in `selected`) and
answered the moment the choice is saved - "Got it, I'll read Work and Family"
followed by the answer. A tap on the picker (`calpick:*`) is exempt from the
approval-flow routing that otherwise claims interactive replies.

A calendar list cached before colours were kept has none, and a picker drawn
from it shows every calendar the same. The portal never renders colours and
treats a cached list as authoritative, so the refresh is asked for only by the
WhatsApp channel (`refreshCalendarColours: true` on the run request), happens
once per connection (`calendarColoursRefreshedAt`), and never empties the
cache if Google returns nothing usable.

An open question never swallows the messages that arrive while it is open.
`parse_calendar_choice` reads words as a pick only when the *whole* message is
one - numbers, names, "all", and the small words that ride along ("family
please"). "Am I free at 3?" has a 3 in it and is not a pick, and neither is
"I want to log out from google". Those go to the model as an ordinary turn
with the open question carried as `pendingChoice` (the question and the
numbered calendar names), and the prompt tells it to decide first whether the
message answers that question. A pick in words the parser cannot place -
"the first one", "mine and the family one" - comes back as
`outcome=calendar_choice` with `calendarIndexes`, and is saved exactly as if
the numbers had been typed. Anything else is answered as it would be with no
question open, and the calendar question stays held so a tap on the picker
still works afterwards. Before this (2026-09-04) every non-pick got "I didn't
catch which ones" and the list again, three times in a row.

## Disconnecting an account from the phone

"Just disconnect me from google" used to get "I can't disconnect Google from
this chat" (2026-09-04): the model had no outcome for it, so it said so. On
WhatsApp there is no card with a Disconnect button, so the chat is the only
place it can happen, and now it does. When something is connected, the turn
prompt offers `outcome=disconnect_command` with `disconnectTargets` drawn from
`google`, `calendar`, `gmail`, `drive`, `outlook` (`google` is everything
Google holds). The chat maps those words onto the stored connections
(`connections_for_disconnect`), names exactly what would go - "Disconnect
Google Calendar and Gmail (nimrod@gmail.com) from Assistyca?" - and holds the
ids in `pending_json` as `kind: disconnect`. A plain *yes* or *no*
(`parse_yes_no`, whole phrases only) is settled locally; anything with more in
it goes to the model as an ordinary turn with `pendingChoice` of kind
`confirmation`, which comes back as `confirm`, `decline`, or whatever the
message actually was, and the question stays open. On yes the chat calls the
same `DELETE /api/platform-connections/<id>` the portal's button calls, once
per connection, so Google's grant is revoked the same way, and the reply says
what happened - including when Google did not confirm the revocation.

## A fresh morning is a fresh conversation

The signup concierge gets firmer each turn the email is not given. That count
now resets after an hour's gap, and a message that is a *question* - "how can
you help me?" - always gets the full, warm answer with three or four concrete
things the person could ask, however many times the email has been asked for.
The capability pitch lives once, in `ASSISTANT_CAPABILITIES_PITCH`, and both
the concierge and the working agent describe the same product from it.

## When something gets in the way

"Can you let me know if there are important emails from today", asked a
minute after Gmail was disconnected from the chat, got "I couldn't form a safe
response" (2026-09-04). The model had answered well; the reply was cut off by
a 700-token output budget the model's own thinking had used up, the API said
so with `status: incomplete`, nothing read the status, and a sentence written
in code went out instead. That sentence was one of more than forty: every
seam of the reply path had its own, and each was a dead end that named
neither the person's situation nor a way forward.

The rule now is that **code reports a situation and the model writes the
sentence**. A failure anywhere - the model not answering, a reply that could
not be read, a lookup that needs a mailbox nobody has connected, a runner
that threw, a voice note - becomes a *situation report*
(`packages/infrastructure/recovery_reply.py`): a code from a closed set,
what the person asked, what happened in plain words, whether asking again
would help, and the options the application has already checked are real,
including a connect link when one can be minted. One composer
(`portal_recovery_composer`, the mid tier at low effort) turns the report into
the reply, and `guard_recovery_reply` checks what code can check: every link
is one the report offered, no machinery words, a link that was forgotten is
put back. When the composer itself cannot run, `computed_recovery_sentence`
assembles the reply from the report's fields, so it still says what happened
and still ends with a step. `tests/test_recovery_reply.py` proves that for
every code and every mix of options.

Where the reports come from:

* `/api/agent/turn` recovers itself. A model error becomes
  `assistant_unavailable` (or `rate_limited`, when the failure classifier says
  so); a reply that cannot be read gets one repair try with the problem named,
  then `assistant_unclear`. Either way the endpoint answers **200** with
  `outcome: message`, `recovered: true`, `recoveryCode`, and - for the
  operator - the old `diagnostic` payload with the provider's code, so a
  billing problem is still visible without being spoken to a customer. The
  rejected text is logged in full, because a rejection logged without it can
  only be reproduced, never read.
* The WhatsApp chat reports to `POST /api/agent/recover` for everything the
  turn endpoint cannot see: a runner's `email_setup_required` or
  `calendar_setup_required` becomes `source_not_connected` with the sign-in
  links as options (before this the runner's "Open Email setup" sentence was
  repeated on the phone, word for word, with nowhere to tap); a
  `needsReceiptDecision` becomes `choice_required`; anything else a runner
  says is read into the closed set by `_situation_for_run_failure`. A
  question half answered and half blocked gets the answer, then the assembled
  sentence for the blocked part with its link. A turn that came back with no
  reply, a voice note, a schedule that would not save, a disconnect that
  failed: all reports. A trial that has ended is the one exception - it is a
  fact to state, not a snag to recover from, and recovering would spend on a
  model.

`WhatsAppRecoveryTests` in `tests/test_whatsapp_agent_chat.py` drives each of
those seams with the failure injected and the composer mocked, so what they
prove is the plumbing: the failure becomes the right report, the report
reaches the composer, and its words are what the phone receives.

The gateway change underneath (`openai_api.py`): a response marked
`incomplete` for `max_output_tokens` is sent again once with double the
budget; partial text is kept when there is any, and `OpenAIIncompleteError`
is raised when there is none. Output budgets now include thinking, and the
reasoning effort is chosen with the model in `task_complexity.py`.

## What a lookup needs, declared once

`LOOKUP_SOURCE_REQUIREMENTS` in `agent_proposals.py` says what each lookup
has to have connected: a mailbox (Gmail or Outlook) for the inbox digest and
receipt searches, the calendar for calendar questions, nothing for exchange
rates and saved folders. The same table is shown to the model as
`lookupRequirements` with a rule that covers every lookup and every source,
and it is checked in code before a runner is called
(`missing_sources_for_lookup`), so a lookup that needs a source nobody
connected is never started only to fail. It becomes a `source_not_connected`
report with the connect link, the same report a runner's own
`email_setup_required` becomes when one slips through.

An open question - which calendars, whether to disconnect - now expires after
a day (`PENDING_QUESTION_TTL_SECONDS`). A question with no timestamp is read as
stale. A "yes" the morning after is a fresh message for the model, not consent
to whatever was asked last week.
