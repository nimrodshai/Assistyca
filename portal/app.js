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
const WHATSAPP_SAMPLE_CONFIRMATION_POLL_MS = 2 * 1000;
const WHATSAPP_SAMPLE_CONFIRMATION_TIMEOUT_MS = 30 * 1000;
const VALID_TABS = new Set(["features", "personal-details", "preview", "simulator", "billing", "pricing", "settings"]);
const VALID_FEATURE_STUDIO_VIEWS = new Set(["overview", "activation", "editor", "history"]);
const TAB_ALIASES = new Map([
  ["guidance", "features"],
  ["tools", "features"],
  ["personal", "personal-details"],
  ["profile", "personal-details"],
  ["details", "personal-details"],
]);
const TAB_LABELS = {
  features: "Tools",
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
    title: "Registered users",
    description: "",
  },
};
const LOCAL_APPROVAL_URL = "../approval.html";
const LOCAL_PORTAL_API_BASE = "http://127.0.0.1:8000";
const META_WHATSAPP_ACCOUNTS_URL = "https://business.facebook.com/latest/settings/whatsapp_account";
const SAVED_ACCESS_TOKEN_FIELD_VALUE = "................";
const DEFAULT_BILLING_MULTIPLIER = 1.5;
const DEFAULT_BILLING_MINIMUM = 50.0;
const DEFAULT_FEATURE_LAUNCH_URL = "";
const MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier";
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
  billingMultiplier: DEFAULT_BILLING_MULTIPLIER,
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
  intervalDays: 7,
  scheduleTimeLocal: "",
  scheduleTimezone: "",
  deliveryChannel: "email",
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
      openai: {
        inputUsdPer1MTokens: 0.2,
        outputUsdPer1MTokens: 1.25,
      },
      ours: {
        inputUsdPer1MTokens: 0.3,
        outputUsdPer1MTokens: 1.875,
      },
      totalOpenAIUsdPer1MTokens: 1.45,
      totalOurUsdPer1MTokens: 2.175,
    },
    {
      band: "Efficient",
      modelId: "gpt-5.4-mini",
      modelName: "GPT-5.4 Mini",
      description: "For everyday assistants that need stronger quality than nano without paying for the full flagship tier.",
      useCases: ["General replies", "Summaries", "Routine drafting"],
      openai: {
        inputUsdPer1MTokens: 0.75,
        outputUsdPer1MTokens: 4.5,
      },
      ours: {
        inputUsdPer1MTokens: 1.125,
        outputUsdPer1MTokens: 6.75,
      },
      totalOpenAIUsdPer1MTokens: 5.25,
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
      openai: {
        inputUsdPer1MTokens: 2.5,
        outputUsdPer1MTokens: 15,
      },
      ours: {
        inputUsdPer1MTokens: 3.75,
        outputUsdPer1MTokens: 22.5,
      },
      totalOpenAIUsdPer1MTokens: 17.5,
      totalOurUsdPer1MTokens: 26.25,
    },
    {
      band: "Premium",
      modelId: "gpt-5.5",
      modelName: "GPT-5.5",
      description: "For the most demanding tasks, deeper reasoning, and higher-stakes outputs.",
      useCases: ["Deep reasoning", "Long context", "Critical drafting"],
      openai: {
        inputUsdPer1MTokens: 5,
        outputUsdPer1MTokens: 30,
      },
      ours: {
        inputUsdPer1MTokens: 7.5,
        outputUsdPer1MTokens: 45,
      },
      totalOpenAIUsdPer1MTokens: 35,
      totalOurUsdPer1MTokens: 52.5,
    },
  ],
};
const MONITOR_INTERVAL_DAYS_MIN = 1;
const MONITOR_INTERVAL_DAYS_MAX = 365;
const DEFAULT_MONITOR_SCHEDULE_TIME = "09:00";
const DEFAULT_TOOL_MODEL = DEFAULT_MONITOR_SETTINGS.model;
const DEFAULT_FEATURE_SETTINGS = {
  model: DEFAULT_TOOL_MODEL,
};
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
    id: "whatsapp-business-follow-up-outreach-writer",
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
    settings: { ...DEFAULT_FEATURE_SETTINGS },
    savedSettings: { ...DEFAULT_FEATURE_SETTINGS },
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
    ask: "Hi Maya, just checking in in case you still need help with the leak repair we discussed. If you want to pick it back up, send me a message and I’ll take it from there.",
    insight: "Keeps old conversations from going cold without sounding pushy.",
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
  requestCountryCode: "",
  authAlertOpen: false,
  menuOpen: false,
  selectedFeatureId: null,
  featureStudioView: "overview",
  featureActivationNotice: "",
  featureActivationFieldErrors: {},
  whatsappHistory: null,
  whatsappHistoryLoading: false,
  whatsappHistoryError: "",
  whatsappHistorySelectedConversationId: "",
  whatsappHistoryLoadedAt: 0,
  whatsappHistoryEmail: "",
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
let whatsappSampleMessageBusy = false;
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
  featureList: document.querySelector("#featureList"),
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
  featureStudioWhatsAppDetailsButton: document.querySelector("#featureStudioWhatsAppDetailsButton"),
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
  monitorWatchItemsEditor: document.querySelector("#monitorWatchItemsEditor"),
  monitorWatchItemsList: document.querySelector("#monitorWatchItemsList"),
  monitorWatchItemInput: document.querySelector("#monitorWatchItemInput"),
  monitorWatchItemAddButton: document.querySelector("#monitorWatchItemAddButton"),
  monitorIntervalDays: document.querySelector("#monitorIntervalDays"),
  monitorScheduleTime: document.querySelector("#monitorScheduleTime"),
  monitorScheduleTimezoneLabel: document.querySelector("#monitorScheduleTimezoneLabel"),
  monitorNextRun: document.querySelector("#monitorNextRun"),
  monitorNextRunValue: document.querySelector("#monitorNextRunValue"),
  monitorDeliveryChannel: document.querySelector("#monitorDeliveryChannel"),
  monitorEmailField: document.querySelector("#monitorEmailField"),
  monitorEmailSummary: document.querySelector("#monitorEmailSummary"),
  monitorTelegramField: document.querySelector("#monitorTelegramField"),
  monitorTelegramChatId: document.querySelector("#monitorTelegramChatId"),
  monitorWhatsAppField: document.querySelector("#monitorWhatsAppField"),
  monitorWhatsAppSetupButton: document.querySelector("#monitorWhatsAppSetupButton"),
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
  whatsappHistoryRefreshButton: document.querySelector("#whatsappHistoryRefreshButton"),
  whatsappHistoryDiagnostics: document.querySelector("#whatsappHistoryDiagnostics"),
  whatsappHistoryConversationList: document.querySelector("#whatsappHistoryConversationList"),
  whatsappHistorySelectedAvatar: document.querySelector("#whatsappHistorySelectedAvatar"),
  whatsappHistorySelectedTitle: document.querySelector("#whatsappHistorySelectedTitle"),
  whatsappHistorySelectedMeta: document.querySelector("#whatsappHistorySelectedMeta"),
  whatsappHistorySelectedCount: document.querySelector("#whatsappHistorySelectedCount"),
  whatsappHistoryMessages: document.querySelector("#whatsappHistoryMessages"),
  accountMenuButton: document.querySelector("#accountMenuButton"),
  accountMenu: document.querySelector("#accountMenu"),
  accountAvatar: document.querySelector("#accountAvatar"),
  accountLabel: document.querySelector("#accountLabel"),
  tabButtons: Array.from(document.querySelectorAll(".tab-button")),
  featuresPanel: document.querySelector("#featuresPanel"),
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
  pricingMultiplierValue: document.querySelector("#pricingMultiplierValue"),
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
  userAccessSettingsPane: document.querySelector("#userAccessSettingsPane"),
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

function clearAuthSession() {
  authSession = null;
  persistJson(AUTH_SESSION_KEY, null);
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

function normalizeAdminUserRecord(user = {}) {
  return {
    email: normalizeEmail(user.email || ""),
    displayName: String(user.displayName || "").trim(),
    isActive: Boolean(user.isActive),
    isAdmin: Boolean(user.isAdmin),
    registeredAt: String(user.registeredAt || "").trim(),
    lastLoginAt: String(user.lastLoginAt || "").trim(),
    assignedFeatureIds: sortUniqueFeatureIds(user.assignedFeatureIds || user.featureIds || []),
  };
}

function sortAdminUsers(users = []) {
  return [...users].sort((left, right) => {
    const leftLabel = (left.displayName || left.email).toLowerCase();
    const rightLabel = (right.displayName || right.email).toLowerCase();
    return leftLabel.localeCompare(rightLabel);
  });
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
      title: "Register user",
      description: "",
    };
  }

  if (state.adminView === "edit") {
    const user = getAdminSelectedUser();
    return {
      title: user ? `Edit ${user.displayName || deriveDisplayName(user.email)}` : "Edit user",
      description: user?.email || "Fix a typo in this account’s name or email.",
    };
  }

  if (state.adminView === "detail") {
    const user = getAdminSelectedUser();
    return {
      title: user
        ? (user.displayName || deriveDisplayName(user.email))
        : SETTINGS_MODE_CONTENT.users.title,
      description: user?.email || "Manage which tools this user can see in the portal.",
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
  if (!normalizedEmail || !isAdminUser()) {
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
  if (user?.isAdmin && activeAdminCount <= 1) {
    return "Add another admin before deleting the last admin account.";
  }

  return "";
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

  return state.adminUsers.filter((user) => {
    const searchable = [
      user.displayName,
      user.email,
      user.isAdmin ? "admin" : "user",
      ...user.assignedFeatureIds,
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

function openAdminUsersList(options = {}) {
  const shouldOpenModal = !state.settingsOpen || normalizeSettingsMode(state.settingsMode) !== "users";
  state.settingsMode = "users";
  state.adminView = "list";
  state.adminSelectedUserEmail = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";
  if (options.preserveSearch !== true) {
    state.adminUserSearch = "";
  }

  if (shouldOpenModal) {
    openSettings("users");
    return;
  }

  closeMenu();
  renderApp();
  if (options.refresh !== false && isAdminUser()) {
    void refreshAdminUsers();
  }
}

function focusAdminAddUserEmailInput() {
  window.requestAnimationFrame(() => {
    const input = elements.userAccessSettingsPane?.querySelector('[data-admin-new-email="true"]');
    if (input instanceof HTMLInputElement) {
      input.focus();
    }
  });
}

function openAdminAddUser() {
  const shouldOpenModal = !state.settingsOpen || normalizeSettingsMode(state.settingsMode) !== "users";
  state.settingsMode = "users";
  state.adminView = "add";
  state.adminSelectedUserEmail = "";
  state.adminUsersError = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminNewUserEmail = "";
  state.adminNewUserDisplayName = "";
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";

  if (shouldOpenModal) {
    openSettings("users");
    focusAdminAddUserEmailInput();
    return;
  }

  closeMenu();
  renderApp();
  focusAdminAddUserEmailInput();
}

function focusAdminEditUserInput() {
  window.requestAnimationFrame(() => {
    const emailInput = elements.userAccessSettingsPane?.querySelector('[data-admin-edit-email="true"]');
    if (emailInput instanceof HTMLInputElement && !emailInput.disabled) {
      emailInput.focus();
      return;
    }

    const nameInput = elements.userAccessSettingsPane?.querySelector('[data-admin-edit-display-name="true"]');
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

  const shouldOpenModal = !state.settingsOpen || normalizeSettingsMode(state.settingsMode) !== "users";
  state.settingsMode = "users";
  state.adminView = "detail";
  state.adminSelectedUserEmail = normalizedEmail;
  state.adminUsersError = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminEditUserEmail = "";
  state.adminEditUserDisplayName = "";

  if (shouldOpenModal) {
    openSettings("users");
    return;
  }

  closeMenu();
  renderApp();
}

function openAdminEditUser(email) {
  const user = state.adminUsers.find((entry) => entry.email === normalizeEmail(email));
  if (!user) {
    return;
  }

  const shouldOpenModal = !state.settingsOpen || normalizeSettingsMode(state.settingsMode) !== "users";
  state.settingsMode = "users";
  state.adminView = "edit";
  state.adminSelectedUserEmail = user.email;
  state.adminUsersError = "";
  state.adminFeatureSearch = "";
  state.adminFeaturePickerOpen = false;
  state.adminEditUserEmail = user.email;
  state.adminEditUserDisplayName = user.displayName || "";

  if (shouldOpenModal) {
    openSettings("users");
    focusAdminEditUserInput();
    return;
  }

  closeMenu();
  renderApp();
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
      settings: featureId === MONITOR_FEATURE_ID
        ? normalizeFeatureMonitorSettings(feature?.settings || {})
        : normalizeFeatureSettings(feature?.settings || {}),
      savedSettings: featureId === MONITOR_FEATURE_ID
        ? normalizeFeatureMonitorSettings(feature?.savedSettings || feature?.settings || {})
        : normalizeFeatureSettings(feature?.savedSettings || feature?.settings || {}),
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
    });
  }

  return {
    profile,
    settings,
    features,
    simulator,
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
    billingMultiplier: Math.max(
      0,
      Number(
        source.billingMultiplier
        ?? source.billing_multiplier
        ?? source.multiplier
        ?? DEFAULT_FEATURE_PRICING.billingMultiplier,
      ),
    ) || DEFAULT_FEATURE_PRICING.billingMultiplier,
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
  const scheduleTimeLocal = normalizeMonitorScheduleTime(
    source.scheduleTimeLocal,
    getMonitorScheduleTime(feature),
  );
  const scheduleTimezone = scheduleTimeLocal
    ? normalizeMonitorScheduleTimezone(source.scheduleTimezone, getMonitorScheduleTimezone(feature))
    : "";

  return normalizeFeatureMonitorSettings({
    ...source,
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

function normalizeFeatureMonitorSettings(settings = {}) {
  const source = settings && typeof settings === "object" ? settings : {};
  const deliveryChannel = String(source.deliveryChannel || DEFAULT_MONITOR_SETTINGS.deliveryChannel).trim().toLowerCase();
  const intervalDays = Number.parseInt(source.intervalDays, 10);
  const legacyCadence = String(source.cadence || "").trim().toLowerCase();
  const scheduleTimeLocal = normalizeMonitorScheduleTime(source.scheduleTimeLocal || source.scheduleTime || "");
  const scheduleTimezone = scheduleTimeLocal
    ? normalizeMonitorScheduleTimezone(source.scheduleTimezone || source.scheduleTimeZone || "", defaultTimeZone())
    : normalizeMonitorScheduleTimezone(source.scheduleTimezone || source.scheduleTimeZone || "", "");

  return {
    ...normalizeFeatureSettings(source),
    watchItems: normalizeMonitorWatchItems(source.watchItems || source.searchPrompt || ""),
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

function getFeaturePricing(feature = getSelectedFeature()) {
  return normalizeFeaturePricing(feature?.pricing || DEFAULT_FEATURE_PRICING);
}

function buildFeaturePitch(feature = getSelectedFeature()) {
  if (feature?.id === MONITOR_FEATURE_ID) {
    return "Scheduled Web Monitor keeps watch for the dates, opportunities, and public updates that matter to this client. It turns a plain-language brief into recurring web research, then sends concise alerts with source links so the right person hears about conferences, holidays, deadlines, or niche developments before they slip by.";
  }

  if (feature?.id === "whatsapp-business-follow-up-outreach-writer") {
    return "WhatsApp Re-engagement Assistant makes it easy to follow up with past customers without starting from scratch. It prepares outreach messages you can review and send, helping you restart conversations, stay top of mind, and bring more opportunities back into your pipeline.";
  }

  return "WhatsApp Reply Assistant helps you respond faster without sounding rushed. It turns incoming messages into clear, polished reply drafts that keep leads warm, reduce missed opportunities after hours, and make follow-up feel consistent and professional. You stay in control of every send while moving quicker, quoting with more confidence, and turning more conversations into booked work.";
}

function buildFeatureExample(feature = getSelectedFeature()) {
  const prompt = feature?.prompt || getSelectedPrompt();
  const scenario = SCENARIOS[prompt.scenario] ?? SCENARIOS.approval;
  return {
    sender: scenario.sender || "Customer",
    avatar: getInitialsFromName(scenario.sender || feature?.name || "WA"),
    meta: scenario.meta || "Recent lead",
    incoming: scenario.user,
    outgoing: buildResponseText(prompt),
  };
}

function buildFeatureEditorHint(feature = getSelectedFeature()) {
  const pricing = getFeaturePricing(feature);
  const accountMinimum = Math.max(DEFAULT_BILLING_MINIMUM, Number(pricing.minimumMonthlyCharge || 0) || 0);
  return `Open the editor before payment. This tool bills at ${pricing.billingMultiplier.toFixed(1)}x token cost, and your account has a ${formatCurrency(accountMinimum, "USD")} monthly minimum across all tools.`;
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
  const settings = featureId === MONITOR_FEATURE_ID
    ? normalizeFeatureMonitorSettings(serverFeature?.settings || existingFeature?.settings || {})
    : normalizeFeatureSettings(serverFeature?.settings || existingFeature?.settings || {});
  const savedSettings = featureId === MONITOR_FEATURE_ID
    ? normalizeFeatureMonitorSettings(serverFeature?.settings || existingFeature?.savedSettings || existingFeature?.settings || {})
    : normalizeFeatureSettings(serverFeature?.settings || existingFeature?.savedSettings || existingFeature?.settings || {});

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
        settings: isMonitorFeature(feature)
          ? buildMonitorSettingsForSave(feature, feature.settings)
          : { ...feature.settings },
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
          settings: isMonitorFeature(feature)
            ? buildMonitorSettingsForSave(feature, feature.settings)
            : { ...feature.settings },
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

function isFeatureSetupComplete(feature = getSelectedFeature()) {
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
  return isMonitorFeature(feature)
    ? normalizeFeatureMonitorSettings(feature?.settings || {})
    : normalizeFeatureSettings(feature?.settings || {});
}

function getSavedFeatureSettings(feature = getSelectedFeature()) {
  return isMonitorFeature(feature)
    ? normalizeFeatureMonitorSettings(feature?.savedSettings || feature?.settings || {})
    : normalizeFeatureSettings(feature?.savedSettings || feature?.settings || {});
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

  if (senderWaId) {
    parts.push(senderWaId);
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
  const item = document.createElement("div");
  item.className = `whatsapp-history-message is-${message.direction}`;

  const bubble = document.createElement("div");
  bubble.className = "whatsapp-history-bubble";

  const text = document.createElement("p");
  text.textContent = message.text;

  const meta = document.createElement("span");
  meta.className = "whatsapp-history-message-meta";
  const timestamp = formatAdminDateTime(message.messageAt);
  const directionLabel = message.direction === "outbound" ? "Business" : "Customer";
  meta.textContent = timestamp ? `${directionLabel} · ${timestamp}` : directionLabel;

  bubble.append(text, meta);
  item.append(bubble);

  if (message.direction === "inbound" && message.suggestedReply) {
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

function renderWhatsAppHistory(feature = getSelectedFeature()) {
  if (!elements.whatsappHistorySection) {
    return;
  }

  const conversations = getWhatsAppHistoryConversations();
  const selectedConversation = getSelectedWhatsAppHistoryConversation();
  const isLoading = Boolean(state.whatsappHistoryLoading);
  const errorText = String(state.whatsappHistoryError || "").trim();

  if (elements.whatsappHistoryRefreshButton) {
    elements.whatsappHistoryRefreshButton.disabled = isLoading || !isSignedIn() || !isWhatsAppFeature(feature);
    elements.whatsappHistoryRefreshButton.classList.toggle("is-loading", isLoading);
    elements.whatsappHistoryRefreshButton.setAttribute("aria-busy", String(isLoading));
    elements.whatsappHistoryRefreshButton.textContent = isLoading ? "Refreshing..." : "Refresh";
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
        createWhatsAppHistoryEmptyState("No saved conversations yet", "New customer messages will appear here after WhatsApp sends them to Assistyca."),
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

  if (!isMonitorFeature(feature)) {
    const currentSettings = getSelectedFeatureSettings(feature);
    const savedSettings = getSavedFeatureSettings(feature);
    return Object.keys(DEFAULT_FEATURE_SETTINGS).some(
      (key) => JSON.stringify(currentSettings[key] ?? "") !== JSON.stringify(savedSettings[key] ?? ""),
    );
  }

  const currentSettings = getSelectedFeatureSettings(feature);
  const savedSettings = getSavedFeatureSettings(feature);
  return Object.keys(DEFAULT_MONITOR_SETTINGS).some(
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
  const currentScheduleTime = normalizeMonitorScheduleTime(currentSettings.scheduleTimeLocal, "");
  const savedScheduleTime = normalizeMonitorScheduleTime(savedSettings.scheduleTimeLocal, "");
  const currentScheduleTimezone = currentScheduleTime
    ? normalizeMonitorScheduleTimezone(currentSettings.scheduleTimezone, getWorkspaceTimeZone()) || getWorkspaceTimeZone()
    : "";
  const savedScheduleTimezone = savedScheduleTime
    ? normalizeMonitorScheduleTimezone(savedSettings.scheduleTimezone, getWorkspaceTimeZone()) || getWorkspaceTimeZone()
    : "";

  return (
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
  const intervalDays = normalizeMonitorIntervalDays(settings.intervalDays);
  const scheduleTimeLocal = normalizeMonitorScheduleTime(settings.scheduleTimeLocal, getMonitorScheduleTime(feature));
  const scheduleTimezone = normalizeMonitorScheduleTimezone(
    settings.scheduleTimezone,
    getMonitorScheduleTimezone(feature),
  ) || getMonitorScheduleTimezone(feature);
  const anchorDate = resolveMonitorAnchorDate(feature, currentTime);
  if (!anchorDate) {
    return "";
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
  const markupMultiplier = Number(report.markupMultiplier ?? billingPlan.markupMultiplier ?? 1.5) || 1.5;
  const inputTokenPriceMultiplier = Number(
    report.inputTokenPriceMultiplier ?? billingPlan.inputTokenPriceMultiplier ?? markupMultiplier,
  ) || markupMultiplier;
  const outputTokenPriceMultiplier = Number(
    report.outputTokenPriceMultiplier ?? billingPlan.outputTokenPriceMultiplier ?? markupMultiplier,
  ) || markupMultiplier;
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
    markupMultiplier,
    inputTokenPriceMultiplier,
    outputTokenPriceMultiplier,
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
      inputTokenPriceMultiplier,
      outputTokenPriceMultiplier,
    },
    asOf: String(report.asOf || "").trim(),
  };
}

function getBillingPolicyLabel(report) {
  const inputMultiplier = Number(report?.inputTokenPriceMultiplier || report?.markupMultiplier || 1.5) || 1.5;
  const outputMultiplier = Number(report?.outputTokenPriceMultiplier || report?.markupMultiplier || 1.5) || 1.5;
  const minimum = formatCurrency(report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM, report?.currency || "USD");
  if (Math.abs(inputMultiplier - outputMultiplier) < 0.0001) {
    return `Billed at ${inputMultiplier.toFixed(1)}x the token cost · ${minimum} monthly minimum across all tools`;
  }

  return `Billed at ${inputMultiplier.toFixed(1)}x input token cost · ${outputMultiplier.toFixed(1)}x output token cost · ${minimum} monthly minimum across all tools`;
}

function getBillingPricingLabel(report) {
  const inputMultiplier = Number(report?.inputTokenPriceMultiplier || report?.markupMultiplier || 1.5) || 1.5;
  const outputMultiplier = Number(report?.outputTokenPriceMultiplier || report?.markupMultiplier || 1.5) || 1.5;
  if (Math.abs(inputMultiplier - outputMultiplier) < 0.0001) {
    return `${inputMultiplier.toFixed(1)}x the token cost`;
  }

  return `${inputMultiplier.toFixed(1)}x input token cost and ${outputMultiplier.toFixed(1)}x output token cost`;
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
  const pricingLabel = getBillingPricingLabel(report);
  const minimum = formatCurrency(report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM, report?.currency || "USD");
  const nextPaymentDate = formatBillingDate(getNextBillingPaymentDate(report));
  const helpLines = [
    "We add up usage across all of your tools each month.",
    `The rate is ${pricingLabel}, so cheaper models cost less and more expensive models cost more. Your account has a ${minimum} monthly minimum across all tools combined.`,
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
  const nextTab = normalizeTab(tab);

  if (nextTab === "settings") {
    openSettings(options.settingsMode || state.settingsMode);
    return;
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

function updatePricingPanel() {
  const snapshot = state.pricingSnapshot && typeof state.pricingSnapshot === "object"
    ? state.pricingSnapshot
    : MANUAL_PRICING_SNAPSHOT;
  const cards = Array.isArray(snapshot?.cards) ? snapshot.cards : [];

  if (elements.pricingCardCount) {
    elements.pricingCardCount.textContent = String(cards.length || 0);
  }

  if (elements.pricingCardGrid) {
    if (!cards.length) {
      const message = "Pricing cards are not available right now.";
      const meta = "Add manual prices to MANUAL_PRICING_SNAPSHOT in portal/app.js.";
      elements.pricingCardGrid.replaceChildren(createPricingEmptyState(message, meta));
    } else {
      elements.pricingCardGrid.replaceChildren(...cards.map((card) => buildPricingCard(card)));
    }
  }
}

async function refreshPricingSnapshot(options = {}) {
  state.pricingSnapshot = MANUAL_PRICING_SNAPSHOT;
  state.pricingLoading = false;
  state.pricingError = "";
  if (options.render !== false) {
    renderApp();
  }
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
    const input = elements.userAccessSettingsPane?.querySelector('[data-admin-feature-search-input="true"]');
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
    ? `${filteredUsers.length} of ${state.adminUsers.length} users`
    : `${state.adminUsers.length} user${state.adminUsers.length === 1 ? "" : "s"}`;

  toolbar.append(searchField, countBadge);
  wrapper.append(toolbar);

  if (state.adminUsersLoading && !state.adminUsers.length) {
    wrapper.append(createAdminEmptyState(
      "Loading users",
      "Fetching registered accounts so you can search and manage them.",
    ));
    return wrapper;
  }

  if (!state.adminUsers.length) {
    wrapper.append(createAdminEmptyState(
      "No registered users yet",
      "Register the first user here, then open them to manage which tools they can see.",
    ));
    return wrapper;
  }

  if (!filteredUsers.length) {
    wrapper.append(createAdminEmptyState(
      "No users match that search",
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
  for (const heading of ["User", "Email", "Tools", "Last login", "Role", ""]) {
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

    const toolsCell = document.createElement("td");
    toolsCell.textContent = String(user.assignedFeatureIds.length);

    const lastLoginCell = document.createElement("td");
    lastLoginCell.textContent = user.lastLoginAt
      ? formatAdminDateTime(user.lastLoginAt)
      : "No login yet";

    const roleCell = document.createElement("td");
    const roleBadge = document.createElement("span");
    roleBadge.className = "feature-status";
    roleBadge.textContent = user.isAdmin ? "Admin" : "Client";
    roleCell.append(roleBadge);

    const actionCell = document.createElement("td");
    const manageButton = document.createElement("button");
    manageButton.type = "button";
    manageButton.className = "ghost-button small";
    manageButton.dataset.adminOpenUser = user.email;
    manageButton.textContent = "Open";
    actionCell.append(manageButton);

    row.append(nameCell, emailCell, toolsCell, lastLoginCell, roleCell, actionCell);
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
  submitButton.textContent = state.adminAddUserBusy ? "Registering..." : "Register user";

  actions.append(cancelButton, submitButton);
  wrapper.append(emailField, nameField, error, actions);
  return wrapper;
}

function createAdminEditUserView(user) {
  if (!user) {
    return createAdminEmptyState(
      "User not found",
      "Go back to the users table and open another account.",
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
    : "Changing the email keeps this user's assigned tools and saved account history attached to the same account.";

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
      "User not found",
      "Go back to the users table and open another account.",
    );
  }

  const draftFeatureIds = getAdminUserDraftFeatureIds(user.email, user.assignedFeatureIds);
  const hasChanges = !featureIdListsMatch(draftFeatureIds, user.assignedFeatureIds);
  const isSaving = Boolean(state.adminSaveBusyByEmail[user.email]);
  const isDeleting = Boolean(state.adminDeleteBusyByEmail[user.email]);
  const deleteDisabledReason = getAdminUserDeleteDisabledReason(user);
  const toolInputsDisabled = isDeleting;
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
  const roleBadge = document.createElement("span");
  roleBadge.className = "feature-status";
  roleBadge.textContent = user.isAdmin ? "Admin" : "Client";

  const toolsBadge = document.createElement("span");
  toolsBadge.className = "feature-status";
  toolsBadge.textContent = `${draftFeatureIds.length} visible tool${draftFeatureIds.length === 1 ? "" : "s"}`;

  strip.append(roleBadge, toolsBadge);

  const grid = document.createElement("div");
  grid.className = "admin-detail-grid";

  const infoPanel = document.createElement("section");
  infoPanel.className = "admin-detail-panel";
  const infoTitle = document.createElement("h4");
  infoTitle.textContent = "Account";
  const infoRows = document.createElement("div");
  infoRows.className = "detail-stack";
  infoRows.append(
    createAdminDetailRow("Registered", formatAdminDateTime(user.registeredAt) || "Unknown"),
    createAdminDetailRow("Last login", user.lastLoginAt ? formatAdminDateTime(user.lastLoginAt) : "No login yet"),
  );

  const infoActions = document.createElement("div");
  infoActions.className = "admin-detail-panel-actions";

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "ghost-button small";
  editButton.dataset.adminOpenEditUser = user.email;
  editButton.disabled = isSaving || isDeleting;
  editButton.textContent = "Edit user";
  infoActions.append(editButton);

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "ghost-button danger small";
  deleteButton.dataset.adminDeleteUser = user.email;
  deleteButton.disabled = isSaving || isDeleting || Boolean(deleteDisabledReason);
  deleteButton.textContent = isDeleting ? "Deleting..." : "Delete user";
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
  const adminVisible = isAdminUser();
  if (elements.adminUsersMenuItem) {
    elements.adminUsersMenuItem.classList.toggle("is-hidden", !adminVisible);
  }

  if (
    !elements.userAccessSettingsPane
    || !elements.adminUsersShell
    || !elements.adminUsersContent
  ) {
    return;
  }

  if (!adminVisible) {
    elements.userAccessSettingsPane.classList.add("is-hidden");
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
  if (!isAdminUser()) {
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
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t load user access right now.");
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

async function addAdminUser() {
  if (!isAdminUser() || state.adminAddUserBusy) {
    return;
  }

  const email = normalizeEmail(state.adminNewUserEmail);
  const displayName = normalizeText(state.adminNewUserDisplayName);

  if (!validateEmail(email)) {
    state.adminUsersError = "Enter a valid email address before adding the user.";
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
      setStatus("User added");
    }
  }
}

async function saveAdminUserDetails() {
  const user = getAdminSelectedUser();
  if (!isAdminUser() || !user || state.adminEditUserBusy) {
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
      setStatus("User updated");
    }
  }
}

async function saveAdminUserFeatures(email) {
  const normalizedEmail = normalizeEmail(email);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!isAdminUser() || !user || state.adminSaveBusyByEmail[normalizedEmail]) {
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
      setStatus("User access saved");
    }
    if (shouldRetry && !state.adminDeleteBusyByEmail[normalizedEmail]) {
      void saveAdminUserFeatures(normalizedEmail);
    }
  }
}

function deleteAdminUser(email) {
  const normalizedEmail = normalizeEmail(email);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!isAdminUser() || !user || state.adminDeleteBusyByEmail[normalizedEmail]) {
    return;
  }

  const disabledReason = getAdminUserDeleteDisabledReason(user);
  if (disabledReason) {
    openAuthAlert("Delete user unavailable", disabledReason, {
      eyebrow: "Delete user",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    });
    return;
  }

  const label = user.displayName || deriveDisplayName(user.email);
  openAuthAlert(
    "Are you sure?",
    `Delete ${label} (${normalizedEmail})? This removes their portal access, assigned tools, billing history, WhatsApp setup, and saved messages.`,
    {
      eyebrow: "Delete user",
      buttonLabel: "Delete user",
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
  if (!isAdminUser() || !user || state.adminDeleteBusyByEmail[normalizedEmail]) {
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
      "Couldn’t delete user",
      formatApiErrorMessage(error, "We couldn’t delete that user right now."),
      {
        eyebrow: "Delete user",
      },
    );
  } finally {
    const { [normalizedEmail]: _ignore, ...nextBusy } = state.adminDeleteBusyByEmail;
    state.adminDeleteBusyByEmail = nextBusy;
    renderApp();
    if (didSucceed) {
      setStatus("User deleted");
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

function updateFeatureList() {
  const features = clientState.features.length ? clientState.features : [];

  if (!features.length) {
    const emptyState = document.createElement("article");
    emptyState.className = "glass-card empty-state";

    const title = document.createElement("h3");
    title.textContent = "No tools assigned";

    const copy = document.createElement("p");
    copy.textContent = "Add a tool to this account before editing a prompt.";

    emptyState.append(title, copy);
    elements.featureList.replaceChildren(emptyState);
    return;
  }

  elements.featureList.replaceChildren(...features.map((feature) => createFeatureCard(feature)));
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

  if (status === "cancelled") {
    return "Test cancelled";
  }
  if (status === "inconsistent_results") {
    return "Results changed unexpectedly";
  }
  if (status === "no_matches") {
    return recentResultsAlreadySent ? "Nothing new right now" : "No matches found";
  }
  if (status === "duplicate_matches") {
    return "Nothing new to send";
  }
  if (notificationsSent > 0) {
    return "Results sent";
  }
  return "Test finished";
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

  if (status === "cancelled") {
    return "The monitor test was cancelled before any new update was delivered.";
  }

  if (status === "inconsistent_results") {
    const countLabel = recentResultsCount === 1 ? "1 result" : `${recentResultsCount} results`;
    const recencyLabel = recentResultsMinutesAgo > 0
      ? `${recentResultsMinutesAgo} minutes earlier`
      : "earlier";
    const pronoun = recentResultsCount === 1 ? "it" : "them";
    return deliveryChannel === "email" && deliveryTarget
      ? `This test came back empty, but the previous run found ${countLabel} ${recencyLabel} and sent ${pronoun} to ${deliveryTarget}. We didn’t send a no-results update because that mismatch may be a search bug.`
      : `This test came back empty, but the previous run found ${countLabel} ${recencyLabel}. We didn’t send a no-results update because that mismatch may be a search bug.`;
  }

  if (status === "no_matches") {
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
  let eyebrow = "Test in progress";
  let title = "Testing your monitor";
  let message = "We’re running a quick test now. You can cancel it anytime if needed.";
  let buttonLabel = "Cancel test";
  let buttonDisabled = false;

  if (monitorManualRunCancelling) {
    eyebrow = "Stopping now";
    title = "Cancelling this test";
    message = "We’re stopping the current test before anything new is sent.";
    buttonLabel = "Cancelling...";
    buttonDisabled = true;
  } else if (monitorManualRunCancellationError) {
    eyebrow = "Still running";
    title = "Couldn’t cancel yet";
    message = `${monitorManualRunCancellationError} The test is still running, so you can try cancelling again or wait for it to finish.`;
    buttonLabel = "Try cancel again";
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
  setStatus("Cancelling the monitor test. We’ll stop before sending anything new.");

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

async function runSelectedMonitorNow() {
  if (monitorManualRunBusy) {
    if (monitorManualRunTargetId && getSelectedFeature()?.id === monitorManualRunTargetId) {
      syncMonitorManualRunOverlay();
      setStatus("A monitor test is already running.");
    } else {
      setStatus("A monitor test is already running. Refresh if this does not clear in a moment.");
    }
    return;
  }

  const initialFeature = getSelectedFeature();
  if (!initialFeature || !isMonitorFeature(initialFeature) || !isFeatureActivated(initialFeature)) {
    setStatus("Refresh the tool and try the monitor test again.");
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
    setStatus("Testing the monitor now. Cancel it if you need to stop before anything new is sent.");
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
    setStatus(completionMessage);
    openAuthAlert(
      getManualMonitorRunAlertTitle(response.run),
      getManualMonitorRunAlertMessage(response.run, completionMessage),
      {
        eyebrow: String(response.run?.status || "").trim().toLowerCase() === "cancelled" ? "Test cancelled" : "Test finished",
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
  const manualRunBusy = isMonitorManualRunBusy(feature);
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
  if (elements.featureStudioExampleMessage) {
    elements.featureStudioExampleMessage.textContent = example.incoming;
  }
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
  if (elements.featureStudioWhatsAppDetailsButton) {
    const showDetailsButton = studioView === "editor" && canOpenFeatureWhatsAppDetails(feature);
    elements.featureStudioWhatsAppDetailsButton.hidden = !showDetailsButton;
    elements.featureStudioWhatsAppDetailsButton.disabled = activationBusy || transitionBusy || manualRunBusy || sampleMessageBusy;
    elements.featureStudioWhatsAppDetailsButton.title = "Open the saved WhatsApp IDs, token, and approval phone";
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
    const showManualRun = isMonitorFeature(feature) && isActivated;
    const manualRunReady = showManualRun;
    elements.featureStudioMonitorRunButton.hidden = !showManualRun;
    elements.featureStudioMonitorRunButton.textContent = manualRunBusy
      ? monitorManualRunCancelling
        ? "Cancelling..."
        : "Testing..."
      : "Test now";
    elements.featureStudioMonitorRunButton.disabled = !manualRunReady || transitionBusy || manualRunBusy;
    elements.featureStudioMonitorRunButton.classList.toggle("is-loading", false);
    elements.featureStudioMonitorRunButton.setAttribute("aria-busy", String(manualRunBusy));
    elements.featureStudioMonitorRunButton.title = manualRunBusy
      ? monitorManualRunCancelling
        ? "The current monitor test is being cancelled"
        : "A monitor test is currently running"
      : manualRunReady
        ? feature.setupStatus?.ready === false
          ? "Run a test now. We'll check the latest setup first."
          : "Run a test without changing the schedule"
        : String(feature.setupStatus?.message || "");
  }

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

function updateMonitorFieldVisibility(settings = getSelectedFeatureSettings()) {
  const isMonitor = isMonitorFeature(getSelectedFeature());
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

  setMonitorDeliveryPanelState(elements.monitorEmailField, settings.deliveryChannel === "email");
  setMonitorDeliveryPanelState(elements.monitorTelegramField, settings.deliveryChannel === "telegram");
  setMonitorDeliveryPanelState(elements.monitorWhatsAppField, settings.deliveryChannel === "whatsapp");
}

function getMonitorNextRunLabel(feature) {
  if (!feature || !isMonitorFeature(feature)) {
    return "";
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
  if (elements.featureStudioEditorSection) {
    elements.featureStudioEditorSection.classList.toggle("is-monitor-flow", isMonitor);
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
    elements.monitorDeliveryCard.classList.toggle("is-hidden", !isMonitor);
  }
  if (!isMonitor) {
    updateMonitorFieldVisibility(DEFAULT_MONITOR_SETTINGS);
    return;
  }

  const monitorSettings = getSelectedFeatureSettings(feature);
  state.monitorWatchItemDraft = loadMonitorWatchDraft(feature.id);
  renderMonitorWatchItems(monitorSettings.watchItems);
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
  if (elements.monitorDeliveryChannel) {
    elements.monitorDeliveryChannel.value = monitorSettings.deliveryChannel;
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
  const adminVisible = isAdminUser();
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
  const showUsers = state.settingsMode === "users" && adminVisible;
  elements.accountSettingsPane.classList.toggle("is-hidden", !showAccount);
  elements.preferencesSettingsPane.classList.toggle("is-hidden", state.settingsMode !== "preferences");
  if (elements.userAccessSettingsPane) {
    elements.userAccessSettingsPane.classList.toggle("is-hidden", !showUsers);
  }
}

function updatePanelVisibility() {
  const inStudio = state.activeTab === "features" && Boolean(state.selectedFeatureId);
  const inBilling = state.activeTab === "billing";
  const inPricing = state.activeTab === "pricing";
  const feature = inStudio ? getSelectedFeature() : null;
  const studioView = inStudio ? getSelectedFeatureStudioView(feature) : "overview";
  elements.appBar.classList.toggle("is-hidden", inStudio || inBilling || inPricing);
  elements.appView.classList.toggle("is-feature-page", inStudio);
  elements.featuresPanel.classList.toggle("is-hidden", state.activeTab !== "features" || inStudio);
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
  updateHeader();
  updateTabButtons();
  updateFeatureStudioHeader();
  updatePanelVisibility();
  updateFeatureList();
  updateFeatureActivationFields();
  populateMonitorTimezoneOptions();
  updateMonitorFields();
  updatePromptFields();
  updatePreview();
  updateSimulatorPanel();
  updateBillingPanel();
  updatePricingPanel();
  updateSettingsButtons();
  updateSettingsFields();
  updatePersonalDetailsFields();
  syncWhatsAppConnectionPolling();
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
  resetAdminState();
  setHashForTab("features");
  setView("app");
  renderApp();
  void refreshBillingReport();
  void refreshWhatsAppConnection();
  void refreshFeatureActivationStates();
  if (authSession.isAdmin) {
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

  const nextSettings = isMonitorFeature(feature)
    ? normalizeFeatureMonitorSettings({
      ...currentSettings,
      model: nextModel,
    })
    : normalizeFeatureSettings({
      ...currentSettings,
      model: nextModel,
    });

  feature.settings = nextSettings;
  persistClientState();
  updateFeatureStudioHeader();
  updateFeatureModelFields();
  scheduleSelectedFeatureConfigAutosave(feature);
}

function syncMonitorSettingsField(key) {
  return (event) => {
    const feature = getSelectedFeature();
    if (!feature || !isMonitorFeature(feature)) {
      return;
    }

    const nextSettings = buildMonitorSettingsForSave(feature, {
      ...getSelectedFeatureSettings(feature),
      [key]: event.target.value,
    });

    feature.settings = nextSettings;
    updateMonitorFieldVisibility(nextSettings);
    persistClientState();
    updateFeatureStudioHeader();
    void flushSelectedFeatureConfigAutosave({
      featureId: feature.id,
      alertOnError: false,
      noChangesMessage: false,
    }).catch(() => {});
  };
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
    intervalDays: elements.monitorIntervalDays,
    scheduleTimeLocal: elements.monitorScheduleTime,
    scheduleTimezone: elements.monitorScheduleTime,
    deliveryChannel: elements.monitorDeliveryChannel,
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
    resetAdminState();
    refreshView();
    void refreshBillingReport();
    void refreshWhatsAppConnection();
    void refreshFeatureActivationStates();
    if (authSession?.isAdmin) {
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
  if (elements.featureStudioWhatsAppDetailsButton) {
    elements.featureStudioWhatsAppDetailsButton.addEventListener("click", () => {
      startFeatureActivation({ statusMessage: "WhatsApp details opened." });
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
  if (elements.whatsappHistoryRefreshButton) {
    elements.whatsappHistoryRefreshButton.addEventListener("click", () => {
      void refreshWhatsAppHistory({ force: true });
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
  if (elements.userAccessSettingsPane) {
    elements.userAccessSettingsPane.addEventListener("focusin", (event) => {
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

    elements.userAccessSettingsPane.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) {
        return;
      }

      if (target.dataset.adminSearchInput === "true") {
        const caret = target.selectionStart;
        state.adminUserSearch = target.value;
        renderAdminUsersPane();
        const nextInput = elements.userAccessSettingsPane.querySelector('[data-admin-search-input="true"]');
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

    elements.userAccessSettingsPane.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") {
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

    elements.userAccessSettingsPane.addEventListener("click", (event) => {
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

    elements.userAccessSettingsPane.addEventListener("keydown", (event) => {
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
    elements.monitorDeliveryChannel.addEventListener("change", syncMonitorSettingsField("deliveryChannel"));
  }
  if (elements.monitorTelegramChatId) {
    elements.monitorTelegramChatId.addEventListener("input", syncMonitorSettingsField("telegramChatId"));
  }
  if (elements.monitorWhatsAppSetupButton) {
    elements.monitorWhatsAppSetupButton.addEventListener("click", () => {
      startFeatureActivation({ statusMessage: "WhatsApp setup opened." });
    });
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
