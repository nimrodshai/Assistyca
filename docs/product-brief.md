# Product brief: Assistyca

What a product reviewer needs to know about this project: whether the
features earn their place, and whether the assistant sounds like a person.
The general standard lives with the reviewer (Shai, in the user's Claude
settings); this file holds only what is particular to Assistyca, and wins
where the two differ. Whether things work correctly is QA's job; see
`docs/qa-brief.md`.

## The product and the person

Assistyca is a WhatsApp assistant for families: the week, who takes and who
collects each child, a word before each pickup, birthdays, lists and
reminders. The person on the other end is a parent - usually writing in
Hebrew, sometimes English - holding a full day, often texting in a hurry.
Partners and grandparents can join from their own phones; grandparents only
read their own pickups.

## Where the features are

There is no hand-kept feature list, on purpose; read the live code.

- **What the assistant can do:** the `ToolSpec` entries in
  `packages/infrastructure/agent_loop.py`. Each tool is a capability the
  model can use in a conversation.
- **What arrives without being asked:** `family_week_nudges.py` (the day's
  messages), `scheduled_actions.py` (what a person scheduled), the inbox
  watch and mailbox findings (`docs/inbox-watch.md`,
  `docs/mailbox-findings.md`).
- **Pages a family opens from a link:** `/week`, `/lists`, `/receipts`,
  `/join/<code>`, `/pay/<code>`, `/register`.
- **What is switched on:** the admin feature grid (`account_types.py`); a
  feature can exist in code and be off.
- **Why a feature exists:** the matching `docs/*.md`.

Product decisions the owner has made, so they are not reopened as findings:

- **Families only** since 2026-10-13. Some capabilities date from the
  business days (insurance, receipts); the grid decides whether a family
  gets them. Judge them for a family, and don't propose business features.
- **Two weeks free, then $4.90 a month.** The price is never pushed during
  the trial (`docs/family-billing.md`).
- **Three kinds of action:** a one-off runs now; an on-demand or recurring
  one is saved and runs again.
- **Connecting Google is offered, never required.** A family runs on its
  phone number alone.
- **Offers come once,** at the moment they fit, and are not repeated on
  later replies.

## Where the words come from

The live code is `origin/staging`. The shared checkout sits on a stale local
`main`; never judge from it. Work from a detached worktree of
`origin/staging` and remove it afterwards.

- `packages/infrastructure/assistant_voice.py` - `ASSISTANT_VOICE`, the one
  description of the voice. Every user-facing prompt quotes it; a new one that
  does not is itself a finding.
- Prompts that write what the person reads: `agent_loop.py` (the main turn,
  `_REPLY` and `_CHANNEL_RULES`), `answer_composer.py`, `recovery_reply.py`
  (when something went wrong), `agent_proposals.py`, `whatsapp_agent_chat.py`.
- `chat_flow.py` - the first conversation: the introduction, getting to know
  the family, then the offer to connect a mailbox and calendar.
- `family_week_nudges.py` - the morning, evening and before-a-drive messages.
  It briefs the main turn rather than calling the model itself; read it for
  what it asks the model to say.
- `group_chat_voice.py` only decides whether to speak in a group.
- Fixed text that reaches families without the model:
  `registration_welcome.py` and the Meta templates. A change there means
  resubmitting the template, which takes days.
- `reply_judge.py` - the automatic judge (truthful, forward, channel, clean,
  honest, calm). It catches correctness; the reviewer catches whether it
  sounds like a person.

## How to run it

Both harnesses call OpenAI on the key in `~/.zshrc`
(`export OPENAI_API_KEY=$(grep -m1 '^export OPENAI_API_KEY=' ~/.zshrc | cut -d= -f2- | tr -d "\"'")`).
Use `/usr/bin/python3` if `python3` lacks packages.

1. **Mock families** - five families through registration, getting to know,
   and one simulated day of nudges. About 4 minutes and a few dollars for all
   five; pass ids to run fewer.
   `MOCK_FAMILY_OUT=<dir> python3 scripts/mock_family_day.py [peretz levi okafor cohen-adler friedman]`
   Each writes `<dir>/<id>.json`. Check the morning plan against what the
   family actually has that day, not only whether it reads well.
2. **Scripted conversations** - eight, scored by the judge, a few cents.
   `python3 scripts/agent_conversation_eval.py` (or `--only <name>`).

Known baseline: 4/8 is normal, because the sandbox cannot mint sign-in links
and those replies improvise. "capability question" returning nothing is a
known bug. Don't re-report these.

## Decisions particular to Assistyca

These were made by the owner; hold replies to them.

- **Calm is the house style** - two notches quieter than marketing, but one
  small emoji now and then is wanted.
- **Hebrew address.** One person, singular, in the gender they use for
  themselves (`אני לוקחת` is a woman). Until known, wording that fits both
  (`רוצה`, `אפשר`, `מה דעתך`); never the plural dodge (`רוצים`, `תגידו`).
  Kept in `person_address.py`. One stray word in another language does not
  flip the reply's language.
- **Getting to know the family** is one question at a time, but a question
  can be about a whole school day, so a parent can answer it all at once.
  Once, at the first school week, it offers to take the timetable as a
  picture or a voice message. PDFs are read if sent, but never suggested.
- **The own-week question** ("put your own work hours in too?") is asked
  once, in the first getting-to-know, and never again.
- **A day's messages:** a morning plan, a word before the person's own
  drives and before a pickup nobody has taken, an evening question about
  tomorrow's open pickups - nothing else. No second word for the same drive;
  the school bus is nobody's drive.
- **An account holder going away** is asked once whether to hand her days to
  her partner and go quiet; if yes, her runs become his and she gets one calm
  message on the first morning. Without a partner on his own phone she is
  never silenced.
- **Outside WhatsApp's 24-hour window** a message rides a Meta template and is
  one line of prose by design - not a formatting bug. Inside the window it
  is still one or two sentences in time order, the way a friend texts;
  bullets only for three or more parallel things to scan.
- **Links** go as a short link on its own line, which WhatsApp shows as a
  button - never a long URL.
- **"What's on today / this week"** is answered with the calendar picture and
  a line or two beside it, never the list and never the week link.
- **Leaving is never behind the paywall:** an expired trial can still delete
  the account, sign out and disconnect.
