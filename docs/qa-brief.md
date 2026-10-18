# QA brief: Assistyca

What a QA pass needs to know about this project. The general method lives
with the reviewer (Oren, in the user's Claude settings); this file holds only
what is particular to Assistyca, and wins where the two differ. Whether a
feature is worth having, and how replies sound, is the product review's job;
see `docs/product-brief.md`.

## The product in one paragraph

A WhatsApp assistant for families: the week, who takes and who collects each
child, a word before each pickup, birthdays, lists and reminders. Parents
write in Hebrew or English. Partners and grandparents join from their own
phones; grandparents only see their own pickups. Two weeks free, then
$4.90 a month.

## Which code is live

- `staging` deploys to the staging service; `main` is production and moves
  only when the owner says so.
- The shared checkout sits on a stale local `main` with other sessions'
  uncommitted files. Never test from it and never touch it. Work from a
  detached worktree of `origin/staging`
  (`git fetch origin && git worktree add --detach <scratch dir> origin/staging`)
  and remove it afterwards (`git worktree remove <dir>`).

## Running things

Use `/usr/bin/python3` if `python3` lacks packages. Anything that calls the
model needs the key from `~/.zshrc`, which is not in a non-interactive shell:
`export OPENAI_API_KEY=$(grep -m1 '^export OPENAI_API_KEY=' ~/.zshrc | cut -d= -f2- | tr -d "\"'")`.
Never print it.

1. **Unit tests** - free. Don't run the whole suite with `discover`: a test
   reaches the network here and it hangs for ten minutes. Run the modules for
   the area under test: `grep -l <module> tests/test_*.py`, then
   `python3 -m unittest tests.test_a tests.test_b`. There is no `timeout`
   binary on this Mac.
2. **WhatsApp simulator** - the whole webhook-to-reply path with a real
   database and real agent turn; only Meta is missing, and every outbound
   send is captured. The best place for most flow testing.
   `python3 scripts/whatsapp_simulator.py [--from 9725...] [--message "..."]`.
   `--canned` swaps the model for a fixed reply when testing routing only
   (free). Real replies cost about a cent each.
3. **Mock families** - five families through registration, getting to know,
   and one simulated day with the clock run forward in 10-minute steps, so
   timed messages actually fire. About 4 minutes and a few dollars for all
   five; pass ids to run fewer.
   `MOCK_FAMILY_OUT=<dir> python3 scripts/mock_family_day.py [peretz levi okafor cohen-adler friedman]`.
   Check each morning plan against what the family really has that day
   (`activities_on`), not against the model's text, which can paper over a
   missing line.
4. **Scripted conversations** - eight, scored by a judge, a few cents.
   `python3 scripts/agent_conversation_eval.py [--only <name>]`.
5. **The web pages locally** - `python3 scripts/run_portal_server.py --port <port>`
   with scratch data, never the local `portal/portal.db`:
   `PORTAL_DB_PATH`, `PORTAL_DATA_ROOT`, `PORTAL_AGENT_OUTPUT_DIR` and
   `PORTAL_BILLING_DATA_PATH` pointing into the scratch dir, and `PORTAL_SESSION_SECRET` set to 32+ characters so
   sessions survive. Start it from Bash in the background - the desktop
   app's launcher is sandboxed and cannot read files under Documents - then
   open the browser pane on the plain `http://127.0.0.1:<port>` URL. The
   pane often runs hidden: it reports `visibilityState === "hidden"` and a
   screenshot can show a stale frame, so read the page text instead.
   The family pages (`/week/open/<code>`, `/lists/open/<code>`,
   `/join/<code>`, `/pay/<code>`) open from links the simulator prints.
   `/admin` signs in by an emailed code, which needs a local SMTP sink:
   `python3 -u -m smtpd -n -c DebuggingServer 127.0.0.1:<port>` and
   `PORTAL_SMTP_HOST/PORT`, `PORTAL_SMTP_STARTTLS=0`,
   `PORTAL_SMTP_FROM_EMAIL=portal@example.com`.

Stop every server and remove every scratch file and worktree before
reporting.

## The flows to cover

A thorough pass goes through all of these; a focused one, the ones touched.

- **Joining:** a stranger texts the number and gets a family account and an
  introduction; web registration (`/register`, `/register/family`) with phone
  and name, then the welcome on WhatsApp; someone who already has an account
  registers again; a phone with no account asks to be forgotten.
- **Getting to know the family:** one question at a time, a whole school day
  in one answer, corrections mid-way, the timetable as a picture or a voice
  note, the own-week question asked once only.
- **The week:** add, change and remove activities and who drives; "I'll
  collect him tomorrow" is that date only, never the weekly rota; exceptions
  (a child, a person, the whole week on hold for some days); the `/week` page
  and its share link; "what's on today / this week" answered with the
  picture.
- **The day's messages** (run the clock): the 06:00 morning plan, a word
  before the person's own drives and before a pickup nobody has taken, the
  evening question about tomorrow's open pickups, "remind me again 5 min
  before". Each arrives once, at the right time, to the right phone; the
  school bus is nobody's drive; close drives merge; nothing fires during an
  exception.
- **Family members:** invite by `/join/<code>`, the partner can edit the
  week, a grandparent only gets their own pickups, removing a member, each
  phone keeps its own thread.
- **Lists and reminders:** create, update and share a list; a reminder at a
  time (a past time is refused); a recurring scheduled action; show and
  cancel what is scheduled.
- **Birthdays:** asked once, softly; a ready-made list before the day.
- **Paying and leaving:** the trial counts down; when it ends the payment
  link arrives; `/pay/<code>` opens checkout for that account only; the
  webhook (`POST /webhooks/lemon-squeezy`, signed with
  `LEMON_SQUEEZY_SIGNING_SECRET` - use a made-up test secret locally) marks
  the account paid; a paying account's link goes to manage, never a second
  purchase. An expired trial can still delete the account, sign out and
  disconnect.
- **Languages:** the same flow in Hebrew and in English; one stray word in
  the other language does not flip the reply's language; Hebrew addresses
  one person in the gender they use, never the plural.
- **Outside the 24-hour window** a message goes as a Meta template: one line
  of prose by design.

## What can't be tested here

- Real WhatsApp delivery and Meta template approval; the simulator stands in.
- Google sign-in and real mailboxes or calendars: no real OAuth locally. Test
  what happens around it (the link is offered, a refusal is handled), not the
  sign-in itself.
- Lemon Squeezy's real checkout page; test the link and the webhook only.
- Mashov / Smart School homework logins.

## Never

- Write to production, create accounts there, or SSH into it.
- Send a message to a real phone number or a real email address.
- Use the owner's real phone number or email as test data.

## Known failures, don't re-report

- The scripted conversations score 4/8 on unchanged code, because the
  sandbox cannot make sign-in links and those replies improvise. Compare a
  run against a same-day run of the code before the change, never read it as
  pass/fail on its own.
- The "capability question" conversation returns no reply at all - a known
  bug.
