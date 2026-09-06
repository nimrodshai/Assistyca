# Receipts

The receipt manager keeps every receipt and invoice a mailbox search pulled:
the amount, the date, who was paid, whether it calls itself a receipt or an
invoice, and the file the vendor attached. The page at `/receipts` shows
them by period, asks the owner about the ones the reading was not sure of,
lets them correct an amount by hand, and exports a summary for an
accountant. The chat still answers the question it was asked; the page is
where the receipts behind the answer end up.

## How receipts get there

Every receipt search (`search_receipts` from chat, or the "pull my
receipts" action) already reads the mailbox, judges each message
(`packages/infrastructure/receipt_judge.py`) and pairs duplicates. Once the
rows are settled, the portal server keeps them
(`_keep_search_receipts` in `packages/infrastructure/portal_auth/server.py`,
which calls `receipt_manager.store_collected_receipts`):

- A row the search counted is stored as **confirmed**, with its kind read
  from the subject and file names (`describe_document_kind`): an invoice
  when it says so, a receipt otherwise.
- The judge now says how sure it is. A verdict with `confidence: "low"`,
  whichever way it went, is stored as **unsure**: a question for the owner,
  never part of a total.
- A message the judge ruled out with confidence, and a second email about a
  payment already counted, are not kept.
- The email is the key (`account_receipts` has one row per user and
  message id), so a search run twice never keeps a receipt twice. A later
  run refreshes what it read - subject, file - but never what the owner
  decided: their yes or no, the kind they chose, an amount they typed.

The files: a bundle run saves attachments as it reads, and those are kept
as they are. An answer run saves nothing, so for each stored receipt whose
email carried a file, the server goes back to the mailbox once
(`save_message_attachments`) and files it under
`<owner>/Receipt manager/<YYYY-MM>/`, served through the existing
`/output/agent_receipts/` route with the session check it has always had.
At most 60 messages are fetched per search.

The lookup result tells the model how many receipts were kept and how many
are waiting for a yes or no (`receiptsPageNote`), and on the portal channel
hands it the page link (`receiptsPage`). On WhatsApp there is no browser
session, so no link is offered.

## The page

`/receipts` serves `portal/receipts.html` (`receipts.js`, `receipts.css`),
a mobile-first page with the session cookie and no inline script:

- A period picker (this month, last month, last 3 months, quarter, year,
  last year, all dates, custom) and filter chips: all, receipts, invoices,
  needs a look.
- Totals per currency for the period, with counts by kind and how many
  have no amount. Currencies are never added together.
- "Is this a receipt or an invoice?" cards for the unsure ones: the email's
  subject, the judge's reason, the amount and file if any, and Yes / No.
  Yes opens a kind choice and an amount box; No leaves it out but keeps the
  row so the same email is not asked about again. Rejected rows sit in a
  collapsed section with a way back.
- Confirmed receipts grouped by month, each with date, vendor, subject,
  amount (or "Set amount"), kind badge and a file chip that opens the PDF.
- A detail view for editing amount, currency, date, kind, vendor, paid-to
  and a note for the accountant; the files; the email text; and delete.
- "Add a receipt by hand" for a paper or cash receipt.
- Export: Excel, CSV or PDF for the period shown.

## API

| Method | Path | Does |
| --- | --- | --- |
| GET | `/api/receipts?from=&to=&status=&kind=` | receipts in the range, `summary` figures, `unsureTotal` |
| GET | `/api/receipts/<id>` | one receipt |
| POST | `/api/receipts` | `{vendor, amount, currency, receiptDate, kind, notes}` typed in by hand |
| POST | `/api/receipts/<id>` | any of `{status, kind, amount, currency, vendor, paidTo, receiptDate, notes}` |
| DELETE | `/api/receipts/<id>` | remove from the page (the email stays) |
| GET | `/api/receipts/export?from=&to=&format=xlsx\|csv\|pdf` | confirmed receipts in the range as a download |

`status` is `confirmed`, `unsure` or `rejected`; `kind` is `receipt` or
`invoice`. Setting an amount marks it as the owner's (`manualAmount`), and
setting a status or kind records `decidedAt`; a later search leaves both
alone. A range keeps only dated receipts inside it; without a range,
everything comes back, undated last.

The export carries the confirmed receipts in the range as rows (date,
vendor, paid to, type, amount, currency, subject, mailbox, file, notes)
followed by the figures: counts by kind, totals per currency, per month and
per vendor. The Excel file has the same two sheets as the bundle export.
The PDF is a landscape summary; without reportlab a plain-text PDF is
written instead.

Limits: 5,000 receipts per account; 300 characters for text fields, 600
for notes. The portal's account menu has a Receipts entry that opens the
page. Receipts are deleted with the account.
