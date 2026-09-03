# Assistyca Portal

This folder holds the client-facing portal for reviewing assigned features, opening a feature studio, editing reply settings, previewing agent responses, and reviewing billing.

It is intentionally separate from the reusable spec and client config layers.

## What lives here

- `index.html` for the tabbed app shell
- `styles.css` for the interface
- `app.js` for the OTP sign-in flow, tab state, account menu, and preview behavior
- The backend now owns the feature catalog, activation state, and billing entitlements. Every client can use every active tool, so there is nothing to assign per client. The browser keeps only local editor and draft setup state.

## Portal layout

- `Features` for the client account and the tools it can use. Click one to open the tool preview or editor.
- `About your business` in the account menu for shared business or personal context that should follow the user across tools.
- `Preview` and `Simulator` panels still exist in the portal code, but they are hidden from the main nav for now
- The Tool page uses inner navigation for overview, WhatsApp setup, and editor inside the portal itself
- The WhatsApp screen stores the client-owned Business Platform connection: WABA ID, Phone Number ID, access token, and owner approval phone. The backend uses those details to verify the phone number, subscribe the WABA to the shared webhook, and route inbound webhooks by phone number ID.
- The Scheduled Web Monitor runs in the backend on a recurring day interval, uses the shared OpenAI gateway plus the web search tool, and sends alerts by email, Telegram, or WhatsApp
- WhatsApp approval pages and webhook handling now live inside the portal backend at `/approval/<approval_id>` and `/webhooks/whatsapp`
- `Settings` opens as a modal overlay for account details and portal preferences
- `Billing` is available from the account menu and shows the current month, per-tool usage, per-model usage, and historical monthly charges
- The top-right menu opens business details, billing, settings, and log out actions
- The simulator's Edit button opens [`../approval.html`](../approval.html), a reusable local approval page that is now only a debug fallback.

## Sign-in flow

- Clients sign in with email and a one-time code.
- The code is now issued by `scripts/run_portal_server.py` and verified by the server instead of being mocked in the browser.
- Set either the SMTP variables or the Resend variables so the server can actually email the code.
- The same mail configuration is also used when a Scheduled Web Monitor alert is configured for email delivery.
- Registered emails now live in the backend SQLite database at `portal/portal.db` by default.
- Set `PORTAL_DB_SEED_REGISTERED_EMAILS` to bootstrap the database the first time it starts. `PORTAL_REGISTERED_EMAILS` is still accepted as a legacy bootstrap alias.
- Set `PORTAL_DB_SEED_ADMIN_EMAILS` to promote bootstrap users to admin on startup. `PORTAL_ADMIN_EMAILS` is still accepted as a legacy alias.
- Set `PORTAL_DB_SEED_PAID_EMAILS` to mark specific portal users as entitled for all billing-required tools on startup. `PORTAL_PAID_EMAILS` is still accepted as a legacy alias.
- Set `PORTAL_SUPPORT_PHONE` to the phone number shown to anyone who is not registered.
- The simulator is still browser-local, so it can be tested before any WhatsApp webhook or approval server exists, but the real approval flow is now routed through the Meta connection and backend webhook setup.

## Recommended test hosting

For a throwaway, non-24/7 test server, you can deploy the repo to Render as a free web service and use Resend for OTP delivery.

Why this setup works:

- Render free web services can host the Python portal backend and static portal together.
- Render free services block outbound SMTP ports, so an HTTPS email API is the safer choice.
- Resend has a free tier and sends over HTTPS, which fits the free Render plan.

Important:

- Render free web services use ephemeral local storage, so portal users, feature assignments, WhatsApp connection state, billing data stored in SQLite, and WhatsApp approval thread history stored in local JSON can disappear after a restart or redeploy.
- For persistent portal data, run the web service on a paid Render plan, attach a persistent disk, and point `PORTAL_DB_PATH` at the disk mount such as `/var/data/portal.db`. The portal will keep its WhatsApp approval JSON state and the receipt bundles behind workspace folders beside that database by default, for example under `/var/data/portal-whatsapp/` and `/var/data/agent-receipts/`.

When you are ready for always-on hosting, you can upgrade the Render service to a paid plan and keep the same code.

Required environment variables on Render:

- `PORTAL_MAIL_PROVIDER=resend`
- `PORTAL_RESEND_API_KEY`
- `PORTAL_RESEND_FROM_EMAIL` for a verified sender like `sign-in@yourdomain.com` or `Assistyca <sign-in@yourdomain.com>`
- `PORTAL_RESEND_FROM_NAME` for the sender label shown in the inbox
- `PORTAL_PRODUCT_NAME` for the sign-in email subject and product branding inside the email
- `PORTAL_DB_PATH` for the SQLite database file. For durable Render deploys, set this to a persistent disk path such as `/var/data/portal.db`.
- `PORTAL_DATA_ROOT` optional shared directory for portal-owned runtime files. If unset, the portal uses the parent directory of `PORTAL_DB_PATH`.
- `PORTAL_DB_SEED_REGISTERED_EMAILS` for the comma-separated list of portal users used only when the database starts empty
- `PORTAL_DB_SEED_ADMIN_EMAILS` for the comma-separated list of admin portal users that get promoted on startup
- `PORTAL_DB_SEED_PAID_EMAILS` for the comma-separated list of portal users that should be treated as paid and entitled for billing-required tools during debugging or controlled internal testing
- `PORTAL_SUPPORT_PHONE` for the phone number shown to blocked sign-in attempts
- `PORTAL_SESSION_SECRET` **required in production**. At least 32 characters, random, and dedicated to this purpose. It signs session tokens and Google OAuth state. There is no longer a fallback to the Resend API key or SMTP password: that fallback meant the mail credential could mint a valid session for any registered email, including an admin. With no secret set the server still boots but sessions are held in memory only, so every user is signed out on restart or redeploy.
- `WHATSAPP_APP_SECRET` **required if you receive WhatsApp webhooks**. Signature verification fails closed, so `/webhooks/whatsapp` rejects every request while this is unset.
- `ASSISTYCA_WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_SENDER_ACCESS_TOKEN`, or legacy `WHATSAPP_ACCESS_TOKEN` for live WhatsApp Cloud API sends from the Assistyca-owned sender number. Owner alerts can also use the portal-saved client WhatsApp connection token when no Assistyca sender token is configured.
- `ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID` optional override for the Assistyca-owned sender number. If unset, the backend uses `1186653017865246`.
- `WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_NAME` approved Meta template for scheduled WhatsApp notifications. Defaults to `notification_message`; its body must contain one text variable (`{{1}}`) for the requested message.
- `WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_LANGUAGE` exact language code approved with that template. Defaults to `en_US`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_NAME` approved Meta template used to ask the owner whether to receive generated re-engagement report details outside the 24-hour window. Defaults to `whatsapp_reengagement_report_prompt`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_LANGUAGE` language code for that template. Defaults to `en`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_BUTTON_INDEX` quick-reply button index for the "Send details" button. Defaults to `0`.
- `WHATSAPP_REENGAGEMENT_REPORT_TEMPLATE_BUTTON_ACTION` quick-reply payload action. Defaults to `send`.
- `WHATSAPP_ALLOW_MOCK_SEND=0` in production so demos and owner alerts fail loudly unless WhatsApp Cloud API delivery is actually configured.
- `ASSISTYCA_WHATSAPP_OWNER_NUMBERS` maps phone numbers to portal accounts for people who text the Assistyca number directly, as comma-separated `number:email` pairs (`972507322341:owner@example.com`). Punctuation and the local `05x` form are normalised, so `+972 50-732-2341` and `050-7322341` both work. This is how whoever runs Assistyca reaches the agent: their number *is* the Assistyca number, so there is no client WhatsApp connection to identify them by. Without an entry here, a message to the Assistyca number from an unrecognised phone is dropped and nothing is sent back.
- `WHATSAPP_AGENT_CHAT_ENABLED` controls the WhatsApp agent conversation: an owner message to the Assistyca number that targets no approval reaches the same agent as the portal chat and gets answered over WhatsApp (see `docs/whatsapp-agent-chat.md`). The default is `1`; set `0` to restore the old help-text behaviour.
- `WHATSAPP_VERIFY_TOKEN` for Meta webhook verification
- `WHATSAPP_APP_SECRET` for webhook signature verification
- `OPENAI_API_KEY` for Scheduled Web Monitor searches and any other backend OpenAI-powered tool execution
- `TELEGRAM_BOT_TOKEN` when you want Scheduled Web Monitor alerts to be delivered through Telegram
- `PORTAL_WHATSAPP_STORE_ROOT` optional override for the per-user WhatsApp approval JSON files. If unset, the portal uses `PORTAL_DATA_ROOT/portal-whatsapp`.
- `PORTAL_AGENT_OUTPUT_DIR` optional override for the receipt bundles actions write to disk. If unset, the portal uses `PORTAL_DATA_ROOT/agent-receipts`, so workspace folders keep their files across restarts.
- `PUBLIC_BASE_URL` recommended for production so approval links and the connection payload always point at the public portal hostname
- `PORTAL_SCHEDULED_MONITOR_ENABLED` enables the recurring Scheduled Web Monitor worker. The default is `1`.
- `PORTAL_SCHEDULED_MONITOR_POLL_SECONDS` controls how often the backend checks for due monitor runs. The default is `300`.
- `PORTAL_SCHEDULED_MONITOR_MODEL` overrides the OpenAI model used for recurring monitor searches. The default is `gpt-5.5`.
- `PORTAL_SCHEDULED_MONITOR_SEARCH_CONTEXT_SIZE` controls the OpenAI web search context size. Supported values are `low`, `medium`, and `high`. The default is `medium`.
- `PORTAL_SCHEDULED_MONITOR_MAX_OUTPUT_TOKENS` caps each monitor search response. The default is `1800`.
- `PORTAL_SCHEDULED_MONITOR_MAX_ITEMS_PER_RUN` limits how many alerts a single run may send. The default is `5`.
- `PORTAL_BILLING_INPUT_TOKEN_PRICE_MULTIPLIER` controls the input-token multiplier for the default billing plan. The default is `1.5`.
- `PORTAL_BILLING_OUTPUT_TOKEN_PRICE_MULTIPLIER` controls the output-token multiplier for the default billing plan. The default is `1.5`.
- `PORTAL_BILLING_MULTIPLIER` is still accepted as a legacy fallback for both billing multipliers.
- `PORTAL_BILLING_DATA_PATH` optional path to a JSON billing ledger used only as a sample fallback. It defaults to `portal/billing.sample.json`.
- `PORTAL_BILLING_MINIMUM_MONTHLY_CHARGE` sets the minimum monthly charge floor across the whole account. The default is `50`.
- `PORTAL_BILLING_CURRENCY` controls the display currency. The default is `USD`.
- `TOKEN_PRICES_API_OPENAI_PRICES_URL` points to the shared token pricing API used to refresh OpenAI model prices. The default is `https://token-prices-api.onrender.com/api/openai/prices`.
- `LEMON_SQUEEZY_API_KEY` for subscription lookups and hosted checkout creation
- `LEMON_SQUEEZY_STORE_ID` for the Lemon Squeezy store
- `LEMON_SQUEEZY_ACTIVATION_VARIANT_ID` for the subscription or plan that should unlock feature activation
- `LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_STORE_ID` optional per-feature override for the WhatsApp Reply Assistant store ID
- `LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_VARIANT_ID` optional per-feature override for the WhatsApp Reply Assistant plan or variant ID
- `LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_PRODUCT_ID` optional per-feature product matcher when you want entitlement checks to follow a specific Lemon Squeezy product
- `LEMON_SQUEEZY_SCHEDULED_MONITOR_STORE_ID` optional per-feature override for the Scheduled Web Monitor store ID
- `LEMON_SQUEEZY_SCHEDULED_MONITOR_VARIANT_ID` optional per-feature override for the Scheduled Web Monitor plan or variant ID
- `LEMON_SQUEEZY_SCHEDULED_MONITOR_PRODUCT_ID` optional per-feature product matcher when you want entitlement checks to follow a specific Lemon Squeezy product
- `LEMON_SQUEEZY_SIGNING_SECRET` optional now, but needed once you accept Lemon Squeezy webhooks
- `LEMON_SQUEEZY_ACTIVATION_REDIRECT_URL` optional override for where checkout should return after payment. If unset, the portal uses `PUBLIC_BASE_URL/portal/#features`
- `FEATURE_ACTIVATION_PAYMENT_STATUS_CACHE_TTL_SECONDS` optional cache TTL for backend payment-status refreshes. The default is `120`.

The `PORTAL_RESEND_API_KEY` and `PORTAL_RESEND_FROM_EMAIL` values should be added as secrets in the Render dashboard.
If you want portal state to survive restarts on Render, add a persistent disk in the Render dashboard and mount it at `/var/data` or another absolute path you control, then set `PORTAL_DB_PATH` to a file inside that mount. The portal will place its WhatsApp approval store and the receipt bundles behind workspace folders in the same persistent area unless you explicitly override them.
Portal sessions now default to 180 days and survive server restarts when the signing secret stays stable.

## Local usage

Run the combined portal server so the UI and OTP API share the same origin.

Example:

```bash
PORTAL_SMTP_HOST=smtp.example.com \
PORTAL_SMTP_FROM_EMAIL=sign-in@example.com \
python3 scripts/run_portal_server.py --port 8000
```

For local WhatsApp testing, edit `scripts/run_portal_server.local.sh`, replace the placeholder values, and run:

```bash
./scripts/run_portal_server.local.sh
```

Then visit `http://localhost:8000/portal/`.

The portal setup form saves the WhatsApp Business Platform fields needed per workspace:

- `business_account_id` required WABA ID
- `phone_number_id` required
- `access_token` required for that client-owned WhatsApp Business Account. It must be able to access the phone number and subscribe the WABA to webhooks, so use a System User token with `whatsapp_business_messaging` and `whatsapp_business_management`.
- `owner_wa_id` required

Clients can find the WABA ID in Meta Business Settings at Accounts > WhatsApp Accounts, or by opening `https://business.facebook.com/latest/settings/whatsapp_account` and selecting the correct WhatsApp Business Account.

### Connecting a client's WhatsApp

Two routes exist. **Embedded Signup** is the one clients should use: they press
Connect WhatsApp, sign in with Facebook, pick their number, and the portal
receives the business account id, phone number id, and an access token scoped to
them. Nothing is copied or pasted, and the client can revoke the token from their
own Meta settings.

It needs `META_APP_ID` and `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` alongside
`WHATSAPP_APP_SECRET`, and it needs the Meta app approved as a Tech Provider.
Until all of that is in place the portal hides the button and falls back to the
manual form below, which is also still reachable behind "Enter the details
manually instead".

The one thing Embedded Signup does not return is the approval phone
(`owner_wa_id`), because Meta has no notion of it. It stays an optional field.

`WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` stay server-side in environment variables for webhook verification and signature checks. Client access tokens are never returned to the browser after save.
The saved client `phone_number_id` is used to route inbound webhooks and to send approved replies from the client's number. Owner alerts, sample alerts, Scheduled Web Monitor WhatsApp notifications, and scheduled assistant messages are sent from the Assistyca sender number instead. Scheduled assistant messages resolve the destination from the saved approval phone, use the approved `notification_message` template, and never read the client connection token or client sender number.
The browser no longer persists these WhatsApp setup fields in local storage; the portal backend is the source of truth.

For Scheduled Web Monitor delivery:

- Clients add a simple watch list in the tool editor, one item per line, then choose how many days should pass between checks.
- Findings land in the owner's in-app notification feed. Email, Telegram and WhatsApp owner alerting were removed in favour of that single durable surface, so no delivery credentials are needed.

To inspect the registered users table from the terminal, run `python3 scripts/portal_db.py list-users`.

If you open the static portal from GitHub Pages, the UI falls back to `http://127.0.0.1:8000`
unless you provide a different API base with `window.PORTAL_API_BASE`, the
`portal-api-base` meta tag, or `?apiBase=...` in the URL.

Signed-in requests authenticate with the `assistyca_portal_session` httpOnly cookie,
which the browser only attaches to same-origin requests. A cross-origin API base can
therefore serve the signed-out pages but cannot carry a session: to work against a
local backend, open the portal from that backend directly (`http://127.0.0.1:8000/portal/`)
rather than pointing a GitHub Pages copy at it.
