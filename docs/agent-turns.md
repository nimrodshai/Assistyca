# Seeing every turn

Phase 4 of the conversation runtime: one record per turn, three numbers on a
page, one alert, the judge in the pipeline, and a weekly sample of real turns.
The failure that started this work - a reply cut off by a token budget, logged
as a parse error with no text - would have been visible on the page and would
have raised the alert before a customer saw it.

## One record per turn

Every request that is part of a turn passes through one door in the server
(`_run_recorded_agent_request` in `packages/infrastructure/portal_auth/server.py`)
and lands on one row in `agent_turns`, keyed by the turn id:

| Field | Why it is there |
| --- | --- |
| `turn_id`, `user_id`, `channel` | find the turn from a screenshot in one query |
| `model`, `reasoning_effort`, `input_tokens`, `output_tokens`, `latency_ms` | cost and speed per turn, and per model when we switch |
| `tool_calls` (name, ok, code, ms) | what the model tried and what it was told back |
| `outcome`, `fallback_used`, `fallback_reason` | the number to alert on |
| `incomplete_responses` | how often the model came back cut off, retried or not |
| `raw_output_on_failure` | the text we did not have when the first failure happened |
| `user_message`, `reply`, `account_state` | what the weekly sample reads |

The row is written from what went in and what came out, not from what a
handler chose to report: the body is read once, the handler runs, the JSON it
answered is read back. A handler that crashes still leaves an `error` row. Model
calls are heard through `observe_responses` in the gateway, per thread, so no
call site hands anything over.

A turn starts at `/api/agent/turn` or `/api/agent/loop`, and its reply carries
`turnId`. The WhatsApp chat hands that id back on every later call for the same
message (`/api/agent/proposals/run`, `/api/agent/answer/compose`,
`/api/agent/recover`), so a lookup that failed and the recovery reply the
person finally got are on the same row as the turn that produced them. A call
that carries no id gets its own row: a lookup the browser ran from a card is
`tool_only`, counted for tool errors but not as a customer turn.

`fallback_used` is true when the reply came from the recovery composer or the
assembled sentence instead of the normal path. The reason is the situation
code, with `/computed` when even the composer could not run and the sentence
was assembled from the report.

## Three numbers

`GET /api/admin/agent-turns` and **Admin > Turns** in the portal show, over the
last day and the last week:

- **Fallback rate** - fallback replies over customer turns, with the reasons.
- **Incomplete-response rate** - turns where a model reply came back cut off.
- **Tool error rate** - failed tool calls over all tool calls, by error code.

Under them, the recent turns: when, which channel, the outcome, the tools it
ran, tokens and latency, what was asked and what was answered. Fallback rows
are marked. That is the whole dashboard.

## The alert

After every recorded turn the last 24 hours are summed. When the fallback rate
is above the line and there are enough turns for the rate to mean something,
every admin gets one notification in the in-app feed for that day, with the
count and the reasons.

- `PORTAL_AGENT_FALLBACK_ALERT_RATE` - the line. Default `0.02`.
- `PORTAL_AGENT_FALLBACK_ALERT_MIN_TURNS` - the floor. Default `10`, so one bad
  turn in a quiet hour does not page anyone; at any real volume two percent is
  reached by a handful of failures.

## Evals in the pipeline

`.github/workflows/conversation-evals.yml` runs `scripts/agent_conversation_eval.py`
on every push and pull request that touches the prompt, the tools, the loop,
the reply path, or the simulator. It needs the `OPENAI_API_KEY` repository
secret; without it the job warns and passes. The judge itself lives in
`packages/infrastructure/reply_judge.py` so the pipeline and the weekly sample
read replies the same way.

## Weekly production sampling

Once a week the server picks random turns from the last seven days, has the
judge score each reply on the five points, and posts the report to every
admin's feed: how many passed, and each reply that fell short with its scores
and the judge's note. A turn where nothing was sent back fails without a judge;
a judge outage is reported as unscored, not hidden. This is where new scripted
conversations come from.

- `PORTAL_AGENT_TURN_SAMPLING_ENABLED` - default `1`.
- `PORTAL_AGENT_TURN_SAMPLING_WEEKDAY`, `_HOUR`, `_MINUTE`, `_TIMEZONE` - when.
  Default Monday 09:30 in the re-engagement scheduler's timezone.
- `PORTAL_AGENT_TURN_SAMPLING_SIZE` - how many turns. Default `20`.
- `PORTAL_AGENT_TURN_SAMPLING_THRESHOLD` - the passing score. Default `3`.

`scripts/agent_turn_sample.py --db <path>` runs the same sample by hand and
prints the report and the three numbers.

## What this does not do

It does not make the model right every time. It makes every wrong turn
visible, bounded, and recoverable in the conversation, which is the standard
the best assistants actually meet.


## Cost by channel

Every model call a turn makes writes its usage row with the turn's `channel`
and `turn_id` (`usage_context` in `openai_api.py`, entered by the recorder),
so **Admin > Clients** can say what this month cost the house in total and per
client, split into web, WhatsApp and background work. A conversation row from
before rows carried a channel is placed by the turn whose time window holds
it; one with no such turn shows as untracked.

## Voice notes

A person can speak a message instead of typing it. The composer records
in the browser (`MediaRecorder`, Opus in WebM or Ogg, MP4 on Safari, two
minutes at most) and posts the recording to `POST /api/agent/transcribe`
as a base64 data URL under `voiceNote`. The server turns it into words
through the OpenAI gateway (`OpenAIGateway.transcribe_audio`, the model
named by `TRANSCRIPTION_MODEL` in `task_complexity.py`, overridable with
`OPENAI_TRANSCRIPTION_MODEL`) and returns `{ "text": ... }`.

The words go into the composer, not straight to the model: the person
reads what was heard, fixes a word if one was misheard, and sends. From
there the turn is an ordinary text turn; nothing downstream knows the
message was spoken.

The call is billed to the account like a turn, on the same ledger, with
`kind: "transcription"` in the usage row's metadata. Tracking is not
strict for it: a transcription model whose price is not in the pricing
table still answers, and the skipped charge shows in the log as
`openai.usage.skipped`. The endpoint is gated like a turn (signed in,
active trial) and rate-limited per account (`VOICE_TRANSCRIBE_PER_USER`).
Recordings are accepted in the containers browsers and WhatsApp produce
(`VOICE_NOTE_MIME_TYPES` in `voice_notes.py`), up to 5 MB.
