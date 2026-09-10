# Inbox watch

Telling the person about mail that cannot wait: an interview slot to
confirm, a meeting moved to this afternoon, a reply someone needs by
Friday.

## How it runs

1. **Polling, not push.** `InboxWatchScheduler`
   (`packages/infrastructure/inbox_watch_polls.py`) polls every account
   with a connected mailbox every three minutes between 07:00 and 22:00
   on the person's clock, and every fifteen minutes at night. Each poll
   is a loopback call to `POST /api/inbox-watch/poll` with a short-lived
   session for the account, so credentials stay in the request handler.
   A failing account backs off, doubling to half an hour; an account
   whose trial has ended is left alone for twelve hours.
2. **Change tracking.** Gmail is asked for its history since the last
   history id (inbox additions only); Outlook is asked for the inbox delta
   since the last delta link. The first poll only records where the
   mailbox stands, so nothing older than the connection is ever alerted.
   A cursor the provider no longer holds starts again from now and says
   so on the cursor row. Access tokens are cached for fifty minutes so a
   poll refreshes them once an hour, not twenty times.
3. **Cheap filters first.** Mailings (an unsubscribe header, bulk or
   list precedence, auto-submitted), Gmail's promotions and social tabs,
   the person's own mail, and machine senders such as `no-reply` are
   skipped without a model call. A machine sender whose subject or body
   carries an invitation, booking, confirmation or deadline word is kept:
   calendar invitations come from no-reply addresses.
4. **One read per message.** What survives is put to the model in
   batches of ten (`packages/infrastructure/inbox_watch.py`): what kind
   of thing it is, whether the person has to act, what and who, when it
   happens, the deadline, urgency, confidence. Mailbox ids never reach
   the model. Every message the watch looked at is written to
   `inbox_watch_messages`, so nothing is judged or told twice.
5. **The decision, in code.** Skip when nothing is asked, the model is
   unsure, the moment has passed, it is more than seven days out, or the
   calendar already holds an event that day with a matching title. Hold
   everything else for ten minutes; anything happening today skips the
   hold. When the hold runs out the message is checked again: if the
   person opened it themselves it is let go without a word.
6. **Telling.** Alerts wait through quiet hours (22:00 to 07:00) and are
   capped at five a day. Several due at once go as one message. The
   message is a one-off `run_task` scheduled action, so the model writes
   it in the person's language from the exact facts, with the plain
   sentence built from the facts as the fallback. Delivery, the WhatsApp
   24-hour window and the in-app feed fallback are the scheduled-actions
   worker's, exactly as for reminders and mailbox findings.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORTAL_INBOX_WATCH_ENABLED` | `1` | Off on staging, which runs no background jobs. |
| `PORTAL_INBOX_WATCH_DAY_POLL_SECONDS` | `180` | Poll interval outside quiet hours. |
| `PORTAL_INBOX_WATCH_NIGHT_POLL_SECONDS` | `900` | Poll interval in quiet hours. |
| `PORTAL_INBOX_WATCH_QUIET_START_HOUR` / `_END_HOUR` | `22` / `7` | Quiet hours on the person's clock. |
| `PORTAL_INBOX_WATCH_HOLD_MINUTES` | `10` | How long to wait for the person to open it themselves. |
| `PORTAL_INBOX_WATCH_DAILY_CAP` | `5` | Alerts per person per day. |
| `OPENAI_INBOX_WATCH_MODEL` | tier for `MEDIUM` | Per-task model override, for incidents only. |

Needs `PORTAL_SCHEDULED_ACTIONS_ENABLED`, since that worker delivers the
alert.

## Costs

Gmail and Graph calls are free. One mid-tier model call per message that
survives the filters. WhatsApp alerts are free inside the 24-hour service
window and a template message outside it.

## Reading the logs

- `inbox_watch_poll`: one line per poll that saw new mail or sent an
  alert: how many were new, read by the model, held, skipped, released
  (opened by the person, gone, on the calendar, over the cap) or deferred
  to the morning.
- `[inbox-watch] user=… poll failed (attempt n)`: an account backing off.
- `[scheduled-actions] … sending the plain one instead`: the model could
  not write the alert and the fallback sentence went out.
