# Platform connections

The portal treats a Slack, email, calendar, Telegram, or other app connection
as a reusable account connection. It is not attached to one task or workflow.

## Credential handling

- The browser opens a short-lived password form. A credential is never put in
  the chat transcript, sent to `/api/agent/turn`, saved in `localStorage`, or
  returned by the connections API.
- The connection API accepts the credential only over the authenticated portal
  request. The server encrypts it with AES-GCM before writing SQLite. The
  database stores ciphertext and a last-four display hint only.
- The server fails closed when the encryption key or `cryptography` dependency
  is unavailable; it never falls back to plaintext storage.
- Tools that need a connected platform should decrypt the credential inside the
  server process through `CredentialVault`. They should never pass it to the
  conversational model or return it to the browser.

## Required deployment secret

Set `PORTAL_CREDENTIALS_KEY` in the deployment secret manager. Use a random
32-byte value, represented as URL-safe base64 or 64-character hex. For example,
generate one locally with:

```sh
openssl rand -base64 32
```

Copy the result into the hosting provider's encrypted environment-variable
store. Do not commit it, put it in a URL, or paste it into chat. Keep a secure
backup of the key: changing or losing it makes existing ciphertext unreadable.
Key rotation should be implemented as a controlled decrypt-and-re-encrypt
migration before replacing the old key.

OAuth with narrowly scoped permissions is preferred for providers that support
it. API-token entry remains available for providers where OAuth is not wired up
yet, with the same encrypted-at-rest path.

The existing WhatsApp-specific setup is migrated into the same vault when the
portal starts with `PORTAL_CREDENTIALS_KEY` configured. The legacy database
column remains only as an empty, one-release compatibility field after a
successful encrypt-and-read-back migration.

`PORTAL_CREDENTIAL_ENCRYPTION_KEY` remains accepted as a local-development alias,
but new deployments should use `PORTAL_CREDENTIALS_KEY`.

## Calendars

One calendar connection is not one calendar. A Google account holds the owner's
own calendar plus every calendar shared with it - Family, a partner's, a team's
- and each is a separate calendar with its own ID.

A meeting summary reads the calendars listed in the action's `calendar` field,
one provider call each, capped at five. The field holds calendar IDs:
`primary` for the connected account's own calendar, and an address for anything
else. Actions saved before the field held IDs kept free text there
(`Google Calendar`, `Connected calendar`); `parse_calendar_ids` reads every
non-address as `primary`, so those keep reading exactly what they always read.

That default is also what made a full calendar summarize as empty: an action
tagged only `Google Calendar` read `primary` alone and never saw the shared
Family calendar the meetings were actually on.

### Listing what is inside an account

`GET /api/platform-connections/calendars` returns one entry per calendar
connection, each with the calendars inside it, so the action editor can offer
them by name instead of asking anyone to find an ID in Google's settings.

Listing them is its own grant. `calendar.events.readonly` can read a calendar
but cannot say which calendars exist, so connecting Calendar now asks for
`calendar.calendarlist.readonly` alongside it. Only the events scope decides
whether the permission connected: declining the list scope leaves a working
connection that simply cannot offer the picker.

A connection made before that grant existed - or one whose owner declined it -
comes back with `status: "needs_reconnect"` and an empty calendar list rather
than an error. The editor keeps its address box for that case, and for a
calendar that was shared but never added to the account's own list.

## Email providers

A user may connect several mailboxes, in any mix of the two providers. Each
one is its own `email` connection row, identified by its address:

| Provider | `metadata.provider` | Grant | Reader |
| --- | --- | --- | --- |
| Gmail | `google_gmail` | `gmail.readonly` | `gmail_summary.py` |
| Outlook / Microsoft 365 | `microsoft_outlook` | `Mail.Read` + `User.Read` + `offline_access` | `outlook_summary.py` |

Both readers return the same per-message shape (`id`, `threadId`, `from`,
`subject`, `date`, `snippet`, `attachments`), so the email digest and the
receipt bundle never learn which mailbox a run came from. A run picks its
reader per mailbox from that mailbox's saved credential, which names its own
provider.

### Several mailboxes on one account

Connections were once unique per `(user, platform)`, so connecting a second
mailbox overwrote the first. Widening that to `(user, platform, account_address)`
was still not enough: Gmail and Outlook share the `email` platform and can
report the same address, because a personal Microsoft account may be registered
under a Gmail address. Uniqueness is now
`(user, platform, provider, account_address)`. A platform that holds one account
per user - Calendar, Drive, WhatsApp - saves with an empty address and so keeps
exactly one row, unchanged.

The `provider` column repeats what the row's metadata has always carried. A
database written before the column had it backfilled from that metadata during
the rebuild, so no row is left unidentified.

The address is read at connect time: Gmail from `users/me/profile`, which
`gmail.readonly` already covers, and Outlook from `/me`, which is why the
Microsoft grant asks for `User.Read` alongside `Mail.Read`. Reading it is a
convenience rather than a permission check, so a refusal never fails the
connect - the mailbox simply has no address until it is reconnected. A row
saved before addresses were captured is adopted by the next connect **from the
same provider** rather than left beside the new one as a duplicate; a connect
from a different provider leaves it alone, which is what stops Outlook from
overwriting an older Gmail mailbox, credential and all.

Where two connected mailboxes share an address, the portal's Mailbox dropdown
saves the connection id instead of the address, because an address that names
two mailboxes names neither. `mailboxAccount` accepts an address, a label, or a
connection id, so both forms keep working.

An action reads **every** connected mailbox and merges the results, unless its
`mailboxAccount` field names one. That field is separate from the older
`mailbox` field, which holds a provider label such as `Outlook` and is still
carried by saved actions. Naming a mailbox that is no longer connected fails
the run with `mailbox_not_connected` rather than quietly reading a different
account.

Each mailbox is read independently, so one expired credential cannot sink the
rest: the failing connection alone is marked `needs_attention`, the run
continues, and the response carries `skippedMailboxes` so a partial result is
never mistaken for a complete one. Chat reads that list out before the answer,
naming the mailbox it could not open. The run fails only when every mailbox
fails, and that failure carries `skippedMailboxes` too, so every mailbox that
was tried is named rather than only the first.

Provider messages are written for the person who reads them in chat, so they
never carry an HTTP status. The code stays in the error's `code` field and in
the logs, where the technical detail panel picks it up.

### Searching two mailboxes with one query

Gmail search strings and Microsoft Graph KQL are not interchangeable, so an
action stores search *intent* - a date window, some words, whether an
attachment is required - as a `MailQuery` in `mail_search.py`. Each reader
renders that into its own dialect.

Two constraints shape the Graph side:

- Graph rejects `$search` together with `$filter`, and `$orderby` together with
  `$search`. The date window therefore travels inside the KQL rather than as a
  filter.
- Graph's KQL date handling is looser than Gmail's `after:`/`before:`
  operators, so every message that comes back is re-checked against the window
  in `mail_search.matches` before it counts. A July receipts run cannot put a
  June receipt in the bundle even if Graph returns one.

Gmail's `in:inbox` has no KQL equivalent. An inbox-only digest reads
`/me/mailFolders/inbox/messages` instead of `/me/messages`; a receipts search
reads the whole mailbox, so filed and archived receipts are still found.

Actions saved before Outlook support stored a raw Gmail query string.
`parse_gmail_query` reads those back into the neutral shape, so an action
written against Gmail keeps working if the mailbox behind it is later an
Outlook one.

### Connecting Outlook

Google uses the Google Identity Services popup. Microsoft has no browser SDK
loaded in the portal, so Outlook uses a plain redirect: `GET
/api/oauth/microsoft/email/start` returns a sign-in URL, and
`/api/oauth/microsoft/email/callback` exchanges the code, saves the encrypted
refresh token, and returns to `/portal/?email_oauth=...`.

Set `MICROSOFT_OAUTH_CLIENT_ID` and `MICROSOFT_OAUTH_CLIENT_SECRET` from an
Azure app registration with the delegated `Mail.Read` and `User.Read`
permissions, and register
`https://<host>/api/oauth/microsoft/email/callback` as a redirect URI.
`MICROSOFT_OAUTH_TENANT` defaults to `common`, which accepts both work and
personal Microsoft accounts; set it to a tenant ID to restrict sign-in to one
organisation. With these unset the portal runs normally and only the "Sign in
with Microsoft" button reports that it is not configured.
