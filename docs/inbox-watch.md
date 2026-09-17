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
   so on the cursor row. A burst above the 30-message read ceiling holds the
   old cursor and drains the remaining ids on later polls; a message that
   vanished is recorded as gone, so it cannot block that backlog. Access
   tokens are cached for fifty minutes so a poll refreshes them once an hour,
   not twenty times.
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
5. **Receipts are kept while the mail is already open.** Before the urgency
   filters, each new message with a receipt word, receipt-like filename or a
   currency amount goes through the existing receipt judge. Confirmed items
   and low-confidence questions are mapped into Receipts Manager with their
   provider mailbox, message id, vendor, paid-to name, subject, dates, amount,
   currency, kind, explanation, email preview and attached file. The receipt
   ledger remembers the verdict, so a later search does not judge it again.
   A judge outage leaves the candidate as an unsure item for the owner rather
   than losing it when the mailbox cursor advances.
6. **The decision, in code.** Skip when nothing is asked, the model is
   unsure, the moment has passed, it is more than seven days out, or the
   calendar already holds an event that day with a matching title. Hold
   everything else for ten minutes; anything happening today skips the
   hold. When the hold runs out the message is checked again: if the
   person opened it themselves it is let go without a word.
7. **Telling.** Alerts wait through quiet hours (22:00 to 07:00) and are
   capped at five a day. Several due at once go as one message. The
   message is a one-off `run_task` scheduled action, so the model writes
   it in the person's language from the exact facts, with the plain
   sentence built from the facts as the fallback. Delivery, the WhatsApp
   24-hour window and the in-app feed fallback are the scheduled-actions
   worker's, exactly as for reminders and mailbox findings.

## Followed conversations

A letter to an authority, a question to a supplier: the person should not
have to remember to look for the answer, or to chase it
(`packages/infrastructure/thread_follow.py`, table `followed_threads`).

1. **Starting.** `send_email` with `follow_reply` follows the thread the
   email went into; the question asking for the yes says so. Replying in a
   followed thread keeps it followed and waiting again. `follow_email`
   follows a conversation already in the mailbox, Gmail or Outlook, with no
   yes; `show_followed_emails` lists them and `stop_following_email` ends
   one (never behind a feature switch). Following needs the `inbox_watch`
   feature, since the watch is what notices the answer.
2. **An answer.** A new inbox message in a followed thread, not from the
   person, skips the urgency reading, the hold and the daily cap. It is
   recorded as `notified` with reason `followed_thread` and reported as a
   one-off action (`source: thread_follow`), in the morning when it lands in
   quiet hours. On WhatsApp with nothing else waiting, the report may offer
   one next step for a yes: the reply drafted with `send_email`, or the date
   with `create_calendar_event`. An automatic acknowledgement is reported
   but keeps the thread waiting.
3. **Silence.** A waiting thread is nudged once, the morning after the day
   the answer was expected, or a week after the person last wrote. Before
   the nudge the thread itself is read: if the person wrote again from their
   phone the nudge moves; if an answer landed outside the inbox it is
   reported instead. The nudge may offer a polite chaser for a yes.
4. **Ending.** A thread nobody touched for 45 days closes without a word.
   At most 30 are followed at once.


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
