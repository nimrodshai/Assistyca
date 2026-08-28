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

## Email providers

The `email` connection holds one mailbox, from either provider:

| Provider | `metadata.provider` | Grant | Reader |
| --- | --- | --- | --- |
| Gmail | `google_gmail` | `gmail.readonly` | `gmail_summary.py` |
| Outlook / Microsoft 365 | `microsoft_outlook` | `Mail.Read` + `offline_access` | `outlook_summary.py` |

Both readers return the same per-message shape (`id`, `threadId`, `from`,
`subject`, `date`, `snippet`, `attachments`), so the email digest and the
receipt bundle never learn which mailbox a run came from. A run picks its
reader from the saved credential, which names its own provider.

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
Azure app registration with the delegated `Mail.Read` permission, and register
`https://<host>/api/oauth/microsoft/email/callback` as a redirect URI.
`MICROSOFT_OAUTH_TENANT` defaults to `common`, which accepts both work and
personal Microsoft accounts; set it to a tenant ID to restrict sign-in to one
organisation. With these unset the portal runs normally and only the "Sign in
with Microsoft" button reports that it is not configured.
