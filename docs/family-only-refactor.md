# Family only: the refactor list

Decided 2026-10-13: Assistyca stops serving businesses. Only families from now on.
This is the inventory of everything that has to change, surveyed on `origin/staging`
at `99e7c478`. Line numbers are from that commit and will drift as work lands.

Tick items off as they ship. Work the packages roughly in order: the decisions
first, then the big deletions, then the plumbing, then the words.

## How the business side is built in today

Three facts shape all the work below.

1. **Business is the default, not a branch.** `DEFAULT_ACCOUNT_TYPE = "business"` and
   every normaliser reads an empty or unknown type as business
   (`account_types.py:30,36`, `household.py:93`, `portal_auth/server.py:2117`,
   `portal_db.py:6150`, `register.js:580`). Every account opened before the
   register page asked, every stranger who texts the number, and every account
   made by OTP sign-in or an admin is a business today.
2. **The assistant's base prompt is written for a business owner.** Families only
   behave like families because `chat_flow.FAMILY_ACCOUNT_RULES` is pasted on top,
   telling the model to "read every mention of their business as their household"
   (`chat_flow.py:170-193`, `agent_loop.py:4157`). Dropping business means
   rewriting the base prompt, after which that override paragraph goes.
3. **Three whole products exist only for businesses** and carry most of the
   business code: the WhatsApp Reply Assistant (approval cards for a client's own
   number), the WhatsApp Re-engagement writer, and the about-page business intake
   agent. A fourth, the Scheduled Web Monitor, is worded for business and overlaps
   `schedule_task` + `search_news`.

## 0. Decisions to make first

These are not settled by "drop business" and change what the code does.

- [ ] **Existing accounts.** `users.account_type` holds `''` and `'business'` for
      every account that is not an explicit family. Flip all to family? Only active
      ones? Erase the genuine business clients (Dor, Bisi, demo accounts)? Count
      first: `SELECT account_type, COUNT(*) FROM users GROUP BY account_type`.
- [ ] **Converted accounts and the family flow.** A flipped account starts getting
      getting-to-know, week nudges and family rules. Reset
      `household_profiles.getting_to_know` for them, or mark it done?
- [ ] **Strangers who text the number.** Today they get the ask-for-email signup
      (`server.py:15110-15190`); families skip email
      (`_open_family_account_without_email`, `server.py:15397`). Does every
      stranger now open a family account with no email?
- [ ] **The admin feature grid.** `account_type_features` is keyed per type. Keep it
      as one column of global feature switches, or remove it?
- [ ] **The Scheduled Web Monitor.** Delete, or fold into `schedule_task`?
- [ ] **The about page.** `about/` is Nimrod's consultancy page "for Business
      Owners" with its own intake agent. Keep as a separate consulting page,
      rewrite, or retire?
- [ ] **Paid business features in production.** Cancel live Lemon Squeezy
      subscriptions in `billing_customers` / `feature_entitlements`? Revoke client
      WABA tokens stored in `whatsapp_connections`?
- [ ] **Grandfathered trials.** Legacy accounts carry `trial_days=0` (unlimited).
      Stay grandfathered or get a trial?
- [ ] **`clients/`, the spec scripts and their docs.** Delete, or archive to
      another repo?

## 1. Delete the business-only products

### 1a. WhatsApp Reply Assistant (approval cards on a client's own number)

- [ ] `packages/tools/whatsapp_reply_approval/server.py` (2,942 lines). **Careful:**
      the live family chat imports plain WhatsApp helpers from it
      (`send_whatsapp_message`, `send_whatsapp_typing_indicator`,
      `verify_whatsapp_signature`, `extract_inbound_events`, `extract_status_events`,
      `parse_json_body`, `parse_form_encoded`, `normalize_text`). Importers:
      `whatsapp_agent_chat.py:64-65`, `notification_delivery.py:218`,
      `portal_auth/server.py:352-359`, `whatsapp_portal_service.py:18-41`. Move
      the helpers into `packages/infrastructure/whatsapp_api.py` first, then delete
      the approval cards, owner commands, dashboard, `BackendStore` and `main()`.
- [ ] `scripts/check_package_layout.py:26-27` requires those files to exist. Update.
- [ ] `packages/infrastructure/whatsapp_portal_service.py` (1,355 lines): the
      approval and customer-event parts (`handle_customer_event` at `:1005`,
      `handle_owner_event`), the sample alert body `:373-384`, template names
      `:45-54,93-99,170`.
- [ ] `portal_auth/server.py`: the three-way inbound route
      (`platform_owner_alert` / `connected_number` / `group`) at `:14713-14755`;
      `handle_customer_event` wiring `:18929`; `handle_owner_event` `:18885`; the
      approval-targeting check on the family route `:18848-18855`; Embedded Signup
      and coexistence endpoints `:4892,5015,17477-17605`; WhatsApp history import
      `:4908,5023,18025,18234`.
- [ ] `agent_proposals.py`: proposal type `whatsapp-replies` (`:76,1244-1247`) and
      the `_TURN_WHATSAPP` prompt (`:1244-1251`).
- [ ] Portal UI: feature studio `portal/index.html:725-776,894-902`; connection
      card asking for "WhatsApp Business Account ID" and "Customer WhatsApp number"
      `:774-899`; Preview tab `:1303`; Simulator tab `:1375,1309-1437`; starter chip
      "Generate smart replies for clients…" `:428-429`; `portal/app.js` demo
      scenarios and skill cards `:274,293-326,409-411,614,726-750,817-821,
      1151-1192,1242,5769-5821,10173-10235,10747,10850,12795-12910`.
- [ ] `notification_delivery.py:18,110,121` comments about customer replies.
- [ ] `scripts/run_whatsapp_backend.py` and `docs/whatsapp-backend.md`.
- [ ] Env: `WHATSAPP_REPLY_ASSISTANT_*`, `WHATSAPP_SAMPLE_TEMPLATE_*`,
      `WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_NAME`, `META_APP_ID`,
      `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`, `CLIENT_ID`, `CLIENT_NAME`,
      `WHATSAPP_OWNER_WA_ID`, `PORTAL_WHATSAPP_STORE_ROOT`
      (`render.yaml:145-168,181-184`; production dashboard too).
- [ ] Meta templates to retire: `whatsapp_reply_assistant`,
      `whatsapp_reply_assistant_1`, `whatsapp_reply_assistant_2`,
      `assistyca_sample_alert`, `notification_message` if nothing else uses it
      (`scheduled_actions.py:43` does; check first).
- [ ] Tests: `test_whatsapp_coexistence.py`, `test_whatsapp_embedded_signup.py`,
      `test_agent_approvals.py`, `test_whatsapp_tool_delivery.py`, the Reply
      Assistant parts of `test_portal_manual_run.py` (~69 hits),
      `test_whatsapp_agent_chat.py:819-846,1249`.

### 1b. WhatsApp Re-engagement writer

- [ ] `packages/infrastructure/whatsapp_reengagement.py` (1,396 lines). Background
      job started at `server.py:19413-19438`, **on by default**
      (`whatsapp_reengagement.py:121`); staging sets it to 0, confirm production.
- [ ] `agent_proposals.py:77,1244-1247` proposal type `reengagement`.
- [ ] `server.py:4256-4262` "Demo cancelled… Customers were not contacted."
- [ ] DB tables `whatsapp_reengagement_runs`, `whatsapp_reengagement_notifications`
      (`portal_db.py:968-1000`), their indexes `:1377-1398`, and their entries in
      `USER_OWNED_TABLES` `:729-763`; `account_erasure.py:24-25` store helpers.
- [ ] Env `PORTAL_WHATSAPP_REENGAGEMENT_*`, `WHATSAPP_REENGAGEMENT_REPORT_*`
      (`render.yaml:44-55,169-176`). Meta template `whatsapp_reengagement_report_prompt`
      (not on the account list any more; confirm and drop the env).
- [ ] `portal/README.md:78,148-175`.
- [ ] Tests: `test_whatsapp_reengagement.py` (1,394 lines), `test_whatsapp_reengagement`
      in `.github/workflows/package-layout.yml:57` and `scripts/check_portal_changes.sh:45`.

### 1c. Shared business tables behind 1a and 1b

- [ ] `whatsapp_connections.business_account_id` (`portal_db.py:905-923`) is the
      client-owned WABA. `whatsapp_connections` itself is also used by family
      routing: keep the table, drop the client-WABA columns and token.
- [ ] `whatsapp_approval_index` `:925`, `whatsapp_conversations` `:933`,
      `whatsapp_conversation_messages` `:953`.

### 1d. Paid feature catalogue and Lemon Squeezy activation

- [ ] `packages/infrastructure/feature_catalog.py`: `whatsapp-business-reply-suggestion-assistant`
      (`:81-105`), `whatsapp-business-follow-up-outreach-writer` (`:107-139`),
      `scheduled-web-monitor-notifier` (`:141-174`), `DEFAULT_PROMPT.businessNotes`
      and `escalationGuidance` (`:16-17`). The catalogue is upserted on every boot
      (`portal_db.py:1914-1935`) and **never deleted**, so retiring a feature needs
      an explicit deactivate or delete of its `features`, `feature_assignments`,
      `feature_entitlements`, `feature_activations` rows.
- [ ] `packages/infrastructure/feature_activation.py` (986 lines) and
      `lemon_squeezy_api.py` (545 lines, only imported by feature_activation).
      Delete, or keep if a single family plan will be sold through Lemon Squeezy.
- [ ] Feature-id constants: `feature_activation.py:28,233,489`,
      `server.py:383,14624-14637,17657`, `whatsapp_reengagement.py:29`, `monitor.py:33`.
- [ ] `_seed_paid_emails` (`portal_db.py:2269+`) grants entitlements for every
      active `billing_required` feature.
- [ ] `portal/billing.sample.json`: its only tool is the Reply Assistant. Replace
      with family sample data or remove.
- [ ] Env `LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_*`, `LEMON_SQUEEZY_WHATSAPP_FOLLOW_UP_*`,
      `LEMON_SQUEEZY_SCHEDULED_MONITOR_*` (`feature_catalog.py:45-77`).
- [ ] Tests: `test_feature_activation.py`, `test_lemon_squeezy_api.py`
      (workflow lines 67, 71).

### 1e. Scheduled Web Monitor (pending decision)

- [ ] `packages/tools/scheduled_monitor/monitor.py` (1,937 lines). Background job
      `server.py:19441-19465`, **on by default** (`monitor.py:133`); manual run
      `server.py:17820`. Proposal type `web-monitor` (`agent_proposals.py:75,122,1219`).
      Tables `feature_monitor_runs`, `feature_monitor_notifications`
      (`portal_db.py:1197-1240`). Env `PORTAL_SCHEDULED_MONITOR_*` (`render.yaml:56-65`).
      Test `test_scheduled_monitor.py` (1,137 lines; workflow line 45,
      `check_portal_changes.sh:40`).
- [ ] If kept: rewrite the prompts "About the client or business", "Typical
      customers", "Why this matters for your business" (`monitor.py:185-187,592,
      603-644,814,820,1003,1115`) and the defence-attorney example
      (`feature_catalog.py:153-155`).

### 1f. About-page business intake agent and Opportunities

- [ ] `about/index.html` (3,336 lines) and `about/page.js` (1,690 lines): "AI Agents
      & Automations for Business Owners", services, how-it-works, the intake chat
      (`index.html:9,14,3047-3199,3264,3279`; `page.js:937,965-994`). Pending
      decision in section 0.
- [ ] `portal_auth/server.py`: endpoints `/api/contact`, `/api/contact/agent`;
      `CONTACT_AGENT_*` replies `:481-488,878-880`; Hebrew scope word list
      `:882-930`; follow-up questions `:1848-1872`; intake prompts `:1907-1930,
      7524-7525`; handlers `:416-482,1755-1940,11945-12044,13029-13043`; Telegram
      lead alert `:1963` (`TELEGRAM_CONTACT_CHAT_ID`, `render.yaml:116`);
      `PORTAL_OPPORTUNITIES_OWNER_EMAIL` `:12965`; `CONTACT_BUSINESS_MAX_LENGTH`
      `:413` (also reused by registration at `:15545`).
- [ ] DB `contact_opportunities` with `business`, `business_summary`
      (`portal_db.py:882-903`; writer `:3622-3690`, loader `:2670-2690`, erasure
      `:3893` and `account_erasure.py:120`). Archive or export before dropping.
- [ ] Admin "Opportunities" tab (`portal/index.html:290,543-561`; `portal/app.js`
      ~146 references; feed strings "New lead", "Business:" `server.py:12027,12080`).
- [ ] Test `test_contact_api.py` (465 lines; workflow line 70).

### 1g. Consulting-client folders, spec workflow and scripts (pending decision)

Nothing at runtime reads these. `/clients/` is only on the static-serve denylist
(`server.py:888,19230`, `test_portal_manual_run.py:2485`).

- [ ] `clients/{Bisi,CinemaCity,Dor,demo-handyman,_template}` (72 files, ~6 MB).
- [ ] `scripts/generate_spec_pdf.py`, `generate_tech_product_spec_json.py`,
      `generate_tech_product_spec_pdf.py`, `validate_site_handoff.py`,
      `check_cinema_city_site.sh`, `download_cinema_city_assets.py`.
- [ ] `docs/client-config.md`, `docs/spec-generation.md`,
      `docs/technical-spec-generation.md`, `docs/conversational-agent-portal-spec.md`
      (1,972 lines, describes the old catalogue, approvals and re-engagement).
- [ ] `AGENTS.md`: client-folder rules `:7-8,17,24-35`, "quoting, follow-up,
      handoff" `:41`, Scope Spec Workflow `:81-86`, "more than one client" framing
      `:88-96`. Keep the insurance rule `:44`.

## 2. Collapse the account type

### 2a. `packages/infrastructure/account_types.py`

- [ ] Docstring `:1-17`; `ACCOUNT_TYPES` business entry `:26`; `ACCOUNT_TYPE_VALUES`
      `:29`; `DEFAULT_ACCOUNT_TYPE` `:30`; `normalize_account_type` `:33-36`.
- [ ] `feature_allowed` `:152-156`, `blocked_tools` `:159-167`,
      `account_feature_allowed` `:170-180`: drop the type argument, read global
      switches. `describe_account_types` `:183-214`: one column or gone. `__all__` `:217-229`.
- [ ] Callers that only need signature updates: `agent_loop.py:327-330` (comment
      "business or family"), `whatsapp_agent_chat.py:32,2901-2903`,
      `family_week_nudges.py:75,844,926`, `inbox_watch_polls.py:31,165`,
      `mailbox_finding_scans.py:39,348`, `server.py:156-162,5619,5693,7875,
      10301,10890,11579,11728,11767`, `portal_db.py:21-23`.
- [ ] `family_week_nudges.py:1122` `accountKind == "family"` condition becomes
      always true; remove.

### 2b. Duplicate normalisers

- [ ] `household.py:26` `ACCOUNT_KINDS`, `:92-93` `normalize_account_kind`, `:843`
      `accountKind` in the described block, `:924-928` `should_describe_household`
      (always true now), `__all__` `:932,970,976`.
- [ ] `server.py:2107` `REGISTRATION_KINDS`, `:2110-2117` `normalize_registration_kind`,
      `:2120-2136` `registration_facts` (the `"what they do"` vs `"their family"` key).
- [ ] `server.py:11735` `should_describe_household` call.

### 2c. `portal_db.py`

- [ ] Schema: `users.account_type` `:817-819` (drop, or default `'family'`);
      `household_profiles.account_kind DEFAULT 'business'` `:477-478` (dead,
      "No longer read") and its insert `:9936-9938`; `account_type_features` `:1325-1334`.
- [ ] Migrations: `_migrate_users_table` `:1946-1948`, `_backfill_account_types`
      `:1958-1971`; replace with a one-off migration per the decision in section 0.
      Pinned-fact migration `:1840` lists `'what they do'`.
- [ ] Reads: `_load_user_row` `:2573,2620,2649`; `list_users` `:3465,3518,3549`;
      `_HOUSEHOLD_PROFILE_SELECT` / `_household_profile_row` `:9875-9905`.
- [ ] Methods: `update_user_account_type` `:3802-3818`, `get_account_type`
      `:3820-3828`, `count_accounts_by_type` `:3830-3835`,
      `get_account_type_permissions` `:3837-3847`, `set_account_type_feature` `:3849-3868`.
- [ ] `start_web_registration(..., business, kind="business")` `:6128-6151`;
      `delete_whatsapp_signups` docstring `:6206`.
- [ ] `profile_json.businessSummary` `:1487-1493`: a family's registration line is
      stored under this key (`server.py:15381-15385`). Rename or drop.
- [ ] `save_account_fact` docstring `:8317-8320` "how their business works".
- [ ] **Production note:** prod's database is older than the schema (see memory);
      a migration over `users.account_type` must be tested against a copy of prod.

### 2d. Admin account-types grid and per-user switch

- [ ] Server: `GET/POST /api/admin/account-types` `:4884-4886,5065-5067,13048-13093`;
      `POST /api/admin/users/<email>/account-type` `:13291-13310`;
      `_serialize_admin_user` `accountType` `:12996`; log event
      `admin.account_type_feature` `:13087`.
- [ ] `portal/app.js`: `ADMIN_ACCOUNT_TYPES` `:39-42`; `VALID_TABS` `:43`; state
      `:1267-1271`; elements `:1716-1718`; `normalizeAdminUser` `:2363`;
      `createAdminAccountTypeSelect` `:2728-2746`; users table `:14415,14437-14440,
      14476,14658,14680-14682`; `saveAdminUserAccountType` `:15047-15090`; tab
      `:12688,12733-12735,31710`; grid `:31776-31969`; `:35236,35346,37022-37025,
      37587-37600`.
- [ ] `portal/index.html:296-298` menu item, `:585-604` panel.
- [ ] `portal/styles.css:13453-13520` the Account types block.

## 3. Registration, landing page and welcome

### 3a. Landing page `index.html`

- [ ] Meta description `:9` "for families and for businesses".
- [ ] Family/Business segmented chooser: inputs and labels `:809-822`, CSS
      `:378-473,744-746` (`#for-business` at `:426`).
- [ ] The whole `.panel.business` `:866-905` (CTA `/register/business` at `:896`).
- [ ] Keep `.panel.family` `:824-864` as the only panel; point its CTA at `/register`.
- [ ] `test_portal_static_pages.py:126-173` asserts both panels and both links.

### 3b. Register page

- [ ] `portal/register.html`: meta `:9`; kind-step CSS `:226-247,311-397,401-405`;
      dots `:847,850`; the "Who am I helping?" step `:854-906`; name-step Back
      `:942`; `data-kind` on the phone step `:946`; "Continue" `.for-business` `:980`;
      "And what do you do?" step `:986-1011`; script tag `:13`.
- [ ] `portal/register.js`: header `:1-7`; business input `:233-235,248,258-260`;
      `KINDS`, `kindChoices`, `chosenKind`, `applyKind`, radio handlers `:262-301`;
      preset handling `:306-324`; errors `:407-409,423-426`; `tidyStep` `:441-443`;
      init `:490`; payload `:580,584`.
- [ ] `portal/register-address.js`: delete the file.
- [ ] `server.py`: `/register/business` alias `:1044-1047` (redirect it rather
      than 404, old links exist); `_handle_register_post` docstring `:15496-15511`,
      `kind` `:15539`, `business` field `:15542-15546`, field errors `:15549-15556`,
      `start_web_registration(... business, kind)` `:15604`,
      `registration_welcome_plan(kind)` `:15618`, log `:15665`.
- [ ] `server.py` `_open_whatsapp_account` `:15356-15391`: `registered_business`,
      `registered_kind`, `update_user_account_type`, `businessSummary`, facts.
- [ ] `server.py` signup routing `:15110-15123` (family skips email) and the
      email-asking path `:15124-15190,15238-15239`, per the stranger decision.
- [ ] `server.py:16018` household payload `accountKind`.

### 3c. Welcome template and signup concierge

- [ ] `registration_welcome.py`: business docstring `:8-13`; `assistyca_welcome1`
      default `:46-49`; tagline header `:56`; business greeting, closing, `{{2}}`
      line in English and Hebrew `:61-74`; `is_family` `:100-101`; `kind=` on
      `greeted_name`, `build_registration_welcome_message`,
      `registration_welcome_template_parameters`, `registration_welcome_plan`,
      `resolve_registration_welcome_template` `:112-239`; template defaults
      `:156-157`; `__all__` `:242-263`. Family plan stays:
      `assistyca_welcome_family` by name script, `assistyca_welcome_family_english_short` fallback.
      Decide whether `WHATSAPP_REGISTRATION_WELCOME_*` env overrides apply to family.
- [ ] `whatsapp_agent_chat.py`: `SIGNUP_PRODUCT_SUMMARY` / `FAMILY_PRODUCT_SUMMARY` /
      `product_summary_for` `:552-575`; registration-present check `:597-599`;
      `:631-632,667-669,679-690,727-736`; `build_registration_welcome_prompt(business,
      kind)` `:834-871`; `REGISTRATION_WELCOME_TEXT` fallback `:815-831`; `__all__` `:3184-3214`.
- [ ] Meta: retire `assistyca_welcome1` (en APPROVED, he PENDING) and the older
      `assistyca_welcome_family_1`, `assistyca_welcome_family_1_hebrew` once the
      new family pair is approved. Test-only `assistyca_welcome2`
      (`test_registration_welcome.py:34,125`).
- [ ] `docs/whatsapp-agent-chat.md:207-238,518-521` describe the business field.
- [ ] `scripts/mock_family_day.py:63,295,299,307-308` call signatures.

## 4. Rewrite the assistant's words for a family

Prompt text changes model behaviour; do this with the eval harness before and
after (`scripts/agent_conversation_eval.py`, baseline 4/8; `scripts/mock_family_day.py`).

### 4a. Main agent prompt, `agent_loop.py`

- [ ] `_ROLE` `:4157-4164` "help the owner run their business", "competitors",
      "for their business instead"; `:4168` "in the owner's terms"; `:4171` "their
      line of work"; `:4193` "plain business language"; `:4197` working hours
      (soften); `:4332-4333,608-610` "exports for an accountant" (soften).
- [ ] `_FACTS` `:4356-4361` whole paragraph, including the `what they do` key.
- [ ] `:4397-4398` "connecting a business to its mail and calendar"; `:4475-4476`
      WhatsApp rule "fitted to their line of work"; `_PHOTO_RULES` `:4499-4500`.
- [ ] Tool descriptions: `rememberFact` schema `:123`; `remember_fact` `:3720-3722`;
      `send_email` "a supplier" `:3454`; `show_findings` invoices-sent `:3971-3973`
      and `:2479`; `open_receipts` `:3281-3285`; `search_receipts` Render example
      `:3190-3201` (optional).
- [ ] `test_account_lists.py:206-216` asserts the `what they do` sentence.

### 4b. Portal agent prompt and shared pitch, `agent_proposals.py`

- [ ] `AGENT_TURN_INSTRUCTIONS` `:42-62` (still used at `server.py:11051`);
      `:850-851,857`; `_TURN_FACTS` `:953-967`; `:1182,1195`; `_TURN_PHOTO` `:1215`.
- [ ] `ASSISTANT_CAPABILITIES_PITCH` `:1256-1272`: "spend on software", "exports
      for the accountant", "a competitor's prices", "send the weekly report". Shared
      by the signup concierge and the loop, so high value.

### 4c. `chat_flow.py`

- [ ] Docstring `:1-33`; `describe_chat_flow(account_type)` `:61-116` and `_flow`
      `:152-165` drop the type; `FAMILY_ACCOUNT_RULES` `:170-193` first paragraph
      goes once 4a is done (keep the grown-up week and invite paragraphs);
      `_CONNECT_OPENING["business"]` `:260-266`; `chat_flow_rules` `:296-308`.

### 4d. Other prompts

- [ ] `answer_composer.py:52,54,173-205` "owner", "plain business language".
- [ ] `reply_judge.py:43` "WhatsApp business assistant".
- [ ] `mailbox_findings.py`: drop the `invoice_sent` / `payment_received` kinds and
      the unpaid-invoice detector: `:3-9,23-24,107-108,153-175,357,359-391,452-504,
      724,742-743,807,841`; `docs/mailbox-findings.md:9-11`.
- [ ] `inbox_watch.py:122` "Dana is waiting for your quote"; `account_types.py:125`
      and `docs/inbox-watch.md:3` "interviews".
- [ ] `thread_follow.py:3-4` "a quote asked of a supplier" (docstring).
- [ ] `insurance_manager.py:51-55` business-liability aliases (optional).
- [ ] `agent_turns.py:698` "No customer turns were recorded".
- [ ] `scripts/agent_conversation_eval.py:79,83,87` business scenario lines.
- [ ] `tests/test_standing_tasks.py:578` "Dana needs the quote by Friday."

## 5. Portal and public copy

- [ ] `portal/index.html:400,632-668` "About your business" menu and panel ("What
      do you do?", "Who are your customers?", air-conditioner example);
      `portal/app.js:61,62,12795`; `:1241-1251` "Business context"; `:1761`
      "Handyman team" placeholder.
- [ ] `portal/app.js:203` and `openai_pricing.py:638` "Client replies" use case.
- [ ] `portal/receipts.html:7,131,153`, `receipt_manager.py:458,485`,
      `docs/receipts.md:9,152` "for your accountant" (keep or soften; households
      have accountants).
- [ ] `portal/README.md:3,12,16,17,26`.
- [ ] `privacy.html`: nav `:443`; scope `:479-489`; `:505,510,515`; `:680-683`;
      section "Business Customer Responsibilities" `:726-740`. Also review
      "Children's Privacy" `:745-751`: the family product stores children's names,
      ages and birthdays. Keep the legal boilerplate at `:518,526,546,566,571,620,652-654`.
- [ ] `docs/agent-turns.md` "customer turn", `docs/free-trials.md` "client",
      `docs/whatsapp-agent-chat.md:15-22,124,317` client-number routing.
- [ ] Admin "Clients" tab and "client type Paying/Demo/QA" mean Assistyca's own
      account holders. Optional rename, not business copy.

## 6. Tests to delete or rewrite

- [ ] `test_account_types.py` (most of it), `test_web_registration.py`
      (`registration()` helper defaults to business `:41-51`; `:154-219,343-353,
      374-382,397-422,484-495,506-532,546-561,568-588,616-625`),
      `test_portal_static_pages.py:126-173,333-341,2604-2611`,
      `test_chat_flow.py:48-56,145-182,256-280`,
      `test_registration_welcome.py:18-59,97-106,124-154,171-213`,
      `test_household.py:279-283,417-421,756,844`, `test_whatsapp_signup.py:224,
      246,391` (and `:95-357` if strangers change), `test_family_week_nudges.py:236,
      450,715,800,893,1019`, `test_schedule_exceptions.py:238`,
      `test_standing_tasks.py:477`, `test_agent_public_records.py:7,110`,
      `test_agent_web_search.py:7,95`, `test_whatsapp_group_turns.py:212`.
- [ ] `.github/workflows/package-layout.yml:40-77` and
      `scripts/check_portal_changes.sh:40,45`: prune the deleted test modules.
- [ ] Before pushing, grep the diff for removed `def test` lines (see memory:
      an anchored slice once swallowed four unrelated tests).

## Keep: these say "business" for other reasons

- Meta's product names: "WhatsApp Business API / Account", `business_account_id`,
  `whatsapp_business_account` webhook object, business.facebook.com, "Official
  Business Account", "until the business is verified" (`whatsapp_agent_chat.py:160`
  is Assistyca's own Meta verification, which still gates groups).
- Lemon Squeezy "store", `customer_portal`, `isPayingCustomer`, `billing_customers`:
  Assistyca's own paying customers.
- `users.client_type` paying/demo/qa (`portal_db.py:55,816`): the billing type, not
  the account type.
- "quote" as a verb and `evidence_quote`, `quote_currency`; "lead" as a verb;
  "owner" meaning the mailbox or account owner in `inbox_watch`, `receipt_judge`,
  `mailbox_findings`, `WEEK_EDITOR_ROLES`, `recipientRef`.
- Receipt vocabulary (vendor, invoice, VAT, חשבונית) in `receipt_collector`,
  `file_tags`, mail search: households have vendors and invoices too.
- `LISTS/RECEIPTS/WEEK_HANDOFF_PREFIX`: page-link handoffs, nothing to do with
  business handoff.
- OAuth/HTTP "client", `getBoundingClientRect`, the admin "Clients" tab.
- `subscription_rhythm.py`: the user's own subscriptions found in receipts. Family.
- Receipts, insurance, lists, reminders, standing actions, web and news search,
  property records, mailbox findings (minus unpaid invoices), inbox watch, voice
  notes, group chat, family week: all stay.

## Rough size

| Area | Lines, roughly |
| --- | --- |
| Reply Assistant + Re-engagement + portal service | 5,700 code, 2,000 tests |
| Scheduled Web Monitor | 1,900 code, 1,100 tests |
| Feature catalogue + Lemon Squeezy activation | 1,700 code |
| About page + intake agent | 5,000 page, ~600 server, 465 tests |
| `clients/` + spec scripts + docs | ~10,000 lines, 6 MB |
| Account-type plumbing (server, db, portal, register) | a few hundred, spread wide |
| Prompt and copy rewrites | a few hundred lines, highest care |
