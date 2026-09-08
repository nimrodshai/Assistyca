# Mailbox findings

What the assistant tells the person about their mail without being asked.

## What it looks for

Four things, all derived from a year of mail read together:

- **Unpaid invoices.** An invoice the person sent (directly or through an
  invoicing service) that no payment from that customer follows within
  thirty days. Matched by invoice reference, or by customer and amount.
- **Bills coming due.** A bill with a due date in the next thirty days, or
  overdue by up to three weeks, with no charge to that vendor after it.
- **Renewals and expiries.** Anything renewing or ending in the next
  forty-five days: insurance, licences, domains, subscriptions, return
  windows. When last year's charge from the same vendor is on record, the
  old price is quoted next to the new one.
- **Price rises.** A recurring charge whose latest amount is at least five
  percent above what the earlier charges settled on, over three or more
  charges.

The morning digest also carries the total of recent recurring charges by
currency.

## How it runs

1. **Connecting a mailbox** (Google with the Gmail scope, or Microsoft)
   queues a `first` scan two minutes out. On WhatsApp the connection
   message says the look-back is under way.
2. **The scan** runs in `FindingScanScheduler`
   (`packages/infrastructure/mailbox_finding_scans.py`), a daemon thread
   like the other schedulers. It calls `POST /api/findings/scan` over
   loopback with a short-lived session for the account, so credentials
   stay in the request handler. The handler lists every connected mailbox
   with the money and renewal words over the last 365 days (45 for later
   scans), downloads a hundred fresh messages per pass, and puts each
   batch of fifteen to the model once, asking what each message is in
   money terms. The answer is a fact row in `mail_facts`, tied to the
   wording's fingerprint; a message already read is never read again.
3. **Deriving** (`packages/infrastructure/mailbox_findings.py`) crosses the
   facts in code and stores the result in `account_findings`, one row per
   stable key. A finding that stops deriving (the payment arrived) is
   marked `resolved`; if it comes back it is `new` again.
4. **Telling.** The first scan tells the single best finding, or says that
   nothing needs attention. The next morning at the scan hour (never less
   than eight hours later) the `digest` scan tells the rest, up to six,
   plus the recurring-charges total. Every morning after, a `daily` scan
   tells only what is new. The message is a one-off `run_task` scheduled
   action: the model writes it in the person's language from the exact
   figures, and if the loop cannot, the plain sentence built from the
   figures goes instead (`fallbackText`). Delivery, the WhatsApp window
   and the in-app feed fallback are the scheduled-actions worker's.
5. **In the chat**, `show_findings` lists what is open and
   `dismiss_finding` drops one the person says is settled.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORTAL_MAILBOX_FINDINGS_ENABLED` | `1` | Off on staging, which runs no background jobs. |
| `PORTAL_MAILBOX_FINDINGS_HOUR` | `8` | Morning scan hour on the person's clock. |
| `PORTAL_MAILBOX_FINDINGS_FIRST_DELAY_MINUTES` | `2` | How long after connecting the first scan runs. |
| `PORTAL_MAILBOX_FINDINGS_POLL_SECONDS` | `60` | How often due scans are picked up. |
| `OPENAI_MAILBOX_FINDINGS_MODEL` | tier for `MEDIUM` | Per-task model override, for incidents only. |

The scheduler also needs `PORTAL_SCHEDULED_ACTIONS_ENABLED`, since that
worker delivers what a scan found.

## Reading the logs

- `mailbox_findings_scan_scheduled`: a mailbox was connected and a scan queued.
- `mailbox_findings_scan`: what one scan read (`read.fetched` vs
  `read.fromLedger`), how many facts it derived from, and how many
  findings are new.
- `[mailbox-findings] scan=… findings=… told=… next=…`: the scheduler's
  line per scan, with when the next one runs.
- `[scheduled-actions] … sending the plain one instead`: the model could
  not write the message and the fallback sentence went out.
