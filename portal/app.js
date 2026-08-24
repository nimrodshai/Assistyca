const LEGACY_STORAGE_PREFIX = "agents-for-all";
const STORAGE_PREFIX = "assistyca";
const LEGACY_WORKSPACE_NAMES = new Set([
  "agent guidance studio",
  "agents for all",
  "guidance studio",
  "lalo",
  "workspace",
]);
const AUTH_SESSION_KEY = `${STORAGE_PREFIX}.portal.auth-session`;
const AUTH_CHALLENGE_KEY = `${STORAGE_PREFIX}.portal.auth-challenge`;
const CLIENT_STATE_PREFIX = `${STORAGE_PREFIX}.client-state`;
const LAST_PRIMARY_TAB_KEY = `${STORAGE_PREFIX}.portal.last-primary-tab`;
const MONITOR_WATCH_DRAFT_PREFIX = `${STORAGE_PREFIX}.portal.monitor-watch-draft`;
migrateLegacyStorage();
const PORTAL_API_BASE = resolvePortalApiBase();
const OTP_TTL_MS = 10 * 60 * 1000;
const SETTINGS_PANEL_ANIMATION_MS = 320;
const FEATURE_CONFIG_AUTOSAVE_DELAY_MS = 450;
const ACCOUNT_PROFILE_AUTOSAVE_DELAY_MS = 500;
const BILLING_ENTRY_REFRESH_COOLDOWN_MS = 20 * 1000;
const WHATSAPP_EXTERNAL_OUTBOUND_TEXT = "You replied here - but the WhatsApp API doesn't let us read the content";
const WHATSAPP_CONNECTION_POLL_MS = 15 * 1000;
const SCHEDULED_ACTIONS_POLL_MS = 5 * 1000;
const WHATSAPP_APPROVALS_POLL_MS = 5 * 1000;
const SCHEDULED_ACTIONS_REFRESH_ERROR_THRESHOLD = 3;
const WHATSAPP_SAMPLE_CONFIRMATION_POLL_MS = 2 * 1000;
const WHATSAPP_SAMPLE_CONFIRMATION_TIMEOUT_MS = 30 * 1000;
const OPPORTUNITIES_OWNER_EMAIL = "nimrod.shai@gmail.com";
const ADMIN_CLIENT_TYPES = [
  { value: "paying", label: "Paying", className: "is-client-type-paying" },
  { value: "demo", label: "Demo", className: "is-client-type-demo" },
  { value: "qa", label: "QA", className: "is-client-type-qa" },
];
const DEFAULT_ADMIN_CLIENT_TYPE = "demo";
const VALID_TABS = new Set(["features", "opportunities", "clients", "personal-details", "preview", "simulator", "billing", "pricing", "settings"]);
const VALID_FEATURE_STUDIO_VIEWS = new Set(["overview", "activation", "editor", "history"]);
const TAB_ALIASES = new Map([
  ["guidance", "features"],
  ["tools", "features"],
  ["leads", "opportunities"],
  ["pipeline", "opportunities"],
  ["users", "clients"],
  ["accounts", "clients"],
  ["customers", "clients"],
  ["personal", "personal-details"],
  ["profile", "personal-details"],
  ["details", "personal-details"],
]);
const TAB_LABELS = {
  features: "Agent",
  opportunities: "Opportunities",
  clients: "Clients",
  "personal-details": "About your business",
  preview: "Preview",
  simulator: "Simulator",
  billing: "Billing",
  pricing: "Pricing",
  settings: "Settings",
};
const VALID_SETTINGS_MODES = new Set(["account", "preferences", "users"]);
const SETTINGS_MODE_CONTENT = {
  account: {
    title: "Account and preferences",
    description: "Update login details and account preferences.",
  },
  preferences: {
    title: "Account and preferences",
    description: "Update login details and account preferences.",
  },
  users: {
    title: "Clients",
    description: "",
  },
};
const LOCAL_APPROVAL_URL = "../approval.html";
const LOCAL_PORTAL_API_BASE = "http://127.0.0.1:8000";
const META_WHATSAPP_ACCOUNTS_URL = "https://business.facebook.com/latest/settings/whatsapp_account";
const SAVED_ACCESS_TOKEN_FIELD_VALUE = "................";
const DEFAULT_BILLING_MINIMUM = 50.0;
const DEFAULT_FEATURE_LAUNCH_URL = "";
const MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier";
const REENGAGEMENT_FEATURE_ID = "whatsapp-business-follow-up-outreach-writer";
const WHATSAPP_REPLY_ASSISTANT_FEATURE_ID = "whatsapp-business-reply-suggestion-assistant";
const LEGACY_DEFAULT_FEATURE_NAMES = new Set([
  "WhatsApp Business Reply Suggestion Assistant",
  "WhatsApp Reply Approval Bot",
]);
const LEGACY_DEFAULT_FEATURE_MODES = new Set([
  "suggestion_only",
  "Approval bot",
]);
const LEGACY_DEFAULT_FEATURE_DESCRIPTION_PATTERNS = [
  /drafts\s+suggested\s+whatsapp\s+replies/i,
  /surfaces?\s+approvals?\s+inside\s+whatsapp/i,
  /reusable\s+approval\s+page/i,
];
const BILLING_MODEL_COLORS = ["#17958a", "#2f7de1", "#d49a3a", "#8c96a3"];
const DEFAULT_FEATURE_PRICING = {
  minimumMonthlyCharge: DEFAULT_BILLING_MINIMUM,
};
const PHONE_PLACEHOLDER_BY_COUNTRY = {
  IL: "972559195101",
  US: "15551234567",
};
const FEATURE_ACTIVATION_REQUIRED_KEYS = [
  "business_account_id",
  "phone_number_id",
  "access_token",
  "owner_wa_id",
];
const FEATURE_ACTIVATION_STEPS = [
  "WABA ID",
  "Phone number ID",
  "Access token",
  "Approval phone number",
];
const DEFAULT_FEATURE_WHATSAPP = {
  business_account_id: "",
  phone_number_id: "",
  access_token: "",
  access_token_configured: false,
  workspace_access_token_configured: false,
  backend_access_token_configured: false,
  owner_wa_id: "",
  connection_status: "not_connected",
  display_phone_number: "",
  verified_name: "",
  connected_at: "",
  last_tested_at: "",
  configured: false,
  live_send_enabled: false,
  webhook_url: "",
  metadata: {},
};
const DEFAULT_MONITOR_SETTINGS = {
  model: "gpt-5.5",
  watchItems: [],
  manualOnly: true,
  runMode: "manual",
  intervalDays: 7,
  intervalMinutes: 0,
  scheduleTimeLocal: "",
  scheduleTimezone: "",
  deliveryChannel: "email",
  telegramChatId: "",
};
const DEFAULT_REENGAGEMENT_SETTINGS = {
  model: "gpt-5.5",
  intervalDays: 7,
  scheduleTimeLocal: "09:00",
  scheduleTimezone: "",
  inactivityValue: 6,
  inactivityUnit: "months",
  maxContextMessages: 100,
  deliveryChannels: [],
  telegramChatId: "",
};
const MANUAL_PRICING_SNAPSHOT = {
  source: "manual",
  sourceUrl: "https://developers.openai.com/api/docs/pricing",
  fetchedAt: "2026-07-12T00:00:00Z",
  cards: [
    {
      band: "Lean",
      modelId: "gpt-5.4-nano",
      modelName: "GPT-5.4 Nano",
      description: "For lightweight automations and high-volume tasks where efficiency matters most.",
      useCases: ["Short prompts", "Extraction", "Classification"],
      ours: {
        inputUsdPer1MTokens: 0.3,
        outputUsdPer1MTokens: 1.875,
      },
      totalOurUsdPer1MTokens: 2.175,
    },
    {
      band: "Efficient",
      modelId: "gpt-5.4-mini",
      modelName: "GPT-5.4 Mini",
      description: "For everyday assistants that need stronger quality than nano without paying for the full flagship tier.",
      useCases: ["General replies", "Summaries", "Routine drafting"],
      ours: {
        inputUsdPer1MTokens: 1.125,
        outputUsdPer1MTokens: 6.75,
      },
      totalOurUsdPer1MTokens: 7.875,
    },
    {
      band: "Balanced",
      modelId: "gpt-5.4",
      modelName: "GPT-5.4",
      description: "For most day-to-day assistants and workflows that need a strong mix of cost and capability.",
      useCases: ["Client replies", "Workflow agents", "Daily operations"],
      featured: true,
      highlightLabel: "Most popular",
      ours: {
        inputUsdPer1MTokens: 3.75,
        outputUsdPer1MTokens: 22.5,
      },
      totalOurUsdPer1MTokens: 26.25,
    },
    {
      band: "Premium",
      modelId: "gpt-5.5",
      modelName: "GPT-5.5",
      description: "For the most demanding tasks, deeper reasoning, and higher-stakes outputs.",
      useCases: ["Deep reasoning", "Long context", "Critical drafting"],
      ours: {
        inputUsdPer1MTokens: 7.5,
        outputUsdPer1MTokens: 45,
      },
      totalOurUsdPer1MTokens: 52.5,
    },
  ],
};
const MONITOR_INTERVAL_DAYS_MIN = 1;
const MONITOR_INTERVAL_DAYS_MAX = 365;
const REENGAGEMENT_INACTIVITY_VALUE_MIN = 1;
const REENGAGEMENT_INACTIVITY_VALUE_MAX = 10000;
const DEFAULT_MONITOR_SCHEDULE_TIME = "09:00";
const DEFAULT_TOOL_MODEL = DEFAULT_MONITOR_SETTINGS.model;
const DEFAULT_FEATURE_SETTINGS = {
  model: DEFAULT_TOOL_MODEL,
};
const DEFAULT_WHATSAPP_TOOL_SETTINGS = {
  ...DEFAULT_FEATURE_SETTINGS,
  deliveryChannels: [],
  telegramChatId: "",
};
const WHATSAPP_TOOL_PLATFORM_OPTIONS = [
  {
    id: "whatsapp",
    label: "WhatsApp",
    shortLabel: "WA",
    caption: "Connected workspace number",
  },
  {
    id: "telegram",
    label: "Telegram",
    shortLabel: "TG",
    caption: "Bot chat delivery",
  },
  {
    id: "portal",
    label: "This chat",
    shortLabel: "CHAT",
    caption: "Review drafts in Assistyca",
  },
];
const DEFAULT_TOOL_MODEL_OPTIONS = MANUAL_PRICING_SNAPSHOT.cards.map((card) => ({
  id: String(card?.modelId || "").trim(),
  name: String(card?.modelName || card?.modelId || "Model").trim(),
  band: String(card?.band || "").trim(),
  summary: String(card?.description || "").trim(),
})).filter((option) => option.id);

const DEFAULT_PROMPT = {
  toneGuidance: "Warm, direct, and practical. Keep replies human, short, and grounded.",
  replyRules:
    "Acknowledge the request first. Ask one clarifying question only when needed. Never guess prices or availability.",
  businessNotes:
    "Service area, hours, pricing hints, and any details the agent should know before replying.",
  escalationGuidance:
    "Hand off when the customer is upset, the answer needs a human decision, or the request is urgent.",
  exampleReplies: "",
  responseStyle: "balanced",
  scenario: "approval",
};

const DEFAULT_SETTINGS = {
  displayName: "",
  workspaceName: "Assistyca",
  timezone: defaultTimeZone(),
};
const DEFAULT_ACCOUNT_PROFILE = {
  businessSummary: "",
  customerNotes: "",
  assistantGuidance: "",
};

const DEFAULT_FEATURES = [
  {
    id: "whatsapp-business-reply-suggestion-assistant",
    name: "WhatsApp Reply Assistant",
    description: "Turns incoming WhatsApp questions into quick, human-reviewed replies that help you quote faster and book more work.",
    channel: "WhatsApp",
    mode: "Human-reviewed",
    status: "non-active",
    activated: false,
    setupComplete: false,
    launchUrl: DEFAULT_FEATURE_LAUNCH_URL,
    pricing: { ...DEFAULT_FEATURE_PRICING },
    prompt: { ...DEFAULT_PROMPT },
    requirements: {
      requiresWhatsAppConnection: true,
    },
    billing: {
      required: true,
      provider: "lemon_squeezy",
      storeId: "",
      productId: "",
      variantId: "",
    },
    assignment: {},
    paymentStatus: null,
    metadata: {},
    settings: { ...DEFAULT_FEATURE_SETTINGS },
    savedSettings: { ...DEFAULT_FEATURE_SETTINGS },
    whatsapp: { ...DEFAULT_FEATURE_WHATSAPP },
    savedWhatsApp: { ...DEFAULT_FEATURE_WHATSAPP },
  },
  {
    id: REENGAGEMENT_FEATURE_ID,
    name: "WhatsApp Re-engagement Assistant",
    description: "Helps you reconnect with past customers using ready-to-send WhatsApp follow-ups, so more quiet conversations turn back into active work.",
    channel: "WhatsApp",
    mode: "Weekly follow-up",
    status: "non-active",
    activated: false,
    setupComplete: false,
    launchUrl: DEFAULT_FEATURE_LAUNCH_URL,
    pricing: { ...DEFAULT_FEATURE_PRICING },
    prompt: {
      ...DEFAULT_PROMPT,
      replyRules:
        "Use the saved conversation to write a warm, low-pressure re-engagement message that is specific, concise, and easy to copy into WhatsApp.",
      businessNotes:
        "Reference real context from the previous conversation when it helps. Never invent discounts, availability, or promises.",
      scenario: "reengagement",
    },
    requirements: {
      requiresWhatsAppConnection: true,
    },
    billing: {
      required: true,
      provider: "lemon_squeezy",
      storeId: "",
      productId: "",
      variantId: "",
    },
    assignment: {},
    paymentStatus: null,
    metadata: {},
    settings: { ...DEFAULT_REENGAGEMENT_SETTINGS },
    savedSettings: { ...DEFAULT_REENGAGEMENT_SETTINGS },
    whatsapp: { ...DEFAULT_FEATURE_WHATSAPP },
    savedWhatsApp: { ...DEFAULT_FEATURE_WHATSAPP },
  },
  {
    id: MONITOR_FEATURE_ID,
    name: "Scheduled Web Monitor",
    description: "Searches the web on a daily, weekly, or monthly schedule and sends source-backed alerts about the events, dates, and opportunities you care about.",
    channel: "Alerts",
    mode: "Scheduled search",
    status: "non-active",
    activated: false,
    setupComplete: false,
    launchUrl: DEFAULT_FEATURE_LAUNCH_URL,
    pricing: { ...DEFAULT_FEATURE_PRICING },
    prompt: {
      ...DEFAULT_PROMPT,
      toneGuidance: "Clear, useful, and concise. Make alerts easy to scan and act on.",
      replyRules: "Only alert when there is a real match with a credible public source. Prefer source-backed specifics over vague mentions.",
      businessNotes: "Region, niche, timing rules, or context that helps the monitor decide what matters most.",
      escalationGuidance: "Mark items urgent when a deadline is close, an event is approaching soon, or the result clearly needs quick human follow-up.",
      exampleReplies: "Good: \"The Israeli Criminal Defense Conference published its 2026 agenda. Registration closes Aug 12. Source: https://example.com\"\nBad: \"There might be something interesting online soon.\"",
      scenario: "monitor",
    },
    requirements: {
      requiresScheduledMonitorConfig: true,
    },
    billing: {
      required: true,
      provider: "lemon_squeezy",
      storeId: "",
      productId: "",
      variantId: "",
    },
    assignment: {},
    paymentStatus: null,
    metadata: {
      setupSurface: "editor",
    },
    settings: { ...DEFAULT_MONITOR_SETTINGS },
    savedSettings: { ...DEFAULT_MONITOR_SETTINGS },
    whatsapp: { ...DEFAULT_FEATURE_WHATSAPP },
    savedWhatsApp: { ...DEFAULT_FEATURE_WHATSAPP },
  },
];

const DEFAULT_SIMULATOR = {
  composer: {
    scenario: "approval",
    senderName: "Maya Cohen",
    senderWaId: "15551230000",
    latestMessage: "Hi, can you quote a same-day leak repair at 14 King St? We’re comparing options now.",
    threadContext:
      "Need a quote for a leak repair at 14 King St.\nWe need the earliest slot and a rough price.\nCustomer is comparing options now.",
    approvalUrl: LOCAL_APPROVAL_URL,
  },
  approvals: [],
  selectedApprovalId: "",
};

const AGENT_INITIAL_MESSAGE = "";
const AGENT_MAX_MESSAGES = 40;
const AGENT_ADD_TOOL_OPTIONS = [
  {
    id: "email",
    label: "Email",
    detail: "Connect your email account",
    icon: "email",
    platformId: "email",
  },
  {
    id: "calendar",
    label: "Calendar",
    detail: "Connect your calendar",
    icon: "calendar",
    platformId: "calendar",
  },
  {
    id: "telegram",
    label: "Telegram",
    detail: "Connect Telegram",
    icon: "telegram",
    platformId: "telegram",
  },
  {
    id: "slack",
    label: "Slack",
    detail: "Connect Slack",
    icon: "slack",
    platformId: "slack",
  },
  {
    id: "custom",
    label: "Another app",
    detail: "Connect an app not listed here",
    icon: "custom",
    prompt: "Help me connect another app.",
  },
];
const PLATFORM_CONNECTION_OPTIONS = AGENT_ADD_TOOL_OPTIONS
  .filter((option) => option.platformId)
  .map((option) => ({
    id: option.platformId,
    label: option.label,
    detail: option.detail,
    icon: option.icon,
    authType: option.id === "telegram" ? "bot_token" : "api_token",
    credentialLabel: option.id === "slack" ? "Slack bot token" : `${option.label} token`,
  }));
const AGENT_BLUEPRINTS = {
  emailDigest: {
    type: "email-digest",
    title: "Daily email digest",
    summary:
      "Create a daily assistant that reads new email, extracts the important items, and sends a concise digest on your schedule.",
    response:
      "I can set that up. I would add a Gmail reading skill, a scheduler, an Email Digest helper, and a delivery helper. Before it starts, I need approval plus your preferred delivery channel and time.",
    relatedFeatureId: MONITOR_FEATURE_ID,
    primaryActionLabel: "Create email digest helpers",
    setupActionLabel: "Review scheduler setup",
    missingCredential: "Gmail access",
    skills: [
      {
        label: "Gmail reader",
        detail: "Connects to the mailbox with read-only access for summary work.",
      },
      {
        label: "Digest writer",
        detail: "Groups urgent, customer, billing, and follow-up messages into a short brief.",
      },
      {
        label: "Daily scheduler",
        detail: "Runs at the chosen local time and keeps timezone rules explicit.",
      },
      {
        label: "Notification delivery",
        detail: "Sends the result by email, Telegram, WhatsApp, or portal-only fallback.",
      },
    ],
    helpers: [
      {
        name: "Email Digest Agent",
        purpose: "Read new messages and produce the daily summary.",
      },
      {
        name: "Delivery Agent",
        purpose: "Send or store the result through the approved channel.",
      },
    ],
    questions: [
      "Which mailbox should I summarize?",
      "What time should the digest run?",
      "How would you like to be notified with the results?",
    ],
    alternatives: ["Email", "Telegram", "WhatsApp after setup", "Portal inbox"],
  },
  webMonitor: {
    type: "web-monitor",
    title: "Scheduled web monitor",
    summary:
      "Create a recurring monitor that searches the web for deadlines, events, mentions, and opportunities, then sends source-backed alerts.",
    response:
      "I can turn that into a scheduled monitoring workflow. The existing web monitor skill can do the search work, and I would add a helper to decide what is worth alerting you about.",
    relatedFeatureId: MONITOR_FEATURE_ID,
    primaryActionLabel: "Create monitor helper",
    setupActionLabel: "Open monitor setup",
    missingCredential: "",
    skills: [
      {
        label: "Web search monitor",
        detail: "Checks the public web on a recurring schedule.",
      },
      {
        label: "Source-backed summarizer",
        detail: "Filters weak matches and includes the important source details.",
      },
      {
        label: "Alert delivery",
        detail: "Sends only meaningful matches through the approved channel.",
      },
    ],
    helpers: [
      {
        name: "Monitoring Agent",
        purpose: "Run the search, compare results to the watchlist, and prepare alerts.",
      },
    ],
    questions: [
      "What exact topics, dates, or opportunities should I watch?",
      "How often should I check?",
      "Where should alerts be delivered?",
    ],
    alternatives: ["Email", "Telegram", "WhatsApp after setup", "Portal inbox"],
  },
  whatsappReplies: {
    type: "whatsapp-replies",
    title: "WhatsApp reply assistant",
    summary:
      "Use WhatsApp skills to draft replies for incoming leads while keeping every send under human control.",
    response:
      "I can use the WhatsApp reply skill for this. If the WhatsApp Business API is not connected yet, I will guide you through the required IDs and access token, then keep manual approval in place.",
    relatedFeatureId: WHATSAPP_REPLY_ASSISTANT_FEATURE_ID,
    primaryActionLabel: "Create WhatsApp helper",
    setupActionLabel: "Open WhatsApp setup",
    missingCredential: "WhatsApp Business API access token",
    skills: [
      {
        label: "WhatsApp listener",
        detail: "Receives new customer messages from the connected workspace number.",
      },
      {
        label: "Reply drafter",
        detail: "Writes short, grounded responses using your business context.",
      },
      {
        label: "Human approval",
        detail: "Sends drafts for review before anything goes to the customer.",
      },
    ],
    helpers: [
      {
        name: "WhatsApp Reply Agent",
        purpose: "Watch inbound leads and prepare approval-ready reply drafts.",
      },
    ],
    questions: [
      "Which WhatsApp number should be connected?",
      "Who approves reply drafts?",
      "What should the assistant never promise without you?",
    ],
    alternatives: ["Manual copy/paste", "Telegram alerts", "Email alerts"],
  },
  scheduledMessage: {
    type: "scheduled-message",
    title: "Scheduled message",
    summary:
      "Schedule one approved message for an exact local time, then send it through the chosen delivery channel.",
    response:
      "I can turn that into a scheduled action: an exact-time trigger plus a send-message action. I will ask only for any missing time, channel, recipient, or message text before scheduling it.",
    relatedFeatureId: "",
    primaryActionLabel: "Schedule message",
    setupActionLabel: "Open delivery setup",
    missingCredential: "",
    skills: [
      {
        label: "Exact-time scheduler",
        detail: "Stores the approved send time as a durable one-shot action.",
      },
      {
        label: "Message delivery",
        detail: "Sends the approved text through the selected channel when the action is due.",
      },
      {
        label: "Delivery tracking",
        detail: "Records provider message IDs and failures for follow-up.",
      },
    ],
    helpers: [
      {
        name: "Scheduled Action Agent",
        purpose: "Track the approved send time and dispatch the message when it is due.",
      },
    ],
    questions: [],
    alternatives: ["WhatsApp", "Email", "Telegram", "Portal inbox"],
  },
  reengagement: {
    type: "reengagement",
    title: "Customer re-engagement",
    summary:
      "Create a recurring helper that finds quiet WhatsApp conversations and drafts warm follow-ups.",
    response:
      "I can help with past-customer follow-up. I would use the saved WhatsApp history, run on a schedule, and generate reviewable follow-up drafts without sending automatically.",
    relatedFeatureId: REENGAGEMENT_FEATURE_ID,
    primaryActionLabel: "Create follow-up helper",
    setupActionLabel: "Open follow-up setup",
    missingCredential: "WhatsApp history or connected WhatsApp",
    skills: [
      {
        label: "Conversation history",
        detail: "Reads saved WhatsApp exports or connected message history.",
      },
      {
        label: "Dormancy detector",
        detail: "Finds conversations that have been quiet longer than your rule.",
      },
      {
        label: "Follow-up writer",
        detail: "Drafts low-pressure messages for review.",
      },
    ],
    helpers: [
      {
        name: "Re-engagement Agent",
        purpose: "Find quiet conversations and prepare follow-up drafts.",
      },
    ],
    questions: [
      "How long should a conversation be quiet before follow-up?",
      "How often should the helper check?",
      "Where should drafts be delivered?",
    ],
    alternatives: ["WhatsApp approval", "Telegram alerts", "Email alerts"],
  },
  custom: {
    type: "custom",
    title: "Custom task agent",
    summary:
      "Create a custom workflow from your request, then ask any missing questions before installation.",
    response:
      "I can shape that into a custom workflow. I will start with a planning helper, then identify the exact skills, external services, credentials, and notification path before anything runs.",
    relatedFeatureId: "",
    primaryActionLabel: "Create planning helper",
    setupActionLabel: "Review available skills",
    missingCredential: "",
    skills: [
      {
        label: "Task planner",
        detail: "Breaks the request into clear steps, dependencies, and approval points.",
      },
      {
        label: "Skill matcher",
        detail: "Checks available portal skills and identifies any missing integrations.",
      },
      {
        label: "Question asker",
        detail: "Collects only the decisions needed to move forward safely.",
      },
    ],
    helpers: [
      {
        name: "Planning Agent",
        purpose: "Map the task and recommend the right skills or helper agents.",
      },
    ],
    questions: [
      "What result should I produce?",
      "How often should this happen?",
      "How should I notify you when it is done?",
    ],
    alternatives: ["Portal inbox", "Email", "Telegram", "WhatsApp after setup"],
  },
};

const AGENT_PROPOSAL_FIELD_SCHEMAS = {
  "email-digest": [
    {
      key: "mailbox",
      question: "Which mailbox should I summarize?",
      actions: ["Gmail", "Outlook"],
    },
    {
      key: "schedule",
      question: "What time should I send the summary?",
      actions: ["8:00 AM", "9:00 AM"],
    },
    {
      key: "deliveryChannel",
      question: "Where should I send it?",
      actions: ["Email", "Telegram", "WhatsApp"],
    },
  ],
  "web-monitor": [
    {
      key: "watchQuery",
      question: "What should I watch for?",
    },
    {
      key: "location",
      question: "What location should I search in for this?",
      requiredWhen: "web-monitor-location-sensitive",
    },
    {
      key: "timeWindow",
      question: "What date range should I focus on?",
      required: false,
    },
    {
      key: "frequency",
      question: "How often should I check?",
      actions: ["Daily", "Weekly", "Monthly"],
    },
    {
      key: "deliveryChannel",
      question: "Where should I send alerts?",
      actions: ["Email", "Telegram", "WhatsApp"],
    },
  ],
  "whatsapp-replies": [
    {
      key: "whatsappNumber",
      question: "Which WhatsApp number should I use?",
    },
    {
      key: "approver",
      question: "Who should approve reply drafts?",
    },
    {
      key: "guardrails",
      question: "What should I never promise without you?",
    },
    {
      key: "deliveryChannel",
      question: "Where should I bring reply drafts for your review?",
      actions: ["This chat", "WhatsApp", "Telegram"],
    },
  ],
  reengagement: [
    {
      key: "inactivityPeriod",
      question: "How long should a conversation be quiet before I suggest a follow-up?",
      actions: ["1 month", "3 months", "6 months"],
    },
    {
      key: "frequency",
      question: "How often should I check?",
      actions: ["Daily", "Weekly"],
    },
    {
      key: "deliveryChannel",
      question: "Where should I send drafts for review?",
      actions: ["WhatsApp", "Email", "Telegram"],
    },
  ],
  custom: [
    {
      key: "result",
      question: "What should the finished result look like?",
    },
    {
      key: "frequency",
      question: "How often should this happen?",
    },
    {
      key: "deliveryChannel",
      question: "How should I let you know when it is done?",
      actions: ["Portal inbox", "Email", "Telegram", "WhatsApp"],
    },
  ],
};
const AGENT_CALENDAR_FIELD_SCHEMA = [
  {
    key: "calendar",
    question: "Which calendar should I use?",
    actions: ["Google Calendar", "Outlook Calendar"],
  },
];
const AGENT_PROPOSAL_FIELD_ALIASES = {
  channel: "deliveryChannel",
  delivery: "deliveryChannel",
  delivery_channel: "deliveryChannel",
  deliverychannel: "deliveryChannel",
  notify: "deliveryChannel",
  notification: "deliveryChannel",
  notification_channel: "deliveryChannel",
  notificationchannel: "deliveryChannel",
  topic: "watchQuery",
  query: "watchQuery",
  watch: "watchQuery",
  watch_query: "watchQuery",
  watchquery: "watchQuery",
  subject: "watchQuery",
  search: "watchQuery",
  search_query: "watchQuery",
  searchquery: "watchQuery",
  cadence: "frequency",
  interval: "frequency",
  schedule: "schedule",
  time: "schedule",
  mailbox: "mailbox",
  inbox: "mailbox",
  location: "location",
  area: "location",
  date_range: "timeWindow",
  daterange: "timeWindow",
  time_window: "timeWindow",
  timewindow: "timeWindow",
  period: "timeWindow",
  number: "whatsappNumber",
  whatsapp_number: "whatsappNumber",
  whatsappnumber: "whatsappNumber",
  approver: "approver",
  reviewer: "approver",
  guardrails: "guardrails",
  restrictions: "guardrails",
  inactivity: "inactivityPeriod",
  inactivity_period: "inactivityPeriod",
  inactivityperiod: "inactivityPeriod",
  quiet_period: "inactivityPeriod",
  quietperiod: "inactivityPeriod",
  result: "result",
  output: "result",
  calendar: "calendar",
};

function normalizeTab(tab) {
  return TAB_ALIASES.get(String(tab || "").trim()) || String(tab || "").trim();
}

function normalizeBrandName(value) {
  return String(value || "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .replace(/[\s_-]+/g, " ");
}

function isLegacyWorkspaceName(value) {
  return LEGACY_WORKSPACE_NAMES.has(normalizeBrandName(value));
}

function isLegacyDefaultFeatureDescription(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }

  return LEGACY_DEFAULT_FEATURE_DESCRIPTION_PATTERNS.some((pattern) => pattern.test(text));
}

const SCENARIOS = {
  approval: {
    label: "Hot lead",
    sender: "Maya Cohen",
    meta: "After-hours quote request",
    user: "Hi, can you quote a same-day leak repair at 14 King St? We’re comparing options now.",
    ask: "Absolutely. Send me a photo and your address, and I’ll confirm pricing and the earliest slot right away.",
    insight: "Keeps fresh leads from going cold while you’re busy on another job.",
    exactReply: true,
  },
  availability: {
    label: "Booking request",
    sender: "Maya Cohen",
    meta: "New inquiry",
    user: "Hi, are you available tomorrow afternoon?",
    ask: "Let me check what works best. What address should I look at?",
    insight: "Shows customers you’re responsive before they move on.",
  },
  pricing: {
    label: "Quote request",
    sender: "Oren Levy",
    meta: "Price comparison",
    user: "How much would it cost to replace the lock?",
    ask: "I can give you a proper price once I know the door type and lock model.",
    insight: "Gets the details you need before quoting blind.",
  },
  reschedule: {
    label: "Schedule change",
    sender: "Dana Klein",
    meta: "Existing customer",
    user: "Can we move the appointment by one day?",
    ask: "Yes, I can check that. What time window would work for you?",
    insight: "Keeps repeat business moving without a phone call.",
  },
  urgent: {
    label: "Escalation",
    sender: "Customer",
    meta: "Needs a human",
    user: "The door is stuck and I need help right now.",
    ask: "I’m flagging this for immediate human follow-up so someone can help you as fast as possible.",
    insight: "Makes urgent jobs impossible to miss.",
  },
  reengagement: {
    label: "Dormant client",
    sender: "Maya Cohen",
    meta: "6+ months since the last thread",
    user: "Thanks, I’ll think about it and get back to you.",
    messages: [
      {
        direction: "incoming",
        text: "Thanks, I’ll think about it and get back to you.",
      },
      {
        direction: "outgoing",
        text: "👍",
      },
    ],
    ask: "Hi Maya, just checking in in case you still need help with the leak repair we discussed. If you want to pick it back up, send me a message and I’ll take it from there.",
    insight: "Keeps old conversations from going cold without sounding pushy.",
    exactReply: true,
  },
  monitor: {
    label: "Scheduled alert",
    sender: "Scheduled monitor",
    meta: "Weekly web search",
    user: "Watch for criminal defense law conferences, holiday reminders, and any registration deadlines worth sharing.",
    ask: "The Israeli Criminal Defense Conference opened registration for Sept 18-19, 2026. Early-bird pricing ends Aug 12. Source: https://example.com",
    insight: "Turns vague watchlists into source-backed alerts on a schedule.",
  },
};

const SIMULATOR_PRESETS = {
  approval: {
    senderName: SCENARIOS.approval.sender,
    senderWaId: "15551230000",
    latestMessage: SCENARIOS.approval.user,
    threadContext:
      "Can you fit me in later today?\nI can check my calendar now.\nIf not, tomorrow afternoon works too.",
    approvalUrl: LOCAL_APPROVAL_URL,
  },
  availability: {
    senderName: SCENARIOS.availability.sender,
    senderWaId: "15551230001",
    latestMessage: SCENARIOS.availability.user,
    threadContext:
      "Hi, are you available tomorrow afternoon?\nLet me check the schedule.\nGreat, thanks.",
    approvalUrl: LOCAL_APPROVAL_URL,
  },
  pricing: {
    senderName: SCENARIOS.pricing.sender,
    senderWaId: "15551230002",
    latestMessage: SCENARIOS.pricing.user,
    threadContext:
      "How much would it cost to replace the lock?\nI can quote it once I know the lock type.\nGot it, I’ll send a photo.",
    approvalUrl: LOCAL_APPROVAL_URL,
  },
  reschedule: {
    senderName: SCENARIOS.reschedule.sender,
    senderWaId: "15551230003",
    latestMessage: SCENARIOS.reschedule.user,
    threadContext:
      "Can we move the appointment by one day?\nYes, I can check what’s open.\nPerfect.",
    approvalUrl: LOCAL_APPROVAL_URL,
  },
  urgent: {
    senderName: SCENARIOS.urgent.sender,
    senderWaId: "15551230004",
    latestMessage: SCENARIOS.urgent.user,
    threadContext:
      "The door is stuck and I need help right now.\nI’m escalating this to a person immediately.\nThanks, please hurry.",
    approvalUrl: LOCAL_APPROVAL_URL,
  },
};

const state = {
  activeTab: "features",
  settingsMode: "account",
  settingsOpen: false,
  adminUsers: [],
  adminFeatures: [],
  adminUsersLoading: false,
  adminUsersNeedsRender: false,
  adminUsersError: "",
  adminAddUserBusy: false,
  adminEditUserBusy: false,
  adminSaveBusyByEmail: {},
  adminSaveQueuedByEmail: {},
  adminStatusBusyByEmail: {},
  adminTypeBusyByEmail: {},
  adminDeleteBusyByEmail: {},
  adminUserDrafts: {},
  adminView: "list",
  adminSelectedUserEmail: "",
  adminUserSearch: "",
  adminFeatureSearch: "",
  adminFeaturePickerOpen: false,
  adminNewUserEmail: "",
  adminNewUserDisplayName: "",
  adminEditUserEmail: "",
  adminEditUserDisplayName: "",
  opportunities: [],
  opportunitiesLoading: false,
  opportunitiesError: "",
  opportunitiesLoadedAt: 0,
  requestCountryCode: "",
  authAlertOpen: false,
  menuOpen: false,
  selectedFeatureId: null,
  featureStudioView: "overview",
  featureActivationNotice: "",
  featureActivationFieldErrors: {},
  whatsappHistory: null,
  whatsappHistoryLoading: false,
  whatsappHistoryImportBusy: false,
  whatsappHistoryDeleteBusy: false,
  whatsappHistoryDeleteTargetId: "",
  whatsappHistoryImportStatus: "",
  whatsappHistoryImportError: "",
  whatsappHistoryError: "",
  whatsappHistorySelectedConversationId: "",
  whatsappHistoryLoadedAt: 0,
  whatsappHistoryEmail: "",
  scheduledActions: [],
  scheduledActionsLoading: false,
  scheduledActionsError: "",
  scheduledActionsFailureCount: 0,
  scheduledActionsLastError: "",
  scheduledActionsLastErrorAt: 0,
  scheduledActionsLoadedAt: 0,
  selectedScheduledActionId: "",
  agentHistoryExpanded: false,
  agentAddToolMenuOpen: false,
  agentAddToolMenuClosing: false,
  platformConnections: [],
  paymentStatus: null,
  selectedSimulatorId: null,
  billingReport: null,
  billingLoading: false,
  billingError: "",
  billingHelpOpen: false,
  pricingSnapshot: null,
  pricingLoading: false,
  pricingError: "",
  monitorWatchItemDraft: "",
  reengagementDemoResult: null,
  reengagementDemoDrafts: {},
  lastPrimaryTab: normalizeTab(loadJson(LAST_PRIMARY_TAB_KEY, "features")) || "features",
};

let settingsPanelOpenFrame = null;
let settingsPanelCloseTimer = null;
let authAlertOpenFrame = null;
let authAlertCloseTimer = null;
let authAlertReturnFocus = null;
let authAlertPrimaryAction = null;
let authAlertSecondaryAction = null;
let authAlertFocusTarget = "primary";
let authAlertCloseOnPrimary = true;
let authAlertCloseOnSecondary = true;
let authAlertBackdropDismiss = true;
let authAlertEscapeDismiss = true;
let billingHelpOpenFrame = null;
let billingHelpCloseTimer = null;
let billingHelpReturnFocus = null;
let billingRefreshPromise = null;
let billingLastRefreshCompletedAt = 0;
let pricingRefreshPromise = null;
let pricingLastRefreshCompletedAt = 0;
let agentTurnBusy = false;
let agentTurnProgressText = "Thinking";
let featureActivationBusy = false;
let featureActivationTransitionBusy = false;
let featureActivationTransitionTargetId = "";
let featureActivationTransitionAction = "";
let monitorManualRunBusy = false;
let monitorManualRunTargetId = "";
let monitorManualRunRequestId = "";
let monitorManualRunCancelling = false;
let monitorManualRunCancellationError = "";
let monitorManualRunOverlayVisible = false;
const monitorActionRunBusy = new Set();
let reengagementDemoRunBusy = false;
let reengagementDemoRunTargetId = "";
let reengagementDemoRunRequestId = "";
let reengagementDemoRunCancelling = false;
let reengagementDemoRunCancellationError = "";
let reengagementDemoRunOverlayVisible = false;
let whatsappSampleMessageBusy = false;
let agentAddToolMenuOpenFrame = null;
let agentAddToolMenuCloseTimer = null;
let whatsappSampleMessageTargetId = "";
let whatsappHistoryRefreshPromise = null;
let featureConfigBusy = false;
let featureConfigSavePromise = null;
const featureConfigAutosaveTimers = new Map();
let accountProfileAutosaveTimer = null;
let accountProfileSavePromise = null;
let whatsappConnectionPollTimer = null;
let whatsappConnectionPollInFlight = false;
let whatsappConnectionPollActive = false;
let whatsappConnectionPollFeatureId = "";
let scheduledActionsPollTimer = null;
let scheduledActionsRefreshPromise = null;
let whatsappApprovalsPollTimer = null;
let whatsappApprovalsRefreshPromise = null;

const elements = {
  loadingView: document.querySelector("#loadingView"),
  authView: document.querySelector("#authView"),
  authCard: document.querySelector("#authCard"),
  authAlertOverlay: document.querySelector("#authAlertOverlay"),
  authAlertDialog: document.querySelector("#authAlertDialog"),
  authAlertIcon: document.querySelector("#authAlertIcon"),
  authAlertEyebrow: document.querySelector("#authAlertEyebrow"),
  authAlertTitle: document.querySelector("#authAlertTitle"),
  authAlertMessage: document.querySelector("#authAlertMessage"),
  authAlertBody: document.querySelector("#authAlertBody"),
  authAlertSecondaryButton: document.querySelector("#authAlertSecondaryButton"),
  authAlertDismissButton: document.querySelector("#authAlertDismissButton"),
  appView: document.querySelector("#appView"),
  emailInput: document.querySelector("#emailInput"),
  sendCodeButton: document.querySelector("#sendCodeButton"),
  otpPanel: document.querySelector("#otpPanel"),
  otpDigits: Array.from(document.querySelectorAll(".otp-digit")),
  changeEmailButton: document.querySelector("#changeEmailButton"),
  authMessage: document.querySelector("#authMessage"),
  demoCodeText: document.querySelector("#demoCodeText"),
  workspaceTitle: document.querySelector("#workspaceTitle"),
  workspaceSubtitle: document.querySelector("#workspaceSubtitle"),
  saveState: document.querySelector("#saveState"),
  appBar: document.querySelector("#appBar"),
  agentWorkspaceStatus: document.querySelector("#agentWorkspaceStatus"),
  agentEmptyState: document.querySelector("#agentEmptyState"),
  agentMessageList: document.querySelector("#agentMessageList"),
  agentComposerForm: document.querySelector("#agentComposerForm"),
  agentComposerInput: document.querySelector("#agentComposerInput"),
  agentComposerButton: document.querySelector("#agentComposerButton"),
  agentProposalCard: document.querySelector("#agentProposalCard"),
  agentHelperCount: document.querySelector("#agentHelperCount"),
  agentHelperList: document.querySelector("#agentHelperList"),
  agentPromptButtons: Array.from(document.querySelectorAll("[data-agent-prompt]")),
  featureList: document.querySelector("#featureList"),
  agentToolShelf: document.querySelector("#agentToolShelf"),
  agentAddToolButton: document.querySelector("#agentAddToolButton"),
  agentAddToolBackdrop: document.querySelector("#agentAddToolBackdrop"),
  agentAddToolMenu: document.querySelector("#agentAddToolMenu"),
  agentActionsPanelBody: document.querySelector("#agentActionsPanelBody"),
  agentActionsListView: document.querySelector("#agentActionsListView"),
  agentActionsStatus: document.querySelector("#agentActionsStatus"),
  agentActionsRefreshButton: document.querySelector("#agentActionsRefreshButton"),
  agentPendingActionsCount: document.querySelector("#agentPendingActionsCount"),
  agentCompletedActionsCount: document.querySelector("#agentCompletedActionsCount"),
  agentHistoryToggleButton: document.querySelector("#agentHistoryToggleButton"),
  agentHistorySection: document.querySelector(".agent-history-section"),
  agentPendingActionList: document.querySelector("#agentPendingActionList"),
  agentCompletedActionList: document.querySelector("#agentCompletedActionList"),
  agentActionDetailView: document.querySelector("#agentActionDetailView"),
  agentActionDetailContent: document.querySelector("#agentActionDetailContent"),
  agentActionDetailBackButton: document.querySelector("#agentActionDetailBackButton"),
  agentToolsToggleButton: document.querySelector("#agentToolsToggleButton"),
  agentToolsCloseButton: document.querySelector("#agentToolsCloseButton"),
  agentToolsPanel: document.querySelector(".agent-tools-panel"),
  featureStudioPanel: document.querySelector("#featureStudioPanel"),
  backToFeaturesButton: document.querySelector("#backToFeaturesButton"),
  featureStudioHeaderLabel: document.querySelector("#featureStudioHeaderLabel"),
  featureStudioNav: document.querySelector("#featureStudioNav"),
  featureStudioOverviewButton: document.querySelector("#featureStudioOverviewButton"),
  featureStudioEditorButton: document.querySelector("#featureStudioEditorButton"),
  featureStudioActivationSection: document.querySelector("#featureStudioActivationSection"),
  featureStudioStatus: document.querySelector("#featureStudioStatus"),
  featureStudioOverviewSection: document.querySelector("#featureStudioOverviewSection"),
  featureStudioActivationButton: document.querySelector("#featureStudioActivationButton"),
  featureStudioEditorSection: document.querySelector("#toolEditorSection"),
  featureStudioEditorToggleButton: document.querySelector("#featureStudioEditorToggleButton"),
  featureStudioWhatsAppSampleButton: document.querySelector("#featureStudioWhatsAppSampleButton"),
  featureStudioWhatsAppHistoryButton: document.querySelector("#featureStudioWhatsAppHistoryButton"),
  featureStudioMonitorRunButton: document.querySelector("#featureStudioMonitorRunButton"),
  featureStudioTitle: document.querySelector("#featureStudioTitle"),
  featureStudioDescription: document.querySelector("#featureStudioDescription"),
  featureStudioPitch: document.querySelector("#featureStudioPitch"),
  featureStudioExampleSender: document.querySelector("#featureStudioExampleSender"),
  featureStudioExampleAvatar: document.querySelector("#featureStudioExampleAvatar"),
  featureStudioExampleMeta: document.querySelector("#featureStudioExampleMeta"),
  featureStudioExampleMessage: document.querySelector("#featureStudioExampleMessage"),
  featureStudioExampleReply: document.querySelector("#featureStudioExampleReply"),
  featureStudioLaunchButton: document.querySelector("#featureStudioLaunchButton"),
  featureActivationBusinessAccountIdInput: document.querySelector("#featureActivationBusinessAccountId"),
  featureActivationBusinessAccountIdHelpButton: document.querySelector("#featureActivationBusinessAccountIdHelpButton"),
  featureActivationPhoneNumberIdInput: document.querySelector("#featureActivationPhoneNumberId"),
  featureActivationPhoneNumberIdHelpButton: document.querySelector("#featureActivationPhoneNumberIdHelpButton"),
  featureActivationBusinessAccountIdError: document.querySelector("#featureActivationBusinessAccountIdError"),
  featureActivationPhoneNumberIdError: document.querySelector("#featureActivationPhoneNumberIdError"),
  featureActivationAccessTokenInput: document.querySelector("#featureActivationAccessToken"),
  featureActivationAccessTokenHelp: document.querySelector("#featureActivationAccessTokenHelp"),
  featureActivationAccessTokenError: document.querySelector("#featureActivationAccessTokenError"),
  featureActivationOwnerWaIdInput: document.querySelector("#featureActivationOwnerWaId"),
  featureActivationOwnerWaIdError: document.querySelector("#featureActivationOwnerWaIdError"),
  featureActivationNumberStatusTitle: document.querySelector("#featureActivationNumberStatusTitle"),
  featureActivationNumberStatusCopy: document.querySelector("#featureActivationNumberStatusCopy"),
  featureActivationInboundStatusTitle: document.querySelector("#featureActivationInboundStatusTitle"),
  featureActivationInboundStatusCopy: document.querySelector("#featureActivationInboundStatusCopy"),
  featureActivationOwnerStatusTitle: document.querySelector("#featureActivationOwnerStatusTitle"),
  featureActivationOwnerStatusCopy: document.querySelector("#featureActivationOwnerStatusCopy"),
  featureActivationWebhookHint: document.querySelector("#featureActivationWebhookHint"),
  monitorTargetCard: document.querySelector("#monitorTargetCard"),
  monitorScheduleCard: document.querySelector("#monitorScheduleCard"),
  monitorDeliveryCard: document.querySelector("#monitorDeliveryCard"),
  monitorDeliveryChannelField: document.querySelector("#monitorDeliveryChannelField"),
  monitorWatchItemsEditor: document.querySelector("#monitorWatchItemsEditor"),
  monitorWatchItemsList: document.querySelector("#monitorWatchItemsList"),
  monitorWatchItemInput: document.querySelector("#monitorWatchItemInput"),
  monitorWatchItemAddButton: document.querySelector("#monitorWatchItemAddButton"),
  monitorManualOnly: document.querySelector("#monitorManualOnly"),
  monitorIntervalDays: document.querySelector("#monitorIntervalDays"),
  monitorScheduleTime: document.querySelector("#monitorScheduleTime"),
  monitorScheduleTimezoneLabel: document.querySelector("#monitorScheduleTimezoneLabel"),
  monitorNextRun: document.querySelector("#monitorNextRun"),
  monitorNextRunValue: document.querySelector("#monitorNextRunValue"),
  monitorDeliveryChannel: document.querySelector("#monitorDeliveryChannel"),
  deliveryPlatformManager: document.querySelector("#deliveryPlatformManager"),
  deliveryPlatformList: document.querySelector("#deliveryPlatformList"),
  deliveryPlatformAddButton: document.querySelector("#deliveryPlatformAddButton"),
  deliveryPlatformMenu: document.querySelector("#deliveryPlatformMenu"),
  monitorEmailField: document.querySelector("#monitorEmailField"),
  monitorEmailSummary: document.querySelector("#monitorEmailSummary"),
  monitorTelegramField: document.querySelector("#monitorTelegramField"),
  monitorTelegramChatId: document.querySelector("#monitorTelegramChatId"),
  monitorWhatsAppField: document.querySelector("#monitorWhatsAppField"),
  monitorWhatsAppSetupButton: document.querySelector("#monitorWhatsAppSetupButton"),
  reengagementScheduleCard: document.querySelector("#reengagementScheduleCard"),
  reengagementIntervalDays: document.querySelector("#reengagementIntervalDays"),
  reengagementScheduleTime: document.querySelector("#reengagementScheduleTime"),
  reengagementScheduleTimezoneLabel: document.querySelector("#reengagementScheduleTimezoneLabel"),
  reengagementInactivityValue: document.querySelector("#reengagementInactivityValue"),
  reengagementInactivityUnit: document.querySelector("#reengagementInactivityUnit"),
  reengagementNextRun: document.querySelector("#reengagementNextRun"),
  reengagementNextRunValue: document.querySelector("#reengagementNextRunValue"),
  reengagementDemoResultsCard: document.querySelector("#reengagementDemoResultsCard"),
  reengagementDemoResultsSummary: document.querySelector("#reengagementDemoResultsSummary"),
  reengagementDemoResultsList: document.querySelector("#reengagementDemoResultsList"),
  featureModelCard: document.querySelector("#featureModelCard"),
  featureModelSelect: document.querySelector("#featureModelSelect"),
  featureModelBand: document.querySelector("#featureModelBand"),
  featureModelSummary: document.querySelector("#featureModelSummary"),
  featureToneCard: document.querySelector("#featureToneCard"),
  featureRulesCard: document.querySelector("#featureRulesCard"),
  featureContextCard: document.querySelector("#featureContextCard"),
  featureStudioWhatsAppHealthNotice: document.querySelector("#featureStudioWhatsAppHealthNotice"),
  featureStudioWhatsAppHealthNoticeTitle: document.querySelector("#featureStudioWhatsAppHealthNoticeTitle"),
  featureStudioWhatsAppHealthNoticeCopy: document.querySelector("#featureStudioWhatsAppHealthNoticeCopy"),
  whatsappHistorySection: document.querySelector("#whatsappHistorySection"),
  whatsappHistoryFileInput: document.querySelector("#whatsappHistoryFileInput"),
  whatsappHistoryImportStatus: document.querySelector("#whatsappHistoryImportStatus"),
  whatsappHistoryDiagnostics: document.querySelector("#whatsappHistoryDiagnostics"),
  whatsappHistoryConversationList: document.querySelector("#whatsappHistoryConversationList"),
  whatsappHistorySelectedAvatar: document.querySelector("#whatsappHistorySelectedAvatar"),
  whatsappHistorySelectedTitle: document.querySelector("#whatsappHistorySelectedTitle"),
  whatsappHistorySelectedMeta: document.querySelector("#whatsappHistorySelectedMeta"),
  whatsappHistorySelectedCount: document.querySelector("#whatsappHistorySelectedCount"),
  whatsappHistoryDeleteButton: document.querySelector("#whatsappHistoryDeleteButton"),
  whatsappHistoryMessages: document.querySelector("#whatsappHistoryMessages"),
  accountMenuButton: document.querySelector("#accountMenuButton"),
  accountMenu: document.querySelector("#accountMenu"),
  accountAvatar: document.querySelector("#accountAvatar"),
  accountLabel: document.querySelector("#accountLabel"),
  tabButtons: Array.from(document.querySelectorAll(".tab-button")),
  featuresPanel: document.querySelector("#featuresPanel"),
  opportunitiesPanel: document.querySelector("#opportunitiesPanel"),
  opportunitiesSummary: document.querySelector("#opportunitiesSummary"),
  opportunitiesList: document.querySelector("#opportunitiesList"),
  opportunitiesRefreshButton: document.querySelector("#opportunitiesRefreshButton"),
  clientsPanel: document.querySelector("#clientsPanel"),
  personalDetailsPanel: document.querySelector("#personalDetailsPanel"),
  personalDetailsPreviewCard: document.querySelector("#personalDetailsPreviewCard"),
  profileBusinessSummaryInput: document.querySelector("#profileBusinessSummaryInput"),
  profileCustomerNotesInput: document.querySelector("#profileCustomerNotesInput"),
  profileAssistantGuidanceInput: document.querySelector("#profileAssistantGuidanceInput"),
  personalDetailsPreview: document.querySelector("#personalDetailsPreview"),
  previewPanel: document.querySelector("#previewPanel"),
  simulatorPanel: document.querySelector("#simulatorPanel"),
  billingPanel: document.querySelector("#billingPanel"),
  billingBackButton: document.querySelector("#backToToolsButton"),
  pricingPanel: document.querySelector("#pricingPanel"),
  pricingBackButton: document.querySelector("#backToPricingToolsButton"),
  settingsPanel: document.querySelector("#settingsPanel"),
  billingStatusBanner: document.querySelector("#billingStatusBanner"),
  billingStatusMessage: document.querySelector("#billingStatusMessage"),
  billingStatusMeta: document.querySelector("#billingStatusMeta"),
  billingHelpButton: document.querySelector("#billingHelpButton"),
  billingHelpPopover: document.querySelector("#billingHelpPopover"),
  billingHelpCloseButton: document.querySelector("#billingHelpCloseButton"),
  billingHelpBody: document.querySelector("#billingHelpBody"),
  billingRefreshButton: document.querySelector("#billingRefreshButton"),
  billingHelpStrip: document.querySelector("#billingHelpStrip"),
  billingHero: document.querySelector("#billingHero"),
  billingGrid: document.querySelector("#billingGrid"),
  billingCurrentMonthLabel: document.querySelector("#billingCurrentMonthLabel"),
  billingCurrentSummary: document.querySelector("#billingCurrentSummary"),
  billingCurrentTokens: document.querySelector("#billingCurrentTokens"),
  billingCurrentCharge: document.querySelector("#billingCurrentCharge"),
  billingNextPayment: document.querySelector("#billingNextPayment"),
  billingMix: document.querySelector("#billingMix"),
  billingModelCount: document.querySelector("#billingModelCount"),
  billingModelList: document.querySelector("#billingModelList"),
  billingHistoryCount: document.querySelector("#billingHistoryCount"),
  billingHistoryList: document.querySelector("#billingHistoryList"),
  pricingCardCount: document.querySelector("#pricingCardCount"),
  pricingSourceType: document.querySelector("#pricingSourceType"),
  pricingStatusBanner: document.querySelector("#pricingStatusBanner"),
  pricingStatusMessage: document.querySelector("#pricingStatusMessage"),
  pricingStatusMeta: document.querySelector("#pricingStatusMeta"),
  pricingCardGrid: document.querySelector("#pricingCardGrid"),
  closeSettingsButton: document.querySelector("#closeSettingsButton"),
  settingsSwitcher: document.querySelector("#settingsSwitcher"),
  settingsTitle: document.querySelector("#settingsTitle"),
  settingsDescription: document.querySelector("#settingsDescription"),
  toneGuidance: document.querySelector("#toneGuidance"),
  responseStyle: document.querySelector("#responseStyle"),
  replyRules: document.querySelector("#replyRules"),
  businessNotes: document.querySelector("#businessNotes"),
  escalationGuidance: document.querySelector("#escalationGuidance"),
  scenarioSelect: document.querySelector("#scenarioSelect"),
  scenarioMessage: document.querySelector("#scenarioMessage"),
  responseMessage: document.querySelector("#responseMessage"),
  approvalSender: document.querySelector("#approvalSender"),
  compiledPrompt: document.querySelector("#compiledPrompt"),
  copyButton: document.querySelector("#copyButton"),
  simulatorPresetSelect: document.querySelector("#simulatorPresetSelect"),
  simulatorSenderNameInput: document.querySelector("#simulatorSenderNameInput"),
  simulatorSenderWaIdInput: document.querySelector("#simulatorSenderWaIdInput"),
  simulatorMessageInput: document.querySelector("#simulatorMessageInput"),
  simulatorContextInput: document.querySelector("#simulatorContextInput"),
  simulatorApprovalUrlInput: document.querySelector("#simulatorApprovalUrlInput"),
  simulatorQueueList: document.querySelector("#simulatorQueueList"),
  simulatorQueueCount: document.querySelector("#simulatorQueueCount"),
  simulatorDetailTitle: document.querySelector("#simulatorDetailTitle"),
  simulatorDetailStatus: document.querySelector("#simulatorDetailStatus"),
  simulatorDetailSender: document.querySelector("#simulatorDetailSender"),
  simulatorDetailMessage: document.querySelector("#simulatorDetailMessage"),
  simulatorDetailReply: document.querySelector("#simulatorDetailReply"),
  simulatorReplyInput: document.querySelector("#simulatorReplyInput"),
  simulatorContextList: document.querySelector("#simulatorContextList"),
  simulatorApprovalNote: document.querySelector("#simulatorApprovalNote"),
  simulatorQueueButton: document.querySelector("#simulatorQueueButton"),
  simulatorLoadSampleButton: document.querySelector("#simulatorLoadSampleButton"),
  simulatorEditButton: document.querySelector("#simulatorEditButton"),
  simulatorSendButton: document.querySelector("#simulatorSendButton"),
  simulatorResetButton: document.querySelector("#simulatorResetButton"),
  settingsButtons: Array.from(document.querySelectorAll("#settingsPanel [data-settings-mode]")),
  accountSettingsPane: document.querySelector("#accountSettingsPane"),
  preferencesSettingsPane: document.querySelector("#preferencesSettingsPane"),
  adminUsersPane: document.querySelector("#clientsPanel"),
  adminUsersShell: document.querySelector("#adminUsersShell"),
  adminUsersMenuItem: document.querySelector("#adminUsersMenuItem"),
  adminOpenAddUserButton: document.querySelector("#adminOpenAddUserButton"),
  adminUsersError: document.querySelector("#adminUsersError"),
  adminUsersContent: document.querySelector("#adminUsersContent"),
  signedInEmail: document.querySelector("#signedInEmail"),
  signOutButton: document.querySelector("#signOutButton"),
  displayNameInput: document.querySelector("#displayNameInput"),
  workspaceNameInput: document.querySelector("#workspaceNameInput"),
  timezoneSelect: document.querySelector("#timezoneSelect"),
};

const storedAuthSession = loadJson(AUTH_SESSION_KEY, null);
const storedAuthChallenge = loadJson(AUTH_CHALLENGE_KEY, null);
const initialAuthSession = normalizeStoredSession(storedAuthSession);
let authSession = null;
let authChallenge = normalizeStoredChallenge(storedAuthChallenge);
let authBusy = false;
let activeEmail = normalizeEmail(initialAuthSession?.email || authChallenge?.email || "");
let clientState = loadClientState("");
state.selectedSimulatorId = clientState.simulator.selectedApprovalId || null;

if (storedAuthSession && !initialAuthSession) {
  persistJson(AUTH_SESSION_KEY, null);
}

if (storedAuthChallenge && !authChallenge) {
  persistJson(AUTH_CHALLENGE_KEY, null);
}

if (authChallenge && authChallenge.expiresAt && Date.now() > authChallenge.expiresAt) {
  authChallenge = null;
  persistJson(AUTH_CHALLENGE_KEY, null);
}

function defaultTimeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function listTimeZones() {
  if (typeof Intl.supportedValuesOf === "function") {
    try {
      return Intl.supportedValuesOf("timeZone");
    } catch {
      return ["UTC", "Asia/Jerusalem", "America/New_York", "Europe/London"];
    }
  }

  return ["UTC", "Asia/Jerusalem", "America/New_York", "Europe/London"];
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function loadJson(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return fallback;
    }

    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function persistJson(key, value) {
  try {
    if (value === null) {
      window.localStorage.removeItem(key);
      return;
    }

    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Keep the app usable when local storage is restricted.
  }
}

function migrateLegacyStorage() {
  try {
    const legacyPrefix = `${LEGACY_STORAGE_PREFIX}.`;
    const nextPrefix = `${STORAGE_PREFIX}.`;
    const keysToMove = [];

    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key && key.startsWith(legacyPrefix)) {
        keysToMove.push(key);
      }
    }

    for (const legacyKey of keysToMove) {
      const nextKey = legacyKey.replace(legacyPrefix, nextPrefix);
      const value = window.localStorage.getItem(legacyKey);
      if (value === null) {
        continue;
      }

      if (window.localStorage.getItem(nextKey) === null) {
        window.localStorage.setItem(nextKey, value);
      }

      window.localStorage.removeItem(legacyKey);
    }
  } catch {
    // Keep the app usable when local storage is restricted.
  }
}

function resolvePortalApiBase() {
  const fromGlobal = window.PORTAL_API_BASE;
  if (typeof fromGlobal === "string" && fromGlobal.trim()) {
    return fromGlobal.trim().replace(/\/+$/, "");
  }

  const fromMeta = document.querySelector('meta[name="portal-api-base"]')?.content?.trim();
  if (fromMeta) {
    return fromMeta.replace(/\/+$/, "");
  }

  const fromQuery = new URLSearchParams(window.location.search).get("apiBase")?.trim();
  if (fromQuery) {
    return fromQuery.replace(/\/+$/, "");
  }

  const hostname = String(window.location.hostname || "").toLowerCase();
  const isGithubPagesHost = hostname === "github.io" || hostname.endsWith(".github.io");

  if (window.location.protocol === "file:" || window.location.origin === "null" || isGithubPagesHost) {
    return LOCAL_PORTAL_API_BASE;
  }

  return window.location.origin.replace(/\/+$/, "");
}

function normalizeStoredSession(value) {
  if (!value || typeof value !== "object") {
    return null;
  }

  const email = normalizeEmail(value.email || "");
  const token = String(value.token || "").trim();
  if (!token || !validateEmail(email)) {
    return null;
  }

  const expiresAt = Number(value.expiresAt || 0);
  if (Number.isFinite(expiresAt) && expiresAt > 0 && Date.now() > expiresAt) {
    return null;
  }

  const signedInAt = Number(value.signedInAt || value.issuedAt || Date.now());
  const requestCountry = String(value.requestCountry || "").trim().toUpperCase();
  return {
    email,
    token,
    signedIn: true,
    signedInAt: Number.isFinite(signedInAt) ? signedInAt : Date.now(),
    expiresAt: Number.isFinite(expiresAt) && expiresAt > 0 ? expiresAt : 0,
    requestCountry: /^[A-Z]{2}$/.test(requestCountry) ? requestCountry : "",
    isAdmin: Boolean(value.isAdmin),
  };
}

function normalizeStoredChallenge(value) {
  if (!value || typeof value !== "object" || "code" in value) {
    return null;
  }

  const email = normalizeEmail(value.email || "");
  if (!validateEmail(email)) {
    return null;
  }

  const requestedAt = Number(value.requestedAt || value.createdAt || value.issuedAt || Date.now());
  const expiresAt = Number(value.expiresAt || 0);
  const safeRequestedAt = Number.isFinite(requestedAt) ? requestedAt : Date.now();
  const safeExpiresAt = Number.isFinite(expiresAt) && expiresAt > 0 ? expiresAt : safeRequestedAt + OTP_TTL_MS;

  if (Date.now() > safeExpiresAt) {
    return null;
  }

  return {
    email,
    requestedAt: safeRequestedAt,
    expiresAt: safeExpiresAt,
  };
}

function isSignedIn() {
  return Boolean(authSession?.token && authSession.email && activeEmail && normalizeEmail(authSession.email) === activeEmail);
}

function isAdminUser() {
  return Boolean(isSignedIn() && authSession?.isAdmin);
}

function canReviewOpportunities() {
  return Boolean(isSignedIn() && normalizeEmail(activeEmail) === OPPORTUNITIES_OWNER_EMAIL);
}

function canManageClients() {
  return isAdminUser() || canReviewOpportunities();
}

function clearAuthSession() {
  authSession = null;
  persistJson(AUTH_SESSION_KEY, null);
  state.scheduledActions = [];
  state.scheduledActionsLoading = false;
  state.scheduledActionsError = "";
  state.scheduledActionsFailureCount = 0;
  state.scheduledActionsLastError = "";
  state.scheduledActionsLastErrorAt = 0;
  state.scheduledActionsLoadedAt = 0;
  state.selectedScheduledActionId = "";
  state.agentAddToolMenuOpen = false;
  state.platformConnections = [];
  if (scheduledActionsPollTimer !== null) {
    window.clearInterval(scheduledActionsPollTimer);
    scheduledActionsPollTimer = null;
  }
  if (whatsappApprovalsPollTimer !== null) {
    window.clearInterval(whatsappApprovalsPollTimer);
    whatsappApprovalsPollTimer = null;
  }
}

function clearAuthChallenge() {
  authChallenge = null;
  persistJson(AUTH_CHALLENGE_KEY, null);
}

function getSessionAuthHeaders() {
  const token = String(authSession?.token || "").trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function normalizeSettingsMode(mode) {
  const nextMode = VALID_SETTINGS_MODES.has(mode) ? mode : "account";
  if (nextMode === "users" && !isAdminUser()) {
    return "account";
  }
  return nextMode;
}

function normalizeAdminFeatureRecord(feature = {}) {
  return {
    featureId: String(feature.featureId || feature.id || "").trim(),
    name: String(feature.name || "").trim() || "Untitled tool",
    description: String(feature.description || "").trim(),
    channel: String(feature.channel || "").trim(),
    mode: String(feature.mode || "").trim(),
    sortOrder: Number(feature.sortOrder || 100),
  };
}

function sortUniqueFeatureIds(featureIds = []) {
  return Array.from(new Set(
    Array.isArray(featureIds)
      ? featureIds.map((featureId) => String(featureId || "").trim()).filter(Boolean)
      : [],
  )).sort();
}

function normalizeAdminPaymentStatus(paymentStatus = null) {
  const source = paymentStatus && typeof paymentStatus === "object" ? paymentStatus : {};
  const subscriptionStatus = String(source.subscriptionStatus || source.subscription_status || "").trim();
  const isPaying = Boolean(
    source.isPaying
    ?? source.isPayingCustomer
    ?? ["active", "on_trial"].includes(subscriptionStatus),
  );
  return {
    isPaying,
    label: String(source.label || "").trim() || (isPaying ? "Paying" : "Not paying"),
    provider: String(source.provider || "").trim(),
    subscriptionStatus,
    customerPortalUrl: String(source.customerPortalUrl || source.customer_portal_url || "").trim(),
    checkoutUrl: String(source.checkoutUrl || source.checkout_url || "").trim(),
    lastCheckedAt: String(source.lastCheckedAt || source.last_checked_at || "").trim(),
  };
}

function normalizeAdminClientType(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  return ADMIN_CLIENT_TYPES.some((type) => type.value === normalized) ? normalized : "";
}

function deriveAdminClientType(paymentStatus = {}) {
  return normalizeAdminPaymentStatus(paymentStatus).isPaying ? "paying" : DEFAULT_ADMIN_CLIENT_TYPE;
}

function getAdminClientTypeOption(value) {
  const normalized = normalizeAdminClientType(value) || DEFAULT_ADMIN_CLIENT_TYPE;
  return ADMIN_CLIENT_TYPES.find((type) => type.value === normalized) || ADMIN_CLIENT_TYPES[1];
}

function getAdminClientTypeLabel(value) {
  return getAdminClientTypeOption(value).label;
}

function getAdminClientTypeClass(value) {
  return getAdminClientTypeOption(value).className;
}

function normalizeAdminUserRecord(user = {}) {
  const paymentStatus = normalizeAdminPaymentStatus(user.paymentStatus || user.payment_status || null);
  const clientType = normalizeAdminClientType(user.clientType || user.client_type)
    || deriveAdminClientType(paymentStatus);
  return {
    email: normalizeEmail(user.email || ""),
    displayName: String(user.displayName || "").trim(),
    isActive: Boolean(user.isActive),
    isAdmin: Boolean(user.isAdmin),
    clientType,
    registeredAt: String(user.registeredAt || "").trim(),
    lastLoginAt: String(user.lastLoginAt || "").trim(),
    usageCount: Number(user.usageCount || user.usage_count || 0),
    lastUsageAt: String(user.lastUsageAt || user.last_usage_at || "").trim(),
    billing: user.billing && typeof user.billing === "object" ? user.billing : {},
    paymentStatus,
    assignedFeatureIds: sortUniqueFeatureIds(user.assignedFeatureIds || user.featureIds || []),
  };
}

function sortAdminUsers(users = []) {
  return [...users].sort((left, right) => {
    if (Boolean(left.isActive) !== Boolean(right.isActive)) {
      return left.isActive ? -1 : 1;
    }
    const leftLabel = (left.displayName || left.email).toLowerCase();
    const rightLabel = (right.displayName || right.email).toLowerCase();
    return leftLabel.localeCompare(rightLabel);
  });
}

function normalizeOpportunityRecord(opportunity = {}) {
  const urgencyScore = Number(opportunity.urgencyScore ?? opportunity.urgency_score ?? 0);
  return {
    id: Number(opportunity.id || 0),
    createdAt: String(opportunity.createdAt || opportunity.created_at || "").trim(),
    status: String(opportunity.status || "new").trim() || "new",
    name: normalizeText(opportunity.name || ""),
    email: normalizeEmail(opportunity.email || ""),
    phone: normalizeText(opportunity.phone || ""),
    business: normalizeText(opportunity.business || ""),
    businessSummary: normalizeText(opportunity.businessSummary || opportunity.business_summary || ""),
    painSummary: normalizeText(opportunity.painSummary || opportunity.pain_summary || ""),
    suggestedTool: normalizeText(opportunity.suggestedTool || opportunity.suggested_tool || ""),
    difficulty: normalizeText(opportunity.difficulty || ""),
    urgency: normalizeText(opportunity.urgency || ""),
    urgencyScore: Number.isFinite(urgencyScore) ? Math.max(0, Math.min(100, Math.round(urgencyScore))) : 0,
    sourcePage: String(opportunity.sourcePage || opportunity.source_page || "").trim(),
    requestCountry: String(opportunity.requestCountry || opportunity.request_country || "").trim().toUpperCase(),
  };
}

function sortOpportunitiesByUrgency(opportunities = []) {
  return [...opportunities].sort((left, right) => {
    if (right.urgencyScore !== left.urgencyScore) {
      return right.urgencyScore - left.urgencyScore;
    }
    return String(right.createdAt || "").localeCompare(String(left.createdAt || ""));
  });
}

function getOpportunityUrgencyTone(opportunity) {
  const score = Number(opportunity?.urgencyScore || 0);
  if (score >= 80) {
    return "critical";
  }
  if (score >= 60) {
    return "high";
  }
  if (score >= 35) {
    return "medium";
  }
  return "low";
}

function getOpportunityStats(opportunities = state.opportunities) {
  const total = opportunities.length;
  const highUrgency = opportunities.filter((opportunity) => Number(opportunity.urgencyScore || 0) >= 60).length;
  const averageUrgency = total
    ? Math.round(opportunities.reduce((sum, opportunity) => sum + Number(opportunity.urgencyScore || 0), 0) / total)
    : 0;
  const hardestCount = opportunities.filter((opportunity) => (
    /high|גבוה|מורכב|קשה/i.test(opportunity.difficulty || "")
  )).length;
  return { total, highUrgency, averageUrgency, hardestCount };
}

function upsertAdminUserState(user) {
  const normalizedUser = normalizeAdminUserRecord(user);
  if (!normalizedUser.email) {
    return null;
  }

  const nextUsers = state.adminUsers.filter((entry) => entry.email !== normalizedUser.email);
  nextUsers.push(normalizedUser);
  state.adminUsers = sortAdminUsers(nextUsers);
  setAdminUserDraftFeatureIds(normalizedUser.email, normalizedUser.assignedFeatureIds);
  return normalizedUser;
}

function replaceAdminUserState(previousEmail, user) {
  const normalizedPreviousEmail = normalizeEmail(previousEmail);
  const normalizedUser = normalizeAdminUserRecord(user);
  if (!normalizedPreviousEmail || !normalizedUser.email) {
    return null;
  }

  const preservedDraftFeatureIds = getAdminUserDraftFeatureIds(
    normalizedPreviousEmail,
    normalizedUser.assignedFeatureIds,
  );
  state.adminUsers = sortAdminUsers([
    ...state.adminUsers.filter((entry) => entry.email !== normalizedPreviousEmail && entry.email !== normalizedUser.email),
    normalizedUser,
  ]);

  const { [normalizedPreviousEmail]: _previousDraft, ...nextDrafts } = state.adminUserDrafts;
  state.adminUserDrafts = nextDrafts;
  setAdminUserDraftFeatureIds(normalizedUser.email, preservedDraftFeatureIds);

  const { [normalizedPreviousEmail]: _saveBusy, ...nextSaveBusy } = state.adminSaveBusyByEmail;
  state.adminSaveBusyByEmail = nextSaveBusy;

  const { [normalizedPreviousEmail]: _saveQueued, ...nextSaveQueued } = state.adminSaveQueuedByEmail;
  state.adminSaveQueuedByEmail = nextSaveQueued;

  const { [normalizedPreviousEmail]: _statusBusy, ...nextStatusBusy } = state.adminStatusBusyByEmail;
  state.adminStatusBusyByEmail = nextStatusBusy;

  const { [normalizedPreviousEmail]: _typeBusy, ...nextTypeBusy } = state.adminTypeBusyByEmail;
  state.adminTypeBusyByEmail = nextTypeBusy;

  const { [normalizedPreviousEmail]: _deleteBusy, ...nextDeleteBusy } = state.adminDeleteBusyByEmail;
  state.adminDeleteBusyByEmail = nextDeleteBusy;

  if (normalizeEmail(state.adminSelectedUserEmail) === normalizedPreviousEmail) {
    state.adminSelectedUserEmail = normalizedUser.email;
  }

  return normalizedUser;
}

function removeAdminUserState(email) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return;
  }

  state.adminUsers = state.adminUsers.filter((user) => user.email !== normalizedEmail);

  const { [normalizedEmail]: _draft, ...nextDrafts } = state.adminUserDrafts;
  state.adminUserDrafts = nextDrafts;

  const { [normalizedEmail]: _saveBusy, ...nextSaveBusy } = state.adminSaveBusyByEmail;
  state.adminSaveBusyByEmail = nextSaveBusy;

  const { [normalizedEmail]: _saveQueued, ...nextSaveQueued } = state.adminSaveQueuedByEmail;
  state.adminSaveQueuedByEmail = nextSaveQueued;

  const { [normalizedEmail]: _statusBusy, ...nextStatusBusy } = state.adminStatusBusyByEmail;
  state.adminStatusBusyByEmail = nextStatusBusy;

  const { [normalizedEmail]: _typeBusy, ...nextTypeBusy } = state.adminTypeBusyByEmail;
  state.adminTypeBusyByEmail = nextTypeBusy;

  const { [normalizedEmail]: _deleteBusy, ...nextDeleteBusy } = state.adminDeleteBusyByEmail;
  state.adminDeleteBusyByEmail = nextDeleteBusy;

  if (normalizeEmail(state.adminSelectedUserEmail) === normalizedEmail) {
    state.adminSelectedUserEmail = "";
    state.adminView = "list";
  }
}

function getSettingsModeContent(mode = state.settingsMode) {
  const normalizedMode = normalizeSettingsMode(mode);
  if (normalizedMode !== "users") {
    return SETTINGS_MODE_CONTENT[normalizedMode] || SETTINGS_MODE_CONTENT.account;
  }

  if (state.adminView === "add") {
    return {
      title: "Add client",
      description: "",
    };
  }

  if (state.adminView === "edit") {
    const user = getAdminSelectedUser();
    return {
      title: user ? `Edit ${user.displayName || deriveDisplayName(user.email)}` : "Edit client",
      description: user?.email || "Fix a typo in this client’s name or email.",
    };
  }

  if (state.adminView === "detail") {
    const user = getAdminSelectedUser();
    return {
      title: user
        ? (user.displayName || deriveDisplayName(user.email))
        : SETTINGS_MODE_CONTENT.users.title,
      description: user?.email || "Manage which tools this client can see in the portal.",
    };
  }

  return SETTINGS_MODE_CONTENT.users;
}

function getAdminUserDraftFeatureIds(email, fallback = []) {
  const key = normalizeEmail(email);
  return sortUniqueFeatureIds(state.adminUserDrafts[key] || fallback);
}

function setAdminUserDraftFeatureIds(email, featureIds) {
  const key = normalizeEmail(email);
  if (!key) {
    return;
  }
  state.adminUserDrafts = {
    ...state.adminUserDrafts,
    [key]: sortUniqueFeatureIds(featureIds),
  };
}

function addAdminUserDraftFeature(email, featureId) {
  const normalizedFeatureId = String(featureId || "").trim();
  if (!normalizedFeatureId) {
    return;
  }

  const nextFeatureIds = new Set(getAdminUserDraftFeatureIds(email));
  nextFeatureIds.add(normalizedFeatureId);
  setAdminUserDraftFeatureIds(email, Array.from(nextFeatureIds));
}

function removeAdminUserDraftFeature(email, featureId) {
  const normalizedFeatureId = String(featureId || "").trim();
  if (!normalizedFeatureId) {
    return;
  }

  const nextFeatureIds = new Set(getAdminUserDraftFeatureIds(email));
  nextFeatureIds.delete(normalizedFeatureId);
  setAdminUserDraftFeatureIds(email, Array.from(nextFeatureIds));
}

function setAdminUserSaveQueued(email, isQueued) {
  const key = normalizeEmail(email);
  if (!key) {
    return;
  }

  if (isQueued) {
    state.adminSaveQueuedByEmail = {
      ...state.adminSaveQueuedByEmail,
      [key]: true,
    };
    return;
  }

  if (!(key in state.adminSaveQueuedByEmail)) {
    return;
  }

  const { [key]: _queued, ...nextQueued } = state.adminSaveQueuedByEmail;
  state.adminSaveQueuedByEmail = nextQueued;
}

function queueAdminUserFeatureAutosave(email) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail || !canManageClients()) {
    return;
  }

  if (state.adminSaveBusyByEmail[normalizedEmail]) {
    setAdminUserSaveQueued(normalizedEmail, true);
    return;
  }

  void saveAdminUserFeatures(normalizedEmail);
}

function buildAdminUserDrafts(users = [], previousUsersByEmail = new Map(), previousDrafts = {}) {
  return Object.fromEntries(users.map((user) => {
    const previousUser = previousUsersByEmail.get(user.email) || null;
    const previousAssigned = previousUser?.assignedFeatureIds || [];
    const previousDraft = sortUniqueFeatureIds(previousDrafts[user.email] || previousAssigned);
    const shouldPreserveDraft = previousUser && !featureIdListsMatch(previousDraft, previousAssigned);
    return [user.email, shouldPreserveDraft ? previousDraft : [...user.assignedFeatureIds]];
  }));
}

function featureIdListsMatch(first = [], second = []) {
  const left = sortUniqueFeatureIds(first);
  const right = sortUniqueFeatureIds(second);
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function syncAdminUsersError() {
  if (!elements.adminUsersError) {
    return;
  }
  elements.adminUsersError.textContent = state.adminUsersError;
  elements.adminUsersError.classList.toggle("is-hidden", !state.adminUsersError);
}

function getAdminUserDeleteDisabledReason(user) {
  const normalizedEmail = normalizeEmail(user?.email || "");
  if (!normalizedEmail) {
    return "Select a valid user first.";
  }

  if (normalizedEmail === normalizeEmail(authSession?.email || activeEmail || "")) {
    return "You can't delete the admin account you're using right now.";
  }

  const activeAdminCount = state.adminUsers.filter((entry) => entry.isActive && entry.isAdmin).length;
  if (user?.isActive && user?.isAdmin && activeAdminCount <= 1) {
    return "Add another admin before deleting the last admin account.";
  }

  return "";
}

function getAdminUserActiveDisabledReason(user, nextIsActive = !Boolean(user?.isActive)) {
  const normalizedEmail = normalizeEmail(user?.email || "");
  if (!normalizedEmail) {
    return "Select a valid client first.";
  }

  if (normalizedEmail === normalizeEmail(authSession?.email || activeEmail || "") && !nextIsActive) {
    return "You can't disable the admin account you're using right now.";
  }

  const activeAdminCount = state.adminUsers.filter((entry) => entry.isActive && entry.isAdmin).length;
  if (user?.isActive && user?.isAdmin && !nextIsActive && activeAdminCount <= 1) {
    return "Add another admin before disabling the last admin account.";
  }

  return "";
}

function getAdminFeatureName(featureId) {
  const normalizedFeatureId = String(featureId || "").trim();
  if (!normalizedFeatureId) {
    return "";
  }
  const feature = state.adminFeatures.find((entry) => entry.featureId === normalizedFeatureId);
  return feature?.name || normalizedFeatureId;
}

function getAdminUserToolNames(user) {
  return sortUniqueFeatureIds(user?.assignedFeatureIds || []).map(getAdminFeatureName).filter(Boolean);
}

function formatAdminUserTools(user, maxVisible = 2) {
  const names = getAdminUserToolNames(user);
  if (!names.length) {
    return "No tools";
  }
  if (names.length <= maxVisible) {
    return names.join(", ");
  }
  return `${names.slice(0, maxVisible).join(", ")} +${names.length - maxVisible}`;
}

function createAdminStateBadge(label, className = "") {
  const badge = document.createElement("span");
  badge.className = `feature-status${className ? ` ${className}` : ""}`;
  badge.textContent = label;
  return badge;
}

function createAdminClientTypeSelect(user, options = {}) {
  const normalizedEmail = normalizeEmail(user?.email || "");
  const isBusy = Boolean(state.adminTypeBusyByEmail[normalizedEmail]);
  const selectedClientType = normalizeAdminClientType(user?.clientType) || deriveAdminClientType(user?.paymentStatus);
  const select = document.createElement("select");
  select.className = "admin-client-type-select";
  select.dataset.adminClientTypeUser = normalizedEmail;
  select.disabled = Boolean(options.disabled) || isBusy;
  select.setAttribute(
    "aria-label",
    `Client type for ${user?.displayName || normalizedEmail || "client"}`,
  );

  for (const type of ADMIN_CLIENT_TYPES) {
    const option = document.createElement("option");
    option.value = type.value;
    option.textContent = type.label;
    option.selected = type.value === selectedClientType;
    select.append(option);
  }

  select.value = selectedClientType;
  select.dataset.adminClientTypeValue = selectedClientType;
  return select;
}

function createAdminActiveSwitch(user, options = {}) {
  const normalizedEmail = normalizeEmail(user?.email || "");
  const nextIsActive = !Boolean(user?.isActive);
  const disabledReason = getAdminUserActiveDisabledReason(user, nextIsActive);
  const isBusy = Boolean(state.adminStatusBusyByEmail[normalizedEmail]);

  const label = document.createElement("label");
  label.className = "admin-switch";
  if (disabledReason) {
    label.title = disabledReason;
  }

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(user?.isActive);
  input.disabled = Boolean(options.disabled) || isBusy || Boolean(disabledReason);
  input.dataset.adminActiveUser = normalizedEmail;
  input.setAttribute(
    "aria-label",
    `${user?.displayName || normalizedEmail || "Client"} portal access`,
  );

  const track = document.createElement("span");
  track.className = "admin-switch-track";
  track.setAttribute("aria-hidden", "true");

  label.append(input, track);
  return label;
}

function getAdminClientStats(users = state.adminUsers) {
  const total = users.length;
  const active = users.filter((user) => user.isActive).length;
  const paying = users.filter((user) => normalizeAdminClientType(user.clientType) === "paying").length;
  const demo = users.filter((user) => normalizeAdminClientType(user.clientType) === "demo").length;
  const qa = users.filter((user) => normalizeAdminClientType(user.clientType) === "qa").length;
  const inactive = total - active;
  return { total, active, paying, demo, qa, inactive };
}

function resetAdminState() {
  state.adminUsers = [];
  state.adminFeatures = [];
  state.adminUsersLoading = false;
  state.adminUsersNeedsRender = false;
  state.adminUsersError = "";
  state.adminAddUserBusy = false;
  state.adminEditUserBusy = false;
  state.adminSaveBusyByEmail = {};
  state.adminSaveQueuedByEmail = {};
  state.adminStatusBusyByEmail = {};
  state.adminTypeBusyByEmail = {};
  state.adminDeleteBusyByEmail = {};
  state.adminUserDrafts = {};
  state.adminView = "list";
  state.adminSelectedUserEmail = "";
  state.adminUserSearch = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminNewUserEmail = "";
  state.adminNewUserDisplayName = "";
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";
}

function getAdminSelectedUser() {
  const email = normalizeEmail(state.adminSelectedUserEmail);
  return state.adminUsers.find((user) => user.email === email) || null;
}

function getFilteredAdminUsers() {
  const query = normalizeText(state.adminUserSearch).toLowerCase();
  if (!query) {
    return state.adminUsers;
  }

  const featureNameById = new Map(state.adminFeatures.map((feature) => [feature.featureId, feature.name]));
  return state.adminUsers.filter((user) => {
    const searchable = [
      user.displayName,
      user.email,
      user.isAdmin ? "admin" : "user",
      user.isActive ? "active" : "inactive",
      user.paymentStatus?.isPaying ? "paying" : "not paying",
      user.paymentStatus?.subscriptionStatus,
      ...user.assignedFeatureIds,
      ...user.assignedFeatureIds.map((featureId) => featureNameById.get(featureId) || ""),
    ].join(" ").toLowerCase();
    return searchable.includes(query);
  });
}

function getFilteredAdminFeatures(query = state.adminFeatureSearch) {
  const normalizedQuery = normalizeText(query).toLowerCase();
  if (!normalizedQuery) {
    return state.adminFeatures;
  }

  return state.adminFeatures.filter((feature) => {
    const searchable = [
      feature.name,
      feature.description,
      feature.channel,
      feature.mode,
      feature.featureId,
    ].join(" ").toLowerCase();
    return searchable.includes(normalizedQuery);
  });
}

function showClientsTab(options = {}) {
  if (!canManageClients()) {
    setActiveTab("features");
    return;
  }

  state.activeTab = "clients";
  state.lastPrimaryTab = "clients";
  persistLastPrimaryTab();
  state.settingsOpen = false;
  state.selectedFeatureId = null;
  state.selectedSimulatorId = null;
  closeFeatureStudioMenu();
  closeBillingHelp();
  closePersonalDetailsTips();
  closeMenu();
  if (options.syncHash !== false) {
    setHashForTab("clients");
  }
  renderApp();
  if (options.refresh !== false) {
    void refreshAdminUsers();
  }
}

function openAdminUsersList(options = {}) {
  state.adminView = "list";
  state.adminSelectedUserEmail = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";
  if (options.preserveSearch !== true) {
    state.adminUserSearch = "";
  }

  showClientsTab({ refresh: options.refresh !== false });
}

function focusAdminAddUserEmailInput() {
  window.requestAnimationFrame(() => {
    const input = elements.adminUsersPane?.querySelector('[data-admin-new-email="true"]');
    if (input instanceof HTMLInputElement) {
      input.focus();
    }
  });
}

function openAdminAddUser() {
  state.adminView = "add";
  state.adminSelectedUserEmail = "";
  state.adminUsersError = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminNewUserEmail = "";
  state.adminNewUserDisplayName = "";
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";

  showClientsTab({ refresh: false });
  focusAdminAddUserEmailInput();
}

function focusAdminEditUserInput() {
  window.requestAnimationFrame(() => {
    const emailInput = elements.adminUsersPane?.querySelector('[data-admin-edit-email="true"]');
    if (emailInput instanceof HTMLInputElement && !emailInput.disabled) {
      emailInput.focus();
      return;
    }

    const nameInput = elements.adminUsersPane?.querySelector('[data-admin-edit-display-name="true"]');
    if (nameInput instanceof HTMLInputElement) {
      nameInput.focus();
    }
  });
}

function openAdminUserDetail(email) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return;
  }

  state.adminView = "detail";
  state.adminSelectedUserEmail = normalizedEmail;
  state.adminUsersError = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";

  showClientsTab({ refresh: false });
}

function openAdminEditUser(email) {
  const user = state.adminUsers.find((entry) => entry.email === normalizeEmail(email));
  if (!user) {
    return;
  }

  state.adminView = "edit";
  state.adminSelectedUserEmail = user.email;
  state.adminUsersError = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminEditUserEmail = user.email;
  state.adminEditUserDisplayName = user.displayName || "";

  showClientsTab({ refresh: false });
  focusAdminEditUserInput();
}

function isFeatureActivationTransitionBusy(feature = getSelectedFeature()) {
  return Boolean(
    featureActivationTransitionBusy
    && feature
    && feature.id
    && feature.id === featureActivationTransitionTargetId
  );
}

function isWhatsAppFeature(feature) {
  return String(feature?.channel || "").trim().toLowerCase() === "whatsapp";
}

function isMonitorFeature(feature = getSelectedFeature()) {
  return Boolean(feature && feature.id === MONITOR_FEATURE_ID);
}

function isReengagementFeature(feature = getSelectedFeature()) {
  return Boolean(feature && feature.id === REENGAGEMENT_FEATURE_ID);
}

function isWhatsAppReplyAssistantFeature(feature = getSelectedFeature()) {
  return Boolean(feature && feature.id === WHATSAPP_REPLY_ASSISTANT_FEATURE_ID);
}

function usesEditorSetup(feature = getSelectedFeature()) {
  return Boolean(feature?.metadata && feature.metadata.setupSurface === "editor");
}

function normalizeCountryCode(value) {
  const code = String(value || "").trim().toUpperCase();
  return /^[A-Z]{2}$/.test(code) ? code : "";
}

function inferRequestCountryCode() {
  const explicit = normalizeCountryCode(state.requestCountryCode || authSession?.requestCountry);
  if (explicit) {
    return explicit;
  }

  const timeZone = String(clientState?.settings?.timezone || defaultTimeZone()).trim();
  if (timeZone === "Asia/Jerusalem") {
    return "IL";
  }

  const locale = String(navigator.language || "").trim().toUpperCase();
  if (locale.endsWith("-IL")) {
    return "IL";
  }
  if (locale.endsWith("-US")) {
    return "US";
  }

  return "";
}

function getOwnerPhonePlaceholder() {
  const requestCountry = inferRequestCountryCode();
  return PHONE_PLACEHOLDER_BY_COUNTRY[requestCountry] || PHONE_PLACEHOLDER_BY_COUNTRY.US;
}

function buildApiUrl(path) {
  return new URL(path, PORTAL_API_BASE.endsWith("/") ? PORTAL_API_BASE : `${PORTAL_API_BASE}/`).toString();
}

function describeHttpError(response) {
  const statusText = sanitizeErrorText(response?.statusText || "").replace(/\.$/, "");
  return statusText
    ? `The server returned ${response.status} ${statusText}. Please try again.`
    : `The server returned ${response.status}. Please try again.`;
}

function syncAuthControls() {
  const hasChallenge = Boolean(authChallenge?.email);
  elements.sendCodeButton.disabled = authBusy;
  elements.changeEmailButton.disabled = authBusy;
  elements.emailInput.disabled = hasChallenge || authBusy;

  for (const digitInput of elements.otpDigits) {
    digitInput.disabled = !hasChallenge || authBusy;
  }
}

function stripTags(value) {
  return String(value || "").replace(/<[^>]*>/g, " ");
}

function sanitizeErrorText(value) {
  return stripTags(value).replace(/\s+/g, " ").trim();
}

function looksLikeHtml(value) {
  const text = String(value || "").trim();
  return /^<!doctype/i.test(text) || /^<html[\s>]/i.test(text) || /<\/[a-z][^>]*>/i.test(text);
}

function formatApiErrorMessage(error, fallback = "Something went wrong. Please try again.") {
  const payloadRaw = String(error?.payload?.message || "");
  const errorRaw = String(error?.message || "");

  if (looksLikeHtml(payloadRaw) || looksLikeHtml(errorRaw)) {
    if (error?.status) {
      const statusText = sanitizeErrorText(error?.statusText || "").replace(/\.$/, "");
      return statusText
        ? `The server returned ${error.status} ${statusText}. Please try again.`
        : `The server returned ${error.status}. Please try again.`;
    }

    return fallback;
  }

  const payloadMessage = sanitizeErrorText(payloadRaw);
  const errorMessage = sanitizeErrorText(errorRaw);
  const raw = payloadMessage || errorMessage;

  if (raw && !looksLikeHtml(raw)) {
    return raw;
  }

  if (error?.status) {
    const statusText = sanitizeErrorText(error?.statusText || "").replace(/\.$/, "");
    return statusText
      ? `The server returned ${error.status} ${statusText}. Please try again.`
      : `The server returned ${error.status}. Please try again.`;
  }

  return fallback;
}

function syncAuthAlertState() {
  const overlay = elements.authAlertOverlay;
  if (!overlay) {
    return;
  }

  if (authAlertOpenFrame !== null) {
    window.cancelAnimationFrame(authAlertOpenFrame);
    authAlertOpenFrame = null;
  }

  if (authAlertCloseTimer !== null) {
    window.clearTimeout(authAlertCloseTimer);
    authAlertCloseTimer = null;
  }

  if (state.authAlertOpen) {
    overlay.classList.remove("is-hidden");
    document.body.dataset.modal = "alert";

    if (!overlay.classList.contains("is-open")) {
      authAlertOpenFrame = window.requestAnimationFrame(() => {
        overlay.classList.add("is-open");
        authAlertOpenFrame = null;
      });
    }

    return;
  }

  overlay.classList.remove("is-open");

  if (overlay.classList.contains("is-hidden")) {
    if (document.body.dataset.modal === "alert") {
      delete document.body.dataset.modal;
    }
    return;
  }

  authAlertCloseTimer = window.setTimeout(() => {
    overlay.classList.add("is-hidden");
    if (document.body.dataset.modal === "alert") {
      delete document.body.dataset.modal;
    }
    authAlertCloseTimer = null;
  }, 220);
}

function openAuthAlert(title, message, options = {}) {
  const iconMode = normalizeText(options.iconMode).toLowerCase();
  if (elements.authAlertOverlay) {
    elements.authAlertOverlay.dataset.mode = iconMode === "spinner" ? "loading" : "default";
  }
  if (elements.authAlertIcon) {
    elements.authAlertIcon.dataset.tone = String(options.tone || "warning");
    elements.authAlertIcon.classList.toggle("is-spinner", iconMode === "spinner");
    elements.authAlertIcon.textContent = iconMode === "spinner" ? "" : String(options.icon || "!");
  }
  if (elements.authAlertEyebrow) {
    elements.authAlertEyebrow.textContent = String(options.eyebrow || "Sign-in help");
  }
  if (elements.authAlertTitle) {
    elements.authAlertTitle.textContent = String(title || "Let’s get you set up");
  }

  if (elements.authAlertMessage) {
    elements.authAlertMessage.textContent = String(message || "If you need help, contact me and I’ll take care of it.");
  }
  if (elements.authAlertDialog) {
    elements.authAlertDialog.dataset.mode = iconMode === "spinner" ? "loading" : "default";
    elements.authAlertDialog.dataset.variant = normalizeText(options.variant) || "default";
  }
  if (elements.authAlertBody) {
    elements.authAlertBody.innerHTML = "";
    const bodyNode = options.bodyNode;
    if (bodyNode && typeof bodyNode.nodeType === "number") {
      elements.authAlertBody.append(bodyNode);
      elements.authAlertBody.classList.remove("is-hidden");
    } else {
      elements.authAlertBody.classList.add("is-hidden");
    }
  }
  const secondaryButtonLabel = normalizeText(options.secondaryButtonLabel);
  const hidePrimaryButton = Boolean(options.hidePrimaryButton);
  if (elements.authAlertSecondaryButton) {
    elements.authAlertSecondaryButton.textContent = secondaryButtonLabel || "Cancel";
    elements.authAlertSecondaryButton.classList.toggle("is-hidden", !secondaryButtonLabel);
    elements.authAlertSecondaryButton.disabled = Boolean(options.secondaryDisabled);
  }
  if (elements.authAlertDismissButton) {
    elements.authAlertDismissButton.textContent = String(options.buttonLabel || "OK");
    elements.authAlertDismissButton.classList.toggle("is-hidden", hidePrimaryButton);
    elements.authAlertDismissButton.classList.toggle("danger", normalizeText(options.primaryTone).toLowerCase() === "danger");
    elements.authAlertDismissButton.disabled = Boolean(options.primaryDisabled);
  }

  authAlertPrimaryAction = typeof options.onPrimary === "function" ? options.onPrimary : null;
  authAlertSecondaryAction = typeof options.onSecondary === "function" ? options.onSecondary : null;
  authAlertCloseOnPrimary = options.closeOnPrimary !== false;
  authAlertCloseOnSecondary = options.closeOnSecondary !== false;
  authAlertBackdropDismiss = options.dismissOnBackdrop !== false;
  authAlertEscapeDismiss = options.dismissOnEscape !== false;
  authAlertFocusTarget = options.focusTarget === "secondary" && secondaryButtonLabel
    ? "secondary"
    : hidePrimaryButton && secondaryButtonLabel
      ? "secondary"
      : "primary";
  authAlertReturnFocus = options.returnFocus || null;
  state.authAlertOpen = true;
  syncAuthAlertState();

  window.requestAnimationFrame(() => {
    const focusTarget = authAlertFocusTarget === "secondary"
      ? elements.authAlertSecondaryButton
      : elements.authAlertDismissButton;
    if (focusTarget && !focusTarget.disabled && !focusTarget.classList.contains("is-hidden")) {
      focusTarget.focus();
      return;
    }

    elements.authAlertDialog?.focus();
  });
}

function openFeatureActivationAlert(title, message, options = {}) {
  openAuthAlert(title, message, {
    eyebrow: options.eyebrow || "Before you turn it on",
    returnFocus: options.returnFocus || elements.featureStudioActivationButton,
  });
}

function openMetaWhatsAppAccounts() {
  window.open(META_WHATSAPP_ACCOUNTS_URL, "_blank", "noopener,noreferrer");
}

function openWhatsAppIdsHelp(returnFocus = elements.featureActivationPhoneNumberIdHelpButton) {
  openAuthAlert(
    "Where to find the WhatsApp IDs",
    "Open Meta Business Settings, choose the correct business portfolio, then go to Accounts > WhatsApp Accounts. Select the client's WhatsApp Business Account; the WABA ID is shown on that account. Open Phone numbers to copy the Phone Number ID for the exact number that receives customer messages.",
    {
      eyebrow: "WhatsApp setup",
      icon: "?",
      buttonLabel: "Open Meta",
      secondaryButtonLabel: "Done",
      onPrimary: openMetaWhatsAppAccounts,
      returnFocus,
    },
  );
}

function updateFeatureActivationPhonePlaceholder() {
  if (!elements.featureActivationOwnerWaIdInput) {
    return;
  }

  elements.featureActivationOwnerWaIdInput.placeholder = getOwnerPhonePlaceholder();
}

function closeAuthAlert() {
  if (!state.authAlertOpen) {
    return;
  }

  // Credential forms are ephemeral. Clear password fields before the dialog
  // leaves the screen so a token cannot linger in the DOM after dismissal.
  elements.authAlertBody?.querySelectorAll('input[type="password"], input[name="credential"]').forEach((input) => {
    input.value = "";
  });
  state.authAlertOpen = false;
  syncAuthAlertState();

  const returnFocus = authAlertReturnFocus;
  authAlertReturnFocus = null;
  authAlertPrimaryAction = null;
  authAlertSecondaryAction = null;
  authAlertFocusTarget = "primary";
  authAlertCloseOnPrimary = true;
  authAlertCloseOnSecondary = true;
  authAlertBackdropDismiss = true;
  authAlertEscapeDismiss = true;

  window.requestAnimationFrame(() => {
    if (returnFocus === "otp") {
      focusFirstEmptyOtpDigit();
      return;
    }

    if (returnFocus === "email") {
      elements.emailInput.focus();
      return;
    }

    if (returnFocus && typeof returnFocus.focus === "function") {
      returnFocus.focus();
    }
  });
}

function handleAuthAlertPrimaryAction() {
  const action = authAlertPrimaryAction;
  if (authAlertCloseOnPrimary) {
    closeAuthAlert();
  }
  if (typeof action === "function") {
    action();
  }
}

function handleAuthAlertSecondaryAction() {
  const action = authAlertSecondaryAction;
  if (authAlertCloseOnSecondary) {
    closeAuthAlert();
  }
  if (typeof action === "function") {
    action();
  }
}

async function apiRequest(path, options = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || 15000);
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const headers = new Headers(options.headers || {});
    const init = {
      method: options.method || "GET",
      headers,
      cache: options.cache || "no-store",
      credentials: options.credentials || "same-origin",
      signal: controller.signal,
    };

    if (options.body !== undefined) {
      if (typeof options.body === "string" || options.body instanceof FormData || options.body instanceof URLSearchParams) {
        init.body = options.body;
      } else {
        init.body = JSON.stringify(options.body);
        if (!headers.has("Content-Type")) {
          headers.set("Content-Type", "application/json");
        }
      }
    }

    const response = await fetch(buildApiUrl(path), init);
    const text = await response.text();
    let payload = {};

    if (text.trim()) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = { message: text };
      }
    }

    if (!response.ok) {
      const error = new Error(describeHttpError(response));
      error.status = response.status;
      error.statusText = response.statusText;
      error.payload = payload;
      error.responseText = text;
      throw error;
    }

    return payload;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function isAbortError(error) {
  const label = `${error?.name || ""} ${error?.message || ""}`.toLowerCase();
  return label.includes("abort");
}

function getClientKey(email) {
  const safeEmail = normalizeEmail(email) || "guest";
  return `${CLIENT_STATE_PREFIX}:${safeEmail}`;
}

function getMonitorWatchDraftKey(featureId, email = activeEmail) {
  const safeFeatureId = String(featureId || "").trim();
  if (!safeFeatureId) {
    return "";
  }

  const safeEmail = normalizeEmail(email) || "guest";
  return `${MONITOR_WATCH_DRAFT_PREFIX}:${safeEmail}:${safeFeatureId}`;
}

function loadMonitorWatchDraft(featureId, email = activeEmail) {
  const key = getMonitorWatchDraftKey(featureId, email);
  return key ? String(loadJson(key, "") || "") : "";
}

function persistMonitorWatchDraft(value, featureId, email = activeEmail) {
  const key = getMonitorWatchDraftKey(featureId, email);
  if (!key) {
    return;
  }

  const draft = String(value || "");
  persistJson(key, draft ? draft : null);
}

function loadClientState(email) {
  const saved = loadJson(getClientKey(email), null) || {};
  const savedPrompt = saved.guidance || {};
  const savedSimulator = saved.simulator || {};
  const profile = normalizeAccountProfile(saved.profile || {});
  const featuresSource = Array.isArray(saved.features) && saved.features.length
    ? saved.features
    : DEFAULT_FEATURES;
  let didMigrateLegacyDescription = false;
  const features = featuresSource.map((feature, index) => {
    const fallbackPrompt = index === 0 ? { ...DEFAULT_PROMPT, ...savedPrompt } : DEFAULT_PROMPT;
    const featureId = String(feature?.id || "");
    const featureName = String(feature?.name || "");
    const featureMode = String(feature?.mode || "");
    const featureDescription = String(feature?.description || "");
    const featureChannel = String(feature?.channel || "");
    const activated = Boolean(
      feature?.activated
      ?? feature?.isActivated
      ?? (String(feature?.status || "").trim().toLowerCase() === "active"),
    );
    const savedSetupComplete = Boolean(
      feature?.setupComplete
      ?? feature?.setup_complete
      ?? feature?.isSetupComplete
      ?? activated,
    );
    const setupComplete = savedSetupComplete;
    const isLegacyDefaultFeature = index === 0
      && featureId === DEFAULT_FEATURES[0].id
      && (
        LEGACY_DEFAULT_FEATURE_NAMES.has(featureName)
        || LEGACY_DEFAULT_FEATURE_MODES.has(featureMode)
      );
    const shouldUpgradeDescription = index === 0
      && featureId === DEFAULT_FEATURES[0].id
      && (
        isLegacyDefaultFeatureDescription(featureDescription)
        || (!featureDescription && isLegacyDefaultFeature)
      );

    if (shouldUpgradeDescription) {
      didMigrateLegacyDescription = true;
    }

    return {
      id: featureId || `feature-${index + 1}`,
      name: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].name
        : String(feature?.name || `Tool ${index + 1}`),
      description: shouldUpgradeDescription
        ? DEFAULT_FEATURES[0].description
        : featureDescription,
      channel: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].channel
        : featureChannel || "Web",
      mode: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].mode
        : String(feature?.mode || "Default"),
      status: activated ? "active" : "non-active",
      activated,
      setupComplete,
      launchUrl: String(
        feature?.launchUrl
        || (index === 0 ? DEFAULT_FEATURE_LAUNCH_URL : "")
      ).trim(),
      pricing: normalizeFeaturePricing(feature?.pricing || {}),
      prompt: normalizePrompt(feature?.prompt || {}, fallbackPrompt),
      savedPrompt: normalizePrompt(feature?.savedPrompt || feature?.prompt || {}, fallbackPrompt),
      requirements: normalizeFeatureRequirements(feature?.requirements || {}),
      billing: normalizeFeatureBilling(feature?.billing || {}),
      assignment: feature?.assignment && typeof feature.assignment === "object"
        ? { ...feature.assignment }
        : {},
      paymentStatus: normalizeFeaturePaymentStatus(feature?.paymentStatus || null),
      metadata: feature?.metadata && typeof feature.metadata === "object"
        ? { ...feature.metadata }
        : {},
      settings: normalizeSettingsForFeature(featureId, feature?.settings || {}),
      savedSettings: normalizeSettingsForFeature(featureId, feature?.savedSettings || feature?.settings || {}),
      whatsapp: normalizeFeatureWhatsApp(feature?.whatsapp || feature?.activation || {}),
      savedWhatsApp: normalizeFeatureWhatsApp(
        feature?.savedWhatsApp
        || feature?.saved_whatsapp
        || feature?.whatsapp
        || feature?.activation
        || {},
      ),
    };
  });
  const settings = { ...DEFAULT_SETTINGS, ...(saved.settings || {}) };
  const simulator = normalizeSimulatorState(savedSimulator, savedPrompt);
  const agent = normalizeAgentWorkspace(saved.agent || {});

  if (!settings.workspaceName || isLegacyWorkspaceName(settings.workspaceName)) {
    settings.workspaceName = DEFAULT_SETTINGS.workspaceName;
  }

  if (didMigrateLegacyDescription) {
    persistJson(getClientKey(email), {
      ...saved,
      profile,
      settings,
      features,
      simulator,
      agent,
    });
  }

  return {
    profile,
    settings,
    features,
    simulator,
    agent,
  };
}

function createAgentId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function createAgentMessage(role, text, metadata = {}) {
  const messageMetadata = metadata && typeof metadata === "object" ? { ...metadata } : {};
  messageMetadata.kind = String(messageMetadata.kind || (role === "user" ? "user" : "text"));
  messageMetadata.actions = Array.isArray(messageMetadata.actions)
    ? messageMetadata.actions.map((action) => ({ ...action }))
    : [];
  return {
    id: createAgentId("agent-message"),
    role: role === "user" ? "user" : "assistant",
    text: String(text || "").trim(),
    createdAt: new Date().toISOString(),
    metadata: messageMetadata,
  };
}

function normalizeAgentTextItem(value, fallback = "") {
  return String(value || fallback).trim();
}

function normalizeAgentObjectItem(value = {}) {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
}

function normalizeAgentFieldValues(value = {}) {
  const source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const fields = {};
  for (const [rawKey, rawValue] of Object.entries(source)) {
    const key = normalizeAgentProposalFieldKey(rawKey);
    const fieldValue = normalizeAgentTextItem(rawValue, "").slice(0, 400).trim();
    if (key && fieldValue) {
      fields[key] = fieldValue;
    }
  }
  return fields;
}

function normalizeAgentSkillItem(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  const label = normalizeAgentTextItem(source.label || source.name, "Skill");
  return {
    label,
    detail: normalizeAgentTextItem(source.detail || source.description || source.purpose, ""),
  };
}

function normalizeAgentHelperDraft(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  return {
    name: normalizeAgentTextItem(source.name, "Helper agent"),
    purpose: normalizeAgentTextItem(source.purpose || source.description, "Help complete the approved task."),
  };
}

function normalizeAgentMessage(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  const text = normalizeAgentTextItem(source.text || source.content, "");
  if (!text) {
    return null;
  }

  const metadata = source.metadata && typeof source.metadata === "object" ? { ...source.metadata } : {};
  metadata.kind = String(metadata.kind || (source.role === "user" ? "user" : "text"));
  metadata.actions = Array.isArray(metadata.actions)
    ? metadata.actions
      .filter((action) => action && typeof action === "object")
      .map((action) => ({
        id: String(action.id || "").trim(),
        label: String(action.label || "").trim(),
        value: String(action.value || action.label || "").trim(),
        tone: String(action.tone || "secondary").trim(),
      }))
      .filter((action) => action.id && action.label)
    : [];

  return {
    id: normalizeAgentTextItem(source.id, createAgentId("agent-message")),
    role: source.role === "user" ? "user" : "assistant",
    text,
    createdAt: normalizeAgentTextItem(source.createdAt || source.created_at, new Date().toISOString()),
    metadata,
  };
}

function normalizeAgentProposal(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  const title = normalizeAgentTextItem(source.title, "Task plan");
  const summary = normalizeAgentTextItem(source.summary, "");
  if (!title && !summary) {
    return null;
  }

  const proposal = {
    id: normalizeAgentTextItem(source.id, createAgentId("agent-proposal")),
    type: normalizeAgentTextItem(source.type, "custom"),
    requestText: normalizeAgentTextItem(source.requestText || source.request_text, ""),
    title,
    summary,
    response: normalizeAgentTextItem(source.response, ""),
    relatedFeatureId: normalizeAgentTextItem(source.relatedFeatureId || source.related_feature_id, ""),
    primaryActionLabel: normalizeAgentTextItem(source.primaryActionLabel || source.primary_action_label, "Approve plan"),
    setupActionLabel: normalizeAgentTextItem(source.setupActionLabel || source.setup_action_label, "Open setup"),
    missingCredential: normalizeAgentTextItem(source.missingCredential || source.missing_credential, ""),
    status: normalizeAgentTextItem(source.status, source.approved ? "approved" : "needs-approval"),
    approved: Boolean(source.approved),
    revision: Math.max(1, Number(source.revision || 1)),
    createdAt: normalizeAgentTextItem(source.createdAt || source.created_at, new Date().toISOString()),
    updatedAt: normalizeAgentTextItem(source.updatedAt || source.updated_at, source.createdAt || source.created_at || new Date().toISOString()),
    approvedAt: normalizeAgentTextItem(source.approvedAt || source.approved_at, ""),
    details: normalizeAgentObjectItem(source.details),
    fields: normalizeAgentFieldValues(source.fields || source.field_values || source.fieldValues),
    executionPlan: normalizeAgentObjectItem(source.executionPlan || source.execution_plan),
    skills: Array.isArray(source.skills) ? source.skills.map(normalizeAgentSkillItem).filter(Boolean) : [],
    helpers: Array.isArray(source.helpers) ? source.helpers.map(normalizeAgentHelperDraft).filter(Boolean) : [],
    questions: Array.isArray(source.questions)
      ? source.questions.map((question) => normalizeAgentTextItem(question, "")).filter(Boolean)
      : [],
    questionKeys: Array.isArray(source.questionKeys || source.question_keys)
      ? (source.questionKeys || source.question_keys).map((questionKey) => normalizeAgentTextItem(questionKey, "")).filter(Boolean)
      : [],
    answers: Array.isArray(source.answers)
      ? source.answers.map((answer) => normalizeAgentTextItem(answer, "")).filter(Boolean)
      : [],
    questionIndex: Math.max(0, Number(source.questionIndex || source.question_index || 0)),
    alternatives: Array.isArray(source.alternatives)
      ? source.alternatives.map((alternative) => normalizeAgentTextItem(alternative, "")).filter(Boolean)
      : [],
  };
  syncAgentProposalFieldCompatibility(proposal);
  return proposal;
}

function normalizeAgentHelper(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  const name = normalizeAgentTextItem(source.name, "Helper agent");
  return {
    id: normalizeAgentTextItem(source.id, createAgentId("agent-helper")),
    name,
    purpose: normalizeAgentTextItem(source.purpose, "Help complete the approved task."),
    status: normalizeAgentTextItem(source.status, "Ready"),
    sourceProposalId: normalizeAgentTextItem(source.sourceProposalId || source.source_proposal_id, ""),
    createdAt: normalizeAgentTextItem(source.createdAt || source.created_at, new Date().toISOString()),
  };
}

function createDefaultAgentWorkspace() {
  return {
    messages: [],
    proposals: [],
    helpers: [],
    activeProposalId: "",
  };
}

function normalizeAgentWorkspace(agent = {}) {
  const source = agent && typeof agent === "object" ? agent : {};
  const fallback = createDefaultAgentWorkspace();
  const messages = Array.isArray(source.messages)
    ? source.messages
      .map(normalizeAgentMessage)
      .filter((message) => message && message.metadata?.kind !== "welcome")
      .slice(-AGENT_MAX_MESSAGES)
    : [];
  const proposals = Array.isArray(source.proposals)
    ? source.proposals.map(normalizeAgentProposal).filter(Boolean)
    : [];
  const helpers = Array.isArray(source.helpers)
    ? source.helpers.map(normalizeAgentHelper).filter(Boolean)
    : [];
  const activeProposalId = normalizeAgentTextItem(source.activeProposalId || source.active_proposal_id, "")
    || proposals[proposals.length - 1]?.id
    || "";

  return {
    messages: messages.length ? messages : fallback.messages,
    proposals,
    helpers,
    activeProposalId,
  };
}

function normalizeAccountProfile(profile = {}) {
  const source = profile && typeof profile === "object" ? profile : {};
  return {
    businessSummary: String(source.businessSummary || "").trim(),
    customerNotes: String(source.customerNotes || "").trim(),
    assistantGuidance: String(source.assistantGuidance || "").trim(),
  };
}

function normalizeFeaturePricing(pricing = {}) {
  const source = pricing && typeof pricing === "object" ? pricing : {};
  return {
    minimumMonthlyCharge: Math.max(
      0,
      Number(
        source.minimumMonthlyCharge
        ?? source.minimum_monthly_charge
        ?? source.minimumCharge
        ?? source.minimum_charge
        ?? DEFAULT_FEATURE_PRICING.minimumMonthlyCharge,
      ),
    ) || DEFAULT_FEATURE_PRICING.minimumMonthlyCharge,
  };
}

function normalizeFeatureRequirements(requirements = {}) {
  const source = requirements && typeof requirements === "object" ? requirements : {};
  return {
    requiresWhatsAppConnection: Boolean(
      source.requiresWhatsAppConnection
      ?? source.requires_whatsapp_connection
      ?? false,
    ),
    requiresScheduledMonitorConfig: Boolean(
      source.requiresScheduledMonitorConfig
      ?? source.requires_scheduled_monitor_config
      ?? false,
    ),
  };
}

function normalizeFeatureBilling(billing = {}) {
  const source = billing && typeof billing === "object" ? billing : {};
  return {
    required: Boolean(source.required ?? source.billingRequired ?? source.billing_required ?? false),
    provider: String(source.provider || source.billingProvider || source.billing_provider || "").trim(),
    storeId: String(source.storeId || source.billingStoreId || source.billing_store_id || "").trim(),
    productId: String(source.productId || source.billingProductId || source.billing_product_id || "").trim(),
    variantId: String(source.variantId || source.billingVariantId || source.billing_variant_id || "").trim(),
  };
}

function normalizeFeaturePaymentStatus(paymentStatus = null) {
  if (!paymentStatus || typeof paymentStatus !== "object") {
    return null;
  }

  return {
    featureId: String(paymentStatus.featureId || paymentStatus.feature_id || "").trim(),
    provider: String(paymentStatus.provider || "").trim(),
    billingRequired: Boolean(paymentStatus.billingRequired ?? paymentStatus.billing_required ?? false),
    isPayingCustomer: Boolean(paymentStatus.isPayingCustomer),
    isEntitled: Boolean(paymentStatus.isEntitled ?? paymentStatus.isPayingCustomer),
    subscriptionStatus: String(paymentStatus.subscriptionStatus || "").trim(),
    entitlementStatus: String(paymentStatus.entitlementStatus || paymentStatus.subscriptionStatus || "").trim(),
    checkoutRequired: Boolean(paymentStatus.checkoutRequired ?? paymentStatus.checkout_required ?? false),
    checkoutUrl: String(paymentStatus.checkoutUrl || paymentStatus.checkout_url || "").trim(),
    customerPortalUrl: String(paymentStatus.customerPortalUrl || paymentStatus.customer_portal_url || "").trim(),
    hasAnyActiveSubscription: Boolean(
      paymentStatus.hasAnyActiveSubscription
      ?? paymentStatus.has_any_active_subscription
      ?? false,
    ),
    message: String(paymentStatus.message || "").trim(),
  };
}

function normalizeFeatureSetupStatus(setupStatus = null) {
  const source = setupStatus && typeof setupStatus === "object" ? setupStatus : {};
  const rawIssues = Array.isArray(source.issues) ? source.issues : [];
  return {
    required: Boolean(source.required ?? false),
    ready: Boolean(source.ready ?? !source.required),
    requirementKey: String(source.requirementKey || source.requirement_key || "").trim(),
    message: String(source.message || "").trim(),
    settingsSavedAt: String(source.settingsSavedAt || source.settings_saved_at || "").trim(),
    lastRunAt: String(source.lastRunAt || source.last_run_at || "").trim(),
    lastRunStatus: String(source.lastRunStatus || source.last_run_status || "").trim(),
    nextRunAt: String(source.nextRunAt || source.next_run_at || "").trim(),
    issues: rawIssues
      .filter((issue) => issue && typeof issue === "object")
      .map((issue) => ({
        field: String(issue.field || "").trim(),
        message: String(issue.message || "").trim(),
      })),
  };
}

function normalizeFeatureWhatsAppMetadata(metadata = null) {
  const source = metadata && typeof metadata === "object" ? metadata : {};
  return {
    lastInboundAt: String(source.lastInboundAt || source.last_inbound_at || "").trim(),
    lastInboundSenderName: String(source.lastInboundSenderName || source.last_inbound_sender_name || "").trim(),
    lastInboundSenderWaId: String(source.lastInboundSenderWaId || source.last_inbound_sender_wa_id || "").trim(),
    lastInboundPreview: String(source.lastInboundPreview || source.last_inbound_preview || "").trim(),
    lastInboundMessageId: String(source.lastInboundMessageId || source.last_inbound_message_id || "").trim(),
    lastInboundPhoneNumberId: String(source.lastInboundPhoneNumberId || source.last_inbound_phone_number_id || "").trim(),
    lastApprovalCreatedAt: String(source.lastApprovalCreatedAt || source.last_approval_created_at || "").trim(),
    lastApprovalId: String(source.lastApprovalId || source.last_approval_id || "").trim(),
    lastOwnerNotificationAt: String(source.lastOwnerNotificationAt || source.last_owner_notification_at || "").trim(),
    lastOwnerNotificationStatus: String(source.lastOwnerNotificationStatus || source.last_owner_notification_status || "").trim(),
    lastOwnerNotificationError: String(source.lastOwnerNotificationError || source.last_owner_notification_error || "").trim(),
    lastOwnerNotificationMessageId: String(source.lastOwnerNotificationMessageId || source.last_owner_notification_message_id || "").trim(),
  };
}

function normalizePendingAccessToken(value) {
  const token = String(value || "").trim();
  return token === SAVED_ACCESS_TOKEN_FIELD_VALUE ? "" : token;
}

function getAccessTokenDisplayValue(whatsapp = {}) {
  const accessToken = normalizePendingAccessToken(whatsapp.access_token);
  if (accessToken) {
    return accessToken;
  }

  return whatsapp.workspace_access_token_configured ? SAVED_ACCESS_TOKEN_FIELD_VALUE : "";
}

function normalizeFeatureWhatsApp(config = {}) {
  const source = config && typeof config === "object" ? config : {};
  const businessAccountId = String(source.business_account_id || source.businessAccountId || "").trim();
  const phoneNumberId = String(source.phone_number_id || source.phoneNumberId || "").trim();
  const accessToken = normalizePendingAccessToken(source.access_token || source.accessToken || "");

  return {
    business_account_id: businessAccountId,
    phone_number_id: phoneNumberId,
    access_token: accessToken,
    access_token_configured: Boolean(source.access_token_configured ?? source.accessTokenConfigured ?? accessToken),
    workspace_access_token_configured: Boolean(source.workspace_access_token_configured ?? source.workspaceAccessTokenConfigured ?? accessToken),
    backend_access_token_configured: Boolean(source.backend_access_token_configured ?? source.backendAccessTokenConfigured ?? false),
    owner_wa_id: String(source.owner_wa_id || source.ownerWaId || "").trim(),
    connection_status: String(source.connection_status || source.connectionStatus || "not_connected").trim() || "not_connected",
    display_phone_number: String(source.display_phone_number || source.displayPhoneNumber || "").trim(),
    verified_name: String(source.verified_name || source.verifiedName || "").trim(),
    connected_at: String(source.connected_at || source.connectedAt || "").trim(),
    last_tested_at: String(source.last_tested_at || source.lastTestedAt || "").trim(),
    configured: Boolean(source.configured ?? false),
    live_send_enabled: Boolean(source.live_send_enabled ?? source.liveSendEnabled ?? false),
    webhook_url: String(source.webhook_url || source.webhookUrl || "").trim(),
    metadata: normalizeFeatureWhatsAppMetadata(source.metadata || {}),
  };
}

function normalizeMonitorWatchItems(value) {
  const rawItems = Array.isArray(value)
    ? value
    : splitLines(String(value || "").replace(/;/g, "\n"));
  const normalizedItems = [];
  const seen = new Set();

  for (const item of rawItems) {
    const cleaned = String(item || "").replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim();
    if (!cleaned) {
      continue;
    }

    const key = cleaned.toLowerCase();
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    normalizedItems.push(cleaned);
  }

  return normalizedItems;
}

function normalizeMonitorManualOnly(value, fallback = DEFAULT_MONITOR_SETTINGS.manualOnly) {
  if (typeof value === "boolean") {
    return value;
  }
  const text = String(value ?? "").trim().toLowerCase();
  if (["1", "true", "yes", "on", "manual", "manual_only", "on_demand", "on-demand"].includes(text)) {
    return true;
  }
  if (["0", "false", "no", "off", "scheduled", "recurring"].includes(text)) {
    return false;
  }
  return Boolean(fallback);
}

function normalizeMonitorIntervalDays(value, fallback = DEFAULT_MONITOR_SETTINGS.intervalDays) {
  const parsedFallback = Number.parseInt(fallback, 10);
  const safeFallback = Number.isFinite(parsedFallback)
    ? Math.min(MONITOR_INTERVAL_DAYS_MAX, Math.max(MONITOR_INTERVAL_DAYS_MIN, parsedFallback))
    : DEFAULT_MONITOR_SETTINGS.intervalDays;
  const intervalDays = Number.parseInt(value, 10);

  return Number.isFinite(intervalDays)
    ? Math.min(MONITOR_INTERVAL_DAYS_MAX, Math.max(MONITOR_INTERVAL_DAYS_MIN, intervalDays))
    : safeFallback;
}

function normalizeMonitorIntervalMinutes(value, fallback = DEFAULT_MONITOR_SETTINGS.intervalMinutes) {
  const parsedFallback = Number.parseInt(fallback, 10);
  const safeFallback = Number.isFinite(parsedFallback) && parsedFallback > 0
    ? Math.min(60 * 24, Math.max(5, parsedFallback))
    : 0;
  const intervalMinutes = Number.parseInt(value, 10);

  return Number.isFinite(intervalMinutes) && intervalMinutes > 0
    ? Math.min(60 * 24, Math.max(5, intervalMinutes))
    : safeFallback;
}

function coerceMonitorScheduleTime(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(\d{1,2})(?::(\d{1,2}))?$/);
  if (!match) {
    return "";
  }

  const hour = Number.parseInt(match[1], 10);
  const minute = Number.parseInt(match[2] || "0", 10);
  if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return "";
  }

  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function normalizeMonitorScheduleTime(value, fallback = DEFAULT_MONITOR_SETTINGS.scheduleTimeLocal) {
  return coerceMonitorScheduleTime(value) || coerceMonitorScheduleTime(fallback) || "";
}

function normalizeMonitorScheduleTimezone(value, fallback = "") {
  const fallbackText = String(fallback || "").trim();
  const text = String(value || "").trim();
  if (!text) {
    return fallbackText;
  }

  try {
    new Intl.DateTimeFormat(undefined, { timeZone: text }).format(new Date());
    return text;
  } catch {
    return fallbackText;
  }
}

function getWorkspaceTimeZone() {
  return normalizeMonitorScheduleTimezone(clientState?.settings?.timezone || defaultTimeZone(), "UTC") || "UTC";
}

function formatMonitorScheduleTimeFromMoment(value, timeZone = getWorkspaceTimeZone()) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }

  const formatter = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: normalizeMonitorScheduleTimezone(timeZone, getWorkspaceTimeZone()) || undefined,
  });
  const parts = formatter.formatToParts(parsed);
  const hour = parts.find((part) => part.type === "hour")?.value || "";
  const minute = parts.find((part) => part.type === "minute")?.value || "";
  return hour && minute ? `${hour}:${minute}` : "";
}

function getMonitorScheduleTimezone(feature = getSelectedFeature()) {
  const settings = isMonitorFeature(feature) ? getSelectedFeatureSettings(feature) : DEFAULT_MONITOR_SETTINGS;
  return normalizeMonitorScheduleTimezone(settings.scheduleTimezone, getWorkspaceTimeZone()) || getWorkspaceTimeZone();
}

function getMonitorScheduleTime(feature = getSelectedFeature()) {
  if (!feature || !isMonitorFeature(feature)) {
    return DEFAULT_MONITOR_SCHEDULE_TIME;
  }

  const settings = getSelectedFeatureSettings(feature);
  if (settings.manualOnly) {
    return "";
  }
  const explicitTime = normalizeMonitorScheduleTime(settings.scheduleTimeLocal);
  if (explicitTime) {
    return explicitTime;
  }

  const derivedTime = formatMonitorScheduleTimeFromMoment(
    feature.nextRunAt || feature.settingsSavedAt || feature.setupStatus?.nextRunAt || "",
    getMonitorScheduleTimezone(feature),
  );
  return derivedTime || DEFAULT_MONITOR_SCHEDULE_TIME;
}

function buildMonitorSettingsForSave(feature = getSelectedFeature(), settings = getSelectedFeatureSettings(feature)) {
  const source = settings && typeof settings === "object" ? settings : {};
  const manualOnly = normalizeMonitorManualOnly(source.manualOnly);
  const scheduleTimeLocal = normalizeMonitorScheduleTime(
    manualOnly ? "" : source.scheduleTimeLocal,
    manualOnly ? "" : getMonitorScheduleTime(feature),
  );
  const scheduleTimezone = !manualOnly && scheduleTimeLocal
    ? normalizeMonitorScheduleTimezone(source.scheduleTimezone, getMonitorScheduleTimezone(feature))
    : "";

  return normalizeFeatureMonitorSettings({
    ...source,
    manualOnly,
    runMode: manualOnly ? "manual" : "recurring",
    scheduleTimeLocal,
    scheduleTimezone,
  });
}

function normalizeFeatureModel(value, fallback = DEFAULT_TOOL_MODEL) {
  const normalizedValue = String(value || "").trim();
  const normalizedFallback = String(fallback || DEFAULT_TOOL_MODEL).trim() || DEFAULT_TOOL_MODEL;
  const availableIds = new Set(DEFAULT_TOOL_MODEL_OPTIONS.map((option) => option.id));

  if (normalizedValue && availableIds.has(normalizedValue)) {
    return normalizedValue;
  }
  if (availableIds.has(normalizedFallback)) {
    return normalizedFallback;
  }
  return DEFAULT_TOOL_MODEL;
}

function normalizeFeatureSettings(settings = {}) {
  const source = settings && typeof settings === "object" ? settings : {};
  return {
    model: normalizeFeatureModel(source.model),
  };
}

function normalizeWhatsAppToolDeliveryChannels(value, fallback = DEFAULT_WHATSAPP_TOOL_SETTINGS.deliveryChannels) {
  const hasArrayFallback = Array.isArray(fallback);
  const fallbackChannels = hasArrayFallback ? fallback : ["whatsapp"];
  let rawChannels = [];
  if (Array.isArray(value)) {
    rawChannels = value;
  } else {
    const text = String(value || "").trim().toLowerCase();
    if (["both", "all", "whatsapp+telegram", "whatsapp_telegram"].includes(text)) {
      rawChannels = ["whatsapp", "telegram"];
    } else if (text) {
      rawChannels = text.replace(/\+/g, ",").split(",");
    }
  }

  const channels = [];
  for (const channel of rawChannels) {
    const normalized = String(channel || "").trim().toLowerCase();
    if (["whatsapp", "telegram", "portal"].includes(normalized) && !channels.includes(normalized)) {
      channels.push(normalized);
    }
  }

  if (Array.isArray(value)) {
    return channels;
  }
  if (channels.length) {
    return channels;
  }
  const normalizedFallback = fallbackChannels.filter((channel) => ["whatsapp", "telegram", "portal"].includes(channel));
  return normalizedFallback.length ? normalizedFallback : hasArrayFallback ? [] : ["whatsapp"];
}

function normalizeWhatsAppToolDeliverySettings(settings = {}) {
  const source = settings && typeof settings === "object" ? settings : {};
  const deliveryChannels = normalizeWhatsAppToolDeliveryChannels(
    source.deliveryChannels || source.delivery_channels || source.deliveryChannel || source.delivery_channel,
  );
  return {
    deliveryChannels,
    telegramChatId: String(source.telegramChatId || source.telegram_chat_id || "").trim(),
  };
}

function normalizeFeatureWhatsAppToolSettings(settings = {}) {
  const source = settings && typeof settings === "object" ? settings : {};
  return {
    ...normalizeFeatureSettings(source),
    ...normalizeWhatsAppToolDeliverySettings(source),
  };
}

function normalizeFeatureWhatsAppReplyAssistantSettings(settings = {}) {
  const normalized = normalizeFeatureWhatsAppToolSettings(settings);
  const source = settings && typeof settings === "object" ? settings : {};
  const hasExplicitDelivery = ["deliveryChannels", "delivery_channels", "deliveryChannel", "delivery_channel"]
    .some((key) => Object.prototype.hasOwnProperty.call(source, key));
  return {
    ...normalized,
    deliveryChannels: hasExplicitDelivery ? normalized.deliveryChannels : ["portal"],
  };
}

function getWhatsAppDeliverySelection(settings = {}) {
  const channels = getWhatsAppToolDeliveryChannels(settings);
  const hasWhatsApp = channels.includes("whatsapp");
  const hasTelegram = channels.includes("telegram");
  if (hasWhatsApp && hasTelegram) {
    return "both";
  }
  if (hasTelegram) {
    return "telegram";
  }
  return hasWhatsApp ? "whatsapp" : "";
}

function normalizeFeatureMonitorSettings(settings = {}) {
  const source = settings && typeof settings === "object" ? settings : {};
  const deliveryChannel = String(source.deliveryChannel || DEFAULT_MONITOR_SETTINGS.deliveryChannel).trim().toLowerCase();
  const runMode = String(source.runMode || source.run_mode || source.mode || "").trim().toLowerCase();
  const manualRunMode = ["manual", "manual_only", "on_demand", "on-demand"].includes(runMode);
  const recurringRunMode = ["scheduled", "recurring", "auto", "automatic", "background"].includes(runMode);
  const hasManualOnlySetting = Object.prototype.hasOwnProperty.call(source, "manualOnly")
    || Object.prototype.hasOwnProperty.call(source, "manual_only");
  const manualOnlyValue = Object.prototype.hasOwnProperty.call(source, "manualOnly")
    ? source.manualOnly
    : source.manual_only;
  const manualOnly = manualRunMode
    ? true
    : recurringRunMode
      ? false
      : normalizeMonitorManualOnly(
        hasManualOnlySetting && normalizeMonitorManualOnly(manualOnlyValue, false) ? manualOnlyValue : true,
        true,
      );
  const intervalMinutes = normalizeMonitorIntervalMinutes(source.intervalMinutes || source.interval_minutes);
  const intervalDays = Number.parseInt(source.intervalDays, 10);
  const legacyCadence = String(source.cadence || "").trim().toLowerCase();
  const scheduleTimeLocal = manualOnly || intervalMinutes
    ? ""
    : normalizeMonitorScheduleTime(source.scheduleTimeLocal || source.scheduleTime || "");
  const scheduleTimezone = !manualOnly && scheduleTimeLocal
    ? normalizeMonitorScheduleTimezone(source.scheduleTimezone || source.scheduleTimeZone || "", defaultTimeZone())
    : intervalMinutes
      ? ""
      : normalizeMonitorScheduleTimezone(source.scheduleTimezone || source.scheduleTimeZone || "", "");

  return {
    ...normalizeFeatureSettings(source),
    watchItems: normalizeMonitorWatchItems(source.watchItems || source.searchPrompt || ""),
    manualOnly,
    runMode: manualOnly ? "manual" : "recurring",
    intervalMinutes,
    intervalDays: Number.isFinite(intervalDays)
      ? normalizeMonitorIntervalDays(intervalDays)
      : legacyCadence === "daily"
        ? 1
        : legacyCadence === "weekly"
          ? 7
          : legacyCadence === "monthly"
            ? 30
            : DEFAULT_MONITOR_SETTINGS.intervalDays,
    scheduleTimeLocal,
    scheduleTimezone,
    deliveryChannel: ["email", "telegram", "whatsapp"].includes(deliveryChannel) ? deliveryChannel : DEFAULT_MONITOR_SETTINGS.deliveryChannel,
    telegramChatId: String(source.telegramChatId || "").trim(),
  };
}

function normalizeReengagementInactivityUnit(value, fallback = DEFAULT_REENGAGEMENT_SETTINGS.inactivityUnit) {
  const text = String(value || "").trim().toLowerCase();
  const aliases = {
    m: "minutes",
    min: "minutes",
    mins: "minutes",
    minute: "minutes",
    minutes: "minutes",
    h: "hours",
    hr: "hours",
    hrs: "hours",
    hour: "hours",
    hours: "hours",
    d: "days",
    day: "days",
    days: "days",
    month: "months",
    months: "months",
  };
  const normalized = aliases[text] || "";
  if (normalized) {
    return normalized;
  }
  return aliases[String(fallback || "").trim().toLowerCase()] || DEFAULT_REENGAGEMENT_SETTINGS.inactivityUnit;
}

function normalizeReengagementInactivityValue(value, fallback = DEFAULT_REENGAGEMENT_SETTINGS.inactivityValue) {
  const parsedFallback = Number.parseInt(fallback, 10);
  const safeFallback = Number.isFinite(parsedFallback)
    ? Math.min(REENGAGEMENT_INACTIVITY_VALUE_MAX, Math.max(REENGAGEMENT_INACTIVITY_VALUE_MIN, parsedFallback))
    : DEFAULT_REENGAGEMENT_SETTINGS.inactivityValue;
  const parsedValue = Number.parseInt(value, 10);
  return Number.isFinite(parsedValue)
    ? Math.min(REENGAGEMENT_INACTIVITY_VALUE_MAX, Math.max(REENGAGEMENT_INACTIVITY_VALUE_MIN, parsedValue))
    : safeFallback;
}

function normalizeFeatureReengagementSettings(settings = {}) {
  const source = settings && typeof settings === "object" ? settings : {};
  const legacyMonths = source.inactivityMonths || source.inactivity_months;
  const inactivityUnit = normalizeReengagementInactivityUnit(
    source.inactivityUnit || source.inactivity_unit || (legacyMonths ? "months" : DEFAULT_REENGAGEMENT_SETTINGS.inactivityUnit),
  );
  const inactivityValue = source.inactivityValue || legacyMonths || DEFAULT_REENGAGEMENT_SETTINGS.inactivityValue;
  const scheduleTimeLocal = normalizeMonitorScheduleTime(
    source.scheduleTimeLocal || source.scheduleTime || "",
    DEFAULT_REENGAGEMENT_SETTINGS.scheduleTimeLocal,
  );
  const scheduleTimezone = scheduleTimeLocal
    ? normalizeMonitorScheduleTimezone(source.scheduleTimezone || source.scheduleTimeZone || "", defaultTimeZone())
    : normalizeMonitorScheduleTimezone(source.scheduleTimezone || source.scheduleTimeZone || "", "");

  return {
    ...normalizeFeatureSettings(source),
    ...normalizeWhatsAppToolDeliverySettings(source),
    intervalDays: normalizeMonitorIntervalDays(source.intervalDays, DEFAULT_REENGAGEMENT_SETTINGS.intervalDays),
    scheduleTimeLocal,
    scheduleTimezone,
    inactivityValue: normalizeReengagementInactivityValue(inactivityValue),
    inactivityUnit,
    maxContextMessages: Math.min(
      DEFAULT_REENGAGEMENT_SETTINGS.maxContextMessages,
      Math.max(1, Number.parseInt(source.maxContextMessages, 10) || DEFAULT_REENGAGEMENT_SETTINGS.maxContextMessages),
    ),
  };
}

function normalizeSettingsForFeature(featureId, settings = {}) {
  if (featureId === MONITOR_FEATURE_ID) {
    return normalizeFeatureMonitorSettings(settings);
  }
  if (featureId === REENGAGEMENT_FEATURE_ID) {
    return normalizeFeatureReengagementSettings(settings);
  }
  if (featureId === WHATSAPP_REPLY_ASSISTANT_FEATURE_ID) {
    return normalizeFeatureWhatsAppReplyAssistantSettings(settings);
  }
  return normalizeFeatureSettings(settings);
}

function getReengagementScheduleTimezone(feature = getSelectedFeature()) {
  const settings = isReengagementFeature(feature) ? getSelectedFeatureSettings(feature) : DEFAULT_REENGAGEMENT_SETTINGS;
  return normalizeMonitorScheduleTimezone(settings.scheduleTimezone, getWorkspaceTimeZone()) || getWorkspaceTimeZone();
}

function getReengagementScheduleTime(feature = getSelectedFeature()) {
  if (!feature || !isReengagementFeature(feature)) {
    return DEFAULT_REENGAGEMENT_SETTINGS.scheduleTimeLocal;
  }

  const settings = getSelectedFeatureSettings(feature);
  const explicitTime = normalizeMonitorScheduleTime(settings.scheduleTimeLocal);
  if (explicitTime) {
    return explicitTime;
  }

  const derivedTime = formatMonitorScheduleTimeFromMoment(
    feature.nextRunAt || feature.settingsSavedAt || feature.setupStatus?.nextRunAt || "",
    getReengagementScheduleTimezone(feature),
  );
  return derivedTime || DEFAULT_REENGAGEMENT_SETTINGS.scheduleTimeLocal;
}

function buildReengagementSettingsForSave(feature = getSelectedFeature(), settings = getSelectedFeatureSettings(feature)) {
  const source = settings && typeof settings === "object" ? settings : {};
  const scheduleTimeLocal = normalizeMonitorScheduleTime(
    source.scheduleTimeLocal,
    getReengagementScheduleTime(feature),
  );
  const scheduleTimezone = scheduleTimeLocal
    ? normalizeMonitorScheduleTimezone(source.scheduleTimezone, getReengagementScheduleTimezone(feature))
    : "";

  return normalizeFeatureReengagementSettings({
    ...source,
    scheduleTimeLocal,
    scheduleTimezone,
    maxContextMessages: DEFAULT_REENGAGEMENT_SETTINGS.maxContextMessages,
  });
}

function buildSettingsForSave(feature = getSelectedFeature(), settings = getSelectedFeatureSettings(feature)) {
  if (isMonitorFeature(feature)) {
    return buildMonitorSettingsForSave(feature, settings);
  }
  if (isReengagementFeature(feature)) {
    return buildReengagementSettingsForSave(feature, settings);
  }
  if (isWhatsAppReplyAssistantFeature(feature)) {
    return normalizeFeatureWhatsAppReplyAssistantSettings(settings);
  }
  return normalizeFeatureSettings(settings);
}

function getFeaturePricing(feature = getSelectedFeature()) {
  return normalizeFeaturePricing(feature?.pricing || DEFAULT_FEATURE_PRICING);
}

function buildFeaturePitch(feature = getSelectedFeature()) {
  if (feature?.id === MONITOR_FEATURE_ID) {
    return "Scheduled Web Monitor keeps watch for the dates, opportunities, and public updates that matter to this client. It turns a plain-language brief into recurring web research, then sends concise alerts with source links so the right person hears about conferences, holidays, deadlines, or niche developments before they slip by.";
  }

  if (feature?.id === REENGAGEMENT_FEATURE_ID) {
    return "WhatsApp Re-engagement Assistant makes it easy to follow up with past customers without starting from scratch. It prepares outreach messages you can review and send, helping you restart conversations, stay top of mind, and bring more opportunities back into your pipeline.";
  }

  return "WhatsApp Reply Assistant helps you respond faster without sounding rushed. It turns incoming messages into clear, polished reply drafts that keep leads warm, reduce missed opportunities after hours, and make follow-up feel consistent and professional. You stay in control of every send while moving quicker, quoting with more confidence, and turning more conversations into booked work.";
}

function buildFeatureExample(feature = getSelectedFeature()) {
  const prompt = feature?.prompt || getSelectedPrompt();
  const scenario = SCENARIOS[prompt.scenario] ?? SCENARIOS.approval;
  const messages = Array.isArray(scenario.messages) && scenario.messages.length
    ? scenario.messages
    : [{ direction: "incoming", text: scenario.user }];
  return {
    sender: scenario.sender || "Customer",
    avatar: getInitialsFromName(scenario.sender || feature?.name || "WA"),
    meta: scenario.meta || "Recent lead",
    incoming: scenario.user,
    messages,
    outgoing: buildResponseText(prompt),
  };
}

function renderFeatureExampleMessages(example = {}) {
  if (!elements.featureStudioExampleMessage) {
    return;
  }

  elements.featureStudioExampleMessage.innerHTML = "";
  const messages = Array.isArray(example.messages) && example.messages.length
    ? example.messages
    : [{ direction: "incoming", text: example.incoming }];

  for (const message of messages) {
    const bubble = document.createElement("div");
    const direction = normalizeText(message?.direction).toLowerCase() === "outgoing" ? "outgoing" : "incoming";
    bubble.className = `bubble ${direction}`;
    bubble.textContent = String(message?.text || "");
    elements.featureStudioExampleMessage.append(bubble);
  }
}

function buildFeatureEditorHint(feature = getSelectedFeature()) {
  const pricing = getFeaturePricing(feature);
  const accountMinimum = Math.max(DEFAULT_BILLING_MINIMUM, Number(pricing.minimumMonthlyCharge || 0) || 0);
  return `Open the editor before payment. This tool bills by usage, and your account has a ${formatCurrency(accountMinimum, "USD")} monthly minimum across all tools.`;
}

function buildWhatsAppConfigHint() {
  return "Connect the client's WhatsApp Business Platform account, then save the WABA ID, Phone Number ID, access token, and approval phone.";
}

function applyWhatsAppConnectionToFeatures(connection, options = {}) {
  const normalizedConnection = normalizeFeatureWhatsApp(connection || {});
  const setupComplete = Boolean(
    normalizedConnection.business_account_id
    && normalizedConnection.phone_number_id
    && normalizedConnection.access_token_configured
    && normalizedConnection.owner_wa_id
    && normalizedConnection.connection_status === "connected",
  );

  clientState.features = clientState.features.map((feature) => {
    if (!isWhatsAppFeature(feature)) {
      return feature;
    }

    return {
      ...feature,
      whatsapp: { ...normalizedConnection },
      savedWhatsApp: { ...normalizedConnection },
      setupComplete,
      status: feature.activated ? "active" : "non-active",
    };
  });

  if (options.persist !== false) {
    persistClientState();
  }
}

function buildClientFeatureFromServer(serverFeature = {}, existingFeature = null, index = 0) {
  const featureId = String(serverFeature?.featureId || serverFeature?.id || existingFeature?.id || `feature-${index + 1}`).trim();
  const channel = String(serverFeature?.channel || existingFeature?.channel || "Web").trim() || "Web";
  const activated = Boolean(
    serverFeature?.isActive
    ?? serverFeature?.activated
    ?? existingFeature?.activated
  );
  const setupComplete = Boolean(
    serverFeature?.setupComplete
    ?? serverFeature?.setup_complete
    ?? existingFeature?.setupComplete
    ?? activated
  );
  const requirements = normalizeFeatureRequirements(serverFeature?.requirements || existingFeature?.requirements || {});
  const billing = normalizeFeatureBilling(serverFeature?.billing || existingFeature?.billing || {});
  const prompt = normalizePrompt(
    serverFeature?.prompt || existingFeature?.prompt || {},
    serverFeature?.prompt || DEFAULT_PROMPT,
  );
  const savedPrompt = normalizePrompt(serverFeature?.prompt || existingFeature?.savedPrompt || existingFeature?.prompt || {}, serverFeature?.prompt || DEFAULT_PROMPT);
  const pricing = normalizeFeaturePricing(serverFeature?.pricing || existingFeature?.pricing || {});
  const paymentStatus = normalizeFeaturePaymentStatus(serverFeature?.paymentStatus || existingFeature?.paymentStatus || null);
  const setupStatus = normalizeFeatureSetupStatus(serverFeature?.setupStatus || serverFeature?.setup_status || existingFeature?.setupStatus || null);
  const metadata = serverFeature?.metadata && typeof serverFeature.metadata === "object"
    ? { ...serverFeature.metadata }
    : existingFeature?.metadata && typeof existingFeature.metadata === "object"
      ? { ...existingFeature.metadata }
      : {};
  const assignment = serverFeature?.assignment && typeof serverFeature.assignment === "object"
    ? { ...serverFeature.assignment }
    : existingFeature?.assignment && typeof existingFeature.assignment === "object"
      ? { ...existingFeature.assignment }
      : {};
  const whatsapp = isWhatsAppFeature({ channel })
    ? normalizeFeatureWhatsApp(existingFeature?.whatsapp || serverFeature?.whatsapp || {})
    : normalizeFeatureWhatsApp({});
  const savedWhatsApp = isWhatsAppFeature({ channel })
    ? normalizeFeatureWhatsApp(existingFeature?.savedWhatsApp || existingFeature?.whatsapp || serverFeature?.whatsapp || {})
    : normalizeFeatureWhatsApp({});
  const settings = normalizeSettingsForFeature(featureId, serverFeature?.settings || existingFeature?.settings || {});
  const savedSettings = normalizeSettingsForFeature(
    featureId,
    serverFeature?.settings || existingFeature?.savedSettings || existingFeature?.settings || {},
  );

  return {
    id: featureId,
    name: String(serverFeature?.name || serverFeature?.featureName || existingFeature?.name || `Tool ${index + 1}`).trim(),
    description: String(serverFeature?.description || existingFeature?.description || "").trim(),
    channel,
    mode: String(serverFeature?.mode || existingFeature?.mode || "Default").trim() || "Default",
    status: activated ? "active" : "non-active",
    activated,
    setupComplete,
    launchUrl: String(serverFeature?.launchUrl || existingFeature?.launchUrl || DEFAULT_FEATURE_LAUNCH_URL).trim(),
    settingsSavedAt: String(serverFeature?.settingsSavedAt || setupStatus.settingsSavedAt || existingFeature?.settingsSavedAt || "").trim(),
    lastRunAt: String(serverFeature?.lastRunAt || setupStatus.lastRunAt || existingFeature?.lastRunAt || "").trim(),
    lastRunStatus: String(serverFeature?.lastRunStatus || setupStatus.lastRunStatus || existingFeature?.lastRunStatus || "").trim(),
    nextRunAt: String(serverFeature?.nextRunAt || setupStatus.nextRunAt || existingFeature?.nextRunAt || "").trim(),
    pricing,
    prompt,
    savedPrompt,
    requirements,
    billing,
    assignment,
    paymentStatus,
    setupStatus,
    metadata,
    settings,
    savedSettings,
    whatsapp,
    savedWhatsApp,
  };
}

function applyServerFeatureStates(features = [], options = {}) {
  const resetMissing = options.resetMissing === true;
  const serverFeatures = Array.isArray(features) ? features : [];
  const existingById = new Map(
    clientState.features
      .filter((feature) => feature && feature.id)
      .map((feature) => [feature.id, feature]),
  );
  const serverById = new Map();

  for (const feature of serverFeatures) {
    const featureId = String(feature?.featureId || feature?.feature_id || feature?.id || "").trim();
    if (featureId) {
      serverById.set(featureId, feature);
    }
  }

  let nextFeatures = [];
  if (resetMissing) {
    nextFeatures = serverFeatures
      .map((serverFeature, index) => buildClientFeatureFromServer(
        serverFeature,
        existingById.get(String(serverFeature?.featureId || serverFeature?.id || "").trim()) || null,
        index,
      ))
      .filter(Boolean);
  } else {
    const seenFeatureIds = new Set();
    nextFeatures = clientState.features.map((feature, index) => {
      const featureId = String(feature?.id || "").trim();
      const serverFeature = serverById.get(featureId);
      if (!serverFeature) {
        return feature;
      }
      seenFeatureIds.add(featureId);
      return buildClientFeatureFromServer(serverFeature, feature, index);
    });

    for (const serverFeature of serverFeatures) {
      const featureId = String(serverFeature?.featureId || serverFeature?.id || "").trim();
      if (!featureId || seenFeatureIds.has(featureId)) {
        continue;
      }
      nextFeatures.push(
        buildClientFeatureFromServer(
          serverFeature,
          existingById.get(featureId) || null,
          nextFeatures.length,
        ),
      );
    }
  }

  clientState.features = nextFeatures.filter(Boolean);
  if (state.selectedFeatureId && !clientState.features.some((feature) => feature.id === state.selectedFeatureId)) {
    state.selectedFeatureId = clientState.features[0]?.id || null;
  }

  if (options.persist !== false) {
    persistClientState();
  }
}

async function refreshFeatureActivationStates(options = {}) {
  if (!isSignedIn()) {
    return null;
  }

  const response = await apiRequest("/api/features", {
    headers: getSessionAuthHeaders(),
    timeoutMs: options.timeoutMs || 15000,
  });

  applyServerFeatureStates(response.features || [], { persist: true, resetMissing: true });
  state.paymentStatus = response.paymentStatus || null;
  if (options.render !== false && document.body.dataset.view === "app") {
    renderApp();
  }
  return response;
}

function normalizePlatformConnection(source = {}) {
  const platform = String(source.platform || "").trim().toLowerCase();
  const option = getPlatformConnectionOption(platform);
  return {
    id: String(source.id || "").trim(),
    platform,
    label: option?.label || platform || "Connected app",
    authType: String(source.authType || source.auth_type || "api_token").trim().toLowerCase(),
    secretHint: String(source.secretHint || "").trim(),
    connectionStatus: String(source.connectionStatus || source.connection_status || "connected").trim().toLowerCase(),
    connectedAt: String(source.connectedAt || source.connected_at || "").trim(),
    updatedAt: String(source.updatedAt || source.updated_at || "").trim(),
  };
}

function getPlatformConnectionOption(platform) {
  const normalized = String(platform || "").trim().toLowerCase();
  return PLATFORM_CONNECTION_OPTIONS.find((option) => option.id === normalized) || null;
}

function getPlatformConnectionByPlatform(platform) {
  const normalized = String(platform || "").trim().toLowerCase();
  return state.platformConnections.find((connection) => connection.platform === normalized) || null;
}

async function refreshPlatformConnections(options = {}) {
  if (!isSignedIn()) {
    state.platformConnections = [];
    return [];
  }

  const response = await apiRequest("/api/platform-connections", {
    headers: getSessionAuthHeaders(),
    timeoutMs: options.timeoutMs || 15000,
  });
  state.platformConnections = Array.isArray(response.connections)
    ? response.connections.map(normalizePlatformConnection).filter((connection) => connection.platform)
    : [];
  if (options.render !== false && document.body.dataset.view === "app") {
    renderApp({ preserveStatus: true });
  }
  return state.platformConnections;
}

function createPlatformConnectionForm(option) {
  const connection = getPlatformConnectionByPlatform(option.id);
  const form = document.createElement("form");
  form.className = "platform-connection-form";

  const intro = document.createElement("p");
  intro.className = "platform-connection-intro";
  intro.textContent = connection
    ? `${option.label} is connected. Enter a new token to replace it.`
    : `Once connected, you can ask me to use ${option.label} for whatever you need.`;

  const field = document.createElement("label");
  field.className = "field platform-connection-field";
  const label = document.createElement("span");
  label.textContent = option.credentialLabel || `${option.label} token`;
  const inputRow = document.createElement("span");
  inputRow.className = "platform-connection-input-row";
  const input = document.createElement("input");
  input.type = "password";
  input.name = "credential";
  input.autocomplete = "new-password";
  input.spellcheck = false;
  input.required = true;
  input.maxLength = 4096;
  input.placeholder = "Paste it here";
  input.setAttribute("aria-describedby", "platformConnectionHelp platformConnectionError");
  const reveal = document.createElement("button");
  reveal.type = "button";
  reveal.className = "ghost-button small platform-connection-reveal";
  reveal.textContent = "Show";
  reveal.setAttribute("aria-label", `Show ${option.label} token`);
  reveal.addEventListener("click", () => {
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    reveal.textContent = showing ? "Show" : "Hide";
    reveal.setAttribute("aria-label", `${showing ? "Show" : "Hide"} ${option.label} token`);
  });
  inputRow.append(input, reveal);
  const help = document.createElement("small");
  help.id = "platformConnectionHelp";
  help.className = "field-help";
  help.textContent = "Use the smallest set of permissions you need. This token is not saved in this browser or sent to the assistant.";
  const error = document.createElement("span");
  error.id = "platformConnectionError";
  error.className = "field-error";
  error.setAttribute("role", "alert");
  error.hidden = true;
  field.append(label, inputRow, help, error);

  const securityNote = document.createElement("div");
  securityNote.className = "platform-connection-security-note";
  securityNote.textContent = "Your token is encrypted before it is stored. You can replace it here or revoke it with the provider at any time.";

  const helpButton = document.createElement("button");
  helpButton.type = "button";
  helpButton.className = "ghost-button small platform-connection-help";
  helpButton.textContent = "Help me get it";
  helpButton.addEventListener("click", () => {
    closeAuthAlert();
    pushAgentMessage("assistant", `I can help you get a ${option.label} token. Tell me what screen you’re on and I’ll walk you through it. Please don’t paste the token into chat.`);
    persistAgentWorkspace(`I can help you get a ${option.label} token.`);
    renderApp({ preserveStatus: true });
    elements.agentComposerInput?.focus();
  });

  form.append(intro, field, securityNote, helpButton);
  return { form, input, error };
}

function openPlatformConnection(optionId) {
  const option = getPlatformConnectionOption(optionId);
  if (!option) {
    return;
  }

  const { form, input, error } = createPlatformConnectionForm(option);
  let saving = false;
  const saveConnection = async () => {
    if (saving) {
      return;
    }
    const credential = String(input.value || "").trim();
    if (!credential) {
      error.textContent = "Paste the token to continue.";
      error.hidden = false;
      input.focus();
      return;
    }

    saving = true;
    elements.authAlertDismissButton.disabled = true;
    elements.authAlertDismissButton.textContent = "Saving…";
    error.hidden = true;
    try {
      const response = await apiRequest("/api/platform-connections", {
        method: "POST",
        headers: getSessionAuthHeaders(),
        timeoutMs: 20000,
        body: {
          platform: option.id,
          authType: option.authType || "api_token",
          credential,
        },
      });
      input.value = "";
      closeAuthAlert();
      const connection = response.connection ? normalizePlatformConnection(response.connection) : null;
      if (connection) {
        state.platformConnections = [
          connection,
          ...state.platformConnections.filter((candidate) => candidate.platform !== connection.platform),
        ];
      } else {
        await refreshPlatformConnections({ render: false });
      }
      pushAgentMessage("assistant", `${option.label} is connected. You can ask me to use it whenever you need it.`);
      persistAgentWorkspace(`${option.label} is connected.`);
      renderApp({ preserveStatus: true });
    } catch (requestError) {
      const message = formatApiErrorMessage(requestError, "I couldn’t save that connection securely. Please try again.");
      error.textContent = message;
      error.hidden = false;
      elements.authAlertDismissButton.disabled = false;
      elements.authAlertDismissButton.textContent = "Save securely";
      input.focus();
    } finally {
      saving = false;
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void saveConnection();
  });

  openAuthAlert(
    `Connect ${option.label}`,
    "Add this connection once, then use it across your requests.",
    {
      eyebrow: "Connect an app",
      icon: "↗",
      tone: "progress",
      variant: "platform-connection",
      bodyNode: form,
      buttonLabel: "Save securely",
      secondaryButtonLabel: "Cancel",
      closeOnPrimary: false,
      returnFocus: elements.agentAddToolButton,
      onPrimary: saveConnection,
    },
  );
  window.requestAnimationFrame(() => input.focus());
}

function looksLikeCredential(text) {
  const value = String(text || "").trim();
  return /\b(?:xox[baprs]-[A-Za-z0-9-]{16,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9._-]{24,})\b/i.test(value)
    || /\b(?:api[_ -]?key|access[_ -]?token|bot[_ -]?token|secret|password)\s*[:=]\s*[^\s]{24,}/i.test(value);
}

function getPlatformConnectionIntentFromText(text) {
  const value = String(text || "").trim().toLowerCase();
  const option = PLATFORM_CONNECTION_OPTIONS.find((candidate) => {
    const platformPattern = candidate.id === "calendar" ? /\bcalendar\b/ : new RegExp(`\\b${candidate.id}\\b`);
    return platformPattern.test(value);
  });
  if (!option) {
    return null;
  }

  const agent = getAgentWorkspace();
  const latestUserIntent = [...agent.messages].reverse().find((message) => message.role === "user");
  const hasConnectionContext = Boolean(
    latestUserIntent
    && /\b(help me|add|connect|link|set\s*up|setup)\b/i.test(String(latestUserIntent.text || ""))
    && /\b(?:custom|another|platform|tool|app)\b/i.test(String(latestUserIntent.text || "")),
  );
  const directConnectionRequest = /\b(connect|link|add|set\s*up|setup)\b/i.test(value);
  return hasConnectionContext || directConnectionRequest ? option : null;
}

function clearFeatureConfigAutosaveTimer(featureId) {
  const normalizedFeatureId = String(featureId || "").trim();
  if (!normalizedFeatureId) {
    return;
  }

  const timerId = featureConfigAutosaveTimers.get(normalizedFeatureId);
  if (timerId) {
    window.clearTimeout(timerId);
    featureConfigAutosaveTimers.delete(normalizedFeatureId);
  }
}

function clearAllFeatureConfigAutosaves() {
  for (const timerId of featureConfigAutosaveTimers.values()) {
    window.clearTimeout(timerId);
  }
  featureConfigAutosaveTimers.clear();
}

function clearAccountProfileAutosaveTimer() {
  if (accountProfileAutosaveTimer !== null) {
    window.clearTimeout(accountProfileAutosaveTimer);
    accountProfileAutosaveTimer = null;
  }
}

function sendAccountProfileKeepalive() {
  if (!isSignedIn()) {
    return;
  }

  try {
    const headers = new Headers(getSessionAuthHeaders());
    headers.set("Content-Type", "application/json");
    void fetch(buildApiUrl("/api/account/profile"), {
      method: "POST",
      headers,
      cache: "no-store",
      keepalive: true,
      body: JSON.stringify({
        profile: normalizeAccountProfile(clientState.profile),
      }),
    });
  } catch {
    // Ignore unload-time save failures; the normal autosave path already handles surfaced errors.
  }
}

async function flushAccountProfileAutosave(options = {}) {
  clearAccountProfileAutosaveTimer();
  if (!isSignedIn()) {
    return null;
  }
  if (accountProfileSavePromise) {
    return accountProfileSavePromise;
  }

  accountProfileSavePromise = (async () => {
    try {
      const response = await apiRequest("/api/account/profile", {
        method: "POST",
        headers: getSessionAuthHeaders(),
        body: {
          profile: normalizeAccountProfile(clientState.profile),
        },
      });
      applyRemoteAccountProfile(response);
      if (options.render !== false && document.body.dataset.view === "app") {
        updatePersonalDetailsFields();
      }
      setStatus(String(response.message || "Saved"));
      return response;
    } catch (error) {
      const status = Number(error?.status || 0);
      if (status === 401 || status === 403) {
        clearAuthSession();
      }
      setStatus("Couldn’t save personal details.");
      throw error;
    } finally {
      accountProfileSavePromise = null;
    }
  })();

  return accountProfileSavePromise;
}

function scheduleAccountProfileAutosave(options = {}) {
  clearAccountProfileAutosaveTimer();
  const delayMs = Number.isFinite(options.delayMs)
    ? Math.max(0, Number(options.delayMs))
    : ACCOUNT_PROFILE_AUTOSAVE_DELAY_MS;
  if (options.status !== false) {
    setStatus("Saving personal details...");
  }

  accountProfileAutosaveTimer = window.setTimeout(() => {
    accountProfileAutosaveTimer = null;
    void flushAccountProfileAutosave({
      render: document.body.dataset.view === "app" && state.activeTab === "personal-details",
    }).catch(() => {});
  }, delayMs);
}

function hasPendingFeatureConfigAutosave(featureId = state.selectedFeatureId) {
  const normalizedFeatureId = String(featureId || "").trim();
  return normalizedFeatureId ? featureConfigAutosaveTimers.has(normalizedFeatureId) : false;
}

function getFeatureConfigReturnFocus() {
  return elements.featureStudioEditorToggleButton || elements.featureStudioActivationButton || null;
}

function sendFeatureConfigKeepalive(feature = getSelectedFeature()) {
  if (!isSignedIn() || !feature || !hasFeatureConfigChanges(feature)) {
    return;
  }

  try {
    const headers = new Headers(getSessionAuthHeaders());
    headers.set("Content-Type", "application/json");
    void fetch(buildApiUrl(`/api/features/${encodeURIComponent(feature.id)}/config`), {
      method: "POST",
      headers,
      cache: "no-store",
      keepalive: true,
      body: JSON.stringify({
        prompt: { ...feature.prompt },
        settings: buildSettingsForSave(feature, feature.settings),
      }),
    });
  } catch {
    // Ignore unload-time save failures; the normal autosave path already handles surfaced errors.
  }
}

function scheduleSelectedFeatureConfigAutosave(feature = getSelectedFeature(), options = {}) {
  const featureId = String(feature?.id || "").trim();
  if (!featureId) {
    return;
  }

  clearFeatureConfigAutosaveTimer(featureId);
  const delayMs = Number.isFinite(options.delayMs)
    ? Math.max(0, Number(options.delayMs))
    : FEATURE_CONFIG_AUTOSAVE_DELAY_MS;
  if (options.status !== false) {
    setStatus("Saving changes...");
  }

  const timerId = window.setTimeout(() => {
    featureConfigAutosaveTimers.delete(featureId);
    void flushSelectedFeatureConfigAutosave({
      featureId,
      render: document.body.dataset.view === "app" && state.selectedFeatureId === featureId,
      alertOnError: false,
    }).catch(() => {});
  }, delayMs);
  featureConfigAutosaveTimers.set(featureId, timerId);
}

async function flushSelectedFeatureConfigAutosave(options = {}) {
  const featureId = String(options.featureId || state.selectedFeatureId || "").trim();
  if (!featureId) {
    return null;
  }

  clearFeatureConfigAutosaveTimer(featureId);
  return saveSelectedFeatureConfig({
    featureId,
    render: options.render !== false && document.body.dataset.view === "app" && state.selectedFeatureId === featureId,
    alertOnError: options.alertOnError === true,
    returnFocus: options.returnFocus || getFeatureConfigReturnFocus(),
    statusMessage: options.statusMessage || "Saving changes...",
    noChangesMessage: options.noChangesMessage || "Saved",
  });
}

async function saveSelectedFeatureConfig(options = {}) {
  if (featureConfigBusy && featureConfigSavePromise) {
    try {
      await featureConfigSavePromise;
    } catch {
      // Let the next save attempt continue so autosave can retry with the latest data.
    }
  }

  const featureId = String(options.featureId || getSelectedFeature()?.id || "").trim();
  const feature = featureId ? getFeatureById(featureId) : getSelectedFeature();
  const shouldRender = options.render !== false && document.body.dataset.view === "app" && state.selectedFeatureId === featureId;
  if (!feature || !hasFeatureConfigChanges(feature)) {
    if (shouldRender) {
      renderApp();
    }
    if (options.noChangesMessage !== false) {
      setStatus(String(options.noChangesMessage || "Saved"));
    }
    return null;
  }

  featureConfigBusy = true;
  let currentSavePromise = null;
  currentSavePromise = (async () => {
    try {
      if (shouldRender) {
        renderApp();
      }
      setStatus(String(options.statusMessage || "Saving tool settings..."));
      const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/config`, {
        method: "POST",
        headers: getSessionAuthHeaders(),
        body: {
          prompt: { ...feature.prompt },
          settings: buildSettingsForSave(feature, feature.settings),
        },
      });

      applyServerFeatureStates([response.feature || {}], { persist: true });
      state.paymentStatus = response.paymentStatus || state.paymentStatus;
      persistClientState();
      if (shouldRender) {
        renderApp();
      }
      setStatus(String(response.message || "Tool settings saved."));
      return response;
    } catch (error) {
      if (options.alertOnError !== false) {
        openFeatureActivationAlert(
          "Couldn’t save the settings",
          formatApiErrorMessage(error, "We couldn’t save these tool settings right now."),
          {
            eyebrow: "Try again",
            returnFocus: options.returnFocus || getFeatureConfigReturnFocus(),
          },
        );
      }
      if (shouldRender) {
        renderApp();
      }
      setStatus("Couldn’t save the tool settings.");
      throw error;
    } finally {
      featureConfigBusy = false;
      if (featureConfigSavePromise === currentSavePromise) {
        featureConfigSavePromise = null;
      }
      if (shouldRender) {
        renderApp();
      }
      updateFeatureStudioHeader();
    }
  })();
  featureConfigSavePromise = currentSavePromise;
  return await currentSavePromise;
}

async function refreshWhatsAppConnection(options = {}) {
  if (!isSignedIn()) {
    return null;
  }

  const response = await apiRequest("/api/whatsapp/connection", {
    headers: getSessionAuthHeaders(),
    timeoutMs: options.timeoutMs || 15000,
  });

  applyWhatsAppConnectionToFeatures(response.connection || null, { persist: true });
  if (options.render !== false && document.body.dataset.view === "app") {
    renderApp();
  }
  return response.connection || null;
}

function clearWhatsAppConnectionPollTimer() {
  if (whatsappConnectionPollTimer !== null) {
    window.clearTimeout(whatsappConnectionPollTimer);
    whatsappConnectionPollTimer = null;
  }
}

function shouldPollWhatsAppConnection(feature = getSelectedFeature()) {
  return Boolean(
    isSignedIn()
    && document.body.dataset.view === "app"
    && state.activeTab === "features"
    && feature
    && isWhatsAppFeature(feature)
    && !hasFeatureActivationChanges(feature)
    && !featureActivationBusy,
  );
}

async function pollWhatsAppConnectionHealth() {
  const feature = getSelectedFeature();
  const featureId = String(feature?.id || "").trim();
  if (whatsappConnectionPollInFlight || !shouldPollWhatsAppConnection(feature)) {
    if (!shouldPollWhatsAppConnection(feature)) {
      clearWhatsAppConnectionPollTimer();
      whatsappConnectionPollActive = false;
    }
    return;
  }

  whatsappConnectionPollInFlight = true;
  try {
    await refreshWhatsAppConnection({ render: false });
    if (
      document.body.dataset.view === "app"
      && state.activeTab === "features"
      && String(getSelectedFeature()?.id || "").trim() === featureId
    ) {
      renderApp({ preserveStatus: true });
    }
  } catch {
    // Keep the current UI and try again on the next poll.
  } finally {
    whatsappConnectionPollInFlight = false;
    clearWhatsAppConnectionPollTimer();
    if (shouldPollWhatsAppConnection()) {
      whatsappConnectionPollTimer = window.setTimeout(() => {
        void pollWhatsAppConnectionHealth();
      }, WHATSAPP_CONNECTION_POLL_MS);
    } else {
      whatsappConnectionPollActive = false;
    }
  }
}

function syncWhatsAppConnectionPolling() {
  const feature = getSelectedFeature();
  const featureId = String(feature?.id || "").trim();

  if (!shouldPollWhatsAppConnection(feature)) {
    clearWhatsAppConnectionPollTimer();
    whatsappConnectionPollActive = false;
    whatsappConnectionPollFeatureId = featureId;
    return;
  }

  const isNewTarget = !whatsappConnectionPollActive || whatsappConnectionPollFeatureId !== featureId;
  whatsappConnectionPollActive = true;
  whatsappConnectionPollFeatureId = featureId;

  if (isNewTarget) {
    clearWhatsAppConnectionPollTimer();
    void pollWhatsAppConnectionHealth();
    return;
  }

  if (whatsappConnectionPollTimer === null && !whatsappConnectionPollInFlight) {
    whatsappConnectionPollTimer = window.setTimeout(() => {
      void pollWhatsAppConnectionHealth();
    }, WHATSAPP_CONNECTION_POLL_MS);
  }
}

function formatNextBillingDate(reference = new Date()) {
  const moment = new Date(reference.getTime());
  moment.setDate(1);
  moment.setMonth(moment.getMonth() + 1);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(moment);
}

function formatDisplayNameFromId(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase()) || "Unassigned tool";
}

function getInitialsFromName(value) {
  const parts = String(value || "")
    .replace(/[^A-Za-z0-9\s]+/g, " ")
    .split(/\s+/)
    .filter(Boolean);

  return (parts.slice(0, 2).map((part) => part[0]).join("") || "WA").toUpperCase();
}

function normalizePrompt(prompt = {}, fallback = DEFAULT_PROMPT) {
  const base = { ...DEFAULT_PROMPT, ...(fallback || {}), ...(prompt || {}) };
  const responseStyle = String(base.responseStyle || DEFAULT_PROMPT.responseStyle).toLowerCase();
  const scenario = SCENARIOS[base.scenario] ? base.scenario : DEFAULT_PROMPT.scenario;
  const exampleReplies = scenario === "monitor"
    ? String(base.exampleReplies || "")
    : "";

  return {
    toneGuidance: String(base.toneGuidance || DEFAULT_PROMPT.toneGuidance),
    replyRules: String(base.replyRules || DEFAULT_PROMPT.replyRules),
    businessNotes: String(base.businessNotes || DEFAULT_PROMPT.businessNotes),
    escalationGuidance: String(base.escalationGuidance || DEFAULT_PROMPT.escalationGuidance),
    exampleReplies,
    responseStyle: ["short", "balanced", "detailed"].includes(responseStyle)
      ? responseStyle
      : DEFAULT_PROMPT.responseStyle,
    scenario,
  };
}

function getFeatureById(featureId) {
  return clientState.features.find((feature) => feature.id === featureId) || null;
}

function getSelectedFeature() {
  return getFeatureById(state.selectedFeatureId) || clientState.features[0] || null;
}

function getSelectedPrompt() {
  return getSelectedFeature()?.prompt || { ...DEFAULT_PROMPT };
}

function getSavedFeaturePrompt(feature = getSelectedFeature()) {
  return normalizePrompt(feature?.savedPrompt || feature?.prompt || {}, DEFAULT_PROMPT);
}

function normalizeFeatureStudioView(view) {
  const nextView = String(view || "").trim().toLowerCase();
  return VALID_FEATURE_STUDIO_VIEWS.has(nextView) ? nextView : null;
}

function isFeatureActivated(feature = getSelectedFeature()) {
  return Boolean(feature && feature.activated);
}

function getWhatsAppConnectionSetupState(feature = getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID)) {
  if (!feature || !isWhatsAppFeature(feature)) {
    return {
      feature: feature || null,
      ready: false,
      genericPlatformConnected: false,
      connectionStatus: "not_connected",
      missingFields: [],
    };
  }

  const candidates = [
    normalizeFeatureWhatsApp(feature.whatsapp || {}),
    normalizeFeatureWhatsApp(feature.savedWhatsApp || {}),
  ];
  const tokenConfigured = (config) => Boolean(
    config.access_token_configured
    || config.workspace_access_token_configured
    || config.backend_access_token_configured
    || config.access_token,
  );
  const hasRequiredDetails = (config) => Boolean(
    config.business_account_id
    && config.phone_number_id
    && tokenConfigured(config)
    && config.owner_wa_id
    && config.connection_status === "connected",
  );
  const readyConfig = candidates.find(hasRequiredDetails) || candidates[0];
  const hasValue = (key) => candidates.some((config) => String(config[key] || "").trim());
  const missingFields = [];

  if (!hasValue("business_account_id")) {
    missingFields.push({ key: "business_account_id", label: "WhatsApp Business Account ID (WABA ID)" });
  }
  if (!hasValue("phone_number_id")) {
    missingFields.push({ key: "phone_number_id", label: "Phone Number ID" });
  }
  if (!candidates.some(tokenConfigured)) {
    missingFields.push({ key: "access_token", label: "WhatsApp access token" });
  }
  if (!hasValue("owner_wa_id")) {
    missingFields.push({ key: "owner_wa_id", label: "Approval phone number" });
  }
  if (!candidates.some((config) => config.connection_status === "connected")) {
    missingFields.push({ key: "connection_status", label: "Verified WhatsApp Business connection" });
  }

  return {
    feature,
    ready: hasRequiredDetails(readyConfig),
    genericPlatformConnected: Boolean(getPlatformConnectionByPlatform("whatsapp")),
    connectionStatus: readyConfig.connection_status || "not_connected",
    missingFields,
  };
}

function isWhatsAppConnectionReady(feature = getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID)) {
  return getWhatsAppConnectionSetupState(feature).ready;
}

function buildAgentToolContext() {
  const whatsapp = getWhatsAppConnectionSetupState();
  return {
    whatsapp: {
      ready: whatsapp.ready,
      platformConnected: whatsapp.genericPlatformConnected,
      connectionStatus: whatsapp.connectionStatus,
      missingFields: whatsapp.missingFields.map((field) => ({
        key: field.key,
        label: field.label,
      })),
    },
  };
}

function isFeatureSetupComplete(feature = getSelectedFeature()) {
  if (isWhatsAppFeature(feature)) {
    return isWhatsAppConnectionReady(feature);
  }
  return Boolean(feature && (feature.setupComplete || isFeatureActivated(feature)));
}

function hasFeatureWhatsAppDetails(feature = getSelectedFeature()) {
  if (!feature || !isWhatsAppFeature(feature)) {
    return false;
  }

  const detailKeys = [
    "business_account_id",
    "phone_number_id",
    "access_token",
    "access_token_configured",
    "owner_wa_id",
    "display_phone_number",
    "verified_name",
  ];
  const configs = [getSelectedFeatureWhatsApp(feature), getSavedFeatureWhatsApp(feature)];

  return configs.some((config) => detailKeys.some((key) => String(config[key] || "").trim()));
}

function canOpenFeatureWhatsAppDetails(feature = getSelectedFeature()) {
  return Boolean(
    feature
    && isWhatsAppFeature(feature)
    && (isFeatureActivated(feature) || isFeatureSetupComplete(feature) || hasFeatureWhatsAppDetails(feature))
  );
}

function getFeatureActivationState(feature = getSelectedFeature()) {
  return isFeatureActivated(feature) ? "active" : "non-active";
}

function getFeatureActivationLabel(feature = getSelectedFeature()) {
  return getFeatureActivationState(feature);
}

function applyFeatureActivationBadgeStyle(element, feature = getSelectedFeature()) {
  if (!element) {
    return;
  }

  const state = getFeatureActivationState(feature);
  const palette = state === "active"
    ? { backgroundColor: "rgba(22, 163, 74, 0.12)", color: "#15803d" }
    : { backgroundColor: "rgba(220, 38, 38, 0.12)", color: "#b42318" };

  element.dataset.state = state;
  element.style.backgroundColor = palette.backgroundColor;
  element.style.color = palette.color;
}

function clearFeatureActivationBadgeStyle(element) {
  if (!element) {
    return;
  }

  element.removeAttribute("data-state");
  element.style.backgroundColor = "";
  element.style.color = "";
}

function setFeatureActivationState(feature, activated) {
  if (!feature) {
    return;
  }

  feature.activated = Boolean(activated);
  if (feature.activated) {
    feature.setupComplete = true;
  }
  feature.status = getFeatureActivationState(feature);
}

function getDefaultFeatureStudioView(feature = getSelectedFeature()) {
  if (usesEditorSetup(feature)) {
    return "editor";
  }
  return isFeatureSetupComplete(feature) ? "editor" : "overview";
}

function getSelectedFeatureStudioView(feature = getSelectedFeature()) {
  const nextView = normalizeFeatureStudioView(state.featureStudioView);
  if (nextView === "history" && !isWhatsAppFeature(feature)) {
    return getDefaultFeatureStudioView(feature);
  }
  return nextView || getDefaultFeatureStudioView(feature);
}

function getActivationBackView(feature = getSelectedFeature()) {
  if (usesEditorSetup(feature)) {
    return "editor";
  }
  return isFeatureActivated(feature) ? "editor" : "overview";
}

function getSelectedFeatureWhatsApp(feature = getSelectedFeature()) {
  return normalizeFeatureWhatsApp(feature?.whatsapp || {});
}

function getSelectedFeatureSettings(feature = getSelectedFeature()) {
  return normalizeSettingsForFeature(feature?.id || "", feature?.settings || {});
}

function getSavedFeatureSettings(feature = getSelectedFeature()) {
  return normalizeSettingsForFeature(feature?.id || "", feature?.savedSettings || feature?.settings || {});
}

function getSavedFeatureWhatsApp(feature = getSelectedFeature()) {
  const savedSource = feature?.savedWhatsApp || feature?.saved_whatsapp;
  if (savedSource) {
    return normalizeFeatureWhatsApp(savedSource);
  }

  return isFeatureSetupComplete(feature)
    ? normalizeFeatureWhatsApp(feature?.whatsapp || {})
    : normalizeFeatureWhatsApp(DEFAULT_FEATURE_WHATSAPP);
}

function getFeatureWhatsAppHealth(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  return normalizeFeatureWhatsAppMetadata(whatsapp.metadata || {});
}

function getFeatureWhatsAppOwnerLabel(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  return String(whatsapp.owner_wa_id || whatsapp.display_phone_number || "your phone").trim() || "your phone";
}

function getFeatureWhatsAppConnectedLabel(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  return String(whatsapp.verified_name || whatsapp.display_phone_number || whatsapp.phone_number_id || "your WhatsApp number").trim() || "your WhatsApp number";
}

function getWhatsAppOwnerNotificationFailureCopy(feature = getSelectedFeature(), options = {}) {
  const ownerLabel = String(options.ownerLabel || getFeatureWhatsAppOwnerLabel(feature) || "your phone").trim() || "your phone";
  const health = getFeatureWhatsAppHealth(feature);
  const errorText = sanitizeErrorText(health.lastOwnerNotificationError || "");
  const issueDetails = errorText ? ` WhatsApp reported: ${errorText}.` : "";
  return `We kept the incoming message, but the alert did not reach ${ownerLabel}.${issueDetails} Check the connected number and your WhatsApp delivery status before trying again.`;
}

function buildFeatureActivationStatusContent(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  const health = getFeatureWhatsAppHealth(feature);
  const isConnected = whatsapp.connection_status === "connected";
  const numberLabel = getFeatureWhatsAppConnectedLabel(feature);
  const ownerLabel = getFeatureWhatsAppOwnerLabel(feature);
  const lastInboundAt = health.lastInboundAt ? formatAdminDateTime(health.lastInboundAt) : "";
  const lastOwnerNotificationAt = health.lastOwnerNotificationAt ? formatAdminDateTime(health.lastOwnerNotificationAt) : "";
  const lastInboundSender = String(health.lastInboundSenderName || health.lastInboundSenderWaId || "a customer").trim() || "a customer";
  const lastOwnerStatus = String(health.lastOwnerNotificationStatus || "").trim().toLowerCase();

  const content = {
    number: {
      title: "Add your details",
      copy: "Save the WABA ID, Phone Number ID, access token, and approval phone.",
    },
    inbound: {
      title: "Waiting for the first live message",
      copy: "Once someone messages your connected WhatsApp number, we’ll show that Assistyca received it here.",
    },
    owner: {
      title: "No approval alert sent yet",
      copy: "The first live message from another number will trigger an approval alert to your phone.",
    },
    note: "",
  };

  if (hasFeatureWhatsAppDetails(feature)) {
    content.number = isConnected
      ? {
          title: "Phone number verified",
          copy: `${numberLabel} is saved and ready for live checks.`,
        }
      : {
          title: "Still need to verify the number",
          copy: "The details are saved, but Assistyca still needs to verify the phone number and subscribe the WABA webhook with Meta.",
        };
  }

  if (health.lastInboundAt) {
    content.inbound = {
      title: "Live message received",
      copy: `Assistyca last received a WhatsApp message on ${lastInboundAt} from ${lastInboundSender}.`,
    };
  } else if (isConnected) {
    content.inbound = {
      title: "Waiting for the first live message",
      copy: "Ask someone else to message your connected WhatsApp number. Messages from your approval phone are treated as your commands, so they will not create a customer draft.",
    };
  }

  if (lastOwnerStatus === "failed") {
    content.owner = {
      title: "Latest approval alert hit a delivery issue",
      copy: lastOwnerNotificationAt
        ? `${getWhatsAppOwnerNotificationFailureCopy(feature, { ownerLabel })} The latest failed attempt was on ${lastOwnerNotificationAt}.`
        : getWhatsAppOwnerNotificationFailureCopy(feature, { ownerLabel }),
    };
  } else if (lastOwnerStatus === "requested") {
    content.owner = {
      title: "Latest approval alert is waiting for delivery confirmation",
      copy: lastOwnerNotificationAt
        ? `We asked WhatsApp to send the latest alert to ${ownerLabel} on ${lastOwnerNotificationAt}. We’re waiting for delivery confirmation.`
        : `We asked WhatsApp to send the latest alert to ${ownerLabel}. We’re waiting for delivery confirmation.`,
    };
  } else if (lastOwnerStatus === "sent") {
    content.owner = {
      title: "Latest approval alert is on the way",
      copy: lastOwnerNotificationAt
        ? `WhatsApp accepted the latest alert for ${ownerLabel} on ${lastOwnerNotificationAt}. We’re still waiting for delivery confirmation.`
        : `WhatsApp accepted the latest alert for ${ownerLabel}. We’re still waiting for delivery confirmation.`,
    };
  } else if (lastOwnerStatus === "delivered") {
    content.owner = {
      title: "Latest approval alert was delivered",
      copy: lastOwnerNotificationAt
        ? `The latest approval alert reached ${ownerLabel} on ${lastOwnerNotificationAt}.`
        : `The latest approval alert reached ${ownerLabel}.`,
    };
  } else if (lastOwnerStatus === "read") {
    content.owner = {
      title: "Latest approval alert was opened",
      copy: lastOwnerNotificationAt
        ? `${ownerLabel} opened the latest approval alert on ${lastOwnerNotificationAt}.`
        : `${ownerLabel} opened the latest approval alert.`,
    };
  } else if (lastOwnerStatus === "pending" && health.lastInboundAt) {
    content.owner = {
      title: "Approval alert is still pending",
      copy: `Assistyca received the message and is still trying to alert ${ownerLabel}.`,
    };
  } else if (isConnected) {
    content.owner = {
      title: "No approval alert sent yet",
      copy: `When the first live message from another number arrives, we’ll alert ${ownerLabel}.`,
    };
  }

  if (isConnected && !health.lastInboundAt && whatsapp.webhook_url) {
    content.note = `If another number messages your connected WhatsApp number and nothing reaches Assistyca, make sure Meta is forwarding new messages to ${whatsapp.webhook_url}.`;
  }

  return content;
}

function buildFeatureEditorWhatsAppHealthNotice(feature = getSelectedFeature()) {
  if (!feature || !isWhatsAppFeature(feature) || !isFeatureActivated(feature)) {
    return null;
  }

  const whatsapp = getSelectedFeatureWhatsApp(feature);
  if (whatsapp.connection_status !== "connected") {
    return null;
  }

  const health = getFeatureWhatsAppHealth(feature);
  const lastOwnerStatus = String(health.lastOwnerNotificationStatus || "").trim().toLowerCase();

  if (["requested", "sent"].includes(lastOwnerStatus)) {
    return {
      tone: "neutral",
      title: "Waiting for WhatsApp delivery confirmation",
      copy: "The latest alert was accepted by WhatsApp, but we have not seen a delivered receipt yet.",
    };
  }

  if (!health.lastInboundAt) {
    return {
      tone: "neutral",
      title: "Still waiting for the first live WhatsApp message",
      copy: "Ask someone else to message your connected WhatsApp number. Messages from your approval phone are treated as your commands. If nothing reaches Assistyca, incoming messages are not being forwarded yet.",
    };
  }

  return null;
}

function hasFeatureActivationChanges(feature = getSelectedFeature()) {
  const current = getSelectedFeatureWhatsApp(feature);
  const saved = getSavedFeatureWhatsApp(feature);
  const editableKeys = ["business_account_id", "phone_number_id", "owner_wa_id"];
  if (normalizePendingAccessToken(current.access_token)) {
    return true;
  }

  return editableKeys.some((key) => String(current[key] || "").trim() !== String(saved[key] || "").trim());
}

function canSendWhatsAppReplySample(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  return Boolean(
    isWhatsAppReplyAssistantFeature(feature)
    && isWhatsAppFeature(feature)
    && whatsapp.connection_status === "connected"
  );
}

function isWhatsAppReplySampleBusy(feature = getSelectedFeature()) {
  return Boolean(
    whatsappSampleMessageBusy
    && feature
    && feature.id
    && feature.id === whatsappSampleMessageTargetId
  );
}

function formatWhatsAppMessageCount(count) {
  const value = Math.max(0, Number.parseInt(count, 10) || 0);
  return `${value} message${value === 1 ? "" : "s"}`;
}

function formatWhatsAppImportLineCount(count) {
  const value = Math.max(0, Number.parseInt(count, 10) || 0);
  return `${value} line${value === 1 ? "" : "s"}`;
}

function buildWhatsAppHistoryImportStatusMessage(response = {}) {
  const saved = Math.max(0, Number.parseInt(response.messagesSaved, 10) || 0);
  const parsed = Math.max(0, Number.parseInt(response.messagesParsed, 10) || 0);
  const replaced = Math.max(0, Number.parseInt(response.messagesReplaced, 10) || 0);
  const duplicates = Math.max(0, Number.parseInt(response.duplicates, 10) || 0);
  const lineCount = Math.max(0, Number.parseInt(response.lineCount, 10) || 0);
  const blankLines = Math.max(0, Number.parseInt(response.blankLineCount, 10) || 0);
  const skipped = Math.max(0, Number.parseInt(response.skippedLineCount, 10) || 0);
  const unsupported = Math.max(0, Number.parseInt(response.unsupportedMessageLineCount, 10) || 0);
  const continuation = Math.max(0, Number.parseInt(response.continuationLineCount, 10) || 0);
  const parts = [];

  if (saved > 0) {
    parts.push(
      replaced > 0
        ? `Imported ${formatWhatsAppMessageCount(saved)}, replacing ${formatWhatsAppMessageCount(replaced)}`
        : `Imported ${formatWhatsAppMessageCount(saved)}`,
    );
  } else if (parsed > 0 && duplicates > 0) {
    parts.push(`No new messages imported; ${formatWhatsAppMessageCount(duplicates)} were already saved`);
  } else {
    parts.push(String(response.message || "WhatsApp history import completed.").replace(/\.$/, ""));
  }

  if (parsed > 0 && (parsed !== saved || lineCount || duplicates)) {
    parts.push(`${formatWhatsAppMessageCount(parsed)} parsed from the file`);
  }
  if (lineCount > 0) {
    const detail = continuation > 0
      ? `${formatWhatsAppImportLineCount(lineCount)} read, including ${formatWhatsAppImportLineCount(continuation)} of multi-line message text`
      : `${formatWhatsAppImportLineCount(lineCount)} read`;
    parts.push(detail);
  }
  if (blankLines > 0) {
    parts.push(`${formatWhatsAppImportLineCount(blankLines)} blank lines ignored`);
  }
  if (skipped > 0) {
    const skippedText = unsupported > 0
      ? `${formatWhatsAppImportLineCount(skipped)} skipped as system/unsupported export rows; ${formatWhatsAppImportLineCount(unsupported)} looked like message rows`
      : `${formatWhatsAppImportLineCount(skipped)} skipped as system/unsupported export rows`;
    parts.push(skippedText);
  }

  return `${parts.join(". ")}.`;
}

function isWhatsAppExternalOutboundPlaceholder(payload = {}) {
  const metadata = payload.metadata && typeof payload.metadata === "object" ? payload.metadata : {};
  const direction = String(payload.direction || "").trim().toLowerCase();
  const text = normalizeText(payload.text || "").toLowerCase();
  return Boolean(
    direction === "outbound"
    && (
      metadata.contentUnavailable
      || (text.includes("content unavailable") && text.includes("outside assistyca"))
    )
  );
}

function getWhatsAppExternalOutboundText(payload = {}) {
  return WHATSAPP_EXTERNAL_OUTBOUND_TEXT;
}

function getWhatsAppHistoryDisplayText(payload = {}) {
  if (isWhatsAppExternalOutboundPlaceholder(payload)) {
    return getWhatsAppExternalOutboundText(payload);
  }

  return normalizeText(payload.text || "");
}

function normalizeWhatsAppHistoryMessage(source = {}) {
  const direction = String(source.direction || "").trim().toLowerCase();
  const metadata = source.metadata && typeof source.metadata === "object" ? source.metadata : {};
  const suggestedReply = normalizeText(
    source.suggestedReply
    || source.suggested_reply
    || metadata.suggestedReply
    || metadata.suggested_reply
    || "",
  );
  const approvalId = normalizeText(
    source.approvalId
    || source.approval_id
    || metadata.approvalId
    || metadata.approval_id
    || "",
  );
  const approvalReviewUrl = normalizeText(
    source.approvalReviewUrl
    || source.approval_review_url
    || metadata.approvalReviewUrl
    || metadata.approval_review_url
    || "",
  );
  const approvalStatus = normalizeText(
    source.approvalStatus
    || source.approval_status
    || metadata.approvalStatus
    || metadata.approval_status
    || "",
  ).toLowerCase();
  return {
    messageId: String(source.messageId || source.message_id || "").trim(),
    direction: ["inbound", "outbound"].includes(direction) ? direction : "inbound",
    messageType: String(source.messageType || source.message_type || "text").trim() || "text",
    text: getWhatsAppHistoryDisplayText({ direction, text: source.text || "", metadata }),
    importSenderName: normalizeText(metadata.importSenderName || metadata.import_sender_name || ""),
    source: normalizeText(metadata.source || ""),
    suggestedReply,
    approvalId,
    approvalReviewUrl,
    approvalStatus,
    messageAt: String(source.messageAt || source.message_at || "").trim(),
    metadata,
    createdAt: String(source.createdAt || source.created_at || "").trim(),
    updatedAt: String(source.updatedAt || source.updated_at || "").trim(),
  };
}

function normalizeWhatsAppHistoryConversation(source = {}) {
  const messages = Array.isArray(source.messages)
    ? source.messages.map(normalizeWhatsAppHistoryMessage).filter((message) => message.text)
    : [];
  const messageCount = Math.max(
    Number.parseInt(source.messageCount ?? source.message_count ?? 0, 10) || 0,
    messages.length,
  );
  const metadata = source.metadata && typeof source.metadata === "object" ? source.metadata : {};
  const lastMessageDirection = String(source.lastMessageDirection || source.last_message_direction || "").trim().toLowerCase();
  const lastMessageText = getWhatsAppHistoryDisplayText({
    direction: lastMessageDirection,
    text: source.lastMessageText || source.last_message_text || "",
    metadata,
  });

  return {
    conversationId: String(source.conversationId || source.conversation_id || "").trim(),
    senderName: normalizeText(source.senderName || source.sender_name || ""),
    senderWaId: normalizeText(source.senderWaId || source.sender_wa_id || ""),
    lastMessageText,
    lastMessageDirection,
    lastMessageAt: String(source.lastMessageAt || source.last_message_at || "").trim(),
    lastInboundAt: String(source.lastInboundAt || source.last_inbound_at || "").trim(),
    lastOutboundAt: String(source.lastOutboundAt || source.last_outbound_at || "").trim(),
    messageCount,
    messages,
    metadata,
    createdAt: String(source.createdAt || source.created_at || "").trim(),
    updatedAt: String(source.updatedAt || source.updated_at || "").trim(),
  };
}

function normalizeWhatsAppHistoryDiagnostic(source = {}) {
  const tone = String(source.tone || "").trim().toLowerCase();
  return {
    tone: ["warning", "neutral", "success"].includes(tone) ? tone : "neutral",
    title: normalizeText(source.title || ""),
    message: normalizeText(source.message || ""),
  };
}

function normalizeWhatsAppHistoryPayload(payload = {}) {
  const conversations = Array.isArray(payload.conversations)
    ? payload.conversations.map(normalizeWhatsAppHistoryConversation).filter((conversation) => conversation.conversationId)
    : [];
  const diagnostics = Array.isArray(payload.diagnostics)
    ? payload.diagnostics.map(normalizeWhatsAppHistoryDiagnostic).filter((item) => item.title || item.message)
    : [];
  const messageCount = conversations.reduce((total, conversation) => total + conversation.messageCount, 0);

  return {
    connection: normalizeFeatureWhatsApp(payload.connection || {}),
    conversationCount: conversations.length,
    diagnostics,
    messageCount,
    conversations,
  };
}

function normalizeWhatsAppParticipantKey(value) {
  return normalizeText(value).toLowerCase().replace(/\s+/g, " ").trim();
}

function deriveWhatsAppEmailNameCandidates(email) {
  const localPart = String(email || "").split("@", 1)[0] || "";
  const cleaned = localPart.replace(/[^A-Za-z0-9]+/g, " ").trim();
  const tokens = cleaned.split(/\s+/).filter(Boolean);
  const candidates = cleaned ? [cleaned] : [];
  if (tokens.length > 1) {
    candidates.push([...tokens].reverse().join(" "));
  }
  return candidates;
}

function getActiveWhatsAppSenderKeys() {
  const keys = new Set();
  const addCandidate = (value) => {
    const key = normalizeWhatsAppParticipantKey(value);
    if (key) {
      keys.add(key);
    }
  };

  addCandidate(clientState?.settings?.displayName || "");
  deriveWhatsAppEmailNameCandidates(activeEmail).forEach(addCandidate);
  addCandidate("You");
  return keys;
}

function resolveWhatsAppHistoryMessageDirection(message = {}) {
  const importSenderName = normalizeText(message.importSenderName || "");
  if (importSenderName) {
    return getActiveWhatsAppSenderKeys().has(normalizeWhatsAppParticipantKey(importSenderName))
      ? "outbound"
      : "inbound";
  }
  return message.direction === "outbound" ? "outbound" : "inbound";
}

function getCurrentWhatsAppHistory() {
  if (state.whatsappHistoryEmail !== normalizeEmail(activeEmail)) {
    return null;
  }
  return state.whatsappHistory && Array.isArray(state.whatsappHistory.conversations)
    ? state.whatsappHistory
    : null;
}

function getWhatsAppHistoryConversations() {
  return getCurrentWhatsAppHistory()?.conversations || [];
}

function getSelectedWhatsAppHistoryConversation() {
  const conversations = getWhatsAppHistoryConversations();
  if (!conversations.length) {
    state.whatsappHistorySelectedConversationId = "";
    return null;
  }

  const selected = conversations.find((conversation) => (
    conversation.conversationId === state.whatsappHistorySelectedConversationId
  ));
  if (selected) {
    return selected;
  }

  state.whatsappHistorySelectedConversationId = conversations[0].conversationId;
  return conversations[0];
}

function buildWhatsAppHistoryConversationTitle(conversation) {
  return String(
    conversation?.senderName
    || conversation?.senderWaId
    || conversation?.conversationId
    || "WhatsApp conversation",
  ).trim() || "WhatsApp conversation";
}

function buildWhatsAppHistoryConversationMeta(conversation) {
  const parts = [];
  const senderWaId = String(conversation?.senderWaId || "").trim();
  const lastMessageAt = formatAdminDateTime(conversation?.lastMessageAt || "");
  const metadata = conversation?.metadata && typeof conversation.metadata === "object" ? conversation.metadata : {};
  const imported = String(metadata.source || "").trim() === "manual_import"
    || Boolean(metadata.importedAt || metadata.imported_at);

  if (senderWaId) {
    parts.push(senderWaId);
  }
  if (imported) {
    parts.push("Imported");
  }
  if (lastMessageAt) {
    parts.push(lastMessageAt);
  }

  return parts.join(" · ");
}

function createWhatsAppHistoryEmptyState(titleText, copyText = "") {
  const emptyState = document.createElement("div");
  emptyState.className = "whatsapp-history-empty";

  const title = document.createElement("h3");
  title.textContent = titleText;
  emptyState.append(title);

  if (copyText) {
    const copy = document.createElement("p");
    copy.textContent = copyText;
    emptyState.append(copy);
  }

  return emptyState;
}

function createWhatsAppHistoryDiagnosticNotice(diagnostic) {
  const notice = document.createElement("article");
  notice.className = `whatsapp-history-diagnostic is-${diagnostic.tone}`;

  const title = document.createElement("h3");
  title.textContent = diagnostic.title || "WhatsApp history notice";

  const message = document.createElement("p");
  message.textContent = diagnostic.message || "";

  notice.append(title, message);
  return notice;
}

function createWhatsAppHistoryConversationButton(conversation, isSelected) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "whatsapp-history-conversation";
  button.dataset.conversationId = conversation.conversationId;
  button.setAttribute("role", "listitem");
  button.setAttribute("aria-pressed", String(isSelected));

  const avatar = document.createElement("span");
  avatar.className = "whatsapp-history-avatar";
  avatar.textContent = deriveInitialsLabel(buildWhatsAppHistoryConversationTitle(conversation), "WA");

  const copy = document.createElement("span");
  copy.className = "whatsapp-history-conversation-copy";

  const titleRow = document.createElement("span");
  titleRow.className = "whatsapp-history-conversation-title-row";

  const title = document.createElement("strong");
  title.textContent = buildWhatsAppHistoryConversationTitle(conversation);

  titleRow.append(title);

  const metadata = conversation.metadata && typeof conversation.metadata === "object" ? conversation.metadata : {};
  if (String(metadata.source || "").trim() === "manual_import" || metadata.importedAt || metadata.imported_at) {
    const badge = document.createElement("span");
    badge.className = "whatsapp-history-source-badge";
    badge.textContent = "Imported";
    titleRow.append(badge);
  }

  const preview = document.createElement("span");
  preview.className = "whatsapp-history-preview";
  preview.textContent = conversation.lastMessageText || "No message preview";

  const meta = document.createElement("span");
  meta.className = "whatsapp-history-meta";
  meta.textContent = buildWhatsAppHistoryConversationMeta(conversation);

  copy.append(titleRow, preview, meta);
  button.append(avatar, copy);
  return button;
}

function createWhatsAppHistoryMessage(message) {
  const direction = resolveWhatsAppHistoryMessageDirection(message);
  const item = document.createElement("div");
  item.className = `whatsapp-history-message is-${direction}`;

  const bubble = document.createElement("div");
  bubble.className = "whatsapp-history-bubble";

  const text = document.createElement("p");
  text.textContent = message.text;

  const meta = document.createElement("span");
  meta.className = "whatsapp-history-message-meta";
  const timestamp = formatAdminDateTime(message.messageAt);
  const directionLabel = direction === "outbound" ? "Business" : "Customer";
  const senderLabel = message.importSenderName || directionLabel;
  meta.textContent = timestamp ? `${senderLabel} · ${timestamp}` : senderLabel;

  bubble.append(text, meta);
  item.append(bubble);

  if (direction === "inbound" && message.suggestedReply) {
    const suggestion = document.createElement("div");
    suggestion.className = "whatsapp-history-suggestion";

    const suggestionHead = document.createElement("div");
    suggestionHead.className = "whatsapp-history-suggestion-head";

    const label = document.createElement("span");
    label.textContent = "Suggested reply";
    suggestionHead.append(label);

    if (message.approvalStatus) {
      const status = document.createElement("span");
      status.className = "whatsapp-history-suggestion-status";
      status.textContent = message.approvalStatus === "sent"
        ? "Sent"
        : message.approvalStatus === "skipped"
          ? "Skipped"
          : "Draft";
      suggestionHead.append(status);
    }

    const suggestionText = document.createElement("p");
    suggestionText.textContent = message.suggestedReply;

    suggestion.append(suggestionHead, suggestionText);

    if (message.approvalReviewUrl && message.approvalStatus !== "sent") {
      const reviewLink = document.createElement("a");
      reviewLink.className = "whatsapp-history-suggestion-link";
      reviewLink.href = message.approvalReviewUrl;
      reviewLink.textContent = "Review reply";
      suggestion.append(reviewLink);
    }

    item.append(suggestion);
  }

  return item;
}

function scrollWhatsAppHistoryMessagesToBottom() {
  const container = elements.whatsappHistoryMessages;
  if (!container) {
    return;
  }

  window.requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight;
  });
}

function renderWhatsAppHistory(feature = getSelectedFeature()) {
  if (!elements.whatsappHistorySection) {
    return;
  }

  const conversations = getWhatsAppHistoryConversations();
  const selectedConversation = getSelectedWhatsAppHistoryConversation();
  const isLoading = Boolean(state.whatsappHistoryLoading);
  const isImporting = Boolean(state.whatsappHistoryImportBusy);
  const isDeleting = Boolean(state.whatsappHistoryDeleteBusy);
  const errorText = String(state.whatsappHistoryError || "").trim();
  const selectedFileCount = elements.whatsappHistoryFileInput?.files?.length || 0;

  if (elements.whatsappHistoryFileInput) {
    elements.whatsappHistoryFileInput.disabled = isImporting || isDeleting || !isSignedIn() || !isWhatsAppFeature(feature);
  }
  if (elements.whatsappHistoryImportStatus) {
    const importError = String(state.whatsappHistoryImportError || "").trim();
    const importStatus = String(state.whatsappHistoryImportStatus || "").trim();
    elements.whatsappHistoryImportStatus.textContent = importError
      || importStatus
      || (selectedFileCount ? `${selectedFileCount} chat file${selectedFileCount === 1 ? "" : "s"} selected` : "");
    elements.whatsappHistoryImportStatus.classList.toggle("is-warning", Boolean(importError));
  }

  if (elements.whatsappHistoryDiagnostics) {
    const diagnostics = getCurrentWhatsAppHistory()?.diagnostics || [];
    elements.whatsappHistoryDiagnostics.classList.toggle("is-hidden", !diagnostics.length);
    elements.whatsappHistoryDiagnostics.replaceChildren(
      ...diagnostics.map(createWhatsAppHistoryDiagnosticNotice),
    );
  }

  if (elements.whatsappHistoryConversationList) {
    if (isLoading && !conversations.length) {
      elements.whatsappHistoryConversationList.replaceChildren(
        createWhatsAppHistoryEmptyState("Loading history", "Fetching saved WhatsApp conversations."),
      );
    } else if (errorText) {
      elements.whatsappHistoryConversationList.replaceChildren(
        createWhatsAppHistoryEmptyState("Couldn’t load history", errorText),
      );
    } else if (!conversations.length) {
      elements.whatsappHistoryConversationList.replaceChildren(
        createWhatsAppHistoryEmptyState("No saved conversations yet", "Live customer messages and imported WhatsApp chat files will appear here."),
      );
    } else {
      elements.whatsappHistoryConversationList.replaceChildren(
        ...conversations.map((conversation) => createWhatsAppHistoryConversationButton(
          conversation,
          selectedConversation?.conversationId === conversation.conversationId,
        )),
      );
    }
  }

  if (elements.whatsappHistorySelectedTitle) {
    elements.whatsappHistorySelectedTitle.textContent = selectedConversation
      ? buildWhatsAppHistoryConversationTitle(selectedConversation)
      : "Select a conversation";
  }
  if (elements.whatsappHistorySelectedMeta) {
    elements.whatsappHistorySelectedMeta.textContent = selectedConversation
      ? buildWhatsAppHistoryConversationMeta(selectedConversation)
      : "";
  }
  if (elements.whatsappHistorySelectedAvatar) {
    elements.whatsappHistorySelectedAvatar.textContent = selectedConversation
      ? deriveInitialsLabel(buildWhatsAppHistoryConversationTitle(selectedConversation), "WA")
      : "WA";
  }
  if (elements.whatsappHistorySelectedCount) {
    elements.whatsappHistorySelectedCount.textContent = selectedConversation
      ? formatWhatsAppMessageCount(selectedConversation.messageCount)
      : "0 messages";
  }
  if (elements.whatsappHistoryDeleteButton) {
    const isDeletingSelected = isDeleting
      && selectedConversation?.conversationId === state.whatsappHistoryDeleteTargetId;
    elements.whatsappHistoryDeleteButton.disabled = (
      isLoading
      || isImporting
      || isDeleting
      || !selectedConversation
      || !isSignedIn()
      || !isWhatsAppFeature(feature)
    );
    elements.whatsappHistoryDeleteButton.classList.toggle("is-loading", isDeletingSelected);
    elements.whatsappHistoryDeleteButton.setAttribute("aria-busy", String(isDeletingSelected));
    elements.whatsappHistoryDeleteButton.textContent = isDeletingSelected ? "Deleting..." : "Delete";
  }

  if (elements.whatsappHistoryMessages) {
    const messages = selectedConversation?.messages || [];
    if (isLoading && !selectedConversation) {
      elements.whatsappHistoryMessages.replaceChildren(
        createWhatsAppHistoryEmptyState("Loading messages"),
      );
    } else if (errorText && !selectedConversation) {
      elements.whatsappHistoryMessages.replaceChildren(
        createWhatsAppHistoryEmptyState("No messages to show"),
      );
    } else if (!selectedConversation) {
      elements.whatsappHistoryMessages.replaceChildren(
        createWhatsAppHistoryEmptyState("No conversation selected"),
      );
    } else if (!messages.length) {
      elements.whatsappHistoryMessages.replaceChildren(
        createWhatsAppHistoryEmptyState("No saved messages in this conversation"),
      );
    } else {
      elements.whatsappHistoryMessages.replaceChildren(...messages.map(createWhatsAppHistoryMessage));
      scrollWhatsAppHistoryMessagesToBottom();
    }
  }
}

function selectWhatsAppHistoryConversation(conversationId) {
  const normalizedId = String(conversationId || "").trim();
  if (!normalizedId) {
    return;
  }

  state.whatsappHistorySelectedConversationId = normalizedId;
  renderWhatsAppHistory();
}

function removeWhatsAppConversationFromState(conversationId) {
  const normalizedId = String(conversationId || "").trim();
  const history = getCurrentWhatsAppHistory();
  if (!normalizedId || !history) {
    return;
  }

  const conversations = history.conversations.filter((conversation) => (
    conversation.conversationId !== normalizedId
  ));
  state.whatsappHistory = {
    ...history,
    conversationCount: conversations.length,
    messageCount: conversations.reduce((total, conversation) => total + conversation.messageCount, 0),
    conversations,
  };
  if (state.whatsappHistorySelectedConversationId === normalizedId) {
    state.whatsappHistorySelectedConversationId = conversations[0]?.conversationId || "";
  }
}

function deleteSelectedWhatsAppHistoryConversation() {
  const conversation = getSelectedWhatsAppHistoryConversation();
  if (!conversation || state.whatsappHistoryDeleteBusy) {
    return;
  }

  const title = buildWhatsAppHistoryConversationTitle(conversation);
  const messageCount = formatWhatsAppMessageCount(conversation.messageCount);
  openAuthAlert(
    "Delete conversation?",
    `Delete ${title} from saved WhatsApp history? This removes ${messageCount}, and the scheduler will no longer scan this conversation unless it is imported or received again.`,
    {
      eyebrow: "Delete WhatsApp history",
      icon: "!",
      tone: "warning",
      buttonLabel: "Delete",
      primaryTone: "danger",
      secondaryButtonLabel: "Cancel",
      returnFocus: elements.whatsappHistoryDeleteButton,
      focusTarget: "secondary",
      onPrimary: () => {
        void confirmWhatsAppHistoryConversationDelete(conversation.conversationId);
      },
    },
  );
}

async function confirmWhatsAppHistoryConversationDelete(conversationId) {
  const normalizedId = String(conversationId || "").trim();
  if (!normalizedId || state.whatsappHistoryDeleteBusy) {
    return;
  }

  state.whatsappHistoryDeleteBusy = true;
  state.whatsappHistoryDeleteTargetId = normalizedId;
  state.whatsappHistoryError = "";
  renderWhatsAppHistory();

  let didSucceed = false;
  try {
    await apiRequest(`/api/whatsapp/history/conversations/${encodeURIComponent(normalizedId)}`, {
      method: "DELETE",
      headers: getSessionAuthHeaders(),
    });
    removeWhatsAppConversationFromState(normalizedId);
    didSucceed = true;
    await refreshWhatsAppHistory({ force: true });
  } catch (error) {
    openAuthAlert(
      "Couldn’t delete conversation",
      formatApiErrorMessage(error, "We couldn’t delete that conversation right now."),
      {
        eyebrow: "Delete WhatsApp history",
      },
    );
  } finally {
    state.whatsappHistoryDeleteBusy = false;
    state.whatsappHistoryDeleteTargetId = "";
    renderWhatsAppHistory(getSelectedFeature());
    if (didSucceed) {
      setStatus("Conversation deleted.");
    }
  }
}

async function readWhatsAppHistoryImportFile(file) {
  const content = await file.text();
  return {
    name: String(file.name || "whatsapp-chat.txt").trim() || "whatsapp-chat.txt",
    content,
  };
}

function isWhatsAppHistoryTxtExport(file) {
  const fileName = String(file?.name || "").trim().toLowerCase();
  return fileName.endsWith(".txt");
}

async function importWhatsAppHistoryExports() {
  const feature = getSelectedFeature();
  if (!isSignedIn() || !isWhatsAppFeature(feature) || state.whatsappHistoryImportBusy) {
    return;
  }

  const files = Array.from(elements.whatsappHistoryFileInput?.files || []);
  if (!files.length) {
    state.whatsappHistoryImportError = "Choose a WhatsApp .txt export first.";
    state.whatsappHistoryImportStatus = "";
    renderWhatsAppHistory(feature);
    elements.whatsappHistoryFileInput?.focus();
    return;
  }
  const unsupportedFiles = files.filter((file) => !isWhatsAppHistoryTxtExport(file));
  if (unsupportedFiles.length) {
    state.whatsappHistoryImportError = "Only .txt files exported from WhatsApp are supported.";
    state.whatsappHistoryImportStatus = "";
    if (elements.whatsappHistoryFileInput) {
      elements.whatsappHistoryFileInput.value = "";
    }
    renderWhatsAppHistory(feature);
    elements.whatsappHistoryFileInput?.focus();
    return;
  }

  state.whatsappHistoryImportBusy = true;
  state.whatsappHistoryImportError = "";
  state.whatsappHistoryImportStatus = `Reading ${files.length} WhatsApp .txt export${files.length === 1 ? "" : "s"}...`;
  renderWhatsAppHistory(feature);

  try {
    const importFiles = await Promise.all(files.map(readWhatsAppHistoryImportFile));
    state.whatsappHistoryImportStatus = "Importing WhatsApp history...";
    renderWhatsAppHistory(feature);

    const response = await apiRequest("/api/whatsapp/history/import", {
      method: "POST",
      headers: getSessionAuthHeaders(),
      timeoutMs: 180000,
      body: {
        files: importFiles,
      },
    });

    const imports = Array.isArray(response.imports) ? response.imports : [];
    const firstImportedConversationId = imports.find((item) => item?.conversationId)?.conversationId || "";
    if (firstImportedConversationId) {
      state.whatsappHistorySelectedConversationId = firstImportedConversationId;
    }
    if (elements.whatsappHistoryFileInput) {
      elements.whatsappHistoryFileInput.value = "";
    }
    state.whatsappHistoryImportStatus = buildWhatsAppHistoryImportStatusMessage(response);
    setStatus(state.whatsappHistoryImportStatus);
    await refreshWhatsAppHistory({ force: true });
  } catch (error) {
    if (isAbortError(error)) {
      state.whatsappHistoryImportError = "The import is taking longer than expected. Refresh history in a moment to check the saved messages.";
      state.whatsappHistoryImportStatus = "";
      setStatus("WhatsApp history import may still be processing.");
    } else {
      state.whatsappHistoryImportError = formatApiErrorMessage(error, "We couldn’t import that WhatsApp chat file.");
      state.whatsappHistoryImportStatus = "";
      setStatus("WhatsApp history import failed.");
    }
  } finally {
    if (elements.whatsappHistoryFileInput) {
      elements.whatsappHistoryFileInput.value = "";
    }
    state.whatsappHistoryImportBusy = false;
    renderWhatsAppHistory(getSelectedFeature());
    updateFeatureStudioHeader();
  }
}

async function refreshWhatsAppHistory(options = {}) {
  if (!isSignedIn()) {
    return null;
  }

  const feature = getSelectedFeature();
  if (!isWhatsAppFeature(feature)) {
    return null;
  }

  if (whatsappHistoryRefreshPromise && !options.force) {
    return whatsappHistoryRefreshPromise;
  }

  state.whatsappHistoryLoading = true;
  state.whatsappHistoryError = "";
  state.whatsappHistoryEmail = normalizeEmail(activeEmail);
  renderWhatsAppHistory(feature);

  whatsappHistoryRefreshPromise = (async () => {
    try {
      const response = await apiRequest("/api/whatsapp/history", {
        headers: getSessionAuthHeaders(),
        timeoutMs: 20000,
      });
      const history = normalizeWhatsAppHistoryPayload(response);
      state.whatsappHistory = history;
      state.whatsappHistoryLoadedAt = Date.now();
      state.whatsappHistoryEmail = normalizeEmail(activeEmail);
      if (!history.conversations.some((conversation) => (
        conversation.conversationId === state.whatsappHistorySelectedConversationId
      ))) {
        state.whatsappHistorySelectedConversationId = history.conversations[0]?.conversationId || "";
      }
      setStatus(`Loaded ${formatWhatsAppMessageCount(history.messageCount)}.`);
      return history;
    } catch (error) {
      state.whatsappHistoryError = formatApiErrorMessage(error, "We couldn’t load the saved WhatsApp history.");
      setStatus("WhatsApp history could not be loaded.");
      return null;
    } finally {
      state.whatsappHistoryLoading = false;
      whatsappHistoryRefreshPromise = null;
      renderWhatsAppHistory(getSelectedFeature());
      updateFeatureStudioHeader();
    }
  })();

  return whatsappHistoryRefreshPromise;
}

function openWhatsAppHistory() {
  const feature = getSelectedFeature();
  if (!feature || !isWhatsAppFeature(feature)) {
    return;
  }

  state.featureStudioView = "history";
  closeMenu();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, "history");
  renderApp();
  window.scrollTo(0, 0);
  void refreshWhatsAppHistory({ force: !getCurrentWhatsAppHistory() });
}

function hasFeatureConfigChanges(feature = getSelectedFeature()) {
  if (!feature) {
    return false;
  }

  const currentPrompt = feature?.prompt || getSelectedPrompt();
  const savedPrompt = getSavedFeaturePrompt(feature);
  const promptKeys = Object.keys(DEFAULT_PROMPT);
  if (promptKeys.some((key) => String(currentPrompt[key] || "") !== String(savedPrompt[key] || ""))) {
    return true;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const savedSettings = getSavedFeatureSettings(feature);
  const currentManualOnly = normalizeMonitorManualOnly(currentSettings.manualOnly);
  const savedManualOnly = normalizeMonitorManualOnly(savedSettings.manualOnly);
  const defaultSettings = isMonitorFeature(feature)
    ? DEFAULT_MONITOR_SETTINGS
    : isReengagementFeature(feature)
      ? DEFAULT_REENGAGEMENT_SETTINGS
      : isWhatsAppReplyAssistantFeature(feature)
        ? DEFAULT_WHATSAPP_TOOL_SETTINGS
        : DEFAULT_FEATURE_SETTINGS;
  return Object.keys(defaultSettings).some(
    (key) => JSON.stringify(currentSettings[key] ?? "") !== JSON.stringify(savedSettings[key] ?? ""),
  );
}

function isFeatureActivationBusy(feature = getSelectedFeature()) {
  return Boolean(featureActivationBusy && getSelectedFeatureStudioView(feature) === "activation");
}

function isMonitorManualRunBusy(feature = getSelectedFeature()) {
  return Boolean(
    monitorManualRunBusy
    && feature
    && feature.id === monitorManualRunTargetId,
  );
}

function isReengagementDemoRunBusy(feature = getSelectedFeature()) {
  return Boolean(
    reengagementDemoRunBusy
    && feature
    && feature.id === reengagementDemoRunTargetId,
  );
}

function formatFeatureActivationFieldLabel(key) {
  const labels = {
    business_account_id: "WhatsApp Business Account ID",
    phone_number_id: "Phone number ID",
    access_token: "Access token",
    owner_wa_id: "Approval phone number",
  };

  return labels[key] || key;
}

function formatReadableList(items = []) {
  const values = items
    .map((item) => String(item || "").trim())
    .filter(Boolean);

  if (!values.length) {
    return "";
  }

  if (values.length === 1) {
    return values[0];
  }

  if (values.length === 2) {
    return `${values[0]} and ${values[1]}`;
  }

  const last = values[values.length - 1];
  return `${values.slice(0, -1).join(", ")}, and ${last}`;
}

function clearFeatureActivationFieldErrors() {
  state.featureActivationFieldErrors = {};
}

function setFeatureActivationFieldErrors(issues = []) {
  const nextErrors = {};

  for (const issue of issues) {
    if (!issue?.field) {
      continue;
    }

    nextErrors[issue.field] = String(issue.message || issue.title || "").trim();
  }

  state.featureActivationFieldErrors = nextErrors;
}

function clearFeatureActivationFieldError(key) {
  if (!state.featureActivationFieldErrors?.[key]) {
    return;
  }

  const nextErrors = { ...state.featureActivationFieldErrors };
  delete nextErrors[key];
  state.featureActivationFieldErrors = nextErrors;
}

function getFeatureActivationFieldError(key) {
  return String(state.featureActivationFieldErrors?.[key] || "").trim();
}

function getFeatureActivationFieldElement(key) {
  const elementsByKey = {
    business_account_id: elements.featureActivationBusinessAccountIdInput,
    phone_number_id: elements.featureActivationPhoneNumberIdInput,
    access_token: elements.featureActivationAccessTokenInput,
    owner_wa_id: elements.featureActivationOwnerWaIdInput,
  };

  return elementsByKey[key] || null;
}

function getMissingFeatureActivationFields(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  return FEATURE_ACTIVATION_REQUIRED_KEYS.filter((key) => {
    if (key === "access_token") {
      return !normalizePendingAccessToken(whatsapp.access_token) && !whatsapp.access_token_configured;
    }
    return !String(whatsapp[key] || "").trim();
  });
}

function getFeatureActivationTestIssues(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  const businessAccountId = String(whatsapp.business_account_id || "").trim();
  const phoneNumberId = String(whatsapp.phone_number_id || "").trim();
  const accessToken = normalizePendingAccessToken(whatsapp.access_token);
  const ownerWaId = String(whatsapp.owner_wa_id || "").trim();
  const issues = [];

  if (!/^\d+$/.test(businessAccountId)) {
    issues.push({ field: "business_account_id", message: "Enter the WhatsApp Business Account ID Meta gave you.", inline: true });
  }
  if (!/^\d+$/.test(phoneNumberId)) {
    issues.push({ field: "phone_number_id", message: "Enter the Phone Number ID Meta gave you.", inline: true });
  }
  if (!accessToken && !whatsapp.access_token_configured) {
    issues.push({ field: "access_token", message: "Paste an access token for this WhatsApp Business Account.", inline: true });
  }
  if (!/^\d+$/.test(ownerWaId)) {
    issues.push({ field: "owner_wa_id", message: "Enter the phone number that should receive suggested replies.", inline: true });
  }

  return issues;
}

function getFeatureActivationProgress(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  const total = FEATURE_ACTIVATION_REQUIRED_KEYS.length;
  const missingKeys = getMissingFeatureActivationFields(feature);
  const ready = isFeatureSetupComplete(feature)
    ? total
    : FEATURE_ACTIVATION_REQUIRED_KEYS.reduce((count, key) => {
        if (key === "access_token") {
          return count + ((normalizePendingAccessToken(whatsapp.access_token) || whatsapp.access_token_configured) ? 1 : 0);
        }
        return count + (String(whatsapp[key] || "").trim() ? 1 : 0);
      }, 0);
  return {
    total,
    ready,
    missing: isFeatureSetupComplete(feature) ? [] : missingKeys.map((key) => formatFeatureActivationFieldLabel(key)),
    readyRatio: total > 0 ? ready / total : 0,
  };
}

function formatFeatureActivationProgressLabel(feature = getSelectedFeature()) {
  if (isFeatureActivationBusy(feature)) {
    return "Saving setup";
  }

  if (isFeatureActivated(feature)) {
    return "Live";
  }

  if (isFeatureSetupComplete(feature)) {
    return "Setup saved";
  }

  const progress = getFeatureActivationProgress(feature);
  if (progress.ready === 0) {
    return "WhatsApp setup";
  }

  return progress.ready === progress.total ? "Ready to save" : "Setup in progress";
}

function getFeatureActivationNoticeLabel() {
  const notice = String(state.featureActivationNotice || "").trim();
  if (!notice) {
    return "";
  }

  if (/^setup failed\b/i.test(notice)) {
    return "Setup failed";
  }

  if (/^checking\b/i.test(notice)) {
    return "Checking connection";
  }

  if (/^setup saved\b/i.test(notice)) {
    return "Setup saved";
  }

  if (/^whatsapp confirmed\b/i.test(notice)) {
    return "Setup saved";
  }

  if (/^add the missing details\b/i.test(notice) || /^please add\b/i.test(notice)) {
    return "Missing details";
  }

  if (/^replace the confirmation code\b/i.test(notice)) {
    return "Confirmation code";
  }

  if (/^sign in again\b/i.test(notice)) {
    return "Sign in again";
  }

  if (/^connection failed\b/i.test(notice) || /could not|failed|rejected|unavailable|network|timeout|connect/i.test(notice)) {
    return "Connection issue";
  }

  return "Check details";
}

function getFeatureStudioStatusLabel(feature = getSelectedFeature(), view = getSelectedFeatureStudioView(feature)) {
  if (isFeatureActivationBusy(feature)) {
    return "Saving setup";
  }

  if (view === "activation") {
    return "";
  }

  return getFeatureActivationLabel(feature);
}

function persistClientState() {
  const persistedFeatures = clientState.features.map((feature) => ({
    ...feature,
    setupComplete: Boolean(feature.setupComplete),
    whatsapp: { ...DEFAULT_FEATURE_WHATSAPP },
    savedWhatsApp: { ...DEFAULT_FEATURE_WHATSAPP },
  }));
  persistJson(getClientKey(activeEmail), {
    ...clientState,
    features: persistedFeatures,
  });
}

function capitalizeWords(value) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatCurrency(value, currency = "USD") {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function formatTokenCount(value) {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 0,
  }).format(Math.max(0, Math.round(Number(value || 0))));
}

function formatCompactTokenCount(value) {
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Math.max(0, Number(value || 0)));
}

function formatBillingMonthLabel(monthKey) {
  const value = String(monthKey || "").trim();
  if (!value) {
    return "Unknown month";
  }

  const match = value.match(/^(\d{4})-(\d{2})$/);
  if (!match) {
    return value;
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const parsed = new Date(Date.UTC(year, month - 1, 1));
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

function formatUsageDate(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}

function formatBillingDate(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed).replace(/,\s+(\d{4})$/, ",\u00A0$1");
}

function formatAdminDateTime(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function formatMonitorNextRunDate(value, timeZone = getWorkspaceTimeZone()) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: normalizeMonitorScheduleTimezone(timeZone, getWorkspaceTimeZone()) || undefined,
  }).format(parsed);
}

function parseMonitorDate(value) {
  const text = String(value || "").trim();
  if (!text) {
    return null;
  }

  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getMonitorZonedDateTimeParts(value, timeZone = getWorkspaceTimeZone()) {
  const parsed = value instanceof Date ? new Date(value.getTime()) : parseMonitorDate(value);
  if (!parsed) {
    return null;
  }

  const formatter = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: normalizeMonitorScheduleTimezone(timeZone, getWorkspaceTimeZone()) || undefined,
  });
  const parts = formatter.formatToParts(parsed);
  const readPart = (type) => Number.parseInt(parts.find((part) => part.type === type)?.value || "", 10);
  const year = readPart("year");
  const month = readPart("month");
  const day = readPart("day");
  const hour = readPart("hour");
  const minute = readPart("minute");
  const second = readPart("second");
  if (![year, month, day, hour, minute, second].every(Number.isFinite)) {
    return null;
  }

  return { year, month, day, hour, minute, second };
}

function addMonitorUtcDays(parts, days) {
  const shifted = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days));
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
  };
}

function buildMonitorDateInTimeZone(parts, timeZone = getWorkspaceTimeZone()) {
  const safeTimeZone = normalizeMonitorScheduleTimezone(timeZone, getWorkspaceTimeZone()) || getWorkspaceTimeZone();
  let candidate = new Date(Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour || 0,
    parts.minute || 0,
    parts.second || 0,
  ));

  for (let attempt = 0; attempt < 4; attempt += 1) {
    const zonedParts = getMonitorZonedDateTimeParts(candidate, safeTimeZone);
    if (!zonedParts) {
      return null;
    }

    const desiredUtc = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour || 0,
      parts.minute || 0,
      parts.second || 0,
    );
    const actualUtc = Date.UTC(
      zonedParts.year,
      zonedParts.month - 1,
      zonedParts.day,
      zonedParts.hour || 0,
      zonedParts.minute || 0,
      zonedParts.second || 0,
    );
    const diffMs = desiredUtc - actualUtc;
    if (!diffMs) {
      return candidate;
    }

    candidate = new Date(candidate.getTime() + diffMs);
  }

  return candidate;
}

function resolveMonitorAnchorDate(feature, now = new Date()) {
  const currentTime = now instanceof Date ? new Date(now.getTime()) : new Date();
  if (Number.isNaN(currentTime.getTime())) {
    return null;
  }

  const activatedAt = parseMonitorDate(feature?.activatedAt);
  const settingsSavedAt = parseMonitorDate(feature?.settingsSavedAt || feature?.setupStatus?.settingsSavedAt || "");
  const lastRunAt = parseMonitorDate(feature?.lastRunAt || feature?.setupStatus?.lastRunAt || "");
  const resetAnchor = [activatedAt, settingsSavedAt]
    .filter(Boolean)
    .sort((left, right) => right.getTime() - left.getTime())[0] || null;

  if (lastRunAt && (!resetAnchor || lastRunAt.getTime() >= resetAnchor.getTime())) {
    return lastRunAt;
  }
  if (resetAnchor) {
    return resetAnchor;
  }
  return currentTime;
}

function hasMonitorScheduleConfigChanges(feature = getSelectedFeature()) {
  if (!feature || !isMonitorFeature(feature)) {
    return false;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const savedSettings = getSavedFeatureSettings(feature);
  const currentIntervalMinutes = normalizeMonitorIntervalMinutes(currentSettings.intervalMinutes);
  const savedIntervalMinutes = normalizeMonitorIntervalMinutes(savedSettings.intervalMinutes);
  const currentScheduleTime = normalizeMonitorScheduleTime(currentSettings.scheduleTimeLocal, "");
  const savedScheduleTime = normalizeMonitorScheduleTime(savedSettings.scheduleTimeLocal, "");
  const currentScheduleTimezone = currentScheduleTime
    ? normalizeMonitorScheduleTimezone(currentSettings.scheduleTimezone, getWorkspaceTimeZone()) || getWorkspaceTimeZone()
    : "";
  const savedScheduleTimezone = savedScheduleTime
    ? normalizeMonitorScheduleTimezone(savedSettings.scheduleTimezone, getWorkspaceTimeZone()) || getWorkspaceTimeZone()
    : "";

  return (
    currentManualOnly !== savedManualOnly
    ||
    currentIntervalMinutes !== savedIntervalMinutes
    ||
    normalizeMonitorIntervalDays(currentSettings.intervalDays) !== normalizeMonitorIntervalDays(savedSettings.intervalDays)
    || currentScheduleTime !== savedScheduleTime
    || currentScheduleTimezone !== savedScheduleTimezone
  );
}

function resolveMonitorNextRunAt(feature, now = new Date()) {
  if (!feature || !isMonitorFeature(feature)) {
    return "";
  }

  const explicitNextRunAt = String(feature.nextRunAt || feature.setupStatus?.nextRunAt || "").trim();
  if (explicitNextRunAt && !hasMonitorScheduleConfigChanges(feature)) {
    return explicitNextRunAt;
  }

  const currentTime = now instanceof Date ? new Date(now.getTime()) : new Date();
  if (Number.isNaN(currentTime.getTime())) {
    return "";
  }

  const settings = getSelectedFeatureSettings(feature);
  if (normalizeMonitorManualOnly(settings.manualOnly)) {
    return "";
  }
  const intervalMinutes = normalizeMonitorIntervalMinutes(settings.intervalMinutes);
  const intervalDays = normalizeMonitorIntervalDays(settings.intervalDays);
  const scheduleTimeLocal = intervalMinutes
    ? ""
    : normalizeMonitorScheduleTime(settings.scheduleTimeLocal, getMonitorScheduleTime(feature));
  const scheduleTimezone = normalizeMonitorScheduleTimezone(
    settings.scheduleTimezone,
    getMonitorScheduleTimezone(feature),
  ) || getMonitorScheduleTimezone(feature);
  const anchorDate = resolveMonitorAnchorDate(feature, currentTime);
  if (!anchorDate) {
    return "";
  }

  if (intervalMinutes) {
    const intervalMs = intervalMinutes * 60 * 1000;
    const firstSlot = new Date(anchorDate.getTime() + intervalMs);
    if (firstSlot.getTime() > currentTime.getTime()) {
      return firstSlot.toISOString();
    }

    const elapsedCycles = Math.floor((currentTime.getTime() - firstSlot.getTime()) / intervalMs);
    const candidate = new Date(firstSlot.getTime() + elapsedCycles * intervalMs);
    return candidate.getTime() <= currentTime.getTime()
      ? new Date(candidate.getTime() + intervalMs).toISOString()
      : candidate.toISOString();
  }

  if (!scheduleTimeLocal) {
    const intervalMs = intervalDays * 24 * 60 * 60 * 1000;
    const firstSlot = new Date(anchorDate.getTime() + intervalMs);
    if (firstSlot.getTime() > currentTime.getTime()) {
      return firstSlot.toISOString();
    }

    const elapsedCycles = Math.floor((currentTime.getTime() - firstSlot.getTime()) / intervalMs);
    return new Date(firstSlot.getTime() + elapsedCycles * intervalMs).toISOString();
  }

  const [hour, minute] = scheduleTimeLocal.split(":").map((value) => Number.parseInt(value, 10));
  const baseLocal = getMonitorZonedDateTimeParts(anchorDate, scheduleTimezone);
  if (!baseLocal) {
    return "";
  }

  const nextLocalDate = addMonitorUtcDays(baseLocal, intervalDays);
  const buildSlot = (localDate) => buildMonitorDateInTimeZone({
    ...localDate,
    hour,
    minute,
    second: 0,
  }, scheduleTimezone);

  const nextSlot = buildSlot(nextLocalDate);
  if (!nextSlot) {
    return "";
  }
  if (nextSlot.getTime() > currentTime.getTime()) {
    return nextSlot.toISOString();
  }

  const currentLocal = getMonitorZonedDateTimeParts(currentTime, scheduleTimezone);
  if (!currentLocal) {
    return nextSlot.toISOString();
  }

  const elapsedDays = Math.max(
    0,
    Math.floor(
      (
        Date.UTC(currentLocal.year, currentLocal.month - 1, currentLocal.day)
        - Date.UTC(nextLocalDate.year, nextLocalDate.month - 1, nextLocalDate.day)
      ) / (24 * 60 * 60 * 1000),
    ),
  );
  const elapsedCycles = Math.floor(elapsedDays / intervalDays);
  let candidateLocalDate = addMonitorUtcDays(nextLocalDate, elapsedCycles * intervalDays);
  let candidateSlot = buildSlot(candidateLocalDate);
  if (!candidateSlot) {
    return nextSlot.toISOString();
  }
  if (candidateSlot.getTime() <= currentTime.getTime()) {
    candidateLocalDate = addMonitorUtcDays(candidateLocalDate, intervalDays);
    candidateSlot = buildSlot(candidateLocalDate);
  }

  return candidateSlot ? candidateSlot.toISOString() : nextSlot.toISOString();
}

function getUtcDateParts(value) {
  const parsed = new Date(String(value || "").trim());
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return {
    year: parsed.getUTCFullYear(),
    month: parsed.getUTCMonth(),
    day: parsed.getUTCDate(),
  };
}

function getDaysInUtcMonth(year, monthIndex) {
  return new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
}

function getNextBillingPaymentDate(report) {
  const registeredAt = String(report?.registeredAt || "").trim();
  if (!registeredAt) {
    return null;
  }

  const registration = getUtcDateParts(registeredAt);
  if (!registration) {
    return null;
  }

  const referenceMoment = report?.asOf ? new Date(report.asOf) : new Date();
  if (Number.isNaN(referenceMoment.getTime())) {
    return null;
  }

  const referenceYear = referenceMoment.getUTCFullYear();
  const referenceMonth = referenceMoment.getUTCMonth();
  const referenceDay = referenceMoment.getUTCDate();
  const referenceStartOfDay = Date.UTC(referenceYear, referenceMonth, referenceDay);
  const targetDay = registration.day;

  const buildCandidate = (year, monthIndex) => {
    const day = Math.min(targetDay, getDaysInUtcMonth(year, monthIndex));
    return Date.UTC(year, monthIndex, day);
  };

  let candidate = buildCandidate(referenceYear, referenceMonth);
  if (candidate < referenceStartOfDay) {
    const nextMonth = new Date(Date.UTC(referenceYear, referenceMonth + 1, 1));
    candidate = buildCandidate(nextMonth.getUTCFullYear(), nextMonth.getUTCMonth());
  }

  return new Date(candidate);
}

function formatModelName(value) {
  const model = String(value || "").trim();
  if (!model) {
    return "Unknown model";
  }

  const withoutSnapshotDate = model.replace(/-\d{4}-\d{2}-\d{2}$/u, "");
  return withoutSnapshotDate.replace(/^gpt-/i, "GPT-").replace(/^gpt/i, "GPT");
}

function normalizeBillingModel(model = {}) {
  const usageDatesSource = Array.isArray(model.usageDates) ? model.usageDates : [];
  const baseCostUsd = Number(model.baseCostUsd ?? model.base_cost_usd ?? 0) || 0;
  const inputChargeUsd = Number(model.inputChargeUsd ?? model.input_charge_usd ?? 0) || 0;
  const outputChargeUsd = Number(model.outputChargeUsd ?? model.output_charge_usd ?? 0) || 0;
  return {
    model: String(model.model || model.name || "Unknown model").trim() || "Unknown model",
    tokensUsed: Math.max(0, Math.round(Number(model.tokensUsed ?? model.tokens ?? model.token_count ?? 0))),
    baseCostUsd,
    inputTokensUsed: Math.max(0, Math.round(Number(model.inputTokensUsed ?? model.input_tokens ?? 0))),
    outputTokensUsed: Math.max(0, Math.round(Number(model.outputTokensUsed ?? model.output_tokens ?? 0))),
    inputChargeUsd,
    outputChargeUsd,
    chargeUsd: Number(model.chargeUsd ?? model.charge_usd ?? (inputChargeUsd + outputChargeUsd || baseCostUsd)) || 0,
    usageCount: Math.max(0, Math.round(Number(model.usageCount ?? model.usage_count ?? usageDatesSource.length ?? 0))),
    usageDates: usageDatesSource
      .map((date) => String(date || "").trim())
      .filter(Boolean),
    firstUsedAt: String(model.firstUsedAt ?? model.first_used_at ?? "").trim(),
    lastUsedAt: String(model.lastUsedAt ?? model.last_used_at ?? "").trim(),
  };
}

function normalizeBillingTool(tool = {}) {
  const modelsSource = Array.isArray(tool.models) ? tool.models : [];
  const models = modelsSource.map(normalizeBillingModel).filter(Boolean);
  const usageDates = Array.isArray(tool.usageDates)
    ? tool.usageDates
    : Array.from(new Set(models.flatMap((model) => model.usageDates || [])));
  const tokensUsed = models.reduce((sum, model) => sum + Math.max(0, Number(model.tokensUsed || 0)), 0);
  const baseCostUsd = models.reduce((sum, model) => sum + Math.max(0, Number(model.baseCostUsd || 0)), 0);
  const inputTokensUsed = models.reduce((sum, model) => sum + Math.max(0, Number(model.inputTokensUsed || 0)), 0);
  const outputTokensUsed = models.reduce((sum, model) => sum + Math.max(0, Number(model.outputTokensUsed || 0)), 0);
  const inputChargeUsd = models.reduce((sum, model) => sum + Math.max(0, Number(model.inputChargeUsd || 0)), 0);
  const outputChargeUsd = models.reduce((sum, model) => sum + Math.max(0, Number(model.outputChargeUsd || 0)), 0);
  const toolId = String(tool.toolId || tool.tool_id || tool.featureId || tool.feature_id || "").trim();
  const toolName = String(tool.toolName || tool.tool_name || tool.name || formatDisplayNameFromId(toolId)).trim() || formatDisplayNameFromId(toolId);

  return {
    toolId,
    toolName,
    tokensUsed,
    baseCostUsd: Number(baseCostUsd.toFixed(2)),
    inputTokensUsed,
    outputTokensUsed,
    inputChargeUsd: Number(inputChargeUsd.toFixed(2)),
    outputChargeUsd: Number(outputChargeUsd.toFixed(2)),
    chargeUsd: Number(Number(tool.chargeUsd ?? 0).toFixed(2)),
    minimumApplied: Boolean(tool.minimumApplied),
    currency: String(tool.currency || "USD").trim() || "USD",
    usageCount: Math.max(0, Math.round(Number(tool.usageCount ?? usageDates.length ?? 0))),
    usageDates: usageDates.map((date) => String(date || "").trim()).filter(Boolean),
    models: models
      .sort((left, right) => right.tokensUsed - left.tokensUsed || left.model.localeCompare(right.model)),
  };
}

function normalizeBillingMonth(month = {}) {
  const toolsSource = Array.isArray(month.tools) ? month.tools : [];
  const modelsSource = Array.isArray(month.models) ? month.models : [];
  const tools = toolsSource.length
    ? toolsSource.map(normalizeBillingTool).filter(Boolean)
    : modelsSource.length
      ? [{
          toolId: String(month.toolId || month.tool_id || "").trim() || "unassigned",
          toolName: String(month.toolName || month.tool_name || month.name || "Unassigned tool").trim() || "Unassigned tool",
          models: modelsSource,
          chargeUsd: month.chargeUsd,
          minimumApplied: month.minimumApplied,
          currency: month.currency,
          usageCount: month.usageCount,
          usageDates: month.usageDates,
        }].map(normalizeBillingTool)
      : [];
  const currentMonthLabel = formatBillingMonthLabel(month.month);
  const tokensUsed = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.tokensUsed || 0)), 0);
  const baseCostUsd = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.baseCostUsd || 0)), 0);
  const inputTokensUsed = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.inputTokensUsed || 0)), 0);
  const outputTokensUsed = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.outputTokensUsed || 0)), 0);
  const inputChargeUsd = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.inputChargeUsd || 0)), 0);
  const outputChargeUsd = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.outputChargeUsd || 0)), 0);
  const usageDates = Array.isArray(month.usageDates)
    ? month.usageDates
    : Array.from(new Set(tools.flatMap((tool) => tool.usageDates || [])));
  const flattenedModels = tools.flatMap((tool) => tool.models || []);
  const minimumMonthlyCharge = Number(month.minimumMonthlyCharge ?? DEFAULT_BILLING_MINIMUM) || DEFAULT_BILLING_MINIMUM;
  const rawChargeUsd = Number(Number(month.chargeUsd ?? 0).toFixed(2));
  const calculatedChargeUsd = tools.reduce((sum, tool) => sum + Math.max(0, Number(tool.chargeUsd || 0)), 0);
  const chargeUsd = Number((rawChargeUsd || calculatedChargeUsd).toFixed(2));
  const usageChargeUsd = Number(calculatedChargeUsd.toFixed(2));

  return {
    month: String(month.month || "").trim(),
    label: String(month.label || currentMonthLabel).trim() || currentMonthLabel,
    tokensUsed,
    baseCostUsd: Number(baseCostUsd.toFixed(2)),
    inputTokensUsed,
    outputTokensUsed,
    inputChargeUsd: Number(inputChargeUsd.toFixed(2)),
    outputChargeUsd: Number(outputChargeUsd.toFixed(2)),
    usageChargeUsd,
    chargeUsd,
    minimumApplied: Boolean(month.minimumApplied),
    minimumMonthlyCharge,
    currency: String(month.currency || "USD").trim() || "USD",
    usageCount: Math.max(0, Math.round(Number(month.usageCount ?? usageDates.length ?? 0))),
    usageDates: usageDates.map((date) => String(date || "").trim()).filter(Boolean),
    toolCount: tools.length,
    tools: tools
      .sort((left, right) => right.tokensUsed - left.tokensUsed || left.toolName.localeCompare(right.toolName)),
    models: flattenedModels
      .sort((left, right) => right.tokensUsed - left.tokensUsed || left.model.localeCompare(right.model)),
  };
}

function normalizeBillingReport(report = {}) {
  const currentMonth = normalizeBillingMonth(report.currentMonth || {});
  const history = Array.isArray(report.history) ? report.history.map(normalizeBillingMonth) : [];
  const billingPlan = report && typeof report.billingPlan === "object" ? report.billingPlan : {};
  const billingPlanMinimumCents = Number(billingPlan.monthlyMinimumCents ?? NaN);
  const minimumMonthlyCharge = Number(
    report.minimumMonthlyCharge ?? (Number.isFinite(billingPlanMinimumCents) ? billingPlanMinimumCents / 100 : DEFAULT_BILLING_MINIMUM),
  ) || DEFAULT_BILLING_MINIMUM;
  const currency = String(report.currency || billingPlan.currency || currentMonth.currency || "USD").trim() || "USD";
  const usageDates = Array.isArray(report.usageDates) ? report.usageDates : [];
  const registeredAt = String(report.registeredAt || "").trim();

  return {
    ok: Boolean(report.ok),
    email: normalizeEmail(report.email || activeEmail),
    currency,
    minimumMonthlyCharge,
    source: String(report.source || "empty"),
    sourceLabel: String(report.sourceLabel || "").trim()
      || (report.source === "database" ? "Latest billing data" : report.source === "defaults" ? "Sample billing data" : "Billing data"),
    currentMonth: {
      ...currentMonth,
      currency,
      chargeUsd: Number(Number(report.currentMonth?.chargeUsd ?? currentMonth.chargeUsd ?? minimumMonthlyCharge).toFixed(2)),
    },
    history: history
      .filter(Boolean)
      .sort((left, right) => right.month.localeCompare(left.month)),
    usageDates: usageDates.map((date) => String(date || "").trim()).filter(Boolean),
    registeredAt,
    billingPlan: {
      currency,
      monthlyMinimumCents: Number.isFinite(billingPlanMinimumCents) ? Math.max(0, Math.round(billingPlanMinimumCents)) : Math.round(minimumMonthlyCharge * 100),
    },
    asOf: String(report.asOf || "").trim(),
  };
}

function getBillingPolicyLabel(report) {
  const minimum = formatCurrency(report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM, report?.currency || "USD");
  return `Usage-based billing · ${minimum} monthly minimum across all tools`;
}

function buildBillingToolCatalog() {
  const features = Array.isArray(clientState?.features) ? clientState.features : [];
  return features.map((feature, index) => {
    const pricing = getFeaturePricing(feature);
    return {
      toolId: String(feature?.id || `feature-${index + 1}`).trim(),
      toolName: String(feature?.name || `Tool ${index + 1}`).trim(),
      pricing,
      status: getFeatureActivationLabel(feature),
    };
  });
}

function mergeBillingMonthWithCatalog(month, catalog = []) {
  const toolMap = new Map();
  for (const tool of Array.isArray(month?.tools) ? month.tools : []) {
    const normalizedTool = normalizeBillingTool(tool);
    const key = normalizedTool.toolId || normalizedTool.toolName;
    if (!key) {
      continue;
    }
    toolMap.set(key, normalizedTool);
  }

  const tools = [];
  const seenKeys = new Set();
  const fallbackUnassignedTool = toolMap.get("unassigned") || toolMap.get("shared") || null;
  for (const catalogTool of catalog) {
    const key = catalogTool.toolId || catalogTool.toolName;
    if (!key) {
      continue;
    }
    const existing = toolMap.get(key) || (catalog.length === 1 ? fallbackUnassignedTool : null);
    const tool = existing
      ? {
          ...existing,
          toolId: key,
          toolName: catalogTool.toolName || existing.toolName,
        }
      : {
          toolId: key,
          toolName: catalogTool.toolName || formatDisplayNameFromId(key),
          tokensUsed: 0,
          baseCostUsd: 0,
          inputTokensUsed: 0,
          outputTokensUsed: 0,
          inputChargeUsd: 0,
          outputChargeUsd: 0,
          chargeUsd: 0,
          minimumApplied: false,
          currency: month?.currency || "USD",
          usageCount: 0,
          usageDates: [],
          models: [],
        };

    tools.push(tool);
    seenKeys.add(key);
  }

  if (fallbackUnassignedTool && catalog.length === 1) {
    seenKeys.add(fallbackUnassignedTool.toolId || "unassigned");
    seenKeys.add("shared");
  }

  for (const [key, tool] of toolMap.entries()) {
    if (seenKeys.has(key)) {
      continue;
    }

    tools.push(tool);
  }

  const currency = month?.currency || "USD";
  const normalizedTools = tools
    .map((tool) => {
      const usageChargeUsd = Number(tool.inputChargeUsd || 0) + Number(tool.outputChargeUsd || 0);
      const chargeUsd = tool.chargeUsd > 0
        ? Number(tool.chargeUsd.toFixed(2))
        : Number(usageChargeUsd.toFixed(2));
      return {
        ...tool,
        currency,
        chargeUsd,
        minimumApplied: Boolean(tool.minimumApplied),
      };
    })
    .sort((left, right) => right.tokensUsed - left.tokensUsed || left.toolName.localeCompare(right.toolName));

  const flattenedModels = normalizedTools.flatMap((tool) => tool.models || []);
  const tokensUsed = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.tokensUsed || 0)), 0);
  const baseCostUsd = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.baseCostUsd || 0)), 0);
  const inputTokensUsed = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.inputTokensUsed || 0)), 0);
  const outputTokensUsed = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.outputTokensUsed || 0)), 0);
  const inputChargeUsd = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.inputChargeUsd || 0)), 0);
  const outputChargeUsd = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.outputChargeUsd || 0)), 0);
  const usageChargeUsd = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.chargeUsd || 0)), 0);
  const chargeUsd = Number(Number(month?.chargeUsd ?? usageChargeUsd).toFixed(2));
  const usageDates = Array.from(new Set(normalizedTools.flatMap((tool) => tool.usageDates || [])));
  const usageCount = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.usageCount || 0)), 0);
  const minimumApplied = Boolean(month?.minimumApplied);

  return {
    ...month,
    tokensUsed,
    baseCostUsd: Number(baseCostUsd.toFixed(2)),
    inputTokensUsed,
    outputTokensUsed,
    inputChargeUsd: Number(inputChargeUsd.toFixed(2)),
    outputChargeUsd: Number(outputChargeUsd.toFixed(2)),
    usageChargeUsd: Number(usageChargeUsd.toFixed(2)),
    chargeUsd,
    minimumApplied,
    usageCount,
    usageDates,
    toolCount: normalizedTools.length,
    tools: normalizedTools,
    models: flattenedModels
      .sort((left, right) => right.tokensUsed - left.tokensUsed || left.model.localeCompare(right.model)),
  };
}

function enrichBillingReportWithCatalog(report) {
  if (!report) {
    return report;
  }

  const catalog = buildBillingToolCatalog();
  return {
    ...report,
    currentMonth: mergeBillingMonthWithCatalog(report.currentMonth, catalog),
    history: Array.isArray(report.history)
      ? report.history.map((month) => mergeBillingMonthWithCatalog(month, catalog))
      : [],
  };
}

function getBillingStatusCopy(report, hasError, isLoading) {
  if (hasError) {
    return {
      message: "We're having temporary billing issues and we're on it.",
      meta: "",
    };
  }

  if (isLoading) {
    return {
      message: report ? "Checking latest billing..." : "Loading billing data...",
      meta: report ? "Keeping the current numbers visible while this updates." : "This usually takes just a moment.",
    };
  }

  if (report) {
    return {
      message: report.currentMonth?.tools?.length
        ? "Billing data is ready."
        : "No usage has been recorded yet.",
      meta: report.asOf
        ? `Updated ${formatUsageDate(report.asOf) || "recently"}`
        : "Snapshot ready.",
    };
  }

  return {
    message: "No billing data has been loaded yet.",
    meta: "Refresh once billing data is ready.",
  };
}

function buildBillingSummaryText(report) {
  const nextPaymentDate = formatBillingDate(getNextBillingPaymentDate(report));
  const currentMonth = report?.currentMonth;
  const minimum = formatCurrency(report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM, report?.currency || "USD");

  if (!currentMonth) {
    return "Projected payment data will appear here once billing loads.";
  }

  const charged = formatCurrency(currentMonth.chargeUsd, report?.currency || "USD");
  if (!currentMonth.tools?.length || !currentMonth.tokensUsed) {
    if (currentMonth.minimumApplied) {
      return nextPaymentDate
        ? `Billing is based on token usage, with a ${minimum} monthly minimum. Since usage is below the minimum, projected payment is ${charged}. Next payment: ${nextPaymentDate}.`
        : `Billing is based on token usage, with a ${minimum} monthly minimum. Since usage is below the minimum, projected payment is ${charged}.`;
    }
    return nextPaymentDate
      ? `Billing is based on token usage. Projected payment will update as usage is recorded. Next payment: ${nextPaymentDate}.`
      : "Billing is based on token usage. Projected payment will update as usage is recorded.";
  }

  if (currentMonth.minimumApplied) {
    return nextPaymentDate
      ? `Billing is based on token usage, with a ${minimum} monthly minimum. Since usage is below the minimum, projected payment is ${charged} so far. Next payment: ${nextPaymentDate}.`
      : `Billing is based on token usage, with a ${minimum} monthly minimum. Since usage is below the minimum, projected payment is ${charged} so far.`;
  }

  return nextPaymentDate
    ? `Billing is based on token usage. Projected payment is ${charged} so far. Next payment: ${nextPaymentDate}.`
    : `Billing is based on token usage. Projected payment is ${charged} so far.`;
}

function buildBillingHelpBody(report) {
  const minimum = formatCurrency(report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM, report?.currency || "USD");
  const nextPaymentDate = formatBillingDate(getNextBillingPaymentDate(report));
  const helpLines = [
    "We add up usage across all of your tools each month.",
    `Each model has its own input and output usage rate. Your account has a ${minimum} monthly minimum across all tools combined.`,
    `If the month’s usage total stays below ${minimum}, we charge ${minimum}. Once usage goes above it, you pay the higher usage-based total.`,
  ];

  if (nextPaymentDate) {
    helpLines.push(`Your next payment is due on ${nextPaymentDate}.`);
  }

  const fragment = document.createDocumentFragment();
  for (const line of helpLines) {
    const paragraph = document.createElement("p");
    paragraph.textContent = line;
    fragment.append(paragraph);
  }

  return fragment;
}

function getBillingStatusLabel(report) {
  if (!report) {
    return "Loading billing";
  }

  if (report.source === "database" || report.source === "account") {
    return "Latest billing data";
  }

  if (report.source === "defaults") {
    return "Sample billing data";
  }

  if (state.billingLoading) {
    return "Loading billing";
  }

  if (state.billingError) {
    return "Billing unavailable";
  }

  return "Billing data";
}

function setBillingError(message) {
  state.billingError = String(message || "").trim();
  state.billingLoading = false;
}

function syncBillingHelpState() {
  const isOpen = Boolean(state.billingHelpOpen);

  if (elements.billingHelpButton) {
    elements.billingHelpButton.setAttribute("aria-expanded", String(isOpen));
  }

  if (elements.billingHelpPopover) {
    if (billingHelpOpenFrame !== null) {
      window.cancelAnimationFrame(billingHelpOpenFrame);
      billingHelpOpenFrame = null;
    }

    if (billingHelpCloseTimer !== null) {
      window.clearTimeout(billingHelpCloseTimer);
      billingHelpCloseTimer = null;
    }

    if (isOpen) {
      elements.billingHelpPopover.classList.remove("is-hidden");
      document.body.dataset.modal = "billing";

      if (!elements.billingHelpPopover.classList.contains("is-open")) {
        billingHelpOpenFrame = window.requestAnimationFrame(() => {
          elements.billingHelpPopover.classList.add("is-open");
          billingHelpOpenFrame = null;
          elements.billingHelpCloseButton?.focus();
        });
      }

      return;
    }

    elements.billingHelpPopover.classList.remove("is-open");

    if (elements.billingHelpPopover.classList.contains("is-hidden")) {
      if (document.body.dataset.modal === "billing") {
        delete document.body.dataset.modal;
      }

      return;
    }

    billingHelpCloseTimer = window.setTimeout(() => {
      elements.billingHelpPopover.classList.add("is-hidden");
      if (document.body.dataset.modal === "billing") {
        delete document.body.dataset.modal;
      }
      billingHelpCloseTimer = null;
      billingHelpReturnFocus?.focus?.();
      billingHelpReturnFocus = null;
    }, 220);
  }
}

function setBillingHelpOpen(open) {
  if (open) {
    billingHelpReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : elements.billingHelpButton;
  }
  state.billingHelpOpen = Boolean(open);
  syncBillingHelpState();
}

function toggleBillingHelp() {
  setBillingHelpOpen(!state.billingHelpOpen);
}

function closeBillingHelp() {
  if (!state.billingHelpOpen) {
    return;
  }

  setBillingHelpOpen(false);
}

function closePersonalDetailsTips() {
  // The personal details page uses inline guidance now, but the view-routing
  // cleanup still calls this helper when switching panels.
}

function ensureBillingMenuItem() {
  if (!elements.accountMenu) {
    return;
  }

  const existing = elements.accountMenu.querySelector('[data-menu-action="billing"]');
  if (existing) {
    return;
  }

  const billingButton = document.createElement("button");
  billingButton.className = "menu-item";
  billingButton.type = "button";
  billingButton.dataset.menuAction = "billing";
  billingButton.textContent = "Billing";

  const settingsButton = elements.accountMenu.querySelector('[data-menu-action="settings"]');
  if (settingsButton && settingsButton.parentElement === elements.accountMenu) {
    elements.accountMenu.insertBefore(billingButton, settingsButton);
    return;
  }

  const firstAction = elements.accountMenu.querySelector("[data-menu-action]");
  if (firstAction && firstAction.parentElement === elements.accountMenu) {
    elements.accountMenu.insertBefore(billingButton, firstAction);
    return;
  }

  elements.accountMenu.prepend(billingButton);
}

function deriveDisplayName(email) {
  const localPart = normalizeEmail(email).split("@")[0] || "";
  const readable = localPart.replace(/[._-]+/g, " ").trim();
  return readable ? capitalizeWords(readable) : "Client";
}

function deriveInitialsLabel(value, fallback = "C") {
  const source = normalizeText(value);
  if (!source) {
    return fallback;
  }

  const parts = source.split(/\s+/).filter(Boolean);
  const initials = parts.slice(0, 2).map((part) => part[0]).join("");
  return (initials || fallback).toUpperCase();
}

function getDisplayName() {
  return clientState.settings.displayName.trim() || deriveDisplayName(activeEmail);
}

function getWorkspaceName() {
  const workspaceName = clientState.settings.workspaceName.trim();
  if (!workspaceName) {
    return DEFAULT_SETTINGS.workspaceName;
  }

  if (isLegacyWorkspaceName(workspaceName)) {
    return DEFAULT_SETTINGS.workspaceName;
  }

  return workspaceName;
}

function getAvatarLabel() {
  return deriveInitialsLabel(getDisplayName() || activeEmail, "G");
}

function setView(view) {
  const nextView = view === "auth" || view === "app" ? view : "loading";
  document.body.dataset.view = nextView;
  if (nextView !== "app") {
    closePersonalDetailsTips();
    delete document.body.dataset.modal;
  }
  elements.loadingView?.classList.toggle("is-hidden", nextView !== "loading");
  elements.authView.classList.toggle("is-hidden", nextView !== "auth");
  elements.appView.classList.toggle("is-hidden", nextView !== "app");
  syncWhatsAppConnectionPolling();
  syncScheduledActionsPolling();
}

function setStatus(message) {
  if (!elements.saveState) {
    return;
  }

  const text = String(message || "").trim();
  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date());

  elements.saveState.textContent = `${text} · ${time}`;
  elements.saveState.classList.toggle("is-loading", /^checking\b/i.test(text));
}

function clearFeatureActivationNotice() {
  state.featureActivationNotice = "";
}

function setHashForTab(tab, itemId = null, subview = null) {
  const normalizedTab = normalizeTab(tab);
  const url = new URL(window.location.href);
  const encodedSubview = normalizeFeatureStudioView(subview);

  if (itemId && (normalizedTab === "features" || normalizedTab === "simulator")) {
    const parts = [normalizedTab, encodeURIComponent(itemId)];
    if (normalizedTab === "features" && encodedSubview) {
      parts.push(encodeURIComponent(encodedSubview));
    }
    url.hash = parts.join("/");
  } else {
    url.hash = normalizedTab;
  }

  window.history.replaceState({}, "", url);
}

function clearHash() {
  const url = new URL(window.location.href);
  url.hash = "";
  window.history.replaceState({}, "", url);
}

function resolveRouteFromHash() {
  const hash = window.location.hash.replace(/^#/, "").trim();

  if (!hash) {
    return { tab: null, featureId: null, subview: null };
  }

  const [rawTab, ...rest] = hash.split("/");
  const normalized = normalizeTab(rawTab);

  if ((normalized === "features" || normalized === "simulator") && rest.length) {
    const [itemId, maybeSubview, ...remaining] = rest;
    return {
      tab: normalized,
      featureId: decodeURIComponent([itemId, ...remaining].join("/")),
      subview: normalized === "features" ? normalizeFeatureStudioView(decodeURIComponent(maybeSubview || "")) : null,
    };
  }

  if (VALID_TABS.has(normalized)) {
    return { tab: normalized, featureId: null, subview: null };
  }

  return { tab: null, featureId: null, subview: null };
}

function persistLastPrimaryTab() {
  persistJson(LAST_PRIMARY_TAB_KEY, state.lastPrimaryTab);
}

function openSettings(mode = state.settingsMode) {
  state.settingsMode = normalizeSettingsMode(mode);

  state.selectedFeatureId = null;
  closeFeatureStudioMenu();
  closeBillingHelp();
  closePersonalDetailsTips();

  if (state.activeTab !== "settings" && VALID_TABS.has(state.activeTab)) {
    state.lastPrimaryTab = state.activeTab;
    persistLastPrimaryTab();
  }

  state.settingsOpen = true;
  closeMenu();
  setHashForTab("settings");
  renderApp();
  if (state.settingsMode === "users" && isAdminUser()) {
    void refreshAdminUsers();
  }
}

function closeSettings() {
  state.settingsOpen = false;
  closeBillingHelp();
  closePersonalDetailsTips();
  state.activeTab = VALID_TABS.has(state.lastPrimaryTab) && state.lastPrimaryTab !== "settings"
    ? state.lastPrimaryTab
    : "features";
  state.selectedFeatureId = null;
  state.lastPrimaryTab = state.activeTab;
  persistLastPrimaryTab();
  closeMenu();
  setHashForTab(state.activeTab);
  renderApp();
}

function setActiveTab(tab, options = {}) {
  let nextTab = normalizeTab(tab);

  if (nextTab === "settings") {
    openSettings(options.settingsMode || state.settingsMode);
    return;
  }

  if (nextTab === "clients" && !canManageClients()) {
    nextTab = "features";
  }

  if (!VALID_TABS.has(nextTab)) {
    return;
  }

  state.activeTab = nextTab;
  state.lastPrimaryTab = nextTab;
  persistLastPrimaryTab();
  state.settingsOpen = false;
  state.selectedFeatureId = null;
  closeFeatureStudioMenu();
  state.selectedSimulatorId = null;
  closeBillingHelp();
  closePersonalDetailsTips();
  if (options.settingsMode) {
    state.settingsMode = normalizeSettingsMode(options.settingsMode);
  }

  if (options.syncHash !== false) {
    setHashForTab(nextTab);
  }

  closeMenu();
  renderApp();
  if (nextTab === "billing" || nextTab === "pricing") {
    window.scrollTo(0, 0);
  }
  if (nextTab === "billing") {
    void refreshBillingReportForActiveTab();
  }
  if (nextTab === "pricing") {
    void refreshPricingSnapshot();
  }
  if (nextTab === "opportunities") {
    void refreshOpportunities();
  }
  if (nextTab === "clients") {
    void refreshAdminUsers();
  }
}

function setSettingsMode(mode, options = {}) {
  state.settingsMode = normalizeSettingsMode(mode);
  if (options.openSettings !== false) {
    openSettings(state.settingsMode);
    return;
  }

  closeMenu();
  renderApp();
  if (state.settingsMode === "users" && isAdminUser()) {
    void refreshAdminUsers();
  }
}

function toggleMenu(force) {
  state.menuOpen = typeof force === "boolean" ? force : !state.menuOpen;
  elements.accountMenu.classList.toggle("is-hidden", !state.menuOpen);
  elements.accountMenuButton.setAttribute("aria-expanded", String(state.menuOpen));
}

function closeMenu() {
  toggleMenu(false);
}

function splitLines(value) {
  return String(value)
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function appendProfilePromptLines(lines, label, value) {
  const parts = splitLines(value);
  if (!parts.length) {
    return lines;
  }

  const [first, ...rest] = parts;
  lines.push(`${label}: ${first}`);
  lines.push(...rest);
  return lines;
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function buildAccountProfilePromptLines(profile = clientState.profile) {
  const normalized = normalizeAccountProfile(profile);
  const lines = [];
  appendProfilePromptLines(lines, "Business basics", normalized.businessSummary);
  appendProfilePromptLines(lines, "Typical customers", normalized.customerNotes);
  appendProfilePromptLines(lines, "Important notes", normalized.assistantGuidance);
  return lines;
}

function hasAccountProfileContent(profile = clientState.profile) {
  const normalized = normalizeAccountProfile(profile);
  return Boolean(
    normalized.businessSummary
    || normalized.customerNotes
    || normalized.assistantGuidance
  );
}

function buildAccountProfilePreviewText(profile = clientState.profile) {
  const lines = buildAccountProfilePromptLines(profile);
  if (!lines.length) {
    return "";
  }

  return [
    "Your assistant should remember:",
    ...bulletList(lines),
  ].join("\n");
}

function applyRemoteAccountProfile(payload = {}) {
  if (!payload || typeof payload !== "object" || !payload.profile || typeof payload.profile !== "object") {
    return;
  }

  clientState.profile = normalizeAccountProfile(payload.profile);
  persistClientState();
}

function nowIso() {
  return new Date().toISOString();
}

function textHasAny(text, needles) {
  const haystack = String(text || "").toLowerCase();
  return needles.some((needle) => haystack.includes(String(needle).toLowerCase()));
}

function bulletList(lines) {
  return (lines.length ? lines : [""]).map((line) => `- ${line}`);
}

function buildOpening(toneText) {
  const tone = toneText.toLowerCase();

  if (tone.includes("warm") || tone.includes("friendly")) {
    return "Of course";
  }

  if (tone.includes("direct") || tone.includes("concise") || tone.includes("short")) {
    return "Yes";
  }

  if (tone.includes("calm") || tone.includes("steady")) {
    return "Absolutely";
  }

  return "Sure";
}

function buildResponseText(prompt = getSelectedPrompt()) {
  const scenario = SCENARIOS[prompt.scenario] ?? SCENARIOS.availability;

  if (scenario.exactReply) {
    return scenario.ask;
  }

  const opening = buildOpening(prompt.toneGuidance);
  const style = prompt.responseStyle;

  if (style === "detailed") {
    return `${opening}. ${scenario.ask} Happy to help.`;
  }

  return `${opening}. ${scenario.ask}`;
}

function buildCompiledPrompt(feature = getSelectedFeature()) {
  const prompt = feature?.prompt || getSelectedPrompt();
  const sharedProfileLines = buildAccountProfilePromptLines();
  const exampleReplies = splitLines(prompt.exampleReplies);
  const lines = [
    "Client tool draft",
    "",
    `Tool: ${feature?.name || "Unassigned tool"}`,
    `Channel: ${feature?.channel || "Web"}`,
    `Mode: ${feature?.mode || "Default"}`,
  ];

  if (sharedProfileLines.length) {
    lines.push(
      "",
      "Shared client context",
      ...bulletList(sharedProfileLines),
    );
  }

  lines.push(
    "",
    "Reply style",
    `- ${prompt.responseStyle}`,
    "",
    "Tone",
    ...bulletList(splitLines(prompt.toneGuidance)),
    "",
    "Reply rules",
    ...bulletList(splitLines(prompt.replyRules)),
    "",
    "Tool-specific business notes",
    ...bulletList(splitLines(prompt.businessNotes)),
    "",
    "Escalation rules",
    ...bulletList(splitLines(prompt.escalationGuidance)),
  );

  if (exampleReplies.length) {
    lines.push(
      "",
      "Example replies",
      ...bulletList(exampleReplies),
    );
  }

  return lines.join("\n").trim();
}

function normalizeSimulatorContext(value) {
  const items = Array.isArray(value) ? value : splitLines(value);
  return items.map((item) => String(item).trim()).filter(Boolean);
}

function buildApprovalMessagePayload(threadContext = []) {
  const messages = normalizeSimulatorContext(threadContext);
  return messages.map((text, index) => ({
    direction: index % 2 === 0 ? "incoming" : "outgoing",
    text,
  }));
}

function normalizeSimulatorApproval(record = {}, index = 0) {
  const approvalId = String(record.approvalId || record.id || `local-approval-${index + 1}`);
  const threadContext = normalizeSimulatorContext(record.threadContext || record.context || []);
  const suggestedReply = String(record.suggestedReply || record.replyDraft || "");
  const replyDraft = String(record.replyDraft || suggestedReply || "");
  const status = String(record.status || "pending").toLowerCase() === "sent" ? "sent" : "pending";
  const createdAt = String(record.createdAt || record.created_at || nowIso());
  const updatedAt = String(record.updatedAt || record.updated_at || createdAt);

  return {
    approvalId,
    senderName: String(record.senderName || record.sender_name || "Customer"),
    senderWaId: String(record.senderWaId || record.sender_wa_id || ""),
    latestMessage: String(record.latestMessage || record.latest_message || ""),
    threadContext,
    suggestedReply,
    replyDraft,
    approvalUrl: String(record.approvalUrl || record.approval_url || DEFAULT_SIMULATOR.composer.approvalUrl),
    status,
    createdAt,
    updatedAt,
    sentAt: String(record.sentAt || record.sent_at || ""),
    messageType: String(record.messageType || record.message_type || "text"),
  };
}

function buildLocalSuggestion(messageText, prompt = getSelectedPrompt(), contextLines = []) {
  const latestText = normalizeText(messageText);
  const lowered = latestText.toLowerCase();
  const tone = normalizeText(prompt.toneGuidance).toLowerCase();
  const replyStyle = normalizeText(prompt.responseStyle || "balanced").toLowerCase();

  let reply;

  if (textHasAny(lowered, ["available today", "available tomorrow", "available", "free today", "calendar", "schedule"])) {
    reply = "One sec, checking my calendar right now.";
  } else if (textHasAny(lowered, ["price", "cost", "quote", "how much", "charge", "estimate"])) {
    reply = "I can help with that. I just need a couple of details first so I can give you the right price.";
  } else if (textHasAny(lowered, ["urgent", "asap", "right now", "emergency", "stuck", "critical"])) {
    reply = "I’m flagging this for immediate human follow-up so someone can help as fast as possible.";
  } else if (textHasAny(lowered, ["resched", "move the appointment", "change the time", "another day"])) {
    reply = "Yes, I can check that for you. What time window works best?";
  } else if (textHasAny(lowered, ["thanks", "thank you", "ok", "okay"])) {
    reply = "Of course. I’m checking that now.";
  } else {
    reply = "Thanks for reaching out. Let me check and I’ll get back to you shortly.";
  }

  if ((tone.includes("friendly") || tone.includes("warm")) && reply.startsWith("Thanks for reaching out")) {
    reply = `${reply} Happy to help.`;
  }

  if (replyStyle === "detailed") {
    if (textHasAny(lowered, ["urgent", "emergency"])) {
      reply = `${reply} I’ll make sure a person follows up as soon as possible.`;
    } else if (!reply.endsWith("right away.")) {
      reply = `${reply} Once I confirm, I’ll send the next step right away.`;
    }
  }

  if (contextLines.length > 2 && reply.toLowerCase().includes("check") && !reply.toLowerCase().includes("again")) {
    reply = `${reply} I’ll keep the thread updated.`;
  }

  return reply;
}

function createSimulatorApproval(composer, options = {}) {
  const now = nowIso();
  const approvalId = String(options.approvalId || `local-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`);
  const threadContext = normalizeSimulatorContext(composer.threadContext);
  const prompt = options.prompt || DEFAULT_PROMPT;
  const suggestedReply = buildLocalSuggestion(composer.latestMessage, prompt, threadContext);
  const approval = normalizeSimulatorApproval(
    {
      approvalId,
      senderName: composer.senderName,
      senderWaId: composer.senderWaId,
      latestMessage: composer.latestMessage,
      threadContext,
      suggestedReply,
      replyDraft: options.replyDraft || suggestedReply,
      approvalUrl: composer.approvalUrl,
      status: "pending",
      createdAt: options.createdAt || now,
      updatedAt: options.updatedAt || now,
      sentAt: "",
      messageType: "text",
      ...options,
    },
    0,
  );

  approval.suggestedReply = suggestedReply;
  if (!approval.replyDraft) {
    approval.replyDraft = suggestedReply;
  }

  return approval;
}

function buildSimulatorEditUrl(approval) {
  const approvalUrl = String(approval?.approvalUrl || "").trim();

  if (!approvalUrl) {
    return null;
  }

  try {
    const url = new URL(approvalUrl, window.location.href);
    url.searchParams.set("senderName", approval.senderName || "");
    url.searchParams.set("senderWaId", approval.senderWaId || "");
    url.searchParams.set("latestMessage", approval.latestMessage || "");
    url.searchParams.set("suggestedReply", approval.suggestedReply || "");
    url.searchParams.set("replyDraft", approval.replyDraft || "");
    url.searchParams.set("messages", JSON.stringify(buildApprovalMessagePayload(approval.threadContext || [])));
    url.searchParams.set("context", (approval.threadContext || []).join("\n"));
    url.searchParams.set("approvalId", approval.approvalId || "");
    url.searchParams.set("clientName", getWorkspaceName());
    url.searchParams.set("returnUrl", new URL("./", window.location.href).toString());
    return url.toString();
  } catch {
    return null;
  }
}

function normalizeSimulatorState(savedSimulator = {}, promptSource = DEFAULT_PROMPT) {
  const prompt = normalizePrompt(promptSource);
  const savedComposer = savedSimulator.composer || {};
  const exampleKey = SIMULATOR_PRESETS[savedComposer.scenario] ? savedComposer.scenario : DEFAULT_SIMULATOR.composer.scenario;
  const preset = SIMULATOR_PRESETS[exampleKey] || SIMULATOR_PRESETS.approval;
  const composer = {
    scenario: exampleKey,
    senderName: String(savedComposer.senderName || preset.senderName || DEFAULT_SIMULATOR.composer.senderName),
    senderWaId: String(savedComposer.senderWaId || preset.senderWaId || DEFAULT_SIMULATOR.composer.senderWaId),
    latestMessage: String(savedComposer.latestMessage || preset.latestMessage || DEFAULT_SIMULATOR.composer.latestMessage),
    threadContext: String(savedComposer.threadContext || preset.threadContext || DEFAULT_SIMULATOR.composer.threadContext),
    approvalUrl: String(savedComposer.approvalUrl || preset.approvalUrl || DEFAULT_SIMULATOR.composer.approvalUrl),
  };

  const approvalsSource = Array.isArray(savedSimulator.approvals) ? savedSimulator.approvals : [];
  const approvals = approvalsSource.length
    ? approvalsSource.map((approval, index) => normalizeSimulatorApproval(approval, index)).filter(Boolean)
    : [createSimulatorApproval(composer, { approvalId: "sample-local-approval", prompt })];

  let selectedApprovalId = String(savedSimulator.selectedApprovalId || approvals[0]?.approvalId || "");
  if (!approvals.some((approval) => approval.approvalId === selectedApprovalId)) {
    selectedApprovalId = approvals[0]?.approvalId || "";
  }

  return {
    composer,
    approvals,
    selectedApprovalId,
  };
}

function getSimulatorState() {
  if (!clientState.simulator) {
    clientState.simulator = normalizeSimulatorState({}, getSelectedPrompt());
  }

  return clientState.simulator;
}

function getSimulatorApprovals() {
  return getSimulatorState().approvals || [];
}

function getSelectedSimulatorApproval() {
  const simulator = getSimulatorState();
  const approvals = simulator.approvals || [];
  if (!approvals.length) {
    return null;
  }

  const selectedId = state.selectedSimulatorId || simulator.selectedApprovalId || approvals[0].approvalId;
  return approvals.find((approval) => approval.approvalId === selectedId) || approvals[0];
}

function ensureSimulatorSelection() {
  const simulator = getSimulatorState();
  const approvals = simulator.approvals || [];
  if (!approvals.length) {
    state.selectedSimulatorId = null;
    simulator.selectedApprovalId = "";
    return null;
  }

  let selectedApproval = approvals.find((approval) => approval.approvalId === state.selectedSimulatorId)
    || approvals.find((approval) => approval.approvalId === simulator.selectedApprovalId)
    || approvals[0];

  if (selectedApproval && selectedApproval.approvalId !== state.selectedSimulatorId) {
    state.selectedSimulatorId = selectedApproval.approvalId;
    simulator.selectedApprovalId = selectedApproval.approvalId;
    persistClientState();
  }

  return selectedApproval || null;
}

function selectSimulatorApproval(approvalId) {
  const simulator = getSimulatorState();
  const approvals = simulator.approvals || [];
  if (!approvals.some((approval) => approval.approvalId === approvalId)) {
    return;
  }

  state.selectedSimulatorId = approvalId;
  simulator.selectedApprovalId = approvalId;
  persistClientState();
  setHashForTab("simulator", approvalId);
  renderApp();
}

function applySimulatorPreset(presetKey) {
  const preset = SIMULATOR_PRESETS[presetKey] || SIMULATOR_PRESETS.approval;
  const simulator = getSimulatorState();
  simulator.composer = {
    scenario: SIMULATOR_PRESETS[presetKey] ? presetKey : "approval",
    senderName: preset.senderName,
    senderWaId: preset.senderWaId,
    latestMessage: preset.latestMessage,
    threadContext: preset.threadContext,
    approvalUrl: preset.approvalUrl,
  };
  persistClientState();
  updateSimulatorComposerFields();
  updateStatusFromSimulator("Loaded sample message");
}

function queueSimulatorApproval() {
  const simulator = getSimulatorState();
  const composer = simulator.composer || { ...DEFAULT_SIMULATOR.composer };
  const approval = createSimulatorApproval(composer, { prompt: getSelectedPrompt() });
  simulator.approvals = [approval, ...(simulator.approvals || [])];
  simulator.selectedApprovalId = approval.approvalId;
  state.selectedSimulatorId = approval.approvalId;
  persistClientState();
  setHashForTab("simulator", approval.approvalId);
  renderApp();
  updateStatusFromSimulator("Queued mock approval");
}

function markSimulatorApprovalSent() {
  const simulator = getSimulatorState();
  const approval = getSelectedSimulatorApproval();
  if (!approval || approval.status === "sent") {
    return;
  }

  approval.replyDraft = normalizeText(approval.replyDraft || approval.suggestedReply);
  approval.status = "sent";
  approval.sentAt = nowIso();
  approval.updatedAt = approval.sentAt;
  persistClientState();
  renderApp();
  updateStatusFromSimulator("Marked as sent locally");
}

function updateStatusFromSimulator(message) {
  setStatus(message || "Saved");
}

function syncSimulatorComposerField(key) {
  return (event) => {
    const simulator = getSimulatorState();
    if (!simulator.composer) {
      simulator.composer = { ...DEFAULT_SIMULATOR.composer };
    }

    simulator.composer[key] = event.target.value;
    persistClientState();
    updateStatusFromSimulator("Simulator draft updated");
  };
}

function syncSimulatorReplyDraft(event) {
  const approval = getSelectedSimulatorApproval();
  if (!approval) {
    return;
  }

  approval.replyDraft = event.target.value;
  approval.updatedAt = nowIso();
  persistClientState();
  updateSimulatorDetail();
  updateSimulatorQueue();
  updateStatusFromSimulator("Reply draft updated");
}

function updateSimulatorComposerFields() {
  const simulator = getSimulatorState();
  const composer = simulator.composer || { ...DEFAULT_SIMULATOR.composer };

  if (elements.simulatorPresetSelect) {
    elements.simulatorPresetSelect.value = composer.scenario;
  }
  if (elements.simulatorSenderNameInput) {
    elements.simulatorSenderNameInput.value = composer.senderName;
  }
  if (elements.simulatorSenderWaIdInput) {
    elements.simulatorSenderWaIdInput.value = composer.senderWaId;
  }
  if (elements.simulatorMessageInput) {
    elements.simulatorMessageInput.value = composer.latestMessage;
  }
  if (elements.simulatorContextInput) {
    elements.simulatorContextInput.value = composer.threadContext;
  }
  if (elements.simulatorApprovalUrlInput) {
    elements.simulatorApprovalUrlInput.value = composer.approvalUrl;
  }
}

function createSimulatorQueueItem(approval, isActive) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "glass-card simulator-queue-item";
  item.classList.toggle("is-active", isActive);
  item.addEventListener("click", () => selectSimulatorApproval(approval.approvalId));

  const head = document.createElement("div");
  head.className = "simulator-queue-head";

  const titleBlock = document.createElement("div");
  const title = document.createElement("h4");
  title.textContent = approval.senderName;
  const meta = document.createElement("p");
  meta.className = "simulator-queue-meta";
  meta.textContent = approval.senderWaId ? approval.senderWaId : "No WhatsApp ID yet";
  titleBlock.append(title, meta);

  const status = document.createElement("span");
  status.className = `feature-status ${approval.status === "sent" ? "is-sent" : ""}`.trim();
  status.textContent = approval.status === "sent" ? "Sent" : "Pending";

  head.append(titleBlock, status);

  const message = document.createElement("p");
  message.className = "simulator-queue-copy";
  message.textContent = approval.latestMessage;

  const footer = document.createElement("div");
  footer.className = "simulator-queue-footer";

  const created = document.createElement("span");
  created.textContent = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(approval.createdAt));

  const action = document.createElement("span");
  action.textContent = "Open";

  footer.append(created, action);
  item.append(head, message, footer);
  return item;
}

function updateSimulatorQueue() {
  const approvals = getSimulatorApprovals();
  if (elements.simulatorQueueCount) {
    const pendingCount = approvals.filter((approval) => approval.status !== "sent").length;
    elements.simulatorQueueCount.textContent = `${pendingCount} pending`;
  }

  if (!elements.simulatorQueueList) {
    return;
  }

  if (!approvals.length) {
    const emptyState = document.createElement("article");
    emptyState.className = "glass-card empty-state simulator-empty";
    const title = document.createElement("h3");
    title.textContent = "No mock approvals yet";
    const copy = document.createElement("p");
    copy.textContent = "Use the form to queue a fake WhatsApp message and create a local approval card.";
    emptyState.append(title, copy);
    elements.simulatorQueueList.replaceChildren(emptyState);
    return;
  }

  const selectedApproval = getSelectedSimulatorApproval();
  elements.simulatorQueueList.replaceChildren(
    ...approvals.map((approval) => createSimulatorQueueItem(approval, approval.approvalId === selectedApproval?.approvalId)),
  );
}

function updateSimulatorDetail() {
  const approval = getSelectedSimulatorApproval();
  if (!approval) {
    if (elements.simulatorDetailTitle) {
      elements.simulatorDetailTitle.textContent = "Select a queued approval";
    }
    if (elements.simulatorDetailStatus) {
      elements.simulatorDetailStatus.textContent = "Empty";
    }
    if (elements.simulatorDetailSender) {
      elements.simulatorDetailSender.textContent = "No sender";
    }
    if (elements.simulatorDetailMessage) {
      elements.simulatorDetailMessage.textContent = "Queue a message to see the local approval view.";
    }
    if (elements.simulatorReplyInput) {
      elements.simulatorReplyInput.value = "";
      elements.simulatorReplyInput.disabled = true;
    }
    if (elements.simulatorContextList) {
      elements.simulatorContextList.replaceChildren();
    }
    if (elements.simulatorApprovalNote) {
      elements.simulatorApprovalNote.textContent = "Edit opens the inline draft editor in this simulator.";
    }
    if (elements.simulatorSendButton) {
      elements.simulatorSendButton.disabled = true;
    }
    if (elements.simulatorEditButton) {
      elements.simulatorEditButton.disabled = true;
    }
    return;
  }

  if (elements.simulatorDetailTitle) {
    elements.simulatorDetailTitle.textContent = approval.senderName;
  }
  if (elements.simulatorDetailStatus) {
    elements.simulatorDetailStatus.textContent = approval.status === "sent" ? "Sent" : "Pending";
  }
  if (elements.simulatorDetailSender) {
    elements.simulatorDetailSender.textContent = approval.senderWaId || "Customer";
  }
  if (elements.simulatorDetailMessage) {
    elements.simulatorDetailMessage.textContent = approval.latestMessage;
  }
  if (elements.simulatorReplyInput) {
    elements.simulatorReplyInput.value = approval.replyDraft || approval.suggestedReply || "";
    elements.simulatorReplyInput.disabled = approval.status === "sent";
  }
  if (elements.simulatorContextList) {
    const items = approval.threadContext.length
      ? approval.threadContext.map((line, index) => {
          const row = document.createElement("div");
          row.className = `simulator-context-item ${index === 0 ? "is-primary" : ""}`.trim();
          row.textContent = line;
          return row;
        })
      : [];

    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "notice";
      empty.textContent = "No thread context was added to this mock message.";
      elements.simulatorContextList.replaceChildren(empty);
    } else {
      elements.simulatorContextList.replaceChildren(...items);
    }
  }
  if (elements.simulatorApprovalNote) {
    elements.simulatorApprovalNote.textContent = approval.approvalUrl
      ? `Edit opens ${approval.approvalUrl} with the sender, message, and draft prefilled.`
      : "Edit keeps the draft local in this simulator.";
  }
  if (elements.simulatorSendButton) {
    elements.simulatorSendButton.disabled = approval.status === "sent";
    elements.simulatorSendButton.textContent = approval.status === "sent" ? "Sent" : "Send";
  }
  if (elements.simulatorEditButton) {
    elements.simulatorEditButton.disabled = false;
  }
}

function updateSimulatorPanel() {
  ensureSimulatorSelection();
  updateSimulatorComposerFields();
  updateSimulatorQueue();
  updateSimulatorDetail();
}

function createBillingNotice(message, tone = "neutral") {
  const notice = document.createElement("article");
  notice.className = `empty-state billing-empty ${tone === "warn" ? "is-warn" : ""}`.trim();
  const title = document.createElement("h3");
  title.textContent = tone === "warn" ? "Billing unavailable" : "Billing data";
  const copy = document.createElement("p");
  copy.textContent = String(message || "No billing data is available yet.");
  notice.append(title, copy);
  return notice;
}

function createBillingModelRow(model, index = 0, currency = "USD") {
  const row = document.createElement("div");
  row.className = "billing-model-row";
  row.style.setProperty("--billing-model-color", BILLING_MODEL_COLORS[index % BILLING_MODEL_COLORS.length]);

  const swatch = document.createElement("span");
  swatch.className = "billing-model-swatch";

  const copy = document.createElement("div");
  copy.className = "billing-model-copy";

  const title = document.createElement("strong");
  title.textContent = formatModelName(model.model);

  const meta = document.createElement("p");
  meta.textContent = `${formatTokenCount(model.tokensUsed)} tokens`;

  copy.append(title, meta);

  const stats = document.createElement("div");
  stats.className = "billing-model-stats";

  const cost = document.createElement("strong");
  cost.textContent = formatCurrency(model.chargeUsd, currency);

  const label = document.createElement("span");
  label.textContent = "Usage cost";

  stats.append(cost, label);

  row.append(swatch, copy, stats);
  return row;
}

function createBillingToolRow(tool, index = 0, currency = "USD", report = null) {
  const details = document.createElement("details");
  details.className = "billing-tool";
  if (index === 0) {
    details.open = true;
  }

  const summary = document.createElement("summary");

  const labelBlock = document.createElement("div");
  labelBlock.className = "billing-tool-label";

  const title = document.createElement("strong");
  title.textContent = tool.toolName || formatDisplayNameFromId(tool.toolId);

  const subtitle = document.createElement("span");
  subtitle.textContent = tool.models.length
    ? tool.models.map((model) => formatModelName(model.model)).join(" · ")
    : "No model activity";

  labelBlock.append(title, subtitle);

  const tokenBlock = document.createElement("div");
  tokenBlock.className = "billing-tool-stat";

  const tokenLabel = document.createElement("span");
  tokenLabel.textContent = "Tokens";

  const tokenValue = document.createElement("strong");
  tokenValue.textContent = formatTokenCount(tool.tokensUsed);

  tokenBlock.append(tokenLabel, tokenValue);

  const paidBlock = document.createElement("div");
  paidBlock.className = "billing-tool-stat";

  const paidLabel = document.createElement("span");
  paidLabel.textContent = "Usage cost";

  const paidValue = document.createElement("strong");
  paidValue.textContent = formatCurrency(tool.chargeUsd, currency);

  paidBlock.append(paidLabel, paidValue);

  const caret = document.createElement("span");
  caret.className = "billing-month-caret";
  caret.setAttribute("aria-hidden", "true");
  caret.textContent = "▸";

  summary.append(labelBlock, tokenBlock, paidBlock, caret);

  const body = document.createElement("div");
  body.className = "billing-tool-body";

  const note = document.createElement("p");
  note.className = "billing-month-note";
  note.textContent = tool.tokensUsed
    ? `Usage-based total for this tool is ${formatCurrency(tool.chargeUsd, currency)}.`
    : "No usage recorded for this tool yet.";

  body.append(note);

  if (!tool.models.length) {
    body.append(createBillingNotice("No model usage was recorded for this tool yet."));
  } else {
    const modelList = document.createElement("div");
    modelList.className = "billing-model-list billing-model-list-nested";
    modelList.append(...tool.models.map((model, modelIndex) => createBillingModelRow(model, modelIndex, currency)));
    body.append(modelList);
  }

  details.append(summary, body);
  return details;
}

function createBillingMonthDetail(month, index = 0, currency = "USD", report = null) {
  const details = document.createElement("details");
  details.className = "billing-month";

  const summary = document.createElement("summary");

  const labelBlock = document.createElement("div");
  labelBlock.className = "billing-month-label";

  const title = document.createElement("strong");
  title.textContent = month.label || formatBillingMonthLabel(month.month);

  const subtitle = document.createElement("span");
  subtitle.textContent = month.tools.length
    ? `${month.tools.length} tool${month.tools.length === 1 ? "" : "s"} · ${month.models.length} model${month.models.length === 1 ? "" : "s"}`
    : "No tool activity";

  labelBlock.append(title, subtitle);

  const tokenBlock = document.createElement("div");
  tokenBlock.className = "billing-month-stat";

  const tokenLabel = document.createElement("span");
  tokenLabel.textContent = "Tokens";

  const tokenValue = document.createElement("strong");
  tokenValue.textContent = formatTokenCount(month.tokensUsed);

  tokenBlock.append(tokenLabel, tokenValue);

  const paidBlock = document.createElement("div");
  paidBlock.className = "billing-month-stat";

  const paidLabel = document.createElement("span");
  paidLabel.textContent = "Paid";

  const paidValue = document.createElement("strong");
  paidValue.textContent = formatCurrency(month.chargeUsd, currency);

  paidBlock.append(paidLabel, paidValue);

  const caret = document.createElement("span");
  caret.className = "billing-month-caret";
  caret.setAttribute("aria-hidden", "true");
  caret.textContent = "▸";

  summary.append(labelBlock, tokenBlock, paidBlock, caret);

  const body = document.createElement("div");
  body.className = "billing-month-body";

  const note = document.createElement("p");
  note.className = "billing-month-note";
  const usageChargeUsd = Number(month.usageChargeUsd ?? month.chargeUsd ?? 0);
  const minimumMonthlyCharge = Number(month.minimumMonthlyCharge || report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM) || DEFAULT_BILLING_MINIMUM;
  note.textContent = month.tokensUsed
    ? month.minimumApplied
      ? `Usage-based total this month is ${formatCurrency(usageChargeUsd, currency)}. Since that is below the ${formatCurrency(minimumMonthlyCharge, currency)} monthly minimum, projected payment is ${formatCurrency(month.chargeUsd, currency)}.`
      : `Usage-based total this month is ${formatCurrency(usageChargeUsd, currency)}.`
    : month.minimumApplied
      ? `No usage recorded this month yet, so projected payment remains the ${formatCurrency(minimumMonthlyCharge, currency)} monthly minimum.`
      : "No usage recorded this month yet.";

  body.append(note);

  if (!month.tools.length) {
    body.append(createBillingNotice("No tool usage was recorded for this month yet."));
  } else {
    const toolList = document.createElement("div");
    toolList.className = "billing-tool-list";
    toolList.append(...month.tools.map((toolRow, toolIndex) => createBillingToolRow(toolRow, toolIndex, currency, report)));
    body.append(toolList);
  }

  details.append(summary, body);
  return details;
}

function updateBillingPanel() {
  const report = state.billingReport ? enrichBillingReportWithCatalog(normalizeBillingReport(state.billingReport)) : null;
  const hasError = Boolean(state.billingError);
  const isLoading = state.billingLoading && !report;
  const isRefreshing = state.billingLoading && Boolean(report);
  const currency = report?.currency || "USD";
  const statusCopy = getBillingStatusCopy(report, hasError, state.billingLoading);
  const showOnlyErrorState = hasError;

  if (showOnlyErrorState && state.billingHelpOpen) {
    setBillingHelpOpen(false);
  }

  if (elements.billingHelpStrip) {
    elements.billingHelpStrip.classList.toggle("is-hidden", showOnlyErrorState);
  }
  if (elements.billingHero) {
    elements.billingHero.classList.toggle("is-hidden", showOnlyErrorState);
  }
  if (elements.billingGrid) {
    elements.billingGrid.classList.toggle("is-hidden", showOnlyErrorState);
  }

  if (elements.billingStatusBanner) {
    elements.billingStatusBanner.classList.toggle("is-warn", hasError);
    elements.billingStatusBanner.classList.toggle("is-loading", state.billingLoading);
    elements.billingStatusBanner.setAttribute("aria-busy", String(state.billingLoading));
  }
  if (elements.billingStatusMessage) {
    elements.billingStatusMessage.textContent = statusCopy.message;
  }
  if (elements.billingStatusMeta) {
    elements.billingStatusMeta.textContent = statusCopy.meta;
    elements.billingStatusMeta.classList.toggle("is-hidden", !statusCopy.meta);
  }
  if (elements.billingRefreshButton) {
    elements.billingRefreshButton.disabled = state.billingLoading;
    elements.billingRefreshButton.classList.toggle("is-hidden", showOnlyErrorState);
    elements.billingRefreshButton.textContent = state.billingLoading
      ? (report ? "Checking latest..." : "Loading...")
      : hasError ? "Try again" : "Refresh billing";
    elements.billingRefreshButton.setAttribute("aria-busy", String(state.billingLoading));
  }

  if (isRefreshing) {
    return;
  }

  if (!report) {
    const fallbackSummary = hasError
      ? "I’m not able to load billing data right now."
      : isLoading
        ? "Loading billing data..."
        : "Projected payment updates as usage changes. Tap ? for the billing rules.";

    if (elements.billingCurrentMonthLabel) {
      elements.billingCurrentMonthLabel.textContent = "This month";
    }
    if (elements.billingCurrentSummary) {
      elements.billingCurrentSummary.textContent = fallbackSummary;
    }
    if (elements.billingCurrentTokens) {
      elements.billingCurrentTokens.textContent = "—";
      elements.billingCurrentTokens.title = hasError || isLoading ? "Billing data unavailable" : "Billing data not loaded yet";
    }
    if (elements.billingCurrentCharge) {
      elements.billingCurrentCharge.textContent = "—";
      elements.billingCurrentCharge.title = hasError || isLoading
        ? "Projected payment unavailable"
        : "Projected payment not loaded yet";
    }
    if (elements.billingNextPayment) {
      elements.billingNextPayment.textContent = "—";
      elements.billingNextPayment.title = hasError || isLoading
        ? "Next payment date unavailable"
        : "Next payment date not loaded yet";
    }
    if (elements.billingModelCount) {
      elements.billingModelCount.textContent = "—";
    }
    if (elements.billingHistoryCount) {
      elements.billingHistoryCount.textContent = "—";
    }
    if (elements.billingModelList) {
      elements.billingModelList.replaceChildren(
        createBillingNotice(
          hasError
            ? "The tool breakdown will return as soon as billing data is reachable again."
            : "Billing activity will appear here once billing is connected.",
          hasError ? "warn" : "neutral",
        ),
      );
    }
    if (elements.billingHistoryList) {
      elements.billingHistoryList.replaceChildren(
        createBillingNotice(
          hasError
            ? "The month history will return as soon as billing data is reachable again."
            : "Previous months will appear here once they are available.",
          hasError ? "warn" : "neutral",
        ),
      );
    }
    if (elements.billingHelpBody) {
      elements.billingHelpBody.replaceChildren(buildBillingHelpBody(report));
    }
    syncBillingHelpState();
    if (elements.billingMix) {
      elements.billingMix.replaceChildren();
    }
    return;
  }

  const currentMonth = report.currentMonth || {
    label: "This month",
    tokensUsed: 0,
    baseCostUsd: 0,
    chargeUsd: report.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM,
    minimumApplied: true,
    minimumMonthlyCharge: report.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM,
    tools: [],
    models: [],
  };

  if (elements.billingCurrentMonthLabel) {
    elements.billingCurrentMonthLabel.textContent = currentMonth.label || "This month";
  }
  if (elements.billingCurrentSummary) {
    elements.billingCurrentSummary.textContent = buildBillingSummaryText(report);
  }
  if (elements.billingCurrentTokens) {
    elements.billingCurrentTokens.textContent = formatCompactTokenCount(currentMonth.tokensUsed);
    elements.billingCurrentTokens.title = `${formatTokenCount(currentMonth.tokensUsed)} tokens`;
  }
  if (elements.billingCurrentCharge) {
    elements.billingCurrentCharge.textContent = formatCurrency(currentMonth.chargeUsd, currency);
    elements.billingCurrentCharge.title = "Projected payment based on current usage";
  }
  if (elements.billingNextPayment) {
    elements.billingNextPayment.textContent = formatBillingDate(getNextBillingPaymentDate(report)) || "—";
    elements.billingNextPayment.title = "Next scheduled payment date";
  }
  if (elements.billingModelCount) {
    currentMonth.tools = Array.isArray(currentMonth.tools) ? currentMonth.tools : [];
    elements.billingModelCount.textContent = `${currentMonth.tools.length} tool${currentMonth.tools.length === 1 ? "" : "s"}`;
  }
  if (elements.billingHistoryCount) {
    elements.billingHistoryCount.textContent = `${report.history.length} month${report.history.length === 1 ? "" : "s"}`;
  }
  if (elements.billingModelList) {
    if (!currentMonth.tools.length) {
      elements.billingModelList.replaceChildren(
        createBillingNotice("No tool usage has been recorded for the current month yet."),
      );
    } else {
      elements.billingModelList.replaceChildren(
        ...currentMonth.tools.map((tool, index) => createBillingToolRow(tool, index, currency, report)),
      );
    }
  }
  if (elements.billingHistoryList) {
    if (!report.history.length) {
      elements.billingHistoryList.replaceChildren(
        createBillingNotice("Previous months will appear here once they are available."),
      );
    } else {
      elements.billingHistoryList.replaceChildren(
        ...report.history.map((month, index) => createBillingMonthDetail(month, index, currency, report)),
      );
    }
  }
  if (elements.billingMix) {
    const totalTokens = Math.max(0, Number(currentMonth.tokensUsed || 0));
    if (!totalTokens || !currentMonth.tools.length) {
      elements.billingMix.replaceChildren();
    } else {
      const segments = currentMonth.tools.map((tool, index) => {
        const segment = document.createElement("div");
        segment.className = "billing-mix-segment";
        segment.style.setProperty("--billing-model-color", BILLING_MODEL_COLORS[index % BILLING_MODEL_COLORS.length]);
        segment.style.flexGrow = String(Math.max(0.001, Number(tool.tokensUsed || 0)));
        segment.title = `${tool.toolName || formatDisplayNameFromId(tool.toolId)} · ${formatTokenCount(tool.tokensUsed)} tokens`;
        return segment;
      });

      elements.billingMix.replaceChildren(...segments);
    }
  }
}

function refreshBillingReportForActiveTab(options = {}) {
  if (state.activeTab !== "billing") {
    return null;
  }

  return refreshBillingReport(options);
}

async function refreshBillingReport(options = {}) {
  if (!authSession?.token) {
    state.billingReport = null;
    state.billingLoading = false;
    state.billingError = "";
    return;
  }

  if (billingRefreshPromise) {
    return billingRefreshPromise;
  }

  const force = Boolean(options.force);
  if (
    !force
    && state.billingReport
    && !state.billingError
    && Date.now() - billingLastRefreshCompletedAt < BILLING_ENTRY_REFRESH_COOLDOWN_MS
  ) {
    return null;
  }

  const requestToken = String(authSession.token);
  state.billingLoading = true;
  state.billingError = "";
  renderApp();

  billingRefreshPromise = (async () => {
    try {
      const response = await apiRequest("/api/billing", {
        headers: {
          Authorization: `Bearer ${requestToken}`,
        },
      });

      if (String(authSession?.token || "") !== requestToken) {
        return null;
      }

      state.billingReport = normalizeBillingReport(response);
      state.billingError = "";
      billingLastRefreshCompletedAt = Date.now();
      return state.billingReport;
    } catch (error) {
      if (String(authSession?.token || "") !== requestToken) {
        return null;
      }
      state.billingReport = null;
      setBillingError(formatApiErrorMessage(error, "We couldn’t load billing data right now."));
      return null;
    } finally {
      billingRefreshPromise = null;
      if (String(authSession?.token || "") === requestToken) {
        state.billingLoading = false;
        renderApp();
      }
    }
  })();

  return billingRefreshPromise;
}

function formatUsdPerMillion(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return "—";
  }

  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: amount >= 10 ? 0 : 2,
    maximumFractionDigits: amount >= 10 ? 1 : 2,
  }).format(amount);
}

function createPricingMetric(label, value, detail) {
  const metric = document.createElement("div");
  metric.className = "pricing-metric";

  const labelElement = document.createElement("span");
  labelElement.textContent = label;

  const valueElement = document.createElement("strong");
  valueElement.textContent = value;

  metric.append(labelElement, valueElement);

  if (detail) {
    const detailElement = document.createElement("small");
    detailElement.textContent = detail;
    metric.append(detailElement);
  }

  return metric;
}

function createPricingTag(text) {
  const tag = document.createElement("span");
  tag.className = "pricing-card-tag";
  tag.textContent = text;
  return tag;
}

function buildPricingCard(card) {
  const article = document.createElement("article");
  article.className = `glass-card pricing-card${card.featured ? " is-featured" : ""}`.trim();

  const head = document.createElement("div");
  head.className = "pricing-card-head";

  const top = document.createElement("div");
  top.className = "pricing-card-top";

  const badge = document.createElement("span");
  badge.className = "pricing-card-band";
  badge.textContent = card.band || "Tier";

  top.append(badge);

  if (card.highlightLabel) {
    const highlight = document.createElement("span");
    highlight.className = "pricing-card-highlight";
    highlight.textContent = card.highlightLabel;
    top.append(highlight);
  }

  const titleBlock = document.createElement("div");
  titleBlock.className = "pricing-card-title";

  const modelName = document.createElement("h3");
  modelName.textContent = card.modelName || card.modelId || "Model";

  const summary = document.createElement("p");
  summary.className = "pricing-card-summary";
  summary.textContent = String(card.description || "").trim();

  const subtitle = document.createElement("p");
  subtitle.className = "pricing-card-model-id";
  subtitle.textContent = `Model: ${card.modelId || ""}`;

  titleBlock.append(modelName, summary, subtitle);
  head.append(top, titleBlock);

  const rates = document.createElement("div");
  rates.className = "pricing-card-rates";
  rates.append(
    createPricingMetric(
      "Input",
      formatUsdPerMillion(card?.ours?.inputUsdPer1MTokens),
      "per 1M tokens",
    ),
    createPricingMetric(
      "Output",
      formatUsdPerMillion(card?.ours?.outputUsdPer1MTokens),
      "per 1M tokens",
    ),
  );

  const body = document.createElement("div");
  body.className = "pricing-card-body";
  body.append(rates);

  const footer = document.createElement("div");
  footer.className = "pricing-card-footer";

  const footerLabel = document.createElement("span");
  footerLabel.className = "pricing-card-footer-label";
  footerLabel.textContent = "Best for";

  const tags = document.createElement("div");
  tags.className = "pricing-card-tags";
  const useCases = Array.isArray(card.useCases) ? card.useCases : [];
  if (useCases.length) {
    tags.replaceChildren(...useCases.map((item) => createPricingTag(item)));
  }

  footer.append(footerLabel, tags);

  article.append(head, body, footer);
  return article;
}

function createPricingEmptyState(message, meta = "") {
  const empty = document.createElement("article");
  empty.className = "glass-card pricing-card pricing-card-empty";

  const title = document.createElement("strong");
  title.textContent = message;
  empty.append(title);

  if (meta) {
    const paragraph = document.createElement("p");
    paragraph.textContent = meta;
    empty.append(paragraph);
  }

  return empty;
}

function normalizePricingSnapshot(snapshot = {}) {
  const source = snapshot && typeof snapshot === "object" ? snapshot : {};
  const cards = Array.isArray(source.cards) ? source.cards : [];
  return {
    ...MANUAL_PRICING_SNAPSHOT,
    ...source,
    cards,
  };
}

function getPricingSourceLabel(snapshot) {
  const source = String(snapshot?.source || "").trim();
  if (source === "token-prices-api") {
    return "Live pricing";
  }
  if (source === "database") {
    return "Cached pricing";
  }
  if (source === "manual") {
    return "Manual fallback";
  }
  return source ? formatDisplayNameFromId(source) : "Pricing";
}

function updatePricingPanel() {
  const snapshot = state.pricingSnapshot && typeof state.pricingSnapshot === "object"
    ? normalizePricingSnapshot(state.pricingSnapshot)
    : MANUAL_PRICING_SNAPSHOT;
  const cards = Array.isArray(snapshot?.cards) ? snapshot.cards : [];
  const hasError = Boolean(state.pricingError);

  if (elements.pricingCardCount) {
    elements.pricingCardCount.textContent = String(cards.length || 0);
  }
  if (elements.pricingSourceType) {
    elements.pricingSourceType.textContent = hasError ? "Fallback pricing" : getPricingSourceLabel(snapshot);
  }
  if (elements.pricingStatusBanner) {
    elements.pricingStatusBanner.classList.toggle("is-warn", hasError);
    elements.pricingStatusBanner.classList.toggle("is-loading", state.pricingLoading);
    elements.pricingStatusBanner.setAttribute("aria-busy", String(state.pricingLoading));
  }
  if (elements.pricingStatusMessage) {
    elements.pricingStatusMessage.textContent = hasError
      ? state.pricingError
      : state.pricingLoading ? "Loading pricing..." : "Pricing is up to date.";
  }
  if (elements.pricingStatusMeta) {
    const fetchedAt = formatBillingDate(snapshot.fetchedAt);
    elements.pricingStatusMeta.textContent = fetchedAt
      ? `${getPricingSourceLabel(snapshot)} refreshed ${fetchedAt}.`
      : getPricingSourceLabel(snapshot);
  }

  if (elements.pricingCardGrid) {
    if (!cards.length) {
      const message = "Pricing cards are not available right now.";
      const meta = hasError ? state.pricingError : "Pricing will appear once token prices are available.";
      elements.pricingCardGrid.replaceChildren(createPricingEmptyState(message, meta));
    } else {
      elements.pricingCardGrid.replaceChildren(...cards.map((card) => buildPricingCard(card)));
    }
  }
}

async function refreshPricingSnapshot(options = {}) {
  if (!authSession?.token) {
    state.pricingSnapshot = MANUAL_PRICING_SNAPSHOT;
    state.pricingLoading = false;
    state.pricingError = "";
    if (options.render !== false) {
      renderApp();
    }
    return state.pricingSnapshot;
  }

  if (pricingRefreshPromise) {
    return pricingRefreshPromise;
  }

  const force = Boolean(options.force);
  if (
    !force
    && state.pricingSnapshot
    && !state.pricingError
    && Date.now() - pricingLastRefreshCompletedAt < BILLING_ENTRY_REFRESH_COOLDOWN_MS
  ) {
    return state.pricingSnapshot;
  }

  const requestToken = String(authSession.token);
  state.pricingLoading = true;
  state.pricingError = "";
  if (options.render !== false) {
    renderApp();
  }

  pricingRefreshPromise = (async () => {
    try {
      const response = await apiRequest("/api/pricing", {
        headers: {
          Authorization: `Bearer ${requestToken}`,
        },
      });

      if (String(authSession?.token || "") !== requestToken) {
        return null;
      }

      state.pricingSnapshot = normalizePricingSnapshot(response);
      state.pricingError = "";
      pricingLastRefreshCompletedAt = Date.now();
      return state.pricingSnapshot;
    } catch (error) {
      if (String(authSession?.token || "") !== requestToken) {
        return null;
      }
      state.pricingSnapshot = MANUAL_PRICING_SNAPSHOT;
      state.pricingError = formatApiErrorMessage(error, "We couldn’t load live pricing right now.");
      return state.pricingSnapshot;
    } finally {
      pricingRefreshPromise = null;
      if (String(authSession?.token || "") === requestToken) {
        state.pricingLoading = false;
        if (options.render !== false) {
          renderApp();
        }
      }
    }
  })();

  return pricingRefreshPromise;
}

function buildAdminFeatureSummary(feature) {
  return [feature.channel, feature.mode].filter(Boolean).join(" · ");
}

function createAdminFeatureOption(feature, options = {}) {
  const option = document.createElement("label");
  option.className = "admin-feature-option";
  if (options.compact) {
    option.classList.add("is-compact");
  }

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(options.checked);
  checkbox.disabled = Boolean(options.disabled);
  checkbox.dataset.adminFeatureId = feature.featureId;
  if (options.userEmail) {
    checkbox.dataset.adminUserEmail = options.userEmail;
  } else {
    checkbox.dataset.adminFeatureTarget = "new";
  }

  const copy = document.createElement("span");
  copy.className = "admin-feature-option-copy";

  const name = document.createElement("strong");
  name.textContent = feature.name;

  const meta = document.createElement("span");
  meta.className = "admin-feature-option-meta";
  meta.textContent = buildAdminFeatureSummary(feature) || "Tool";

  copy.append(name, meta);
  if (options.showDescription && feature.description) {
    const description = document.createElement("span");
    description.className = "admin-feature-option-description";
    description.textContent = feature.description;
    copy.append(description);
  }
  option.append(checkbox, copy);
  return option;
}

function createAdminEmptyState(titleText, copyText) {
  const empty = document.createElement("article");
  empty.className = "glass-card empty-state admin-users-empty";

  const title = document.createElement("h3");
  title.textContent = titleText;

  const copy = document.createElement("p");
  copy.textContent = copyText;

  empty.append(title, copy);
  return empty;
}

function createAdminDetailRow(labelText, valueText) {
  const row = document.createElement("div");
  row.className = "detail-row";

  const label = document.createElement("span");
  label.className = "detail-key";
  label.textContent = labelText;

  const value = document.createElement("strong");
  value.textContent = valueText;

  row.append(label, value);
  return row;
}

function focusAdminFeatureSearchInput(selectionStart = null, selectionEnd = selectionStart) {
  window.requestAnimationFrame(() => {
    const input = elements.adminUsersPane?.querySelector('[data-admin-feature-search-input="true"]');
    if (!(input instanceof HTMLInputElement)) {
      return;
    }

    input.focus();
    if (typeof selectionStart === "number") {
      const safeEnd = typeof selectionEnd === "number" ? selectionEnd : selectionStart;
      input.setSelectionRange(selectionStart, safeEnd);
    }
  });
}

function getEventTargetElement(event) {
  const target = event.target;
  if (target instanceof Element) {
    return target;
  }

  return target instanceof Node ? target.parentElement : null;
}

function createAdminAssignedFeatureBadge(feature, options = {}) {
  const badge = document.createElement("div");
  badge.className = "admin-tool-badge";

  const label = document.createElement("span");
  label.className = "admin-tool-badge-label";
  label.textContent = feature?.name || "Untitled tool";

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "admin-tool-badge-remove";
  removeButton.dataset.adminRemoveFeature = String(feature?.featureId || "").trim();
  removeButton.dataset.adminUserEmail = normalizeEmail(options.userEmail || "");
  removeButton.disabled = Boolean(options.disabled);
  removeButton.setAttribute("aria-label", `Remove ${feature?.name || "tool"}`);
  removeButton.textContent = "×";

  badge.append(label, removeButton);
  return badge;
}

function createAdminFeatureSearchResult(feature, options = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "admin-tool-result";
  button.disabled = Boolean(options.disabled);
  button.dataset.adminAddFeature = String(feature?.featureId || "").trim();
  button.dataset.adminUserEmail = normalizeEmail(options.userEmail || "");

  const copy = document.createElement("span");
  copy.className = "admin-tool-result-copy";

  const title = document.createElement("strong");
  title.textContent = feature?.name || "Untitled tool";
  copy.append(title);

  const metaText = [feature?.channel, feature?.mode].filter(Boolean).join(" · ");
  if (metaText) {
    const meta = document.createElement("span");
    meta.className = "admin-tool-result-meta";
    meta.textContent = metaText;
    copy.append(meta);
  }

  const stateBadge = document.createElement("span");
  stateBadge.className = "admin-tool-result-state";
  stateBadge.textContent = "Add";

  button.append(copy, stateBadge);
  return button;
}

function createAdminUsersListView() {
  const wrapper = document.createElement("div");
  wrapper.className = "admin-users-view admin-users-list-view";

  const stats = getAdminClientStats();
  const summary = document.createElement("div");
  summary.className = "clients-summary";
  const summaryItems = [
    ["Clients", stats.total, "Registered accounts"],
    ["Active", stats.active, "Can sign in"],
    ["Paying", stats.paying, "Client type"],
    ["Demo", stats.demo, "Client type"],
    ["QA", stats.qa, "Client type"],
  ];
  for (const [labelText, valueText, metaText] of summaryItems) {
    const item = document.createElement("div");
    item.className = "client-metric";
    const label = document.createElement("span");
    label.textContent = labelText;
    const value = document.createElement("strong");
    value.textContent = String(valueText);
    const meta = document.createElement("small");
    meta.textContent = metaText;
    item.append(label, value, meta);
    summary.append(item);
  }
  wrapper.append(summary);

  const toolbar = document.createElement("div");
  toolbar.className = "admin-users-toolbar";

  const searchField = document.createElement("label");
  searchField.className = "field admin-users-search-field";

  const searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.placeholder = "Search name or email";
  searchInput.setAttribute("aria-label", "Search users");
  searchInput.value = state.adminUserSearch;
  searchInput.autocomplete = "off";
  searchInput.dataset.adminSearchInput = "true";

  searchField.append(searchInput);

  const filteredUsers = getFilteredAdminUsers();
  const countBadge = document.createElement("span");
  countBadge.className = "feature-status";
  countBadge.textContent = state.adminUserSearch
    ? `${filteredUsers.length} of ${state.adminUsers.length} clients`
    : `${state.adminUsers.length} client${state.adminUsers.length === 1 ? "" : "s"}`;

  toolbar.append(searchField, countBadge);
  wrapper.append(toolbar);

  if (state.adminUsersLoading && !state.adminUsers.length) {
    wrapper.append(createAdminEmptyState(
      "Loading clients",
      "Fetching registered accounts so you can search and manage them.",
    ));
    return wrapper;
  }

  if (!state.adminUsers.length) {
    wrapper.append(createAdminEmptyState(
      "No clients yet",
      "Add the first client here, then open them to manage which tools they can see.",
    ));
    return wrapper;
  }

  if (!filteredUsers.length) {
    wrapper.append(createAdminEmptyState(
      "No clients match that search",
      "Try a different name or email address.",
    ));
    return wrapper;
  }

  const tableWrap = document.createElement("div");
  tableWrap.className = "admin-users-table-wrap";

  const table = document.createElement("table");
  table.className = "admin-users-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const heading of ["Client", "Email", "Client type", "Active", "Visible tools", "Last login", ""]) {
    const cell = document.createElement("th");
    cell.textContent = heading;
    headRow.append(cell);
  }
  thead.append(headRow);

  const tbody = document.createElement("tbody");
  for (const user of filteredUsers) {
    const row = document.createElement("tr");

    const nameCell = document.createElement("td");
    const nameButton = document.createElement("button");
    nameButton.type = "button";
    nameButton.className = "admin-user-link";
    nameButton.dataset.adminOpenUser = user.email;
    nameButton.textContent = user.displayName || deriveDisplayName(user.email);
    nameCell.append(nameButton);

    const emailCell = document.createElement("td");
    emailCell.textContent = user.email;

    const clientTypeCell = document.createElement("td");
    clientTypeCell.append(createAdminClientTypeSelect(user, {
      disabled: Boolean(state.adminDeleteBusyByEmail[user.email]),
    }));

    const activeCell = document.createElement("td");
    activeCell.append(createAdminActiveSwitch(user, {
      disabled: Boolean(state.adminDeleteBusyByEmail[user.email]),
    }));

    const toolsCell = document.createElement("td");
    toolsCell.className = "admin-tools-cell";
    const toolSummary = document.createElement("span");
    toolSummary.className = "admin-tools-summary";
    toolSummary.textContent = formatAdminUserTools(user, 2);
    toolSummary.title = getAdminUserToolNames(user).join(", ");
    toolsCell.append(toolSummary);

    const lastLoginCell = document.createElement("td");
    lastLoginCell.textContent = user.lastLoginAt
      ? formatAdminDateTime(user.lastLoginAt)
      : "No login yet";

    const actionCell = document.createElement("td");
    const manageButton = document.createElement("button");
    manageButton.type = "button";
    manageButton.className = "ghost-button small";
    manageButton.dataset.adminOpenUser = user.email;
    manageButton.textContent = "Manage";
    actionCell.append(manageButton);

    row.classList.toggle("is-inactive-client", !user.isActive);
    row.append(nameCell, emailCell, clientTypeCell, activeCell, toolsCell, lastLoginCell, actionCell);
    tbody.append(row);
  }

  table.append(thead, tbody);
  tableWrap.append(table);
  wrapper.append(tableWrap);
  return wrapper;
}

function createAdminAddUserView() {
  const wrapper = document.createElement("div");
  wrapper.className = "admin-users-view admin-users-add-view";

  const emailField = document.createElement("label");
  emailField.className = "field";
  const emailLabel = document.createElement("span");
  emailLabel.textContent = "Email";
  const emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.placeholder = "client@example.com";
  emailInput.value = state.adminNewUserEmail;
  emailInput.autocomplete = "off";
  emailInput.dataset.adminNewEmail = "true";
  emailField.append(emailLabel, emailInput);

  const nameField = document.createElement("label");
  nameField.className = "field";
  const nameLabel = document.createElement("span");
  nameLabel.textContent = "Display name";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "Client name";
  nameInput.value = state.adminNewUserDisplayName;
  nameInput.autocomplete = "off";
  nameInput.dataset.adminNewDisplayName = "true";
  nameField.append(nameLabel, nameInput);

  const error = document.createElement("div");
  error.className = `field-error${state.adminUsersError ? "" : " is-hidden"}`;
  error.role = "status";
  error.setAttribute("aria-live", "polite");
  error.textContent = state.adminUsersError;

  const actions = document.createElement("div");
  actions.className = "card-actions admin-form-actions";

  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "ghost-button";
  cancelButton.dataset.adminCancelAddUser = "true";
  cancelButton.disabled = state.adminAddUserBusy;
  cancelButton.textContent = "Cancel";

  const submitButton = document.createElement("button");
  submitButton.type = "button";
  submitButton.className = `primary-button${state.adminAddUserBusy ? " is-loading" : ""}`;
  submitButton.dataset.adminCreateUser = "true";
  submitButton.disabled = state.adminAddUserBusy;
  submitButton.textContent = state.adminAddUserBusy ? "Adding..." : "Add client";

  actions.append(cancelButton, submitButton);
  wrapper.append(emailField, nameField, error, actions);
  return wrapper;
}

function createAdminEditUserView(user) {
  if (!user) {
    return createAdminEmptyState(
      "Client not found",
      "Go back to the clients table and open another account.",
    );
  }

  const normalizedUserEmail = normalizeEmail(user.email);
  const isEditingCurrentUser = normalizedUserEmail === normalizeEmail(authSession?.email || activeEmail || "");
  const isBusy = state.adminEditUserBusy;

  const wrapper = document.createElement("div");
  wrapper.className = "admin-users-view admin-users-add-view";

  const emailField = document.createElement("label");
  emailField.className = "field";
  const emailLabel = document.createElement("span");
  emailLabel.textContent = "Email";
  const emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.placeholder = "client@example.com";
  emailInput.value = state.adminEditUserEmail;
  emailInput.autocomplete = "off";
  emailInput.disabled = isBusy || isEditingCurrentUser;
  emailInput.dataset.adminEditEmail = "true";
  emailField.append(emailLabel, emailInput);

  const nameField = document.createElement("label");
  nameField.className = "field";
  const nameLabel = document.createElement("span");
  nameLabel.textContent = "Display name";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "Client name";
  nameInput.value = state.adminEditUserDisplayName;
  nameInput.autocomplete = "off";
  nameInput.disabled = isBusy;
  nameInput.dataset.adminEditDisplayName = "true";
  nameField.append(nameLabel, nameInput);

  const note = document.createElement("p");
  note.className = "admin-form-note";
  note.textContent = isEditingCurrentUser
    ? "You can change the display name here, but not the email on the admin account you're using right now."
    : "Changing the email keeps this client's assigned tools and saved account history attached to the same account.";

  const error = document.createElement("div");
  error.className = `field-error${state.adminUsersError ? "" : " is-hidden"}`;
  error.role = "status";
  error.setAttribute("aria-live", "polite");
  error.textContent = state.adminUsersError;

  const actions = document.createElement("div");
  actions.className = "card-actions admin-form-actions";

  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "ghost-button";
  cancelButton.dataset.adminCancelEditUser = "true";
  cancelButton.disabled = isBusy;
  cancelButton.textContent = "Cancel";

  const submitButton = document.createElement("button");
  submitButton.type = "button";
  submitButton.className = `primary-button${isBusy ? " is-loading" : ""}`;
  submitButton.dataset.adminSaveEditUser = "true";
  submitButton.disabled = isBusy;
  submitButton.textContent = isBusy ? "Saving..." : "Save changes";

  actions.append(cancelButton, submitButton);
  wrapper.append(emailField, nameField, note, error, actions);
  return wrapper;
}

function createAdminUserDetailView(user) {
  if (!user) {
    return createAdminEmptyState(
      "Client not found",
      "Go back to the clients table and open another account.",
    );
  }

  const draftFeatureIds = getAdminUserDraftFeatureIds(user.email, user.assignedFeatureIds);
  const hasChanges = !featureIdListsMatch(draftFeatureIds, user.assignedFeatureIds);
  const isSaving = Boolean(state.adminSaveBusyByEmail[user.email]);
  const isDeleting = Boolean(state.adminDeleteBusyByEmail[user.email]);
  const isStatusSaving = Boolean(state.adminStatusBusyByEmail[user.email]);
  const deleteDisabledReason = getAdminUserDeleteDisabledReason(user);
  const toolInputsDisabled = isDeleting || isStatusSaving;
  const featureLookup = new Map(state.adminFeatures.map((feature) => [feature.featureId, feature]));
  const assignedFeatures = draftFeatureIds.map((featureId) => (
    featureLookup.get(featureId) || {
      featureId,
      name: featureId,
      description: "",
      channel: "",
      mode: "",
    }
  ));
  const filteredFeatures = getFilteredAdminFeatures();
  const showToolResults = state.adminFeaturePickerOpen;

  const wrapper = document.createElement("div");
  wrapper.className = "admin-users-view admin-users-detail-view";

  const strip = document.createElement("div");
  strip.className = "admin-detail-strip";
  const roleBadge = createAdminStateBadge(user.isAdmin ? "Admin" : "Client");

  const clientTypeBadge = createAdminStateBadge(
    getAdminClientTypeLabel(user.clientType),
    getAdminClientTypeClass(user.clientType),
  );

  const activeBadge = createAdminStateBadge(
    isStatusSaving ? "Saving status" : user.isActive ? "Active" : "Inactive",
    user.isActive ? "is-active-client" : "is-inactive-client",
  );

  const toolsBadge = document.createElement("span");
  toolsBadge.className = "feature-status";
  toolsBadge.textContent = `${draftFeatureIds.length} visible tool${draftFeatureIds.length === 1 ? "" : "s"}`;

  strip.append(roleBadge, clientTypeBadge, activeBadge, toolsBadge);

  const grid = document.createElement("div");
  grid.className = "admin-detail-grid";

  const infoPanel = document.createElement("section");
  infoPanel.className = "admin-detail-panel";
  const infoTitle = document.createElement("h4");
  infoTitle.textContent = "Account";
  const infoRows = document.createElement("div");
  infoRows.className = "detail-stack";
  infoRows.append(
    createAdminDetailRow("Client type", getAdminClientTypeLabel(user.clientType)),
    createAdminDetailRow("Login", user.isActive ? "Active" : "Inactive"),
    createAdminDetailRow("Registered", formatAdminDateTime(user.registeredAt) || "Unknown"),
    createAdminDetailRow("Last login", user.lastLoginAt ? formatAdminDateTime(user.lastLoginAt) : "No login yet"),
    createAdminDetailRow("Usage events", String(Number.isFinite(user.usageCount) ? user.usageCount : 0)),
  );

  const infoActions = document.createElement("div");
  infoActions.className = "admin-detail-panel-actions";

  const statusControl = createAdminActiveSwitch(user, {
    disabled: isSaving || isDeleting,
  });
  const clientTypeControl = createAdminClientTypeSelect(user, {
    disabled: isSaving || isDeleting || isStatusSaving,
  });
  infoActions.append(clientTypeControl);
  infoActions.append(statusControl);

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "ghost-button small";
  editButton.dataset.adminOpenEditUser = user.email;
  editButton.disabled = isSaving || isDeleting || isStatusSaving;
  editButton.textContent = "Edit client";
  infoActions.append(editButton);

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "ghost-button danger small";
  deleteButton.dataset.adminDeleteUser = user.email;
  deleteButton.disabled = isSaving || isDeleting || isStatusSaving || Boolean(deleteDisabledReason);
  deleteButton.textContent = isDeleting ? "Deleting..." : "Delete client";
  infoActions.append(deleteButton);

  infoPanel.append(infoTitle, infoRows, infoActions);
  if (deleteDisabledReason) {
    const deleteNote = document.createElement("p");
    deleteNote.className = "admin-danger-note is-warn";
    deleteNote.textContent = deleteDisabledReason;
    infoPanel.append(deleteNote);
  }

  const accessPanel = document.createElement("section");
  accessPanel.className = "admin-detail-panel admin-detail-access-panel";

  const accessTitle = document.createElement("h4");
  accessTitle.textContent = "Visible tools";

  const availableFeatures = filteredFeatures.filter((feature) => !draftFeatureIds.includes(feature.featureId));

  const picker = document.createElement("div");
  picker.className = "admin-tool-picker";
  picker.dataset.adminFeaturePicker = "true";

  const searchField = document.createElement("label");
  searchField.className = "field admin-tool-search-field";

  const searchLabel = document.createElement("span");
  searchLabel.textContent = "Search tools";

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.placeholder = "Click to browse all tools or type to filter";
  searchInput.value = state.adminFeatureSearch;
  searchInput.autocomplete = "off";
  searchInput.disabled = toolInputsDisabled;
  searchInput.dataset.adminFeatureSearchInput = "true";
  searchInput.setAttribute("aria-expanded", String(showToolResults));

  searchField.append(searchLabel, searchInput);

  const results = document.createElement("div");
  results.className = `admin-tool-results${showToolResults ? "" : " is-hidden"}`;

  if (!state.adminFeatures.length) {
    const empty = document.createElement("p");
    empty.className = "admin-empty-copy";
    empty.textContent = "No active tools are available to assign.";
    results.append(empty);
  } else if (!availableFeatures.length && !state.adminFeatureSearch) {
    const empty = document.createElement("p");
    empty.className = "admin-empty-copy";
    empty.textContent = "All tools are already assigned.";
    results.append(empty);
  } else if (!availableFeatures.length) {
    const empty = document.createElement("p");
    empty.className = "admin-empty-copy";
    empty.textContent = "No tools match that search.";
    results.append(empty);
  } else {
    results.append(
      ...availableFeatures.map((feature) => createAdminFeatureSearchResult(feature, {
        disabled: toolInputsDisabled,
        userEmail: user.email,
      })),
    );
  }

  picker.append(searchField, results);

  const assignedShell = document.createElement("div");
  assignedShell.className = "admin-assigned-tools-shell";

  const assignedHead = document.createElement("div");
  assignedHead.className = "admin-assigned-tools-head";

  const assignedTitle = document.createElement("h5");
  assignedTitle.textContent = "Assigned tools";

  const assignedCount = document.createElement("span");
  assignedCount.className = "status-pill";
  assignedCount.textContent = `${assignedFeatures.length} selected`;

  assignedHead.append(assignedTitle, assignedCount);

  const assignedList = document.createElement("div");
  assignedList.className = "admin-assigned-tools";
  if (!assignedFeatures.length) {
    const empty = document.createElement("p");
    empty.className = "admin-tool-badge-empty";
    empty.textContent = "No tools assigned yet.";
    assignedList.append(empty);
  } else {
    assignedList.append(
      ...assignedFeatures.map((feature) => createAdminAssignedFeatureBadge(feature, {
        userEmail: user.email,
        disabled: toolInputsDisabled,
      })),
    );
  }

  assignedShell.append(assignedHead, assignedList);

  const actions = document.createElement("div");
  actions.className = "card-actions admin-user-actions";

  const summary = document.createElement("span");
  summary.className = "admin-user-summary";
  if (isDeleting) {
    summary.textContent = "Deleting user…";
  } else if (isSaving) {
    summary.textContent = "Saving changes…";
  } else if (hasChanges) {
    summary.textContent = "Changes not saved";
  } else {
    summary.textContent = "All access changes saved";
  }

  actions.append(summary);
  accessPanel.append(accessTitle, picker, assignedShell, actions);

  grid.append(infoPanel, accessPanel);
  wrapper.append(strip, grid);
  return wrapper;
}

function renderAdminUsersPane() {
  const adminVisible = canManageClients();
  if (elements.adminUsersMenuItem) {
    elements.adminUsersMenuItem.classList.toggle("is-hidden", !adminVisible);
  }

  if (
    !elements.adminUsersPane
    || !elements.adminUsersShell
    || !elements.adminUsersContent
  ) {
    return;
  }

  if (!adminVisible) {
    elements.adminUsersShell.classList.remove("is-hidden");
    elements.adminUsersShell.classList.remove("is-add-view");
    elements.adminUsersShell.classList.remove("is-detail-view");
    return;
  }

  if (elements.adminUsersError) {
    syncAdminUsersError();
  }
  if (
    (state.adminView === "detail" || state.adminView === "edit")
    && !state.adminUsersLoading
    && !getAdminSelectedUser()
  ) {
    state.adminView = "list";
    state.adminSelectedUserEmail = "";
  }

  if (elements.adminOpenAddUserButton) {
    elements.adminOpenAddUserButton.classList.toggle("is-hidden", state.adminView !== "list");
    elements.adminOpenAddUserButton.disabled = false;
  }

  if (state.adminView === "add") {
    elements.adminUsersShell.classList.add("is-add-view");
    elements.adminUsersShell.classList.remove("is-detail-view");
    if (elements.adminUsersError) {
      elements.adminUsersError.classList.add("is-hidden");
    }
    elements.adminUsersContent.replaceChildren(createAdminAddUserView());
    return;
  }

  if (state.adminView === "edit") {
    elements.adminUsersShell.classList.add("is-add-view");
    elements.adminUsersShell.classList.remove("is-detail-view");
    if (elements.adminUsersError) {
      elements.adminUsersError.classList.add("is-hidden");
    }
    elements.adminUsersContent.replaceChildren(createAdminEditUserView(getAdminSelectedUser()));
    return;
  }

  elements.adminUsersShell.classList.remove("is-add-view");

  if (state.adminView === "detail") {
    elements.adminUsersShell.classList.add("is-detail-view");
    elements.adminUsersContent.replaceChildren(createAdminUserDetailView(getAdminSelectedUser()));
    return;
  }

  elements.adminUsersShell.classList.remove("is-detail-view");
  elements.adminUsersContent.replaceChildren(createAdminUsersListView());
}

async function refreshAdminUsers(options = {}) {
  const shouldRender = options.render !== false;
  if (!canManageClients()) {
    return null;
  }

  if (state.adminUsersLoading) {
    if (shouldRender) {
      state.adminUsersNeedsRender = true;
    }
    return null;
  }

  state.adminUsersLoading = true;
  state.adminUsersNeedsRender = shouldRender;
  state.adminUsersError = "";
  if (shouldRender && document.body.dataset.view === "app") {
    renderApp();
  }

  try {
    const previousUsersByEmail = new Map(state.adminUsers.map((user) => [user.email, user]));
    const previousDrafts = state.adminUserDrafts;
    const response = await apiRequest("/api/admin/users", {
      headers: getSessionAuthHeaders(),
      timeoutMs: options.timeoutMs || 15000,
    });

    state.adminFeatures = (Array.isArray(response.features) ? response.features : [])
      .map((feature) => normalizeAdminFeatureRecord(feature))
      .filter((feature) => feature.featureId)
      .sort((left, right) => {
        const leftSort = Number.isFinite(left.sortOrder) ? left.sortOrder : 100;
        const rightSort = Number.isFinite(right.sortOrder) ? right.sortOrder : 100;
        if (leftSort !== rightSort) {
          return leftSort - rightSort;
        }
        return left.name.localeCompare(right.name);
      });
    state.adminUsers = sortAdminUsers((Array.isArray(response.users) ? response.users : [])
      .map((user) => normalizeAdminUserRecord(user))
      .filter((user) => user.email));
    state.adminUserDrafts = buildAdminUserDrafts(state.adminUsers, previousUsersByEmail, previousDrafts);
    if (state.adminView === "detail" && !state.adminUsers.some((user) => user.email === state.adminSelectedUserEmail)) {
      state.adminView = "list";
      state.adminSelectedUserEmail = "";
    }

    if (authSession) {
      authSession = normalizeStoredSession({
        ...authSession,
        isAdmin: Boolean(response.currentUser?.isAdmin),
      });
      persistJson(AUTH_SESSION_KEY, authSession);
    }
    state.settingsMode = normalizeSettingsMode(state.settingsMode);
    return response;
  } catch (error) {
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t load clients right now.");
    if (Number(error?.status || 0) === 403 && authSession) {
      authSession = normalizeStoredSession({
        ...authSession,
        isAdmin: false,
      });
      persistJson(AUTH_SESSION_KEY, authSession);
      state.settingsMode = "account";
    }
    return null;
  } finally {
    state.adminUsersLoading = false;
    if (document.body.dataset.view === "app" && state.adminUsersNeedsRender) {
      state.adminUsersNeedsRender = false;
      renderApp();
    }
  }
}

async function refreshOpportunities(options = {}) {
  const shouldRender = options.render !== false;
  if (!canReviewOpportunities()) {
    state.opportunities = [];
    state.opportunitiesError = "";
    state.opportunitiesLoading = false;
    return null;
  }

  if (state.opportunitiesLoading) {
    return null;
  }

  state.opportunitiesLoading = true;
  state.opportunitiesError = "";
  if (shouldRender && document.body.dataset.view === "app") {
    renderApp({ preserveStatus: true });
  }

  try {
    const response = await apiRequest("/api/admin/opportunities?limit=200", {
      headers: getSessionAuthHeaders(),
      timeoutMs: options.timeoutMs || 15000,
    });
    state.opportunities = sortOpportunitiesByUrgency(
      (Array.isArray(response.opportunities) ? response.opportunities : [])
        .map((opportunity) => normalizeOpportunityRecord(opportunity))
        .filter((opportunity) => opportunity.id > 0),
    );
    state.opportunitiesLoadedAt = Date.now();
    return response;
  } catch (error) {
    state.opportunitiesError = formatApiErrorMessage(error, "We couldn’t load opportunities right now.");
    if (Number(error?.status || 0) === 403 && state.activeTab === "opportunities") {
      state.activeTab = "features";
      state.lastPrimaryTab = "features";
      persistLastPrimaryTab();
      setHashForTab("features");
    }
    return null;
  } finally {
    state.opportunitiesLoading = false;
    if (shouldRender && document.body.dataset.view === "app") {
      renderApp({ preserveStatus: true });
    }
  }
}

async function addAdminUser() {
  if (!canManageClients() || state.adminAddUserBusy) {
    return;
  }

  const email = normalizeEmail(state.adminNewUserEmail);
  const displayName = normalizeText(state.adminNewUserDisplayName);

  if (!validateEmail(email)) {
    state.adminUsersError = "Enter a valid email address before adding the client.";
    renderApp();
    return;
  }

  state.adminAddUserBusy = true;
  state.adminUsersError = "";
  renderApp();

  let didSucceed = false;
  try {
    const response = await apiRequest("/api/admin/users", {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        email,
        displayName,
      },
    });

    state.adminNewUserEmail = "";
    state.adminNewUserDisplayName = "";
    const createdUser = upsertAdminUserState(response.user || {
      email,
      displayName,
      assignedFeatureIds: [],
    });

    state.adminView = "detail";
    state.adminSelectedUserEmail = createdUser?.email || email;
    didSucceed = true;
    void refreshAdminUsers({ render: false });
  } catch (error) {
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t add that user right now.");
  } finally {
    state.adminAddUserBusy = false;
    renderApp();
    if (didSucceed) {
      setStatus("Client added");
    }
  }
}

async function saveAdminUserDetails() {
  const user = getAdminSelectedUser();
  if (!canManageClients() || !user || state.adminEditUserBusy) {
    return;
  }

  const currentEmail = normalizeEmail(user.email);
  const nextEmail = normalizeEmail(state.adminEditUserEmail);
  const nextDisplayName = normalizeText(state.adminEditUserDisplayName);

  if (!validateEmail(nextEmail)) {
    state.adminUsersError = "Enter a valid email address before saving.";
    renderApp();
    return;
  }

  state.adminEditUserBusy = true;
  state.adminUsersError = "";
  renderApp();

  let updatedUser = null;
  try {
    const response = await apiRequest(`/api/admin/users/${encodeURIComponent(currentEmail)}`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        email: nextEmail,
        displayName: nextDisplayName,
      },
    });

    updatedUser = replaceAdminUserState(currentEmail, response.user || {
      ...user,
      email: nextEmail,
      displayName: nextDisplayName,
    });
    state.adminSelectedUserEmail = updatedUser?.email || nextEmail;
    state.adminView = "detail";
    state.adminEditUserEmail = "";
    state.adminEditUserDisplayName = "";
    void refreshAdminUsers({ render: false });
  } catch (error) {
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t update that user right now.");
  } finally {
    state.adminEditUserBusy = false;
    renderApp();
    if (updatedUser) {
      setStatus("Client updated");
    }
  }
}

async function saveAdminUserStatus(email, isActive) {
  const normalizedEmail = normalizeEmail(email);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!canManageClients() || !user || state.adminStatusBusyByEmail[normalizedEmail]) {
    return;
  }

  const disabledReason = getAdminUserActiveDisabledReason(user, Boolean(isActive));
  if (disabledReason) {
    openAuthAlert("Client status unavailable", disabledReason, {
      eyebrow: "Client status",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    });
    return;
  }

  state.adminStatusBusyByEmail = {
    ...state.adminStatusBusyByEmail,
    [normalizedEmail]: true,
  };
  state.adminUsersError = "";
  renderApp();

  let updatedUser = null;
  try {
    const response = await apiRequest(`/api/admin/users/${encodeURIComponent(normalizedEmail)}/status`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        isActive: Boolean(isActive),
      },
    });

    updatedUser = upsertAdminUserState(response.user || {
      ...user,
      isActive: Boolean(isActive),
    });
    void refreshAdminUsers({ render: false });
  } catch (error) {
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t update that client right now.");
    openAuthAlert("Couldn’t update client", state.adminUsersError, {
      eyebrow: "Client status",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    });
  } finally {
    const { [normalizedEmail]: _ignore, ...nextBusy } = state.adminStatusBusyByEmail;
    state.adminStatusBusyByEmail = nextBusy;
    renderApp();
    if (updatedUser) {
      setStatus(updatedUser.isActive ? "Client activated" : "Client disabled");
    }
  }
}

async function saveAdminUserClientType(email, clientType) {
  const normalizedEmail = normalizeEmail(email);
  const normalizedClientType = normalizeAdminClientType(clientType);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!canManageClients() || !user || !normalizedClientType || state.adminTypeBusyByEmail[normalizedEmail]) {
    return;
  }

  const previousClientType = normalizeAdminClientType(user.clientType) || deriveAdminClientType(user.paymentStatus);
  if (previousClientType === normalizedClientType) {
    return;
  }

  state.adminTypeBusyByEmail = {
    ...state.adminTypeBusyByEmail,
    [normalizedEmail]: true,
  };
  state.adminUsers = state.adminUsers.map((entry) => (
    entry.email === normalizedEmail
      ? { ...entry, clientType: normalizedClientType }
      : entry
  ));
  state.adminUsersError = "";
  renderApp();

  let updatedUser = null;
  try {
    const response = await apiRequest(`/api/admin/users/${encodeURIComponent(normalizedEmail)}/client-type`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        clientType: normalizedClientType,
      },
    });

    updatedUser = upsertAdminUserState(response.user || {
      ...user,
      clientType: normalizedClientType,
    });
    void refreshAdminUsers({ render: false });
  } catch (error) {
    state.adminUsers = state.adminUsers.map((entry) => (
      entry.email === normalizedEmail
        ? { ...entry, clientType: previousClientType }
        : entry
    ));
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t update that client type right now.");
    openAuthAlert("Couldn’t update client type", state.adminUsersError, {
      eyebrow: "Client type",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    });
  } finally {
    const { [normalizedEmail]: _ignore, ...nextBusy } = state.adminTypeBusyByEmail;
    state.adminTypeBusyByEmail = nextBusy;
    renderApp();
    if (updatedUser) {
      setStatus(`Client type set to ${getAdminClientTypeLabel(updatedUser.clientType)}`);
    }
  }
}

async function saveAdminUserFeatures(email) {
  const normalizedEmail = normalizeEmail(email);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!canManageClients() || !user || state.adminSaveBusyByEmail[normalizedEmail]) {
    return;
  }

  const requestedFeatureIds = getAdminUserDraftFeatureIds(normalizedEmail, user.assignedFeatureIds);
  state.adminSaveBusyByEmail = {
    ...state.adminSaveBusyByEmail,
    [normalizedEmail]: true,
  };
  state.adminUsersError = "";
  renderApp();

  let didSucceed = false;
  try {
    await apiRequest(`/api/admin/users/${encodeURIComponent(normalizedEmail)}/features`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        assignedFeatureIds: requestedFeatureIds,
      },
    });

    state.adminUsers = state.adminUsers.map((entry) => (
      entry.email === normalizedEmail
        ? {
          ...entry,
          assignedFeatureIds: [...requestedFeatureIds],
        }
        : entry
    ));

    if (normalizedEmail === activeEmail) {
      await refreshFeatureActivationStates({ render: false });
      try {
        await refreshWhatsAppConnection({ render: false });
      } catch {
        // Keep the user access update even if the follow-up refresh fails.
      }
    }

    await refreshAdminUsers({ render: false });
    didSucceed = true;
  } catch (error) {
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t save tool access right now.");
  } finally {
    const { [normalizedEmail]: _ignore, ...nextBusy } = state.adminSaveBusyByEmail;
    state.adminSaveBusyByEmail = nextBusy;
    const latestUser = state.adminUsers.find((entry) => entry.email === normalizedEmail) || null;
    const shouldRetry = didSucceed
      && Boolean(latestUser)
      && (
        Boolean(state.adminSaveQueuedByEmail[normalizedEmail])
        || !featureIdListsMatch(
          getAdminUserDraftFeatureIds(normalizedEmail, latestUser.assignedFeatureIds),
          latestUser.assignedFeatureIds,
        )
      );
    setAdminUserSaveQueued(normalizedEmail, false);
    renderApp();
    if (didSucceed) {
      setStatus("Client access saved");
    }
    if (shouldRetry && !state.adminDeleteBusyByEmail[normalizedEmail]) {
      void saveAdminUserFeatures(normalizedEmail);
    }
  }
}

function deleteAdminUser(email) {
  const normalizedEmail = normalizeEmail(email);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!canManageClients() || !user || state.adminDeleteBusyByEmail[normalizedEmail]) {
    return;
  }

  const disabledReason = getAdminUserDeleteDisabledReason(user);
  if (disabledReason) {
    openAuthAlert("Delete client unavailable", disabledReason, {
      eyebrow: "Delete client",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    });
    return;
  }

  const label = user.displayName || deriveDisplayName(user.email);
  openAuthAlert(
    "Are you sure?",
    `Delete ${label} (${normalizedEmail})? This removes their portal access, assigned tools, billing history, WhatsApp setup, and saved messages.`,
    {
      eyebrow: "Delete client",
      buttonLabel: "Delete client",
      secondaryButtonLabel: "Cancel",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
      focusTarget: "secondary",
      onPrimary: () => {
        void confirmAdminUserDelete(normalizedEmail);
      },
    },
  );
}

async function confirmAdminUserDelete(email) {
  const normalizedEmail = normalizeEmail(email);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!canManageClients() || !user || state.adminDeleteBusyByEmail[normalizedEmail]) {
    return;
  }

  state.adminDeleteBusyByEmail = {
    ...state.adminDeleteBusyByEmail,
    [normalizedEmail]: true,
  };
  state.adminUsersError = "";
  renderApp();

  let didSucceed = false;
  try {
    await apiRequest(`/api/admin/users/${encodeURIComponent(normalizedEmail)}`, {
      method: "DELETE",
      headers: getSessionAuthHeaders(),
    });

    persistJson(getClientKey(normalizedEmail), null);
    removeAdminUserState(normalizedEmail);
    state.adminFeatureSearch = "";
    state.adminFeaturePickerOpen = false;
    didSucceed = true;
    void refreshAdminUsers({ render: false });
  } catch (error) {
    openAuthAlert(
      "Couldn’t delete client",
      formatApiErrorMessage(error, "We couldn’t delete that client right now."),
      {
        eyebrow: "Delete client",
      },
    );
  } finally {
    const { [normalizedEmail]: _ignore, ...nextBusy } = state.adminDeleteBusyByEmail;
    state.adminDeleteBusyByEmail = nextBusy;
    renderApp();
    if (didSucceed) {
      setStatus("Client deleted");
    }
  }
}

function updateHeader() {
  const displayName = getDisplayName();
  const workspaceName = getWorkspaceName();
  const selectedFeature = getSelectedFeature();
  const settingsLabel = state.settingsMode === "users"
    ? getSettingsModeContent(state.settingsMode).title
    : "Settings";
  const titleLabel = state.settingsOpen
    ? settingsLabel
    : state.selectedFeatureId && selectedFeature
      ? selectedFeature.name
      : TAB_LABELS[state.activeTab] || capitalizeWords(state.activeTab);
  if (elements.workspaceTitle) {
    elements.workspaceTitle.textContent = workspaceName;
  }
  if (elements.workspaceSubtitle) {
    elements.workspaceSubtitle.textContent = `Signed in as ${displayName}`;
  }
  elements.accountAvatar.textContent = getAvatarLabel();
  elements.accountLabel.textContent = activeEmail;
  document.title = `${workspaceName} · ${titleLabel}`;
}

function getAgentWorkspace() {
  if (!clientState.agent) {
    clientState.agent = createDefaultAgentWorkspace();
  }

  clientState.agent = normalizeAgentWorkspace(clientState.agent);
  return clientState.agent;
}

function normalizeAgentDeliveryChannel(value) {
  const text = String(value || "").toLowerCase();
  if (/\bwhats\s*app\b|\bwhatsapp\b/.test(text)) {
    return "whatsapp";
  }
  if (/\btelegram\b/.test(text)) {
    return "telegram";
  }
  if (/\bemail\b|\bmail\b/.test(text)) {
    return "email";
  }
  if (/\bportal\b|\bworkspace\b|\bchat\b/.test(text)) {
    return "portal";
  }
  return "";
}

function extractAgentTimeLocal(text) {
  const value = String(text || "");
  const colonMatch = value.match(/\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*(a\.?m\.?|p\.?m\.?|am|pm)?\b/i);
  const hourOnlyMatch = value.match(/\b(1[0-2]|0?[1-9])\s*(a\.?m\.?|p\.?m\.?|am|pm)\b/i);
  const match = colonMatch || hourOnlyMatch;
  if (!match) {
    return "";
  }

  let hour = Number.parseInt(match[1], 10);
  const minute = colonMatch ? Number.parseInt(match[2], 10) : 0;
  const meridiem = String(colonMatch ? match[3] || "" : match[2] || "").toLowerCase().replace(/\./g, "");
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) {
    return "";
  }
  if (meridiem === "pm" && hour < 12) {
    hour += 12;
  }
  if (meridiem === "am" && hour === 12) {
    hour = 0;
  }
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return "";
  }
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function extractAgentDatePolicy(text) {
  const value = String(text || "").toLowerCase();
  if (/\btomorrow\b/.test(value)) {
    return "tomorrow";
  }
  if (/\btoday\b|\btonight\b/.test(value)) {
    return "today";
  }
  return "next_occurrence";
}

function getAgentDefaultScheduledMessageText(timeLocal = "") {
  const normalizedTime = String(timeLocal || "").trim();
  return normalizedTime ? `It's ${normalizedTime}.` : "";
}

function isAgentDefaultScheduledMessageText(messageText, timeLocal = "") {
  return String(messageText || "").trim() === getAgentDefaultScheduledMessageText(timeLocal);
}

function extractAgentScheduledMessageText(text, timeLocal = "") {
  const value = String(text || "").trim();
  const quotedMatch = value.match(/\b(?:saying|that says|with text|message(?: saying)?|text)\s+["“']([^"”']{1,400})["”']/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1].trim();
  }

  const reminderMatch = value.match(/\bremind me to\s+(.+?)\s+(?:at|when|by)\b/i);
  if (reminderMatch?.[1]) {
    return reminderMatch[1].trim();
  }

  if (timeLocal) {
    return getAgentDefaultScheduledMessageText(timeLocal);
  }
  return "";
}

function isAgentScheduledMessageRequest(text) {
  const value = String(text || "").toLowerCase();
  const asksForSend = /\b(send|message|notify|remind|alert)\b/.test(value);
  const hasTimeTrigger = Boolean(extractAgentTimeLocal(value)) || /\b(today|tomorrow|tonight)\b/.test(value);
  return asksForSend && hasTimeTrigger;
}

function resolveAgentScheduledRunAt(details = {}, now = new Date()) {
  const timeLocal = String(details.timeLocal || "").trim();
  const timeMatch = timeLocal.match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!timeMatch) {
    return "";
  }

  const timeZone = normalizeMonitorScheduleTimezone(
    details.timezone || clientState?.settings?.timezone || defaultTimeZone(),
    "UTC",
  ) || "UTC";
  const currentTime = now instanceof Date && !Number.isNaN(now.getTime()) ? now : new Date();
  const currentParts = getMonitorZonedDateTimeParts(currentTime, timeZone);
  if (!currentParts) {
    return "";
  }

  const hour = Number.parseInt(timeMatch[1], 10);
  const minute = Number.parseInt(timeMatch[2], 10);
  let dateParts = {
    year: currentParts.year,
    month: currentParts.month,
    day: currentParts.day,
  };
  const datePolicy = String(details.datePolicy || "next_occurrence").trim();
  if (datePolicy === "tomorrow") {
    dateParts = addMonitorUtcDays(dateParts, 1);
  }

  let candidate = buildMonitorDateInTimeZone({
    ...dateParts,
    hour,
    minute,
    second: 0,
  }, timeZone);

  if (datePolicy === "next_occurrence" && candidate && candidate.getTime() <= currentTime.getTime()) {
    dateParts = addMonitorUtcDays(dateParts, 1);
    candidate = buildMonitorDateInTimeZone({
      ...dateParts,
      hour,
      minute,
      second: 0,
    }, timeZone);
  }

  return candidate && !Number.isNaN(candidate.getTime()) ? candidate.toISOString() : "";
}

function buildAgentScheduledMessageQuestionPlan(details = {}) {
  const questions = [];
  const questionKeys = [];
  if (!normalizeAgentDeliveryChannel(details.channel)) {
    questionKeys.push("channel");
    questions.push("Which channel should I use to send it?");
  }
  if (!String(details.timeLocal || details.runAt || "").trim()) {
    questionKeys.push("time");
    questions.push("What exact local time should I send it?");
  }
  if (!String(details.messageText || "").trim()) {
    questionKeys.push("messageText");
    questions.push("What should the message say?");
  }
  return { questions, questionKeys };
}

function buildAgentScheduledMessageDetails(text) {
  const requestText = String(text || "");
  const channel = normalizeAgentDeliveryChannel(requestText);
  const timeLocal = extractAgentTimeLocal(requestText);
  const timezone = normalizeMonitorScheduleTimezone(clientState?.settings?.timezone || defaultTimeZone(), "UTC") || "UTC";
  const datePolicy = extractAgentDatePolicy(requestText);
  const messageText = extractAgentScheduledMessageText(requestText, timeLocal);
  const messageSource = messageText && !isAgentDefaultScheduledMessageText(messageText, timeLocal)
    ? "user"
    : "generated";
  const details = {
    actionType: "send_message",
    channel,
    recipientRef: /\b(me|myself|owner)\b/i.test(requestText) ? "owner" : "owner",
    timeLocal,
    datePolicy,
    timezone,
    messageText,
    messageSource,
    runAt: "",
  };
  details.runAt = resolveAgentScheduledRunAt(details);
  return details;
}

function buildAgentScheduledMessageExecutionPlan(details = {}) {
  return {
    trigger: {
      type: "at",
      runAt: String(details.runAt || "").trim(),
      timeLocal: String(details.timeLocal || "").trim(),
      timezone: String(details.timezone || "").trim(),
      datePolicy: String(details.datePolicy || "next_occurrence").trim(),
    },
    action: {
      type: "send_message",
      channel: normalizeAgentDeliveryChannel(details.channel),
      recipientRef: String(details.recipientRef || "owner").trim(),
      messageText: String(details.messageText || "").trim(),
    },
  };
}

function formatAgentScheduledMessageChannel(channel) {
  const normalized = normalizeAgentDeliveryChannel(channel);
  if (normalized === "whatsapp") {
    return "WhatsApp";
  }
  if (normalized === "telegram") {
    return "Telegram";
  }
  if (normalized === "email") {
    return "email";
  }
  if (normalized === "portal") {
    return "this workspace";
  }
  return "the chosen channel";
}

function getAgentBlueprintForText(text) {
  const value = String(text || "").toLowerCase();
  if (isAgentScheduledMessageRequest(value)) {
    return AGENT_BLUEPRINTS.scheduledMessage;
  }

  if (/\b(gmail|inbox|email|mailbox|digest|summari[sz]e|summary)\b/.test(value)) {
    return AGENT_BLUEPRINTS.emailDigest;
  }

  if (/\b(re-?engage|follow[- ]?up|past customer|quiet conversation|dormant)\b/.test(value)) {
    return AGENT_BLUEPRINTS.reengagement;
  }

  if (/\b(whatsapp|reply|approval|lead|customer message)\b/.test(value)) {
    return AGENT_BLUEPRINTS.whatsappReplies;
  }

  if (/\b(watch|monitor|deadline|alert|web|search|opportunit|event)\b/.test(value)) {
    return AGENT_BLUEPRINTS.webMonitor;
  }

  return AGENT_BLUEPRINTS.custom;
}

function getAgentBlueprintForType(type) {
  const normalizedType = String(type || "").trim();
  return Object.values(AGENT_BLUEPRINTS).find((blueprint) => blueprint.type === normalizedType)
    || AGENT_BLUEPRINTS.custom;
}

function cloneAgentItems(items = []) {
  return Array.isArray(items) ? items.map((item) => ({ ...item })) : [];
}

function createAgentProposalFromRequest(text, blueprintOverride = null) {
  const blueprint = blueprintOverride && typeof blueprintOverride === "object"
    ? blueprintOverride
    : getAgentBlueprintForText(text);
  const scheduledDetails = blueprint.type === "scheduled-message" ? buildAgentScheduledMessageDetails(text) : {};
  const inferredFields = blueprint.type === "scheduled-message"
    ? {}
    : inferAgentProposalFieldsFromText(text, blueprint.type);
  if (blueprint.type === "whatsapp-replies" && isWhatsAppConnectionReady()) {
    inferredFields.whatsappNumber = inferredFields.whatsappNumber || "connected WhatsApp number";
    inferredFields.deliveryChannel = inferredFields.deliveryChannel || "portal";
  }
  const scheduledQuestionPlan = blueprint.type === "scheduled-message"
    ? buildAgentScheduledMessageQuestionPlan(scheduledDetails)
    : { questions: [...blueprint.questions], questionKeys: [] };
  const scheduledChannel = normalizeAgentDeliveryChannel(scheduledDetails.channel);
  const relatedFeatureId = blueprint.type === "scheduled-message" && scheduledChannel === "whatsapp"
    ? WHATSAPP_REPLY_ASSISTANT_FEATURE_ID
    : blueprint.relatedFeatureId;
  const missingCredential = blueprint.type === "scheduled-message" && scheduledChannel === "whatsapp"
    ? (isFeatureSetupComplete(getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID)) ? "" : "WhatsApp Business API access token")
    : blueprint.type === "whatsapp-replies" && isWhatsAppConnectionReady()
      ? ""
      : blueprint.missingCredential;
  const proposal = normalizeAgentProposal({
    id: createAgentId("agent-proposal"),
    type: blueprint.type,
    requestText: String(text || "").trim(),
    title: blueprint.title,
    summary: blueprint.summary,
    response: blueprint.response,
    relatedFeatureId,
    primaryActionLabel: blueprint.primaryActionLabel,
    setupActionLabel: blueprint.setupActionLabel,
    missingCredential,
    status: "needs-approval",
    approved: false,
    revision: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    details: scheduledDetails,
    fields: inferredFields,
    executionPlan: blueprint.type === "scheduled-message"
      ? buildAgentScheduledMessageExecutionPlan(scheduledDetails)
      : {},
    skills: cloneAgentItems(blueprint.skills),
    helpers: cloneAgentItems(blueprint.helpers),
    questions: scheduledQuestionPlan.questions,
    questionKeys: scheduledQuestionPlan.questionKeys,
    alternatives: [...blueprint.alternatives],
  });

  if (proposal.type === "custom") {
    proposal.summary = `${blueprint.summary} Request: "${String(text).trim().slice(0, 140)}"`;
  }
  if (proposal.type === "scheduled-message") {
    const channelLabel = formatAgentScheduledMessageChannel(scheduledDetails.channel);
    const timeLabel = scheduledDetails.timeLocal ? ` at ${scheduledDetails.timeLocal}` : "";
    proposal.summary = `Schedule a one-shot ${channelLabel} message${timeLabel}.`;
  } else {
    updateAgentProposalSummaryFromFields(proposal);
  }

  return proposal;
}

function getActiveAgentProposal() {
  const agent = getAgentWorkspace();
  return agent.proposals.find((proposal) => proposal.id === agent.activeProposalId)
    || agent.proposals[agent.proposals.length - 1]
    || null;
}

function getLatestApprovedAgentProposal() {
  const agent = getAgentWorkspace();
  return [...agent.proposals].reverse().find((proposal) => proposal.approved) || null;
}

function pushAgentMessage(role, text, metadata = {}) {
  const agent = getAgentWorkspace();
  const message = createAgentMessage(role, text, metadata);
  if (!message.text) {
    return null;
  }

  agent.messages.push(message);
  agent.messages = agent.messages.slice(-AGENT_MAX_MESSAGES);
  return message;
}

function createAgentAction(id, label, value = label, tone = "secondary") {
  return { id, label, value, tone };
}

function resolveAgentMessageActions(messageId, resolvedBy = "user-message") {
  const agent = getAgentWorkspace();
  const message = agent.messages.find((candidate) => candidate.id === messageId);
  if (!message || !Array.isArray(message.metadata?.actions) || !message.metadata.actions.length) {
    return false;
  }

  message.metadata.actionsResolvedAt = message.metadata.actionsResolvedAt || new Date().toISOString();
  message.metadata.actionsResolvedBy = String(resolvedBy || "user-message").trim();
  return true;
}

function resolvePendingAgentMessageActions(resolvedBy = "user-message") {
  const agent = getAgentWorkspace();
  let didResolve = false;
  for (const message of agent.messages) {
    if (message.role !== "assistant" || message.metadata?.actionsResolvedAt) {
      continue;
    }
    if (!Array.isArray(message.metadata?.actions) || !message.metadata.actions.length) {
      continue;
    }
    message.metadata.actionsResolvedAt = new Date().toISOString();
    message.metadata.actionsResolvedBy = String(resolvedBy || "user-message").trim();
    didResolve = true;
  }
  return didResolve;
}

function areAgentMessageActionsResolved(message, messages = []) {
  if (message.metadata?.actionsResolvedAt) {
    return true;
  }

  const messageIndex = messages.findIndex((candidate) => candidate.id === message.id);
  return messageIndex >= 0 && messageIndex < messages.length - 1;
}

function normalizeAgentProposalFieldKey(key) {
  const rawKey = String(key || "").trim();
  if (!rawKey) {
    return "";
  }
  const aliasKey = rawKey
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s.-]+/g, "_")
    .replace(/[^a-zA-Z0-9_]/g, "")
    .toLowerCase();
  return AGENT_PROPOSAL_FIELD_ALIASES[aliasKey] || rawKey.replace(/[^a-zA-Z0-9_]/g, "").slice(0, 80);
}

function getAgentProposalFieldKeyForSchema(rawKey, allowedKeys) {
  let key = normalizeAgentProposalFieldKey(rawKey);
  if (allowedKeys.has(key)) {
    return key;
  }

  const aliasKey = String(rawKey || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s.-]+/g, "_")
    .replace(/[^a-zA-Z0-9_]/g, "")
    .toLowerCase();
  if (["schedule", "time", "cadence", "interval"].includes(aliasKey) && allowedKeys.has("frequency")) {
    key = "frequency";
  } else if (["schedule", "time", "send_time", "sendtime"].includes(aliasKey) && allowedKeys.has("schedule")) {
    key = "schedule";
  }
  return allowedKeys.has(key) ? key : "";
}

function getAgentProposalFieldSchema(proposal) {
  const requestText = String(proposal?.requestText || "");
  if (
    proposal?.type === "custom"
    && /\b(calendar|schedule|agenda|appointments?)\b/i.test(requestText)
  ) {
    return AGENT_CALENDAR_FIELD_SCHEMA;
  }
  return AGENT_PROPOSAL_FIELD_SCHEMAS[proposal?.type] || AGENT_PROPOSAL_FIELD_SCHEMAS.custom;
}

function getAgentProposalFieldMap(proposal) {
  return proposal?.fields && typeof proposal.fields === "object" && !Array.isArray(proposal.fields)
    ? proposal.fields
    : {};
}

function hasAgentProposalFieldValue(proposal, key) {
  return Boolean(String(getAgentProposalFieldMap(proposal)[key] || "").trim());
}

function isAgentWebMonitorLocationSensitive(proposal) {
  if (proposal?.type !== "web-monitor") {
    return false;
  }
  const fields = getAgentProposalFieldMap(proposal);
  const text = `${proposal.requestText || ""} ${fields.watchQuery || ""}`.toLowerCase();
  return /\b(events?|activities|things to do|kids?|children|famil(y|ies)|nearby|near me|local|restaurants?|venues?|classes?|workshops?|camps?)\b/.test(text);
}

function isAgentProposalFieldRequired(proposal, field) {
  if (!field || field.required === false) {
    return false;
  }
  if (field.requiredWhen === "web-monitor-location-sensitive") {
    return isAgentWebMonitorLocationSensitive(proposal);
  }
  return true;
}

function getAgentNextMissingQuestionIndex(proposal) {
  if (proposal?.type === "scheduled-message") {
    const questions = Array.isArray(proposal.questions) ? proposal.questions : [];
    const answers = Array.isArray(proposal.answers) ? proposal.answers : [];
    return answers.length < questions.length ? answers.length : -1;
  }

  const schema = getAgentProposalFieldSchema(proposal);
  for (let index = 0; index < schema.length; index += 1) {
    const field = schema[index];
    if (isAgentProposalFieldRequired(proposal, field) && !hasAgentProposalFieldValue(proposal, field.key)) {
      return index;
    }
  }
  return -1;
}

function formatAgentProposalFieldValue(key, value) {
  const cleanValue = String(value || "").trim().replace(/\s+/g, " ");
  if (!cleanValue) {
    return "";
  }
  if (key === "deliveryChannel") {
    const channel = normalizeAgentDeliveryChannel(cleanValue);
    return channel ? formatAgentScheduledMessageChannel(channel) : cleanValue;
  }
  return cleanValue.slice(0, 400).trim();
}

function getAgentProposalFieldKeysForAnswers(proposal, answerCount = 0) {
  const schema = getAgentProposalFieldSchema(proposal);
  if (answerCount === 1) {
    const missingIndex = getAgentNextMissingQuestionIndex(proposal);
    if (missingIndex >= 0 && schema[missingIndex]?.key) {
      return [schema[missingIndex].key];
    }
  }

  if (proposal?.type === "web-monitor") {
    if (answerCount >= 5) {
      return schema.map((field) => field.key);
    }
    if (answerCount === 4) {
      return ["watchQuery", "location", "frequency", "deliveryChannel"];
    }
    return ["watchQuery", "frequency", "deliveryChannel"];
  }

  if (proposal?.type === "email-digest") {
    return ["mailbox", "schedule", "deliveryChannel"];
  }

  if (proposal?.type === "whatsapp-replies") {
    return ["whatsappNumber", "approver", "guardrails", "deliveryChannel"];
  }

  if (proposal?.type === "reengagement") {
    return ["inactivityPeriod", "frequency", "deliveryChannel"];
  }

  return schema.map((field) => field.key);
}

function mergeAgentProposalFields(proposal, rawFields = {}) {
  if (!proposal || proposal.type === "scheduled-message") {
    return false;
  }

  const allowedKeys = new Set(getAgentProposalFieldSchema(proposal).map((field) => field.key));
  const currentFields = { ...getAgentProposalFieldMap(proposal) };
  let didChange = false;

  for (const [rawKey, rawValue] of Object.entries(rawFields || {})) {
    const key = getAgentProposalFieldKeyForSchema(rawKey, allowedKeys);
    if (!key) {
      continue;
    }
    const value = formatAgentProposalFieldValue(key, rawValue);
    if (!value || currentFields[key] === value) {
      continue;
    }
    currentFields[key] = value;
    didChange = true;
  }

  proposal.fields = currentFields;
  proposal.answers = getAgentProposalAnswersFromFields(proposal);
  return didChange;
}

function mergeAgentProposalAnswers(proposal, rawAnswers = []) {
  const answers = Array.isArray(rawAnswers)
    ? rawAnswers.map((answer) => String(answer || "").trim()).filter(Boolean)
    : [];
  if (!proposal || proposal.type === "scheduled-message" || !answers.length) {
    return false;
  }

  const keys = getAgentProposalFieldKeysForAnswers(proposal, answers.length);
  const fields = {};
  answers.forEach((answer, index) => {
    const key = keys[index];
    if (key) {
      fields[key] = answer;
    }
  });
  return mergeAgentProposalFields(proposal, fields);
}

function getAgentProposalAnswersFromFields(proposal) {
  if (proposal?.type === "scheduled-message") {
    return Array.isArray(proposal.answers) ? proposal.answers : [];
  }
  const fields = getAgentProposalFieldMap(proposal);
  return getAgentProposalFieldSchema(proposal)
    .map((field) => String(fields[field.key] || "").trim())
    .filter(Boolean);
}

function syncAgentProposalFieldCompatibility(proposal) {
  if (!proposal || proposal.type === "scheduled-message") {
    return proposal;
  }
  proposal.fields = normalizeAgentFieldValues(proposal.fields);
  if (!Object.keys(proposal.fields).length && Array.isArray(proposal.answers) && proposal.answers.length) {
    mergeAgentProposalAnswers(proposal, proposal.answers);
  } else {
    proposal.answers = getAgentProposalAnswersFromFields(proposal);
  }
  return proposal;
}

function extractAgentFrequencyField(text) {
  const value = String(text || "");
  const everyMatch = value.match(/\bevery\s+(\d+)\s*(minutes?|mins?|hours?|days?|weeks?|months?)\b/i);
  if (everyMatch) {
    const amount = everyMatch[1];
    const unit = everyMatch[2].toLowerCase().replace(/^mins?$/, "minutes");
    return `every ${amount} ${unit}`;
  }
  const namedMatch = value.match(/\b(hourly|daily|weekly|monthly|every day|every week|every month)\b/i);
  return namedMatch ? namedMatch[0] : "";
}

function buildAgentMonitorIntervalFromFrequency(value = "") {
  const text = String(value || "").trim().toLowerCase();
  const everyMatch = text.match(/\bevery\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\b/i);
  if (everyMatch) {
    const amount = Math.max(1, Number.parseInt(everyMatch[1], 10) || 1);
    const unit = everyMatch[2].toLowerCase();
    if (unit.startsWith("minute") || unit.startsWith("min")) {
      return { intervalMinutes: normalizeMonitorIntervalMinutes(amount), intervalDays: 1 };
    }
    if (unit.startsWith("hour") || unit.startsWith("hr")) {
      return { intervalMinutes: normalizeMonitorIntervalMinutes(amount * 60), intervalDays: 1 };
    }
    if (unit.startsWith("week")) {
      return { intervalMinutes: 0, intervalDays: normalizeMonitorIntervalDays(amount * 7) };
    }
    if (unit.startsWith("month")) {
      return { intervalMinutes: 0, intervalDays: normalizeMonitorIntervalDays(amount * 30) };
    }
    return { intervalMinutes: 0, intervalDays: normalizeMonitorIntervalDays(amount) };
  }

  if (["hourly", "every hour"].includes(text)) {
    return { intervalMinutes: 60, intervalDays: 1 };
  }
  if (["daily", "every day"].includes(text)) {
    return { intervalMinutes: 0, intervalDays: 1 };
  }
  if (["weekly", "every week"].includes(text)) {
    return { intervalMinutes: 0, intervalDays: 7 };
  }
  if (["monthly", "every month"].includes(text)) {
    return { intervalMinutes: 0, intervalDays: 30 };
  }
  return {
    intervalMinutes: DEFAULT_MONITOR_SETTINGS.intervalMinutes,
    intervalDays: DEFAULT_MONITOR_SETTINGS.intervalDays,
  };
}

function extractAgentWebMonitorTimeWindow(text) {
  const value = String(text || "");
  const monthMatch = value.match(/\b(in|during|for)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*)(?:\s+(\d{4}))?\b/i);
  if (monthMatch) {
    return `${monthMatch[2]}${monthMatch[3] ? ` ${monthMatch[3]}` : ""}`;
  }
  const rangeMatch = value.match(/\b(next|this)\s+(week|month|quarter|year)\b/i);
  return rangeMatch ? rangeMatch[0] : "";
}

function extractAgentWebMonitorWatchQuery(text) {
  const original = String(text || "").trim();
  let value = original
    .replace(/^\s*(please\s+)?(check|search|monitor|watch|look for|find)\s+(the\s+)?(web|internet|online)?\s*/i, "")
    .replace(/\bwhen you (have|find|get) results?[\s\S]*$/i, "")
    .replace(/\bevery\s+\d+\s*(minutes?|mins?|hours?|days?|weeks?|months?)\b/ig, "")
    .replace(/\b(hourly|daily|weekly|monthly|every day|every week|every month)\b/ig, "")
    .replace(/\b(send|email|message|notify)\s+me[\s\S]*$/i, "")
    .replace(/^\s*(for|about|on)\s+/i, "")
    .replace(/\s+(and|to|with)\s*$/i, "")
    .trim();
  value = value.replace(/\s+/g, " ");
  return value || original;
}

function inferAgentProposalFieldsFromText(text, proposalType) {
  const value = String(text || "").trim();
  const fields = {};
  const deliveryChannel = normalizeAgentDeliveryChannel(value);
  const frequency = extractAgentFrequencyField(value);

  if (proposalType === "web-monitor") {
    fields.watchQuery = extractAgentWebMonitorWatchQuery(value);
    if (frequency) {
      fields.frequency = frequency;
    }
    if (deliveryChannel) {
      fields.deliveryChannel = formatAgentScheduledMessageChannel(deliveryChannel);
    }
    const timeWindow = extractAgentWebMonitorTimeWindow(value);
    if (timeWindow) {
      fields.timeWindow = timeWindow;
    }
    return fields;
  }

  if (proposalType === "email-digest") {
    if (/\b(gmail|google mail)\b/i.test(value)) {
      fields.mailbox = "Gmail";
    } else if (/\b(outlook|office 365|microsoft mail)\b/i.test(value)) {
      fields.mailbox = "Outlook";
    }
    if (frequency) {
      fields.schedule = frequency;
    }
    if (deliveryChannel) {
      fields.deliveryChannel = formatAgentScheduledMessageChannel(deliveryChannel);
    }
    return fields;
  }

  if (proposalType === "reengagement") {
    const inactivityMatch = value.match(/\b(\d+)\s*(days?|weeks?|months?)\b/i);
    if (inactivityMatch) {
      fields.inactivityPeriod = `${inactivityMatch[1]} ${inactivityMatch[2].toLowerCase()}`;
    }
    if (frequency) {
      fields.frequency = frequency;
    }
    if (deliveryChannel) {
      fields.deliveryChannel = formatAgentScheduledMessageChannel(deliveryChannel);
    }
    return fields;
  }

  if (proposalType === "whatsapp-replies") {
    if (/\bwhatsapp\b/i.test(value)) {
      fields.whatsappNumber = "connected WhatsApp number";
    }
    const deliveryMatch = value.match(/\b(?:send|deliver|bring|notify|alert|review)\b[\s\S]{0,40}\b(whatsapp|telegram|portal|chat|workspace)\b/i);
    const requestedDeliveryChannel = normalizeAgentDeliveryChannel(deliveryMatch?.[1] || "");
    if (requestedDeliveryChannel) {
      fields.deliveryChannel = formatAgentScheduledMessageChannel(requestedDeliveryChannel);
    }
    return fields;
  }

  if (/\b(calendar|schedule|agenda|appointments?)\b/i.test(value)) {
    return {};
  }

  fields.result = value;
  if (frequency) {
    fields.frequency = frequency;
  }
  if (deliveryChannel) {
    fields.deliveryChannel = formatAgentScheduledMessageChannel(deliveryChannel);
  }
  return fields;
}

function updateAgentProposalSummaryFromFields(proposal) {
  if (!proposal || proposal.type === "scheduled-message") {
    return;
  }
  const fields = getAgentProposalFieldMap(proposal);
  if (proposal.type === "web-monitor" && fields.watchQuery) {
    const location = fields.location ? ` around ${fields.location}` : "";
    const frequency = fields.frequency ? ` ${fields.frequency}` : "";
    const deliveryChannel = getAgentProposalDeliveryChannel(proposal);
    const deliveryTarget = getAgentProposalDeliveryTarget(proposal, deliveryChannel);
    const deliveryText = deliveryChannel
      ? ` and send source-backed alerts ${formatAgentDeliveryTargetSentence(deliveryChannel, deliveryTarget)}`
      : " and send source-backed alerts";
    proposal.summary = `Monitor ${fields.watchQuery}${location}${frequency}${deliveryText}.`;
  } else if (proposal.type === "email-digest" && (fields.mailbox || fields.schedule)) {
    const mailbox = fields.mailbox || "the selected mailbox";
    const schedule = fields.schedule ? ` on ${fields.schedule}` : "";
    proposal.summary = `Summarize important messages from ${mailbox}${schedule}.`;
  } else if (proposal.type === "reengagement" && (fields.inactivityPeriod || fields.frequency)) {
    const inactivity = fields.inactivityPeriod || "the chosen quiet period";
    const frequency = fields.frequency ? ` ${fields.frequency}` : "";
    proposal.summary = `Find conversations quiet for ${inactivity}${frequency} and draft follow-ups.`;
  }
}

function applyAgentFieldProposalRevision(proposal, changes = {}, options = {}) {
  if (!proposal || proposal.type === "scheduled-message") {
    return false;
  }

  const patch = changes && typeof changes === "object" ? changes : {};
  let didChange = false;
  if (patch.fields && typeof patch.fields === "object" && !Array.isArray(patch.fields)) {
    didChange = mergeAgentProposalFields(proposal, patch.fields) || didChange;
  }
  if (Array.isArray(patch.answers)) {
    didChange = mergeAgentProposalAnswers(proposal, patch.answers) || didChange;
  }

  syncAgentProposalFieldCompatibility(proposal);
  updateAgentProposalSummaryFromFields(proposal);
  if (didChange && options.bumpRevision !== false) {
    proposal.revision = Math.max(1, Number(proposal.revision || 1)) + 1;
    proposal.updatedAt = new Date().toISOString();
    proposal.status = "needs-approval";
    proposal.approved = false;
  }
  return didChange;
}

function pushAgentProposalNextStep(proposal, reply = "") {
  const missingIndex = getAgentNextMissingQuestionIndex(proposal);
  if (missingIndex >= 0) {
    pushAgentQuestion(proposal, missingIndex, reply);
    return;
  }
  pushAgentApprovalPrompt(proposal, reply);
}

function getAgentQuestionActions(proposal, questionIndex = 0) {
  const index = Math.max(0, Number(questionIndex || 0));

  if (proposal?.type === "scheduled-message") {
    const questionKey = proposal.questionKeys?.[index] || "";
    if (questionKey === "channel") {
      return [
        createAgentAction("choose", "WhatsApp"),
        createAgentAction("choose", "Email"),
        createAgentAction("choose", "Telegram"),
      ];
    }
    if (questionKey === "time") {
      return [
        createAgentAction("choose", "12:40"),
        createAgentAction("choose", "9:00 AM"),
      ];
    }
    return [];
  }

  const field = getAgentProposalFieldSchema(proposal)[index];
  return Array.isArray(field?.actions)
    ? field.actions.map((action) => (
      typeof action === "string"
        ? createAgentAction("choose", action)
        : createAgentAction("choose", action.label, action.value || action.label, action.tone || "secondary")
    ))
    : [];
}

function getAgentApprovalActions(proposal) {
  return [
    createAgentAction("approve-proposal", "Set it up", proposal?.id || "", "primary"),
    createAgentAction("request-change", "Change something", proposal?.id || ""),
  ];
}

function shouldAttachAgentApprovalActions(proposal, messageText = "") {
  if (!proposal) {
    return false;
  }
  const text = String(messageText || "").toLowerCase();
  const asksToConfirmSetup = (
    /\bconfirm\b/.test(text)
    || /\bgo ahead\b/.test(text)
    || /\bproceed\b/.test(text)
    || /\bset\s+(?:it|this|that|the setup)\s+up\b/.test(text)
  );
  const offersChangePath = (
    /\bchange\b/.test(text)
    || /\badjust\b/.test(text)
    || /\bedit\b/.test(text)
    || /\bmodify\b/.test(text)
  );
  return !(asksToConfirmSetup && offersChangePath);
}

function getAgentApprovalPromptActions(proposal, messageText = "") {
  return shouldAttachAgentApprovalActions(proposal, messageText)
    ? getAgentApprovalActions(proposal)
    : [];
}

function pushAgentQuestion(proposal, questionIndex = 0, questionOverride = "") {
  const index = Math.max(0, Number(questionIndex || 0));
  proposal.questionIndex = index;
  const messageText = String(questionOverride || "").trim();
  if (!messageText) {
    return null;
  }
  const field = proposal?.type === "scheduled-message"
    ? null
    : getAgentProposalFieldSchema(proposal)[index] || null;
  return pushAgentMessage("assistant", messageText, {
    kind: "question",
    proposalId: proposal.id,
    questionIndex: index,
    fieldKey: field?.key || "",
    actions: getAgentQuestionActions(proposal, index),
  });
}

function pushAgentApprovalPrompt(proposal, reply = "") {
  const messageText = String(reply || "").trim();
  if (!messageText) {
    return null;
  }
  return pushAgentMessage("assistant", messageText, {
    kind: "approval",
    proposalId: proposal.id,
    proposalRevision: Math.max(1, Number(proposal.revision || 1)),
    actions: getAgentApprovalPromptActions(proposal, messageText),
  });
}

function persistAgentWorkspace(status = "Agent workspace saved.") {
  persistClientState();
  setStatus(status);
}

function getProposalReadinessLabel(proposal) {
  if (!proposal) {
    return "Ready";
  }

  if (proposal.approved) {
    return "Approved";
  }

  if (proposal.status === "scheduling") {
    return "Scheduling";
  }

  if (proposal.status === "revising") {
    return "Updating plan";
  }

  if (proposal.missingCredential) {
    return "Needs credential";
  }

  const feature = proposal.relatedFeatureId ? getFeatureById(proposal.relatedFeatureId) : null;
  if (feature && isFeatureSetupComplete(feature)) {
    return "Skill ready";
  }

  return "Needs approval";
}

function getProposalSetupLabel(proposal) {
  if (!proposal?.relatedFeatureId) {
    return "Review skills";
  }

  const feature = getFeatureById(proposal.relatedFeatureId);
  if (!feature) {
    return proposal.setupActionLabel || "Review setup";
  }

  if (isFeatureSetupComplete(feature)) {
    return "Open active skill";
  }

  return proposal.setupActionLabel || "Open setup";
}

function normalizeAgentErrorTechnicalInfo(technical = {}) {
  const source = technical && typeof technical === "object" ? technical : {};
  const rawStatus = Number(source.status || 0);
  const status = Number.isInteger(rawStatus) && rawStatus >= 100 && rawStatus <= 599 ? rawStatus : 0;
  const rawUpstreamStatus = Number(source.upstreamStatus || 0);
  const upstreamStatus = Number.isInteger(rawUpstreamStatus)
    && rawUpstreamStatus >= 100
    && rawUpstreamStatus <= 599
    ? rawUpstreamStatus
    : 0;
  const rawCode = String(source.code || "").trim().toLowerCase();
  const code = /^[a-z0-9_-]{1,80}$/.test(rawCode) ? rawCode : "request_failed";
  const rawProviderCode = String(source.providerCode || "").trim().toLowerCase();
  const providerCode = /^[a-z0-9_-]{1,80}$/.test(rawProviderCode) ? rawProviderCode : "";
  const occurredAt = String(source.occurredAt || "").trim();
  return {
    endpoint: "/api/agent/turn",
    status,
    upstreamStatus,
    code,
    providerCode,
    occurredAt: /^\d{4}-\d{2}-\d{2}T/.test(occurredAt) ? occurredAt : "",
  };
}

function getAgentErrorTechnicalInfo(error) {
  const isTimedOut = isAbortError(error);
  return normalizeAgentErrorTechnicalInfo({
    status: error?.status,
    upstreamStatus: error?.payload?.upstreamStatus,
    providerCode: error?.payload?.providerCode,
    code: error?.payload?.error || (isTimedOut ? "client_timeout" : "request_failed"),
    occurredAt: new Date().toISOString(),
  });
}

function getAgentErrorGuidance(technical) {
  const details = normalizeAgentErrorTechnicalInfo(technical);
  if (details.code === "agent_billing_required") {
    if (details.providerCode === "credit_balance_exhausted") {
      return "OpenAI reported that this project’s prepaid credit balance is exhausted. If you just added funds, refresh billing and confirm the server is using the same project before retrying.";
    }
    if (["organization_spend_limit_exceeded", "project_spend_limit_exceeded"].includes(details.providerCode)) {
      return "OpenAI reported a spend limit, not necessarily an empty balance. Check the project and organization limits, then retry.";
    }
    if (details.providerCode === "organization_usage_limit_exceeded") {
      return "OpenAI reported that the organization usage limit was reached. Check the organization limit or request an increase, then retry.";
    }
    if (details.providerCode === "insufficient_quota") {
      return "OpenAI returned a legacy quota or billing rejection. This does not prove a recent payment failed to apply; refresh billing and retry, then check the project and API key if it persists.";
    }
    return "OpenAI reported a billing restriction for this project. Refresh billing and retry; this message does not by itself prove that your funds are missing.";
  }
  if (details.code === "agent_quota_unclear") {
    return "OpenAI returned a quota or usage-limit response, but the exact cause was not identified. This does not prove that your funds are missing. Refresh billing and retry; if it continues, check credits, spend limits, and rate limits.";
  }
  if (details.code === "agent_configuration_error") {
    return "The server is missing a valid OpenAI configuration. Check the API key, model name, and deployment environment variables.";
  }
  if (details.code === "agent_authentication_error") {
    return "OpenAI rejected its credentials. Check the server API key and permissions.";
  }
  if (details.code === "agent_rate_limited") {
    return "OpenAI is temporarily rate-limited. Wait briefly before retrying.";
  }
  if (details.code === "agent_network_error") {
    return "The server could not reach OpenAI. Check service health and network access, then retry.";
  }
  if (details.code === "secret_in_chat") {
    return "Use the secure connection form for credentials. Do not paste tokens or API keys into chat.";
  }
  if (details.status === 401 || details.status === 403) {
    return "The session may have expired or may not have permission to use this endpoint. Sign in again, then retry.";
  }
  if (details.status === 503 || details.code === "agent_unavailable") {
    return "The server could not reach the model service or its configuration is unavailable. Check the server logs and the model/API configuration, then retry.";
  }
  if (details.status === 502 || details.code === "invalid_agent_turn") {
    return "The model returned a response the portal could not validate. Check the server response logs and the agent-turn response schema.";
  }
  if (details.code === "client_timeout") {
    return "The browser waited too long for a response. The server may still be processing the request; check service health and server logs before retrying.";
  }
  if (!details.status || details.code === "request_failed") {
    return "The request may have timed out or the network may have dropped. Check connectivity and service health, then retry.";
  }
  return "Retry once. If it keeps failing, inspect the server logs for this endpoint, status, and error code.";
}

function createAgentErrorHelpBody(technical = {}) {
  const details = normalizeAgentErrorTechnicalInfo(technical);
  const body = document.createElement("div");
  body.className = "agent-error-help";

  const intro = document.createElement("p");
  intro.className = "agent-error-help-intro";
  intro.textContent = "The request failed before any task was created or sent. These safe diagnostics can help locate the problem.";

  const detailList = document.createElement("dl");
  detailList.className = "agent-error-help-details";
  const rows = [
    ["Endpoint", details.endpoint],
    ["HTTP status", details.status ? String(details.status) : "Not returned"],
    ...(details.upstreamStatus ? [["Upstream status", String(details.upstreamStatus)]] : []),
    ...(details.providerCode ? [["Provider code", details.providerCode]] : []),
    ["Error code", details.code],
    ["Time", details.occurredAt || "Not recorded"],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "agent-error-help-detail";
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    row.append(term, description);
    detailList.append(row);
  }

  const guidance = document.createElement("div");
  guidance.className = "agent-error-help-guidance";
  const guidanceTitle = document.createElement("strong");
  guidanceTitle.textContent = "What to check";
  const guidanceText = document.createElement("p");
  guidanceText.textContent = getAgentErrorGuidance(details);
  guidance.append(guidanceTitle, guidanceText);

  const note = document.createElement("p");
  note.className = "agent-error-help-note";
  note.textContent = "No credentials or raw server response are shown here.";

  body.append(intro, detailList, guidance, note);
  return body;
}

function openAgentErrorHelp(technical = {}, returnFocus = null) {
  openAuthAlert(
    "Request details",
    "Use the diagnostics below to understand why this request stopped.",
    {
      eyebrow: "Technical details",
      icon: "i",
      tone: "progress",
      bodyNode: createAgentErrorHelpBody(technical),
      buttonLabel: "Close",
      returnFocus,
    },
  );
}

function createAgentConnectionSetupCard(message) {
  const setup = message?.metadata?.connectionSetup && typeof message.metadata.connectionSetup === "object"
    ? message.metadata.connectionSetup
    : {};
  const card = document.createElement("section");
  card.className = "agent-message-connection-card";
  card.setAttribute("aria-label", "WhatsApp setup details");

  const eyebrow = document.createElement("span");
  eyebrow.className = "agent-message-connection-card-eyebrow";
  eyebrow.textContent = "WhatsApp setup";

  const title = document.createElement("h3");
  title.className = "agent-message-connection-card-title";
  title.textContent = setup.platformConnected ? "Finish the Business connection" : "Connect WhatsApp Business";

  const copy = document.createElement("p");
  copy.className = "agent-message-connection-card-copy";
  copy.textContent = setup.platformConnected
    ? "The WhatsApp app is connected, but incoming-message monitoring uses a separate WhatsApp Business connection."
    : "Add these details in the secure setup form so I can monitor incoming messages.";

  const list = document.createElement("ul");
  list.className = "agent-message-connection-card-list";
  const missingFields = Array.isArray(setup.missingFields) ? setup.missingFields : [];
  for (const field of missingFields) {
    const item = document.createElement("li");
    item.className = "agent-message-connection-card-item";
    item.textContent = String(field?.label || "Required connection detail");
    list.append(item);
  }
  if (!missingFields.length) {
    const item = document.createElement("li");
    item.className = "agent-message-connection-card-item";
    item.textContent = "Verified WhatsApp Business connection";
    list.append(item);
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "agent-message-connection-card-button primary-button";
  button.textContent = "Open WhatsApp setup";
  button.dataset.agentMessageAction = "open-whatsapp-setup";
  button.dataset.agentActionValue = "whatsapp";
  button.dataset.agentActionMessage = message.id;
  const agent = getAgentWorkspace();
  button.disabled = Boolean(agentTurnBusy || areAgentMessageActionsResolved(message, agent.messages));

  const note = document.createElement("p");
  note.className = "agent-message-connection-card-note";
  note.textContent = "Your access token stays in the secure setup form and is never shown in chat.";

  card.append(eyebrow, title, copy, list, button, note);
  return card;
}

function getAgentWhatsAppApprovalForMessage(message) {
  return message?.metadata?.approval && typeof message.metadata.approval === "object"
    ? message.metadata.approval
    : {};
}

function createAgentWhatsAppReplyCard(message) {
  const approval = getAgentWhatsAppApprovalForMessage(message);
  const status = String(approval.status || message.metadata?.approvalStatus || "pending").trim().toLowerCase();
  const senderName = String(approval.sender_name || approval.senderName || approval.sender_wa_id || "WhatsApp contact").trim();
  const incomingText = String(approval.latest_message || approval.incoming_text || approval.message || "").trim();
  const suggestedReply = String(approval.suggested_reply || approval.suggestedReply || "").trim();

  const card = document.createElement("section");
  card.className = `agent-message-whatsapp-card is-${status || "pending"}`;
  card.setAttribute("aria-label", `WhatsApp reply from ${senderName}`);

  const header = document.createElement("div");
  header.className = "agent-message-whatsapp-card-head";
  const eyebrow = document.createElement("span");
  eyebrow.className = "agent-message-whatsapp-card-eyebrow";
  eyebrow.textContent = "WhatsApp reply";
  const title = document.createElement("h3");
  title.className = "agent-message-whatsapp-card-title";
  title.textContent = senderName;
  const statusLabel = document.createElement("span");
  statusLabel.className = "agent-message-whatsapp-card-status";
  statusLabel.setAttribute("role", "status");
  statusLabel.textContent = status === "sent" ? "Sent" : status === "skipped" ? "Skipped" : "Needs review";
  header.append(eyebrow, title, statusLabel);

  const incomingLabel = document.createElement("span");
  incomingLabel.className = "agent-message-whatsapp-card-label";
  incomingLabel.textContent = "They wrote";
  const incoming = document.createElement("p");
  incoming.className = "agent-message-whatsapp-card-incoming";
  incoming.textContent = incomingText || "New WhatsApp message received.";

  const replyLabel = document.createElement("label");
  replyLabel.className = "agent-message-whatsapp-card-label";
  replyLabel.textContent = "Suggested reply";
  const textarea = document.createElement("textarea");
  textarea.className = "agent-message-whatsapp-card-textarea";
  textarea.id = `agent-whatsapp-reply-${message.id}`;
  replyLabel.htmlFor = textarea.id;
  textarea.rows = 3;
  textarea.value = suggestedReply;
  textarea.setAttribute("aria-label", `Suggested reply to ${senderName}`);
  textarea.disabled = status !== "pending";

  card.append(header, incomingLabel, incoming, replyLabel, textarea);

  if (status === "pending") {
    if (message.metadata?.approvalError) {
      const error = document.createElement("p");
      error.className = "agent-message-whatsapp-card-error";
      error.setAttribute("role", "alert");
      error.textContent = String(message.metadata.approvalError);
      card.append(error);
    }
    const note = document.createElement("p");
    note.className = "agent-message-whatsapp-card-note";
    note.textContent = "Review or edit it here. Nothing is sent until you choose Send reply.";
    const actions = document.createElement("div");
    actions.className = "agent-message-whatsapp-card-actions";

    const sendButton = document.createElement("button");
    sendButton.type = "button";
    sendButton.className = "primary-button small";
    sendButton.textContent = "Send reply";
    sendButton.dataset.agentWhatsAppAction = "send";
    sendButton.dataset.agentWhatsAppApproval = String(approval.approval_id || approval.approvalId || "");
    sendButton.dataset.agentWhatsAppMessage = message.id;

    const skipButton = document.createElement("button");
    skipButton.type = "button";
    skipButton.className = "ghost-button small";
    skipButton.textContent = "Skip";
    skipButton.dataset.agentWhatsAppAction = "skip";
    skipButton.dataset.agentWhatsAppApproval = String(approval.approval_id || approval.approvalId || "");
    skipButton.dataset.agentWhatsAppMessage = message.id;
    actions.append(sendButton, skipButton);
    card.append(note, actions);
  } else if (message.metadata?.approvalError) {
    const error = document.createElement("p");
    error.className = "agent-message-whatsapp-card-error";
    error.setAttribute("role", "alert");
    error.textContent = String(message.metadata.approvalError);
    card.append(error);
  } else {
    const outcome = document.createElement("p");
    outcome.className = "agent-message-whatsapp-card-note";
    outcome.textContent = status === "sent"
      ? "The approved reply was sent to this WhatsApp contact."
      : "This suggestion was skipped and will not be sent.";
    card.append(outcome);
  }

  return card;
}

async function handleAgentWhatsAppApprovalAction(button) {
  const approvalId = String(button?.dataset.agentWhatsAppApproval || "").trim();
  const messageId = String(button?.dataset.agentWhatsAppMessage || "").trim();
  const action = String(button?.dataset.agentWhatsAppAction || "").trim().toLowerCase();
  if (!approvalId || !messageId || !["send", "skip"].includes(action)) {
    return;
  }

  const agent = getAgentWorkspace();
  const message = agent.messages.find((candidate) => candidate.id === messageId);
  if (!message) {
    return;
  }
  const approval = getAgentWhatsAppApprovalForMessage(message);
  if (String(approval.status || "pending").toLowerCase() !== "pending") {
    return;
  }

  const card = button.closest(".agent-message-whatsapp-card");
  const textarea = card?.querySelector(".agent-message-whatsapp-card-textarea");
  const buttons = card ? Array.from(card.querySelectorAll("button")) : [button];
  buttons.forEach((candidate) => {
    candidate.disabled = true;
  });
  if (card) {
    card.classList.add("is-busy");
  }

  try {
    const response = await apiRequest(`/api/approvals/${encodeURIComponent(approvalId)}/${action}`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: action === "send" ? { reply_text: String(textarea?.value || "").trim() } : {},
    });
    message.metadata.approval = response.approval || {
      ...approval,
      status: action === "send" ? "sent" : "skipped",
    };
    message.metadata.approvalStatus = action === "send" ? "sent" : "skipped";
    message.metadata.approvalError = "";
    persistAgentWorkspace(action === "send" ? "Reply sent." : "Reply skipped.");
    renderAgentMessages();
  } catch (error) {
    message.metadata.approvalError = formatApiErrorMessage(
      error,
      action === "send" ? "I couldn’t send that reply. Check the WhatsApp connection and try again." : "I couldn’t skip that reply. Try again.",
    );
    persistClientState();
    renderAgentMessages();
  }
}

function renderAgentMessage(message) {
  const row = document.createElement("article");
  const kind = String(message.metadata?.kind || (message.role === "user" ? "user" : "text"));
  row.className = `agent-message is-${message.role} is-${kind}`;

  const bubble = document.createElement("div");
  bubble.className = "agent-message-bubble";
  if (kind === "thinking") {
    const progressText = agentTurnProgressText || "Thinking";
    bubble.setAttribute("aria-label", `Assistyca is ${progressText.toLowerCase()}`);
    bubble.append(document.createTextNode(progressText));
    const dots = document.createElement("span");
    dots.className = "agent-thinking-dots";
    dots.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      dots.append(document.createElement("span"));
    }
    bubble.append(dots);
  } else {
    bubble.textContent = message.text;
  }

  const messageLine = document.createElement("div");
  messageLine.className = "agent-message-line";
  messageLine.append(bubble);
  if (kind === "error") {
    const helpButton = document.createElement("button");
    helpButton.type = "button";
    helpButton.className = "agent-message-help-button";
    const helpIcon = document.createElement("span");
    helpIcon.className = "agent-message-help-icon";
    helpIcon.textContent = "i";
    helpIcon.setAttribute("aria-hidden", "true");
    helpButton.append(helpIcon);
    helpButton.setAttribute("aria-label", "Show technical details for this failure");
    helpButton.title = "Show technical details";
    helpButton.addEventListener("click", () => openAgentErrorHelp(message.metadata?.technical, helpButton));
    messageLine.append(helpButton);
  }
  row.append(messageLine);

  if (kind === "connection-setup") {
    row.append(createAgentConnectionSetupCard(message));
  }
  if (kind === "whatsapp-reply-suggestion") {
    row.append(createAgentWhatsAppReplyCard(message));
  }

  const rawActions = kind === "connection-setup"
    ? []
    : (Array.isArray(message.metadata?.actions) ? message.metadata.actions : []);
  if (rawActions.length && message.role !== "user") {
    const agent = getAgentWorkspace();
    const proposal = message.metadata?.proposalId
      ? agent.proposals.find((candidate) => candidate.id === message.metadata.proposalId)
      : null;
    const actions = kind === "approval" && !shouldAttachAgentApprovalActions(proposal, message.text)
      ? []
      : rawActions;
    if (!actions.length) {
      return row;
    }
    const messageRevision = Math.max(0, Number(message.metadata?.proposalRevision || 0));
    const isStaleApproval = kind === "approval"
      && proposal
      && messageRevision > 0
      && messageRevision !== Math.max(1, Number(proposal.revision || 1));
    const actionsResolved = areAgentMessageActionsResolved(message, agent.messages);
    const actionRow = document.createElement("div");
    actionRow.className = "agent-message-actions";
    for (const action of actions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = action.tone === "primary" ? "primary-button small" : "ghost-button small";
      button.dataset.agentMessageAction = action.id;
      button.dataset.agentActionValue = action.value || action.label;
      button.dataset.agentActionProposal = message.metadata?.proposalId || "";
      button.dataset.agentActionRevision = String(messageRevision || "");
      button.dataset.agentActionMessage = message.id;
      button.disabled = Boolean(isStaleApproval || actionsResolved || agentTurnBusy);
      button.textContent = action.label;
      actionRow.append(button);
    }
    row.append(actionRow);
  }

  return row;
}

function getAgentMessageRenderSignature(messages) {
  return JSON.stringify(messages.map((message) => [
    message.id,
    message.role,
    message.text,
    message.metadata?.kind || "",
    message.metadata?.kind === "thinking" ? agentTurnProgressText : "",
    message.metadata?.kind === "whatsapp-reply-suggestion" ? String(message.metadata?.approval?.status || message.metadata?.approvalStatus || "") : "",
    message.metadata?.kind === "whatsapp-reply-suggestion" ? String(message.metadata?.approvalError || "") : "",
    message.metadata?.kind === "whatsapp-reply-suggestion" ? String(message.metadata?.approval?.suggested_reply || "") : "",
    message.metadata?.proposalId || "",
    message.metadata?.proposalRevision || "",
    message.metadata?.actionsResolvedAt || "",
    message.metadata?.actionsResolvedBy || "",
    message.metadata?.connectionSetup?.platformConnected ? "connected" : "",
    message.metadata?.connectionSetup?.connectionStatus || "",
    Array.isArray(message.metadata?.connectionSetup?.missingFields)
      ? message.metadata.connectionSetup.missingFields.map((field) => field?.key || field?.label || "")
      : [],
    Array.isArray(message.metadata?.actions)
      ? message.metadata.actions.map((action) => [
        action.id || "",
        action.label || "",
        action.value || "",
        action.tone || "",
      ])
      : [],
  ]));
}

function isAgentMessageListNearBottom(container) {
  return container.scrollHeight - container.scrollTop - container.clientHeight < 96;
}

function scrollAgentMessagesToBottom() {
  if (!elements.agentMessageList) {
    return;
  }

  elements.agentMessageList.scrollTop = elements.agentMessageList.scrollHeight;
}

function shouldPinAgentMessagesToBottom(container, messages) {
  if (!container.dataset.agentMessageRenderSignature) {
    return true;
  }
  if (isAgentMessageListNearBottom(container)) {
    return true;
  }

  const nextLastMessage = messages.at(-1);
  return Boolean(
    nextLastMessage
    && nextLastMessage.id !== container.dataset.agentMessageLastId
    && nextLastMessage.role === "user"
  );
}

function renderAgentMessages() {
  if (!elements.agentMessageList) {
    return;
  }

  const agent = getAgentWorkspace();
  elements.agentEmptyState?.classList.toggle("is-hidden", agent.messages.length > 0);
  const visibleMessages = agentTurnBusy
    ? [
      ...agent.messages,
      {
        id: "agent-thinking",
        role: "assistant",
        text: "Thinking",
        metadata: { kind: "thinking", actions: [] },
      },
    ]
    : agent.messages;
  const signature = getAgentMessageRenderSignature(visibleMessages);
  if (elements.agentMessageList.dataset.agentMessageRenderSignature === signature) {
    return;
  }

  const shouldPinToBottom = shouldPinAgentMessagesToBottom(elements.agentMessageList, visibleMessages);
  const lastMessage = visibleMessages.at(-1);
  elements.agentMessageList.dataset.agentMessageRenderSignature = signature;
  elements.agentMessageList.dataset.agentMessageLastId = lastMessage?.id || "";
  elements.agentMessageList.replaceChildren(...visibleMessages.map(renderAgentMessage));
  if (shouldPinToBottom) {
    window.requestAnimationFrame(scrollAgentMessagesToBottom);
  }
}

function createAgentList(items, className, itemClassName) {
  const list = document.createElement("div");
  list.className = className;

  for (const item of items) {
    const row = document.createElement("div");
    row.className = itemClassName;

    const title = document.createElement("strong");
    title.textContent = item.label || item.name || "Item";

    const detail = document.createElement("p");
    detail.textContent = item.detail || item.purpose || "";

    row.append(title, detail);
    list.append(row);
  }

  return list;
}

function renderAgentProposalCard() {
  if (!elements.agentProposalCard) {
    return;
  }

  const proposal = getActiveAgentProposal();
  if (!proposal) {
    const empty = document.createElement("div");
    empty.className = "agent-empty-panel";
    const eyebrow = document.createElement("p");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "Plan";
    const title = document.createElement("h2");
    title.textContent = "No plan yet";
    const copy = document.createElement("p");
    copy.textContent = "Send a request and the agent will turn it into an approval-ready plan.";
    empty.append(eyebrow, title, copy);
    elements.agentProposalCard.replaceChildren(empty);
    return;
  }

  const head = document.createElement("div");
  head.className = "agent-proposal-head";

  const copyBlock = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "Proposed plan";
  const title = document.createElement("h2");
  title.textContent = proposal.title;
  const summary = document.createElement("p");
  summary.textContent = proposal.summary;
  copyBlock.append(eyebrow, title, summary);

  const status = document.createElement("span");
  status.className = "feature-status";
  status.textContent = getProposalReadinessLabel(proposal);
  head.append(copyBlock, status);

  const skillsTitle = document.createElement("h3");
  skillsTitle.textContent = "Skills";
  const skills = createAgentList(proposal.skills, "agent-mini-list", "agent-mini-row");

  const helpersTitle = document.createElement("h3");
  helpersTitle.textContent = "Helper agents";
  const helpers = createAgentList(
    proposal.helpers.map((helper) => ({
      label: helper.name,
      detail: helper.purpose,
    })),
    "agent-mini-list",
    "agent-mini-row",
  );

  const questions = document.createElement("div");
  questions.className = "agent-question-block";
  const questionsTitle = document.createElement("h3");
  questionsTitle.textContent = "Questions before it runs";
  const questionList = document.createElement("ul");
  if (proposal.questions.length) {
    for (const question of proposal.questions) {
      const item = document.createElement("li");
      item.textContent = question;
      questionList.append(item);
    }
  } else {
    const item = document.createElement("li");
    item.textContent = "No missing details; ready for approval.";
    questionList.append(item);
  }
  questions.append(questionsTitle, questionList);

  const actions = document.createElement("div");
  actions.className = "agent-proposal-actions";

  const approveButton = document.createElement("button");
  approveButton.className = "primary-button small";
  approveButton.type = "button";
  approveButton.dataset.agentApproveProposal = proposal.id;
  approveButton.textContent = proposal.approved ? "Approved" : proposal.primaryActionLabel;
  approveButton.disabled = proposal.approved;

  const setupButton = document.createElement("button");
  setupButton.className = "ghost-button small";
  setupButton.type = "button";
  setupButton.dataset.agentOpenSetup = proposal.id;
  setupButton.textContent = getProposalSetupLabel(proposal);

  const changeButton = document.createElement("button");
  changeButton.className = "ghost-button small";
  changeButton.type = "button";
  changeButton.dataset.agentRequestChanges = proposal.id;
  changeButton.textContent = "Adjust plan";

  actions.append(approveButton, setupButton, changeButton);

  if (proposal.missingCredential) {
    const credential = document.createElement("div");
    credential.className = "agent-credential-callout";
    const credentialCopy = document.createElement("p");
    credentialCopy.textContent = `${proposal.missingCredential} may be required. If you do not know how to get it, I can help.`;
    const helpButton = document.createElement("button");
    helpButton.className = "ghost-button small";
    helpButton.type = "button";
    helpButton.dataset.agentCredentialHelp = proposal.id;
    helpButton.textContent = "Help me get it";
    credential.append(credentialCopy, helpButton);
    elements.agentProposalCard.replaceChildren(head, skillsTitle, skills, helpersTitle, helpers, questions, credential, actions);
    return;
  }

  elements.agentProposalCard.replaceChildren(head, skillsTitle, skills, helpersTitle, helpers, questions, actions);
}

function renderAgentHelpers() {
  if (!elements.agentHelperList || !elements.agentHelperCount) {
    return;
  }

  const agent = getAgentWorkspace();
  elements.agentHelperCount.textContent = String(agent.helpers.length);

  if (!agent.helpers.length) {
    const empty = document.createElement("p");
    empty.className = "agent-helper-empty";
    empty.textContent = "Approved helper agents will appear here.";
    elements.agentHelperList.replaceChildren(empty);
    return;
  }

  const rows = agent.helpers.map((helper) => {
    const row = document.createElement("article");
    row.className = "agent-helper-row";

    const copy = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = helper.name;
    const purpose = document.createElement("p");
    purpose.textContent = helper.purpose;
    copy.append(title, purpose);

    const status = document.createElement("span");
    status.className = "feature-status";
    status.textContent = helper.status;

    row.append(copy, status);
    return row;
  });

  elements.agentHelperList.replaceChildren(...rows);
}

function normalizeScheduledAction(action = {}) {
  const payload = action?.payload && typeof action.payload === "object" ? action.payload : {};
  return {
    id: Math.max(0, Number(action.id || 0)),
    actionType: String(action.actionType || "").trim(),
    channel: String(action.channel || "").trim().toLowerCase(),
    recipientRef: String(action.recipientRef || "").trim(),
    runAt: String(action.runAt || "").trim(),
    timezone: String(action.timezone || "").trim(),
    status: String(action.status || "pending").trim().toLowerCase() || "pending",
    attemptCount: Math.max(0, Number(action.attemptCount || 0)),
    providerMessageId: String(action.providerMessageId || "").trim(),
    payload: { ...payload },
    lastError: String(action.lastError || "").trim(),
    claimedAt: String(action.claimedAt || "").trim(),
    completedAt: String(action.completedAt || "").trim(),
    createdAt: String(action.createdAt || "").trim(),
    updatedAt: String(action.updatedAt || "").trim(),
  };
}

function normalizeAgentActionTypeLabel(value) {
  return capitalizeWords(String(value || "")
    .replace(/^agent[_-]+/, "")
    .replace(/[_-]+/g, " ")
    .trim());
}

function isAgentProposalLocalAction(action) {
  return Boolean(
    action?.payload?.source === "agent_proposal"
    || String(action?.id || "").startsWith("proposal:")
  );
}

function isAgentFeatureLiveAction(action) {
  return Boolean(
    action?.payload?.source === "feature"
    || String(action?.id || "").startsWith("feature:")
  );
}

function isAgentLocalAction(action) {
  return Boolean(
    isAgentProposalLocalAction(action)
    || isAgentFeatureLiveAction(action)
    || (action?.local === true && String(action?.actionType || "").startsWith("agent_"))
  );
}

function getAgentProposalFieldValue(proposal, key) {
  const fields = proposal?.fields && typeof proposal.fields === "object" ? proposal.fields : {};
  return String(fields[key] || "").trim();
}

function getAgentProposalExecutionSettings(proposal) {
  return proposal?.executionPlan?.settings && typeof proposal.executionPlan.settings === "object"
    ? proposal.executionPlan.settings
    : {};
}

function agentWebMonitorTextSuggestsManualOnly(value) {
  return /\b(?:manual(?:ly)?|manual[ _-]?only|on[ -]?demand|when i (?:ask|choose|want)|when (?:the )?user clicks?|run only when|run now)\b/i
    .test(String(value || ""));
}

function getAgentProposalWebMonitorManualOnly(proposal, backendFeature = null) {
  if (proposal?.type !== "web-monitor") {
    return false;
  }

  const requestedFrequency = extractAgentFrequencyField(proposal?.requestText || "");
  if (backendFeature && isMonitorFeature(backendFeature)) {
    if (normalizeMonitorManualOnly(getSavedFeatureSettings(backendFeature).manualOnly, false)) {
      return true;
    }
    if (!requestedFrequency) {
      return true;
    }
  }

  const settings = getAgentProposalExecutionSettings(proposal);
  if (Object.prototype.hasOwnProperty.call(settings, "manualOnly")) {
    if (normalizeMonitorManualOnly(settings.manualOnly, false)) {
      return true;
    }
    if (!requestedFrequency) {
      return true;
    }
  }
  if (Object.prototype.hasOwnProperty.call(settings, "manual_only")) {
    if (normalizeMonitorManualOnly(settings.manual_only, false)) {
      return true;
    }
    if (!requestedFrequency) {
      return true;
    }
  }

  const runMode = String(
    settings.runMode
    || settings.run_mode
    || settings.mode
    || proposal?.executionPlan?.runMode
    || proposal?.executionPlan?.run_mode
    || "",
  ).trim().toLowerCase();
  if (["manual", "manual_only", "on_demand", "on-demand"].includes(runMode)) {
    return true;
  }

  return [
    settings.frequency,
    proposal?.executionPlan?.frequency,
    getAgentProposalFieldValue(proposal, "frequency"),
    proposal?.summary,
    proposal?.requestText,
  ].some(agentWebMonitorTextSuggestsManualOnly) || !requestedFrequency;
}

function getAgentProposalLocalActionTitle(proposal) {
  if (proposal?.type === "web-monitor") {
    return "Web monitor";
  }
  if (proposal?.type === "email-digest") {
    return "Email digest";
  }
  if (proposal?.type === "whatsapp-replies") {
    return "WhatsApp helper";
  }
  if (proposal?.type === "reengagement") {
    return "Customer follow-up";
  }
  return proposal?.title || proposal?.helpers?.[0]?.name || "Agent helper";
}

function getAgentProposalLocalActionPreview(proposal) {
  if (proposal?.type === "web-monitor") {
    const pieces = [
      getAgentProposalFieldValue(proposal, "watchQuery"),
      getAgentProposalFieldValue(proposal, "location"),
      getAgentProposalFieldValue(proposal, "timeWindow"),
    ].filter(Boolean);
    return pieces.length ? pieces.join(" · ") : proposal.summary;
  }
  return proposal?.summary || proposal?.helpers?.[0]?.purpose || "";
}

function getSignedInDeliveryEmail() {
  return normalizeEmail(authSession?.email || activeEmail || "");
}

function getAgentProposalDeliveryChannel(proposal) {
  if (proposal?.type === "whatsapp-replies") {
    return normalizeAgentDeliveryChannel(getAgentProposalFieldValue(proposal, "deliveryChannel")) || "portal";
  }
  const settings = getAgentProposalExecutionSettings(proposal);
  return normalizeAgentDeliveryChannel(settings.deliveryChannel)
    || normalizeAgentDeliveryChannel(getAgentProposalFieldValue(proposal, "deliveryChannel"))
    || normalizeAgentDeliveryChannel(proposal?.requestText || "");
}

function getAgentProposalDeliveryTarget(proposal, deliveryChannel = "") {
  const explicitTarget = String(
    proposal?.executionPlan?.deliveryTarget
    || proposal?.executionPlan?.settings?.deliveryTarget
    || proposal?.executionPlan?.action?.recipientRef
    || "",
  ).trim();
  const normalizedChannel = normalizeAgentDeliveryChannel(deliveryChannel);
  if (normalizedChannel === "email") {
    return validateEmail(explicitTarget) ? normalizeEmail(explicitTarget) : getSignedInDeliveryEmail();
  }
  return explicitTarget && explicitTarget !== "owner" ? explicitTarget : "";
}

function formatAgentDeliveryTargetDetail(deliveryChannel = "", deliveryTarget = "") {
  const channelLabel = formatAgentScheduledMessageChannel(deliveryChannel);
  const targetLabel = String(deliveryTarget || "").trim();
  return targetLabel ? `${channelLabel} → ${targetLabel}` : channelLabel;
}

function formatAgentDeliveryTargetSentence(deliveryChannel = "", deliveryTarget = "") {
  const channelLabel = formatAgentScheduledMessageChannel(deliveryChannel);
  const targetLabel = String(deliveryTarget || "").trim();
  return targetLabel ? `by ${channelLabel} to ${targetLabel}` : `by ${channelLabel}`;
}

function createAgentProposalLocalAction(proposal) {
  if (!proposal || !proposal.approved || proposal.type === "scheduled-message") {
    return null;
  }

  const deliveryChannel = getAgentProposalDeliveryChannel(proposal);
  const deliveryTarget = getAgentProposalDeliveryTarget(proposal, deliveryChannel);
  const deliveryLabel = formatAgentDeliveryTargetDetail(deliveryChannel, deliveryTarget);
  const approvedAt = String(proposal.approvedAt || proposal.updatedAt || proposal.createdAt || new Date().toISOString());
  const backendFeatureId = String(proposal.executionPlan?.backendFeatureId || proposal.relatedFeatureId || "").trim();
  const backendFeature = backendFeatureId ? getFeatureById(backendFeatureId) : null;
  const backendFeatureActive = backendFeatureId ? isFeatureActivated(backendFeature) : false;
  const manualOnly = getAgentProposalWebMonitorManualOnly(proposal, backendFeature);
  const status = backendFeatureId
    ? (backendFeatureActive ? (manualOnly ? "manual_only" : "running") : "cancelled")
    : (proposal.missingCredential ? "pending" : (manualOnly ? "manual_only" : "running"));
  return {
    id: `proposal:${proposal.id}`,
    actionType: `agent_${String(proposal.type || "helper").replace(/[^a-zA-Z0-9]+/g, "_")}`,
    channel: deliveryChannel || "agent",
    recipientRef: deliveryTarget || deliveryChannel,
    runAt: approvedAt,
    timezone: normalizeMonitorScheduleTimezone(clientState?.settings?.timezone || defaultTimeZone(), "UTC") || "UTC",
    status,
    attemptCount: 0,
    providerMessageId: "",
    payload: {
      source: "agent_proposal",
      proposalId: proposal.id,
      proposalType: proposal.type,
      backendFeatureId,
      backendFeatureActive,
      title: getAgentProposalLocalActionTitle(proposal),
      preview: getAgentProposalLocalActionPreview(proposal),
      summary: proposal.summary,
      watchQuery: getAgentProposalFieldValue(proposal, "watchQuery"),
      location: getAgentProposalFieldValue(proposal, "location"),
      timeWindow: getAgentProposalFieldValue(proposal, "timeWindow"),
      frequency: manualOnly
        ? "manual only"
        : (proposal.executionPlan?.frequency || getAgentProposalFieldValue(proposal, "frequency")),
      manualOnly,
      deliveryChannel,
      deliveryTarget,
      deliveryLabel,
      initialRunStatus: String(proposal.executionPlan?.initialRunStatus || "").trim(),
      initialRunMessage: String(proposal.executionPlan?.initialRunMessage || "").trim(),
      initialRunError: String(proposal.executionPlan?.initialRunError || "").trim(),
    },
    local: true,
    lastError: backendFeatureId && !backendFeatureActive ? "The connected tool is turned off." : "",
    claimedAt: "",
    completedAt: backendFeatureId && !backendFeatureActive ? String(backendFeature?.deactivatedAt || proposal.updatedAt || approvedAt) : "",
    createdAt: approvedAt,
    updatedAt: String(proposal.updatedAt || approvedAt),
  };
}

function getAgentProposalLocalActions() {
  return getAgentWorkspace().proposals
    .map(createAgentProposalLocalAction)
    .filter(Boolean);
}

function getMonitorFeatureLiveActionPreview(feature, settings = getSavedFeatureSettings(feature)) {
  const watchItems = normalizeMonitorWatchItems(settings.watchItems);
  if (watchItems.length) {
    return watchItems.join(" · ");
  }
  return String(feature?.description || "Saved web monitor").trim();
}

function getMonitorFeatureDeliveryTarget(settings = {}, deliveryChannel = "") {
  const explicitTarget = String(settings.deliveryTarget || settings.recipientRef || "").trim();
  if (explicitTarget && explicitTarget !== "owner") {
    return explicitTarget;
  }
  if (deliveryChannel === "email") {
    return getSignedInDeliveryEmail();
  }
  if (deliveryChannel === "telegram") {
    return String(settings.telegramChatId || "").trim();
  }
  return "";
}

function createMonitorFeatureLiveAction(feature) {
  if (!feature || !isMonitorFeature(feature) || !isFeatureActivated(feature)) {
    return null;
  }

  const settings = getSavedFeatureSettings(feature);
  const manualOnly = normalizeMonitorManualOnly(settings.manualOnly);
  const deliveryChannel = normalizeAgentDeliveryChannel(settings.deliveryChannel) || "email";
  const deliveryTarget = getMonitorFeatureDeliveryTarget(settings, deliveryChannel);
  const nextRunAt = manualOnly
    ? ""
    : (
      resolveMonitorNextRunAt(feature)
      || String(feature.nextRunAt || feature.setupStatus?.nextRunAt || "").trim()
      || String(feature.lastRunAt || feature.setupStatus?.lastRunAt || "").trim()
      || String(feature.activatedAt || feature.settingsSavedAt || feature.setupStatus?.settingsSavedAt || "").trim()
      || new Date().toISOString()
    );
  const createdAt = String(feature.activatedAt || feature.settingsSavedAt || feature.setupStatus?.settingsSavedAt || nextRunAt).trim();
  const updatedAt = String(feature.lastRunAt || feature.setupStatus?.lastRunAt || feature.settingsSavedAt || createdAt).trim();
  const watchItems = normalizeMonitorWatchItems(settings.watchItems);
  const deliveryLabel = formatAgentDeliveryTargetDetail(deliveryChannel, deliveryTarget);

  return {
    id: `feature:${feature.id}`,
    actionType: "agent_web_monitor",
    channel: deliveryChannel,
    recipientRef: deliveryTarget || deliveryChannel,
    runAt: nextRunAt,
    timezone: getMonitorScheduleTimezone(feature),
    status: manualOnly ? "manual_only" : "running",
    attemptCount: 0,
    providerMessageId: "",
    payload: {
      source: "feature",
      backendFeatureId: feature.id,
      backendFeatureActive: true,
      title: "Web monitor",
      preview: getMonitorFeatureLiveActionPreview(feature, settings),
      summary: String(feature.description || "").trim(),
      watchItems,
      frequency: formatAgentWebMonitorFrequency(settings),
      manualOnly,
      deliveryChannel,
      deliveryTarget,
      deliveryLabel,
      lastRunAt: String(feature.lastRunAt || feature.setupStatus?.lastRunAt || "").trim(),
      lastRunStatus: String(feature.lastRunStatus || feature.setupStatus?.lastRunStatus || "").trim(),
      nextRunAt,
    },
    local: true,
    lastError: "",
    claimedAt: "",
    completedAt: "",
    createdAt,
    updatedAt,
  };
}

function getAgentFeatureLiveActions() {
  return clientState.features
    .map(createMonitorFeatureLiveAction)
    .filter(Boolean);
}

function getRenderableAgentActions() {
  const backendActions = Array.isArray(state.scheduledActions) ? state.scheduledActions : [];
  const proposalActions = getAgentProposalLocalActions();
  const proposalFeatureIds = new Set(
    proposalActions
      .map((action) => String(action.payload?.backendFeatureId || "").trim())
      .filter(Boolean),
  );
  const featureActions = getAgentFeatureLiveActions()
    .filter((action) => !proposalFeatureIds.has(String(action.payload?.backendFeatureId || "").trim()));
  return [
    ...featureActions,
    ...proposalActions,
    ...backendActions,
  ];
}

function isActiveAgentActionStatus(status) {
  return ["pending", "running", "manual_only"].includes(String(status || "").trim().toLowerCase());
}

function canCancelAgentAction(action) {
  return isActiveAgentActionStatus(action?.status);
}

function createAgentActionDetailActions(action) {
  if (!canCancelAgentAction(action)) {
    return null;
  }

  const actions = document.createElement("div");
  actions.className = "agent-action-detail-actions";
  const featureId = String(action?.payload?.backendFeatureId || "").trim();
  if (isAgentFeatureLiveAction(action) && action.actionType === "agent_web_monitor" && featureId) {
    const runButton = document.createElement("button");
    runButton.type = "button";
    runButton.className = "primary-button small agent-action-run-button";
    runButton.dataset.agentRunMonitorAction = featureId;
    const isBusy = monitorActionRunBusy.has(featureId);
    runButton.textContent = isBusy ? "Running…" : "Run now";
    runButton.disabled = isBusy;
    runButton.setAttribute("aria-busy", String(isBusy));
    runButton.setAttribute("aria-label", `${isBusy ? "Running" : "Run"} ${getScheduledActionTitle(action)} now`);
    actions.append(runButton);
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost-button small agent-action-danger-button";

  if (isAgentLocalAction(action)) {
    button.dataset.agentRemoveLocalAction = String(action.id || "");
    const hasBackendFeature = Boolean(String(action.payload?.backendFeatureId || "").trim());
    button.textContent = hasBackendFeature ? "Turn off action" : "Remove action";
    button.setAttribute("aria-label", `${hasBackendFeature ? "Turn off" : "Remove"} ${getScheduledActionTitle(action)}`);
  } else {
    button.dataset.agentCancelScheduledAction = String(action.id || "");
    button.textContent = "Cancel action";
    button.setAttribute("aria-label", `Cancel ${getScheduledActionTitle(action)}`);
  }

  actions.append(button);
  return actions;
}

function getScheduledActionStatusLabel(status, action = null) {
  const labels = {
    pending: "Scheduled",
    running: "Sending",
    sent: "Sent",
    delivered: "Delivered",
    read: "Read",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  const normalized = String(status || "pending").trim().toLowerCase();
  if (isAgentLocalAction(action)) {
    if (normalized === "manual_only") {
      return "Manual";
    }
    if (normalized === "running") {
      return "Working";
    }
    if (normalized === "pending") {
      return "Ready";
    }
  }
  return labels[normalized] || capitalizeWords(normalized.replace(/[_-]+/g, " ")) || "Unknown";
}

function getScheduledActionStatusClass(status) {
  const normalized = String(status || "pending").trim().toLowerCase();
  return ["pending", "running", "manual_only", "sent", "delivered", "read", "failed", "cancelled"].includes(normalized)
    ? normalized
    : "unknown";
}

function getScheduledActionTitle(action) {
  const payloadTitle = String(action?.payload?.title || "").trim();
  if (payloadTitle) {
    return payloadTitle;
  }
  if (isAgentLocalAction(action)) {
    return normalizeAgentActionTypeLabel(action?.actionType) || "Agent helper";
  }
  const channel = formatAgentScheduledMessageChannel(action?.channel);
  if (String(action?.actionType || "").trim() === "send_message") {
    return `${channel} message`;
  }
  return "Scheduled action";
}

function formatScheduledActionDate(value, timeZone = "") {
  const text = String(value || "").trim();
  if (!text) {
    return "Not available";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  const normalizedTimeZone = normalizeMonitorScheduleTimezone(timeZone, getWorkspaceTimeZone()) || undefined;
  const options = {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: normalizedTimeZone,
  };
  if (parsed.getFullYear() !== new Date().getFullYear()) {
    options.year = "numeric";
  }
  return new Intl.DateTimeFormat(undefined, options).format(parsed);
}

function createScheduledActionStatus(action) {
  const status = document.createElement("span");
  const statusClass = getScheduledActionStatusClass(action.status);
  status.className = `agent-action-status is-${statusClass}`;
  status.textContent = getScheduledActionStatusLabel(action.status, action);
  return status;
}

function getScheduledActionItemTimeValue(action) {
  return isActiveAgentActionStatus(action.status)
    ? action.runAt
    : (action.completedAt || action.updatedAt);
}

function getScheduledActionSortTime(action, fallback = Number.MAX_SAFE_INTEGER) {
  const value = getScheduledActionItemTimeValue(action) || action.updatedAt || action.createdAt;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? fallback : parsed;
}

function getScheduledActionItemSignature(action) {
  return JSON.stringify([
    action.id,
    getScheduledActionTitle(action),
    getScheduledActionStatusClass(action.status),
    getScheduledActionStatusLabel(action.status, action),
    action.payload?.manualOnly ? "Run when you choose" : formatScheduledActionDate(getScheduledActionItemTimeValue(action), action.timezone),
  ]);
}

function getScheduledActionListSignature(actions, emptyMessage) {
  if (!actions.length) {
    return JSON.stringify(["empty", emptyMessage]);
  }
  return JSON.stringify(actions.map(getScheduledActionItemSignature));
}

function createScheduledActionItem(action) {
  const item = document.createElement("article");
  const statusClass = getScheduledActionStatusClass(action.status);
  item.className = `agent-action-item is-${statusClass}`;
  item.dataset.agentScheduledActionId = String(action.id || "");

  const isExpanded = state.selectedScheduledActionId === String(action.id);
  if (isExpanded) {
    item.classList.add("is-expanded");
  }

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "agent-action-item-trigger";
  trigger.dataset.agentScheduledActionTrigger = String(action.id || "");
  trigger.setAttribute("aria-expanded", String(isExpanded));
  trigger.setAttribute("aria-controls", `agent-action-expansion-${String(action.id || "")}`);
  trigger.setAttribute("aria-label", `${isExpanded ? "Collapse" : "Open"} ${getScheduledActionTitle(action)}, ${getScheduledActionStatusLabel(action.status, action)}`);

  const head = document.createElement("span");
  head.className = "agent-action-item-head";
  const title = document.createElement("strong");
  title.textContent = getScheduledActionTitle(action);
  head.append(title, createScheduledActionStatus(action));

  const time = document.createElement("span");
  time.className = "agent-action-item-time";
  time.textContent = action.payload?.manualOnly
    ? "Run when you choose"
    : formatScheduledActionDate(
      getScheduledActionItemTimeValue(action),
      action.timezone,
    );

  trigger.append(head, time);

  const expansion = document.createElement("div");
  expansion.id = `agent-action-expansion-${String(action.id || "")}`;
  expansion.className = "agent-action-item-expansion";
  expansion.setAttribute("role", "region");
  expansion.setAttribute("aria-label", `${getScheduledActionTitle(action)} details`);
  expansion.setAttribute("aria-hidden", String(!isExpanded));
  expansion.inert = !isExpanded;

  const expansionInner = document.createElement("div");
  expansionInner.className = "agent-action-item-expansion-inner";
  expansionInner.append(createScheduledActionDetail(action));
  expansion.append(expansionInner);

  item.append(trigger, expansion);
  return item;
}

function createScheduledActionEmpty(message) {
  const empty = document.createElement("p");
  empty.className = "agent-action-empty";
  empty.textContent = message;
  return empty;
}

function renderScheduledActionList(container, actions, emptyMessage) {
  const signature = getScheduledActionListSignature(actions, emptyMessage);
  if (container.dataset.agentActionListSignature === signature) {
    return;
  }

  container.dataset.agentActionListSignature = signature;
  container.replaceChildren(
    ...(actions.length
      ? actions.map(createScheduledActionItem)
      : [createScheduledActionEmpty(emptyMessage)]),
  );
}

function setScheduledActionItemExpandedState(item, isExpanded) {
  if (!item) {
    return;
  }

  item.classList.toggle("is-expanded", isExpanded);
  const trigger = item.querySelector("[data-agent-scheduled-action-trigger]");
  const expansion = item.querySelector(".agent-action-item-expansion");
  const actionTitle = item.querySelector(".agent-action-item-head strong")?.textContent || "Action";
  trigger?.setAttribute("aria-expanded", String(isExpanded));
  trigger?.setAttribute("aria-label", `${isExpanded ? "Collapse" : "Open"} ${actionTitle}`);
  expansion?.setAttribute("aria-hidden", String(!isExpanded));
  if (expansion) {
    expansion.inert = !isExpanded;
  }
}

function syncScheduledActionSelection() {
  const selectedActionId = String(state.selectedScheduledActionId || "");
  for (const item of document.querySelectorAll("[data-agent-scheduled-action-id]")) {
    setScheduledActionItemExpandedState(
      item,
      Boolean(selectedActionId) && item.dataset.agentScheduledActionId === selectedActionId,
    );
  }
}

function preserveAgentActionsScrollPosition(scrollTop) {
  const scrollContainer = elements.agentActionsPanelBody;
  if (!scrollContainer || !Number.isFinite(scrollTop)) {
    return;
  }

  scrollContainer.scrollTop = scrollTop;
  window.requestAnimationFrame(() => {
    scrollContainer.scrollTop = scrollTop;
  });
}

function selectScheduledAction(actionId) {
  const normalizedActionId = String(actionId || "");
  const scrollContainer = elements.agentActionsPanelBody;
  const scrollTop = scrollContainer?.scrollTop;
  state.selectedScheduledActionId = state.selectedScheduledActionId === normalizedActionId
    ? ""
    : normalizedActionId;

  const selectedItem = Array.from(document.querySelectorAll("[data-agent-scheduled-action-id]"))
    .find((item) => item.dataset.agentScheduledActionId === state.selectedScheduledActionId);
  const previousItem = Array.from(document.querySelectorAll(".agent-action-item.is-expanded"))[0];
  if (selectedItem || previousItem) {
    // Keep the existing DOM nodes so the card can animate from its current
    // height. Replacing the list here would make the new card appear already
    // open and would also invite the browser to re-anchor the scroll view.
    syncScheduledActionSelection();
    preserveAgentActionsScrollPosition(scrollTop);
    return;
  }

  renderAgentActions();
  preserveAgentActionsScrollPosition(scrollTop);
}

function handleScheduledActionListClick(event) {
  const target = getEventTargetElement(event);
  const scheduledActionTrigger = target?.closest("[data-agent-scheduled-action-trigger]");
  if (!scheduledActionTrigger) {
    return;
  }
  const actionId = scheduledActionTrigger.dataset.agentScheduledActionTrigger || "";
  if (!actionId) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  selectScheduledAction(actionId);
}

function createScheduledActionDetailRow(label, value) {
  const row = document.createElement("div");
  row.className = "agent-action-detail-row";
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value || "Not available";
  row.append(term, description);
  return row;
}

function getScheduledActionDetailSignature(action) {
  const messageText = String(
    action.payload?.preview
    || action.payload?.summary
    || action.payload?.messageText
    || action.payload?.text
    || "",
  ).trim();
  return JSON.stringify([
    action.id,
    getScheduledActionTitle(action),
    getScheduledActionStatusClass(action.status),
    getScheduledActionStatusLabel(action.status, action),
    messageText,
    formatScheduledActionDate(action.runAt, action.timezone),
    action.timezone || getWorkspaceTimeZone(),
    formatAgentScheduledMessageChannel(action.channel),
    String(action.attemptCount),
    formatScheduledActionDate(action.createdAt, action.timezone),
    action.completedAt ? formatScheduledActionDate(action.completedAt, action.timezone) : "",
    action.providerMessageId,
    action.lastError,
    String(action.payload?.backendFeatureActive ?? ""),
    String(action.payload?.manualOnly ?? ""),
    monitorActionRunBusy.has(String(action.payload?.backendFeatureId || "").trim()),
    String(action.payload?.initialRunStatus || ""),
    String(action.payload?.initialRunMessage || ""),
    String(action.payload?.initialRunError || ""),
    String(action.payload?.deliveryTarget || ""),
    String(action.payload?.deliveryLabel || ""),
    String(action.payload?.lastRunAt || ""),
    String(action.payload?.lastRunStatus || ""),
    String(action.payload?.nextRunAt || ""),
    Array.isArray(action.payload?.watchItems) ? action.payload.watchItems.join("|") : "",
  ]);
}

function getAgentMonitorEditorFrequencyValue(settings = {}) {
  const normalized = normalizeFeatureMonitorSettings(settings);
  if (normalized.manualOnly) {
    return "manual";
  }
  if (normalized.intervalMinutes) {
    return `minutes:${normalized.intervalMinutes}`;
  }
  return `days:${normalized.intervalDays}`;
}

function getAgentMonitorEditorFrequencyOptions(settings = {}) {
  const options = [
    { value: "manual", label: "Run manually" },
    { value: "minutes:5", label: "Every 5 minutes" },
    { value: "minutes:15", label: "Every 15 minutes" },
    { value: "minutes:60", label: "Hourly" },
    { value: "days:1", label: "Daily" },
    { value: "days:7", label: "Weekly" },
    { value: "days:30", label: "Monthly" },
  ];
  const currentValue = getAgentMonitorEditorFrequencyValue(settings);
  if (!options.some((option) => option.value === currentValue)) {
    options.push({ value: currentValue, label: formatAgentWebMonitorFrequency(settings) });
  }
  return options;
}

function getAgentMonitorEditorFrequencySettings(value, currentSettings = {}) {
  const normalizedValue = String(value || "").trim().toLowerCase();
  if (normalizedValue === "manual") {
    return {
      manualOnly: true,
      runMode: "manual",
      intervalMinutes: 0,
    };
  }

  const [unit, rawAmount] = normalizedValue.split(":");
  const amount = Math.max(1, Number.parseInt(rawAmount, 10) || 1);
  return {
    manualOnly: false,
    runMode: "recurring",
    intervalMinutes: unit === "minutes" ? amount : 0,
    intervalDays: unit === "days" ? amount : currentSettings.intervalDays,
  };
}

function setAgentMonitorEditorStatus(editor, message, isError = false) {
  if (!editor?.status) {
    return;
  }
  editor.status.hidden = !message;
  editor.status.textContent = message;
  editor.status.classList.toggle("is-error", isError);
}

function scheduleAgentMonitorAutoSave(action, draft, form, options = {}) {
  const editor = form?._agentMonitorEditor;
  if (!editor) {
    return;
  }
  if (editor.saveTimer) {
    window.clearTimeout(editor.saveTimer);
  }
  if (options.status !== false) {
    setAgentMonitorEditorStatus(editor, "Saving changes…");
  }
  const delayMs = Number.isFinite(options.delayMs) ? Math.max(0, Number(options.delayMs)) : 220;
  editor.saveTimer = window.setTimeout(() => {
    editor.saveTimer = null;
    void saveAgentMonitorActionSettings(action, draft, form).catch(() => {});
  }, delayMs);
}

function updateAgentMonitorActionFrequency(action, settings) {
  const actionId = String(action?.id || "");
  const item = Array.from(document.querySelectorAll("[data-agent-scheduled-action-id]"))
    .find((candidate) => candidate.dataset.agentScheduledActionId === actionId);
  if (!item) {
    return;
  }
  const frequencyTerm = Array.from(item.querySelectorAll("dt"))
    .find((term) => term.textContent === "Frequency");
  if (frequencyTerm?.nextElementSibling) {
    frequencyTerm.nextElementSibling.textContent = formatAgentWebMonitorFrequency(settings);
  }
}

function createAgentMonitorEditor(action) {
  const featureId = String(action?.payload?.backendFeatureId || "").trim();
  const feature = getFeatureById(featureId);
  if (!feature || !isMonitorFeature(feature)) {
    return null;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const draft = {
    watchItems: normalizeMonitorWatchItems(
      currentSettings.watchItems.length
        ? currentSettings.watchItems
        : (action?.payload?.watchItems || []),
    ),
    frequency: getAgentMonitorEditorFrequencyValue(currentSettings),
  };

  const form = document.createElement("form");
  form.className = "agent-action-editor";
  form.dataset.agentMonitorEditForm = featureId;

  const heading = document.createElement("div");
  heading.className = "agent-action-editor-heading";
  const title = document.createElement("strong");
  title.textContent = "Edit monitor";
  const subtitle = document.createElement("span");
  subtitle.textContent = "Changes save automatically.";
  heading.append(title, subtitle);

  const topicsField = document.createElement("div");
  topicsField.className = "agent-action-editor-field";
  const topicsLabel = document.createElement("span");
  topicsLabel.className = "agent-action-editor-label";
  topicsLabel.textContent = "Topics to watch";
  const topicsList = document.createElement("div");
  topicsList.className = "agent-action-editor-topics";
  topicsList.setAttribute("role", "list");
  const topicEntry = document.createElement("div");
  topicEntry.className = "agent-action-editor-topic-entry";
  const topicInput = document.createElement("input");
  topicInput.type = "text";
  topicInput.className = "agent-action-editor-input";
  topicInput.placeholder = "Add a topic or tag";
  topicInput.setAttribute("aria-label", "Add a topic or tag");
  const addTopicButton = document.createElement("button");
  addTopicButton.type = "button";
  addTopicButton.className = "ghost-button small agent-action-editor-add";
  addTopicButton.textContent = "Add";
  topicEntry.append(topicInput, addTopicButton);
  topicsField.append(topicsLabel, topicsList, topicEntry);

  const frequencyField = document.createElement("label");
  frequencyField.className = "agent-action-editor-field";
  const frequencyLabel = document.createElement("span");
  frequencyLabel.className = "agent-action-editor-label";
  frequencyLabel.textContent = "Frequency";
  const frequencySelect = document.createElement("select");
  frequencySelect.className = "agent-action-editor-select";
  frequencySelect.setAttribute("aria-label", "Monitor frequency");
  for (const option of getAgentMonitorEditorFrequencyOptions(currentSettings)) {
    const optionElement = document.createElement("option");
    optionElement.value = option.value;
    optionElement.textContent = option.label;
    frequencySelect.append(optionElement);
  }
  frequencySelect.value = draft.frequency;
  frequencyField.append(frequencyLabel, frequencySelect);

  const delivery = document.createElement("p");
  delivery.className = "agent-action-editor-delivery";
  delivery.textContent = `Results go to ${String(action.payload?.deliveryLabel || formatAgentDeliveryTargetDetail(action.payload?.deliveryChannel || action.channel, action.payload?.deliveryTarget || action.recipientRef) || "your configured delivery" )}.`;

  const status = document.createElement("p");
  status.className = "agent-action-editor-status";
  status.setAttribute("role", "status");
  status.hidden = true;

  const renderTopics = () => {
    topicsList.replaceChildren();
    if (!draft.watchItems.length) {
      const empty = document.createElement("span");
      empty.className = "agent-action-editor-empty";
      empty.textContent = "Add at least one topic.";
      topicsList.append(empty);
      return;
    }
    draft.watchItems.forEach((item, index) => {
      const chip = document.createElement("span");
      chip.className = "agent-action-editor-chip";
      chip.setAttribute("role", "listitem");
      const label = document.createElement("span");
      label.className = "agent-action-editor-chip-label";
      label.textContent = item;
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "agent-action-editor-chip-remove";
      removeButton.dataset.agentMonitorEditorRemove = String(index);
      removeButton.setAttribute("aria-label", `Remove ${item}`);
      removeButton.textContent = "×";
      chip.append(label, removeButton);
      topicsList.append(chip);
    });
  };

  const addTopics = () => {
    const nextItems = normalizeMonitorWatchItems(topicInput.value);
    if (!nextItems.length) {
      topicInput.focus();
      return;
    }
    draft.watchItems = normalizeMonitorWatchItems([...draft.watchItems, ...nextItems]);
    topicInput.value = "";
    renderTopics();
    topicInput.focus();
    scheduleAgentMonitorAutoSave(action, draft, form);
  };

  addTopicButton.addEventListener("click", addTopics);
  topicInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addTopics();
    }
  });
  topicsList.addEventListener("click", (event) => {
    const removeButton = getEventTargetElement(event)?.closest("[data-agent-monitor-editor-remove]");
    if (!removeButton) {
      return;
    }
    const index = Number.parseInt(removeButton.dataset.agentMonitorEditorRemove, 10);
    if (Number.isInteger(index)) {
      draft.watchItems.splice(index, 1);
      renderTopics();
      scheduleAgentMonitorAutoSave(action, draft, form);
    }
  });
  frequencySelect.addEventListener("change", () => {
    draft.frequency = frequencySelect.value;
    scheduleAgentMonitorAutoSave(action, draft, form);
  });

  form._agentMonitorEditor = {
    draft,
    frequencySelect,
    status,
    saveTimer: null,
    savePromise: null,
    saveQueued: false,
  };
  form.append(heading, topicsField, frequencyField, delivery, status);
  renderTopics();
  return form;
}

async function saveAgentMonitorActionSettings(action, draft, form) {
  const editor = form?._agentMonitorEditor;
  const featureId = String(action?.payload?.backendFeatureId || "").trim();
  const feature = getFeatureById(featureId);
  if (!editor || !feature || !isMonitorFeature(feature)) {
    return null;
  }
  if (editor.savePromise) {
    editor.saveQueued = true;
    return editor.savePromise;
  }
  if (featureConfigBusy && featureConfigSavePromise) {
    try {
      await featureConfigSavePromise;
    } catch {
      // Continue with the latest monitor edit after the other save settles.
    }
  }

  const watchItems = normalizeMonitorWatchItems(draft.watchItems);
  if (!watchItems.length) {
    setAgentMonitorEditorStatus(editor, "Add at least one topic before saving.", true);
    return null;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const nextSettings = buildMonitorSettingsForSave(feature, {
    ...currentSettings,
    watchItems,
    ...getAgentMonitorEditorFrequencySettings(editor.frequencySelect?.value, currentSettings),
  });
  setAgentMonitorEditorStatus(editor, "Saving changes…");

  let currentSavePromise = null;
  currentSavePromise = (async () => {
    featureConfigBusy = true;
    try {
      const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/config`, {
        method: "POST",
        headers: getSessionAuthHeaders(),
        body: {
          prompt: { ...feature.prompt },
          settings: nextSettings,
        },
      });
      applyServerFeatureStates([response.feature || {}], { persist: true });
      state.paymentStatus = response.paymentStatus || state.paymentStatus;
      updateAgentMonitorActionFrequency(action, nextSettings);
      setAgentMonitorEditorStatus(editor, "Saved");
      setStatus("Monitor settings saved.");
      return response;
    } catch (error) {
      setAgentMonitorEditorStatus(editor, formatApiErrorMessage(error, "We couldn’t save the monitor settings."), true);
      setStatus("Couldn’t save the monitor settings.");
      throw error;
    } finally {
      featureConfigBusy = false;
      if (editor.savePromise === currentSavePromise) {
        editor.savePromise = null;
      }
      if (featureConfigSavePromise === currentSavePromise) {
        featureConfigSavePromise = null;
      }
      if (editor.saveQueued) {
        editor.saveQueued = false;
        scheduleAgentMonitorAutoSave(action, draft, form, { delayMs: 0, status: false });
      }
    }
  })();
  editor.savePromise = currentSavePromise;
  featureConfigSavePromise = currentSavePromise;
  return currentSavePromise;
}

function createScheduledActionDetail(action) {
  const card = document.createElement("div");
  card.className = "agent-action-detail-card";

  const messageText = String(action.payload?.messageText || action.payload?.text || "").trim();
  if (messageText) {
    const message = document.createElement("p");
    message.className = "agent-action-message";
    message.textContent = `“${messageText}”`;
    card.append(message);
  }

  if (isAgentLocalAction(action)) {
    const payload = action.payload && typeof action.payload === "object" ? action.payload : {};
    const isFeatureAction = isAgentFeatureLiveAction(action);
    const details = document.createElement("dl");
    details.className = "agent-action-detail-grid";
    details.append(
      createScheduledActionDetailRow(isFeatureAction ? "Active since" : "Approved", formatScheduledActionDate(action.createdAt || action.runAt, action.timezone)),
      createScheduledActionDetailRow("Frequency", String(payload.frequency || "As configured").trim()),
      createScheduledActionDetailRow("Delivery", String(
        payload.deliveryLabel
        || formatAgentDeliveryTargetDetail(payload.deliveryChannel || action.channel, payload.deliveryTarget || action.recipientRef)
        || "As configured",
      ).trim()),
    );
    if (payload.location) {
      details.append(createScheduledActionDetailRow("Location", String(payload.location)));
    }
    if (payload.timeWindow) {
      details.append(createScheduledActionDetailRow("Date range", String(payload.timeWindow)));
    }
    if (payload.lastRunAt) {
      const lastRunStatus = String(payload.lastRunStatus || "").trim();
      const lastRunLabel = lastRunStatus
        ? `${formatScheduledActionDate(payload.lastRunAt, action.timezone)} · ${capitalizeWords(lastRunStatus.replace(/[_-]+/g, " "))}`
        : formatScheduledActionDate(payload.lastRunAt, action.timezone);
      details.append(createScheduledActionDetailRow("Last check", lastRunLabel));
    }
    if (payload.nextRunAt) {
      details.append(createScheduledActionDetailRow("Next check", formatScheduledActionDate(payload.nextRunAt, action.timezone)));
    }
    card.append(details);

    if (payload.initialRunError) {
      const error = document.createElement("div");
      error.className = "agent-action-error";
      const errorTitle = document.createElement("strong");
      errorTitle.textContent = payload.manualOnly ? "Setup needs attention" : "First check failed";
      const errorMessage = document.createElement("p");
      errorMessage.textContent = String(payload.initialRunError);
      error.append(errorTitle, errorMessage);
      card.append(error);
    } else if (payload.initialRunMessage) {
      const runNote = document.createElement("div");
      runNote.className = "agent-action-note";
      const runTitle = document.createElement("strong");
      runTitle.textContent = payload.manualOnly ? "Ready to run" : "First check";
      const runMessage = document.createElement("p");
      runMessage.textContent = String(payload.initialRunMessage);
      runNote.append(runTitle, runMessage);
      card.append(runNote);
    }

    if (isFeatureAction) {
      const editor = createAgentMonitorEditor(action);
      if (editor) {
        card.append(editor);
      }
    }

    const localActions = createAgentActionDetailActions(action);
    if (localActions) {
      card.append(localActions);
    }
    return card;
  }

  const details = document.createElement("dl");
  details.className = "agent-action-detail-grid";
  details.append(
    createScheduledActionDetailRow("Scheduled for", formatScheduledActionDate(action.runAt, action.timezone)),
    createScheduledActionDetailRow("Timezone", action.timezone || getWorkspaceTimeZone()),
    createScheduledActionDetailRow("Channel", formatAgentScheduledMessageChannel(action.channel)),
    createScheduledActionDetailRow("Attempts", String(action.attemptCount)),
    createScheduledActionDetailRow("Created", formatScheduledActionDate(action.createdAt, action.timezone)),
  );
  if (action.completedAt) {
    details.append(createScheduledActionDetailRow("Completed", formatScheduledActionDate(action.completedAt, action.timezone)));
  }
  if (action.providerMessageId) {
    details.append(createScheduledActionDetailRow("Provider reference", action.providerMessageId));
  }
  card.append(details);

  if (action.lastError) {
    const error = document.createElement("div");
    error.className = "agent-action-error";
    const errorTitle = document.createElement("strong");
    errorTitle.textContent = "What went wrong";
    const errorMessage = document.createElement("p");
    errorMessage.textContent = action.lastError;
    error.append(errorTitle, errorMessage);
    card.append(error);
  } else {
    const notes = {
      pending: ["Waiting to run", "This action is queued and will run automatically at the scheduled time."],
      running: ["Sending now", "The action has started and is waiting for WhatsApp to respond."],
      sent: ["Accepted by WhatsApp", "WhatsApp accepted the message. Waiting for a delivery update."],
      delivered: ["Delivered", "WhatsApp confirmed that the message reached the recipient."],
      read: ["Read", "WhatsApp confirmed that the message was opened."],
      cancelled: ["Cancelled", "This action will not run."],
    };
    const noteCopy = notes[action.status];
    if (noteCopy) {
      const note = document.createElement("div");
      note.className = "agent-action-note";
      const noteTitle = document.createElement("strong");
      noteTitle.textContent = noteCopy[0];
      const noteMessage = document.createElement("p");
      noteMessage.textContent = noteCopy[1];
      note.append(noteTitle, noteMessage);
      card.append(note);
    }
  }
  const actionControls = createAgentActionDetailActions(action);
  if (actionControls) {
    card.append(actionControls);
  }
  return card;
}

function markScheduledActionsRefreshSuccess(loadedAt = Date.now()) {
  state.scheduledActionsLoadedAt = loadedAt;
  state.scheduledActionsError = "";
  state.scheduledActionsFailureCount = 0;
  state.scheduledActionsLastError = "";
  state.scheduledActionsLastErrorAt = 0;
}

function markScheduledActionsRefreshFailure(error, options = {}) {
  const message = formatApiErrorMessage(error, "Couldn’t refresh actions.");
  state.scheduledActionsFailureCount = Math.max(0, Number(state.scheduledActionsFailureCount || 0)) + 1;
  state.scheduledActionsLastError = message;
  state.scheduledActionsLastErrorAt = Date.now();
  state.scheduledActionsError = (options.userInitiated || state.scheduledActionsFailureCount >= SCHEDULED_ACTIONS_REFRESH_ERROR_THRESHOLD)
    ? message
    : "";
}

function renderAgentActions() {
  if (!elements.agentPendingActionList || !elements.agentCompletedActionList) {
    return;
  }

  const actions = getRenderableAgentActions();
  const activeActions = actions
    .filter((action) => isActiveAgentActionStatus(action.status))
    .sort((left, right) => getScheduledActionSortTime(left) - getScheduledActionSortTime(right));
  const completed = actions
    .filter((action) => !isActiveAgentActionStatus(action.status))
    .sort((left, right) => getScheduledActionSortTime(right, 0) - getScheduledActionSortTime(left, 0));

  elements.agentPendingActionsCount.textContent = String(activeActions.length);
  elements.agentCompletedActionsCount.textContent = String(completed.length);
  const historyExpanded = Boolean(state.agentHistoryExpanded);
  elements.agentHistoryToggleButton?.setAttribute("aria-expanded", String(historyExpanded));
  elements.agentHistoryToggleButton?.setAttribute(
    "aria-label",
    historyExpanded ? "Hide action history" : "Show action history",
  );
  if (elements.agentHistorySection) {
    elements.agentHistorySection.classList.toggle("is-expanded", historyExpanded);
  }
  if (elements.agentCompletedActionList) {
    elements.agentCompletedActionList.hidden = !historyExpanded;
  }
  renderScheduledActionList(elements.agentPendingActionList, activeActions, "No active actions.");
  renderScheduledActionList(elements.agentCompletedActionList, completed, "Action results and errors will appear here.");

  const statusRow = elements.agentActionsStatus?.closest(".agent-actions-sync-row");
  statusRow?.classList.toggle("is-error", Boolean(state.scheduledActionsError));
  statusRow?.classList.toggle("is-syncing", Boolean(state.scheduledActionsLoading && state.scheduledActionsLoadedAt));
  if (elements.agentActionsStatus) {
    if (state.scheduledActionsLoading && !state.scheduledActionsLoadedAt) {
      elements.agentActionsStatus.textContent = "Checking actions…";
    } else if (state.scheduledActionsError) {
      elements.agentActionsStatus.textContent = "Couldn’t refresh actions";
    } else if (state.scheduledActionsLastError && !state.scheduledActionsLoadedAt) {
      elements.agentActionsStatus.textContent = "Retrying actions refresh…";
    } else if (state.scheduledActionsLoadedAt) {
      elements.agentActionsStatus.textContent = `Updated ${new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(state.scheduledActionsLoadedAt))}`;
    } else {
      elements.agentActionsStatus.textContent = "Waiting to check";
    }
  }
  elements.agentActionsRefreshButton?.classList.toggle("is-loading", state.scheduledActionsLoading);
  if (elements.agentActionsRefreshButton) {
    elements.agentActionsRefreshButton.disabled = state.scheduledActionsLoading;
  }

  const selectedAction = actions.find((action) => String(action.id) === String(state.selectedScheduledActionId));
  if (state.selectedScheduledActionId && !selectedAction) {
    state.selectedScheduledActionId = "";
  }
  syncScheduledActionSelection();
  // Action details now live inside the selected card. Keep the legacy detail
  // container hidden so older persisted markup cannot create a second panel.
  elements.agentActionDetailView?.classList.add("is-hidden");
  elements.agentActionDetailContent?.replaceChildren();

  const panelOpen = elements.agentToolsPanel?.classList.contains("is-open");
  setAgentToolsOpen(Boolean(panelOpen));
}

async function refreshScheduledActions(options = {}) {
  if (!isSignedIn()) {
    return null;
  }
  if (scheduledActionsRefreshPromise) {
    return scheduledActionsRefreshPromise;
  }

  const requestToken = String(authSession?.token || "");
  state.scheduledActionsLoading = true;
  renderAgentActions();
  scheduledActionsRefreshPromise = (async () => {
    try {
      const response = await apiRequest("/api/scheduled-actions?limit=100", {
        headers: getSessionAuthHeaders(),
      });
      if (requestToken !== String(authSession?.token || "")) {
        return null;
      }
      state.scheduledActions = Array.isArray(response.actions)
        ? response.actions.map(normalizeScheduledAction).filter((action) => action.id > 0)
        : [];
      markScheduledActionsRefreshSuccess();
      return state.scheduledActions;
    } catch (error) {
      if (requestToken === String(authSession?.token || "")) {
        markScheduledActionsRefreshFailure(error, options);
      }
      return null;
    } finally {
      if (requestToken === String(authSession?.token || "")) {
        state.scheduledActionsLoading = false;
        renderAgentActions();
      }
      scheduledActionsRefreshPromise = null;
    }
  })();
  return scheduledActionsRefreshPromise;
}

async function refreshWhatsAppApprovals() {
  if (!isSignedIn() || whatsappApprovalsRefreshPromise) {
    return null;
  }

  const requestToken = String(authSession?.token || "");
  whatsappApprovalsRefreshPromise = (async () => {
    try {
      const response = await apiRequest("/api/approvals?status=pending&delivery=portal", {
        headers: getSessionAuthHeaders(),
      });
      if (requestToken !== String(authSession?.token || "")) {
        return null;
      }

      const approvals = Array.isArray(response.approvals) ? response.approvals : [];
      const agent = getAgentWorkspace();
      const knownApprovalIds = new Set(
        agent.messages
          .filter((message) => message.metadata?.kind === "whatsapp-reply-suggestion")
          .map((message) => String(message.metadata?.approvalId || "").trim())
          .filter(Boolean),
      );
      let didAddMessage = false;
      for (const approval of approvals) {
        const approvalId = String(approval?.approval_id || approval?.approvalId || "").trim();
        if (!approvalId || knownApprovalIds.has(approvalId)) {
          continue;
        }
        const senderName = String(approval.sender_name || approval.sender_wa_id || "WhatsApp contact").trim();
        pushAgentMessage("assistant", `A new WhatsApp message arrived from ${senderName}.`, {
          kind: "whatsapp-reply-suggestion",
          approvalId,
          approval,
          excludeFromModel: true,
        });
        knownApprovalIds.add(approvalId);
        didAddMessage = true;
      }
      if (didAddMessage) {
        persistClientState();
        renderAgentMessages();
      }
      return approvals;
    } catch {
      // The chat remains usable when an inbox refresh is temporarily offline;
      // the next poll will retry without interrupting the user's conversation.
      return null;
    } finally {
      whatsappApprovalsRefreshPromise = null;
    }
  })();
  return whatsappApprovalsRefreshPromise;
}

function syncWhatsAppApprovalsPolling() {
  const shouldPoll = Boolean(
    isSignedIn()
    && document.body.dataset.view === "app"
    && document.visibilityState !== "hidden"
    && state.activeTab === "features"
    && !state.selectedFeatureId
  );
  if (!shouldPoll) {
    if (whatsappApprovalsPollTimer !== null) {
      window.clearInterval(whatsappApprovalsPollTimer);
      whatsappApprovalsPollTimer = null;
    }
    return;
  }

  if (!whatsappApprovalsRefreshPromise) {
    void refreshWhatsAppApprovals();
  }
  if (whatsappApprovalsPollTimer === null) {
    whatsappApprovalsPollTimer = window.setInterval(() => {
      void refreshWhatsAppApprovals();
    }, WHATSAPP_APPROVALS_POLL_MS);
  }
}

function syncScheduledActionsPolling() {
  const shouldPoll = Boolean(
    isSignedIn()
    && document.body.dataset.view === "app"
    && document.visibilityState !== "hidden"
    && state.activeTab === "features"
    && !state.selectedFeatureId
  );
  if (!shouldPoll) {
    if (scheduledActionsPollTimer !== null) {
      window.clearInterval(scheduledActionsPollTimer);
      scheduledActionsPollTimer = null;
    }
    syncWhatsAppApprovalsPolling();
    return;
  }

  if (!state.scheduledActionsLoadedAt && !scheduledActionsRefreshPromise) {
    void refreshScheduledActions();
  }
  if (scheduledActionsPollTimer === null) {
    scheduledActionsPollTimer = window.setInterval(() => {
      void refreshScheduledActions();
    }, SCHEDULED_ACTIONS_POLL_MS);
  }
  syncWhatsAppApprovalsPolling();
}

function updateAgentWorkspace() {
  if (!elements.agentMessageList) {
    return;
  }

  renderAgentMessages();
  renderAgentActions();
  if (elements.agentComposerInput) {
    elements.agentComposerInput.disabled = agentTurnBusy;
    elements.agentComposerInput.setAttribute("aria-busy", String(agentTurnBusy));
  }
  if (elements.agentComposerButton) {
    elements.agentComposerButton.disabled = agentTurnBusy;
  }
}

function applyAgentScheduledMessageRevision(proposal, changes = {}) {
  if (proposal?.type !== "scheduled-message") {
    return false;
  }

  const patch = changes && typeof changes === "object" ? changes : {};
  const details = proposal.details && typeof proposal.details === "object" ? { ...proposal.details } : {};
  const previousTime = String(details.timeLocal || "").trim();
  const previousMessage = String(details.messageText || "").trim();
  const messageWasGenerated = details.messageSource === "generated"
    || isAgentDefaultScheduledMessageText(previousMessage, previousTime);
  const hasChange = (field) => Object.prototype.hasOwnProperty.call(patch, field);

  if (hasChange("channel")) {
    details.channel = normalizeAgentDeliveryChannel(patch.channel);
  }
  if (hasChange("timeLocal")) {
    details.timeLocal = String(patch.timeLocal || "").trim();
  }
  if (hasChange("datePolicy")) {
    details.datePolicy = String(patch.datePolicy || "next_occurrence").trim();
  }
  if (hasChange("messageText")) {
    details.messageText = String(patch.messageText || "").trim();
    details.messageSource = "user";
  } else if (
    hasChange("timeLocal")
    && messageWasGenerated
    && patch.preserveMessageText !== true
  ) {
    details.messageText = getAgentDefaultScheduledMessageText(details.timeLocal);
    details.messageSource = "generated";
  }

  details.timezone = details.timezone
    || normalizeMonitorScheduleTimezone(clientState?.settings?.timezone || defaultTimeZone(), "UTC")
    || "UTC";
  details.runAt = resolveAgentScheduledRunAt(details);
  proposal.details = details;
  proposal.executionPlan = buildAgentScheduledMessageExecutionPlan(details);

  const channel = normalizeAgentDeliveryChannel(details.channel);
  if (channel === "whatsapp") {
    proposal.relatedFeatureId = WHATSAPP_REPLY_ASSISTANT_FEATURE_ID;
    proposal.setupActionLabel = "Open WhatsApp setup";
    proposal.missingCredential = isFeatureSetupComplete(getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID))
      ? ""
      : "WhatsApp Business API access token";
  } else {
    proposal.relatedFeatureId = "";
    proposal.missingCredential = "";
  }

  const channelLabel = formatAgentScheduledMessageChannel(channel);
  const timeLabel = details.timeLocal ? ` at ${details.timeLocal}` : "";
  proposal.summary = `Schedule a one-shot ${channelLabel} message${timeLabel}.`;
  proposal.revision = Math.max(1, Number(proposal.revision || 1)) + 1;
  proposal.updatedAt = new Date().toISOString();
  proposal.status = "needs-approval";
  proposal.approved = false;
  return true;
}

function getAgentActionIntentText(action, value = "") {
  const normalizedAction = String(action || "").trim();
  if (normalizedAction === "approve-proposal") {
    return "Set it up please";
  }
  if (normalizedAction === "request-change") {
    return "Change something";
  }
  if (normalizedAction === "open-setup") {
    return "Open setup";
  }
  if (normalizedAction === "credential-help") {
    return "Help me get it";
  }
  if (normalizedAction === "show-whatsapp-setup") {
    return "Set up WhatsApp details";
  }
  if (normalizedAction === "open-whatsapp-setup") {
    return "Open WhatsApp setup";
  }
  return String(value || "").trim();
}

function pushAgentActionIntentMessage(action, value = "", proposalId = "") {
  const text = getAgentActionIntentText(action, value);
  if (!text) {
    return null;
  }
  return pushAgentMessage("user", text, {
    kind: "action-intent",
    action,
    proposalId,
  });
}

function handleAgentMessageAction(event) {
  const target = getEventTargetElement(event);
  const button = target?.closest("[data-agent-message-action]");
  if (!button) {
    return false;
  }

  if (button.disabled) {
    return true;
  }

  const action = button.dataset.agentMessageAction || "";
  const proposalId = button.dataset.agentActionProposal || "";
  const proposalRevision = Math.max(0, Number(button.dataset.agentActionRevision || 0));
  const value = button.dataset.agentActionValue || button.textContent || "";
  const messageId = button.dataset.agentActionMessage || "";
  resolveAgentMessageActions(messageId, action);
  persistClientState();
  renderAgentMessages();

  if (action === "approve-proposal") {
    pushAgentActionIntentMessage(action, value, proposalId);
    persistClientState();
    renderAgentMessages();
    startAgentProposalApproval(proposalId, proposalRevision);
    return true;
  }

  if (action === "request-change") {
    pushAgentActionIntentMessage(action, value, proposalId);
    persistClientState();
    renderAgentMessages();
    requestAgentProposalChanges(proposalId, proposalRevision);
    return true;
  }

  if (action === "open-setup") {
    pushAgentActionIntentMessage(action, value, proposalId);
    persistClientState();
    renderAgentMessages();
    openAgentProposalSetup(proposalId);
    return true;
  }

  if (action === "credential-help") {
    pushAgentActionIntentMessage(action, value, proposalId);
    persistClientState();
    renderAgentMessages();
    openAgentCredentialHelp(proposalId);
    return true;
  }

  if (action === "show-whatsapp-setup") {
    pushAgentActionIntentMessage(action, value);
    pushAgentWhatsAppSetupCard();
    persistAgentWorkspace("WhatsApp setup details are ready.");
    renderApp({ preserveStatus: true });
    return true;
  }

  if (action === "open-whatsapp-setup") {
    pushAgentActionIntentMessage(action, value);
    persistAgentWorkspace("Opening WhatsApp setup...");
    renderApp({ preserveStatus: true });
    openAgentWhatsAppSetup();
    return true;
  }

  if (action === "choose") {
    handleAgentUserText(value);
    return true;
  }

  return false;
}

function startAgentProposalApproval(proposalId, expectedRevision = 0) {
  if (agentTurnBusy) {
    return;
  }

  agentTurnBusy = true;
  agentTurnProgressText = "Setting it up";
  persistAgentWorkspace("Setting it up...");
  renderApp({ preserveStatus: true });

  void approveAgentProposal(proposalId, expectedRevision)
    .catch((error) => {
      const message = formatApiErrorMessage(error, "I couldn’t finish setting that up yet.");
      pushAgentMessage("assistant", message, {
        kind: "result",
        proposalId,
      });
      persistAgentWorkspace(message);
      renderApp({ preserveStatus: true });
    })
    .finally(() => {
      agentTurnBusy = false;
      agentTurnProgressText = "Thinking";
      renderApp({ preserveStatus: true });
    });
}

function pushAgentProposalResult(proposalId, text, kind = "result") {
  const message = String(text || "").trim();
  if (!message) {
    return null;
  }

  return pushAgentMessage("assistant", message, {
    kind,
    ...(proposalId ? { proposalId } : {}),
  });
}

function buildAgentTurnActiveProposal(proposal) {
  if (!proposal || proposal.approved || proposal.status === "rejected") {
    return null;
  }
  return {
    id: proposal.id,
    type: proposal.type,
    revision: Math.max(1, Number(proposal.revision || 1)),
    requestText: proposal.requestText,
    summary: proposal.summary,
    details: proposal.details,
    fields: proposal.fields,
    questions: proposal.questions,
    answers: proposal.answers,
  };
}

function isAgentWhatsAppMonitoringRequest(text) {
  const value = String(text || "").trim().toLowerCase();
  return /\b(?:whatsapp|whats\s*app|wa)\b/.test(value)
    && /\b(?:watch|monitor|listen|track|incoming|new\s+messages?)\b/.test(value);
}

function buildAgentWhatsAppSetupMetadata(setup, actionId, actionLabel) {
  return {
    connectionSetup: {
      platformConnected: Boolean(setup?.genericPlatformConnected),
      connectionStatus: String(setup?.connectionStatus || "not_connected"),
      missingFields: Array.isArray(setup?.missingFields)
        ? setup.missingFields.map((field) => ({
          key: String(field?.key || "").trim(),
          label: String(field?.label || "").trim(),
        })).filter((field) => field.key && field.label)
        : [],
    },
    actions: actionId
      ? [createAgentAction(actionId, actionLabel, "whatsapp", "primary")]
      : [],
  };
}

function pushAgentWhatsAppSetupPrompt() {
  const setup = getWhatsAppConnectionSetupState();
  const firstMissing = setup.missingFields?.[0]?.label || "WhatsApp Business connection details";
  const message = setup.genericPlatformConnected
    ? `WhatsApp is connected for general use. To monitor incoming messages, I need your ${firstMissing} first.`
    : `I can set that up. I need your ${firstMissing} first.`;
  return pushAgentMessage("assistant", message, {
    kind: "question",
    ...buildAgentWhatsAppSetupMetadata(setup, "show-whatsapp-setup", "Set up WhatsApp details"),
  });
}

function pushAgentWhatsAppSetupCard() {
  const setup = getWhatsAppConnectionSetupState();
  const message = setup.genericPlatformConnected
    ? "Here’s what is still needed for WhatsApp message monitoring."
    : "Here’s what I need to connect WhatsApp message monitoring.";
  return pushAgentMessage("assistant", message, {
    kind: "connection-setup",
    ...buildAgentWhatsAppSetupMetadata(setup, "open-whatsapp-setup", "Open WhatsApp setup"),
  });
}

function openAgentWhatsAppSetup() {
  const feature = getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID)
    || clientState.features.find((candidate) => isWhatsAppFeature(candidate));
  if (feature) {
    openFeatureStudio(feature.id, "activation");
    return;
  }
  openPlatformConnection("whatsapp");
}

function createAgentProposalFromTurn(requestText, turn = {}) {
  const blueprint = getAgentBlueprintForType(turn.proposalType);
  const proposal = createAgentProposalFromRequest(requestText, blueprint);
  if (proposal.type === "scheduled-message" && turn.changes && typeof turn.changes === "object") {
    applyAgentScheduledMessageRevision(proposal, turn.changes);
    proposal.revision = 1;
    proposal.createdAt = new Date().toISOString();
    proposal.updatedAt = proposal.createdAt;
  } else {
    applyAgentFieldProposalRevision(proposal, turn.changes, { bumpRevision: false });
  }
  return proposal;
}

function applyAgentTurnProposalRevision(proposal, changes = {}) {
  if (proposal?.type === "scheduled-message") {
    return applyAgentScheduledMessageRevision(proposal, changes);
  }
  if (!proposal || !applyAgentFieldProposalRevision(proposal, changes)) {
    return false;
  }
  return true;
}

async function applyAgentTurnResponse(turn, userText) {
  const agent = getAgentWorkspace();
  const activeProposal = agent.proposals.find((proposal) => proposal.id === agent.activeProposalId)
    || agent.proposals[agent.proposals.length - 1]
    || null;
  const currentRevision = Math.max(1, Number(activeProposal?.revision || 1));
  const outcome = String(turn?.outcome || "").trim();
  const reply = String(turn?.reply || "").trim();

  if (outcome === "approve_proposal" && activeProposal && !activeProposal.approved) {
    agentTurnProgressText = "Setting it up";
    renderApp({ preserveStatus: true });
    await approveAgentProposal(activeProposal.id, currentRevision);
    return true;
  }

  if (outcome === "approve_proposal") {
    if (reply) {
      pushAgentMessage("assistant", reply, { kind: "text" });
    } else {
      setStatus("Use the latest Set it up button to approve a plan.");
    }
    return true;
  }

  if (outcome === "reject_proposal" && activeProposal && !activeProposal.approved) {
    activeProposal.status = "rejected";
    activeProposal.updatedAt = new Date().toISOString();
    if (reply) {
      pushAgentMessage("assistant", reply, {
        kind: "result",
        proposalId: activeProposal.id,
      });
    }
    return true;
  }

  if (
    outcome === "revise_proposal"
    && activeProposal
    && applyAgentTurnProposalRevision(activeProposal, turn.changes)
  ) {
    pushAgentProposalNextStep(activeProposal, reply);
    return true;
  }

  if (outcome === "proposal" || (outcome === "question" && turn?.proposalType)) {
    const proposal = createAgentProposalFromTurn(userText, turn);
    agent.proposals.push(proposal);
    agent.activeProposalId = proposal.id;
    pushAgentProposalNextStep(proposal, reply);
    return true;
  }

  if (reply) {
    pushAgentMessage(
      "assistant",
      reply,
      { kind: outcome === "question" ? "question" : "text" },
    );
  }
  return true;
}

async function handleAgentUserText(text) {
  const cleanText = String(text || "").trim();
  if (!cleanText || agentTurnBusy) {
    return;
  }

  // Never put a likely credential into the transcript or the LLM request.
  // Ask the user to use the dedicated secure connection form instead.
  if (looksLikeCredential(cleanText)) {
    pushAgentMessage("assistant", "Please don’t paste access tokens into chat. Choose the app from Available tools and use its secure connection form instead.", { kind: "credential" });
    persistAgentWorkspace("Use the secure connection form for access tokens.");
    renderApp({ preserveStatus: true });
    return;
  }

  const whatsappSetup = getWhatsAppConnectionSetupState();
  if (isAgentWhatsAppMonitoringRequest(cleanText) && !whatsappSetup.ready) {
    resolvePendingAgentMessageActions("user-message");
    pushAgentMessage("user", cleanText);
    pushAgentWhatsAppSetupPrompt();
    persistAgentWorkspace("WhatsApp setup details are needed.");
    renderApp({ preserveStatus: true });
    elements.agentComposerInput?.focus();
    return;
  }

  const platformConnection = getPlatformConnectionIntentFromText(cleanText);
  if (platformConnection) {
    resolvePendingAgentMessageActions("platform-connection");
    pushAgentMessage("user", cleanText);
    pushAgentMessage("assistant", `Let’s connect ${platformConnection.label}.`);
    persistAgentWorkspace(`Connecting ${platformConnection.label}...`);
    renderApp({ preserveStatus: true });
    openPlatformConnection(platformConnection.id);
    return;
  }

  resolvePendingAgentMessageActions("user-message");
  pushAgentMessage("user", cleanText);
  const agent = getAgentWorkspace();
  const activeProposal = getActiveAgentProposal();
  const conversation = agent.messages.slice(-12).filter((message) => !message.metadata?.excludeFromModel).map((message) => ({
    role: message.role,
    text: message.text,
  }));
  const activeProposalPayload = buildAgentTurnActiveProposal(activeProposal);
  agentTurnBusy = true;
  agentTurnProgressText = "Thinking";
  persistAgentWorkspace("Assistyca is thinking...");
  renderApp({ preserveStatus: true });

  try {
    const turn = await apiRequest("/api/agent/turn", {
      method: "POST",
      // Keep this longer than the backend OpenAI gateway timeout so a slow
      // model response becomes a useful 503/502 diagnostic instead of an
      // opaque browser-side AbortError.
      timeoutMs: 90000,
      body: {
        userMessage: cleanText,
        timezone: normalizeMonitorScheduleTimezone(
          clientState?.settings?.timezone || defaultTimeZone(),
          "UTC",
        ) || "UTC",
        conversation,
        activeProposal: activeProposalPayload,
        toolContext: buildAgentToolContext(),
      },
    });
    await applyAgentTurnResponse(turn, cleanText);
    agentTurnBusy = false;
    agentTurnProgressText = "Thinking";
    persistAgentWorkspace("Agent updated.");
    renderApp({ preserveStatus: true });
  } catch (error) {
    agentTurnBusy = false;
    agentTurnProgressText = "Thinking";
    const message = formatApiErrorMessage(
      error,
      "I couldn’t get a response right now. Please try again in a moment.",
    );
    // Keep failures in the conversation. A status-only update made the
    // thinking indicator disappear and left the user with no explanation.
    pushAgentMessage("assistant", message, {
      kind: "error",
      technical: getAgentErrorTechnicalInfo(error),
    });
    persistAgentWorkspace(message);
    renderApp({ preserveStatus: true });
    elements.agentComposerInput?.focus();
  }
}

function handleAgentComposerSubmit(event = null) {
  event?.preventDefault();
  if (agentTurnBusy) {
    return;
  }
  const input = elements.agentComposerInput;
  const text = String(input?.value || "").trim();
  if (!text) {
    input?.focus();
    return;
  }

  if (input) {
    input.value = "";
  }

  void handleAgentUserText(text);
}

function normalizeAgentComposerPastedText(text) {
  return String(text || "")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]*\n+[ \t]*/g, " ")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function insertAgentComposerText(input, text) {
  const value = String(text || "");
  if (!input || !value) {
    return;
  }

  const start = typeof input.selectionStart === "number" ? input.selectionStart : input.value.length;
  const end = typeof input.selectionEnd === "number" ? input.selectionEnd : start;
  if (typeof input.setRangeText === "function") {
    input.setRangeText(value, start, end, "end");
  } else {
    input.value = `${input.value.slice(0, start)}${value}${input.value.slice(end)}`;
    const caret = start + value.length;
    input.setSelectionRange?.(caret, caret);
  }
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleAgentComposerPaste(event) {
  const pastedText = event.clipboardData?.getData("text") || "";
  const normalizedText = normalizeAgentComposerPastedText(pastedText);
  if (!normalizedText || normalizedText === pastedText) {
    return;
  }

  event.preventDefault();
  insertAgentComposerText(event.currentTarget, normalizedText);
}

async function scheduleAgentScheduledMessageProposal(proposal) {
  const details = proposal.details && typeof proposal.details === "object" ? { ...proposal.details } : {};
  details.channel = normalizeAgentDeliveryChannel(details.channel);
  details.timezone = details.timezone || normalizeMonitorScheduleTimezone(clientState?.settings?.timezone || defaultTimeZone(), "UTC") || "UTC";
  details.runAt = resolveAgentScheduledRunAt(details) || String(details.runAt || "").trim();
  details.messageText = String(details.messageText || "").trim();

  if (details.channel !== "whatsapp") {
    throw new Error("Only WhatsApp scheduled messages are supported right now.");
  }
  if (!details.runAt) {
    throw new Error("I need an exact send time before I can schedule this.");
  }
  if (!details.messageText) {
    throw new Error("I need message text before I can schedule this.");
  }

  proposal.details = details;
  proposal.executionPlan = buildAgentScheduledMessageExecutionPlan(details);
  return apiRequest("/api/scheduled-actions", {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: {
      actionType: "send_message",
      channel: details.channel,
      recipientRef: details.recipientRef || "owner",
      runAt: details.runAt,
      timezone: details.timezone,
      messageText: details.messageText,
      source: "portal_agent",
      payload: {
        proposalId: proposal.id,
        requestText: proposal.requestText,
        messageText: details.messageText,
      },
    },
  });
}

function buildAgentWebMonitorWatchItem(proposal) {
  const watchQuery = getAgentProposalFieldValue(proposal, "watchQuery") || proposal?.requestText || "";
  const location = getAgentProposalFieldValue(proposal, "location");
  const timeWindow = getAgentProposalFieldValue(proposal, "timeWindow");
  const pieces = [watchQuery];
  if (location) {
    pieces.push(`Location: ${location}`);
  }
  if (timeWindow) {
    pieces.push(`Date range: ${timeWindow}`);
  }
  return pieces
    .map((piece) => String(piece || "").trim())
    .filter(Boolean)
    .join(" · ");
}

function buildAgentWebMonitorSettings(proposal) {
  const requestText = String(proposal?.requestText || "");
  const requestedFrequency = extractAgentFrequencyField(requestText);
  const frequency = requestedFrequency || getAgentProposalFieldValue(proposal, "frequency");
  const interval = buildAgentMonitorIntervalFromFrequency(frequency);
  const requestsManualRuns = /\b(manual(?:ly)?|on[ -]?demand|when i want|when i ask|turn(?:ed)? on manually)\b/i.test(requestText);
  // Agent-created monitors are manual by default; only an explicit cadence in
  // the user's request opts into recurring background checks.
  const manualOnly = requestsManualRuns || !requestedFrequency;
  const deliveryChannel = normalizeAgentDeliveryChannel(getAgentProposalFieldValue(proposal, "deliveryChannel"))
    || normalizeAgentDeliveryChannel(proposal?.requestText || "")
    || DEFAULT_MONITOR_SETTINGS.deliveryChannel;
  const settings = normalizeFeatureMonitorSettings({
    ...DEFAULT_MONITOR_SETTINGS,
    watchItems: [buildAgentWebMonitorWatchItem(proposal)],
    manualOnly,
    runMode: manualOnly ? "manual" : "recurring",
    intervalMinutes: interval.intervalMinutes,
    intervalDays: interval.intervalDays,
    scheduleTimezone: getWorkspaceTimeZone(),
    deliveryChannel,
  });

  if (!settings.watchItems.length) {
    throw new Error("I need a topic to watch before I can activate the web monitor.");
  }
  return settings;
}

function formatAgentWebMonitorFrequency(settings = {}) {
  if (normalizeMonitorManualOnly(settings.manualOnly)) {
    return "manual only";
  }
  const intervalMinutes = normalizeMonitorIntervalMinutes(settings.intervalMinutes);
  if (intervalMinutes) {
    if (intervalMinutes < 60) {
      return `every ${intervalMinutes} minutes`;
    }
    if (intervalMinutes % 60 === 0) {
      const hours = intervalMinutes / 60;
      return hours === 1 ? "hourly" : `every ${hours} hours`;
    }
    return `every ${intervalMinutes} minutes`;
  }

  const intervalDays = normalizeMonitorIntervalDays(settings.intervalDays);
  if (intervalDays === 1) {
    return "daily";
  }
  if (intervalDays % 30 === 0) {
    const months = intervalDays / 30;
    return months === 1 ? "monthly" : `every ${months} months`;
  }
  if (intervalDays % 7 === 0) {
    const weeks = intervalDays / 7;
    return weeks === 1 ? "weekly" : `every ${weeks} weeks`;
  }
  return `every ${intervalDays} days`;
}

async function runAgentWebMonitorInitialCheck() {
  const response = await apiRequest(`/api/features/${encodeURIComponent(MONITOR_FEATURE_ID)}/run`, {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: {
      runRequestId: createManualMonitorRunRequestId(),
    },
    timeoutMs: 90000,
  });
  const run = response.run || {};
  return {
    response,
    status: String(run.status || "").trim(),
    message: getManualMonitorRunAlertMessage(run, response.message || "First monitor check finished."),
  };
}

async function saveAndActivateAgentWebMonitorProposal(proposal) {
  if (!isSignedIn()) {
    throw new Error("Sign in before activating a web monitor.");
  }

  const feature = getFeatureById(MONITOR_FEATURE_ID);
  if (!feature) {
    throw new Error("Scheduled Web Monitor is not available for this account.");
  }

  const settings = buildAgentWebMonitorSettings(proposal);
  const prompt = feature.prompt && typeof feature.prompt === "object" ? { ...feature.prompt } : {};
  const configResponse = await apiRequest(`/api/features/${encodeURIComponent(MONITOR_FEATURE_ID)}/config`, {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: {
      prompt,
      settings,
    },
  });
  applyServerFeatureStates([configResponse.feature || {}], { persist: true });
  state.paymentStatus = configResponse.paymentStatus || state.paymentStatus;

  const updatedFeature = getFeatureById(MONITOR_FEATURE_ID) || feature;
  const activationResponse = await apiRequest(`/api/features/${encodeURIComponent(MONITOR_FEATURE_ID)}/activation`, {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: {
      action: "activate",
      featureName: updatedFeature.name,
      channel: updatedFeature.channel,
    },
  });
  applyServerFeatureStates([activationResponse.feature || {}], { persist: true });
  state.paymentStatus = activationResponse.paymentStatus || state.paymentStatus;

  let initialRun = null;
  let initialRunError = "";
  if (settings.manualOnly) {
    initialRun = {
      status: "manual_only",
      message: "Ready when you are. Use Run now for a fresh top-five summary.",
    };
  } else {
    try {
      initialRun = await runAgentWebMonitorInitialCheck();
    } catch (error) {
      initialRunError = formatApiErrorMessage(error, "The monitor was activated, but the first check could not run yet.");
    }
  }

  proposal.relatedFeatureId = MONITOR_FEATURE_ID;
  proposal.executionPlan = {
    ...proposal.executionPlan,
    backendFeatureId: MONITOR_FEATURE_ID,
    backendStatus: "active",
    settings,
    frequency: formatAgentWebMonitorFrequency(settings),
    initialRunStatus: initialRun?.status || "",
    initialRunMessage: initialRun?.message || "",
    initialRunError,
  };
  const deliveryTarget = getAgentProposalDeliveryTarget(proposal, settings.deliveryChannel);
  proposal.executionPlan.deliveryTarget = deliveryTarget;
  proposal.summary = `Monitor ${settings.watchItems[0]} ${formatAgentWebMonitorFrequency(settings)} and send source-backed alerts ${formatAgentDeliveryTargetSentence(settings.deliveryChannel, deliveryTarget)}.`;
  return {
    configResponse,
    activationResponse,
    initialRun,
    initialRunError,
    settings,
  };
}

function buildAgentWhatsAppReplySettings(proposal, feature) {
  const requestedChannel = getAgentProposalDeliveryChannel(proposal) || "portal";
  const currentSettings = getSelectedFeatureSettings(feature);
  return buildSettingsForSave(feature, {
    ...currentSettings,
    deliveryChannels: [requestedChannel],
  });
}

async function saveAndActivateAgentWhatsAppProposal(proposal) {
  if (!isSignedIn()) {
    throw new Error("Sign in before activating the WhatsApp reply assistant.");
  }

  const feature = getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID);
  if (!feature) {
    throw new Error("WhatsApp Reply Assistant is not available for this account.");
  }

  const settings = buildAgentWhatsAppReplySettings(proposal, feature);
  const prompt = feature.prompt && typeof feature.prompt === "object" ? { ...feature.prompt } : {};
  const configResponse = await apiRequest(`/api/features/${encodeURIComponent(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID)}/config`, {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: { prompt, settings },
  });
  applyServerFeatureStates([configResponse.feature || {}], { persist: true });
  state.paymentStatus = configResponse.paymentStatus || state.paymentStatus;

  const updatedFeature = getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID) || feature;
  const activationResponse = await apiRequest(`/api/features/${encodeURIComponent(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID)}/activation`, {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: {
      action: "activate",
      featureName: updatedFeature.name,
      channel: updatedFeature.channel,
    },
  });
  applyServerFeatureStates([activationResponse.feature || {}], { persist: true });
  state.paymentStatus = activationResponse.paymentStatus || state.paymentStatus;
  return { configResponse, activationResponse, settings };
}

function handleAgentWhatsAppActivationError(error, proposal) {
  proposal.status = "needs-approval";
  proposal.updatedAt = new Date().toISOString();
  const payload = error?.payload || {};
  if (payload.feature) {
    applyServerFeatureStates([payload.feature], { persist: true });
  }
  state.paymentStatus = payload.paymentStatus || state.paymentStatus;

  if (payload.error === "payment_required") {
    const checkoutUrl = payload.paymentStatus?.checkoutUrl || payload.checkoutUrl || "";
    const checkoutOpened = openPaymentCheckout(checkoutUrl);
    const message = payload.message || "Add payment details before activating the WhatsApp reply assistant.";
    pushAgentProposalResult(proposal.id, message, "credential");
    persistAgentWorkspace(checkoutOpened ? "Opening checkout..." : "Payment is required before activation.");
    renderApp({ preserveStatus: true });
    return;
  }

  if (payload.error === "setup_required") {
    const message = String(
      payload.message
      || payload.setupStatus?.message
      || "I need the WhatsApp Business connection details before I can start this.",
    ).trim();
    pushAgentProposalResult(proposal.id, message, "credential");
    pushAgentWhatsAppSetupPrompt();
    persistAgentWorkspace(message);
    renderApp({ preserveStatus: true });
    return;
  }

  const message = formatApiErrorMessage(error, "I couldn’t activate the WhatsApp reply assistant yet.");
  pushAgentProposalResult(proposal.id, message);
  persistAgentWorkspace(message);
  renderApp({ preserveStatus: true });
}

function handleAgentWebMonitorActivationError(error, proposal) {
  const payload = error?.payload || {};
  proposal.status = "needs-approval";
  proposal.updatedAt = new Date().toISOString();
  if (payload.feature) {
    applyServerFeatureStates([payload.feature], { persist: true });
  }
  state.paymentStatus = payload.paymentStatus || state.paymentStatus;

  if (payload.error === "payment_required") {
    const checkoutUrl = payload.paymentStatus?.checkoutUrl || payload.checkoutUrl || "";
    const checkoutOpened = openPaymentCheckout(checkoutUrl);
    const message = payload.message || "Add payment details before activating this monitor.";
    pushAgentProposalResult(proposal.id, message);
    openFeatureActivationAlert(
      "Payment needed",
      message,
      {
        eyebrow: "Billing required",
        returnFocus: elements.agentComposerInput,
      },
    );
    persistAgentWorkspace(checkoutOpened ? "Opening checkout..." : "Payment is required before activation.");
    renderApp({ preserveStatus: true });
    return;
  }

  if (payload.error === "setup_required") {
    const setupStatus = payload.setupStatus || {};
    const message = String(
      payload.message
      || setupStatus.message
      || "Finish the web monitor setup before activating it.",
    ).trim();
    pushAgentProposalResult(proposal.id, message, "credential");
    openFeatureActivationAlert(
      "Finish setup first",
      message,
      {
        eyebrow: "One thing left",
        returnFocus: elements.agentComposerInput,
      },
    );
    persistAgentWorkspace(message);
    renderApp({ preserveStatus: true });
    return;
  }

  const message = formatApiErrorMessage(error, "I couldn’t activate the web monitor yet.");
  pushAgentProposalResult(proposal.id, message);
  openFeatureActivationAlert("Couldn’t activate the monitor", message, {
    eyebrow: "Try again",
    returnFocus: elements.agentComposerInput,
  });
  persistAgentWorkspace(message);
  renderApp({ preserveStatus: true });
}

async function approveAgentProposal(proposalId, expectedRevision = 0) {
  const agent = getAgentWorkspace();
  const proposal = agent.proposals.find((candidate) => candidate.id === proposalId);
  if (!proposal || proposal.approved || proposal.status === "scheduling") {
    return;
  }

  const currentRevision = Math.max(1, Number(proposal.revision || 1));
  if (expectedRevision > 0 && expectedRevision !== currentRevision) {
    persistAgentWorkspace("Latest plan approval required.");
    renderApp({ preserveStatus: true });
    return;
  }

  if (
    proposal.type === "scheduled-message"
    && normalizeAgentDeliveryChannel(proposal.details?.channel) === "whatsapp"
    && isFeatureSetupComplete(getFeatureById(WHATSAPP_REPLY_ASSISTANT_FEATURE_ID))
  ) {
    proposal.missingCredential = "";
    proposal.relatedFeatureId = WHATSAPP_REPLY_ASSISTANT_FEATURE_ID;
  }

  if (proposal.type === "whatsapp-replies" && isWhatsAppConnectionReady()) {
    proposal.missingCredential = "";
    proposal.relatedFeatureId = WHATSAPP_REPLY_ASSISTANT_FEATURE_ID;
  }

  if (proposal.type === "scheduled-message" && proposal.missingCredential) {
    const message = `${proposal.missingCredential} setup is required before I can finish this.`;
    pushAgentProposalResult(proposal.id, message, "credential");
    persistAgentWorkspace(message);
    openAgentProposalSetup(proposal.id);
    renderApp({ preserveStatus: true });
    return;
  }

  if (proposal.type === "whatsapp-replies" && proposal.missingCredential) {
    proposal.status = "needs-approval";
    pushAgentWhatsAppSetupPrompt();
    persistAgentWorkspace("WhatsApp setup is required before I can start this.");
    renderApp({ preserveStatus: true });
    return;
  }

  let scheduledAction = null;
  let monitorActivation = null;
  let whatsappActivation = null;
  if (proposal.type === "scheduled-message" && !proposal.missingCredential) {
    proposal.status = "scheduling";
    persistAgentWorkspace("Scheduling message...");
    renderApp({ preserveStatus: true });
    try {
      const response = await scheduleAgentScheduledMessageProposal(proposal);
      scheduledAction = response.action || null;
      proposal.executionPlan = {
        ...proposal.executionPlan,
        backendActionId: scheduledAction?.id || "",
        backendStatus: scheduledAction?.status || "",
      };
      if (scheduledAction?.id) {
        const normalizedAction = normalizeScheduledAction(scheduledAction);
        state.scheduledActions = [
          normalizedAction,
          ...state.scheduledActions.filter((action) => action.id !== normalizedAction.id),
        ];
        markScheduledActionsRefreshSuccess();
        renderAgentActions();
      }
    } catch (error) {
      proposal.status = "needs-approval";
      const payload = error?.payload || {};
      let statusMessage = "Scheduling failed.";
      if (payload.error === "missing_whatsapp_connection") {
        proposal.missingCredential = "WhatsApp Business API access token";
        statusMessage = "WhatsApp setup required.";
        openAgentProposalSetup(proposal.id);
      } else {
        statusMessage = formatApiErrorMessage(error, "I could not schedule that message yet.");
      }
      pushAgentProposalResult(proposal.id, statusMessage, payload.error === "missing_whatsapp_connection" ? "credential" : "result");
      persistAgentWorkspace(statusMessage);
      renderApp({ preserveStatus: true });
      return;
    }
  }

  if (proposal.type === "web-monitor") {
    proposal.status = "activating";
    persistAgentWorkspace("Activating web monitor...");
    renderApp({ preserveStatus: true });
    try {
      monitorActivation = await saveAndActivateAgentWebMonitorProposal(proposal);
    } catch (error) {
      handleAgentWebMonitorActivationError(error, proposal);
      return;
    }
  }

  if (proposal.type === "whatsapp-replies") {
    proposal.status = "activating";
    persistAgentWorkspace("Starting WhatsApp reply assistant...");
    renderApp({ preserveStatus: true });
    try {
      whatsappActivation = await saveAndActivateAgentWhatsAppProposal(proposal);
    } catch (error) {
      handleAgentWhatsAppActivationError(error, proposal);
      return;
    }
  }

  proposal.approved = true;
  proposal.status = "approved";
  proposal.approvedAt = new Date().toISOString();
  for (const helper of proposal.helpers) {
    const existingHelper = agent.helpers.find((candidate) => (
      candidate.sourceProposalId === proposal.id
      && candidate.name.toLowerCase() === helper.name.toLowerCase()
    ));
    if (existingHelper) {
      existingHelper.status = proposal.missingCredential ? "Needs setup" : "Working";
      continue;
    }

    agent.helpers.push(normalizeAgentHelper({
      id: createAgentId("agent-helper"),
      name: helper.name,
      purpose: helper.purpose,
      status: proposal.missingCredential ? "Needs setup" : "Working",
      sourceProposalId: proposal.id,
      createdAt: new Date().toISOString(),
    }));
  }

  if (proposal.missingCredential) {
    const message = `${proposal.missingCredential} setup is required before I can finish this.`;
    pushAgentProposalResult(proposal.id, message, "credential");
    persistAgentWorkspace(message);
    openAgentProposalSetup(proposal.id);
  } else if (proposal.type === "scheduled-message") {
    const message = "Scheduled message created.";
    pushAgentProposalResult(proposal.id, message);
    persistAgentWorkspace(message);
  } else if (proposal.type === "web-monitor") {
    const runMessage = monitorActivation?.initialRun?.message || "";
    const runError = monitorActivation?.initialRunError || "";
    const message = runMessage || runError || "Web monitor activated.";
    pushAgentProposalResult(proposal.id, message);
    persistAgentWorkspace(message);
  } else if (proposal.type === "whatsapp-replies") {
    const deliveryChannel = formatAgentScheduledMessageChannel(
      getAgentProposalDeliveryChannel(proposal) || whatsappActivation?.settings?.deliveryChannels?.[0] || "portal",
    );
    const message = deliveryChannel === "this workspace"
      ? "WhatsApp reply assistant is active. New drafts will appear here for review."
      : `WhatsApp reply assistant is active. New drafts will be brought to you by ${deliveryChannel}.`;
    pushAgentProposalResult(proposal.id, message);
    persistAgentWorkspace(message);
  } else {
    const message = "Agent helper created.";
    pushAgentProposalResult(proposal.id, message);
    persistAgentWorkspace(message);
  }
  renderApp({ preserveStatus: true });
}

function requestAgentProposalChanges(proposalId, expectedRevision = 0) {
  const agent = getAgentWorkspace();
  const proposal = agent.proposals.find((candidate) => candidate.id === proposalId);
  if (!proposal || proposal.approved || proposal.status === "revising") {
    return;
  }

  const currentRevision = Math.max(1, Number(proposal.revision || 1));
  if (expectedRevision > 0 && expectedRevision !== currentRevision) {
    persistAgentWorkspace("That plan has already changed. Review the latest version before editing.");
    renderApp({ preserveStatus: true });
    return;
  }

  agent.activeProposalId = proposal.id;
  persistAgentWorkspace("Tell Assistyca what you want to change.");
  renderApp({ preserveStatus: true });
  elements.agentComposerInput?.focus();
}

function openAgentProposalSetup(proposalId) {
  const proposal = getAgentWorkspace().proposals.find((candidate) => candidate.id === proposalId);
  if (!proposal?.relatedFeatureId) {
    persistAgentWorkspace("This plan needs a custom setup path.");
    renderApp({ preserveStatus: true });
    elements.agentComposerInput?.focus();
    return;
  }

  const feature = getFeatureById(proposal.relatedFeatureId);
  if (!feature) {
    return;
  }

  const view = isWhatsAppFeature(feature) && !isFeatureSetupComplete(feature)
    ? "activation"
    : getDefaultFeatureStudioView(feature);
  openFeatureStudio(feature.id, view);
}

function openAgentCredentialHelp(proposalId) {
  const proposal = getAgentWorkspace().proposals.find((candidate) => candidate.id === proposalId);
  const credential = proposal?.missingCredential || "API credentials";
  if (elements.agentComposerInput) {
    elements.agentComposerInput.placeholder = `Ask Assistyca about ${credential}`;
  }
  persistAgentWorkspace(`Ask Assistyca about ${credential}.`);
  renderApp({ preserveStatus: true });
  elements.agentComposerInput?.focus();
}

function getAgentProposalIdFromLocalActionId(actionId) {
  return String(actionId || "").replace(/^proposal:/, "").trim();
}

function getAgentFeatureIdFromLocalActionId(actionId) {
  const text = String(actionId || "").trim();
  return text.startsWith("feature:") ? text.replace(/^feature:/, "").trim() : "";
}

async function deactivateAgentBackendFeature(backendFeatureId) {
  const featureId = String(backendFeatureId || "").trim();
  if (!featureId) {
    return null;
  }

  const feature = getFeatureById(featureId);
  if (!feature || !isFeatureActivated(feature)) {
    return null;
  }

  const response = await apiRequest(`/api/features/${encodeURIComponent(featureId)}/activation`, {
    method: "POST",
    headers: getSessionAuthHeaders(),
    body: {
      action: "deactivate",
      featureName: feature.name,
      channel: feature.channel,
    },
  });
  applyServerFeatureStates([response.feature || {}], { persist: true });
  state.paymentStatus = response.paymentStatus || state.paymentStatus;
  return response;
}

async function deactivateAgentProposalBackendFeature(proposal) {
  const backendFeatureId = String(proposal?.executionPlan?.backendFeatureId || "").trim();
  if (!backendFeatureId) {
    return null;
  }

  return deactivateAgentBackendFeature(backendFeatureId);
}

async function removeAgentProposalLocalAction(actionId) {
  const featureId = getAgentFeatureIdFromLocalActionId(actionId);
  if (featureId) {
    const feature = getFeatureById(featureId);
    if (!feature || !isFeatureActivated(feature)) {
      return false;
    }

    persistAgentWorkspace("Turning off action...");
    renderApp({ preserveStatus: true });
    try {
      await deactivateAgentBackendFeature(featureId);
    } catch (error) {
      persistAgentWorkspace(formatApiErrorMessage(error, "Couldn’t turn off that action."));
      renderApp({ preserveStatus: true });
      return false;
    }

    state.selectedScheduledActionId = "";
    persistAgentWorkspace("Action turned off.");
    renderApp({ preserveStatus: true });
    return true;
  }

  const proposalId = getAgentProposalIdFromLocalActionId(actionId);
  if (!proposalId) {
    return false;
  }

  const proposal = getAgentWorkspace().proposals.find((candidate) => candidate.id === proposalId);
  if (!proposal || !proposal.approved || proposal.type === "scheduled-message") {
    return false;
  }

  persistAgentWorkspace("Turning off action...");
  renderApp({ preserveStatus: true });
  try {
    await deactivateAgentProposalBackendFeature(proposal);
  } catch (error) {
    persistAgentWorkspace(formatApiErrorMessage(error, "Couldn’t turn off that action."));
    renderApp({ preserveStatus: true });
    return false;
  }

  const agent = getAgentWorkspace();
  agent.proposals = agent.proposals.filter((candidate) => candidate.id !== proposalId);
  agent.helpers = agent.helpers.filter((helper) => helper.sourceProposalId !== proposalId);
  if (agent.activeProposalId === proposalId) {
    agent.activeProposalId = agent.proposals[agent.proposals.length - 1]?.id || "";
  }
  state.selectedScheduledActionId = "";
  persistAgentWorkspace("Action removed.");
  renderApp({ preserveStatus: true });
  return true;
}

async function cancelScheduledAction(actionId) {
  const id = Math.max(0, Number(actionId || 0));
  if (!id) {
    return false;
  }

  persistAgentWorkspace("Cancelling action...");
  renderApp({ preserveStatus: true });

  try {
    const response = await apiRequest(`/api/scheduled-actions/${encodeURIComponent(String(id))}`, {
      method: "DELETE",
      headers: getSessionAuthHeaders(),
    });
    if (response.action) {
      const normalizedAction = normalizeScheduledAction(response.action);
      state.scheduledActions = [
        normalizedAction,
        ...state.scheduledActions.filter((action) => action.id !== normalizedAction.id),
      ];
      state.selectedScheduledActionId = String(normalizedAction.id || "");
    } else {
      state.scheduledActions = state.scheduledActions.filter((action) => action.id !== id);
      state.selectedScheduledActionId = "";
    }
    markScheduledActionsRefreshSuccess();
    persistAgentWorkspace("Action cancelled.");
    renderApp({ preserveStatus: true });
    return true;
  } catch (error) {
    persistAgentWorkspace(formatApiErrorMessage(error, "Couldn’t cancel that action."));
    renderApp({ preserveStatus: true });
    return false;
  }
}

function handleAgentWorkspaceClick(event) {
  const whatsappApprovalButton = getEventTargetElement(event)?.closest("[data-agent-whatsapp-action]");
  if (whatsappApprovalButton) {
    void handleAgentWhatsAppApprovalAction(whatsappApprovalButton);
    return;
  }

  if (handleAgentMessageAction(event)) {
    return;
  }

  const target = getEventTargetElement(event);
  const removeLocalActionButton = target?.closest("[data-agent-remove-local-action]");
  if (removeLocalActionButton) {
    event.preventDefault();
    event.stopPropagation();
    void removeAgentProposalLocalAction(removeLocalActionButton.dataset.agentRemoveLocalAction || "");
    return;
  }

  const cancelScheduledActionButton = target?.closest("[data-agent-cancel-scheduled-action]");
  if (cancelScheduledActionButton) {
    event.preventDefault();
    event.stopPropagation();
    void cancelScheduledAction(cancelScheduledActionButton.dataset.agentCancelScheduledAction || "");
    return;
  }

  const runMonitorActionButton = target?.closest("[data-agent-run-monitor-action]");
  if (runMonitorActionButton) {
    event.preventDefault();
    event.stopPropagation();
    void runMonitorActionNow(runMonitorActionButton.dataset.agentRunMonitorAction || "");
    return;
  }

  const scheduledActionItem = target?.closest("[data-agent-scheduled-action-id]");
  const scheduledActionId = scheduledActionItem?.dataset.agentScheduledActionId || "";
  const isActionControl = target?.closest("button, input, select, textarea, a, [contenteditable=\"true\"], [role=\"button\"], [role=\"combobox\"]");
  if (
    scheduledActionItem
    && scheduledActionId
    && state.selectedScheduledActionId === scheduledActionId
    && !isActionControl
  ) {
    event.preventDefault();
    event.stopPropagation();
    selectScheduledAction(scheduledActionId);
    return;
  }

  const scheduledActionTrigger = target?.closest("[data-agent-scheduled-action-trigger]");
  if (scheduledActionTrigger) {
    event.preventDefault();
    event.stopPropagation();
    selectScheduledAction(scheduledActionTrigger.dataset.agentScheduledActionTrigger || "");
    return;
  }

  const addToolButton = target?.closest("[data-agent-add-tool]");
  if (addToolButton) {
    event.preventDefault();
    event.stopPropagation();
    const option = getAgentAddToolOption(addToolButton.dataset.agentAddTool || "");
    if (option) {
      setAgentAddToolMenuOpen(false);
      if (option.platformId) {
        openPlatformConnection(option.platformId);
      } else if (option.prompt) {
        void handleAgentUserText(option.prompt);
      }
    }
    return;
  }

  const platformConnectionButton = target?.closest("[data-agent-platform-connection]");
  if (platformConnectionButton) {
    event.preventDefault();
    event.stopPropagation();
    openPlatformConnection(platformConnectionButton.dataset.agentPlatformConnection || "");
    return;
  }

  const toolButton = target?.closest("[data-agent-tool-feature-id]");
  if (toolButton) {
    event.preventDefault();
    event.stopPropagation();
    openAgentToolDetails(toolButton.dataset.agentToolFeatureId || "");
    return;
  }

  const approveButton = target?.closest("[data-agent-approve-proposal]");
  if (approveButton) {
    const proposalId = approveButton.dataset.agentApproveProposal || "";
    pushAgentActionIntentMessage("approve-proposal", "Set it up", proposalId);
    persistClientState();
    renderAgentMessages();
    startAgentProposalApproval(proposalId);
    return;
  }

  const setupButton = target?.closest("[data-agent-open-setup]");
  if (setupButton) {
    openAgentProposalSetup(setupButton.dataset.agentOpenSetup || "");
    return;
  }

  const changesButton = target?.closest("[data-agent-request-changes]");
  if (changesButton) {
    const proposalId = changesButton.dataset.agentRequestChanges || "";
    pushAgentActionIntentMessage("request-change", "Change something", proposalId);
    persistClientState();
    renderAgentMessages();
    requestAgentProposalChanges(proposalId);
    return;
  }

  const helpButton = target?.closest("[data-agent-credential-help]");
  if (helpButton) {
    openAgentCredentialHelp(helpButton.dataset.agentCredentialHelp || "");
  }
}

function setAgentToolsOpen(open) {
  const isOpen = Boolean(open);
  elements.agentToolsPanel?.classList.toggle("is-open", isOpen);
  elements.agentToolsToggleButton?.setAttribute("aria-expanded", String(isOpen));
  if (elements.agentToolsToggleButton) {
    const upcomingCount = getRenderableAgentActions().filter((action) => isActiveAgentActionStatus(action.status)).length;
    elements.agentToolsToggleButton.textContent = isOpen
      ? "Close actions"
      : (upcomingCount ? `Actions (${upcomingCount})` : "View actions");
  }
}

function createFeatureCard(feature) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "glass-card feature-card feature-card-button";
  card.setAttribute("aria-label", `Open ${feature.name}`);
  card.addEventListener("click", () => openFeatureStudio(feature.id));

  const status = document.createElement("span");
  status.className = "feature-status feature-card-status";
  applyFeatureActivationBadgeStyle(status, feature);
  status.textContent = getFeatureActivationLabel(feature);

  const head = document.createElement("div");
  head.className = "feature-card-head";

  const titleBlock = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = feature.name;

  titleBlock.append(title);
  head.append(titleBlock);

  const description = document.createElement("p");
  description.className = "feature-card-copy";
  description.textContent = feature.description || "";

  card.append(status, head, description);
  return card;
}

function getAgentToolLabel(feature) {
  if (isWhatsAppFeature(feature)) {
    return "WhatsApp";
  }
  if (isMonitorFeature(feature)) {
    return "Web monitoring";
  }
  if (isReengagementFeature(feature)) {
    return "Customer follow-up";
  }
  return feature?.name || "Tool";
}

function getAgentToolDetailsView(feature) {
  if (canOpenFeatureWhatsAppDetails(feature)) {
    return "activation";
  }
  return getDefaultFeatureStudioView(feature);
}

function openAgentToolDetails(featureId) {
  const feature = getFeatureById(featureId);
  if (!feature) {
    return;
  }

  state.agentAddToolMenuOpen = false;
  openFeatureStudio(feature.id, getAgentToolDetailsView(feature));
  setStatus(isWhatsAppFeature(feature) ? "WhatsApp details opened." : `${getAgentToolLabel(feature)} details opened.`);
}

function getAgentAddToolOption(id) {
  return AGENT_ADD_TOOL_OPTIONS.find((option) => option.id === id) || null;
}

function setAgentAddToolMenuOpen(open) {
  const nextOpen = Boolean(open);
  if (agentAddToolMenuOpenFrame !== null) {
    window.cancelAnimationFrame(agentAddToolMenuOpenFrame);
    agentAddToolMenuOpenFrame = null;
  }
  if (agentAddToolMenuCloseTimer !== null) {
    window.clearTimeout(agentAddToolMenuCloseTimer);
    agentAddToolMenuCloseTimer = null;
  }
  state.agentAddToolMenuOpen = nextOpen;
  state.agentAddToolMenuClosing = !nextOpen && (
    !elements.agentAddToolMenu?.hidden
    || !elements.agentAddToolBackdrop?.hidden
  );
  renderAgentAddToolMenu();
}

function createSvgElement(tagName, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  return element;
}

function createAgentAddToolLogo(option) {
  const iconType = String(option?.icon || option?.id || "").trim().toLowerCase();
  const svg = createSvgElement("svg", {
    viewBox: "0 0 24 24",
    width: "18",
    height: "18",
    fill: "none",
    "aria-hidden": "true",
    focusable: "false",
  });

  if (iconType === "email") {
    svg.append(
      createSvgElement("rect", {
        x: "3.5",
        y: "5.5",
        width: "17",
        height: "13",
        rx: "3.2",
        stroke: "currentColor",
        "stroke-width": "2",
      }),
      createSvgElement("path", {
        d: "M5 8l7 5.2L19 8",
        stroke: "currentColor",
        "stroke-width": "2",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      }),
    );
    return svg;
  }

  if (iconType === "calendar") {
    svg.append(
      createSvgElement("rect", {
        x: "4",
        y: "5.5",
        width: "16",
        height: "15",
        rx: "3",
        stroke: "currentColor",
        "stroke-width": "2",
      }),
      createSvgElement("path", {
        d: "M8 3.5v4M16 3.5v4M4.8 10h14.4M8 14h2.8M13.2 14H16M8 17h2.8",
        stroke: "currentColor",
        "stroke-width": "2",
        "stroke-linecap": "round",
      }),
    );
    return svg;
  }

  if (iconType === "telegram") {
    svg.append(
      createSvgElement("path", {
        d: "M20.3 4.8 3.9 11.1c-1.1.4-1.1 1.1-.2 1.4l4.2 1.3 1.6 5c.2.6.5.8 1 .8.5 0 .8-.2 1.2-.6l2.3-2.2 4.8 3.5c.9.5 1.5.3 1.7-.8l3-14c.3-1.2-.5-1.8-1.2-1.5Z",
        fill: "currentColor",
        transform: "translate(-1.6 -.4) scale(1.08)",
      }),
      createSvgElement("path", {
        d: "m8.3 13.5 8.5-5.3-6.6 6.8-.2 3",
        stroke: "rgba(255,255,255,0.72)",
        "stroke-width": "1.35",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      }),
    );
    return svg;
  }

  if (iconType === "slack") {
    svg.append(
      createSvgElement("path", {
        d: "M8.1 3.3a2 2 0 1 0 0 4h1.2V3.3a2 2 0 0 0-1.2 0Zm-4.8 4.8a2 2 0 1 0 4 0V6.9H3.3a2 2 0 0 0 0 1.2Zm4.8 4.8a2 2 0 1 0 0-4H6.9v4.8a2 2 0 0 0 1.2 0Zm4.8-4.8a2 2 0 1 0-4 0v1.2h4.8a2 2 0 0 0 0-1.2Zm-1.8 8.6a2 2 0 1 0 0-4H9.9v4.8a2 2 0 0 0 1.2 0Zm4.8-4.8a2 2 0 1 0-4 0v1.2h4.8a2 2 0 0 0 0-1.2Zm-4.8 4.8a2 2 0 1 0 0-4H9.9v4.8a2 2 0 0 0 1.2 0Zm4.8-4.8a2 2 0 1 0-4 0v1.2h4.8a2 2 0 0 0 0-1.2Z",
        fill: "currentColor",
      }),
    );
    return svg;
  }

  svg.append(
    createSvgElement("path", {
      d: "M12 5v14M5 12h14",
      stroke: "currentColor",
      "stroke-width": "2.4",
      "stroke-linecap": "round",
    }),
  );
  return svg;
}

function createAgentAddToolOption(option) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "agent-add-tool-option";
  item.dataset.agentAddTool = option.id;
  item.setAttribute("role", "menuitem");

  const icon = document.createElement("span");
  icon.className = "agent-add-tool-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.append(createAgentAddToolLogo(option));

  const copy = document.createElement("span");
  copy.className = "agent-tool-copy";
  const label = document.createElement("strong");
  label.textContent = option.label;
  const detail = document.createElement("span");
  detail.textContent = option.detail;
  copy.append(label, detail);

  item.append(icon, copy);
  return item;
}

function renderAgentAddToolMenu() {
  if (!elements.agentAddToolButton || !elements.agentAddToolMenu) {
    return;
  }

  const isOpen = Boolean(state.agentAddToolMenuOpen);
  const isClosing = Boolean(state.agentAddToolMenuClosing) && !isOpen;
  const isVisible = isOpen || isClosing;
  elements.agentAddToolButton.setAttribute("aria-expanded", String(isOpen));
  elements.appView?.classList.toggle("agent-tool-picker-background-blurred", isVisible);
  elements.agentAddToolMenu.hidden = !isVisible;
  elements.agentAddToolMenu.classList.toggle("is-hidden", !isVisible);
  elements.agentAddToolMenu.classList.toggle("is-closing", isClosing);
  if (elements.agentAddToolBackdrop) {
    elements.agentAddToolBackdrop.hidden = !isVisible;
    elements.agentAddToolBackdrop.classList.toggle("is-hidden", !isVisible);
    elements.agentAddToolBackdrop.classList.toggle("is-closing", isClosing);
  }

  if (!isVisible) {
    elements.agentAddToolMenu.classList.remove("is-open");
    elements.agentAddToolBackdrop?.classList.remove("is-open");
    return;
  }

  if (isOpen) {
    elements.agentAddToolMenu.classList.remove("is-closing");
    elements.agentAddToolBackdrop?.classList.remove("is-closing");
    elements.agentAddToolMenu.replaceChildren(...AGENT_ADD_TOOL_OPTIONS.map(createAgentAddToolOption));
    if (!elements.agentAddToolMenu.classList.contains("is-open") && agentAddToolMenuOpenFrame === null) {
      agentAddToolMenuOpenFrame = window.requestAnimationFrame(() => {
        if (state.agentAddToolMenuOpen) {
          elements.agentAddToolMenu.classList.add("is-open");
          elements.agentAddToolBackdrop?.classList.add("is-open");
        }
        agentAddToolMenuOpenFrame = null;
      });
    }
    return;
  }

  elements.agentAddToolMenu.classList.remove("is-open");
  elements.agentAddToolBackdrop?.classList.remove("is-open");
  if (agentAddToolMenuCloseTimer === null) {
    agentAddToolMenuCloseTimer = window.setTimeout(() => {
      state.agentAddToolMenuClosing = false;
      agentAddToolMenuCloseTimer = null;
      renderAgentAddToolMenu();
    }, 190);
  }
}

function createAgentToolItem(feature) {
  const item = document.createElement("button");
  const label = getAgentToolLabel(feature);
  const isConnected = isFeatureSetupComplete(feature);
  const needsWhatsAppDetails = isWhatsAppFeature(feature) && !isConnected;
  item.type = "button";
  item.className = "agent-tool-item";
  item.dataset.agentToolFeatureId = feature.id;
  item.setAttribute(
    "aria-label",
    isConnected
      ? `Open ${label} details`
      : (needsWhatsAppDetails ? `Finish ${label} setup` : `Open ${label} setup`),
  );

  const icon = document.createElement("span");
  icon.className = "agent-tool-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = label.slice(0, 1).toUpperCase();

  const copy = document.createElement("span");
  copy.className = "agent-tool-copy";
  const title = document.createElement("strong");
  title.textContent = label;
  const detail = document.createElement("span");
  detail.textContent = isConnected
    ? "Connected"
    : (needsWhatsAppDetails ? "Needs details" : "Available");
  copy.append(title, detail);

  const arrow = document.createElement("span");
  arrow.className = "agent-tool-arrow";
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "→";

  item.append(icon, copy, arrow);
  return item;
}

function createAgentPlatformConnectionItem(connection) {
  const item = document.createElement("button");
  const label = connection.label || "Connected app";
  item.type = "button";
  item.className = "agent-tool-item agent-platform-connection-item";
  item.dataset.agentPlatformConnection = connection.platform;
  item.setAttribute("aria-label", `Replace ${label} connection`);

  const icon = document.createElement("span");
  icon.className = "agent-tool-icon agent-platform-connection-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = label.slice(0, 1).toUpperCase();

  const copy = document.createElement("span");
  copy.className = "agent-tool-copy";
  const title = document.createElement("strong");
  title.textContent = label;
  const detail = document.createElement("span");
  detail.textContent = connection.secretHint ? `Connected ${connection.secretHint}` : "Connected";
  copy.append(title, detail);

  const arrow = document.createElement("span");
  arrow.className = "agent-tool-arrow";
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "→";
  item.append(icon, copy, arrow);
  return item;
}

function updateFeatureList() {
  const features = clientState.features.length ? clientState.features : [];
  const connections = Array.isArray(state.platformConnections) ? state.platformConnections : [];
  const target = elements.agentToolShelf || elements.featureList;
  renderAgentAddToolMenu();
  if (!target) {
    return;
  }

  if (!features.length && !connections.length) {
    const emptyState = document.createElement("p");
    emptyState.className = "agent-tools-empty";

    emptyState.textContent = "No tools are available yet.";
    target.replaceChildren(emptyState);
    return;
  }

  const visibleFeatures = [];
  const seenLabels = new Set();
  for (const feature of features) {
    const label = getAgentToolLabel(feature);
    if (seenLabels.has(label)) {
      continue;
    }
    seenLabels.add(label);
    visibleFeatures.push(feature);
  }

  target.replaceChildren(
    ...visibleFeatures.map((feature) => createAgentToolItem(feature)),
    ...connections.map((connection) => createAgentPlatformConnectionItem(connection)),
  );
}

function createOpportunityMetric(label, value, detail = "") {
  const metric = document.createElement("article");
  metric.className = "opportunity-metric";

  const labelElement = document.createElement("span");
  labelElement.textContent = label;

  const valueElement = document.createElement("strong");
  valueElement.textContent = value;

  metric.append(labelElement, valueElement);
  if (detail) {
    const detailElement = document.createElement("small");
    detailElement.textContent = detail;
    metric.append(detailElement);
  }

  return metric;
}

function createOpportunityField(label, value) {
  const field = document.createElement("div");
  field.className = "opportunity-field";

  const labelElement = document.createElement("span");
  labelElement.textContent = label;

  const valueElement = document.createElement("p");
  valueElement.textContent = value || "Not captured";

  field.append(labelElement, valueElement);
  return field;
}

function createOpportunityCard(opportunity) {
  const card = document.createElement("article");
  card.className = "opportunity-card";

  const tone = getOpportunityUrgencyTone(opportunity);
  const header = document.createElement("div");
  header.className = "opportunity-card-head";

  const titleBlock = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = opportunity.business || opportunity.name || "Website opportunity";

  const meta = document.createElement("p");
  const contact = [opportunity.email, opportunity.phone].filter(Boolean).join(" · ");
  const metaParts = [
    formatAdminDateTime(opportunity.createdAt) || "Unknown date",
    opportunity.name,
    contact,
    opportunity.requestCountry,
  ].filter(Boolean);
  meta.textContent = metaParts.join(" · ");
  titleBlock.append(title, meta);

  const badge = document.createElement("span");
  badge.className = `opportunity-urgency is-${tone}`;
  badge.textContent = `${opportunity.urgency || "Urgency"} · ${opportunity.urgencyScore}`;

  header.append(titleBlock, badge);

  const details = document.createElement("div");
  details.className = "opportunity-fields";
  details.append(
    createOpportunityField("Business summary", opportunity.businessSummary),
    createOpportunityField("Pain summary", opportunity.painSummary),
    createOpportunityField("Suggested tool", opportunity.suggestedTool),
    createOpportunityField("Difficulty", opportunity.difficulty),
  );

  card.append(header, details);
  if (opportunity.sourcePage) {
    const source = document.createElement("a");
    source.className = "opportunity-source";
    source.href = opportunity.sourcePage;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = "Source page";
    card.append(source);
  }

  return card;
}

function updateOpportunityNavigation() {
  const allowed = canReviewOpportunities();
  for (const button of elements.tabButtons) {
    if (button.dataset.tab === "opportunities") {
      button.hidden = !allowed;
    }
  }

  if (!allowed && state.activeTab === "opportunities") {
    state.activeTab = "features";
    state.lastPrimaryTab = "features";
    persistLastPrimaryTab();
    setHashForTab("features");
  }
}

function updateClientNavigation() {
  const allowed = canManageClients();
  for (const button of elements.tabButtons) {
    if (button.dataset.tab === "clients") {
      button.hidden = !allowed;
    }
  }

  if (!allowed && state.activeTab === "clients") {
    state.activeTab = "features";
    state.lastPrimaryTab = "features";
    state.adminView = "list";
    state.adminSelectedUserEmail = "";
    persistLastPrimaryTab();
    setHashForTab("features");
  }
}

function updateOpportunitiesPanel() {
  if (!elements.opportunitiesPanel || !elements.opportunitiesSummary || !elements.opportunitiesList) {
    return;
  }

  if (elements.opportunitiesRefreshButton) {
    elements.opportunitiesRefreshButton.disabled = state.opportunitiesLoading || !canReviewOpportunities();
    elements.opportunitiesRefreshButton.textContent = state.opportunitiesLoading ? "Refreshing" : "Refresh";
  }

  if (!canReviewOpportunities()) {
    elements.opportunitiesSummary.replaceChildren();
    elements.opportunitiesList.replaceChildren();
    return;
  }

  const stats = getOpportunityStats();
  const loadedLabel = state.opportunitiesLoadedAt
    ? `Updated ${formatAdminDateTime(new Date(state.opportunitiesLoadedAt).toISOString())}`
    : "Not loaded yet";
  elements.opportunitiesSummary.replaceChildren(
    createOpportunityMetric("Open leads", String(stats.total), loadedLabel),
    createOpportunityMetric("High urgency", String(stats.highUrgency), "Score 60+"),
    createOpportunityMetric("Average urgency", String(stats.averageUrgency), "0 to 100"),
    createOpportunityMetric("Hard work", String(stats.hardestCount), "High difficulty"),
  );

  if (state.opportunitiesLoading && !state.opportunities.length) {
    const loading = document.createElement("article");
    loading.className = "glass-card empty-state opportunity-empty";
    const title = document.createElement("h3");
    title.textContent = "Loading opportunities";
    const copy = document.createElement("p");
    copy.textContent = "Fetching the latest completed intake conversations.";
    loading.append(title, copy);
    elements.opportunitiesList.replaceChildren(loading);
    return;
  }

  if (state.opportunitiesError) {
    const error = document.createElement("article");
    error.className = "glass-card empty-state opportunity-empty is-warn";
    const title = document.createElement("h3");
    title.textContent = "Couldn’t load opportunities";
    const copy = document.createElement("p");
    copy.textContent = state.opportunitiesError;
    error.append(title, copy);
    elements.opportunitiesList.replaceChildren(error);
    return;
  }

  if (!state.opportunities.length) {
    const empty = document.createElement("article");
    empty.className = "glass-card empty-state opportunity-empty";
    const title = document.createElement("h3");
    title.textContent = "No opportunities yet";
    const copy = document.createElement("p");
    copy.textContent = "Completed website conversations will appear here after the visitor leaves contact details.";
    empty.append(title, copy);
    elements.opportunitiesList.replaceChildren(empty);
    return;
  }

  elements.opportunitiesList.replaceChildren(...state.opportunities.map((opportunity) => createOpportunityCard(opportunity)));
}

function setFeatureStudioView(view, options = {}) {
  const nextView = normalizeFeatureStudioView(view) || getDefaultFeatureStudioView();
  state.featureStudioView = nextView;

  if (options.syncHash !== false && state.selectedFeatureId) {
    setHashForTab("features", state.selectedFeatureId, state.featureStudioView);
  }

  closeFeatureStudioMenu();
  renderApp();
  if (options.scroll !== false) {
    window.scrollTo(0, 0);
  }
}

function openFeatureStudio(featureId, view = null) {
  const feature = getFeatureById(featureId) || clientState.features[0];

  if (!feature) {
    return;
  }

  state.selectedFeatureId = feature.id;
  state.activeTab = "features";
  state.settingsOpen = false;
  state.featureStudioView = normalizeFeatureStudioView(view) || getDefaultFeatureStudioView(feature);
  closeMenu();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, state.featureStudioView);
  renderApp();
  window.scrollTo(0, 0);

  if (isSignedIn() && isMonitorFeature(feature)) {
    void refreshFeatureActivationStates().catch(() => {});
  }
}

function closeFeatureStudio() {
  state.selectedFeatureId = null;
  state.featureStudioView = "overview";
  state.activeTab = "features";
  state.lastPrimaryTab = "features";
  persistLastPrimaryTab();
  closeMenu();
  closeFeatureStudioMenu();
  setHashForTab("features");
  renderApp();
  window.scrollTo(0, 0);
}

function closeFeatureStudioMenu() {
  // No-op: the former feature options menu now lives in the action strip.
}

async function activateSelectedFeature() {
  if (featureActivationBusy) {
    return;
  }

  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }
  const editingActiveFeature = isFeatureActivated(feature);
  if (!hasFeatureActivationChanges(feature)) {
    updateFeatureStudioHeader();
    setStatus("No changes to save.");
    return;
  }

  const issues = getFeatureActivationTestIssues(feature);
  if (issues.length) {
    setFeatureActivationFieldErrors(issues);
    updateFeatureStudioHeader();
    setStatus("Finish the missing details.");
    const firstIssue = issues[0];
    const focusTarget = getFeatureActivationFieldElement(firstIssue.field);
    window.requestAnimationFrame(() => {
      focusTarget?.focus();
    });
    return;
  }

  featureActivationBusy = true;
  state.featureActivationNotice = "";
  try {
    updateFeatureStudioHeader();
    setStatus(editingActiveFeature ? "Saving details..." : "Saving setup...");
    const whatsapp = getSelectedFeatureWhatsApp(feature);
    const accessToken = normalizePendingAccessToken(whatsapp.access_token);
    const response = await apiRequest("/api/whatsapp/connection", {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        business_account_id: whatsapp.business_account_id,
        phone_number_id: whatsapp.phone_number_id,
        ...(accessToken ? { access_token: accessToken } : {}),
        owner_wa_id: whatsapp.owner_wa_id,
      },
    });

    applyWhatsAppConnectionToFeatures(response.connection || whatsapp, { persist: false });
    if (elements.featureActivationAccessTokenInput) {
      elements.featureActivationAccessTokenInput.value = getAccessTokenDisplayValue(
        normalizeFeatureWhatsApp(response.connection || whatsapp),
      );
    }
    if (usesEditorSetup(feature)) {
      await refreshFeatureActivationStates({ render: false });
    }
    const savedFeature = getSelectedFeature();
    if (savedFeature) {
      savedFeature.status = getFeatureActivationState(savedFeature);
    }
    state.featureActivationNotice = String(response.message || "").trim();
    clearFeatureActivationFieldErrors();
    persistClientState();
    closeFeatureStudioMenu();
    const readyFeature = getSelectedFeature();
    const liveReady = Boolean(
      readyFeature
      && (isFeatureSetupComplete(readyFeature) || readyFeature.setupStatus?.ready),
    );

    if (!liveReady) {
      state.featureStudioView = "activation";
      setHashForTab("features", feature.id, "activation");
      renderApp();
      window.scrollTo(0, 0);
      openFeatureActivationAlert(
        "One thing left",
        response.message || "WhatsApp details were saved, but this client number still needs its own access token before this tool can go live.",
        {
          eyebrow: "Almost there",
          returnFocus: elements.featureStudioActivationButton,
        },
      );
      setStatus("Setup saved, but the live WhatsApp connection still needs this client's access token.");
      return;
    }

    clearFeatureActivationNotice();
    if (editingActiveFeature) {
      state.featureStudioView = "activation";
      setHashForTab("features", feature.id, "activation");
      renderApp();
      window.scrollTo(0, 0);
      setStatus("WhatsApp details saved.");
      return;
    }

    state.featureStudioView = "editor";
    setHashForTab("features", feature.id, "editor");
    renderApp();
    window.scrollTo(0, 0);
    openAuthAlert(
      "Setup succeeded",
      usesEditorSetup(feature)
        ? "Your WhatsApp delivery setup was saved. Head back to the editor and finish activating this tool when you're ready."
        : "Your WhatsApp setup succeeded. This feature is now ready to be activated. Before turning it on, review the tool editor and make sure everything is set up to your taste.",
      {
        eyebrow: "Nice work",
        buttonLabel: "Open tool editor",
        icon: "✓",
        tone: "success",
        returnFocus: elements.featureStudioEditorToggleButton,
      },
    );
    setStatus(
      usesEditorSetup(feature)
        ? "WhatsApp setup saved. Return to the editor when you're ready."
        : "Setup saved. Review the tool editor before activating.",
    );
  } catch (error) {
    const payload = error?.payload || {};
    if (Array.isArray(payload.issues) && payload.issues.length) {
      setFeatureActivationFieldErrors(payload.issues);
    }
    const message = formatApiErrorMessage(error, "WhatsApp setup could not be confirmed.");
    state.featureActivationNotice = "Setup failed";
    updateFeatureStudioHeader();
    openFeatureActivationAlert(
      "Setup failed",
      message,
      {
        eyebrow: "Before you continue",
        returnFocus: elements.featureStudioActivationButton,
      },
    );
    setStatus("Setup failed");
    return;
  } finally {
    featureActivationBusy = false;
    updateFeatureStudioHeader();
  }
}

function startFeatureActivation(options = {}) {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  clearFeatureActivationNotice();
  clearFeatureActivationFieldErrors();
  state.featureStudioView = "activation";
  closeMenu();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, "activation");
  renderApp();
  window.scrollTo(0, 0);
  const firstMissingKey = getMissingFeatureActivationFields(feature)[0];
  const focusTarget = firstMissingKey ? getFeatureActivationFieldElement(firstMissingKey) : elements.featureActivationBusinessAccountIdInput;
  window.requestAnimationFrame(() => {
    focusTarget?.focus();
  });
  setStatus(String(options.statusMessage || (isFeatureActivated(feature) ? "WhatsApp details opened." : "WhatsApp setup opened.")));
}

async function deactivateSelectedFeature(options = {}) {
  if (featureActivationTransitionBusy) {
    return;
  }

  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  featureActivationTransitionBusy = true;
  featureActivationTransitionTargetId = feature.id;
  featureActivationTransitionAction = "deactivate";
  try {
    updateFeatureStudioHeader();
    setStatus("Turning tool off...");
    const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/activation`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        action: "deactivate",
        featureName: feature.name,
        channel: feature.channel,
      },
    });

    applyServerFeatureStates([response.feature || {}], { persist: true });
    state.paymentStatus = response.paymentStatus || state.paymentStatus;
    clearFeatureActivationNotice();
    clearFeatureActivationFieldErrors();
    state.featureStudioView = normalizeFeatureStudioView(options.view) || getDefaultFeatureStudioView(feature);
    closeFeatureStudioMenu();
    setHashForTab("features", feature.id, state.featureStudioView);
    renderApp();
    window.scrollTo(0, 0);
    setStatus(String(response.message || options.statusMessage || "Tool turned off."));
  } catch (error) {
    openFeatureActivationAlert(
      "Couldn’t turn the tool off",
      formatApiErrorMessage(error, "We couldn’t update the activation right now."),
      {
        eyebrow: "Try again",
        returnFocus: elements.featureStudioEditorToggleButton,
      },
    );
    setStatus("Couldn’t turn the tool off.");
  } finally {
    featureActivationTransitionBusy = false;
    featureActivationTransitionTargetId = "";
    featureActivationTransitionAction = "";
    updateFeatureStudioHeader();
  }
}

function openPaymentCheckout(checkoutUrl) {
  const url = String(checkoutUrl || "").trim();
  if (!url) {
    return false;
  }

  const popup = window.open(url, "_blank", "noopener");
  if (popup) {
    return true;
  }

  window.location.assign(url);
  return true;
}

function getManualMonitorRunAlertTone(run = {}) {
  const status = String(run?.status || "").trim().toLowerCase();
  const notificationsSent = Math.max(0, Number(run?.notificationsSent || 0));
  const metadata = run?.run?.metadata && typeof run.run.metadata === "object"
    ? run.run.metadata
      : run?.metadata && typeof run.metadata === "object"
        ? run.metadata
        : {};
  const noResultsNotificationSent = Boolean(metadata.noResultsNotificationSent);
  if (status === "cancelled" || status === "inconsistent_results") {
    return "warning";
  }
  return (status === "completed" && notificationsSent > 0) || noResultsNotificationSent ? "success" : "warning";
}

function getManualMonitorRunAlertIcon(run = {}) {
  return getManualMonitorRunAlertTone(run) === "success" ? "✓" : "!";
}

function getManualMonitorRunAlertTitle(run = {}) {
  const status = String(run?.status || "").trim().toLowerCase();
  const notificationsSent = Math.max(0, Number(run?.notificationsSent || 0));
  const metadata = run?.run?.metadata && typeof run.run.metadata === "object"
    ? run.run.metadata
    : run?.metadata && typeof run.metadata === "object"
      ? run.metadata
      : {};
  const recentResultsAlreadySent = Boolean(metadata.recentResultsAlreadySent);
  const manualRun = Boolean(metadata.manualRun);

  if (status === "cancelled") {
    return "Run cancelled";
  }
  if (status === "inconsistent_results") {
    return "Results changed unexpectedly";
  }
  if (status === "no_matches") {
    return manualRun ? "No relevant matches" : recentResultsAlreadySent ? "Nothing new right now" : "No matches found";
  }
  if (status === "duplicate_matches") {
    return "Nothing new to send";
  }
  if (notificationsSent > 0) {
    return "Results sent";
  }
  return "Run finished";
}

function getManualMonitorRunAlertMessage(run = {}, fallbackMessage = "Manual run finished.") {
  const status = String(run?.status || "").trim().toLowerCase();
  const notificationsSent = Math.max(0, Number(run?.notificationsSent || 0));
  const findingsCount = Math.max(0, Number(run?.findingsCount || 0));
  const metadata = run?.run?.metadata && typeof run.run.metadata === "object"
    ? run.run.metadata
    : run?.metadata && typeof run.metadata === "object"
      ? run.metadata
      : {};
  const deliveryChannel = String(metadata.deliveryChannel || "").trim().toLowerCase();
  const deliveryTarget = String(metadata.deliveryTarget || "").trim();
  const noResultsNotificationSent = Boolean(metadata.noResultsNotificationSent);
  const recentResultsAlreadySent = Boolean(metadata.recentResultsAlreadySent);
  const recentResultsCount = Math.max(0, Number(metadata.recentResultsCount || 0));
  const recentResultsMinutesAgo = Math.max(0, Number(metadata.recentResultsMinutesAgo || 0));
  const manualRun = Boolean(metadata.manualRun);

  if (status === "cancelled") {
    return "The monitor run was cancelled before any update was delivered.";
  }

  if (status === "inconsistent_results") {
    const countLabel = recentResultsCount === 1 ? "1 result" : `${recentResultsCount} results`;
    const recencyLabel = recentResultsMinutesAgo > 0
      ? `${recentResultsMinutesAgo} minutes earlier`
      : "earlier";
    const pronoun = recentResultsCount === 1 ? "it" : "them";
    return deliveryChannel === "email" && deliveryTarget
      ? `This run came back empty, but the previous run found ${countLabel} ${recencyLabel} and sent ${pronoun} to ${deliveryTarget}. We didn’t send a no-results update because that mismatch may be a search bug.`
      : `This run came back empty, but the previous run found ${countLabel} ${recencyLabel}. We didn’t send a no-results update because that mismatch may be a search bug.`;
  }

  if (status === "no_matches") {
    if (manualRun) {
      return deliveryChannel === "email" && deliveryTarget
        ? `I checked the saved topics and didn’t find a relevant match in this run. Nothing was sent to ${deliveryTarget}.`
        : "I checked the saved topics and didn’t find a relevant match in this run.";
    }
    if (noResultsNotificationSent) {
      if (recentResultsAlreadySent) {
        return deliveryChannel === "email" && deliveryTarget
          ? `The monitor completed successfully, didn't find anything new right now, and sent that update to ${deliveryTarget}. The latest results were already sent earlier.`
          : "The monitor completed successfully, didn't find anything new right now, and sent that update. The latest results were already sent earlier.";
      }
      return deliveryChannel === "email" && deliveryTarget
        ? `The monitor completed successfully, searched your saved topics, found no new results, and sent that update to ${deliveryTarget}.`
        : "The monitor completed successfully, searched your saved topics, found no new results, and sent an update about that.";
    }
    if (recentResultsAlreadySent) {
      return "The monitor completed successfully, didn't find anything new right now. The latest results were already sent earlier.";
    }
    return "The monitor completed successfully, but it did not find any relevant new matches, so no alert was sent.";
  }

  if (status === "duplicate_matches") {
    if (noResultsNotificationSent) {
      return deliveryChannel === "email" && deliveryTarget
        ? `The monitor completed successfully, found nothing new to report, and sent that update to ${deliveryTarget}.`
        : "The monitor completed successfully, found nothing new to report, and sent that update.";
    }
    return "The monitor found relevant items, but they were already sent before, so no new alert was sent.";
  }

  if (notificationsSent > 0) {
    if (manualRun) {
      const countLabel = findingsCount === 1 ? "the best match" : `the best ${findingsCount} matches`;
      if (deliveryChannel === "email" && deliveryTarget) {
        return `I ranked ${countLabel} for your saved topics and sent the summary to ${deliveryTarget}.`;
      }
      return `I ranked ${countLabel} for your saved topics and sent the summary.`;
    }
    if (deliveryChannel === "email" && deliveryTarget) {
      return `The monitor completed successfully and sent the results to ${deliveryTarget}.`;
    }
    return "The monitor completed successfully and sent the results.";
  }

  if (findingsCount > 0) {
    const matchLabel = findingsCount === 1 ? "match" : "matches";
    return `The monitor finished and found ${findingsCount} ${matchLabel}, but no alert was delivered.`;
  }

  return fallbackMessage;
}

function createManualMonitorRunRequestId() {
  if (typeof window.crypto?.randomUUID === "function") {
    return window.crypto.randomUUID();
  }

  return `monitor-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function syncMonitorManualRunOverlay() {
  if (!monitorManualRunBusy) {
    return;
  }

  const returnFocus = elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton;
  let eyebrow = "Run in progress";
  let title = "Running your monitor";
  let message = "We’re preparing the summary now. You can cancel it anytime if needed.";
  let buttonLabel = "Cancel run";
  let buttonDisabled = false;

  if (monitorManualRunCancelling) {
    eyebrow = "Stopping now";
    title = "Cancelling this run";
    message = "We’re stopping the current run before anything is sent.";
    buttonLabel = "Cancelling...";
    buttonDisabled = true;
  } else if (monitorManualRunCancellationError) {
    eyebrow = "Still running";
    title = "Couldn’t cancel yet";
    message = `${monitorManualRunCancellationError} The run is still active, so you can try cancelling again or wait for it to finish.`;
    buttonLabel = "Try again";
  }

  openAuthAlert(title, message, {
    eyebrow,
    buttonLabel,
    closeOnPrimary: false,
    dismissOnBackdrop: false,
    dismissOnEscape: false,
    iconMode: "spinner",
    onPrimary: () => {
      void requestMonitorManualRunCancellation();
    },
    primaryDisabled: buttonDisabled,
    returnFocus,
    tone: "progress",
  });
  monitorManualRunOverlayVisible = true;
}

function releaseMonitorManualRunOverlay() {
  if (!monitorManualRunOverlayVisible) {
    return;
  }

  monitorManualRunOverlayVisible = false;
  closeAuthAlert();
}

async function requestMonitorManualRunCancellation() {
  if (monitorManualRunCancelling || !monitorManualRunBusy || !monitorManualRunRequestId) {
    return;
  }

  const feature = getSelectedFeature();
  if (!feature || feature.id !== monitorManualRunTargetId) {
    return;
  }
  const requestId = monitorManualRunRequestId;

  monitorManualRunCancelling = true;
  monitorManualRunCancellationError = "";
  updateFeatureStudioHeader();
  syncMonitorManualRunOverlay();
  setStatus("Cancelling the monitor run. We’ll stop before sending anything.");

  try {
    await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/run`, {
      method: "DELETE",
      headers: getSessionAuthHeaders(),
      body: {
        runRequestId: requestId,
      },
    });
  } catch (error) {
    if (!monitorManualRunBusy || monitorManualRunRequestId !== requestId) {
      return;
    }
    monitorManualRunCancelling = false;
    monitorManualRunCancellationError = formatApiErrorMessage(
      error,
      "We couldn’t cancel it just yet. You can try again in a moment.",
    );
    updateFeatureStudioHeader();
    syncMonitorManualRunOverlay();
    setStatus(monitorManualRunCancellationError);
  }
}

async function runMonitorActionNow(featureId) {
  const normalizedFeatureId = String(featureId || "").trim();
  if (!normalizedFeatureId) {
    return;
  }
  if (monitorActionRunBusy.has(normalizedFeatureId)) {
    setStatus("This monitor is already running.");
    return;
  }

  let feature = getFeatureById(normalizedFeatureId);
  if (!feature || !isMonitorFeature(feature) || !isFeatureActivated(feature)) {
    setStatus("Activate the monitor before running it.");
    return;
  }

  if (feature.setupStatus?.ready === false) {
    try {
      await refreshFeatureActivationStates({ render: false });
      feature = getFeatureById(normalizedFeatureId) || feature;
    } catch {
      feature = getFeatureById(normalizedFeatureId) || feature;
    }
  }

  if (feature.setupStatus?.ready === false) {
    const setupStatus = feature.setupStatus || {};
    const firstIssue = Array.isArray(setupStatus.issues) ? setupStatus.issues[0] || {} : {};
    const message = String(
      setupStatus.message
      || firstIssue.message
      || "Finish the monitor setup before running it.",
    ).trim();
    openFeatureActivationAlert("Finish setup first", message, {
      eyebrow: "One thing left",
      returnFocus: elements.agentActionDetailContent,
    });
    return;
  }

  const requestId = createManualMonitorRunRequestId();
  monitorActionRunBusy.add(normalizedFeatureId);
  renderAgentActions();
  persistAgentWorkspace("Running the monitor now...");
  renderApp({ preserveStatus: true });

  try {
    const response = await apiRequest(`/api/features/${encodeURIComponent(normalizedFeatureId)}/run`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: { runRequestId: requestId },
      timeoutMs: 90000,
    });
    const completionMessage = String(response.message || "The monitor finished.");
    await refreshFeatureActivationStates({ render: false });
    pushAgentMessage("assistant", completionMessage, { kind: "result" });
    persistAgentWorkspace(completionMessage);
    renderApp({ preserveStatus: true });
    openAuthAlert(
      getManualMonitorRunAlertTitle(response.run),
      getManualMonitorRunAlertMessage(response.run, completionMessage),
      {
        eyebrow: "Manual run",
        buttonLabel: "OK",
        icon: getManualMonitorRunAlertIcon(response.run),
        tone: getManualMonitorRunAlertTone(response.run),
        returnFocus: elements.agentActionDetailContent,
      },
    );
  } catch (error) {
    const message = formatApiErrorMessage(error, "We couldn’t run the monitor right now.");
    pushAgentMessage("assistant", message, { kind: "error" });
    persistAgentWorkspace(message);
    renderApp({ preserveStatus: true });
    openFeatureActivationAlert("Couldn’t run the monitor", message, {
      eyebrow: "Try again",
      returnFocus: elements.agentActionDetailContent,
    });
  } finally {
    monitorActionRunBusy.delete(normalizedFeatureId);
    renderAgentActions();
  }
}

async function runSelectedMonitorNow() {
  if (monitorManualRunBusy) {
    if (monitorManualRunTargetId && getSelectedFeature()?.id === monitorManualRunTargetId) {
      syncMonitorManualRunOverlay();
      setStatus("A monitor run is already running.");
    } else {
      setStatus("A monitor run is already running. Refresh if this does not clear in a moment.");
    }
    return;
  }

  const initialFeature = getSelectedFeature();
  if (!initialFeature || !isMonitorFeature(initialFeature) || !isFeatureActivated(initialFeature)) {
    setStatus("Refresh the tool and try the monitor run again.");
    return;
  }

  let feature = initialFeature;
  if (feature.setupStatus?.ready === false) {
    try {
      await refreshFeatureActivationStates({ render: false });
      feature = getFeatureById(initialFeature.id) || initialFeature;
    } catch {
      feature = getFeatureById(initialFeature.id) || initialFeature;
    }
  }

  if (feature.setupStatus?.ready === false) {
    const setupStatus = feature.setupStatus || {};
    const issues = Array.isArray(setupStatus.issues) ? setupStatus.issues : [];
    const firstIssue = issues[0] || {};
    const message = String(
      setupStatus.message
      || firstIssue.message
      || "Finish the monitor setup before running it manually.",
    ).trim();
    openFeatureActivationAlert(
      "Finish setup first",
      message,
      {
        eyebrow: "One thing left",
        returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
      },
    );
    window.requestAnimationFrame(() => {
      getMonitorFieldElement(firstIssue.field)?.focus();
    });
    setStatus(message);
    return;
  }

  if (hasPendingFeatureConfigAutosave(feature.id) || hasFeatureConfigChanges(feature) || featureConfigBusy) {
    try {
      await flushSelectedFeatureConfigAutosave({
        featureId: feature.id,
        alertOnError: true,
        returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
        statusMessage: "Saving settings before running...",
      });
    } catch {
      return;
    }
  }

  monitorManualRunBusy = true;
  monitorManualRunTargetId = feature.id;
  monitorManualRunRequestId = createManualMonitorRunRequestId();
  monitorManualRunCancelling = false;
  monitorManualRunCancellationError = "";
  try {
    updateFeatureStudioHeader();
    syncMonitorManualRunOverlay();
    setStatus("Running the monitor now. Cancel it if you need to stop before anything is sent.");
    const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/run`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        runRequestId: monitorManualRunRequestId,
      },
      timeoutMs: 90000,
    });

    const completionMessage = String(response.message || "Manual run finished.");
    monitorManualRunOverlayVisible = false;
    pushAgentMessage("assistant", completionMessage, { kind: "result" });
    setStatus(completionMessage);
    openAuthAlert(
      getManualMonitorRunAlertTitle(response.run),
      getManualMonitorRunAlertMessage(response.run, completionMessage),
      {
        eyebrow: String(response.run?.status || "").trim().toLowerCase() === "cancelled" ? "Run cancelled" : "Run finished",
        buttonLabel: "OK",
        icon: getManualMonitorRunAlertIcon(response.run),
        tone: getManualMonitorRunAlertTone(response.run),
        returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
      },
    );
  } catch (error) {
    const payload = error?.payload || {};
    if (payload.error === "setup_required") {
      const setupStatus = payload.setupStatus || {};
      const issues = Array.isArray(setupStatus.issues) ? setupStatus.issues : [];
      const firstIssue = issues[0] || {};
      const message = String(
        payload.message
        || setupStatus.message
        || firstIssue.message
        || "Finish the monitor settings before running this manually.",
      ).trim();
      monitorManualRunOverlayVisible = false;
      openFeatureActivationAlert(
        "Finish setup first",
        message,
        {
          eyebrow: "One thing left",
          returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
        },
      );
      window.requestAnimationFrame(() => {
        getMonitorFieldElement(firstIssue.field)?.focus();
      });
      setStatus(message);
      return;
    }

    monitorManualRunOverlayVisible = false;
    openFeatureActivationAlert(
      "Couldn’t run the monitor",
      formatApiErrorMessage(error, "We couldn’t run the manual monitor right now."),
      {
        eyebrow: "Try again",
        returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
      },
    );
    setStatus("Couldn’t run the manual monitor.");
  } finally {
    monitorManualRunBusy = false;
    monitorManualRunTargetId = "";
    monitorManualRunRequestId = "";
    monitorManualRunCancelling = false;
    monitorManualRunCancellationError = "";
    releaseMonitorManualRunOverlay();
    updateFeatureStudioHeader();
  }
}

function formatReengagementInactivityLabel(settings = {}) {
  const inactivityValue = normalizeReengagementInactivityValue(settings.inactivityValue);
  const inactivityUnit = normalizeReengagementInactivityUnit(settings.inactivityUnit);
  const singular = inactivityUnit.endsWith("s") ? inactivityUnit.slice(0, -1) : inactivityUnit;
  return `${inactivityValue} ${inactivityValue === 1 ? singular : inactivityUnit}`;
}

function getReengagementInactivityWindowMilliseconds(settings = {}) {
  const inactivityValue = normalizeReengagementInactivityValue(settings.inactivityValue);
  const inactivityUnit = normalizeReengagementInactivityUnit(settings.inactivityUnit);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (inactivityUnit === "minutes") {
    return inactivityValue * minute;
  }
  if (inactivityUnit === "hours") {
    return inactivityValue * hour;
  }
  if (inactivityUnit === "days") {
    return inactivityValue * day;
  }
  return inactivityValue * 30 * day;
}

function formatReengagementDurationPart(value, singular, plural = `${singular}s`) {
  return `${value} ${value === 1 ? singular : plural}`;
}

function formatReengagementElapsedDuration(milliseconds) {
  const value = Math.max(0, Number(milliseconds) || 0);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (value < minute) {
    return "less than 1 minute";
  }

  const totalMinutes = Math.max(1, Math.floor(value / minute));
  if (totalMinutes < 60) {
    return formatReengagementDurationPart(totalMinutes, "minute");
  }

  const totalHours = Math.floor(totalMinutes / 60);
  const remainingMinutes = totalMinutes % 60;
  if (totalHours < 24) {
    const label = formatReengagementDurationPart(totalHours, "hour");
    return remainingMinutes && totalHours < 6
      ? `${label} ${formatReengagementDurationPart(remainingMinutes, "minute")}`
      : label;
  }

  const totalDays = Math.floor(totalHours / 24);
  const remainingHours = totalHours % 24;
  if (totalDays < 30) {
    const label = formatReengagementDurationPart(totalDays, "day");
    return remainingHours && totalDays < 3
      ? `${label} ${formatReengagementDurationPart(remainingHours, "hour")}`
      : label;
  }

  const totalMonths = Math.floor(totalDays / 30);
  if (totalMonths < 12) {
    return formatReengagementDurationPart(totalMonths, "month");
  }

  const totalYears = Math.floor(totalDays / 365);
  const remainingMonths = Math.floor((totalDays - (totalYears * 365)) / 30);
  const label = formatReengagementDurationPart(totalYears, "year");
  return remainingMonths && totalYears < 3
    ? `${label} ${formatReengagementDurationPart(remainingMonths, "month")}`
    : label;
}

function parseReengagementDemoTimestamp(value) {
  const text = normalizeText(value);
  if (!text) {
    return 0;
  }
  const parsed = new Date(text);
  const time = parsed.getTime();
  return Number.isFinite(time) ? time : 0;
}

function getReengagementDemoEvaluatedAtMilliseconds(run = {}) {
  for (const key of ["evaluatedAt", "completedAt", "createdAt", "runAt"]) {
    const time = parseReengagementDemoTimestamp(run?.[key]);
    if (time) {
      return time;
    }
  }

  const cutoffAt = parseReengagementDemoTimestamp(run?.cutoffAt);
  if (cutoffAt) {
    const settings = run?.settings && typeof run.settings === "object" ? run.settings : DEFAULT_REENGAGEMENT_SETTINGS;
    return cutoffAt + getReengagementInactivityWindowMilliseconds(settings);
  }
  return Date.now();
}

function getReengagementDemoCandidateInactiveMilliseconds(candidate = {}, run = {}) {
  const inactiveSeconds = Number(candidate.inactiveSeconds ?? candidate.inactive_seconds);
  if (Number.isFinite(inactiveSeconds) && inactiveSeconds >= 0) {
    return inactiveSeconds * 1000;
  }

  const lastActivityAt = parseReengagementDemoTimestamp(candidate.lastMessageAt || candidate.last_message_at);
  if (!lastActivityAt) {
    return 0;
  }
  return Math.max(0, getReengagementDemoEvaluatedAtMilliseconds(run) - lastActivityAt);
}

function formatReengagementCandidateName(candidate = {}) {
  return String(candidate.senderName || candidate.senderWaId || candidate.conversationId || "Unknown conversation").trim();
}

function formatReengagementOwnerLabel(run = {}) {
  const explicitOwner = normalizeText(run?.ownerWaId);
  const owner = explicitOwner || getFeatureWhatsAppOwnerLabel(getSelectedFeature());
  if (/^\d+$/.test(owner)) {
    return `+${owner}`;
  }
  return owner || "your WhatsApp";
}

function getReengagementDeliveryMode(run = {}) {
  return normalizeText(run?.deliveryMode).toLowerCase();
}

function getReengagementConversationsChecked(run = {}) {
  return Math.max(0, Number(run?.conversationsChecked || 0));
}

function formatReengagementCheckedConversationsLabel(run = {}) {
  const conversationsChecked = getReengagementConversationsChecked(run);
  return conversationsChecked === 1 ? "1 saved conversation" : `${conversationsChecked} saved conversations`;
}

function getReengagementSkippedConversations(run = {}) {
  const skipped = run?.skippedConversations && typeof run.skippedConversations === "object"
    ? run.skippedConversations
    : {};
  return {
    missingTimestamp: Math.max(0, Number(skipped.missingTimestamp || 0)),
    recentActivity: Math.max(0, Number(skipped.recentActivity || 0)),
    alreadyNotified: Math.max(0, Number(skipped.alreadyNotified || 0)),
  };
}

function formatReengagementSkippedSummary(run = {}) {
  const skipped = getReengagementSkippedConversations(run);
  const parts = [];
  if (skipped.recentActivity) {
    parts.push(`${skipped.recentActivity} ${skipped.recentActivity === 1 ? "was" : "were"} still inside the inactivity window`);
  }
  if (skipped.alreadyNotified) {
    parts.push(`${skipped.alreadyNotified} ${skipped.alreadyNotified === 1 ? "was" : "were"} already handled for the latest customer activity`);
  }
  if (skipped.missingTimestamp) {
    parts.push(`${skipped.missingTimestamp} had no saved activity timestamp`);
  }
  return parts.join("; ");
}

function hasReengagementDemoDeliveryErrors(run = {}) {
  return Array.isArray(run?.deliveryErrors) && run.deliveryErrors.length > 0;
}

function getReengagementDemoAlertIcon(run = {}) {
  const status = normalizeText(run?.status).toLowerCase();
  if (status === "cancelled" || hasReengagementDemoDeliveryErrors(run)) {
    return "!";
  }
  return Math.max(0, Number(run?.candidatesCount || 0)) > 0 ? "✓" : "!";
}

function getReengagementDemoAlertTone(run = {}) {
  const status = normalizeText(run?.status).toLowerCase();
  if (status === "cancelled" || hasReengagementDemoDeliveryErrors(run)) {
    return "warning";
  }
  return Math.max(0, Number(run?.candidatesCount || 0)) > 0 ? "success" : "warning";
}

function getReengagementDemoAlertTitle(run = {}) {
  const status = normalizeText(run?.status).toLowerCase();
  if (status === "cancelled") {
    return "Demo cancelled";
  }
  const candidatesCount = Math.max(0, Number(run?.candidatesCount || 0));
  if (candidatesCount > 0) {
    return candidatesCount === 1 ? "1 inactive conversation" : `${candidatesCount} inactive conversations`;
  }
  const notificationsSent = Math.max(0, Number(run?.notificationsSent || 0));
  if (notificationsSent > 0) {
    const deliveryMode = getReengagementDeliveryMode(run);
    if (deliveryMode === "mock") {
      return "WhatsApp report simulated";
    }
    if (deliveryMode === "template_prompt") {
      return "WhatsApp prompt sent";
    }
    if (deliveryMode === "telegram") {
      return "Telegram report sent";
    }
    if (deliveryMode === "mixed") {
      return "Reports partly sent";
    }
    return "Owner report sent";
  }
  if (!getReengagementConversationsChecked(run) && candidatesCount <= 0) {
    return "No saved conversations yet";
  }
  return "No inactive conversations";
}

function getReengagementDemoAlertMessage(run = {}, fallbackMessage = "Demo run finished.") {
  const status = normalizeText(run?.status).toLowerCase();
  const deliveryMode = getReengagementDeliveryMode(run);
  const ownerLabel = formatReengagementOwnerLabel(run);
  const candidatesCount = Math.max(0, Number(run?.candidatesCount || 0));
  const notificationsSent = Math.max(0, Number(run?.notificationsSent || 0));
  const conversationsChecked = getReengagementConversationsChecked(run);
  const checkedLabel = formatReengagementCheckedConversationsLabel(run);
  const deliveryErrors = Array.isArray(run?.deliveryErrors) ? run.deliveryErrors : [];
  const settings = run?.settings && typeof run.settings === "object" ? run.settings : DEFAULT_REENGAGEMENT_SETTINGS;
  const inactivityLabel = formatReengagementInactivityLabel(settings);

  if (status === "cancelled") {
    if (notificationsSent > 0) {
      const reportLabel = deliveryMode === "telegram"
        ? (notificationsSent === 1 ? "Telegram report" : "Telegram reports")
        : (notificationsSent === 1 ? "WhatsApp report" : "WhatsApp reports");
      if (deliveryMode === "mock") {
        return `Cancelled after simulating ${notificationsSent} demo ${reportLabel} for ${ownerLabel}. Customers were not contacted.`;
      }
      if (deliveryMode === "template_prompt") {
        return `Cancelled after sending a WhatsApp template prompt to ${ownerLabel}. Customers were not contacted.`;
      }
      return `Cancelled after sending ${notificationsSent} demo ${reportLabel}. Customers were not contacted.`;
    }
    return "Cancelled before any demo owner report was sent. Customers were not contacted.";
  }

  if (!conversationsChecked && candidatesCount <= 0) {
    return "No saved conversations are available yet. Import WhatsApp history or wait for conversations to be captured, then run the demo again. Customers were not contacted.";
  }

  if (deliveryErrors.length && notificationsSent <= 0) {
    if (candidatesCount > 0) {
      const matchLabel = candidatesCount === 1 ? "1 inactive conversation" : `${candidatesCount} inactive conversations`;
      return `Found ${matchLabel} and prepared the follow-up drafts below. Owner delivery failed, so nothing was sent. Customers were not contacted.`;
    }
    const skippedSummary = formatReengagementSkippedSummary(run);
    const scanSummary = skippedSummary
      ? `Checked ${checkedLabel}. ${skippedSummary}.`
      : `Checked ${checkedLabel} against the current ${inactivityLabel} inactivity window.`;
    return `${scanSummary} Owner delivery failed before a no-results report could be sent. Customers were not contacted.`;
  }

  if (notificationsSent > 0) {
    const reportLabel = deliveryMode === "telegram"
      ? (notificationsSent === 1 ? "Telegram message" : "Telegram messages")
      : deliveryMode === "mixed"
        ? (notificationsSent === 1 ? "owner message" : "owner messages")
        : (notificationsSent === 1 ? "WhatsApp message" : "WhatsApp messages");
    const matchLabel = candidatesCount === 1 ? "1 inactive conversation" : `${candidatesCount} inactive conversations`;
    if (deliveryMode === "mock") {
      const base = candidatesCount > 0
        ? `Simulated ${notificationsSent} demo ${reportLabel} for ${ownerLabel} with details for ${matchLabel}.`
        : `Simulated a no-results demo ${reportLabel} for ${ownerLabel} for the current ${inactivityLabel} inactivity window.`;
      return `${base} Live WhatsApp delivery is not configured, so nothing reached your WhatsApp. Customers were not contacted.`;
    }
    if (deliveryMode === "template_prompt") {
      const base = candidatesCount > 0
        ? `Sent a WhatsApp template prompt to ${ownerLabel} for ${matchLabel}.`
        : `Sent a WhatsApp template prompt to ${ownerLabel} for the current ${inactivityLabel} inactivity window.`;
      return `${base} Tap Send details in WhatsApp to receive the generated report. Customers were not contacted.`;
    }
    if (deliveryMode === "telegram") {
      const base = candidatesCount > 0
        ? `Sent ${notificationsSent} demo ${reportLabel} with details for ${matchLabel}.`
        : `Sent a no-results demo ${reportLabel} for the current ${inactivityLabel} inactivity window.`;
      return `${base} Customers were not contacted.`;
    }
    const base = candidatesCount > 0
      ? `Sent ${notificationsSent} demo ${reportLabel} to ${ownerLabel} with details for ${matchLabel}.`
      : `Sent a no-results demo ${reportLabel} to ${ownerLabel} for the current ${inactivityLabel} inactivity window.`;
    return deliveryErrors.length
      ? `${base} Some results could not be delivered, so try again if anything looks missing. Customers were not contacted.`
      : `${base} Customers were not contacted.`;
  }

  if (candidatesCount > 0 && deliveryMode === "none") {
    const matchLabel = candidatesCount === 1 ? "1 inactive conversation" : `${candidatesCount} inactive conversations`;
    return `Found ${matchLabel}. Review, edit, and copy the generated follow-up drafts below. Customers were not contacted.`;
  }

  return `${fallbackMessage} Customers were not contacted.`;
}

function getReengagementDemoCandidates(run = {}) {
  return Array.isArray(run?.candidates) ? run.candidates : [];
}

function getReengagementDemoCandidateKey(candidate = {}, index = 0) {
  return normalizeText(candidate.conversationId)
    || normalizeText(candidate.senderWaId)
    || `candidate-${index + 1}`;
}

function formatReengagementDemoSummary(run = {}, fallbackMessage = "") {
  const status = normalizeText(run?.status).toLowerCase();
  const candidatesCount = Math.max(0, Number(run?.candidatesCount || getReengagementDemoCandidates(run).length || 0));
  const conversationsChecked = getReengagementConversationsChecked(run);
  const checkedLabel = formatReengagementCheckedConversationsLabel(run);
  const settings = run?.settings && typeof run.settings === "object" ? run.settings : DEFAULT_REENGAGEMENT_SETTINGS;
  const inactivityLabel = formatReengagementInactivityLabel(settings);
  const deliveryMode = getReengagementDeliveryMode(run);
  const deliveryErrors = Array.isArray(run?.deliveryErrors) ? run.deliveryErrors : [];

  if (status === "cancelled") {
    return fallbackMessage || "The demo was cancelled before the full findings list was completed.";
  }
  if (!candidatesCount) {
    if (!conversationsChecked) {
      return "No saved conversations are available for this demo yet. Import WhatsApp history or let new conversations arrive, then run the demo again.";
    }
    const skippedSummary = formatReengagementSkippedSummary(run);
    const base = `Checked ${checkedLabel}. None matched the current inactivity rule: more than ${inactivityLabel} without customer activity.`;
    return skippedSummary ? `${base} ${skippedSummary}.` : base;
  }
  const matchLabel = candidatesCount === 1 ? "conversation" : "conversations";
  const deliveryNote = deliveryErrors.length
    ? "WhatsApp delivery failed, so no WhatsApp message was sent."
    : deliveryMode === "none"
    ? "No WhatsApp message was sent."
    : "Customers were not contacted.";
  return `Found ${candidatesCount} inactive ${matchLabel}. Review, edit, and copy the generated follow-up drafts below. ${deliveryNote}`;
}

function formatReengagementDemoCandidateMeta(candidate = {}, run = {}) {
  const inactiveLabel = formatReengagementElapsedDuration(
    getReengagementDemoCandidateInactiveMilliseconds(candidate, run),
  );
  return inactiveLabel ? `Inactive for ${inactiveLabel}` : "Inactive";
}

async function copyReengagementDemoDraft(candidateKey, candidateName, textarea) {
  const text = String(textarea?.value || "").trim();
  if (!text) {
    setStatus("There is no draft text to copy.");
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    state.reengagementDemoDrafts[candidateKey] = text;
    setStatus(`Copied follow-up draft for ${candidateName}.`);
  } catch {
    setStatus("Copy failed in this browser.");
  }
}

function resizeReengagementDemoDraftTextarea(textarea) {
  if (!textarea) {
    return;
  }
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function scheduleReengagementDemoDraftResize(textarea) {
  resizeReengagementDemoDraftTextarea(textarea);
  window.requestAnimationFrame(() => {
    resizeReengagementDemoDraftTextarea(textarea);
  });
}

function createReengagementDemoEmptyResult(run = {}) {
  const conversationsChecked = getReengagementConversationsChecked(run);
  const skippedSummary = formatReengagementSkippedSummary(run);
  const empty = document.createElement("div");
  empty.className = "reengagement-demo-empty";
  const title = document.createElement("strong");
  title.textContent = conversationsChecked ? "No matching conversations" : "No saved conversations yet";
  const copy = document.createElement("p");
  copy.textContent = conversationsChecked
    ? skippedSummary || "Lower the inactivity window or wait for older conversations, then run the demo again."
    : "Import real WhatsApp history or let this tool capture conversations before running the demo again.";
  empty.append(title, copy);
  return empty;
}

function createReengagementDemoCandidateResult(candidate = {}, index = 0, run = {}) {
  const candidateKey = getReengagementDemoCandidateKey(candidate, index);
  const candidateName = formatReengagementCandidateName(candidate);
  const savedDraftText = String(state.reengagementDemoDrafts[candidateKey] || "").trim();
  const generatedDraftText = String(candidate.draftText || "").trim();
  const draftText = savedDraftText || generatedDraftText;
  state.reengagementDemoDrafts[candidateKey] = draftText;

  const item = document.createElement("article");
  item.className = "reengagement-demo-result";

  const header = document.createElement("div");
  header.className = "reengagement-demo-result-head";
  const titleGroup = document.createElement("div");
  titleGroup.className = "reengagement-demo-result-title";
  const title = document.createElement("h4");
  title.textContent = candidateName;
  const meta = document.createElement("p");
  meta.textContent = formatReengagementDemoCandidateMeta(candidate, run);
  titleGroup.append(title, meta);
  header.append(titleGroup);
  item.append(header);

  const draftWrap = document.createElement("div");
  draftWrap.className = "reengagement-demo-draft";
  const draftHead = document.createElement("div");
  draftHead.className = "reengagement-demo-draft-head";
  const label = document.createElement("label");
  const textareaId = `reengagementDemoDraft-${index}`;
  label.setAttribute("for", textareaId);
  label.textContent = "Draft";
  const copyButton = document.createElement("button");
  copyButton.className = "reengagement-demo-copy-button";
  copyButton.type = "button";
  copyButton.title = `Copy follow-up draft for ${candidateName}`;
  copyButton.setAttribute("aria-label", `Copy follow-up draft for ${candidateName}`);
  const copyIcon = document.createElement("span");
  copyIcon.className = "copy-icon";
  copyIcon.setAttribute("aria-hidden", "true");
  copyButton.append(copyIcon);
  draftHead.append(label, copyButton);

  const textarea = document.createElement("textarea");
  textarea.id = textareaId;
  textarea.rows = 2;
  textarea.value = draftText;
  textarea.addEventListener("input", () => {
    state.reengagementDemoDrafts[candidateKey] = textarea.value;
    resizeReengagementDemoDraftTextarea(textarea);
  });
  copyButton.addEventListener("click", () => {
    void copyReengagementDemoDraft(candidateKey, candidateName, textarea);
  });

  draftWrap.append(draftHead, textarea);
  item.append(draftWrap);
  scheduleReengagementDemoDraftResize(textarea);
  return item;
}

function renderReengagementDemoResultItems(list, run = {}) {
  if (!list) {
    return;
  }

  list.innerHTML = "";
  const candidates = getReengagementDemoCandidates(run);
  if (!candidates.length) {
    list.append(createReengagementDemoEmptyResult(run));
    return;
  }

  candidates.forEach((candidate, index) => {
    list.append(createReengagementDemoCandidateResult(candidate, index, run));
  });
}

function createReengagementDemoAlertBody(run = {}) {
  const body = document.createElement("div");
  body.className = "reengagement-demo-alert-results";

  const list = document.createElement("div");
  list.className = "reengagement-demo-results-list";
  renderReengagementDemoResultItems(list, run);

  body.append(list);
  return body;
}

function openReengagementDemoResultsAlert(run = {}, completionMessage = "Demo run finished.", returnFocus = null) {
  const candidates = getReengagementDemoCandidates(run);
  const hasCandidateResults = candidates.length > 0;
  openAuthAlert(
    getReengagementDemoAlertTitle(run),
    getReengagementDemoAlertMessage(run, completionMessage),
    {
      eyebrow: "Demo results",
      buttonLabel: "OK",
      bodyNode: hasCandidateResults ? createReengagementDemoAlertBody(run) : null,
      icon: getReengagementDemoAlertIcon(run),
      tone: getReengagementDemoAlertTone(run),
      variant: hasCandidateResults ? "demo-results" : "default",
      returnFocus,
    },
  );
}

function renderReengagementDemoResults(feature = getSelectedFeature()) {
  const card = elements.reengagementDemoResultsCard;
  const summary = elements.reengagementDemoResultsSummary;
  const list = elements.reengagementDemoResultsList;
  if (!card || !summary || !list) {
    return;
  }

  const result = state.reengagementDemoResult;
  const run = result?.run && typeof result.run === "object" ? result.run : null;
  const resultFeatureId = normalizeText(result?.featureId);
  const selectedFeatureId = normalizeText(feature?.id);
  const showResults = Boolean(isReengagementFeature(feature) && run && resultFeatureId === selectedFeatureId);
  card.classList.toggle("is-hidden", !showResults);
  list.innerHTML = "";

  if (!showResults || !run) {
    summary.textContent = "Run the demo to find inactive conversations and prepare follow-up drafts.";
    return;
  }

  summary.textContent = formatReengagementDemoSummary(run, result?.message || "");
  renderReengagementDemoResultItems(list, run);
}

function syncReengagementDemoRunOverlay() {
  if (!reengagementDemoRunBusy) {
    return;
  }

  let title = "Running demo";
  let message = "Checking saved conversations and generating follow-up drafts. If WhatsApp delivery is configured, we’ll also send the owner prompt. Customers will not be contacted.";
  let secondaryButtonLabel = "Cancel";
  let secondaryDisabled = false;

  if (reengagementDemoRunCancelling) {
    title = "Cancelling demo";
    message = "Stopping after the current step and before sending any more WhatsApp reports. Customers will not be contacted.";
    secondaryButtonLabel = "Cancelling...";
    secondaryDisabled = true;
  } else if (reengagementDemoRunCancellationError) {
    title = "Couldn’t cancel yet";
    message = `${reengagementDemoRunCancellationError} The demo is still running, so you can try cancelling again or wait for it to finish.`;
    secondaryButtonLabel = "Try again";
  }

  openAuthAlert(title, message, {
    eyebrow: "Demo run",
    buttonLabel: "Running...",
    primaryDisabled: true,
    secondaryButtonLabel,
    secondaryDisabled,
    closeOnSecondary: false,
    dismissOnBackdrop: false,
    dismissOnEscape: false,
    focusTarget: secondaryDisabled ? "primary" : "secondary",
    iconMode: "spinner",
    onSecondary: () => {
      void requestReengagementDemoRunCancellation();
    },
    returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
    tone: "progress",
  });
  reengagementDemoRunOverlayVisible = true;
}

function releaseReengagementDemoRunOverlay() {
  if (!reengagementDemoRunOverlayVisible) {
    return;
  }

  reengagementDemoRunOverlayVisible = false;
  closeAuthAlert();
}

async function requestReengagementDemoRunCancellation() {
  if (reengagementDemoRunCancelling || !reengagementDemoRunBusy || !reengagementDemoRunRequestId) {
    return;
  }

  const feature = getSelectedFeature();
  if (!feature || feature.id !== reengagementDemoRunTargetId) {
    return;
  }

  const requestId = reengagementDemoRunRequestId;
  reengagementDemoRunCancelling = true;
  reengagementDemoRunCancellationError = "";
  updateFeatureStudioHeader();
  syncReengagementDemoRunOverlay();
  setStatus("Cancelling the re-engagement demo. We’ll stop before sending any more WhatsApp reports.");

  try {
    await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/run`, {
      method: "DELETE",
      headers: getSessionAuthHeaders(),
      body: {
        runRequestId: requestId,
      },
    });
  } catch (error) {
    if (!reengagementDemoRunBusy || reengagementDemoRunRequestId !== requestId) {
      return;
    }
    reengagementDemoRunCancelling = false;
    reengagementDemoRunCancellationError = formatApiErrorMessage(
      error,
      "We couldn’t cancel the demo just yet. You can try again in a moment.",
    );
    updateFeatureStudioHeader();
    syncReengagementDemoRunOverlay();
    setStatus(reengagementDemoRunCancellationError);
  }
}

async function runSelectedReengagementDemo() {
  if (reengagementDemoRunBusy) {
    setStatus("A re-engagement demo is already running.");
    return;
  }

  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    setStatus("Refresh the tool and try the demo again.");
    return;
  }

  if (hasPendingFeatureConfigAutosave(feature.id) || hasFeatureConfigChanges(feature) || featureConfigBusy) {
    try {
      await flushSelectedFeatureConfigAutosave({
        featureId: feature.id,
        alertOnError: true,
        returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
        statusMessage: "Saving settings before the demo...",
      });
    } catch {
      return;
    }
  }

  reengagementDemoRunBusy = true;
  reengagementDemoRunTargetId = feature.id;
  reengagementDemoRunRequestId = createManualMonitorRunRequestId();
  reengagementDemoRunCancelling = false;
  reengagementDemoRunCancellationError = "";
  state.reengagementDemoResult = null;
  state.reengagementDemoDrafts = {};
  try {
    updateFeatureStudioHeader();
    syncReengagementDemoRunOverlay();
    setStatus("Running the re-engagement demo and preparing results.");
    const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/run`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        runRequestId: reengagementDemoRunRequestId,
      },
      timeoutMs: 90000,
    });

    const completionMessage = String(response.message || "Demo run finished.");
    state.reengagementDemoResult = {
      featureId: feature.id,
      message: completionMessage,
      run: response.run && typeof response.run === "object" ? response.run : {},
    };
    state.reengagementDemoDrafts = {};
    renderReengagementDemoResults(feature);
    reengagementDemoRunOverlayVisible = false;
    setStatus(completionMessage);
    openReengagementDemoResultsAlert(
      response.run,
      completionMessage,
      elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
    );
  } catch (error) {
    reengagementDemoRunOverlayVisible = false;
    const errorPayload = error?.payload && typeof error.payload === "object" ? error.payload : {};
    const errorRun = errorPayload.run && typeof errorPayload.run === "object" ? errorPayload.run : null;
    if (errorRun) {
      const completionMessage = String(
        errorPayload.message
          || formatApiErrorMessage(error, "Demo generated findings, but WhatsApp delivery failed."),
      );
      state.reengagementDemoResult = {
        featureId: feature.id,
        message: completionMessage,
        run: errorRun,
      };
      state.reengagementDemoDrafts = {};
      renderReengagementDemoResults(feature);
      setStatus(completionMessage);
      openReengagementDemoResultsAlert(
        errorRun,
        completionMessage,
        elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
      );
      return;
    }
    openFeatureActivationAlert(
      "Couldn’t run the demo",
      formatApiErrorMessage(error, "We couldn’t run the re-engagement demo right now."),
      {
        eyebrow: "Try again",
        returnFocus: elements.featureStudioMonitorRunButton || elements.featureStudioEditorToggleButton,
      },
    );
    setStatus("Couldn’t run the re-engagement demo.");
  } finally {
    reengagementDemoRunBusy = false;
    reengagementDemoRunTargetId = "";
    reengagementDemoRunRequestId = "";
    reengagementDemoRunCancelling = false;
    reengagementDemoRunCancellationError = "";
    releaseReengagementDemoRunOverlay();
    updateFeatureStudioHeader();
  }
}

function waitForDelay(delayMs) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, Math.max(0, Number(delayMs) || 0));
  });
}

function createWhatsAppSampleWaitControl() {
  const control = {
    action: "",
    promise: null,
    resolve: null,
  };

  control.promise = new Promise((resolve) => {
    control.resolve = (action) => {
      if (control.action) {
        return;
      }

      control.action = normalizeText(action);
      resolve(control.action);
    };
  });

  return control;
}

function getWhatsAppReplySampleConfirmationState(featureId, ownerMessageId) {
  const feature = getFeatureById(featureId);
  const health = getFeatureWhatsAppHealth(feature);
  const status = String(health.lastOwnerNotificationStatus || "").trim().toLowerCase();
  const messageId = String(health.lastOwnerNotificationMessageId || "").trim();

  return {
    feature,
    health,
    status,
    messageId,
    matchesMessageId: Boolean(ownerMessageId) && messageId === ownerMessageId,
  };
}

function getWhatsAppReplySampleSuccessMessage(feature, confirmationState) {
  const ownerLabel = getFeatureWhatsAppOwnerLabel(feature);
  return confirmationState.status === "read"
    ? `WhatsApp confirmed the sample reached ${ownerLabel} and was opened.`
    : `WhatsApp confirmed the sample reached ${ownerLabel}.`;
}

function getWhatsAppReplySampleFailureMessage(feature) {
  const ownerLabel = getFeatureWhatsAppOwnerLabel(feature);
  const health = getFeatureWhatsAppHealth(feature);
  const errorText = sanitizeErrorText(health.lastOwnerNotificationError || "");
  const issueDetails = errorText ? ` WhatsApp reported: ${errorText}.` : "";
  return `The sample alert did not reach ${ownerLabel}.${issueDetails} Check the connected number and your WhatsApp delivery status before trying again.`;
}

function getWhatsAppReplySamplePendingMessage(feature, confirmationState) {
  const ownerLabel = getFeatureWhatsAppOwnerLabel(feature);
  const receiptSummary = confirmationState.matchesMessageId && confirmationState.status === "sent"
    ? "WhatsApp accepted the sample, but no delivery receipt arrived within 30 seconds."
    : "The sample was sent, but no delivery receipt arrived within 30 seconds.";
  return `${receiptSummary} It may already be on ${ownerLabel}; we’ll keep updating this status when Meta sends the receipt.`;
}

function withWhatsAppSampleUserAction(confirmationState, userAction = "") {
  return {
    ...confirmationState,
    userAction: normalizeText(userAction),
  };
}

async function waitForWhatsAppReplySampleConfirmation(featureId, ownerMessageId, options = {}) {
  const userControl = options.userControl || null;
  let confirmationState = getWhatsAppReplySampleConfirmationState(featureId, ownerMessageId);
  if (
    confirmationState.matchesMessageId
    && ["delivered", "read", "failed"].includes(confirmationState.status)
  ) {
    return withWhatsAppSampleUserAction(confirmationState);
  }

  const deadline = Date.now() + WHATSAPP_SAMPLE_CONFIRMATION_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (userControl?.action) {
      return withWhatsAppSampleUserAction(
        getWhatsAppReplySampleConfirmationState(featureId, ownerMessageId),
        userControl.action,
      );
    }

    const delayMs = Math.min(
      WHATSAPP_SAMPLE_CONFIRMATION_POLL_MS,
      Math.max(0, deadline - Date.now()),
    );
    let userAction = "";
    if (userControl) {
      userAction = await Promise.race([
        waitForDelay(delayMs).then(() => ""),
        userControl.promise,
      ]);
    } else {
      await waitForDelay(delayMs);
    }

    if (userAction) {
      return withWhatsAppSampleUserAction(
        getWhatsAppReplySampleConfirmationState(featureId, ownerMessageId),
        userAction,
      );
    }

    try {
      await refreshWhatsAppConnection({ render: false, timeoutMs: 10000 });
    } catch {
      // Keep waiting until timeout in case the next refresh succeeds.
    }

    if (document.body.dataset.view === "app") {
      renderApp({ preserveStatus: true });
    }

    confirmationState = getWhatsAppReplySampleConfirmationState(featureId, ownerMessageId);
    if (userControl?.action) {
      return withWhatsAppSampleUserAction(confirmationState, userControl.action);
    }

    if (
      confirmationState.matchesMessageId
      && ["delivered", "read", "failed"].includes(confirmationState.status)
    ) {
      return withWhatsAppSampleUserAction(confirmationState);
    }
  }

  return withWhatsAppSampleUserAction(getWhatsAppReplySampleConfirmationState(featureId, ownerMessageId));
}

async function sendSelectedWhatsAppReplySample() {
  if (whatsappSampleMessageBusy) {
    return;
  }

  const feature = getSelectedFeature();
  if (!feature || !isWhatsAppReplyAssistantFeature(feature) || !canSendWhatsAppReplySample(feature)) {
    setStatus("Finish WhatsApp setup before sending a sample.");
    return;
  }

  if (hasFeatureActivationChanges(feature)) {
    openFeatureActivationAlert(
      "Save the latest details first",
      "Save your WhatsApp details before sending a sample so the test goes to the right phone.",
      {
        eyebrow: "Almost there",
        returnFocus: elements.featureStudioWhatsAppSampleButton || elements.featureStudioEditorToggleButton,
      },
    );
    setStatus("Save the latest WhatsApp details before sending a sample.");
    return;
  }

  whatsappSampleMessageBusy = true;
  whatsappSampleMessageTargetId = feature.id;
  try {
    updateFeatureStudioHeader();
    setStatus("Sending a sample WhatsApp alert...");
    const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/sample`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {},
    });

    applyWhatsAppConnectionToFeatures(response.connection || null, { persist: true });
    renderApp({ preserveStatus: true });
    const ownerMessageId = String(
      response.ownerMessageId
      || getFeatureWhatsAppHealth(getFeatureById(feature.id) || feature).lastOwnerNotificationMessageId
      || "",
    ).trim();
    const waitControl = createWhatsAppSampleWaitControl();
    openAuthAlert(
      "Testing WhatsApp delivery",
      "We’re sending a sample alert now and waiting for WhatsApp to confirm it reached your phone.",
      {
        eyebrow: "Testing now",
        buttonLabel: "Received the msg",
        dismissOnBackdrop: false,
        dismissOnEscape: false,
        iconMode: "spinner",
        onPrimary: () => waitControl.resolve("received"),
        onSecondary: () => waitControl.resolve("cancelled"),
        returnFocus: elements.featureStudioWhatsAppSampleButton || elements.featureStudioEditorToggleButton,
        secondaryButtonLabel: "Cancel",
        tone: "progress",
      },
    );
    setStatus("Waiting for WhatsApp to confirm the sample delivery...");

    const confirmationState = await waitForWhatsAppReplySampleConfirmation(feature.id, ownerMessageId, { userControl: waitControl });
    const latestFeature = getFeatureById(feature.id) || feature;
    if (confirmationState.userAction === "cancelled") {
      setStatus("Sample delivery check cancelled.");
      return;
    }

    if (confirmationState.userAction === "received") {
      openAuthAlert(
        "Marked as received",
        "Nice. We’ll stop waiting here and keep updating the setup if WhatsApp sends the official receipt later.",
        {
          eyebrow: "Got it",
          buttonLabel: "OK",
          icon: "✓",
          tone: "success",
          returnFocus: elements.featureStudioWhatsAppSampleButton || elements.featureStudioEditorToggleButton,
        },
      );
      setStatus("Sample marked as received.");
      return;
    }

    if (
      confirmationState.matchesMessageId
      && ["delivered", "read"].includes(confirmationState.status)
    ) {
      openAuthAlert(
        "Sample delivered",
        getWhatsAppReplySampleSuccessMessage(latestFeature, confirmationState),
        {
          eyebrow: "Check WhatsApp",
          buttonLabel: "OK",
          icon: "✓",
          tone: "success",
          returnFocus: elements.featureStudioWhatsAppSampleButton || elements.featureStudioEditorToggleButton,
        },
      );
      setStatus("WhatsApp confirmed the sample delivery.");
      return;
    }

    const failedByWhatsApp = confirmationState.matchesMessageId && confirmationState.status === "failed";
    openAuthAlert(
      failedByWhatsApp ? "Sample failed" : "Sample sent",
      failedByWhatsApp
        ? getWhatsAppReplySampleFailureMessage(latestFeature)
        : getWhatsAppReplySamplePendingMessage(latestFeature, confirmationState),
      {
        eyebrow: failedByWhatsApp ? "Test failed" : "Delivery receipt pending",
        buttonLabel: "OK",
        icon: failedByWhatsApp ? "!" : "✓",
        tone: failedByWhatsApp ? "warning" : "progress",
        returnFocus: elements.featureStudioWhatsAppSampleButton || elements.featureStudioEditorToggleButton,
      },
    );
    setStatus(
      failedByWhatsApp
        ? "The sample alert did not reach your phone."
        : "The sample alert was sent; delivery receipt is still pending.",
    );
  } catch (error) {
    try {
      await refreshWhatsAppConnection({ render: false });
    } catch {
      // Keep the current UI if the follow-up refresh fails.
    }
    renderApp({ preserveStatus: true });
    openFeatureActivationAlert(
      "Couldn’t send the sample",
      formatApiErrorMessage(
        error,
        "We couldn’t send a sample WhatsApp alert right now. Check the saved connection details and try again.",
      ),
      {
        eyebrow: "Try again",
        returnFocus: elements.featureStudioWhatsAppSampleButton || elements.featureStudioEditorToggleButton,
      },
    );
    setStatus("Couldn’t send the sample WhatsApp alert.");
  } finally {
    whatsappSampleMessageBusy = false;
    whatsappSampleMessageTargetId = "";
    updateFeatureStudioHeader();
  }
}

async function toggleSelectedFeatureEditorActivation() {
  if (featureActivationTransitionBusy) {
    return;
  }

  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  if (isFeatureActivated(feature)) {
    await deactivateSelectedFeature({ view: "editor", statusMessage: "Tool turned off." });
    return;
  }

  if (usesEditorSetup(feature)) {
    let configResponse = null;
    if (hasPendingFeatureConfigAutosave(feature.id) || hasFeatureConfigChanges(feature) || featureConfigBusy) {
      try {
        configResponse = await flushSelectedFeatureConfigAutosave({
          featureId: feature.id,
          alertOnError: true,
          returnFocus: elements.featureStudioEditorToggleButton,
          statusMessage: "Saving settings before activation...",
        });
      } catch {
        return;
      }
    }

    const refreshedFeature = getSelectedFeature() || feature;
    const setupStatus = configResponse?.setupStatus || refreshedFeature.setupStatus || {};
    if (!isFeatureSetupComplete(refreshedFeature) || setupStatus.ready === false) {
      const issues = Array.isArray(setupStatus.issues) ? setupStatus.issues : [];
      const firstIssue = issues[0] || {};
      const message = String(
        setupStatus.message
        || firstIssue.message
        || "Finish the monitor settings before turning this tool on.",
      ).trim();
      openFeatureActivationAlert(
        "Finish setup first",
        message,
        {
          eyebrow: "One thing left",
          returnFocus: elements.featureStudioEditorToggleButton,
        },
      );
      window.requestAnimationFrame(() => {
        getMonitorFieldElement(firstIssue.field)?.focus();
      });
      setStatus(message);
      return;
    }
  } else if (!isFeatureSetupComplete(feature)) {
    startFeatureActivation({
      statusMessage: hasFeatureWhatsAppDetails(feature)
        ? "Finish WhatsApp setup before turning this tool on."
        : "Start WhatsApp setup before turning this tool on.",
    });
    return;
  }

  featureActivationTransitionBusy = true;
  featureActivationTransitionTargetId = feature.id;
  featureActivationTransitionAction = "activate";
  try {
    updateFeatureStudioHeader();
    setStatus("Checking payment and activation...");
    const response = await apiRequest(`/api/features/${encodeURIComponent(feature.id)}/activation`, {
      method: "POST",
      headers: getSessionAuthHeaders(),
      body: {
        action: "activate",
        featureName: feature.name,
        channel: feature.channel,
      },
    });

    applyServerFeatureStates([response.feature || {}], { persist: true });
    state.paymentStatus = response.paymentStatus || state.paymentStatus;
    clearFeatureActivationNotice();
    clearFeatureActivationFieldErrors();
    state.featureStudioView = "editor";
    closeFeatureStudioMenu();
    setHashForTab("features", feature.id, "editor");
    renderApp();
    window.scrollTo(0, 0);
    setStatus(String(response.message || "Tool activated."));
  } catch (error) {
    const payload = error?.payload || {};
    if (payload.error === "payment_required") {
      state.paymentStatus = payload.paymentStatus || state.paymentStatus;
      const checkoutOpened = openPaymentCheckout(payload.paymentStatus?.checkoutUrl || payload.checkoutUrl);
      openFeatureActivationAlert(
        "Add payment details",
        payload.message || "Add your card details before activating this tool.",
        {
          eyebrow: "Billing required",
          returnFocus: elements.featureStudioEditorToggleButton,
        },
      );
      setStatus(checkoutOpened ? "Opening checkout..." : "Payment is required before activation.");
      return;
    }

    if (payload.error === "setup_required") {
      const message = payload.message || "Finish setup before turning this tool on.";
      if (usesEditorSetup(feature)) {
        openFeatureActivationAlert(
          "Finish setup first",
          message,
          {
            eyebrow: "One thing left",
            returnFocus: elements.featureStudioEditorToggleButton,
          },
        );
      } else {
        startFeatureActivation({
          statusMessage: payload.message || "Finish WhatsApp setup before turning this tool on.",
        });
        openFeatureActivationAlert(
          "Finish setup first",
          payload.message || "Finish WhatsApp setup before turning this tool on.",
          {
            eyebrow: "One thing left",
            returnFocus: elements.featureStudioActivationButton,
          },
        );
      }
      setStatus(message);
      return;
    }

    openFeatureActivationAlert(
      "Couldn’t activate the tool",
      formatApiErrorMessage(error, "We couldn’t activate the tool right now."),
      {
        eyebrow: "Try again",
        returnFocus: elements.featureStudioEditorToggleButton,
      },
    );
    setStatus("Couldn’t activate the tool.");
  } finally {
    featureActivationTransitionBusy = false;
    featureActivationTransitionTargetId = "";
    featureActivationTransitionAction = "";
    updateFeatureStudioHeader();
  }
}

function updateFeatureActivationFields() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  updateFeatureActivationPhonePlaceholder();
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  if (elements.featureActivationBusinessAccountIdInput) {
    elements.featureActivationBusinessAccountIdInput.value = whatsapp.business_account_id;
  }
  if (elements.featureActivationPhoneNumberIdInput) {
    elements.featureActivationPhoneNumberIdInput.value = whatsapp.phone_number_id;
  }
  if (elements.featureActivationAccessTokenInput && !elements.featureActivationAccessTokenInput.matches(":focus")) {
    elements.featureActivationAccessTokenInput.value = getAccessTokenDisplayValue(whatsapp);
  }
  if (elements.featureActivationAccessTokenHelp) {
    let tokenHelpText = "Paste a token with access to this WABA and phone number.";
    if (whatsapp.workspace_access_token_configured) {
      tokenHelpText = "A token is saved and hidden. Paste over the dots to replace it.";
    } else if (whatsapp.backend_access_token_configured) {
      tokenHelpText = "The Assistyca sender token is configured for owner alerts. Paste this client's token to connect their number.";
    }
    elements.featureActivationAccessTokenHelp.textContent = tokenHelpText;
  }
  if (elements.featureActivationOwnerWaIdInput) {
    elements.featureActivationOwnerWaIdInput.value = whatsapp.owner_wa_id;
  }
}

function updateFeatureActivationStatus(feature = getSelectedFeature()) {
  const content = buildFeatureActivationStatusContent(feature);

  if (elements.featureActivationNumberStatusTitle) {
    elements.featureActivationNumberStatusTitle.textContent = content.number.title;
  }
  if (elements.featureActivationNumberStatusCopy) {
    elements.featureActivationNumberStatusCopy.textContent = content.number.copy;
  }
  if (elements.featureActivationInboundStatusTitle) {
    elements.featureActivationInboundStatusTitle.textContent = content.inbound.title;
  }
  if (elements.featureActivationInboundStatusCopy) {
    elements.featureActivationInboundStatusCopy.textContent = content.inbound.copy;
  }
  if (elements.featureActivationOwnerStatusTitle) {
    elements.featureActivationOwnerStatusTitle.textContent = content.owner.title;
  }
  if (elements.featureActivationOwnerStatusCopy) {
    elements.featureActivationOwnerStatusCopy.textContent = content.owner.copy;
  }
  if (elements.featureActivationWebhookHint) {
    elements.featureActivationWebhookHint.textContent = content.note;
    elements.featureActivationWebhookHint.classList.toggle("is-hidden", !content.note);
  }
}

function updateFeatureStudioWhatsAppHealthNotice(feature = getSelectedFeature()) {
  const notice = buildFeatureEditorWhatsAppHealthNotice(feature);
  const element = elements.featureStudioWhatsAppHealthNotice;
  if (!element || !elements.featureStudioWhatsAppHealthNoticeTitle || !elements.featureStudioWhatsAppHealthNoticeCopy) {
    return;
  }

  if (!notice) {
    element.classList.add("is-hidden");
    element.dataset.tone = "";
    elements.featureStudioWhatsAppHealthNoticeTitle.textContent = "";
    elements.featureStudioWhatsAppHealthNoticeCopy.textContent = "";
    return;
  }

  element.classList.remove("is-hidden");
  element.dataset.tone = notice.tone || "neutral";
  elements.featureStudioWhatsAppHealthNoticeTitle.textContent = notice.title;
  elements.featureStudioWhatsAppHealthNoticeCopy.textContent = notice.copy;
}

function renderFeatureActivationFieldErrors() {
  const fieldStates = [
    {
      key: "business_account_id",
      input: elements.featureActivationBusinessAccountIdInput,
      error: elements.featureActivationBusinessAccountIdError,
    },
    {
      key: "phone_number_id",
      input: elements.featureActivationPhoneNumberIdInput,
      error: elements.featureActivationPhoneNumberIdError,
    },
    {
      key: "access_token",
      input: elements.featureActivationAccessTokenInput,
      error: elements.featureActivationAccessTokenError,
    },
    {
      key: "owner_wa_id",
      input: elements.featureActivationOwnerWaIdInput,
      error: elements.featureActivationOwnerWaIdError,
    },
  ];

  for (const { key, input, error } of fieldStates) {
    if (!input || !error) {
      continue;
    }

    const message = getFeatureActivationFieldError(key);
    const field = input.closest(".field");
    if (field) {
      field.classList.toggle("has-error", Boolean(message));
    }

    input.setAttribute("aria-invalid", String(Boolean(message)));
    error.textContent = message;
    error.hidden = !message;
  }
}

function syncFeatureActivationField(key) {
  return (event) => {
    const feature = getSelectedFeature();
    if (!feature) {
      return;
    }

    if (!feature.whatsapp) {
      feature.whatsapp = { ...DEFAULT_FEATURE_WHATSAPP };
    }

    feature.whatsapp[key] = key === "access_token"
      ? normalizePendingAccessToken(event.target.value)
      : event.target.value;

    if (!featureActivationBusy) {
      clearFeatureActivationNotice();
    }
    clearFeatureActivationFieldError(key);
    persistClientState();
    updateFeatureStudioHeader();
    setStatus(hasFeatureActivationChanges(feature) ? "Changes ready to save." : "No changes to save.");
  };
}

function handleFeatureActivationAccessTokenFocus(event) {
  if (normalizeText(event.target.value) === SAVED_ACCESS_TOKEN_FIELD_VALUE) {
    event.target.value = "";
  }
}

function handleFeatureActivationAccessTokenBlur() {
  updateFeatureActivationFields();
}

function updateFeatureStudioHeader() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  const example = buildFeatureExample(feature);
  const pitch = buildFeaturePitch(feature);
  const isActivated = isFeatureActivated(feature);
  const isSetupComplete = isFeatureSetupComplete(feature);
  const studioView = getSelectedFeatureStudioView(feature);
  const activationBusy = isFeatureActivationBusy(feature);
  const transitionBusy = isFeatureActivationTransitionBusy(feature);
  const manualRunBusy = isMonitorManualRunBusy(feature) || isReengagementDemoRunBusy(feature);
  const hasActivationChanges = hasFeatureActivationChanges(feature);

  state.featureStudioView = studioView;

  if (elements.featureStudioHeaderLabel) {
    elements.featureStudioHeaderLabel.textContent = studioView === "history"
      ? "Conversation history"
      : studioView === "editor"
        ? "Tool editor"
        : studioView === "activation"
        ? isActivated
          ? "WhatsApp details"
          : "WhatsApp setup"
        : "Tool overview";
  }
  if (elements.featureStudioNav) {
    elements.featureStudioNav.classList.add("is-hidden");
  }
  if (elements.featureStudioOverviewButton) {
    elements.featureStudioOverviewButton.hidden = true;
    elements.featureStudioOverviewButton.classList.toggle("is-active", studioView === "overview");
    elements.featureStudioOverviewButton.setAttribute("aria-selected", String(studioView === "overview"));
  }
  if (elements.featureStudioEditorButton) {
    elements.featureStudioEditorButton.hidden = true;
    elements.featureStudioEditorButton.classList.toggle("is-active", studioView === "editor");
    elements.featureStudioEditorButton.setAttribute("aria-selected", String(studioView === "editor"));
  }
  if (elements.featureStudioOverviewSection) {
    elements.featureStudioOverviewSection.classList.toggle("is-hidden", studioView !== "overview");
  }
  if (elements.featureStudioActivationSection) {
    elements.featureStudioActivationSection.classList.toggle("is-hidden", studioView !== "activation");
  }
  if (elements.featureStudioEditorSection) {
    elements.featureStudioEditorSection.classList.toggle("is-hidden", studioView !== "editor");
  }
  if (elements.whatsappHistorySection) {
    elements.whatsappHistorySection.classList.toggle("is-hidden", studioView !== "history");
  }
  if (elements.backToFeaturesButton) {
    elements.backToFeaturesButton.querySelector("span:last-child").textContent = studioView === "history"
      ? "Back to editor"
      : studioView === "activation"
      ? getActivationBackView(feature) === "editor"
        ? "Back to editor"
        : "Back to overview"
      : "Back to tools";
  }
  if (elements.featureStudioStatus) {
    elements.featureStudioStatus.classList.toggle("is-hidden", studioView === "activation");
    if (studioView === "activation") {
      clearFeatureActivationBadgeStyle(elements.featureStudioStatus);
      elements.featureStudioStatus.textContent = getFeatureStudioStatusLabel(feature, studioView);
    } else if (studioView === "history") {
      clearFeatureActivationBadgeStyle(elements.featureStudioStatus);
      const history = getCurrentWhatsAppHistory();
      elements.featureStudioStatus.textContent = state.whatsappHistoryLoading
        ? "Loading history"
        : history
          ? formatWhatsAppMessageCount(history.messageCount)
          : "History";
    } else {
      applyFeatureActivationBadgeStyle(elements.featureStudioStatus, feature);
      elements.featureStudioStatus.textContent = getFeatureActivationLabel(feature);
    }
  }
  elements.featureStudioTitle.textContent = feature.name;
  elements.featureStudioDescription.textContent = feature.description || "";
  if (elements.featureStudioPitch) {
    elements.featureStudioPitch.textContent = pitch;
  }
  if (elements.featureStudioExampleSender) {
    elements.featureStudioExampleSender.textContent = example.sender;
  }
  if (elements.featureStudioExampleAvatar) {
    elements.featureStudioExampleAvatar.textContent = example.avatar;
  }
  if (elements.featureStudioExampleMeta) {
    elements.featureStudioExampleMeta.textContent = example.meta;
  }
  renderFeatureExampleMessages(example);
  if (elements.featureStudioExampleReply) {
    elements.featureStudioExampleReply.textContent = example.outgoing;
  }
  if (elements.featureStudioLaunchButton) {
    elements.featureStudioLaunchButton.hidden = isActivated || studioView === "activation";
    elements.featureStudioLaunchButton.disabled = false;
    elements.featureStudioLaunchButton.textContent = usesEditorSetup(feature)
      ? isSetupComplete
        ? "Open tool editor"
        : "Continue setup"
      : isSetupComplete
        ? "Open tool editor"
        : "Start setup";
  }

  updateFeatureActivationStatus(feature);
  updateFeatureStudioWhatsAppHealthNotice(feature);
  renderFeatureActivationFieldErrors();
  if (elements.featureStudioActivationButton) {
    const showActivationSaveButton = activationBusy || hasActivationChanges;
    const activationActions = elements.featureStudioActivationButton.closest(".feature-activation-actions");
    if (activationActions) {
      activationActions.classList.remove("is-hidden");
      activationActions.classList.toggle("is-save-visible", showActivationSaveButton);
      activationActions.setAttribute("aria-hidden", String(!showActivationSaveButton));
    }
    elements.featureStudioActivationButton.hidden = false;
    elements.featureStudioActivationButton.tabIndex = showActivationSaveButton ? 0 : -1;
    elements.featureStudioActivationButton.textContent = activationBusy
      ? isActivated
        ? "Saving details..."
        : "Saving setup..."
      : isActivated
        ? "Save details"
        : "Save setup";
    elements.featureStudioActivationButton.disabled = activationBusy || !hasActivationChanges;
    elements.featureStudioActivationButton.classList.toggle("is-loading", activationBusy);
    elements.featureStudioActivationButton.setAttribute("aria-busy", String(activationBusy));
  }
  if (elements.featureActivationBusinessAccountIdInput) {
    elements.featureActivationBusinessAccountIdInput.disabled = activationBusy;
  }
  if (elements.featureActivationPhoneNumberIdInput) {
    elements.featureActivationPhoneNumberIdInput.disabled = activationBusy;
  }
  if (elements.featureActivationAccessTokenInput) {
    elements.featureActivationAccessTokenInput.disabled = activationBusy;
  }
  if (elements.featureActivationOwnerWaIdInput) {
    elements.featureActivationOwnerWaIdInput.disabled = activationBusy;
  }
  if (elements.featureStudioActivationSection) {
    elements.featureStudioActivationSection.classList.toggle("is-loading", activationBusy);
    elements.featureStudioActivationSection.setAttribute("aria-busy", String(activationBusy));
  }
  const isEditorSetup = usesEditorSetup(feature);
  const sampleMessageBusy = isWhatsAppReplySampleBusy(feature);
  if (elements.featureStudioEditorToggleButton) {
    elements.featureStudioEditorToggleButton.textContent = transitionBusy
      ? featureActivationTransitionAction === "deactivate"
        ? "Turning off..."
        : "Activating..."
      : isActivated
        ? "Deactivate tool"
        : isEditorSetup && !isSetupComplete
          ? "Finish setup"
        : isSetupComplete
          ? "Activate tool"
        : hasFeatureWhatsAppDetails(feature)
            ? "Finish WhatsApp setup"
            : "Start WhatsApp setup";
    elements.featureStudioEditorToggleButton.className = isActivated ? "ghost-button danger" : "primary-button";
    elements.featureStudioEditorToggleButton.disabled = transitionBusy || manualRunBusy || sampleMessageBusy;
    elements.featureStudioEditorToggleButton.setAttribute("aria-pressed", String(isActivated));
  }
  if (elements.featureStudioWhatsAppSampleButton) {
    const showSampleButton = canSendWhatsAppReplySample(feature);
    const sampleReady = showSampleButton && !hasFeatureActivationChanges(feature);
    elements.featureStudioWhatsAppSampleButton.hidden = !showSampleButton;
    elements.featureStudioWhatsAppSampleButton.textContent = sampleMessageBusy ? "Testing WhatsApp..." : "Send sample";
    elements.featureStudioWhatsAppSampleButton.disabled = activationBusy || transitionBusy || sampleMessageBusy || !sampleReady;
    elements.featureStudioWhatsAppSampleButton.classList.toggle("is-loading", sampleMessageBusy);
    elements.featureStudioWhatsAppSampleButton.setAttribute("aria-busy", String(sampleMessageBusy));
    elements.featureStudioWhatsAppSampleButton.title = sampleMessageBusy
      ? "Testing WhatsApp delivery now"
      : sampleReady
        ? "Send a sample approval alert to your WhatsApp"
        : "Save the latest WhatsApp details before sending a sample";
  }
  if (elements.featureStudioWhatsAppHistoryButton) {
    const showHistoryButton = isWhatsAppFeature(feature);
    elements.featureStudioWhatsAppHistoryButton.hidden = !showHistoryButton;
    elements.featureStudioWhatsAppHistoryButton.disabled = transitionBusy || manualRunBusy || sampleMessageBusy;
  }
  if (elements.featureStudioMonitorRunButton) {
    const showMonitorRun = isMonitorFeature(feature) && isActivated;
    const showReengagementDemo = isReengagementFeature(feature);
    const showManualRun = showMonitorRun || showReengagementDemo;
    const manualRunReady = showManualRun;
    const reengagementBusy = isReengagementDemoRunBusy(feature);
    elements.featureStudioMonitorRunButton.hidden = !showManualRun;
    elements.featureStudioMonitorRunButton.textContent = reengagementBusy
      ? reengagementDemoRunCancelling
        ? "Cancelling..."
        : "Running demo..."
      : manualRunBusy
        ? monitorManualRunCancelling
          ? "Cancelling..."
          : "Running..."
        : showReengagementDemo
          ? "Demo run"
          : "Run now";
    elements.featureStudioMonitorRunButton.disabled = !manualRunReady || transitionBusy || manualRunBusy;
    elements.featureStudioMonitorRunButton.classList.toggle("is-loading", false);
    elements.featureStudioMonitorRunButton.setAttribute("aria-busy", String(manualRunBusy));
    elements.featureStudioMonitorRunButton.title = reengagementBusy
      ? reengagementDemoRunCancelling
        ? "The current re-engagement demo is being cancelled"
        : "A re-engagement demo is currently running"
      : showReengagementDemo
        ? "Find inactive conversations and preview follow-up drafts without sending anything"
        : manualRunBusy
      ? monitorManualRunCancelling
        ? "The current monitor run is being cancelled"
        : "A monitor run is currently running"
        : manualRunReady
        ? feature.setupStatus?.ready === false
          ? "Run a summary now. We'll check the latest setup first."
          : "Run a summary without changing the schedule"
        : String(feature.setupStatus?.message || "");
  }
  renderReengagementDemoResults(feature);

  if (studioView === "history") {
    renderWhatsAppHistory(feature);
    if (!getCurrentWhatsAppHistory() && !state.whatsappHistoryLoading && !state.whatsappHistoryError) {
      void refreshWhatsAppHistory();
    }
  }
}

function updatePromptFields() {
  const prompt = getSelectedPrompt();
  elements.toneGuidance.value = prompt.toneGuidance;
  elements.responseStyle.value = prompt.responseStyle;
  elements.replyRules.value = prompt.replyRules;
  elements.businessNotes.value = prompt.businessNotes;
  elements.escalationGuidance.value = prompt.escalationGuidance;
  updateFeatureModelFields();
}

function setMonitorDeliveryPanelState(panel, isActive) {
  if (!panel) {
    return;
  }

  panel.classList.toggle("is-active", isActive);
  panel.setAttribute("aria-hidden", String(!isActive));

  for (const control of panel.querySelectorAll("input, select, textarea, button")) {
    control.disabled = !isActive;
  }
}

function setDeliveryChannelOptionState(value, isVisible) {
  const option = elements.monitorDeliveryChannel?.querySelector(`option[value="${value}"]`);
  if (!option) {
    return;
  }
  option.hidden = !isVisible;
  option.disabled = !isVisible;
}

function getWhatsAppToolPlatformOption(platformId) {
  const normalizedId = String(platformId || "").trim().toLowerCase();
  return getWhatsAppToolPlatformOptions().find((option) => option.id === normalizedId) || null;
}

function getWhatsAppToolPlatformOptions(feature = getSelectedFeature()) {
  if (isWhatsAppReplyAssistantFeature(feature)) {
    return WHATSAPP_TOOL_PLATFORM_OPTIONS.filter((option) => ["whatsapp", "telegram", "portal"].includes(option.id));
  }
  return WHATSAPP_TOOL_PLATFORM_OPTIONS.filter((option) => option.id !== "portal");
}

function normalizeWhatsAppToolDeliveryChannelsForFeature(feature, value, fallback = DEFAULT_WHATSAPP_TOOL_SETTINGS.deliveryChannels) {
  const allowedPlatformIds = new Set(getWhatsAppToolPlatformOptions(feature).map((option) => option.id));
  return normalizeWhatsAppToolDeliveryChannels(value, fallback).filter((channel) => allowedPlatformIds.has(channel));
}

function getWhatsAppToolDeliveryChannels(settings = getSelectedFeatureSettings(), feature = getSelectedFeature()) {
  return normalizeWhatsAppToolDeliveryChannelsForFeature(
    feature,
    Array.isArray(settings?.deliveryChannels) ? settings.deliveryChannels : settings?.deliveryChannel,
    [],
  );
}

function setDeliveryPlatformMenuOpen(isOpen) {
  if (!elements.deliveryPlatformMenu) {
    return;
  }
  const shouldOpen = Boolean(isOpen);
  elements.deliveryPlatformMenu.hidden = !shouldOpen;
  elements.deliveryPlatformMenu.classList.toggle("is-hidden", !shouldOpen);
  elements.deliveryPlatformMenu.classList.toggle("is-open", shouldOpen);
  elements.deliveryPlatformAddButton?.setAttribute("aria-expanded", String(shouldOpen));
}

function updateDeliveryPlatformMenu(settings = getSelectedFeatureSettings()) {
  if (!elements.deliveryPlatformMenu) {
    return;
  }
  const channels = getWhatsAppToolDeliveryChannels(settings);
  const selected = new Set(channels);
  const availableOptions = getWhatsAppToolPlatformOptions();
  const buttons = availableOptions.map((option) => {
    const button = document.createElement("button");
    const isSelected = selected.has(option.id);
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.dataset.deliveryPlatformOption = option.id;
    button.disabled = isSelected;
    button.setAttribute("aria-disabled", String(isSelected));
    button.textContent = option.label;
    return button;
  });
  elements.deliveryPlatformMenu.replaceChildren(...buttons);
  if (elements.deliveryPlatformAddButton) {
    const hasAvailablePlatform = availableOptions.some((option) => !selected.has(option.id));
    elements.deliveryPlatformAddButton.disabled = !hasAvailablePlatform;
    elements.deliveryPlatformAddButton.textContent = hasAvailablePlatform ? "+ Add platform" : "All platforms added";
    if (!hasAvailablePlatform) {
      setDeliveryPlatformMenuOpen(false);
    }
  }
}

function renderDeliveryPlatformList(settings = getSelectedFeatureSettings()) {
  if (!elements.deliveryPlatformList) {
    return;
  }
  const channels = getWhatsAppToolDeliveryChannels(settings);
  const rows = [];

  if (!channels.length) {
    const empty = document.createElement("div");
    empty.className = "delivery-platform-empty";
    empty.setAttribute("role", "listitem");
    empty.textContent = "No platforms added yet";
    rows.push(empty);
  }

  for (const channel of channels) {
    const option = getWhatsAppToolPlatformOption(channel);
    if (!option) {
      continue;
    }
    const row = document.createElement("div");
    row.className = "delivery-platform-row";
    row.setAttribute("role", "listitem");

    const badge = document.createElement("span");
    badge.className = `delivery-platform-badge is-${option.id}`;
    badge.setAttribute("aria-hidden", "true");
    badge.textContent = option.shortLabel;

    const copy = document.createElement("span");
    copy.className = "delivery-platform-copy";
    const label = document.createElement("strong");
    label.textContent = option.label;
    const caption = document.createElement("span");
    if (option.id === "whatsapp") {
      caption.textContent = getFeatureWhatsAppConnectedLabel();
    } else {
      const chatId = String(settings?.telegramChatId || "").trim();
      caption.textContent = chatId ? `Chat ${chatId}` : "Chat id missing";
    }
    copy.append(label, caption);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "delivery-platform-remove";
    removeButton.dataset.deliveryPlatformRemove = option.id;
    removeButton.setAttribute("aria-label", `Remove ${option.label}`);
    removeButton.textContent = "×";

    row.append(badge, copy, removeButton);
    rows.push(row);
  }

  elements.deliveryPlatformList.replaceChildren(...rows);
  updateDeliveryPlatformMenu(settings);
}

function updateMonitorFieldVisibility(settings = getSelectedFeatureSettings()) {
  const feature = getSelectedFeature();
  const isMonitor = isMonitorFeature(feature);
  const isWhatsAppTool = isWhatsAppFeature(feature);
  const whatsappDeliverySelection = getWhatsAppDeliverySelection(settings);
  const usesWhatsAppDelivery = isWhatsAppTool && ["whatsapp", "both"].includes(whatsappDeliverySelection);
  const usesTelegramDelivery = isWhatsAppTool && ["telegram", "both"].includes(whatsappDeliverySelection);
  const sharedPromptCards = [
    elements.featureToneCard,
    elements.featureRulesCard,
    elements.featureContextCard,
  ];

  for (const card of sharedPromptCards) {
    if (card) {
      card.classList.toggle("is-hidden", isMonitor);
    }
  }

  setDeliveryChannelOptionState("email", isMonitor);
  setDeliveryChannelOptionState("telegram", true);
  setDeliveryChannelOptionState("whatsapp", true);
  if (elements.monitorDeliveryChannelField) {
    elements.monitorDeliveryChannelField.classList.toggle("is-hidden", isWhatsAppTool);
  }
  if (elements.deliveryPlatformManager) {
    elements.deliveryPlatformManager.classList.toggle("is-hidden", !isWhatsAppTool);
    if (!isWhatsAppTool) {
      setDeliveryPlatformMenuOpen(false);
    } else {
      renderDeliveryPlatformList(settings);
    }
  }

  setMonitorDeliveryPanelState(elements.monitorEmailField, isMonitor && settings.deliveryChannel === "email");
  setMonitorDeliveryPanelState(
    elements.monitorTelegramField,
    isMonitor ? settings.deliveryChannel === "telegram" : usesTelegramDelivery,
  );
  setMonitorDeliveryPanelState(
    elements.monitorWhatsAppField,
    isMonitor ? settings.deliveryChannel === "whatsapp" : usesWhatsAppDelivery,
  );
}

function getMonitorNextRunLabel(feature) {
  if (!feature || !isMonitorFeature(feature)) {
    return "";
  }

  if (normalizeMonitorManualOnly(getSelectedFeatureSettings(feature).manualOnly)) {
    return "Manual only · use Run now when you want a summary";
  }
  const nextRunAt = resolveMonitorNextRunAt(feature);
  if (!nextRunAt) {
    if (!isFeatureActivated(feature)) {
      return "Activate to schedule";
    }
    if (feature.setupStatus?.ready === false) {
      return "Finish setup first";
    }
    return "Next run will appear soon";
  }

  const formatted = formatMonitorNextRunDate(nextRunAt, getMonitorScheduleTimezone(feature));
  if (!formatted) {
    return "Next run will appear soon";
  }

  const parsed = new Date(nextRunAt);
  if (!Number.isNaN(parsed.getTime()) && parsed.getTime() <= Date.now()) {
    return `Due now · ${formatted}`;
  }
  return formatted;
}

function updateMonitorFields() {
  const feature = getSelectedFeature();
  const isMonitor = isMonitorFeature(feature);
  const supportsOwnerDelivery = isMonitor || isWhatsAppFeature(feature);
  const isScheduledTool = isMonitor || isReengagementFeature(feature);
  if (elements.featureStudioEditorSection) {
    elements.featureStudioEditorSection.classList.toggle("is-monitor-flow", isMonitor);
    elements.featureStudioEditorSection.classList.toggle("is-scheduled-flow", isScheduledTool);
  }
  if (elements.monitorTargetCard) {
    elements.monitorTargetCard.classList.toggle("is-hidden", !isMonitor);
  }
  if (elements.monitorScheduleCard) {
    elements.monitorScheduleCard.classList.toggle("is-hidden", !isMonitor);
  }
  if (elements.monitorNextRun) {
    elements.monitorNextRun.hidden = !isMonitor;
  }
  if (elements.monitorDeliveryCard) {
    elements.monitorDeliveryCard.classList.toggle("is-hidden", !supportsOwnerDelivery);
  }
  if (!supportsOwnerDelivery) {
    updateMonitorFieldVisibility(DEFAULT_MONITOR_SETTINGS);
    return;
  }

  const monitorSettings = getSelectedFeatureSettings(feature);
  if (isMonitor) {
    state.monitorWatchItemDraft = loadMonitorWatchDraft(feature.id);
    renderMonitorWatchItems(monitorSettings.watchItems);
    const manualOnly = normalizeMonitorManualOnly(monitorSettings.manualOnly);
    if (elements.monitorManualOnly) {
      elements.monitorManualOnly.checked = manualOnly;
      elements.monitorManualOnly.setAttribute("aria-checked", String(manualOnly));
    }
    const scheduleControls = elements.monitorManualOnly?.closest(".monitor-schedule-controls");
    scheduleControls?.setAttribute("data-manual-only", String(manualOnly));
    if (elements.monitorIntervalDays) {
      elements.monitorIntervalDays.disabled = manualOnly;
    }
    if (elements.monitorScheduleTime) {
      elements.monitorScheduleTime.disabled = manualOnly;
    }
    if (elements.monitorWatchItemInput) {
      elements.monitorWatchItemInput.value = state.monitorWatchItemDraft;
    }
    if (elements.monitorIntervalDays) {
      elements.monitorIntervalDays.value = String(monitorSettings.intervalDays);
    }
    if (elements.monitorScheduleTime) {
      elements.monitorScheduleTime.value = getMonitorScheduleTime(feature);
    }
    if (elements.monitorScheduleTimezoneLabel) {
      const scheduleTimezone = getMonitorScheduleTimezone(feature);
      elements.monitorScheduleTimezoneLabel.textContent = scheduleTimezone === getWorkspaceTimeZone()
        ? "Workspace time"
        : "Saved time zone";
      elements.monitorScheduleTimezoneLabel.title = scheduleTimezone;
    }
    if (elements.monitorNextRunValue) {
      elements.monitorNextRunValue.textContent = getMonitorNextRunLabel(feature);
      elements.monitorNextRunValue.title = resolveMonitorNextRunAt(feature);
    }
  }
  if (elements.monitorDeliveryChannel) {
    elements.monitorDeliveryChannel.value = isMonitor
      ? monitorSettings.deliveryChannel
      : getWhatsAppDeliverySelection(monitorSettings);
  }
  if (elements.monitorEmailSummary) {
    const emailSummary = activeEmail || "Workspace account email";
    elements.monitorEmailSummary.textContent = emailSummary;
    elements.monitorEmailSummary.title = emailSummary;
  }
  if (elements.monitorTelegramChatId) {
    elements.monitorTelegramChatId.value = monitorSettings.telegramChatId;
  }
  updateMonitorFieldVisibility(monitorSettings);
}

function getReengagementNextRunLabel(feature) {
  if (!feature || !isReengagementFeature(feature)) {
    return "";
  }

  if (!isFeatureActivated(feature)) {
    return "Activate to schedule";
  }

  const nextRunAt = String(feature.nextRunAt || feature.setupStatus?.nextRunAt || "").trim();
  if (!nextRunAt) {
    return hasFeatureConfigChanges(feature) ? "Saving changes..." : "Next run will appear soon";
  }

  const formatted = formatMonitorNextRunDate(nextRunAt, getReengagementScheduleTimezone(feature));
  if (!formatted) {
    return "Next run will appear soon";
  }

  const parsed = new Date(nextRunAt);
  if (!Number.isNaN(parsed.getTime()) && parsed.getTime() <= Date.now()) {
    return `Due now · ${formatted}`;
  }
  return formatted;
}

function updateReengagementFields() {
  const feature = getSelectedFeature();
  const isReengagement = isReengagementFeature(feature);
  if (elements.reengagementScheduleCard) {
    elements.reengagementScheduleCard.classList.toggle("is-hidden", !isReengagement);
  }
  if (elements.reengagementNextRun) {
    elements.reengagementNextRun.hidden = !isReengagement;
  }
  if (!isReengagement) {
    return;
  }

  const settings = getSelectedFeatureSettings(feature);
  if (elements.reengagementIntervalDays) {
    elements.reengagementIntervalDays.value = String(settings.intervalDays);
  }
  if (elements.reengagementScheduleTime) {
    elements.reengagementScheduleTime.value = getReengagementScheduleTime(feature);
  }
  if (elements.reengagementScheduleTimezoneLabel) {
    const scheduleTimezone = getReengagementScheduleTimezone(feature);
    elements.reengagementScheduleTimezoneLabel.textContent = scheduleTimezone === getWorkspaceTimeZone()
      ? "Workspace time"
      : "Saved time zone";
    elements.reengagementScheduleTimezoneLabel.title = scheduleTimezone;
  }
  if (elements.reengagementInactivityValue) {
    elements.reengagementInactivityValue.value = String(settings.inactivityValue);
  }
  if (elements.reengagementInactivityUnit) {
    elements.reengagementInactivityUnit.value = settings.inactivityUnit;
  }
  if (elements.reengagementNextRunValue) {
    elements.reengagementNextRunValue.textContent = getReengagementNextRunLabel(feature);
    elements.reengagementNextRunValue.title = String(feature.nextRunAt || feature.setupStatus?.nextRunAt || "");
  }
}

function getFeatureModelOptions() {
  return DEFAULT_TOOL_MODEL_OPTIONS.map((option) => ({ ...option }));
}

function getFeatureModelOptionById(modelId) {
  const normalizedModelId = String(modelId || "").trim();
  return getFeatureModelOptions().find((option) => option.id === normalizedModelId) || null;
}

function updateFeatureModelFields() {
  const feature = getSelectedFeature();
  const settings = getSelectedFeatureSettings(feature);
  const modelOptions = getFeatureModelOptions();
  const selectedOption = getFeatureModelOptionById(settings.model) || modelOptions[0] || null;

  if (elements.featureModelSelect) {
    const existingSignature = Array.from(elements.featureModelSelect.options)
      .map((option) => `${option.value}:${option.textContent || ""}`)
      .join("|");
    const nextSignature = modelOptions.map((option) => `${option.id}:${option.name}`).join("|");
    if (existingSignature !== nextSignature) {
      elements.featureModelSelect.replaceChildren(
        ...modelOptions.map((option) => {
          const element = document.createElement("option");
          element.value = option.id;
          element.textContent = option.name;
          return element;
        }),
      );
    }
    const nextValue = selectedOption?.id || "";
    if (String(elements.featureModelSelect.value || "").trim() !== nextValue) {
      elements.featureModelSelect.value = nextValue;
    }
  }

  if (elements.featureModelBand) {
    elements.featureModelBand.textContent = selectedOption?.band || "Model";
  }
  if (elements.featureModelSummary) {
    elements.featureModelSummary.textContent = selectedOption?.summary || "Choose which model this tool should use.";
  }
}

function populateMonitorTimezoneOptions() {
  if (!elements.monitorScheduleTimezoneLabel) {
    return;
  }

  elements.monitorScheduleTimezoneLabel.title = getMonitorScheduleTimezone();
}

function updateTabButtons() {
  updateOpportunityNavigation();
  updateClientNavigation();
  for (const button of elements.tabButtons) {
    const isSettingsButton = button.dataset.tab === "settings";
    const isActive = isSettingsButton
      ? state.settingsOpen
      : !state.settingsOpen && button.dataset.tab === state.activeTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  }
}

function updateSettingsButtons() {
  state.settingsMode = normalizeSettingsMode(state.settingsMode);
  const modeContent = getSettingsModeContent(state.settingsMode);

  for (const button of elements.settingsButtons) {
    const isActive = button.dataset.settingsMode === state.settingsMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  }

  if (elements.settingsSwitcher) {
    elements.settingsSwitcher.classList.toggle("is-hidden", state.settingsMode === "users");
  }

  if (elements.settingsTitle) {
    elements.settingsTitle.textContent = modeContent.title;
  }
  if (elements.settingsDescription) {
    elements.settingsDescription.textContent = modeContent.description;
    elements.settingsDescription.classList.toggle("is-hidden", !modeContent.description);
  }

  const showAccount = state.settingsMode === "account";
  elements.accountSettingsPane.classList.toggle("is-hidden", !showAccount);
  elements.preferencesSettingsPane.classList.toggle("is-hidden", state.settingsMode !== "preferences");
}

function updatePanelVisibility() {
  const inStudio = state.activeTab === "features" && Boolean(state.selectedFeatureId);
  const inBilling = state.activeTab === "billing";
  const inPricing = state.activeTab === "pricing";
  const feature = inStudio ? getSelectedFeature() : null;
  const studioView = inStudio ? getSelectedFeatureStudioView(feature) : "overview";
  elements.appBar.classList.toggle("is-hidden", inStudio || inBilling || inPricing);
  elements.appView.classList.toggle("is-feature-page", inStudio);
  const isChatWorkspace = state.activeTab === "features" && !inStudio;
  elements.appView.classList.toggle("is-chat-workspace", isChatWorkspace);
  document.body.classList.toggle("is-chat-view", isChatWorkspace);
  elements.featuresPanel.classList.toggle("is-hidden", state.activeTab !== "features" || inStudio);
  elements.opportunitiesPanel?.classList.toggle("is-hidden", state.activeTab !== "opportunities");
  elements.clientsPanel?.classList.toggle("is-hidden", state.activeTab !== "clients");
  elements.personalDetailsPanel.classList.toggle("is-hidden", state.activeTab !== "personal-details");
  elements.featureStudioPanel.classList.toggle("is-hidden", !inStudio);
  elements.previewPanel.classList.toggle("is-hidden", state.activeTab !== "preview");
  elements.simulatorPanel.classList.toggle("is-hidden", state.activeTab !== "simulator");
  elements.billingPanel.classList.toggle("is-hidden", state.activeTab !== "billing");
  elements.pricingPanel.classList.toggle("is-hidden", state.activeTab !== "pricing");
  if (elements.featureStudioActivationSection && feature) {
    elements.featureStudioActivationSection.classList.toggle("is-hidden", studioView !== "activation");
  }
  syncSettingsPanelState();
}

function syncSettingsPanelState() {
  const panel = elements.settingsPanel;

  if (!panel) {
    return;
  }

  if (settingsPanelOpenFrame !== null) {
    window.cancelAnimationFrame(settingsPanelOpenFrame);
    settingsPanelOpenFrame = null;
  }

  if (settingsPanelCloseTimer !== null) {
    window.clearTimeout(settingsPanelCloseTimer);
    settingsPanelCloseTimer = null;
  }

  if (state.settingsOpen) {
    panel.classList.remove("is-hidden");
    document.body.dataset.modal = "settings";

    if (!panel.classList.contains("is-open")) {
      settingsPanelOpenFrame = window.requestAnimationFrame(() => {
        panel.classList.add("is-open");
        settingsPanelOpenFrame = null;
      });
    }

    return;
  }

  panel.classList.remove("is-open");

  if (panel.classList.contains("is-hidden")) {
    delete document.body.dataset.modal;
    return;
  }

  settingsPanelCloseTimer = window.setTimeout(() => {
    panel.classList.add("is-hidden");
    delete document.body.dataset.modal;
    settingsPanelCloseTimer = null;
  }, SETTINGS_PANEL_ANIMATION_MS);
}

function updatePreview() {
  const prompt = getSelectedPrompt();
  const scenario = SCENARIOS[prompt.scenario] ?? SCENARIOS.availability;
  elements.scenarioSelect.value = prompt.scenario;
  elements.approvalSender.textContent = scenario.sender || "Customer";
  elements.scenarioMessage.textContent = scenario.user;
  elements.responseMessage.textContent = buildResponseText(prompt);
  elements.compiledPrompt.textContent = buildCompiledPrompt();
}

function updateSettingsFields() {
  elements.signedInEmail.textContent = activeEmail;
  elements.displayNameInput.value = clientState.settings.displayName;
  elements.workspaceNameInput.value = clientState.settings.workspaceName;
  elements.timezoneSelect.value = clientState.settings.timezone;
  renderAdminUsersPane();
}

function updatePersonalDetailsFields() {
  const hasContent = hasAccountProfileContent();
  if (elements.profileBusinessSummaryInput) {
    elements.profileBusinessSummaryInput.value = clientState.profile.businessSummary;
  }
  if (elements.profileCustomerNotesInput) {
    elements.profileCustomerNotesInput.value = clientState.profile.customerNotes;
  }
  if (elements.profileAssistantGuidanceInput) {
    elements.profileAssistantGuidanceInput.value = clientState.profile.assistantGuidance;
  }
  if (elements.personalDetailsPreviewCard) {
    elements.personalDetailsPreviewCard.classList.toggle("is-hidden", !hasContent);
  }
  if (elements.personalDetailsPreview) {
    elements.personalDetailsPreview.textContent = buildAccountProfilePreviewText();
  }
}

function renderApp(options = {}) {
  updateOpportunityNavigation();
  updateClientNavigation();
  updateHeader();
  updateTabButtons();
  updateFeatureStudioHeader();
  updatePanelVisibility();
  updateAgentWorkspace();
  updateFeatureList();
  updateOpportunitiesPanel();
  updateFeatureActivationFields();
  populateMonitorTimezoneOptions();
  updateMonitorFields();
  updateReengagementFields();
  updatePromptFields();
  updatePreview();
  updateSimulatorPanel();
  updateBillingPanel();
  updatePricingPanel();
  updateSettingsButtons();
  updateSettingsFields();
  updatePersonalDetailsFields();
  syncWhatsAppConnectionPolling();
  syncScheduledActionsPolling();
  if (options.preserveStatus !== true) {
    setStatus("Saved");
  }
}

function renderAuth(preferredEmail = "", messageOverride = "") {
  const challengeEmail = normalizeEmail(authChallenge?.email || "");
  const showChallenge = Boolean(challengeEmail);
  const stage = showChallenge ? "code" : "email";
  const defaultMessage = showChallenge
    ? `A 6-digit code was sent to ${challengeEmail}.`
    : "We’ll send a code to your email.";

  elements.authCard.dataset.authStage = stage;
  elements.emailInput.value = challengeEmail || normalizeEmail(authSession?.email || preferredEmail || "");
  elements.otpPanel.setAttribute("aria-hidden", String(!showChallenge));
  elements.sendCodeButton.setAttribute("aria-label", showChallenge ? "Verify code" : "Send code");
  elements.authMessage.textContent = String(messageOverride || defaultMessage);
  elements.demoCodeText.textContent = showChallenge
    ? `Check ${challengeEmail} for the code. It expires in 10 minutes.`
    : "";
  elements.demoCodeText.classList.toggle("is-hidden", !showChallenge);
  clearOtpDigits();
  syncAuthControls();
}

function showAuthView(preferredEmail = activeEmail, messageOverride = "") {
  setView("auth");
  renderAuth(preferredEmail, messageOverride);
}

function refreshView() {
  if (isSignedIn()) {
    state.settingsMode = normalizeSettingsMode(state.settingsMode);
    const route = resolveRouteFromHash();
    const rawHash = window.location.hash.replace(/^#/, "");
    const restoredPrimaryTab = VALID_TABS.has(state.lastPrimaryTab) && state.lastPrimaryTab !== "settings"
      ? state.lastPrimaryTab
      : "features";

    if (route.tab === "settings") {
      // Treat the settings drawer as transient UI, not a reload destination.
      state.selectedFeatureId = null;
      state.selectedSimulatorId = null;
      closeFeatureStudioMenu();
      state.settingsOpen = false;
      state.activeTab = restoredPrimaryTab;
      state.lastPrimaryTab = state.activeTab;
      persistLastPrimaryTab();
      setHashForTab(state.activeTab);
    } else {
      state.settingsOpen = false;
      state.activeTab = route.tab || "features";
      state.selectedFeatureId = route.tab === "features" && route.featureId
        ? route.featureId
        : null;
      state.selectedSimulatorId = route.tab === "simulator" && route.featureId
        ? route.featureId
        : clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
      if (state.selectedFeatureId && !getFeatureById(state.selectedFeatureId)) {
        state.selectedFeatureId = clientState.features[0]?.id || null;
      }
      if (state.selectedSimulatorId && !clientState.simulator.approvals.some((approval) => approval.approvalId === state.selectedSimulatorId)) {
        state.selectedSimulatorId = clientState.simulator.approvals[0]?.approvalId || null;
      }
      if (state.activeTab === "features" && state.selectedFeatureId) {
        const feature = getFeatureById(state.selectedFeatureId);
        const selectedView = normalizeFeatureStudioView(route.subview);
        state.featureStudioView = selectedView || getDefaultFeatureStudioView(feature);
        setHashForTab("features", state.selectedFeatureId, state.featureStudioView);
      } else {
        state.featureStudioView = "overview";
      }
      state.lastPrimaryTab = state.activeTab;
      persistLastPrimaryTab();
      if (!route.tab) {
        setHashForTab(state.activeTab);
      } else if (state.activeTab === "simulator" && state.selectedSimulatorId) {
        setHashForTab("simulator", state.selectedSimulatorId);
      } else if (rawHash && rawHash !== route.tab) {
        setHashForTab(route.tab);
      }
    }

    setView("app");
    renderApp();
    if (state.activeTab === "billing") {
      void refreshBillingReportForActiveTab();
    }
    if (state.activeTab === "pricing") {
      void refreshPricingSnapshot();
    }
    if (state.activeTab === "opportunities") {
      void refreshOpportunities();
    }
    if (state.activeTab === "clients") {
      void refreshAdminUsers();
    }
    return;
  }

  showAuthView(activeEmail);
}

function validateEmail(email) {
  return /^\S+@\S+\.\S+$/.test(email);
}

function clearOtpDigits() {
  for (const digitInput of elements.otpDigits) {
    digitInput.value = "";
  }
}

function setOtpDigits(value) {
  const digits = String(value || "")
    .replace(/\D/g, "")
    .slice(0, elements.otpDigits.length);

  elements.otpDigits.forEach((digitInput, index) => {
    digitInput.value = digits[index] || "";
  });

  return digits;
}

function applyOtpDigits(value) {
  const digits = setOtpDigits(value);

  if (!digits) {
    return false;
  }

  if (!maybeAutoVerifyOtp()) {
    focusOtpDigit(Math.min(digits.length, elements.otpDigits.length - 1));
  }

  return true;
}

function maybeAutoVerifyOtp() {
  if (authBusy || !authChallenge?.email) {
    return false;
  }

  if (getOtpDigits().length !== elements.otpDigits.length) {
    return false;
  }

  void verifyOtpFlow();
  return true;
}

function getOtpDigits() {
  return elements.otpDigits
    .map((digitInput) => String(digitInput.value || "").replace(/\D/g, "").slice(0, 1))
    .join("");
}

function focusOtpDigit(index = 0) {
  const safeIndex = Math.max(0, Math.min(index, elements.otpDigits.length - 1));
  const digitInput = elements.otpDigits[safeIndex];

  if (!digitInput) {
    return;
  }

  digitInput.focus();

  if (typeof digitInput.select === "function") {
    digitInput.select();
  }
}

function focusFirstEmptyOtpDigit() {
  const emptyIndex = elements.otpDigits.findIndex((digitInput) => !String(digitInput.value || "").trim());
  focusOtpDigit(emptyIndex >= 0 ? emptyIndex : elements.otpDigits.length - 1);
}

function handleOtpDigitInput(event) {
  const digitInput = event.target;
  const index = elements.otpDigits.indexOf(digitInput);

  if (index < 0 || authBusy || !authChallenge?.email) {
    return;
  }

  const replacementDigits = String(event.data || "").replace(/\D/g, "");
  if (replacementDigits.length > 1) {
    applyOtpDigits(replacementDigits);
    return;
  }

  const digits = String(digitInput.value || "").replace(/\D/g, "");

  if (!digits) {
    digitInput.value = "";
    return;
  }

  if (digits.length > 1) {
    applyOtpDigits(digits);
    return;
  }

  digitInput.value = digits.slice(0, 1);

  const didAutoVerify = maybeAutoVerifyOtp();

  if (!didAutoVerify && index < elements.otpDigits.length - 1) {
    focusOtpDigit(index + 1);
  }
}

function handleOtpDigitBeforeInput(event) {
  if (authBusy || !authChallenge?.email) {
    return;
  }

  const incomingDigits = String(event.data || "").replace(/\D/g, "");

  if (incomingDigits.length <= 1) {
    return;
  }

  event.preventDefault();
  applyOtpDigits(incomingDigits);
}

function handleOtpDigitKeydown(event) {
  const digitInput = event.target;
  const index = elements.otpDigits.indexOf(digitInput);

  if (index < 0 || authBusy || !authChallenge?.email) {
    return;
  }

  if (event.key === "Enter") {
    event.preventDefault();
    void verifyOtpFlow();
    return;
  }

  if (event.key === "ArrowLeft" && index > 0) {
    event.preventDefault();
    focusOtpDigit(index - 1);
    return;
  }

  if (event.key === "ArrowRight" && index < elements.otpDigits.length - 1) {
    event.preventDefault();
    focusOtpDigit(index + 1);
    return;
  }

  if (event.key === "Backspace" && !digitInput.value && index > 0) {
    event.preventDefault();
    const previousInput = elements.otpDigits[index - 1];
    previousInput.value = "";
    focusOtpDigit(index - 1);
  }
}

function handleOtpDigitPaste(event) {
  if (authBusy || !authChallenge?.email) {
    return;
  }

  const pasted = String(event.clipboardData?.getData("text") || "").replace(/\D/g, "");

  if (!pasted) {
    return;
  }

  event.preventDefault();
  applyOtpDigits(pasted);
}

function handlePrimaryAuthAction() {
  if (authBusy) {
    return;
  }

  if (authChallenge?.email) {
    void verifyOtpFlow();
    return;
  }

  void startOtpFlow();
}

async function startOtpFlow() {
  const typedEmail = normalizeEmail(elements.emailInput.value);
  const email = typedEmail;

  if (!validateEmail(email)) {
    clearAuthChallenge();
    clearOtpDigits();
    renderAuth(typedEmail);
    openAuthAlert("Enter a valid email", "Use an email address like name@company.com.", {
      returnFocus: "email",
    });
    return;
  }

  authBusy = true;
  syncAuthControls();
  elements.authMessage.textContent = "Sending your code...";

  try {
    const response = await apiRequest("/api/auth/otp/request", {
      method: "POST",
      body: { email },
    });

    authChallenge = normalizeStoredChallenge({
      email: response.email || email,
      requestedAt: response.requestedAt || Date.now(),
      expiresAt: response.expiresAt || Date.now() + OTP_TTL_MS,
    });
    if (authChallenge) {
      persistJson(AUTH_CHALLENGE_KEY, authChallenge);
    }

    clearAuthSession();
    authBusy = false;
    closeAuthAlert();
    renderAuth(email);
    elements.demoCodeText.textContent = `Check ${email} for the code. It expires in 10 minutes.`;
    elements.demoCodeText.classList.remove("is-hidden");
    window.requestAnimationFrame(() => {
      focusOtpDigit(0);
    });
  } catch (error) {
    authBusy = false;
    const payload = error?.payload || {};
    const message = formatApiErrorMessage(error, "We couldn’t send the code. Please try again.");
    clearAuthChallenge();
    if (payload.error === "not_registered") {
      const friendlyMessage = "If you’d like access, contact me and I’ll set you up.";
      renderAuth(email, friendlyMessage);
      openAuthAlert("Let’s get you set up", friendlyMessage, { returnFocus: "email" });
      return;
    }

    renderAuth(email);
    openAuthAlert("Couldn’t send code", message, { returnFocus: "email" });
  }
}

function completeSignIn(session) {
  const email = normalizeEmail(session?.email || elements.emailInput.value || authChallenge?.email || "");
  const token = String(session?.sessionToken || "").trim();
  if (!email || !token) {
    return;
  }

  activeEmail = email;
  clientState = loadClientState(activeEmail);
  applyRemoteAccountProfile(session);
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
  authSession = {
    email: activeEmail,
    token,
    signedIn: true,
    signedInAt: Date.now(),
    issuedAt: session?.issuedAt || Date.now(),
    expiresAt: session?.expiresAt || 0,
    requestCountry: normalizeCountryCode(session?.requestCountry),
    isAdmin: Boolean(session?.isAdmin),
  };
  state.requestCountryCode = authSession.requestCountry;
  clearAuthChallenge();
  authBusy = false;
  closeAuthAlert();

  persistJson(AUTH_SESSION_KEY, authSession);

  state.activeTab = "features";
  state.settingsMode = "account";
  state.settingsOpen = false;
  state.lastPrimaryTab = "features";
  persistLastPrimaryTab();
  closeBillingHelp();
  state.billingReport = null;
  state.billingLoading = true;
  state.billingError = "";
  state.pricingSnapshot = null;
  state.pricingLoading = false;
  state.pricingError = "";
  state.paymentStatus = null;
  state.platformConnections = [];
  resetAdminState();
  setHashForTab("features");
  setView("app");
  renderApp();
  void refreshBillingReport();
  void refreshWhatsAppConnection();
  void refreshFeatureActivationStates();
  void refreshPlatformConnections({ render: false });
  if (canManageClients()) {
    void refreshAdminUsers({ render: false });
  }
}

async function verifyOtpFlow() {
  if (authBusy) {
    return;
  }

  const enteredCode = getOtpDigits();
  const email = normalizeEmail(elements.emailInput.value || authChallenge?.email || "");

  if (!authChallenge?.email) {
    openAuthAlert("Send a fresh code", "Request a new code to continue.", {
      returnFocus: "email",
    });
    return;
  }

  if (authChallenge.expiresAt && Date.now() > authChallenge.expiresAt) {
    clearAuthChallenge();
    renderAuth(email);
    openAuthAlert("Code expired", "That code expired. Request a new one.", {
      returnFocus: "email",
    });
    return;
  }

  if (enteredCode.length !== elements.otpDigits.length) {
    openAuthAlert("Incomplete code", "Enter the full 6-digit code.", {
      returnFocus: "otp",
    });
    return;
  }

  if (email !== normalizeEmail(authChallenge.email)) {
    openAuthAlert("Wrong email", "Use the same email address that requested the code.", {
      returnFocus: "email",
    });
    return;
  }

  authBusy = true;
  syncAuthControls();
  elements.authMessage.textContent = "Verifying your code...";

  try {
    const response = await apiRequest("/api/auth/otp/verify", {
      method: "POST",
      body: {
        email,
        code: enteredCode,
      },
    });

    completeSignIn(response);
  } catch (error) {
    authBusy = false;
    syncAuthControls();

    const payload = error?.payload || {};
    const message = formatApiErrorMessage(error, "That code is not correct.");

    if (payload.error === "expired" || payload.error === "missing_challenge" || payload.error === "too_many_attempts") {
      clearAuthChallenge();
      renderAuth(email);
      openAuthAlert("Code expired", message, {
        returnFocus: "email",
      });
      return;
    }

    if (payload.error === "incorrect") {
      openAuthAlert("Incorrect code", message, {
        returnFocus: "otp",
      });
      return;
    }

    openAuthAlert("Couldn’t verify code", message, {
      returnFocus: "otp",
    });
    return;
  }
}

async function signOut() {
  persistClientState();
  const previousEmail = normalizeEmail(authSession?.email || activeEmail || "");
  const token = String(authSession?.token || "").trim();
  if (token) {
    try {
      await apiRequest("/api/auth/logout", {
        method: "POST",
        body: { token },
      });
    } catch {
      // Ignore logout failures; the local session is still cleared.
    }
  }

  authSession = null;
  clearAuthChallenge();
  activeEmail = "";
  clientState = loadClientState(activeEmail);
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
  state.billingReport = null;
  state.billingLoading = false;
  state.billingError = "";
  state.pricingSnapshot = null;
  state.pricingLoading = false;
  state.pricingError = "";
  state.paymentStatus = null;
  state.platformConnections = [];
  state.requestCountryCode = "";
  state.settingsOpen = false;
  state.settingsMode = "account";
  state.lastPrimaryTab = "features";
  resetAdminState();
  persistLastPrimaryTab();
  closeBillingHelp();
  clearAllFeatureConfigAutosaves();

  persistJson(AUTH_SESSION_KEY, null);
  clearHash();
  setView("auth");
  renderAuth(previousEmail);
  closeAuthAlert();
}

function syncPromptField(key) {
  return (event) => {
    const feature = getSelectedFeature();

    if (!feature) {
      return;
    }

    feature.prompt[key] = event.target.value;
    persistClientState();
    updateHeader();
    updateFeatureStudioHeader();
    updatePreview();
    scheduleSelectedFeatureConfigAutosave(feature);
  };
}

function syncFeatureModelField(event) {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  const nextModel = normalizeFeatureModel(event.target.value, getSelectedFeatureSettings(feature).model);
  if (event.target.value !== nextModel) {
    event.target.value = nextModel;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  if (currentSettings.model === nextModel) {
    updateFeatureModelFields();
    return;
  }

  const nextSettings = buildSettingsForSave(feature, {
    ...currentSettings,
    model: nextModel,
  });

  feature.settings = nextSettings;
  persistClientState();
  updateFeatureStudioHeader();
  updateFeatureModelFields();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function syncDeliverySettingsField(key) {
  return (event) => {
    const feature = getSelectedFeature();
    if (!feature || (!isMonitorFeature(feature) && !isWhatsAppFeature(feature))) {
      return;
    }

    const currentSettings = getSelectedFeatureSettings(feature);
    let nextSettings;
    if (isMonitorFeature(feature)) {
      nextSettings = buildMonitorSettingsForSave(feature, {
        ...currentSettings,
        [key]: event.target.value,
      });
    } else {
      const deliveryPatch = key === "deliveryChannel"
        ? { deliveryChannels: normalizeWhatsAppToolDeliveryChannels(event.target.value) }
        : { [key]: event.target.value };
      const nextSource = {
        ...currentSettings,
        ...deliveryPatch,
      };
      nextSettings = buildSettingsForSave(feature, nextSource);
    }

    feature.settings = nextSettings;
    updateMonitorFields();
    persistClientState();
    updateFeatureStudioHeader();
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  };
}

function saveWhatsAppToolDeliveryChannels(nextChannels) {
  const feature = getSelectedFeature();
  if (!feature || !isWhatsAppFeature(feature)) {
    return false;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const deliveryChannels = normalizeWhatsAppToolDeliveryChannelsForFeature(feature, nextChannels, []);
  if (JSON.stringify(deliveryChannels) === JSON.stringify(getWhatsAppToolDeliveryChannels(currentSettings))) {
    updateMonitorFields();
    return false;
  }

  const nextSource = {
    ...currentSettings,
    deliveryChannels,
  };
  feature.settings = buildSettingsForSave(feature, nextSource);
  updateMonitorFields();
  persistClientState();
  updateFeatureStudioHeader();
  void flushSelectedFeatureConfigAutosave({
    featureId: feature.id,
    alertOnError: false,
    noChangesMessage: false,
  }).catch(() => {});
  return true;
}

function addWhatsAppToolDeliveryPlatform(platformId) {
  const option = getWhatsAppToolPlatformOption(platformId);
  if (!option) {
    return false;
  }
  const currentChannels = getWhatsAppToolDeliveryChannels();
  if (currentChannels.includes(option.id)) {
    return false;
  }
  const didSave = saveWhatsAppToolDeliveryChannels([...currentChannels, option.id]);
  if (didSave) {
    setStatus(`${option.label} platform added.`);
  }
  setDeliveryPlatformMenuOpen(false);
  return didSave;
}

function removeWhatsAppToolDeliveryPlatform(platformId) {
  const option = getWhatsAppToolPlatformOption(platformId);
  if (!option) {
    return false;
  }
  const currentChannels = getWhatsAppToolDeliveryChannels();
  const nextChannels = currentChannels.filter((channel) => channel !== option.id);
  const didSave = saveWhatsAppToolDeliveryChannels(nextChannels);
  if (didSave) {
    setStatus(`${option.label} platform removed.`);
  }
  return didSave;
}

function syncMonitorIntervalDaysField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return;
  }

  const rawValue = String(event.target.value || "").trim();
  if (!rawValue) {
    return;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const normalizedIntervalDays = normalizeMonitorIntervalDays(rawValue, currentSettings.intervalDays);
  const normalizedValue = String(normalizedIntervalDays);

  if (event.target.value !== normalizedValue) {
    event.target.value = normalizedValue;
  }
  if (currentSettings.intervalDays === normalizedIntervalDays) {
    return;
  }

  feature.settings = buildMonitorSettingsForSave(feature, {
    ...currentSettings,
    intervalDays: normalizedIntervalDays,
  });
  persistClientState();
  updateMonitorFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function syncMonitorManualOnlyField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return;
  }

  const manualOnly = Boolean(event.target.checked);
  const currentSettings = getSelectedFeatureSettings(feature);
  if (normalizeMonitorManualOnly(currentSettings.manualOnly) === manualOnly) {
    updateMonitorFields();
    return;
  }

  feature.settings = buildMonitorSettingsForSave(feature, {
    ...currentSettings,
    manualOnly,
    scheduleTimeLocal: manualOnly ? "" : currentSettings.scheduleTimeLocal,
    scheduleTimezone: manualOnly ? "" : currentSettings.scheduleTimezone,
  });
  persistClientState();
  updateMonitorFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
  setStatus(manualOnly ? "Manual runs enabled." : "Recurring schedule enabled.");
}

function syncMonitorScheduleTimeField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return;
  }

  const rawValue = String(event.target.value || "").trim();
  const normalizedTime = normalizeMonitorScheduleTime(rawValue, "");
  if (!normalizedTime) {
    return;
  }
  if (event.type !== "input" && event.target.value !== normalizedTime) {
    event.target.value = normalizedTime;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const currentScheduleTime = normalizeMonitorScheduleTime(currentSettings.scheduleTimeLocal);
  const nextTimezone = getWorkspaceTimeZone();
  if (currentScheduleTime === normalizedTime && normalizeMonitorScheduleTimezone(currentSettings.scheduleTimezone) === nextTimezone) {
    updateMonitorFields();
    return;
  }

  feature.settings = buildMonitorSettingsForSave(feature, {
    ...currentSettings,
    scheduleTimeLocal: normalizedTime,
    scheduleTimezone: nextTimezone,
  });
  persistClientState();
  updateMonitorFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function finalizeMonitorScheduleTimeField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return;
  }

  const normalizedTime = normalizeMonitorScheduleTime(event.target.value, getMonitorScheduleTime(feature));
  event.target.value = normalizedTime || getMonitorScheduleTime(feature);

  if (hasPendingFeatureConfigAutosave(feature.id)) {
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  }
}

function finalizeMonitorIntervalDaysField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const rawValue = String(event.target.value || "").trim();

  if (!rawValue) {
    event.target.value = String(currentSettings.intervalDays);
  } else {
    const normalizedValue = String(normalizeMonitorIntervalDays(rawValue, currentSettings.intervalDays));
    if (event.target.value !== normalizedValue) {
      event.target.value = normalizedValue;
    }
  }

  if (hasPendingFeatureConfigAutosave(feature.id)) {
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  }
}

function syncReengagementIntervalDaysField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }

  const rawValue = String(event.target.value || "").trim();
  if (!rawValue) {
    return;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const normalizedIntervalDays = normalizeMonitorIntervalDays(rawValue, currentSettings.intervalDays);
  const normalizedValue = String(normalizedIntervalDays);
  if (event.target.value !== normalizedValue) {
    event.target.value = normalizedValue;
  }
  if (currentSettings.intervalDays === normalizedIntervalDays) {
    return;
  }

  feature.settings = buildReengagementSettingsForSave(feature, {
    ...currentSettings,
    intervalDays: normalizedIntervalDays,
  });
  persistClientState();
  updateReengagementFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function syncReengagementScheduleTimeField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }

  const rawValue = String(event.target.value || "").trim();
  const normalizedTime = normalizeMonitorScheduleTime(rawValue, "");
  if (!normalizedTime) {
    return;
  }
  if (event.type !== "input" && event.target.value !== normalizedTime) {
    event.target.value = normalizedTime;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const nextTimezone = getWorkspaceTimeZone();
  if (
    normalizeMonitorScheduleTime(currentSettings.scheduleTimeLocal) === normalizedTime
    && normalizeMonitorScheduleTimezone(currentSettings.scheduleTimezone) === nextTimezone
  ) {
    updateReengagementFields();
    return;
  }

  feature.settings = buildReengagementSettingsForSave(feature, {
    ...currentSettings,
    scheduleTimeLocal: normalizedTime,
    scheduleTimezone: nextTimezone,
  });
  persistClientState();
  updateReengagementFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function syncReengagementInactivityValueField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }

  const rawValue = String(event.target.value || "").trim();
  if (!rawValue) {
    return;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const normalizedValue = normalizeReengagementInactivityValue(rawValue, currentSettings.inactivityValue);
  if (event.target.value !== String(normalizedValue)) {
    event.target.value = String(normalizedValue);
  }
  if (currentSettings.inactivityValue === normalizedValue) {
    return;
  }

  feature.settings = buildReengagementSettingsForSave(feature, {
    ...currentSettings,
    inactivityValue: normalizedValue,
  });
  persistClientState();
  updateReengagementFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function syncReengagementInactivityUnitField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const inactivityUnit = normalizeReengagementInactivityUnit(event.target.value, currentSettings.inactivityUnit);
  if (event.target.value !== inactivityUnit) {
    event.target.value = inactivityUnit;
  }
  if (currentSettings.inactivityUnit === inactivityUnit) {
    return;
  }

  feature.settings = buildReengagementSettingsForSave(feature, {
    ...currentSettings,
    inactivityUnit,
  });
  persistClientState();
  updateReengagementFields();
  updateFeatureStudioHeader();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function finalizeReengagementIntervalDaysField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }
  const currentSettings = getSelectedFeatureSettings(feature);
  const rawValue = String(event.target.value || "").trim();
  event.target.value = rawValue
    ? String(normalizeMonitorIntervalDays(rawValue, currentSettings.intervalDays))
    : String(currentSettings.intervalDays);
  if (hasPendingFeatureConfigAutosave(feature.id)) {
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  }
}

function finalizeReengagementScheduleTimeField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }
  const normalizedTime = normalizeMonitorScheduleTime(event.target.value, getReengagementScheduleTime(feature));
  event.target.value = normalizedTime || getReengagementScheduleTime(feature);
  if (hasPendingFeatureConfigAutosave(feature.id)) {
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  }
}

function finalizeReengagementInactivityValueField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isReengagementFeature(feature)) {
    return;
  }
  const currentSettings = getSelectedFeatureSettings(feature);
  const rawValue = String(event.target.value || "").trim();
  event.target.value = rawValue
    ? String(normalizeReengagementInactivityValue(rawValue, currentSettings.inactivityValue))
    : String(currentSettings.inactivityValue);
  if (hasPendingFeatureConfigAutosave(feature.id)) {
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  }
}

function syncMonitorWatchItemsField(event) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return;
  }

  state.monitorWatchItemDraft = event.target.value;
  persistMonitorWatchDraft(state.monitorWatchItemDraft, feature.id);
}

function createMonitorWatchItemBadge(item, index) {
  const badge = document.createElement("div");
  badge.className = "monitor-watch-badge";
  badge.setAttribute("role", "listitem");

  const label = document.createElement("span");
  label.className = "monitor-watch-badge-label";
  label.textContent = item || "Untitled";

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "monitor-watch-badge-remove";
  removeButton.dataset.monitorRemoveWatchItemIndex = String(index);
  removeButton.setAttribute("aria-label", `Remove ${item || "watch item"}`);
  removeButton.textContent = "×";

  badge.append(label, removeButton);
  return badge;
}

function renderMonitorWatchItems(items = []) {
  if (!elements.monitorWatchItemsList) {
    return;
  }

  const watchItems = normalizeMonitorWatchItems(items);
  if (!watchItems.length) {
    const empty = document.createElement("p");
    empty.className = "monitor-watch-badge-empty";
    empty.textContent = "Items you add show up here.";
    elements.monitorWatchItemsList.replaceChildren(empty);
    return;
  }

  elements.monitorWatchItemsList.replaceChildren(
    ...watchItems.map((item, index) => createMonitorWatchItemBadge(item, index)),
  );
}

function setMonitorWatchItems(items, options = {}) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return false;
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const nextSettings = buildMonitorSettingsForSave(feature, {
    ...currentSettings,
    watchItems: items,
  });

  if (JSON.stringify(nextSettings.watchItems) === JSON.stringify(currentSettings.watchItems)) {
    if (options.clearDraft === true) {
      state.monitorWatchItemDraft = "";
      persistMonitorWatchDraft("", feature.id);
      if (elements.monitorWatchItemInput) {
        elements.monitorWatchItemInput.value = "";
      }
    }
    if (options.focusInput !== false) {
      window.requestAnimationFrame(() => {
        elements.monitorWatchItemInput?.focus();
      });
    }
    return false;
  }

  feature.settings = nextSettings;
  if (options.clearDraft === true) {
    state.monitorWatchItemDraft = "";
    persistMonitorWatchDraft("", feature.id);
  }
  persistClientState();
  updateMonitorFields();
  updateFeatureStudioHeader();
  void flushSelectedFeatureConfigAutosave({
    featureId: feature.id,
    alertOnError: false,
    noChangesMessage: false,
  }).catch(() => {});

  if (options.focusInput !== false) {
    window.requestAnimationFrame(() => {
      elements.monitorWatchItemInput?.focus();
    });
  }
  return true;
}

function addMonitorWatchItems(rawValue = state.monitorWatchItemDraft || "", options = {}) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return false;
  }

  const nextItems = normalizeMonitorWatchItems(rawValue);
  if (!nextItems.length) {
    state.monitorWatchItemDraft = String(rawValue || "");
    persistMonitorWatchDraft(state.monitorWatchItemDraft, feature.id);
    if (options.focusInput !== false) {
      window.requestAnimationFrame(() => {
        elements.monitorWatchItemInput?.focus();
      });
    }
    return false;
  }

  const currentItems = getSelectedFeatureSettings(feature).watchItems;
  const didChange = setMonitorWatchItems([...currentItems, ...nextItems], {
    clearDraft: true,
    focusInput: options.focusInput !== false,
  });
  if (didChange && options.announce !== false) {
    setStatus("Watch item added.");
  }
  return didChange;
}

function finalizeMonitorWatchItemsField(event) {
  const draftValue = String(event.target.value || "");
  addMonitorWatchItems(draftValue, { focusInput: false, announce: false });
}

function removeMonitorWatchItem(index) {
  const feature = getSelectedFeature();
  if (!feature || !isMonitorFeature(feature)) {
    return false;
  }

  const currentItems = getSelectedFeatureSettings(feature).watchItems;
  const itemIndex = Number.parseInt(index, 10);
  if (!Number.isInteger(itemIndex) || itemIndex < 0 || itemIndex >= currentItems.length) {
    return false;
  }

  const nextItems = currentItems.filter((_, currentIndex) => currentIndex !== itemIndex);
  const didChange = setMonitorWatchItems(nextItems);
  if (didChange) {
    setStatus(nextItems.length ? "Watch item removed." : "Watch list cleared.");
  }
  return didChange;
}

function getMonitorFieldElement(field) {
  const fieldMap = {
    watchItems: elements.monitorWatchItemInput,
    manualOnly: elements.monitorManualOnly,
    intervalDays: elements.monitorIntervalDays,
    scheduleTimeLocal: elements.monitorScheduleTime,
    scheduleTimezone: elements.monitorScheduleTime,
    deliveryChannel: elements.monitorDeliveryChannel,
    deliveryChannels: elements.deliveryPlatformAddButton || elements.monitorDeliveryChannel,
    telegramChatId: elements.monitorTelegramChatId,
  };

  return fieldMap[field] || elements.monitorWatchItemInput || null;
}

function syncSettingsField(key) {
  return (event) => {
    clientState.settings[key] = event.target.value;
    persistClientState();
    updateHeader();
    updateSettingsFields();
    setStatus("Saved");
  };
}

function syncAccountProfileField(key) {
  return (event) => {
    clientState.profile[key] = event.target.value;
    persistClientState();
    updatePersonalDetailsFields();
    scheduleAccountProfileAutosave();
  };
}

function handleMenuAction(action) {
  if (action === "personal-details") {
    setActiveTab("personal-details");
    return;
  }

  if (action === "billing") {
    setActiveTab("billing");
    return;
  }

  if (action === "pricing") {
    setActiveTab("pricing");
    return;
  }

  if (action === "admin-users") {
    openAdminUsersList();
    return;
  }

  if (action === "settings") {
    openSettings("account");
    return;
  }

  if (action === "logout") {
    void signOut();
  }
}

async function bootstrapAuthState() {
  setView("loading");

  const storedSession = normalizeStoredSession(loadJson(AUTH_SESSION_KEY, null));
  authChallenge = normalizeStoredChallenge(loadJson(AUTH_CHALLENGE_KEY, null));
  activeEmail = normalizeEmail(storedSession?.email || authChallenge?.email || "");
  clientState = loadClientState("");
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;

  const applyRestoredSession = (response, fallbackSession = null) => {
    authSession = normalizeStoredSession({
      email: response.email || fallbackSession?.email || "",
      token: response.token || fallbackSession?.token || "",
      signedInAt: response.issuedAt || fallbackSession?.signedInAt || Date.now(),
      expiresAt: response.expiresAt || fallbackSession?.expiresAt || 0,
      requestCountry: response.requestCountry || fallbackSession?.requestCountry || "",
      isAdmin: response.isAdmin,
    });
    state.requestCountryCode = normalizeCountryCode(response.requestCountry || authSession?.requestCountry);
    activeEmail = normalizeEmail(authSession?.email || "");
    clientState = loadClientState(activeEmail);
    state.scheduledActions = [];
    state.scheduledActionsLoading = false;
    state.scheduledActionsError = "";
    state.scheduledActionsFailureCount = 0;
    state.scheduledActionsLastError = "";
    state.scheduledActionsLastErrorAt = 0;
    state.scheduledActionsLoadedAt = 0;
    state.selectedScheduledActionId = "";
    state.agentAddToolMenuOpen = false;
    applyRemoteAccountProfile(response);
    state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
    clearAuthChallenge();
    persistJson(AUTH_SESSION_KEY, authSession);
    state.billingReport = null;
    state.billingLoading = true;
    state.billingError = "";
    state.pricingSnapshot = null;
    state.pricingLoading = false;
    state.pricingError = "";
    state.paymentStatus = null;
    state.platformConnections = [];
    resetAdminState();
    refreshView();
    void refreshBillingReport();
    void refreshWhatsAppConnection();
    void refreshFeatureActivationStates();
    void refreshPlatformConnections({ render: false });
    if (canManageClients()) {
      void refreshAdminUsers({ render: false });
    }
  };

  const tryRestoreSession = async (headers = {}, fallbackSession = null) => {
    const response = await apiRequest("/api/auth/session", { headers });
    applyRestoredSession(response, fallbackSession);
  };

  if (storedSession?.token) {
    try {
      await tryRestoreSession({
        Authorization: `Bearer ${storedSession.token}`,
      }, storedSession);
      return;
    } catch (error) {
      const status = Number(error?.status || 0);
      if (status === 401 || status === 403) {
        try {
          await tryRestoreSession({}, storedSession);
          return;
        } catch (cookieError) {
          const cookieStatus = Number(cookieError?.status || 0);
          if (cookieStatus !== 401 && cookieStatus !== 403) {
            authSession = null;
            showAuthView(activeEmail);
            openAuthAlert(
              "Couldn’t verify session",
              formatApiErrorMessage(cookieError, "We couldn’t verify your session. Please sign in again."),
              { returnFocus: "email" },
            );
            return;
          }
          clearAuthSession();
        }
      } else {
        authSession = null;
        showAuthView(activeEmail);
        openAuthAlert(
          "Couldn’t verify session",
          formatApiErrorMessage(error, "We couldn’t verify your session. Please sign in again."),
          { returnFocus: "email" },
        );
        return;
      }
    }
  }

  try {
    await tryRestoreSession();
    return;
  } catch (error) {
    const status = Number(error?.status || 0);
    if (status !== 401 && status !== 403) {
      authSession = null;
      showAuthView(activeEmail);
      openAuthAlert(
        "Couldn’t verify session",
        formatApiErrorMessage(error, "We couldn’t verify your session. Please sign in again."),
        { returnFocus: "email" },
      );
      return;
    }
  }

  activeEmail = normalizeEmail(authChallenge?.email || storedSession?.email || "");
  state.requestCountryCode = normalizeCountryCode(storedSession?.requestCountry);
  clientState = loadClientState(activeEmail);
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
  state.billingReport = null;
  state.billingLoading = false;
  state.billingError = "";
  state.pricingSnapshot = null;
  state.pricingLoading = false;
  state.pricingError = "";
  state.paymentStatus = null;
  refreshView();
}

function bindEvents() {
  ensureBillingMenuItem();

  elements.sendCodeButton.addEventListener("click", () => {
    void handlePrimaryAuthAction();
  });
  elements.authAlertDismissButton.addEventListener("click", handleAuthAlertPrimaryAction);
  elements.authAlertSecondaryButton.addEventListener("click", handleAuthAlertSecondaryAction);
  elements.authAlertOverlay.addEventListener("click", (event) => {
    if (event.target === elements.authAlertOverlay && authAlertBackdropDismiss) {
      handleAuthAlertSecondaryAction();
    }
  });
  elements.changeEmailButton.addEventListener("click", () => {
    clearAuthChallenge();
    closeAuthAlert();
    clearOtpDigits();
    renderAuth();
    elements.emailInput.focus();
  });
  elements.signOutButton.addEventListener("click", () => {
    void signOut();
  });
  elements.closeSettingsButton.addEventListener("click", closeSettings);
  elements.backToFeaturesButton.addEventListener("click", () => {
    if (state.featureStudioView === "history") {
      setFeatureStudioView("editor");
      return;
    }

    if (state.featureStudioView === "activation") {
      setFeatureStudioView(getActivationBackView());
      return;
    }

    closeFeatureStudio();
  });
  if (elements.billingRefreshButton) {
    elements.billingRefreshButton.addEventListener("click", () => {
      void refreshBillingReport({ force: true });
    });
  }
  if (elements.billingHelpButton) {
    elements.billingHelpButton.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleBillingHelp();
    });
  }
  if (elements.featureStudioLaunchButton) {
    elements.featureStudioLaunchButton.addEventListener("click", () => {
      const feature = getSelectedFeature();
      if (!feature) {
        return;
      }

      if (usesEditorSetup(feature) || isFeatureSetupComplete(feature)) {
        setFeatureStudioView("editor");
        setStatus(usesEditorSetup(feature) && !isFeatureSetupComplete(feature) ? "Continue setup in the tool editor." : "Tool editor opened.");
        return;
      }

      startFeatureActivation();
    });
  }
  if (elements.featureStudioActivationSection) {
    elements.featureStudioActivationSection.addEventListener("click", (event) => {
      const activationButton = event.target.closest("#featureStudioActivationButton");
      if (!activationButton || activationButton.disabled) {
        return;
      }

      event.preventDefault();
      void activateSelectedFeature();
    });
  }
  if (elements.featureStudioActivationButton) {
    elements.featureStudioActivationButton.addEventListener("click", () => {
      void activateSelectedFeature();
    });
  }
  if (elements.featureStudioOverviewButton) {
    elements.featureStudioOverviewButton.addEventListener("click", () => {
      setFeatureStudioView("overview");
    });
  }
  if (elements.featureStudioEditorButton) {
    elements.featureStudioEditorButton.addEventListener("click", () => {
      setFeatureStudioView("editor");
    });
  }
  if (elements.featureStudioEditorToggleButton) {
    elements.featureStudioEditorToggleButton.addEventListener("click", () => {
      void toggleSelectedFeatureEditorActivation();
    });
  }
  if (elements.featureStudioWhatsAppSampleButton) {
    elements.featureStudioWhatsAppSampleButton.addEventListener("click", () => {
      void sendSelectedWhatsAppReplySample();
    });
  }
  if (elements.featureStudioWhatsAppHistoryButton) {
    elements.featureStudioWhatsAppHistoryButton.addEventListener("click", () => {
      openWhatsAppHistory();
    });
  }
  if (elements.whatsappHistoryFileInput) {
    elements.whatsappHistoryFileInput.addEventListener("change", () => {
      state.whatsappHistoryImportError = "";
      const fileCount = elements.whatsappHistoryFileInput.files?.length || 0;
      if (fileCount) {
        state.whatsappHistoryImportStatus = `Reading ${fileCount} chat file${fileCount === 1 ? "" : "s"}...`;
        renderWhatsAppHistory();
        void importWhatsAppHistoryExports();
        return;
      }
      state.whatsappHistoryImportStatus = "";
      renderWhatsAppHistory();
    });
  }
  if (elements.whatsappHistoryDeleteButton) {
    elements.whatsappHistoryDeleteButton.addEventListener("click", () => {
      deleteSelectedWhatsAppHistoryConversation();
    });
  }
  if (elements.whatsappHistoryConversationList) {
    elements.whatsappHistoryConversationList.addEventListener("click", (event) => {
      const target = getEventTargetElement(event);
      const item = target?.closest("[data-conversation-id]");
      if (!item) {
        return;
      }

      selectWhatsAppHistoryConversation(item.dataset.conversationId);
    });
  }
  if (elements.featureStudioMonitorRunButton) {
    elements.featureStudioMonitorRunButton.addEventListener("click", () => {
      if (monitorManualRunBusy && getSelectedFeature()?.id === monitorManualRunTargetId) {
        void requestMonitorManualRunCancellation();
        return;
      }
      if (isReengagementFeature(getSelectedFeature())) {
        void runSelectedReengagementDemo();
        return;
      }
      void runSelectedMonitorNow();
    });
  }
  if (elements.featureActivationBusinessAccountIdHelpButton) {
    elements.featureActivationBusinessAccountIdHelpButton.addEventListener("click", () => {
      openWhatsAppIdsHelp(elements.featureActivationBusinessAccountIdHelpButton);
    });
  }
  if (elements.featureActivationPhoneNumberIdHelpButton) {
    elements.featureActivationPhoneNumberIdHelpButton.addEventListener("click", () => {
      openWhatsAppIdsHelp(elements.featureActivationPhoneNumberIdHelpButton);
    });
  }
  if (elements.featureActivationBusinessAccountIdInput) {
    elements.featureActivationBusinessAccountIdInput.addEventListener("input", syncFeatureActivationField("business_account_id"));
  }
  if (elements.featureActivationPhoneNumberIdInput) {
    elements.featureActivationPhoneNumberIdInput.addEventListener("input", syncFeatureActivationField("phone_number_id"));
  }
  if (elements.featureActivationAccessTokenInput) {
    elements.featureActivationAccessTokenInput.addEventListener("input", syncFeatureActivationField("access_token"));
    elements.featureActivationAccessTokenInput.addEventListener("focus", handleFeatureActivationAccessTokenFocus);
    elements.featureActivationAccessTokenInput.addEventListener("blur", handleFeatureActivationAccessTokenBlur);
  }
  if (elements.featureActivationOwnerWaIdInput) {
    elements.featureActivationOwnerWaIdInput.addEventListener("input", syncFeatureActivationField("owner_wa_id"));
  }
  if (elements.billingHelpCloseButton) {
    elements.billingHelpCloseButton.addEventListener("click", () => {
      closeBillingHelp();
    });
  }
  if (elements.billingHelpPopover) {
    elements.billingHelpPopover.addEventListener("click", (event) => {
      if (event.target === elements.billingHelpPopover) {
        closeBillingHelp();
      }
    });
  }
  if (elements.billingBackButton) {
    elements.billingBackButton.addEventListener("click", () => {
      setActiveTab("features");
      window.scrollTo(0, 0);
    });
  }
  if (elements.pricingBackButton) {
    elements.pricingBackButton.addEventListener("click", () => {
      setActiveTab("features");
      window.scrollTo(0, 0);
    });
  }
  if (elements.adminUsersPane) {
    elements.adminUsersPane.addEventListener("focusin", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || target.dataset.adminFeatureSearchInput !== "true") {
        return;
      }

      if (!state.adminFeaturePickerOpen) {
        const caret = target.selectionStart;
        state.adminFeaturePickerOpen = true;
        renderAdminUsersPane();
        focusAdminFeatureSearchInput(caret);
      }
    });

    elements.adminUsersPane.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) {
        return;
      }

      if (target.dataset.adminSearchInput === "true") {
        const caret = target.selectionStart;
        state.adminUserSearch = target.value;
        renderAdminUsersPane();
        const nextInput = elements.adminUsersPane.querySelector('[data-admin-search-input="true"]');
        if (nextInput instanceof HTMLInputElement) {
          nextInput.focus();
          if (typeof caret === "number") {
            nextInput.setSelectionRange(caret, caret);
          }
        }
        return;
      }

      if (target.dataset.adminFeatureSearchInput === "true") {
        const caret = target.selectionStart;
        state.adminFeatureSearch = target.value;
        state.adminFeaturePickerOpen = true;
        renderAdminUsersPane();
        focusAdminFeatureSearchInput(caret);
        return;
      }

      if (target.dataset.adminNewEmail === "true") {
        state.adminNewUserEmail = target.value;
      }

      if (target.dataset.adminNewDisplayName === "true") {
        state.adminNewUserDisplayName = target.value;
      }

      if (target.dataset.adminEditEmail === "true") {
        state.adminEditUserEmail = target.value;
      }

      if (target.dataset.adminEditDisplayName === "true") {
        state.adminEditUserDisplayName = target.value;
      }

      if (state.adminUsersError) {
        state.adminUsersError = "";
        if (state.adminView === "add" || state.adminView === "edit") {
          renderAdminUsersPane();
        } else {
          syncAdminUsersError();
        }
      }
    });

    elements.adminUsersPane.addEventListener("change", (event) => {
      const target = event.target;
      if (target instanceof HTMLSelectElement && target.dataset.adminClientTypeUser) {
        void saveAdminUserClientType(target.dataset.adminClientTypeUser || "", target.value);
        return;
      }

      if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") {
        return;
      }

      const activeUserEmail = normalizeEmail(target.dataset.adminActiveUser || "");
      if (activeUserEmail) {
        void saveAdminUserStatus(activeUserEmail, target.checked);
        return;
      }

      const featureId = String(target.dataset.adminFeatureId || "").trim();
      if (!featureId) {
        return;
      }

      const userEmail = normalizeEmail(target.dataset.adminUserEmail || "");
      if (!userEmail) {
        return;
      }

      const nextFeatureIds = new Set(getAdminUserDraftFeatureIds(userEmail));
      if (target.checked) {
        nextFeatureIds.add(featureId);
      } else {
        nextFeatureIds.delete(featureId);
      }
      setAdminUserDraftFeatureIds(userEmail, Array.from(nextFeatureIds));
      queueAdminUserFeatureAutosave(userEmail);
      renderAdminUsersPane();
    });

    elements.adminUsersPane.addEventListener("click", (event) => {
      const target = getEventTargetElement(event);
      if (!target) {
        return;
      }

      const openUserButton = target.closest("[data-admin-open-user]");
      if (openUserButton) {
        openAdminUserDetail(openUserButton.dataset.adminOpenUser || "");
        return;
      }

      const openAddUserButton = target.closest("[data-admin-open-add-user]");
      if (openAddUserButton) {
        openAdminAddUser();
        return;
      }

      const openEditUserButton = target.closest("[data-admin-open-edit-user]");
      if (openEditUserButton) {
        openAdminEditUser(openEditUserButton.dataset.adminOpenEditUser || "");
        return;
      }

      const addFeatureButton = target.closest("[data-admin-add-feature]");
      if (addFeatureButton) {
        addAdminUserDraftFeature(
          addFeatureButton.dataset.adminUserEmail || "",
          addFeatureButton.dataset.adminAddFeature || "",
        );
        queueAdminUserFeatureAutosave(addFeatureButton.dataset.adminUserEmail || "");
        state.adminFeatureSearch = "";
        state.adminFeaturePickerOpen = true;
        renderAdminUsersPane();
        focusAdminFeatureSearchInput();
        return;
      }

      const removeFeatureButton = target.closest("[data-admin-remove-feature]");
      if (removeFeatureButton) {
        removeAdminUserDraftFeature(
          removeFeatureButton.dataset.adminUserEmail || "",
          removeFeatureButton.dataset.adminRemoveFeature || "",
        );
        queueAdminUserFeatureAutosave(removeFeatureButton.dataset.adminUserEmail || "");
        renderAdminUsersPane();
        return;
      }

      const createUserButton = target.closest("[data-admin-create-user]");
      if (createUserButton) {
        void addAdminUser();
        return;
      }

      const cancelAddButton = target.closest("[data-admin-cancel-add-user]");
      if (cancelAddButton) {
        state.adminUsersError = "";
        openAdminUsersList({ preserveSearch: true, refresh: false });
        return;
      }

      const cancelEditButton = target.closest("[data-admin-cancel-edit-user]");
      if (cancelEditButton) {
        state.adminUsersError = "";
        state.adminEditUserEmail = "";
        state.adminEditUserDisplayName = "";
        openAdminUserDetail(state.adminSelectedUserEmail);
        return;
      }

      const saveEditButton = target.closest("[data-admin-save-edit-user]");
      if (saveEditButton) {
        void saveAdminUserDetails();
        return;
      }

      const deleteUserButton = target.closest("[data-admin-delete-user]");
      if (deleteUserButton) {
        void deleteAdminUser(deleteUserButton.dataset.adminDeleteUser || "");
        return;
      }
    });

    elements.adminUsersPane.addEventListener("keydown", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) {
        return;
      }

      if (target.dataset.adminFeatureSearchInput === "true" && event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        state.adminFeatureSearch = "";
        state.adminFeaturePickerOpen = false;
        renderAdminUsersPane();
        return;
      }

      if (event.key !== "Enter") {
        return;
      }

      if (target.dataset.adminNewEmail === "true" || target.dataset.adminNewDisplayName === "true") {
        event.preventDefault();
        void addAdminUser();
      }
    });
  }

  elements.settingsPanel.addEventListener("click", (event) => {
    if (event.target === elements.settingsPanel) {
      closeSettings();
    }
  });

  elements.accountMenuButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMenu();
  });

  for (const button of elements.tabButtons) {
    button.addEventListener("click", () => {
      setActiveTab(button.dataset.tab || "features");
    });
  }

  if (elements.agentComposerForm) {
    elements.agentComposerForm.addEventListener("submit", handleAgentComposerSubmit);
  }

  if (elements.agentComposerInput) {
    elements.agentComposerInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleAgentComposerSubmit(event);
      }
    });
    elements.agentComposerInput.addEventListener("paste", handleAgentComposerPaste);
  }

  for (const button of elements.agentPromptButtons) {
    button.addEventListener("click", () => {
      if (elements.agentComposerInput) {
        elements.agentComposerInput.value = button.dataset.agentPrompt || "";
      }
      handleAgentComposerSubmit();
    });
  }

  if (elements.featuresPanel) {
    elements.featuresPanel.addEventListener("click", handleAgentWorkspaceClick);
  }

  if (elements.agentToolsPanel) {
    elements.agentToolsPanel.addEventListener("click", handleAgentWorkspaceClick);
  }

  if (elements.agentAddToolMenu) {
    elements.agentAddToolMenu.addEventListener("click", handleAgentWorkspaceClick);
  }

  if (elements.agentToolsToggleButton) {
    elements.agentToolsToggleButton.addEventListener("click", () => {
      const isOpen = elements.agentToolsPanel?.classList.contains("is-open");
      setAgentToolsOpen(!isOpen);
    });
  }

  if (elements.agentToolsCloseButton) {
    elements.agentToolsCloseButton.addEventListener("click", () => {
      setAgentToolsOpen(false);
    });
  }

  if (elements.agentAddToolButton) {
    elements.agentAddToolButton.addEventListener("click", () => {
      setAgentAddToolMenuOpen(!state.agentAddToolMenuOpen);
    });
  }
  if (elements.agentAddToolBackdrop) {
    elements.agentAddToolBackdrop.addEventListener("click", () => {
      setAgentAddToolMenuOpen(false);
    });
  }

  if (elements.agentActionsRefreshButton) {
    elements.agentActionsRefreshButton.addEventListener("click", () => {
      void refreshScheduledActions({ userInitiated: true });
    });
  }

  for (const actionList of [elements.agentPendingActionList, elements.agentCompletedActionList]) {
    actionList?.addEventListener("click", handleScheduledActionListClick, { capture: true });
  }

  if (elements.agentHistoryToggleButton) {
    elements.agentHistoryToggleButton.addEventListener("click", () => {
      state.agentHistoryExpanded = !state.agentHistoryExpanded;
      renderAgentActions();
    });
  }

  if (elements.agentActionDetailBackButton) {
    elements.agentActionDetailBackButton.addEventListener("click", () => {
      state.selectedScheduledActionId = "";
      renderAgentActions();
    });
  }

  document.addEventListener("visibilitychange", () => {
    syncScheduledActionsPolling();
    if (document.visibilityState === "visible" && isSignedIn()) {
      void refreshScheduledActions();
    }
  });

  if (elements.opportunitiesRefreshButton) {
    elements.opportunitiesRefreshButton.addEventListener("click", () => {
      void refreshOpportunities();
    });
  }

  for (const button of elements.settingsButtons) {
    button.addEventListener("click", () => {
      setSettingsMode(button.dataset.settingsMode || "account");
    });
  }

  for (const item of Array.from(elements.accountMenu.querySelectorAll("[data-menu-action]"))) {
    item.addEventListener("click", () => {
      handleMenuAction(item.dataset.menuAction || "");
      closeMenu();
    });
  }

  document.addEventListener("click", (event) => {
    const billingHelpButton = elements.billingHelpButton;
    const billingHelpPopover = elements.billingHelpPopover;
    const target = getEventTargetElement(event);
    const pickerTarget = target?.closest("[data-admin-feature-picker=\"true\"]") || null;
    if (
      state.billingHelpOpen
      && billingHelpPopover
      && billingHelpButton
      && !billingHelpPopover.contains(event.target)
      && !billingHelpButton.contains(event.target)
    ) {
      closeBillingHelp();
    }

    if (state.adminFeaturePickerOpen && !pickerTarget) {
      state.adminFeaturePickerOpen = false;
      renderAdminUsersPane();
    }

    if (
      state.agentAddToolMenuOpen
      && elements.agentAddToolMenu
      && elements.agentAddToolButton
      && !elements.agentAddToolMenu.contains(event.target)
      && !elements.agentAddToolButton.contains(event.target)
    ) {
      setAgentAddToolMenuOpen(false);
    }

    if (
      elements.deliveryPlatformMenu
      && elements.deliveryPlatformManager
      && !elements.deliveryPlatformMenu.hidden
      && !elements.deliveryPlatformManager.contains(event.target)
    ) {
      setDeliveryPlatformMenuOpen(false);
    }

    if (!elements.accountMenu.contains(event.target) && !elements.accountMenuButton.contains(event.target)) {
      closeMenu();
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (state.authAlertOpen) {
        if (authAlertEscapeDismiss) {
          handleAuthAlertSecondaryAction();
        }
        return;
      }

      if (state.billingHelpOpen) {
        closeBillingHelp();
        return;
      }

      if (state.agentAddToolMenuOpen) {
        setAgentAddToolMenuOpen(false);
        return;
      }

      if (elements.deliveryPlatformMenu && !elements.deliveryPlatformMenu.hidden) {
        setDeliveryPlatformMenuOpen(false);
        return;
      }

      if (state.settingsOpen) {
        closeSettings();
      } else {
        closeMenu();
      }
    }
  });

  window.addEventListener("hashchange", () => {
    if (!isSignedIn()) {
      return;
    }

    state.settingsMode = normalizeSettingsMode(state.settingsMode);
    const route = resolveRouteFromHash();
    const rawHash = window.location.hash.replace(/^#/, "");

    if (route.tab === "settings") {
      state.selectedFeatureId = null;
      state.selectedSimulatorId = null;
      if (!state.settingsOpen) {
        openSettings(state.settingsMode);
      }
      return;
    }

    if (route.tab) {
      state.settingsOpen = false;
      closeFeatureStudioMenu();
      if (route.tab !== state.activeTab) {
        state.activeTab = route.tab;
      }
      state.selectedFeatureId = route.tab === "features" && route.featureId
        ? route.featureId
        : null;
      state.selectedSimulatorId = route.tab === "simulator" && route.featureId
        ? route.featureId
        : state.selectedSimulatorId;
      if (state.selectedFeatureId && !getFeatureById(state.selectedFeatureId)) {
        state.selectedFeatureId = clientState.features[0]?.id || null;
      }
      if (state.selectedSimulatorId && !clientState.simulator.approvals.some((approval) => approval.approvalId === state.selectedSimulatorId)) {
        state.selectedSimulatorId = clientState.simulator.approvals[0]?.approvalId || null;
      }
      if (state.activeTab === "features" && state.selectedFeatureId) {
        const feature = getFeatureById(state.selectedFeatureId);
        const defaultView = getDefaultFeatureStudioView(feature);
        state.featureStudioView = normalizeFeatureStudioView(route.subview) || defaultView;
        setHashForTab("features", state.selectedFeatureId, state.featureStudioView);
      } else if (state.activeTab === "simulator" && state.selectedSimulatorId) {
        setHashForTab("simulator", state.selectedSimulatorId);
      } else if (rawHash && rawHash !== route.tab) {
        setHashForTab(route.tab);
      }
      state.lastPrimaryTab = route.tab;
      persistLastPrimaryTab();
      renderApp();
      if (route.tab === "billing") {
        void refreshBillingReportForActiveTab();
      }
      if (route.tab === "pricing") {
        void refreshPricingSnapshot();
      }
      if (route.tab === "opportunities") {
        void refreshOpportunities();
      }
      if (route.tab === "clients") {
        void refreshAdminUsers();
      }
      return;
    }

    if (!route.tab) {
      setHashForTab(state.settingsOpen ? "settings" : state.activeTab);
    }
  });

  window.addEventListener("pagehide", () => {
    if (accountProfileAutosaveTimer !== null) {
      clearAccountProfileAutosaveTimer();
      sendAccountProfileKeepalive();
    }
    clearAllFeatureConfigAutosaves();
    for (const feature of clientState.features) {
      if (hasFeatureConfigChanges(feature)) {
        sendFeatureConfigKeepalive(feature);
      }
    }
  });

  elements.emailInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void handlePrimaryAuthAction();
    }
  });

  for (const digitInput of elements.otpDigits) {
    digitInput.addEventListener("beforeinput", handleOtpDigitBeforeInput);
    digitInput.addEventListener("input", handleOtpDigitInput);
    digitInput.addEventListener("keydown", handleOtpDigitKeydown);
    digitInput.addEventListener("paste", handleOtpDigitPaste);
  }

  elements.toneGuidance.addEventListener("input", syncPromptField("toneGuidance"));
  elements.responseStyle.addEventListener("change", syncPromptField("responseStyle"));
  elements.replyRules.addEventListener("input", syncPromptField("replyRules"));
  elements.businessNotes.addEventListener("input", syncPromptField("businessNotes"));
  elements.escalationGuidance.addEventListener("input", syncPromptField("escalationGuidance"));
  elements.scenarioSelect.addEventListener("change", syncPromptField("scenario"));
  if (elements.featureModelSelect) {
    elements.featureModelSelect.addEventListener("change", syncFeatureModelField);
  }
  if (elements.monitorWatchItemInput) {
    elements.monitorWatchItemInput.addEventListener("input", syncMonitorWatchItemsField);
    elements.monitorWatchItemInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === "," || event.key === ";") {
        event.preventDefault();
        addMonitorWatchItems(event.currentTarget.value);
      }
    });
    elements.monitorWatchItemInput.addEventListener("paste", (event) => {
      const pastedText = event.clipboardData?.getData("text") || "";
      const parsedItems = normalizeMonitorWatchItems(pastedText);
      if (parsedItems.length > 1 || /[\n;,]/.test(pastedText)) {
        event.preventDefault();
        addMonitorWatchItems(pastedText, { focusInput: false });
      }
    });
    elements.monitorWatchItemInput.addEventListener("blur", finalizeMonitorWatchItemsField);
  }
  if (elements.monitorWatchItemAddButton) {
    elements.monitorWatchItemAddButton.addEventListener("click", () => {
      addMonitorWatchItems(elements.monitorWatchItemInput?.value || "");
    });
  }
  if (elements.monitorWatchItemsList) {
    elements.monitorWatchItemsList.addEventListener("click", (event) => {
      const target = getEventTargetElement(event);
      const removeButton = target?.closest("[data-monitor-remove-watch-item-index]");
      if (!removeButton) {
        return;
      }

      event.preventDefault();
      removeMonitorWatchItem(removeButton.dataset.monitorRemoveWatchItemIndex || "");
    });
  }
  if (elements.monitorManualOnly) {
    elements.monitorManualOnly.addEventListener("change", syncMonitorManualOnlyField);
  }
  if (elements.monitorIntervalDays) {
    elements.monitorIntervalDays.addEventListener("input", syncMonitorIntervalDaysField);
    elements.monitorIntervalDays.addEventListener("blur", finalizeMonitorIntervalDaysField);
  }
  if (elements.monitorScheduleTime) {
    elements.monitorScheduleTime.addEventListener("input", syncMonitorScheduleTimeField);
    elements.monitorScheduleTime.addEventListener("change", syncMonitorScheduleTimeField);
    elements.monitorScheduleTime.addEventListener("blur", finalizeMonitorScheduleTimeField);
  }
  if (elements.monitorDeliveryChannel) {
    elements.monitorDeliveryChannel.addEventListener("change", syncDeliverySettingsField("deliveryChannel"));
  }
  if (elements.deliveryPlatformAddButton) {
    elements.deliveryPlatformAddButton.addEventListener("click", (event) => {
      event.preventDefault();
      if (elements.deliveryPlatformAddButton.disabled) {
        return;
      }
      const isOpen = !elements.deliveryPlatformMenu?.hidden;
      setDeliveryPlatformMenuOpen(!isOpen);
    });
  }
  if (elements.deliveryPlatformMenu) {
    elements.deliveryPlatformMenu.addEventListener("click", (event) => {
      const target = getEventTargetElement(event);
      const optionButton = target?.closest("[data-delivery-platform-option]");
      if (!optionButton || optionButton.disabled) {
        return;
      }
      event.preventDefault();
      addWhatsAppToolDeliveryPlatform(optionButton.dataset.deliveryPlatformOption || "");
    });
  }
  if (elements.deliveryPlatformList) {
    elements.deliveryPlatformList.addEventListener("click", (event) => {
      const target = getEventTargetElement(event);
      const removeButton = target?.closest("[data-delivery-platform-remove]");
      if (!removeButton) {
        return;
      }
      event.preventDefault();
      removeWhatsAppToolDeliveryPlatform(removeButton.dataset.deliveryPlatformRemove || "");
    });
  }
  if (elements.monitorTelegramChatId) {
    elements.monitorTelegramChatId.addEventListener("input", syncDeliverySettingsField("telegramChatId"));
  }
  if (elements.monitorWhatsAppSetupButton) {
    elements.monitorWhatsAppSetupButton.addEventListener("click", () => {
      startFeatureActivation({ statusMessage: "WhatsApp setup opened." });
    });
  }
  if (elements.reengagementIntervalDays) {
    elements.reengagementIntervalDays.addEventListener("input", syncReengagementIntervalDaysField);
    elements.reengagementIntervalDays.addEventListener("blur", finalizeReengagementIntervalDaysField);
  }
  if (elements.reengagementScheduleTime) {
    elements.reengagementScheduleTime.addEventListener("input", syncReengagementScheduleTimeField);
    elements.reengagementScheduleTime.addEventListener("change", syncReengagementScheduleTimeField);
    elements.reengagementScheduleTime.addEventListener("blur", finalizeReengagementScheduleTimeField);
  }
  if (elements.reengagementInactivityValue) {
    elements.reengagementInactivityValue.addEventListener("input", syncReengagementInactivityValueField);
    elements.reengagementInactivityValue.addEventListener("blur", finalizeReengagementInactivityValueField);
  }
  if (elements.reengagementInactivityUnit) {
    elements.reengagementInactivityUnit.addEventListener("change", syncReengagementInactivityUnitField);
  }

  elements.displayNameInput.addEventListener("input", syncSettingsField("displayName"));
  elements.workspaceNameInput.addEventListener("input", syncSettingsField("workspaceName"));
  elements.timezoneSelect.addEventListener("change", syncSettingsField("timezone"));
  if (elements.profileBusinessSummaryInput) {
    elements.profileBusinessSummaryInput.addEventListener("input", syncAccountProfileField("businessSummary"));
  }
  if (elements.profileCustomerNotesInput) {
    elements.profileCustomerNotesInput.addEventListener("input", syncAccountProfileField("customerNotes"));
  }
  if (elements.profileAssistantGuidanceInput) {
    elements.profileAssistantGuidanceInput.addEventListener("input", syncAccountProfileField("assistantGuidance"));
  }

  if (elements.simulatorPresetSelect) {
    elements.simulatorPresetSelect.addEventListener("change", (event) => {
      applySimulatorPreset(event.target.value);
    });
  }

  if (elements.simulatorLoadSampleButton) {
    elements.simulatorLoadSampleButton.addEventListener("click", () => {
      applySimulatorPreset(elements.simulatorPresetSelect?.value || DEFAULT_SIMULATOR.composer.scenario);
    });
  }

  if (elements.simulatorQueueButton) {
    elements.simulatorQueueButton.addEventListener("click", queueSimulatorApproval);
  }

  if (elements.simulatorReplyInput) {
    elements.simulatorReplyInput.addEventListener("input", syncSimulatorReplyDraft);
  }

  if (elements.simulatorEditButton) {
    elements.simulatorEditButton.addEventListener("click", () => {
      const approval = getSelectedSimulatorApproval();
      if (!approval) {
        return;
      }

      const editUrl = buildSimulatorEditUrl(approval);
      if (editUrl) {
        window.open(editUrl, "_blank", "noopener,noreferrer");
        updateStatusFromSimulator("Opened approval page");
        return;
      }

      if (elements.simulatorReplyInput) {
        elements.simulatorReplyInput.focus();
        if (typeof elements.simulatorReplyInput.select === "function") {
          elements.simulatorReplyInput.select();
        }
      }

      updateStatusFromSimulator("Focused the local reply draft");
    });
  }

  if (elements.simulatorSendButton) {
    elements.simulatorSendButton.addEventListener("click", markSimulatorApprovalSent);
  }

  for (const field of [
    ["simulatorSenderNameInput", "senderName"],
    ["simulatorSenderWaIdInput", "senderWaId"],
    ["simulatorMessageInput", "latestMessage"],
    ["simulatorContextInput", "threadContext"],
    ["simulatorApprovalUrlInput", "approvalUrl"],
  ]) {
    const [elementKey, stateKey] = field;
    const element = elements[elementKey];

    if (element) {
      element.addEventListener("input", syncSimulatorComposerField(stateKey));
    }
  }

  elements.copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(buildCompiledPrompt());
      setStatus("Instruction preview copied");
    } catch {
      setStatus("Copy failed in this browser");
    }
  });

  document.addEventListener("click", (event) => {
    const activationButton = event.target.closest("#featureStudioActivationButton");
    if (!activationButton || activationButton.disabled) {
      return;
    }

    event.preventDefault();
    void activateSelectedFeature();
  });
}

bindEvents();
void bootstrapAuthState();
