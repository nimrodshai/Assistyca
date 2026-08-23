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

`PORTAL_CREDENTIAL_ENCRYPTION_KEY` remains accepted as a local-development alias,
but new deployments should use `PORTAL_CREDENTIALS_KEY`.
