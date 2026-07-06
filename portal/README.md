# Assistyca Portal

This folder holds the client-facing portal for reviewing assigned features, opening a feature studio, editing reply settings, previewing agent responses, and reviewing billing.

It is intentionally separate from the reusable spec and client config layers.

## What lives here

- `index.html` for the tabbed app shell
- `styles.css` for the interface
- `app.js` for the OTP sign-in flow, tab state, account menu, and preview behavior

## Portal layout

- `Features` for the client account and its assigned capabilities. Click one to open the tool preview or editor.
- `Preview` and `Simulator` panels still exist in the portal code, but they are hidden from the main nav for now
- The Tool page uses inner navigation for overview and editor, then opens a separate connection guide that explains the Meta Embedded Signup flow before the tool is marked live
- The WhatsApp screen no longer asks for raw access tokens; the backend keeps the Meta app secrets (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, and `WHATSAPP_APP_SECRET`) and routes by WABA ID and phone number ID
- The backend connection details still live in the per-client backend config at `clients/<client-id>/backend.json`, with the raw secrets in the backend deployment environment or the same file for local setups
- `Settings` opens as a modal overlay for account details and portal preferences
- `Billing` is available from the account menu and shows the current month, per-tool usage, per-model usage, and historical monthly charges
- The top-right menu opens account, settings, and log out actions
- The simulator's Edit button opens [`../approval.html`](../approval.html), a reusable local approval page that is now only a debug fallback.

## Sign-in flow

- Clients sign in with email and a one-time code.
- The code is now issued by `scripts/run_portal_server.py` and verified by the server instead of being mocked in the browser.
- Set either the SMTP variables or the Resend variables so the server can actually email the code.
- Registered emails now live in the backend SQLite database at `portal/portal.db` by default.
- Set `PORTAL_DB_SEED_REGISTERED_EMAILS` to bootstrap the database the first time it starts. `PORTAL_REGISTERED_EMAILS` is still accepted as a legacy bootstrap alias.
- Set `PORTAL_DB_SEED_ADMIN_EMAILS` to promote bootstrap users to admin on startup. `PORTAL_ADMIN_EMAILS` is still accepted as a legacy alias.
- Set `PORTAL_SUPPORT_PHONE` to the phone number shown to anyone who is not registered.
- The simulator is still browser-local, so it can be tested before any WhatsApp webhook or approval server exists, but the real approval flow is now routed through the Meta connection and backend webhook setup.

## Recommended test hosting

For a free, non-24/7 test server, deploy the repo to Render as a free web service and use Resend for OTP delivery.

Why this setup works:

- Render free web services can host the Python portal backend and static portal together.
- Render free services block outbound SMTP ports, so an HTTPS email API is the safer choice.
- Resend has a free tier and sends over HTTPS, which fits the free Render plan.

When you are ready for always-on hosting, you can upgrade the Render service to a paid plan and keep the same code.

Required environment variables on Render:

- `PORTAL_MAIL_PROVIDER=resend`
- `PORTAL_RESEND_API_KEY`
- `PORTAL_RESEND_FROM_EMAIL` for a verified sender like `sign-in@yourdomain.com` or `Assistyca <sign-in@yourdomain.com>`
- `PORTAL_RESEND_FROM_NAME` for the sender label shown in the inbox
- `PORTAL_PRODUCT_NAME` for the sign-in email subject and product branding inside the email
- `PORTAL_DB_PATH` for the SQLite database file, which defaults to `portal/portal.db`
- `PORTAL_DB_SEED_REGISTERED_EMAILS` for the comma-separated list of portal users used only when the database starts empty
- `PORTAL_DB_SEED_ADMIN_EMAILS` for the comma-separated list of admin portal users that get promoted on startup
- `PORTAL_SUPPORT_PHONE` for the phone number shown to blocked sign-in attempts
- `PORTAL_SESSION_SECRET` optional but recommended when you want session signing to stay independent from mail-provider credentials
- `PORTAL_BILLING_INPUT_TOKEN_PRICE_MULTIPLIER` controls the input-token multiplier for the default billing plan. The default is `1.5`.
- `PORTAL_BILLING_OUTPUT_TOKEN_PRICE_MULTIPLIER` controls the output-token multiplier for the default billing plan. The default is `1.5`.
- `PORTAL_BILLING_MULTIPLIER` is still accepted as a legacy fallback for both billing multipliers.
- `PORTAL_BILLING_DATA_PATH` optional path to a JSON billing ledger used only as a sample fallback. It defaults to `portal/billing.sample.json`.
- `PORTAL_BILLING_MINIMUM_MONTHLY_CHARGE` sets the minimum monthly charge floor per tool. The default is `14.9`.
- `PORTAL_BILLING_CURRENCY` controls the display currency. The default is `USD`.

The `PORTAL_RESEND_API_KEY` and `PORTAL_RESEND_FROM_EMAIL` values should be added as secrets in the Render dashboard.
Portal sessions now default to 180 days and survive server restarts when the signing secret stays stable.

## Local usage

Run the combined portal server so the UI and OTP API share the same origin.

Example:

```bash
PORTAL_SMTP_HOST=smtp.example.com \
PORTAL_SMTP_FROM_EMAIL=sign-in@example.com \
python3 scripts/run_portal_server.py --port 8000
```

Then visit `http://localhost:8000/portal/`.

To inspect the registered users table from the terminal, run `python3 scripts/portal_db.py list-users`.

If you open the static portal from GitHub Pages, the UI falls back to `http://127.0.0.1:8000`
unless you provide a different API base with `window.PORTAL_API_BASE`, the
`portal-api-base` meta tag, or `?apiBase=...` in the URL.
