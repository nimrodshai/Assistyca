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
migrateLegacyStorage();
const PORTAL_API_BASE = resolvePortalApiBase();
const OTP_TTL_MS = 10 * 60 * 1000;
const SETTINGS_PANEL_ANIMATION_MS = 320;
const VALID_TABS = new Set(["features", "preview", "simulator", "billing", "settings"]);
const VALID_FEATURE_STUDIO_VIEWS = new Set(["overview", "activation", "editor"]);
const TAB_ALIASES = new Map([
  ["guidance", "features"],
  ["tools", "features"],
]);
const TAB_LABELS = {
  features: "Tools",
  preview: "Preview",
  simulator: "Simulator",
  billing: "Billing",
  settings: "Settings",
};
const VALID_SETTINGS_MODES = new Set(["account", "preferences"]);
const LOCAL_APPROVAL_URL = "../approval.html";
const LOCAL_PORTAL_API_BASE = "http://127.0.0.1:8000";
const DEFAULT_BILLING_MULTIPLIER = 1.5;
const DEFAULT_BILLING_MINIMUM = 14.9;
const DEFAULT_FEATURE_LAUNCH_URL = "";
const DEFAULT_TOOL_EDITOR_TARGET_ID = "toolEditorSection";
const LEGACY_DEFAULT_FEATURE_NAMES = new Set([
  "WhatsApp Business Reply Suggestion Assistant",
  "WhatsApp Reply Approval Bot",
]);
const LEGACY_DEFAULT_FEATURE_MODES = new Set([
  "suggestion_only",
  "Approval bot",
]);
const BILLING_MODEL_COLORS = ["#17958a", "#2f7de1", "#d49a3a", "#8c96a3"];
const DEFAULT_FEATURE_PRICING = {
  billingMultiplier: DEFAULT_BILLING_MULTIPLIER,
  minimumMonthlyCharge: DEFAULT_BILLING_MINIMUM,
};
const DEFAULT_FEATURE_WHATSAPP = {
  verify_token: "",
  access_token: "",
  phone_number_id: "",
  app_secret: "",
  owner_wa_id: "",
  allow_mock_send: true,
};

const DEFAULT_PROMPT = {
  toneGuidance: "Warm, direct, and practical. Keep replies human, short, and grounded.",
  replyRules:
    "Acknowledge the request first. Ask one clarifying question only when needed. Never guess prices or availability.",
  businessNotes:
    "Service area, hours, pricing hints, and any details the agent should know before replying.",
  escalationGuidance:
    "Hand off when the customer is upset, the answer needs a human decision, or the request is urgent.",
  exampleReplies:
    "Good: \"Yes, I can help. What is the address?\"\nBad: \"Sure, anything is possible.\"",
  responseStyle: "balanced",
  scenario: "approval",
};

const DEFAULT_SETTINGS = {
  displayName: "",
  workspaceName: "Assistyca",
  timezone: defaultTimeZone(),
};

const DEFAULT_FEATURES = [
  {
    id: "whatsapp-business-reply-suggestion-assistant",
    name: "WhatsApp Reply Assistant",
    description: "Drafts suggested WhatsApp replies and surfaces approvals inside WhatsApp for manual review.",
    channel: "WhatsApp",
    mode: "Human-reviewed",
    status: "Active",
    activated: false,
    launchUrl: DEFAULT_FEATURE_LAUNCH_URL,
    pricing: { ...DEFAULT_FEATURE_PRICING },
    prompt: { ...DEFAULT_PROMPT },
    whatsapp: { ...DEFAULT_FEATURE_WHATSAPP },
  },
];

const DEFAULT_SIMULATOR = {
  composer: {
    scenario: "approval",
    senderName: "Jim Hopper",
    senderWaId: "15551230000",
    latestMessage: "Hey, are you available today?",
    threadContext:
      "Can you fit me in later today?\nI can check my calendar now.\nIf not, tomorrow afternoon works too.",
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

const SCENARIOS = {
  approval: {
    label: "WhatsApp reply assistant example",
    sender: "Jim Hopper",
    user: "Hey, are you available today?",
    ask: "One sec, checking my calendar right now.",
    exactReply: true,
  },
  availability: {
    label: "New lead asking about availability",
    sender: "Maya Cohen",
    user: "Hi, are you available tomorrow afternoon?",
    ask: "Let me check what works best. What address should I look at?",
  },
  pricing: {
    label: "Customer asking about price",
    sender: "Oren Levy",
    user: "How much would it cost to replace the lock?",
    ask: "I can give you a proper price once I know the door type and lock model.",
  },
  reschedule: {
    label: "Existing client wants to reschedule",
    sender: "Dana Klein",
    user: "Can we move the appointment by one day?",
    ask: "Yes, I can check that. What time window would work for you?",
  },
  urgent: {
    label: "Urgent request that should escalate",
    sender: "Customer",
    user: "The door is stuck and I need help right now.",
    ask: "I am flagging this for immediate human follow-up so someone can help you as fast as possible.",
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
  authAlertOpen: false,
  menuOpen: false,
  selectedFeatureId: null,
  featureStudioView: "overview",
  featureStudioMenuOpen: false,
  selectedSimulatorId: null,
  billingReport: null,
  billingLoading: false,
  billingError: "",
  billingHelpOpen: false,
  lastPrimaryTab: normalizeTab(loadJson(LAST_PRIMARY_TAB_KEY, "features")) || "features",
};

let settingsPanelOpenFrame = null;
let settingsPanelCloseTimer = null;
let authAlertOpenFrame = null;
let authAlertCloseTimer = null;
let authAlertReturnFocus = null;
let billingHelpOpenFrame = null;
let billingHelpCloseTimer = null;
let billingHelpReturnFocus = null;

const elements = {
  authView: document.querySelector("#authView"),
  authCard: document.querySelector("#authCard"),
  authAlertOverlay: document.querySelector("#authAlertOverlay"),
  authAlertTitle: document.querySelector("#authAlertTitle"),
  authAlertMessage: document.querySelector("#authAlertMessage"),
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
  featureActivationStatus: document.querySelector("#featureActivationStatus"),
  featureStudioOverviewSection: document.querySelector("#featureStudioOverviewSection"),
  featureStudioActivationBackButton: document.querySelector("#featureStudioActivationBackButton"),
  featureStudioActivationButton: document.querySelector("#featureStudioActivationButton"),
  featureStudioEditorSection: document.querySelector("#toolEditorSection"),
  featureStudioTitle: document.querySelector("#featureStudioTitle"),
  featureStudioDescription: document.querySelector("#featureStudioDescription"),
  featureStudioChannel: document.querySelector("#featureStudioChannel"),
  featureStudioMode: document.querySelector("#featureStudioMode"),
  featureStudioPricing: document.querySelector("#featureStudioPricing"),
  featureStudioPitch: document.querySelector("#featureStudioPitch"),
  featureStudioExampleSender: document.querySelector("#featureStudioExampleSender"),
  featureStudioExampleLabel: document.querySelector("#featureStudioExampleLabel"),
  featureStudioExampleMessage: document.querySelector("#featureStudioExampleMessage"),
  featureStudioExampleReply: document.querySelector("#featureStudioExampleReply"),
  featureStudioLaunchButton: document.querySelector("#featureStudioLaunchButton"),
  featureStudioLaunchNote: document.querySelector("#featureStudioLaunchNote"),
  featureActivationAccessTokenInput: document.querySelector("#featureActivationAccessToken"),
  featureActivationPhoneNumberIdInput: document.querySelector("#featureActivationPhoneNumberId"),
  featureActivationVerifyTokenInput: document.querySelector("#featureActivationVerifyToken"),
  featureActivationOwnerWaIdInput: document.querySelector("#featureActivationOwnerWaId"),
  featureActivationAppSecretInput: document.querySelector("#featureActivationAppSecret"),
  featureActivationAllowMockSendInput: document.querySelector("#featureActivationAllowMockSend"),
  featureActivationSummary: document.querySelector("#featureActivationSummary"),
  featureStudioMenuWrap: document.querySelector("#featureStudioMenuWrap"),
  featureStudioMenuButton: document.querySelector("#featureStudioMenuButton"),
  featureStudioMenu: document.querySelector("#featureStudioMenu"),
  accountMenuButton: document.querySelector("#accountMenuButton"),
  accountMenu: document.querySelector("#accountMenu"),
  accountAvatar: document.querySelector("#accountAvatar"),
  accountLabel: document.querySelector("#accountLabel"),
  tabButtons: Array.from(document.querySelectorAll(".tab-button")),
  featuresPanel: document.querySelector("#featuresPanel"),
  previewPanel: document.querySelector("#previewPanel"),
  simulatorPanel: document.querySelector("#simulatorPanel"),
  billingPanel: document.querySelector("#billingPanel"),
  billingBackButton: document.querySelector("#backToToolsButton"),
  settingsPanel: document.querySelector("#settingsPanel"),
  billingStatusBanner: document.querySelector("#billingStatusBanner"),
  billingStatusMessage: document.querySelector("#billingStatusMessage"),
  billingStatusMeta: document.querySelector("#billingStatusMeta"),
  billingHelpButton: document.querySelector("#billingHelpButton"),
  billingHelpPopover: document.querySelector("#billingHelpPopover"),
  billingHelpCloseButton: document.querySelector("#billingHelpCloseButton"),
  billingHelpBody: document.querySelector("#billingHelpBody"),
  billingRefreshButton: document.querySelector("#billingRefreshButton"),
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
  closeSettingsButton: document.querySelector("#closeSettingsButton"),
  toneGuidance: document.querySelector("#toneGuidance"),
  responseStyle: document.querySelector("#responseStyle"),
  replyRules: document.querySelector("#replyRules"),
  businessNotes: document.querySelector("#businessNotes"),
  escalationGuidance: document.querySelector("#escalationGuidance"),
  exampleReplies: document.querySelector("#exampleReplies"),
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
  return {
    email,
    token,
    signedIn: true,
    signedInAt: Number.isFinite(signedInAt) ? signedInAt : Date.now(),
    expiresAt: Number.isFinite(expiresAt) && expiresAt > 0 ? expiresAt : 0,
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

function clearAuthSession() {
  authSession = null;
  persistJson(AUTH_SESSION_KEY, null);
}

function clearAuthChallenge() {
  authChallenge = null;
  persistJson(AUTH_CHALLENGE_KEY, null);
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

function focusAuthAlertReturnTarget() {
  if (authAlertReturnFocus === "otp") {
    focusFirstEmptyOtpDigit();
  } else {
    elements.emailInput.focus();
  }

  authAlertReturnFocus = null;
}

function openAuthAlert(title, message, options = {}) {
  if (elements.authAlertTitle) {
    elements.authAlertTitle.textContent = String(title || "Let’s get you set up");
  }

  if (elements.authAlertMessage) {
    elements.authAlertMessage.textContent = String(message || "If you need help, contact me and I’ll take care of it.");
  }

  authAlertReturnFocus = options.returnFocus || null;
  state.authAlertOpen = true;
  syncAuthAlertState();

  window.requestAnimationFrame(() => {
    elements.authAlertDismissButton?.focus();
  });
}

function closeAuthAlert() {
  if (!state.authAlertOpen) {
    return;
  }

  state.authAlertOpen = false;
  syncAuthAlertState();

  const returnFocus = authAlertReturnFocus;
  authAlertReturnFocus = null;

  window.requestAnimationFrame(() => {
    if (returnFocus === "otp") {
      focusFirstEmptyOtpDigit();
      return;
    }

    if (returnFocus === "email") {
      elements.emailInput.focus();
    }
  });
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

function loadClientState(email) {
  const saved = loadJson(getClientKey(email), null) || {};
  const savedPrompt = saved.guidance || {};
  const savedSimulator = saved.simulator || {};
  const featuresSource = Array.isArray(saved.features) && saved.features.length
    ? saved.features
    : DEFAULT_FEATURES;
  const features = featuresSource.map((feature, index) => {
    const fallbackPrompt = index === 0 ? { ...DEFAULT_PROMPT, ...savedPrompt } : DEFAULT_PROMPT;
    const featureId = String(feature?.id || "");
    const featureName = String(feature?.name || "");
    const featureMode = String(feature?.mode || "");
    const isLegacyDefaultFeature = index === 0
      && featureId === DEFAULT_FEATURES[0].id
      && (
        LEGACY_DEFAULT_FEATURE_NAMES.has(featureName)
        || LEGACY_DEFAULT_FEATURE_MODES.has(featureMode)
      );

    return {
      id: featureId || `feature-${index + 1}`,
      name: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].name
        : String(feature?.name || `Tool ${index + 1}`),
      description: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].description
        : String(feature?.description || ""),
      channel: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].channel
        : String(feature?.channel || "Web"),
      mode: isLegacyDefaultFeature
        ? DEFAULT_FEATURES[0].mode
        : String(feature?.mode || "Default"),
      status: String(feature?.status || "Active"),
      activated: Boolean(feature?.activated ?? feature?.isActivated ?? false),
      launchUrl: String(
        feature?.launchUrl
        || (index === 0 ? DEFAULT_FEATURE_LAUNCH_URL : "")
      ).trim(),
      pricing: normalizeFeaturePricing(feature?.pricing || {}),
      prompt: normalizePrompt(feature?.prompt || {}, fallbackPrompt),
      whatsapp: normalizeFeatureWhatsApp(feature?.whatsapp || feature?.activation || {}),
    };
  });
  const settings = { ...DEFAULT_SETTINGS, ...(saved.settings || {}) };
  const simulator = normalizeSimulatorState(savedSimulator, savedPrompt);

  if (!settings.workspaceName || isLegacyWorkspaceName(settings.workspaceName)) {
    settings.workspaceName = DEFAULT_SETTINGS.workspaceName;
  }

  return {
    settings,
    features,
    simulator,
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

function normalizeFeatureWhatsApp(config = {}) {
  const source = config && typeof config === "object" ? config : {};
  return {
    verify_token: String(source.verify_token || source.verifyToken || "").trim(),
    access_token: String(source.access_token || source.accessToken || "").trim(),
    phone_number_id: String(source.phone_number_id || source.phoneNumberId || "").trim(),
    app_secret: String(source.app_secret || source.appSecret || "").trim(),
    owner_wa_id: String(source.owner_wa_id || source.ownerWaId || "").trim(),
    allow_mock_send: Boolean(source.allow_mock_send ?? source.allowMockSend ?? true),
  };
}

function getFeaturePricing(feature = getSelectedFeature()) {
  return normalizeFeaturePricing(feature?.pricing || DEFAULT_FEATURE_PRICING);
}

function formatFeaturePricingLabel(feature = getSelectedFeature(), currency = "USD") {
  const pricing = getFeaturePricing(feature);
  return `${pricing.billingMultiplier.toFixed(1)}x token cost · ${formatCurrency(pricing.minimumMonthlyCharge, currency)} minimum per tool`;
}

function buildFeaturePitch(feature = getSelectedFeature()) {
  const prompt = feature?.prompt || getSelectedPrompt();
  const scenario = SCENARIOS[prompt.scenario] ?? SCENARIOS.approval;
  const title = feature?.name || "This tool";
  return `${title} keeps replies human and fast. For example, when someone says "${scenario.user}", it drafts "${scenario.ask}" and keeps the final send inside WhatsApp for review.`;
}

function buildFeatureExample(feature = getSelectedFeature()) {
  const prompt = feature?.prompt || getSelectedPrompt();
  const scenario = SCENARIOS[prompt.scenario] ?? SCENARIOS.approval;
  return {
    sender: scenario.sender || "Customer",
    label: "Example",
    incoming: scenario.user,
    outgoing: buildResponseText(prompt),
  };
}

function buildFeatureEditorHint(feature = getSelectedFeature()) {
  const pricing = getFeaturePricing(feature);
  return `Open the editor before payment. This tool bills at ${pricing.billingMultiplier.toFixed(1)}x token cost with a ${formatCurrency(pricing.minimumMonthlyCharge, "USD")} minimum per tool.`;
}

function buildWhatsAppConfigHint() {
  return "Put the phone number and WhatsApp credentials in the client backend config at `clients/<client-id>/backend.json` under `whatsapp.*`.";
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

function normalizePrompt(prompt = {}, fallback = DEFAULT_PROMPT) {
  const base = { ...DEFAULT_PROMPT, ...(fallback || {}), ...(prompt || {}) };
  const responseStyle = String(base.responseStyle || DEFAULT_PROMPT.responseStyle).toLowerCase();
  const scenario = SCENARIOS[base.scenario] ? base.scenario : DEFAULT_PROMPT.scenario;

  return {
    toneGuidance: String(base.toneGuidance || DEFAULT_PROMPT.toneGuidance),
    replyRules: String(base.replyRules || DEFAULT_PROMPT.replyRules),
    businessNotes: String(base.businessNotes || DEFAULT_PROMPT.businessNotes),
    escalationGuidance: String(base.escalationGuidance || DEFAULT_PROMPT.escalationGuidance),
    exampleReplies: String(base.exampleReplies || DEFAULT_PROMPT.exampleReplies),
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
  return getFeatureById(state.selectedFeatureId) || clientState.features[0] || DEFAULT_FEATURES[0];
}

function getSelectedPrompt() {
  return getSelectedFeature()?.prompt || { ...DEFAULT_PROMPT };
}

function normalizeFeatureStudioView(view) {
  const nextView = String(view || "").trim().toLowerCase();
  return VALID_FEATURE_STUDIO_VIEWS.has(nextView) ? nextView : null;
}

function isFeatureActivated(feature = getSelectedFeature()) {
  return Boolean(feature && feature.activated);
}

function getFeatureActivationLabel(feature = getSelectedFeature()) {
  return isFeatureActivated(feature) ? "Active" : "Preview";
}

function getDefaultFeatureStudioView(feature = getSelectedFeature()) {
  return isFeatureActivated(feature) ? "editor" : "overview";
}

function getSelectedFeatureStudioView(feature = getSelectedFeature()) {
  return isFeatureActivated(feature)
    ? "editor"
    : normalizeFeatureStudioView(state.featureStudioView) || getDefaultFeatureStudioView(feature);
}

function getSelectedFeatureWhatsApp(feature = getSelectedFeature()) {
  return normalizeFeatureWhatsApp(feature?.whatsapp || {});
}

function formatFeatureActivationFieldLabel(key) {
  const labels = {
    access_token: "Access token",
    phone_number_id: "Phone number ID",
    verify_token: "Verify token",
    owner_wa_id: "Owner WhatsApp ID",
    app_secret: "App secret",
  };

  return labels[key] || key;
}

function getMissingFeatureActivationFields(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  return ["access_token", "phone_number_id", "verify_token", "owner_wa_id"].filter((key) => !String(whatsapp[key] || "").trim());
}

function getFeatureActivationSummary(feature = getSelectedFeature()) {
  const whatsapp = getSelectedFeatureWhatsApp(feature);
  const missing = getMissingFeatureActivationFields(feature);

  if (missing.length) {
    const readableMissing = missing.map(formatFeatureActivationFieldLabel);
    const needsList = readableMissing.length === 1
      ? readableMissing[0]
      : `${readableMissing.slice(0, -1).join(", ")} and ${readableMissing[readableMissing.length - 1]}`;
    return `Fill ${needsList} to unlock activation. App secret is recommended for signature checks.`;
  }

  return whatsapp.app_secret
    ? "All required WhatsApp keys are in place. Activating will start billing and switch you to the editor."
    : "All required WhatsApp keys are in place. App secret is recommended for signature checks before you activate.";
}

function getFeatureStudioStatusLabel(feature = getSelectedFeature(), view = getSelectedFeatureStudioView(feature)) {
  if (isFeatureActivated(feature)) {
    return "Active";
  }

  if (view === "activation") {
    return "Setup";
  }

  return "Preview";
}

function persistClientState() {
  persistJson(getClientKey(activeEmail), clientState);
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

function formatUsageDateSummary(dates = []) {
  const uniqueDates = Array.from(
    new Set(
      (Array.isArray(dates) ? dates : [])
        .map((value) => String(value || "").trim())
        .filter(Boolean),
    ),
  );

  if (!uniqueDates.length) {
    return "";
  }

  const visibleDates = uniqueDates.slice(0, 3).map(formatUsageDate).filter(Boolean);
  const extraCount = Math.max(0, uniqueDates.length - visibleDates.length);
  const suffix = extraCount > 0 ? ` +${extraCount} more` : "";
  return `Used on ${visibleDates.join(", ")}${suffix}`;
}

function formatModelName(value) {
  const model = String(value || "").trim();
  if (!model) {
    return "Unknown model";
  }

  return model.replace(/^gpt-/i, "GPT-").replace(/^gpt/i, "GPT");
}

function normalizeBillingModel(model = {}) {
  const usageDatesSource = Array.isArray(model.usageDates) ? model.usageDates : [];
  return {
    model: String(model.model || model.name || "Unknown model").trim() || "Unknown model",
    tokensUsed: Math.max(0, Math.round(Number(model.tokensUsed ?? model.tokens ?? model.token_count ?? 0))),
    baseCostUsd: Number(model.baseCostUsd ?? model.base_cost_usd ?? 0) || 0,
    inputTokensUsed: Math.max(0, Math.round(Number(model.inputTokensUsed ?? model.input_tokens ?? 0))),
    outputTokensUsed: Math.max(0, Math.round(Number(model.outputTokensUsed ?? model.output_tokens ?? 0))),
    inputChargeUsd: Number(model.inputChargeUsd ?? model.input_charge_usd ?? 0) || 0,
    outputChargeUsd: Number(model.outputChargeUsd ?? model.output_charge_usd ?? 0) || 0,
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

  return {
    month: String(month.month || "").trim(),
    label: String(month.label || currentMonthLabel).trim() || currentMonthLabel,
    tokensUsed,
    baseCostUsd: Number(baseCostUsd.toFixed(2)),
    inputTokensUsed,
    outputTokensUsed,
    inputChargeUsd: Number(inputChargeUsd.toFixed(2)),
    outputChargeUsd: Number(outputChargeUsd.toFixed(2)),
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
      || (report.source === "database" ? "Latest billing snapshot" : report.source === "defaults" ? "Sample billing data" : "Billing data"),
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
    return `Billed at ${inputMultiplier.toFixed(1)}x the token cost · ${minimum} minimum per tool`;
  }

  return `Billed at ${inputMultiplier.toFixed(1)}x input token cost · ${outputMultiplier.toFixed(1)}x output token cost · ${minimum} minimum per tool`;
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
      status: String(feature?.status || "Active").trim(),
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
    const minimumMonthlyCharge = Number(catalogTool?.pricing?.minimumMonthlyCharge || month?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM) || DEFAULT_BILLING_MINIMUM;

    const existing = toolMap.get(key) || (catalog.length === 1 ? fallbackUnassignedTool : null);
    const tool = existing
      ? {
          ...existing,
          toolId: key,
          toolName: catalogTool.toolName || existing.toolName,
          minimumMonthlyCharge,
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
          chargeUsd: Number(minimumMonthlyCharge.toFixed(2)),
          minimumApplied: true,
          currency: month?.currency || "USD",
          usageCount: 0,
          usageDates: [],
          models: [],
          minimumMonthlyCharge,
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
      const minimumMonthlyCharge = Number(tool.minimumMonthlyCharge || month?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM) || DEFAULT_BILLING_MINIMUM;
      const rawChargeUsd = Number(tool.baseCostUsd || 0);
      const chargeUsd = tool.chargeUsd > 0
        ? Number(Math.max(tool.chargeUsd, minimumMonthlyCharge).toFixed(2))
        : Number(Math.max(rawChargeUsd, minimumMonthlyCharge).toFixed(2));
      return {
        ...tool,
        currency,
        chargeUsd,
        minimumApplied: Boolean(tool.minimumApplied || rawChargeUsd < minimumMonthlyCharge || tool.chargeUsd <= 0),
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
  const chargeUsd = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.chargeUsd || 0)), 0);
  const usageDates = Array.from(new Set(normalizedTools.flatMap((tool) => tool.usageDates || [])));
  const usageCount = normalizedTools.reduce((sum, tool) => sum + Math.max(0, Number(tool.usageCount || 0)), 0);
  const minimumApplied = normalizedTools.some((tool) => tool.minimumApplied);

  return {
    ...month,
    tokensUsed,
    baseCostUsd: Number(baseCostUsd.toFixed(2)),
    inputTokensUsed,
    outputTokensUsed,
    inputChargeUsd: Number(inputChargeUsd.toFixed(2)),
    outputChargeUsd: Number(outputChargeUsd.toFixed(2)),
    chargeUsd: Number(chargeUsd.toFixed(2)),
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
      message: report
        ? "The latest refresh didn’t come through, but your last snapshot is still visible."
        : "I’m having trouble reaching billing right now.",
      meta: report
        ? "Refresh billing to try again. I’ll keep the last good snapshot on screen while we wait."
        : "Try Refresh billing. If it keeps failing, I’ll check the billing connection.",
    };
  }

  if (isLoading) {
    return {
      message: report ? "Refreshing the billing snapshot..." : "Loading billing data...",
      meta: report ? "Showing the last loaded snapshot while I refresh." : "This usually takes just a moment.",
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

  if (!currentMonth) {
    return "Projected payment data will appear here once billing loads.";
  }

  const charged = formatCurrency(currentMonth.chargeUsd, report?.currency || "USD");
  if (!currentMonth.tools?.length || !currentMonth.tokensUsed) {
    return nextPaymentDate
      ? `Projected payment will update as usage grows. Next payment: ${nextPaymentDate}.`
      : "Projected payment will update as usage grows.";
  }

  return nextPaymentDate
    ? `Projected payment is ${charged} so far. Next payment: ${nextPaymentDate}.`
    : `Projected payment is ${charged} so far.`;
}

function buildBillingHelpBody(report) {
  const pricingLabel = getBillingPricingLabel(report);
  const minimum = formatCurrency(report?.minimumMonthlyCharge || DEFAULT_BILLING_MINIMUM, report?.currency || "USD");
  const nextPaymentDate = formatBillingDate(getNextBillingPaymentDate(report));
  const helpLines = [
    "We bill each tool separately each month.",
    `The rate is ${pricingLabel}, with a ${minimum} minimum per tool. If a tool’s token total for the month stays below the minimum, we charge the minimum instead.`,
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
    return "Latest billing snapshot";
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
  const source = getDisplayName() || activeEmail;
  const parts = source.split(/\s+/).filter(Boolean);
  const initials = parts.slice(0, 2).map((part) => part[0]).join("");
  return (initials || "G").toUpperCase();
}

function setView(view) {
  document.body.dataset.view = view;
  if (view !== "app") {
    delete document.body.dataset.modal;
  }
  elements.authView.classList.toggle("is-hidden", view !== "auth");
  elements.appView.classList.toggle("is-hidden", view !== "app");
}

function setStatus(message) {
  if (!elements.saveState) {
    return;
  }

  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date());

  elements.saveState.textContent = `${message} · ${time}`;
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
  if (VALID_SETTINGS_MODES.has(mode)) {
    state.settingsMode = mode;
  }

  state.selectedFeatureId = null;
  closeFeatureStudioMenu();
  closeBillingHelp();

  if (state.activeTab !== "settings" && VALID_TABS.has(state.activeTab)) {
    state.lastPrimaryTab = state.activeTab;
    persistLastPrimaryTab();
  }

  state.settingsOpen = true;
  closeMenu();
  setHashForTab("settings");
  renderApp();
}

function closeSettings() {
  state.settingsOpen = false;
  closeBillingHelp();
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
  if (options.settingsMode && VALID_SETTINGS_MODES.has(options.settingsMode)) {
    state.settingsMode = options.settingsMode;
  }

  if (options.syncHash !== false) {
    setHashForTab(nextTab);
  }

  closeMenu();
  renderApp();
  if (nextTab === "billing") {
    window.scrollTo(0, 0);
  }
}

function setSettingsMode(mode, options = {}) {
  if (!VALID_SETTINGS_MODES.has(mode)) {
    return;
  }

  state.settingsMode = mode;
  if (options.openSettings !== false) {
    openSettings(mode);
    return;
  }

  closeMenu();
  renderApp();
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

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
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
  const lines = [
    "Client tool draft",
    "",
    `Tool: ${feature?.name || "Unassigned tool"}`,
    `Channel: ${feature?.channel || "Web"}`,
    `Mode: ${feature?.mode || "Default"}`,
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
    "Business notes",
    ...bulletList(splitLines(prompt.businessNotes)),
    "",
    "Escalation rules",
    ...bulletList(splitLines(prompt.escalationGuidance)),
    "",
    "Example replies",
    ...bulletList(splitLines(prompt.exampleReplies)),
  ];

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
  setStatus(message || "Autosaved locally");
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
  const usageSummary = formatUsageDateSummary(model.usageDates);
  meta.textContent = [`${formatTokenCount(model.tokensUsed)} tokens`, usageSummary].filter(Boolean).join(" · ");

  copy.append(title, meta);

  const stats = document.createElement("div");
  stats.className = "billing-model-stats";

  const cost = document.createElement("strong");
  cost.textContent = formatCurrency(model.baseCostUsd, currency);

  const label = document.createElement("span");
  label.textContent = "Base spend";

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
  paidLabel.textContent = "Charged";

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
    ? `Base usage for this tool is ${formatCurrency(tool.baseCostUsd, currency)}.`
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
  note.textContent = month.tokensUsed
    ? `Base usage this month is ${formatCurrency(month.baseCostUsd, currency)}.`
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

  if (elements.billingStatusBanner) {
    elements.billingStatusBanner.classList.toggle("is-warn", hasError);
    elements.billingStatusBanner.classList.toggle("is-loading", isLoading);
  }
  if (elements.billingStatusMessage) {
    elements.billingStatusMessage.textContent = statusCopy.message;
  }
  if (elements.billingStatusMeta) {
    elements.billingStatusMeta.textContent = statusCopy.meta;
  }
  if (elements.billingRefreshButton) {
    elements.billingRefreshButton.disabled = state.billingLoading;
    elements.billingRefreshButton.textContent = hasError ? "Try again" : "Refresh billing";
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

async function refreshBillingReport() {
  if (!authSession?.token) {
    state.billingReport = null;
    state.billingLoading = false;
    state.billingError = "";
    return;
  }

  state.billingLoading = true;
  state.billingError = "";
  renderApp();

  try {
    const response = await apiRequest("/api/billing", {
      headers: {
        Authorization: `Bearer ${authSession.token}`,
      },
    });

    state.billingReport = normalizeBillingReport(response);
    state.billingError = "";
  } catch (error) {
    setBillingError(formatApiErrorMessage(error, "We couldn’t load billing data right now."));
  } finally {
    state.billingLoading = false;
    renderApp();
  }
}

function updateHeader() {
  const displayName = getDisplayName();
  const workspaceName = getWorkspaceName();
  const selectedFeature = getSelectedFeature();
  const titleLabel = state.settingsOpen
    ? "Settings"
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

  const meta = document.createElement("div");
  meta.className = "feature-meta";

  const channel = document.createElement("span");
  channel.textContent = feature.channel || "Web";

  const mode = document.createElement("span");
  mode.textContent = feature.mode || "Default";

  const pricing = document.createElement("span");
  pricing.textContent = formatFeaturePricingLabel(feature);

  meta.append(channel, mode, pricing);

  card.append(status, head, description, meta);
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

  if (isFeatureActivated(getSelectedFeature()) && nextView !== "editor") {
    state.featureStudioView = "editor";
  } else {
    state.featureStudioView = nextView;
  }

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
  state.featureStudioView = isFeatureActivated(feature)
    ? "editor"
    : normalizeFeatureStudioView(view) || getDefaultFeatureStudioView(feature);
  closeMenu();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, state.featureStudioView);
  renderApp();
  window.scrollTo(0, 0);
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
  state.featureStudioMenuOpen = false;
  if (elements.featureStudioMenu) {
    elements.featureStudioMenu.classList.add("is-hidden");
  }
  if (elements.featureStudioMenuButton) {
    elements.featureStudioMenuButton.setAttribute("aria-expanded", "false");
  }
}

function toggleFeatureStudioMenu(force) {
  if (!elements.featureStudioMenuButton || !elements.featureStudioMenu) {
    return;
  }

  const nextOpen = typeof force === "boolean" ? force : !state.featureStudioMenuOpen;
  state.featureStudioMenuOpen = nextOpen;
  elements.featureStudioMenu.classList.toggle("is-hidden", !nextOpen);
  elements.featureStudioMenuButton.setAttribute("aria-expanded", String(nextOpen));
}

function buildFeatureStudioMenu(feature) {
  if (!elements.featureStudioMenu) {
    return;
  }

  const launchUrl = String(feature?.launchUrl || "").trim();
  const items = [];

  if (launchUrl && isFeatureActivated(feature)) {
    const launchButton = document.createElement("button");
    launchButton.type = "button";
    launchButton.className = "menu-item";
    launchButton.dataset.featureAction = "launch";
    launchButton.textContent = "Open live dashboard";
    items.push(launchButton);
  }

  const deactivateButton = document.createElement("button");
  deactivateButton.type = "button";
  deactivateButton.className = "menu-item danger";
  deactivateButton.dataset.featureAction = "deactivate";
  deactivateButton.textContent = "Deactivate tool";
  items.push(deactivateButton);

  elements.featureStudioMenu.replaceChildren(...items);
}

function activateSelectedFeature() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  const missingFields = getMissingFeatureActivationFields(feature);
  if (missingFields.length) {
    setStatus(`Fill ${missingFields.map(formatFeatureActivationFieldLabel).join(", ")} before activating.`);
    return;
  }

  feature.activated = true;
  state.featureStudioView = "editor";
  persistClientState();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, "editor");
  renderApp();
  window.scrollTo(0, 0);
  setStatus("Activated the tool.");
}

function startFeatureActivation() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  state.featureStudioView = "activation";
  closeMenu();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, "activation");
  renderApp();
  window.scrollTo(0, 0);
  setStatus("Opened the activation setup.");
}

function deactivateSelectedFeature() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  feature.activated = false;
  state.featureStudioView = "overview";
  persistClientState();
  closeFeatureStudioMenu();
  setHashForTab("features", feature.id, "overview");
  renderApp();
  window.scrollTo(0, 0);
  setStatus("Deactivated the tool.");
}

function handleFeatureStudioMenuAction(action) {
  if (action === "launch") {
    openSelectedFeatureLaunchUrl();
    return;
  }

  if (action === "deactivate") {
    deactivateSelectedFeature();
  }
}

function updateFeatureActivationFields() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  const whatsapp = getSelectedFeatureWhatsApp(feature);
  if (elements.featureActivationAccessTokenInput) {
    elements.featureActivationAccessTokenInput.value = whatsapp.access_token;
  }
  if (elements.featureActivationPhoneNumberIdInput) {
    elements.featureActivationPhoneNumberIdInput.value = whatsapp.phone_number_id;
  }
  if (elements.featureActivationVerifyTokenInput) {
    elements.featureActivationVerifyTokenInput.value = whatsapp.verify_token;
  }
  if (elements.featureActivationOwnerWaIdInput) {
    elements.featureActivationOwnerWaIdInput.value = whatsapp.owner_wa_id;
  }
  if (elements.featureActivationAppSecretInput) {
    elements.featureActivationAppSecretInput.value = whatsapp.app_secret;
  }
  if (elements.featureActivationAllowMockSendInput) {
    elements.featureActivationAllowMockSendInput.checked = Boolean(whatsapp.allow_mock_send);
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

    if (key === "allow_mock_send") {
      feature.whatsapp[key] = Boolean(event.target.checked);
    } else {
      feature.whatsapp[key] = event.target.value;
    }

    persistClientState();
    updateFeatureStudioHeader();
    setStatus("Activation draft saved locally.");
  };
}

function updateFeatureStudioHeader() {
  const feature = getSelectedFeature();
  if (!feature) {
    return;
  }

  const example = buildFeatureExample(feature);
  const pricingLabel = formatFeaturePricingLabel(feature);
  const pitch = buildFeaturePitch(feature);
  const launchUrl = String(feature.launchUrl || "").trim();
  const isActivated = isFeatureActivated(feature);
  const studioView = getSelectedFeatureStudioView(feature);
  const activationSummary = getFeatureActivationSummary(feature);
  const activationReady = getMissingFeatureActivationFields(feature).length === 0;

  state.featureStudioView = studioView;

  if (elements.featureStudioHeaderLabel) {
    elements.featureStudioHeaderLabel.textContent = studioView === "editor"
      ? "Tool editor"
      : studioView === "activation"
        ? "Tool activation"
        : "Tool overview";
  }
  if (elements.featureStudioNav) {
    elements.featureStudioNav.classList.toggle("is-hidden", isActivated || studioView === "activation");
  }
  if (elements.featureStudioOverviewButton) {
    elements.featureStudioOverviewButton.classList.toggle("is-active", studioView === "overview");
    elements.featureStudioOverviewButton.setAttribute("aria-selected", String(studioView === "overview"));
  }
  if (elements.featureStudioEditorButton) {
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
  if (elements.featureStudioMenuWrap) {
    elements.featureStudioMenuWrap.classList.toggle("is-hidden", !isActivated);
  }
  if (elements.featureActivationStatus) {
    elements.featureActivationStatus.textContent = getFeatureStudioStatusLabel(feature, studioView);
  }
  if (elements.featureStudioStatus) {
    elements.featureStudioStatus.textContent = getFeatureStudioStatusLabel(feature, studioView);
  }
  elements.featureStudioTitle.textContent = feature.name;
  elements.featureStudioDescription.textContent = feature.description || "";
  elements.featureStudioChannel.textContent = `Channel: ${feature.channel || "Web"}`;
  elements.featureStudioMode.textContent = `Mode: ${feature.mode || "Default"}`;
  if (elements.featureStudioPricing) {
    elements.featureStudioPricing.textContent = pricingLabel;
  }
  if (elements.featureStudioPitch) {
    elements.featureStudioPitch.textContent = pitch;
  }
  if (elements.featureStudioExampleSender) {
    elements.featureStudioExampleSender.textContent = example.sender;
  }
  if (elements.featureStudioExampleLabel) {
    elements.featureStudioExampleLabel.textContent = example.label;
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
    elements.featureStudioLaunchButton.textContent = "Activate tool";
    elements.featureStudioLaunchButton.dataset.launchUrl = launchUrl;
  }

  if (elements.featureStudioLaunchNote) {
    elements.featureStudioLaunchNote.hidden = isActivated || studioView === "activation";
    elements.featureStudioLaunchNote.textContent = "Open the activation page to enter the WhatsApp keys and routing data before billing starts.";
  }

  if (elements.featureActivationSummary) {
    elements.featureActivationSummary.textContent = activationSummary;
  }
  if (elements.featureStudioActivationButton) {
    elements.featureStudioActivationButton.disabled = !activationReady || isActivated;
  }

  buildFeatureStudioMenu(feature);
}

function updatePromptFields() {
  const prompt = getSelectedPrompt();
  elements.toneGuidance.value = prompt.toneGuidance;
  elements.responseStyle.value = prompt.responseStyle;
  elements.replyRules.value = prompt.replyRules;
  elements.businessNotes.value = prompt.businessNotes;
  elements.escalationGuidance.value = prompt.escalationGuidance;
  elements.exampleReplies.value = prompt.exampleReplies;
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
  for (const button of elements.settingsButtons) {
    const isActive = button.dataset.settingsMode === state.settingsMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  }

  const showAccount = state.settingsMode === "account";
  elements.accountSettingsPane.classList.toggle("is-hidden", !showAccount);
  elements.preferencesSettingsPane.classList.toggle("is-hidden", showAccount);
}

function updatePanelVisibility() {
  const inStudio = state.activeTab === "features" && Boolean(state.selectedFeatureId);
  const inBilling = state.activeTab === "billing";
  const feature = inStudio ? getSelectedFeature() : null;
  const studioView = inStudio ? getSelectedFeatureStudioView(feature) : "overview";
  elements.appBar.classList.toggle("is-hidden", inStudio || inBilling);
  elements.appView.classList.toggle("is-feature-page", inStudio);
  elements.featuresPanel.classList.toggle("is-hidden", state.activeTab !== "features" || inStudio);
  elements.featureStudioPanel.classList.toggle("is-hidden", !inStudio);
  elements.previewPanel.classList.toggle("is-hidden", state.activeTab !== "preview");
  elements.simulatorPanel.classList.toggle("is-hidden", state.activeTab !== "simulator");
  elements.billingPanel.classList.toggle("is-hidden", state.activeTab !== "billing");
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
}

function renderApp() {
  updateHeader();
  updateTabButtons();
  updateFeatureStudioHeader();
  updatePanelVisibility();
  updateFeatureList();
  updateFeatureActivationFields();
  updatePromptFields();
  updatePreview();
  updateSimulatorPanel();
  updateBillingPanel();
  updateSettingsButtons();
  updateSettingsFields();
  setStatus("Autosaved locally");
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

function refreshView() {
  if (isSignedIn()) {
    const route = resolveRouteFromHash();
    const rawHash = window.location.hash.replace(/^#/, "");

    if (route.tab === "settings") {
      state.selectedFeatureId = null;
      state.selectedSimulatorId = null;
      closeFeatureStudioMenu();
      state.settingsOpen = true;
      state.activeTab = VALID_TABS.has(state.lastPrimaryTab) && state.lastPrimaryTab !== "settings"
        ? state.lastPrimaryTab
        : "features";
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
        state.featureStudioView = isFeatureActivated(feature)
          ? "editor"
          : selectedView || getDefaultFeatureStudioView(feature);
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
    return;
  }

  setView("auth");
  renderAuth(activeEmail);
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
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
  authSession = {
    email: activeEmail,
    token,
    signedIn: true,
    signedInAt: Date.now(),
    issuedAt: session?.issuedAt || Date.now(),
    expiresAt: session?.expiresAt || 0,
  };
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
  setHashForTab("features");
  setView("app");
  renderApp();
  void refreshBillingReport();
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
  state.settingsOpen = false;
  state.lastPrimaryTab = "features";
  persistLastPrimaryTab();
  closeBillingHelp();

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
    setStatus("Autosaved locally");
  };
}

function syncSettingsField(key) {
  return (event) => {
    clientState.settings[key] = event.target.value;
    persistClientState();
    updateHeader();
    updateSettingsFields();
    setStatus("Autosaved locally");
  };
}

function handleMenuAction(action) {
  if (action === "billing") {
    setActiveTab("billing");
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

function openSelectedFeatureLaunchUrl() {
  const feature = getSelectedFeature();
  const launchUrl = String(feature?.launchUrl || "").trim();
  if (!launchUrl) {
    const editor = document.querySelector(`#${DEFAULT_TOOL_EDITOR_TARGET_ID}`);
    if (editor && typeof editor.scrollIntoView === "function") {
      editor.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (elements.toneGuidance && typeof elements.toneGuidance.focus === "function") {
      elements.toneGuidance.focus();
    }
    setStatus("Opened the tool editor.");
    return;
  }

  window.open(launchUrl, "_blank", "noopener,noreferrer");
  setStatus(`Opened ${feature.name || "the live tool"}`);
}

async function bootstrapAuthState() {
  const storedSession = normalizeStoredSession(loadJson(AUTH_SESSION_KEY, null));
  authChallenge = normalizeStoredChallenge(loadJson(AUTH_CHALLENGE_KEY, null));
  activeEmail = normalizeEmail(storedSession?.email || authChallenge?.email || "");
  clientState = loadClientState("");
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;

  if (storedSession?.token) {
    setView("auth");
    renderAuth(activeEmail);

    try {
      const response = await apiRequest("/api/auth/session", {
        headers: {
          Authorization: `Bearer ${storedSession.token}`,
        },
      });

      authSession = normalizeStoredSession({
        email: response.email || storedSession.email,
        token: response.token || storedSession.token,
        signedInAt: response.issuedAt || storedSession.signedInAt || Date.now(),
        expiresAt: response.expiresAt || storedSession.expiresAt || 0,
      });
      activeEmail = normalizeEmail(authSession?.email || "");
      clientState = loadClientState(activeEmail);
      state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
      clearAuthChallenge();
      persistJson(AUTH_SESSION_KEY, authSession);
      state.billingReport = null;
      state.billingLoading = true;
      state.billingError = "";
      refreshView();
      void refreshBillingReport();
      return;
    } catch (error) {
      const status = Number(error?.status || 0);
      if (status === 401 || status === 403) {
        clearAuthSession();
      } else {
        authSession = null;
        openAuthAlert(
          "Couldn’t verify session",
          formatApiErrorMessage(error, "We couldn’t verify your session. Please sign in again."),
          { returnFocus: "email" },
      );
    }
  }
  if (elements.billingHelpBody) {
    elements.billingHelpBody.replaceChildren(buildBillingHelpBody(report));
  }
  syncBillingHelpState();
}

  activeEmail = normalizeEmail(authChallenge?.email || storedSession?.email || "");
  clientState = loadClientState("");
  state.selectedSimulatorId = clientState.simulator.selectedApprovalId || clientState.simulator.approvals[0]?.approvalId || null;
  state.billingReport = null;
  state.billingLoading = true;
  state.billingError = "";
  refreshView();
  void refreshBillingReport();
}

function bindEvents() {
  ensureBillingMenuItem();

  elements.sendCodeButton.addEventListener("click", () => {
    void handlePrimaryAuthAction();
  });
  elements.authAlertDismissButton.addEventListener("click", closeAuthAlert);
  elements.authAlertOverlay.addEventListener("click", (event) => {
    if (event.target === elements.authAlertOverlay) {
      closeAuthAlert();
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
  elements.backToFeaturesButton.addEventListener("click", closeFeatureStudio);
  if (elements.billingRefreshButton) {
    elements.billingRefreshButton.addEventListener("click", () => {
      void refreshBillingReport();
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
      startFeatureActivation();
    });
  }
  if (elements.featureStudioActivationBackButton) {
    elements.featureStudioActivationBackButton.addEventListener("click", () => {
      setFeatureStudioView("overview");
    });
  }
  if (elements.featureStudioActivationButton) {
    elements.featureStudioActivationButton.addEventListener("click", () => {
      activateSelectedFeature();
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
  if (elements.featureStudioMenuButton) {
    elements.featureStudioMenuButton.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMenu();
      toggleFeatureStudioMenu();
    });
  }
  if (elements.featureStudioMenu) {
    elements.featureStudioMenu.addEventListener("click", (event) => {
      const item = event.target.closest("[data-feature-action]");
      if (!item) {
        return;
      }

      const action = item.dataset.featureAction || "";
      closeFeatureStudioMenu();
      handleFeatureStudioMenuAction(action);
    });
  }
  if (elements.featureActivationAccessTokenInput) {
    elements.featureActivationAccessTokenInput.addEventListener("input", syncFeatureActivationField("access_token"));
  }
  if (elements.featureActivationPhoneNumberIdInput) {
    elements.featureActivationPhoneNumberIdInput.addEventListener("input", syncFeatureActivationField("phone_number_id"));
  }
  if (elements.featureActivationVerifyTokenInput) {
    elements.featureActivationVerifyTokenInput.addEventListener("input", syncFeatureActivationField("verify_token"));
  }
  if (elements.featureActivationOwnerWaIdInput) {
    elements.featureActivationOwnerWaIdInput.addEventListener("input", syncFeatureActivationField("owner_wa_id"));
  }
  if (elements.featureActivationAppSecretInput) {
    elements.featureActivationAppSecretInput.addEventListener("input", syncFeatureActivationField("app_secret"));
  }
  if (elements.featureActivationAllowMockSendInput) {
    elements.featureActivationAllowMockSendInput.addEventListener("change", syncFeatureActivationField("allow_mock_send"));
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
    const featureMenuWrap = elements.featureStudioMenuWrap;
    if (
      state.billingHelpOpen
      && billingHelpPopover
      && billingHelpButton
      && !billingHelpPopover.contains(event.target)
      && !billingHelpButton.contains(event.target)
    ) {
      closeBillingHelp();
    }

    if (
      state.featureStudioMenuOpen
      && featureMenuWrap
      && elements.featureStudioMenuButton
      && !featureMenuWrap.contains(event.target)
      && !elements.featureStudioMenuButton.contains(event.target)
    ) {
      closeFeatureStudioMenu();
    }

    if (!elements.accountMenu.contains(event.target) && !elements.accountMenuButton.contains(event.target)) {
      closeMenu();
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (state.authAlertOpen) {
        closeAuthAlert();
        return;
      }

      if (state.billingHelpOpen) {
        closeBillingHelp();
        return;
      }

      if (state.featureStudioMenuOpen) {
        closeFeatureStudioMenu();
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
        state.featureStudioView = route.subview && (!isFeatureActivated(feature) || route.subview === "editor")
          ? route.subview
          : defaultView;
        if (isFeatureActivated(feature)) {
          state.featureStudioView = "editor";
        }
        setHashForTab("features", state.selectedFeatureId, state.featureStudioView);
      } else if (state.activeTab === "simulator" && state.selectedSimulatorId) {
        setHashForTab("simulator", state.selectedSimulatorId);
      } else if (rawHash && rawHash !== route.tab) {
        setHashForTab(route.tab);
      }
      state.lastPrimaryTab = route.tab;
      persistLastPrimaryTab();
      renderApp();
      return;
    }

    if (!route.tab) {
      setHashForTab(state.settingsOpen ? "settings" : state.activeTab);
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
  elements.exampleReplies.addEventListener("input", syncPromptField("exampleReplies"));
  elements.scenarioSelect.addEventListener("change", syncPromptField("scenario"));

  elements.displayNameInput.addEventListener("input", syncSettingsField("displayName"));
  elements.workspaceNameInput.addEventListener("input", syncSettingsField("workspaceName"));
  elements.timezoneSelect.addEventListener("change", syncSettingsField("timezone"));

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
}

bindEvents();
void bootstrapAuthState();
