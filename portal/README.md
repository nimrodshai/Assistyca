# Assistyca Portal

This folder holds the web pages around the WhatsApp assistant. Families talk to Assistyca on WhatsApp; there is no web chat. What is here:

- `admin.html`, `admin.js`, `admin.css` at `/admin`: the house's own page. It signs in by email and a one-time code and shows four tabs: Clients (who has an account, their trial, their spend), Features (one switch per feature, for every account), Turns (how the assistant's turns are holding up) and Opportunities (website leads, for the owner only). The server decides which tabs a session gets (`canManageClients`, `canReviewOpportunities` on `/api/auth/session`); anyone else who signs in is told the page is not for them. The old `/portal/` address redirects here.
- `register.html` at `/register`: the public registration page. A name and a structured WhatsApp number, and the agent texts the person first. See `docs/whatsapp-agent-chat.md`, "Registering on the web".
- `week.html`, `lists.html`, `receipts.html` and their share pages: opened from links the assistant sends in WhatsApp. A link carries a one-time sign-in, so a family never types an email.

The WhatsApp webhook lives in the same backend at `/webhooks/whatsapp`.

## Sign-in flow (admin page)

- Admins sign in with email and a one-time code, issued and verified by `scripts/run_portal_server.py`.
- Set either the SMTP variables or the Resend variables so the server can actually email the code.
- Registered emails live in the backend SQLite database at `portal/portal.db` by default.
- Set `PORTAL_DB_SEED_REGISTERED_EMAILS` to bootstrap the database the first time it starts. `PORTAL_REGISTERED_EMAILS` is still accepted as a legacy bootstrap alias.
- Set `PORTAL_DB_SEED_ADMIN_EMAILS` to promote bootstrap users to admin on startup. `PORTAL_ADMIN_EMAILS` is still accepted as a legacy alias.
- Set `PORTAL_DB_SEED_PAID_EMAILS` to mark specific users as entitled for all billing-required tools on startup. `PORTAL_PAID_EMAILS` is still accepted as a legacy alias.

## Recommended test hosting

For a throwaway, non-24/7 test server, you can deploy the repo to Render as a free web service and use Resend for OTP delivery.

Why this setup works:

- Render free web services can host the Python portal backend and static portal together.
- Render free services block outbound SMTP ports, so an HTTPS email API is the safer choice.
- Resend has a free tier and sends over HTTPS, which fits the free Render plan.

Important:

- Render free web services use ephemeral local storage, so portal users, feature state and billing data stored in SQLite can disappear after a restart or redeploy.
- For persistent portal data, run the web service on a paid Render plan, attach a persistent disk, and point `PORTAL_DB_PATH` at the disk mount such as `/var/data/portal.db`. The portal will keep the receipt bundles behind workspace folders beside that database by default, for example under `/var/data/agent-receipts/`.

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
- `ASSISTYCA_WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_SENDER_ACCESS_TOKEN`, or legacy `WHATSAPP_ACCESS_TOKEN` for live WhatsApp Cloud API sends from the Assistyca-owned sender number.
- `ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID` optional override for the Assistyca-owned sender number. If unset, the backend uses `1186653017865246`.
- `WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_NAME` approved Meta template for scheduled WhatsApp notifications. Defaults to `notification_message`; its body must contain one text variable (`{{1}}`) for the requested message.
- `WHATSAPP_SCHEDULED_NOTIFICATION_TEMPLATE_LANGUAGE` exact language code approved with that template. Defaults to `en_US`.
- `WHATSAPP_ALLOW_MOCK_SEND=0` in production so sends fail loudly unless WhatsApp Cloud API delivery is actually configured.
- `PORTAL_WHATSAPP_SIGNUP_ENABLED` whether a phone nobody knows can open an account by texting the Assistyca number. Defaults to `1`; set `0` to restore silence to unknown numbers.
- `PORTAL_WHATSAPP_SIGNUP_DAILY_CAP` how many signups may start in any 24 hours. Defaults to `50`; `0` removes the cap. See `docs/whatsapp-agent-chat.md`.
- `PORTAL_DEFAULT_TRIAL_DAYS` how many free days a newly created account starts with. Defaults to `14`. Set a length per account with `POST /api/admin/users/<email>/trial`; `0` means no limit, which is what every account created before trials existed carries. See `docs/free-trials.md`.
- `ASSISTYCA_WHATSAPP_DISPLAY_NUMBER` the Assistyca WhatsApp number in plain digits (`972559196101`). Used only to build the `wa.me` tap-to-open link handed out with a claim code; without it the code still works, typed by hand.
- `ASSISTYCA_WHATSAPP_OWNER_NUMBERS` maps phone numbers to portal accounts, as comma-separated `number:email` pairs (`972507322341:owner@example.com`). Punctuation and the local `05x` form are normalised, so `+972 50-732-2341` and `050-7322341` both work. This is a bootstrap and a way back in, **not** the normal path: people link their own phone by sending a claim code from it (see `docs/whatsapp-agent-chat.md`), which needs no configuration and no redeploy.
- `WHATSAPP_AGENT_CHAT_ENABLED` controls the WhatsApp agent conversation: a message to the Assistyca number reaches the same agent as the portal chat and gets answered over WhatsApp (see `docs/whatsapp-agent-chat.md`). The default is `1`; set `0` to restore the old help-text behaviour.
- `PORTAL_AGENT_FALLBACK_ALERT_RATE` and `PORTAL_AGENT_FALLBACK_ALERT_MIN_TURNS` set the line and the floor for the assistant fallback alert: when more than this share of the last day's turns (default `0.02`) ended in a fallback reply, on at least this many turns (default `10`), every admin gets one notification for the day. See `docs/agent-turns.md`.
- `PORTAL_AGENT_TURN_SAMPLING_ENABLED` (default `1`), `PORTAL_AGENT_TURN_SAMPLING_WEEKDAY`, `_HOUR`, `_MINUTE`, `_TIMEZONE`, `_SIZE` (default `20`) and `_THRESHOLD` (default `3`) control the weekly sample of real assistant turns scored by the judge and reported to admins. See `docs/agent-turns.md`.
- `WHATSAPP_VERIFY_TOKEN` for Meta webhook verification
- `WHATSAPP_APP_SECRET` for webhook signature verification
- `OPENAI_API_KEY` for Scheduled Web Monitor searches and any other backend OpenAI-powered tool execution
- `TELEGRAM_BOT_TOKEN` when you want Scheduled Web Monitor alerts to be delivered through Telegram
- `PORTAL_AGENT_OUTPUT_DIR` optional override for the receipt bundles actions write to disk. If unset, the portal uses `PORTAL_DATA_ROOT/agent-receipts`, so workspace folders keep their files across restarts.
- `PUBLIC_BASE_URL` recommended for production so links the assistant sends always point at the public portal hostname
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
- `LEMON_SQUEEZY_SCHEDULED_MONITOR_STORE_ID` optional per-feature override for the Scheduled Web Monitor store ID
- `LEMON_SQUEEZY_SCHEDULED_MONITOR_VARIANT_ID` optional per-feature override for the Scheduled Web Monitor plan or variant ID
- `LEMON_SQUEEZY_SCHEDULED_MONITOR_PRODUCT_ID` optional per-feature product matcher when you want entitlement checks to follow a specific Lemon Squeezy product
- `LEMON_SQUEEZY_SIGNING_SECRET` optional now, but needed once you accept Lemon Squeezy webhooks
- `LEMON_SQUEEZY_ACTIVATION_REDIRECT_URL` optional override for where checkout should return after payment. If unset, checkout returns to `PUBLIC_BASE_URL/whatsapp`, the conversation
- `FEATURE_ACTIVATION_PAYMENT_STATUS_CACHE_TTL_SECONDS` optional cache TTL for backend payment-status refreshes. The default is `120`.

The `PORTAL_RESEND_API_KEY` and `PORTAL_RESEND_FROM_EMAIL` values should be added as secrets in the Render dashboard.
If you want portal state to survive restarts on Render, add a persistent disk in the Render dashboard and mount it at `/var/data` or another absolute path you control, then set `PORTAL_DB_PATH` to a file inside that mount. The portal will place the receipt bundles behind workspace folders in the same persistent area unless you explicitly override them.
Portal sessions now default to 180 days and survive server restarts when the signing secret stays stable.

## Local usage

Run the combined portal server so the UI and OTP API share the same origin.

Example:

```bash
PORTAL_SMTP_HOST=smtp.example.com \
PORTAL_SMTP_FROM_EMAIL=sign-in@example.com \
python3 scripts/run_portal_server.py --port 8000
```

Then visit `http://localhost:8000/admin`.

To inspect the registered users table from the terminal, run `python3 scripts/portal_db.py list-users`.

Signed-in requests authenticate with the `assistyca_portal_session` httpOnly cookie,
which the browser only attaches to same-origin requests, so open the admin page from
the backend that serves it (`http://127.0.0.1:8000/admin`).
