// The house's own page: who has an account, which features are switched on,
// how the assistant's turns are holding up, and the website leads. Families
// never come here - they live in WhatsApp - so this page signs in by email
// and shows nothing to anyone the server does not let manage clients.

const ADMIN_TABS = [
  { tab: "clients", label: "Clients", isAllowed: () => Boolean(session?.canManageClients) },
  { tab: "features", label: "Features", isAllowed: () => Boolean(session?.canManageClients) },
  { tab: "turns", label: "Turns", isAllowed: () => Boolean(session?.canManageClients) },
  { tab: "opportunities", label: "Opportunities", isAllowed: () => Boolean(session?.canReviewOpportunities) },
];
const ADMIN_CLIENT_TYPES = [
  { value: "paying", label: "Paying", className: "is-client-type-paying" },
  { value: "demo", label: "Demo", className: "is-client-type-demo" },
  { value: "qa", label: "QA", className: "is-client-type-qa" },
];
const DEFAULT_ADMIN_CLIENT_TYPE = "demo";

let session = null;
let pendingCodeEmail = "";
let authBusy = false;
let alertPrimaryAction = null;
let alertReturnFocus = null;

const state = {
  activeTab: "clients",
  adminUsers: [],
  adminUsersLoading: false,
  adminUsersNeedsRender: false,
  adminUsersError: "",
  adminSpendTotals: null,
  adminAddUserBusy: false,
  adminEditUserBusy: false,
  adminStatusBusyByEmail: {},
  adminTypeBusyByEmail: {},
  adminTrialBusyByEmail: {},
  adminDeleteBusyByEmail: {},
  adminView: "list",
  adminSelectedUserEmail: "",
  adminUserSearch: "",
  adminNewUserEmail: "",
  adminNewUserDisplayName: "",
  adminEditUserEmail: "",
  adminEditUserDisplayName: "",
  opportunities: [],
  opportunitiesLoading: false,
  opportunitiesLoadedAt: 0,
  opportunitiesError: "",
  featureSwitches: null,
  featureSwitchesLoading: false,
  featureSwitchesError: "",
  featureSwitchesBusy: {},
  agentTurns: null,
  agentTurnsLoading: false,
  agentTurnsLoadedAt: 0,
  agentTurnsError: "",
};

const elements = {
  loadingView: document.querySelector("#loadingView"),
  authView: document.querySelector("#authView"),
  deniedView: document.querySelector("#deniedView"),
  deniedEmail: document.querySelector("#deniedEmail"),
  deniedSignOutButton: document.querySelector("#deniedSignOutButton"),
  adminView: document.querySelector("#adminView"),
  authForm: document.querySelector("#authForm"),
  emailInput: document.querySelector("#emailInput"),
  codeField: document.querySelector("#codeField"),
  codeInput: document.querySelector("#codeInput"),
  authSubmitButton: document.querySelector("#authSubmitButton"),
  authMessage: document.querySelector("#authMessage"),
  changeEmailButton: document.querySelector("#changeEmailButton"),
  adminTabs: document.querySelector("#adminTabs"),
  accountEmail: document.querySelector("#accountEmail"),
  signOutButton: document.querySelector("#signOutButton"),
  saveState: document.querySelector("#saveState"),
  opportunitiesPanel: document.querySelector("#opportunitiesPanel"),
  opportunitiesRefreshButton: document.querySelector("#opportunitiesRefreshButton"),
  opportunitiesSummary: document.querySelector("#opportunitiesSummary"),
  opportunitiesList: document.querySelector("#opportunitiesList"),
  turnsPanel: document.querySelector("#turnsPanel"),
  turnsRefreshButton: document.querySelector("#turnsRefreshButton"),
  turnsSummary: document.querySelector("#turnsSummary"),
  turnsList: document.querySelector("#turnsList"),
  featureSwitchesPanel: document.querySelector("#featureSwitchesPanel"),
  featureSwitchesRefreshButton: document.querySelector("#featureSwitchesRefreshButton"),
  featureSwitchesContent: document.querySelector("#featureSwitchesContent"),
  adminUsersPane: document.querySelector("#clientsPanel"),
  adminUsersShell: document.querySelector("#adminUsersShell"),
  adminOpenAddUserButton: document.querySelector("#adminOpenAddUserButton"),
  adminUsersError: document.querySelector("#adminUsersError"),
  adminUsersContent: document.querySelector("#adminUsersContent"),
  alertOverlay: document.querySelector("#authAlertOverlay"),
  alertDialog: document.querySelector("#authAlertDialog"),
  alertEyebrow: document.querySelector("#authAlertEyebrow"),
  alertTitle: document.querySelector("#authAlertTitle"),
  alertMessage: document.querySelector("#authAlertMessage"),
  alertSecondaryButton: document.querySelector("#authAlertSecondaryButton"),
  alertDismissButton: document.querySelector("#authAlertDismissButton"),
};

function canManageClients() {
  return Boolean(session?.canManageClients);
}

function canReviewOpportunities() {
  return Boolean(session?.canReviewOpportunities);
}

function stripTags(value) {
  return String(value || "").replace(/<[^>]*>/g, " ");
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
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    };

    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body);
      headers.set("Content-Type", "application/json");
    }

    const response = await fetch(path, init);
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
      throw error;
    }

    return payload;
  } finally {
    window.clearTimeout(timeoutId);
  }
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
  elements.saveState.classList.add("is-visible");
}

// One dialog for every question and every failure on the page. Only the
// options the admin code asks for are honoured: a title, a message, an
// eyebrow, a confirm button with a cancel beside it, and where focus goes back.
function openAuthAlert(title, message, options = {}) {
  elements.alertEyebrow.textContent = String(options.eyebrow || "Admin");
  elements.alertTitle.textContent = String(title || "");
  elements.alertMessage.textContent = String(message || "");

  const secondaryLabel = normalizeText(options.secondaryButtonLabel);
  elements.alertSecondaryButton.textContent = secondaryLabel || "Cancel";
  elements.alertSecondaryButton.classList.toggle("is-hidden", !secondaryLabel);
  elements.alertDismissButton.textContent = String(options.buttonLabel || "OK");

  alertPrimaryAction = typeof options.onPrimary === "function" ? options.onPrimary : null;
  alertReturnFocus = options.returnFocus || null;
  elements.alertOverlay.classList.remove("is-hidden");

  // A frame between showing and opening, so the fade-in has a start.
  window.requestAnimationFrame(() => {
    elements.alertOverlay.classList.add("is-open");
    const target = options.focusTarget === "secondary" && secondaryLabel
      ? elements.alertSecondaryButton
      : elements.alertDismissButton;
    target.focus();
  });
}

function closeAuthAlert() {
  if (elements.alertOverlay.classList.contains("is-hidden")) {
    return;
  }

  elements.alertOverlay.classList.remove("is-open");
  elements.alertOverlay.classList.add("is-hidden");
  const returnFocus = alertReturnFocus;
  alertReturnFocus = null;
  alertPrimaryAction = null;
  if (returnFocus && typeof returnFocus.focus === "function") {
    window.requestAnimationFrame(() => returnFocus.focus());
  }
}

// -- Text and numbers --------------------------------------------------------

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function validateEmail(email) {
  return /^\S+@\S+\.\S+$/.test(email);
}

function capitalizeWords(value) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function deriveDisplayName(email) {
  const localPart = normalizeEmail(email).split("@")[0] || "";
  const readable = localPart.replace(/[._-]+/g, " ").trim();
  return readable ? capitalizeWords(readable) : "Client";
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

function describeHttpError(response) {
  const statusText = sanitizeErrorText(response?.statusText || "").replace(/\.$/, "");
  return statusText
    ? `The server returned ${response.status} ${statusText}. Please try again.`
    : `The server returned ${response.status}. Please try again.`;
}

function getEventTargetElement(event) {
  const target = event.target;
  if (target instanceof Element) {
    return target;
  }

  return target instanceof Node ? target.parentElement : null;
}


// -- Clients: records --------------------------------------------------------

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

function normalizeAdminTrial(trial = null) {
  const source = trial && typeof trial === "object" ? trial : {};
  const trialDays = Number(source.trialDays ?? source.trial_days ?? 0);
  const daysLeft = Number(source.daysLeft ?? source.days_left ?? 0);
  return {
    onTrial: Boolean(source.onTrial ?? source.on_trial),
    allowed: source.allowed === undefined ? true : Boolean(source.allowed),
    expired: Boolean(source.expired),
    trialDays: Number.isFinite(trialDays) ? Math.max(0, Math.round(trialDays)) : 0,
    endsAt: String(source.endsAt || source.ends_at || "").trim(),
    daysLeft: Number.isFinite(daysLeft) ? Math.max(0, Math.round(daysLeft)) : 0,
  };
}

function normalizeAdminTrialDays(value) {
  const text = String(value ?? "").trim();
  if (!text || !/^\d+$/.test(text)) {
    return null;
  }
  const days = Number.parseInt(text, 10);
  return Number.isFinite(days) ? days : null;
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

const SPEND_CHANNEL_LABELS = {
  web: "Web",
  whatsapp: "WhatsApp",
  background: "Background",
  unattributed: "Untracked",
};

function normalizeSpendChannels(value) {
  const source = value && typeof value === "object" ? value : {};
  const channels = {};
  for (const [name, entry] of Object.entries(source)) {
    const bucket = entry && typeof entry === "object" ? entry : {};
    const costUsd = Number(bucket.costUsd ?? bucket.cost_usd ?? 0);
    const usageUsd = Number(bucket.usageUsd ?? bucket.usage_usd ?? 0);
    const tokensUsed = Number(bucket.tokensUsed ?? bucket.tokens_used ?? 0);
    const usageCount = Number(bucket.usageCount ?? bucket.usage_count ?? 0);
    channels[String(name)] = {
      costUsd: Number.isFinite(costUsd) ? costUsd : 0,
      usageUsd: Number.isFinite(usageUsd) ? usageUsd : 0,
      tokensUsed: Number.isFinite(tokensUsed) ? Math.max(0, tokensUsed) : 0,
      usageCount: Number.isFinite(usageCount) ? Math.max(0, usageCount) : 0,
    };
  }
  return channels;
}

// "Web $0.20 · WhatsApp $0.53": the channels that cost something this month,
// in a fixed order, so the split reads the same on every row.
function describeSpendChannels(channels, currency) {
  const parts = [];
  for (const name of Object.keys(SPEND_CHANNEL_LABELS)) {
    const bucket = channels?.[name];
    if (!bucket || (!bucket.usageCount && !bucket.costUsd)) {
      continue;
    }
    parts.push(`${SPEND_CHANNEL_LABELS[name]} ${formatCurrency(bucket.costUsd, currency)}`);
  }
  return parts.join(" · ");
}

function normalizeAdminSpendTotals(value) {
  const payload = value && typeof value === "object" ? value : {};
  const currency = String(payload.currency || "USD").trim().toUpperCase() || "USD";
  const costUsd = Number(payload.costUsd ?? 0);
  const usageUsd = Number(payload.usageUsd ?? 0);
  const billedUsd = Number(payload.billedUsd ?? 0);
  const tokensUsed = Number(payload.tokensUsed ?? 0);
  const clientsWithUsage = Number(payload.clientsWithUsage ?? 0);
  return {
    month: String(payload.month || "").trim(),
    label: String(payload.label || "").trim(),
    currency,
    costUsd: Number.isFinite(costUsd) ? costUsd : 0,
    usageUsd: Number.isFinite(usageUsd) ? usageUsd : 0,
    billedUsd: Number.isFinite(billedUsd) ? billedUsd : 0,
    tokensUsed: Number.isFinite(tokensUsed) ? Math.max(0, tokensUsed) : 0,
    clientsWithUsage: Number.isFinite(clientsWithUsage) ? Math.max(0, clientsWithUsage) : 0,
    channels: normalizeSpendChannels(payload.channels),
  };
}

function normalizeAdminSpendMonth(entry = {}, currency = "USD") {
  const usageUsd = Number(entry.usageUsd ?? entry.usage_usd ?? 0);
  const costUsd = Number(entry.costUsd ?? entry.cost_usd ?? 0);
  const billedUsd = Number(entry.billedUsd ?? entry.billed_usd ?? 0);
  const tokensUsed = Number(entry.tokensUsed ?? entry.tokens_used ?? 0);
  const usageCount = Number(entry.usageCount ?? entry.usage_count ?? 0);
  const month = String(entry.month || "").trim();
  return {
    month,
    label: String(entry.label || "").trim() || formatBillingMonthLabel(month),
    usageUsd: Number.isFinite(usageUsd) ? usageUsd : 0,
    costUsd: Number.isFinite(costUsd) ? costUsd : 0,
    channels: normalizeSpendChannels(entry.channels),
    billedUsd: Number.isFinite(billedUsd) ? billedUsd : 0,
    minimumApplied: Boolean(entry.minimumApplied ?? entry.minimum_applied),
    tokensUsed: Number.isFinite(tokensUsed) ? Math.max(0, tokensUsed) : 0,
    usageCount: Number.isFinite(usageCount) ? Math.max(0, usageCount) : 0,
    currency: String(entry.currency || currency || "USD").trim().toUpperCase() || "USD",
  };
}

function normalizeAdminSpend(value) {
  const payload = value && typeof value === "object" ? value : {};
  const currency = String(payload.currency || "USD").trim().toUpperCase() || "USD";
  const minimumMonthlyCharge = Number(payload.minimumMonthlyCharge ?? payload.minimum_monthly_charge ?? 0);
  const lifetimeUsageUsd = Number(payload.lifetimeUsageUsd ?? payload.lifetime_usage_usd ?? 0);
  const lifetimeCostUsd = Number(payload.lifetimeCostUsd ?? payload.lifetime_cost_usd ?? 0);
  const previousMonths = Array.isArray(payload.previousMonths || payload.previous_months)
    ? (payload.previousMonths || payload.previous_months).map((entry) => normalizeAdminSpendMonth(entry, currency))
    : [];
  return {
    currency,
    isBilled: Boolean(payload.isBilled ?? payload.is_billed),
    billingNote: String(payload.billingNote || payload.billing_note || "").trim(),
    minimumMonthlyCharge: Number.isFinite(minimumMonthlyCharge) ? minimumMonthlyCharge : 0,
    currentMonth: normalizeAdminSpendMonth(payload.currentMonth || payload.current_month, currency),
    previousMonths: previousMonths.filter((entry) => entry.month),
    lifetimeUsageUsd: Number.isFinite(lifetimeUsageUsd) ? lifetimeUsageUsd : 0,
    lifetimeCostUsd: Number.isFinite(lifetimeCostUsd) ? lifetimeCostUsd : 0,
  };
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
    spend: normalizeAdminSpend(user.spend || user.spend_summary || null),
    trial: normalizeAdminTrial(user.trial || null),
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

function upsertAdminUserState(user) {
  const normalizedUser = normalizeAdminUserRecord(user);
  if (!normalizedUser.email) {
    return null;
  }

  const nextUsers = state.adminUsers.filter((entry) => entry.email !== normalizedUser.email);
  nextUsers.push(normalizedUser);
  state.adminUsers = sortAdminUsers(nextUsers);
  return normalizedUser;
}

function replaceAdminUserState(previousEmail, user) {
  const normalizedPreviousEmail = normalizeEmail(previousEmail);
  const normalizedUser = normalizeAdminUserRecord(user);
  if (!normalizedPreviousEmail || !normalizedUser.email) {
    return null;
  }

  state.adminUsers = sortAdminUsers([
    ...state.adminUsers.filter((entry) => entry.email !== normalizedPreviousEmail && entry.email !== normalizedUser.email),
    normalizedUser,
  ]);


  const { [normalizedPreviousEmail]: _statusBusy, ...nextStatusBusy } = state.adminStatusBusyByEmail;
  state.adminStatusBusyByEmail = nextStatusBusy;

  const { [normalizedPreviousEmail]: _typeBusy, ...nextTypeBusy } = state.adminTypeBusyByEmail;
  state.adminTypeBusyByEmail = nextTypeBusy;

  const { [normalizedPreviousEmail]: _trialBusy, ...nextTrialBusy } = state.adminTrialBusyByEmail;
  state.adminTrialBusyByEmail = nextTrialBusy;

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

  const { [normalizedEmail]: _statusBusy, ...nextStatusBusy } = state.adminStatusBusyByEmail;
  state.adminStatusBusyByEmail = nextStatusBusy;

  const { [normalizedEmail]: _typeBusy, ...nextTypeBusy } = state.adminTypeBusyByEmail;
  state.adminTypeBusyByEmail = nextTypeBusy;

  const { [normalizedEmail]: _trialBusy, ...nextTrialBusy } = state.adminTrialBusyByEmail;
  state.adminTrialBusyByEmail = nextTrialBusy;

  const { [normalizedEmail]: _deleteBusy, ...nextDeleteBusy } = state.adminDeleteBusyByEmail;
  state.adminDeleteBusyByEmail = nextDeleteBusy;

  if (normalizeEmail(state.adminSelectedUserEmail) === normalizedEmail) {
    state.adminSelectedUserEmail = "";
    state.adminView = "list";
  }
}


// -- Clients: views ----------------------------------------------------------

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

  if (normalizedEmail === normalizeEmail(session?.email || "")) {
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

  if (normalizedEmail === normalizeEmail(session?.email || "") && !nextIsActive) {
    return "You can't disable the admin account you're using right now.";
  }

  const activeAdminCount = state.adminUsers.filter((entry) => entry.isActive && entry.isAdmin).length;
  if (user?.isActive && user?.isAdmin && !nextIsActive && activeAdminCount <= 1) {
    return "Add another admin before disabling the last admin account.";
  }

  return "";
}

function createAdminStateBadge(label, className = "") {
  const badge = document.createElement("span");
  badge.className = `feature-status${className ? ` ${className}` : ""}`;
  badge.textContent = label;
  return badge;
}

function formatAdminTrialDate(value) {
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
  }).format(parsed);
}

function describeAdminTrial(user) {
  const trial = normalizeAdminTrial(user?.trial);
  const { isPaying } = normalizeAdminPaymentStatus(user?.paymentStatus);

  // A client who pays is not on a clock, so a leftover expiry on their record
  // must never make them read as cut off.
  if (isPaying) {
    return { label: "No limit", note: "Paying client", tone: "is-trial-open", trialDays: trial.trialDays };
  }

  // Zero is how the limit is removed, not a trial of no length. Reading this
  // before the expiry flag is what keeps "no limit" from showing as "ended".
  if (trial.trialDays <= 0) {
    return { label: "No limit", note: "", tone: "is-trial-open", trialDays: 0 };
  }

  if (trial.expired) {
    return {
      label: "Trial ended",
      note: trial.endsAt ? `Ended ${formatAdminTrialDate(trial.endsAt)}` : "",
      tone: "is-trial-ended",
      trialDays: trial.trialDays,
    };
  }

  const daysLeft = Math.max(0, trial.daysLeft);
  return {
    label: daysLeft === 1 ? "1 day left" : daysLeft > 1 ? `${daysLeft} days left` : "Last day",
    note: trial.endsAt ? `Ends ${formatAdminTrialDate(trial.endsAt)}` : "Not started yet",
    tone: daysLeft <= 1 ? "is-trial-ending" : "is-trial-running",
    trialDays: trial.trialDays,
  };
}

function createAdminTrialControl(user, options = {}) {
  const normalizedEmail = normalizeEmail(user?.email || "");
  const isBusy = Boolean(state.adminTrialBusyByEmail[normalizedEmail]);
  const summary = describeAdminTrial(user);

  const wrapper = document.createElement("div");
  wrapper.className = "admin-trial-control";

  const stateLabel = document.createElement("strong");
  stateLabel.className = `admin-trial-state ${summary.tone}`;
  stateLabel.textContent = summary.label;
  wrapper.append(stateLabel);

  if (summary.note) {
    const note = document.createElement("span");
    note.className = "admin-trial-note";
    note.textContent = summary.note;
    wrapper.append(note);
  }

  const field = document.createElement("label");
  field.className = "admin-trial-field";

  const input = document.createElement("input");
  input.type = "number";
  input.min = "0";
  input.step = "1";
  input.className = "admin-trial-input";
  input.value = String(summary.trialDays);
  input.dataset.adminTrialUser = normalizedEmail;
  input.dataset.adminTrialValue = String(summary.trialDays);
  input.disabled = Boolean(options.disabled) || isBusy;
  input.setAttribute(
    "aria-label",
    `Free trial length in days for ${user?.displayName || normalizedEmail || "client"}`,
  );

  const hint = document.createElement("span");
  hint.className = "admin-trial-hint";
  hint.textContent = "days (0 = no limit)";

  field.append(input, hint);
  wrapper.append(field);

  if (options.help) {
    const help = document.createElement("p");
    help.className = "admin-trial-help";
    help.textContent = "Changing the length keeps the days already used. Set 0 to remove the limit.";
    wrapper.append(help);
  }

  return wrapper;
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
      user.isActive ? "active" : "inactive",
      user.paymentStatus?.isPaying ? "paying" : "not paying",
      user.paymentStatus?.subscriptionStatus,
    ].join(" ").toLowerCase();
    return searchable.includes(query);
  });
}

function openAdminUsersList(options = {}) {
  state.adminView = "list";
  state.adminSelectedUserEmail = "";
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
  state.adminEditUserEmail = user.email;
  state.adminEditUserDisplayName = user.displayName || "";

  showClientsTab({ refresh: false });
  focusAdminEditUserInput();
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

function getAdminUserSpend(user) {
  return user && typeof user.spend === "object" && user.spend ? user.spend : normalizeAdminSpend(null);
}

function createAdminSpendSummary(user) {
  const spend = getAdminUserSpend(user);
  const month = spend.currentMonth;
  const wrapper = document.createElement("div");
  wrapper.className = "admin-spend-summary";

  const amount = document.createElement("strong");
  amount.className = "admin-spend-amount";
  amount.textContent = formatCurrency(month.costUsd, spend.currency);
  amount.title = `${formatTokenCount(month.tokensUsed)} tokens across ${month.usageCount} model call${month.usageCount === 1 ? "" : "s"}`;
  wrapper.append(amount);

  const split = describeSpendChannels(month.channels, spend.currency);
  if (split) {
    const channels = document.createElement("span");
    channels.className = "admin-spend-split";
    channels.textContent = split;
    wrapper.append(channels);
  }

  const note = document.createElement("span");
  note.className = "admin-spend-note";
  if (!spend.isBilled) {
    note.classList.add("is-not-billed");
    note.textContent = "Not billed";
    note.title = spend.billingNote || "This client is not billed.";
  } else if (month.minimumApplied) {
    note.textContent = `Billed ${formatCurrency(month.billedUsd, spend.currency)} (minimum)`;
  } else {
    note.textContent = `Billed ${formatCurrency(month.billedUsd, spend.currency)}`;
  }
  wrapper.append(note);

  return wrapper;
}

function createAdminSpendMonthRow(month, spend, options = {}) {
  const row = document.createElement("div");
  row.className = "admin-spend-row";
  if (options.isCurrent) {
    row.classList.add("is-current-month");
  }

  const label = document.createElement("span");
  label.className = "admin-spend-month";
  label.textContent = options.isCurrent ? `${month.label} (this month)` : month.label;

  const values = document.createElement("span");
  values.className = "admin-spend-values";

  const usage = document.createElement("strong");
  usage.textContent = formatCurrency(month.costUsd, spend.currency);
  values.append(usage);

  const split = describeSpendChannels(month.channels, spend.currency);
  if (split) {
    const channels = document.createElement("span");
    channels.className = "admin-spend-split";
    channels.textContent = split;
    values.append(channels);
  }

  const detail = document.createElement("span");
  detail.className = "admin-spend-row-note";
  if (!spend.isBilled) {
    detail.classList.add("is-not-billed");
    detail.textContent = "not billed";
  } else if (month.minimumApplied) {
    detail.textContent = `billed ${formatCurrency(month.billedUsd, spend.currency)} (minimum)`;
  } else {
    detail.textContent = `billed ${formatCurrency(month.billedUsd, spend.currency)}`;
  }
  values.append(detail);

  row.append(label, values);
  row.title = `${formatTokenCount(month.tokensUsed)} tokens across ${month.usageCount} usage event${month.usageCount === 1 ? "" : "s"}`;
  return row;
}

function createAdminSpendPanel(user) {
  const spend = getAdminUserSpend(user);
  const panel = document.createElement("section");
  panel.className = "admin-detail-panel admin-detail-spend-panel";

  const title = document.createElement("h4");
  title.textContent = "Spend";
  panel.append(title);

  const badge = createAdminStateBadge(
    spend.isBilled ? "Billed monthly" : "Not billed",
    spend.isBilled ? "is-billed-client" : "is-not-billed-client",
  );
  panel.append(badge);

  const stack = document.createElement("div");
  stack.className = "detail-stack admin-spend-stack";
  stack.append(createAdminSpendMonthRow(spend.currentMonth, spend, { isCurrent: true }));

  if (spend.previousMonths.length) {
    for (const month of spend.previousMonths) {
      stack.append(createAdminSpendMonthRow(month, spend));
    }
  } else {
    const empty = document.createElement("p");
    empty.className = "admin-spend-empty";
    empty.textContent = "No earlier months with usage yet.";
    stack.append(empty);
  }

  panel.append(stack);

  const costRow = createAdminDetailRow(
    "Cost to date",
    formatCurrency(spend.lifetimeCostUsd, spend.currency),
  );
  costRow.classList.add("admin-spend-total");
  panel.append(costRow);

  const totalRow = createAdminDetailRow(
    "Usage to date at client rates",
    formatCurrency(spend.lifetimeUsageUsd, spend.currency),
  );
  totalRow.classList.add("admin-spend-total");
  panel.append(totalRow);

  const note = document.createElement("p");
  note.className = "admin-spend-footnote";
  if (!spend.isBilled) {
    note.textContent = spend.billingNote || "This client is not billed.";
  } else if (spend.minimumMonthlyCharge > 0) {
    note.textContent = `Charged the larger of usage or the ${formatCurrency(spend.minimumMonthlyCharge, spend.currency)} monthly minimum.`;
  } else {
    note.textContent = "Charged for usage only.";
  }
  panel.append(note);

  return panel;
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

function createAdminUsersListView() {
  const wrapper = document.createElement("div");
  wrapper.className = "admin-users-view admin-users-list-view";

  const stats = getAdminClientStats();
  const totals = state.adminSpendTotals || normalizeAdminSpendTotals(null);
  const summary = document.createElement("div");
  summary.className = "clients-summary";
  const summaryItems = [
    ["Cost this month", formatCurrency(totals.costUsd, totals.currency), describeSpendChannels(totals.channels, totals.currency) || "What the model calls cost you"],
    ["Billed this month", formatCurrency(totals.billedUsd, totals.currency), "What clients pay"],
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
      "Add the first client here, then open them to see their usage and account details.",
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
  for (const heading of ["Client", "Email", "Client type", "Free trial", "Cost this month", "Active", "Last login", ""]) {
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

    const trialCell = document.createElement("td");
    trialCell.className = "admin-trial-cell";
    trialCell.append(createAdminTrialControl(user, {
      disabled: Boolean(state.adminDeleteBusyByEmail[user.email]),
    }));

    const spendCell = document.createElement("td");
    spendCell.className = "admin-spend-cell";
    spendCell.append(createAdminSpendSummary(user));

    const activeCell = document.createElement("td");
    activeCell.append(createAdminActiveSwitch(user, {
      disabled: Boolean(state.adminDeleteBusyByEmail[user.email]),
    }));

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
    row.append(nameCell, emailCell, clientTypeCell, trialCell, spendCell, activeCell, lastLoginCell, actionCell);
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
  const isEditingCurrentUser = normalizedUserEmail === normalizeEmail(session?.email || "");
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

  const isDeleting = Boolean(state.adminDeleteBusyByEmail[user.email]);
  const isStatusSaving = Boolean(state.adminStatusBusyByEmail[user.email]);
  const deleteDisabledReason = getAdminUserDeleteDisabledReason(user);

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

  strip.append(roleBadge, clientTypeBadge, activeBadge);

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
    createAdminDetailRow("Free trial", describeAdminTrial(user).label),
    createAdminDetailRow("Login", user.isActive ? "Active" : "Inactive"),
    createAdminDetailRow("Registered", formatAdminDateTime(user.registeredAt) || "Unknown"),
    createAdminDetailRow("Last login", user.lastLoginAt ? formatAdminDateTime(user.lastLoginAt) : "No login yet"),
    createAdminDetailRow("Usage events", String(Number.isFinite(user.usageCount) ? user.usageCount : 0)),
  );

  const infoActions = document.createElement("div");
  infoActions.className = "admin-detail-panel-actions";

  const statusControl = createAdminActiveSwitch(user, {
    disabled: isDeleting,
  });
  const clientTypeControl = createAdminClientTypeSelect(user, {
    disabled: isDeleting || isStatusSaving,
  });
  const trialControl = createAdminTrialControl(user, {
    disabled: isDeleting || isStatusSaving,
    help: true,
  });
  infoActions.append(clientTypeControl);
  infoActions.append(trialControl);
  infoActions.append(statusControl);

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "ghost-button small";
  editButton.dataset.adminOpenEditUser = user.email;
  editButton.disabled = isDeleting || isStatusSaving;
  editButton.textContent = "Edit client";
  infoActions.append(editButton);

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "ghost-button danger small";
  deleteButton.dataset.adminDeleteUser = user.email;
  deleteButton.disabled = isDeleting || isStatusSaving || Boolean(deleteDisabledReason);
  deleteButton.textContent = isDeleting ? "Deleting..." : "Delete client";
  infoActions.append(deleteButton);

  infoPanel.append(infoTitle, infoRows, infoActions);
  if (deleteDisabledReason) {
    const deleteNote = document.createElement("p");
    deleteNote.className = "admin-danger-note is-warn";
    deleteNote.textContent = deleteDisabledReason;
    infoPanel.append(deleteNote);
  }

  grid.append(infoPanel, createAdminSpendPanel(user));
  wrapper.append(strip, grid);
  return wrapper;
}

function renderAdminUsersPane() {
  const adminVisible = canManageClients();

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


// -- Clients: actions --------------------------------------------------------

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
  if (shouldRender && document.body.dataset.view === "admin") {
    renderApp();
  }

  try {
    const response = await apiRequest("/api/admin/users", {
      timeoutMs: options.timeoutMs || 15000,
    });

    state.adminSpendTotals = normalizeAdminSpendTotals(response.spendTotals);
    state.adminUsers = sortAdminUsers((Array.isArray(response.users) ? response.users : [])
      .map((user) => normalizeAdminUserRecord(user))
      .filter((user) => user.email));
    if (state.adminView === "detail" && !state.adminUsers.some((user) => user.email === state.adminSelectedUserEmail)) {
      state.adminView = "list";
      state.adminSelectedUserEmail = "";
    }

    return response;
  } catch (error) {
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t load clients right now.");
    return null;
  } finally {
    state.adminUsersLoading = false;
    if (document.body.dataset.view === "admin" && state.adminUsersNeedsRender) {
      state.adminUsersNeedsRender = false;
      renderApp();
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

async function saveAdminUserTrial(email, trialDays) {
  const normalizedEmail = normalizeEmail(email);
  const nextTrialDays = normalizeAdminTrialDays(trialDays);
  const user = state.adminUsers.find((entry) => entry.email === normalizedEmail);
  if (!canManageClients() || !user || nextTrialDays === null || state.adminTrialBusyByEmail[normalizedEmail]) {
    return;
  }

  const previousTrial = normalizeAdminTrial(user.trial);
  if (previousTrial.trialDays === nextTrialDays) {
    return;
  }

  state.adminTrialBusyByEmail = {
    ...state.adminTrialBusyByEmail,
    [normalizedEmail]: true,
  };
  state.adminUsers = state.adminUsers.map((entry) => (
    entry.email === normalizedEmail
      ? { ...entry, trial: { ...previousTrial, trialDays: nextTrialDays } }
      : entry
  ));
  state.adminUsersError = "";
  renderApp();

  let updatedUser = null;
  try {
    const response = await apiRequest(`/api/admin/users/${encodeURIComponent(normalizedEmail)}/trial`, {
      method: "POST",
      body: {
        trialDays: nextTrialDays,
      },
    });

    updatedUser = upsertAdminUserState(response.user || {
      ...user,
      trial: { ...previousTrial, trialDays: nextTrialDays },
    });
    void refreshAdminUsers({ render: false });
  } catch (error) {
    state.adminUsers = state.adminUsers.map((entry) => (
      entry.email === normalizedEmail
        ? { ...entry, trial: previousTrial }
        : entry
    ));
    state.adminUsersError = formatApiErrorMessage(error, "We couldn’t update that free trial right now.");
    openAuthAlert("Couldn’t update free trial", state.adminUsersError, {
      eyebrow: "Free trial",
      returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    });
  } finally {
    const { [normalizedEmail]: _ignore, ...nextBusy } = state.adminTrialBusyByEmail;
    state.adminTrialBusyByEmail = nextBusy;
    renderApp();
    if (updatedUser) {
      setStatus(nextTrialDays === 0
        ? "Free trial limit removed"
        : `Free trial set to ${nextTrialDays === 1 ? "1 day" : `${nextTrialDays} days`}`);
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
    });

    removeAdminUserState(normalizedEmail);
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


// -- Opportunities -----------------------------------------------------------

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
  if (shouldRender && document.body.dataset.view === "admin") {
    renderApp();
  }

  try {
    const response = await apiRequest("/api/admin/opportunities?limit=200", {
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
    return null;
  } finally {
    state.opportunitiesLoading = false;
    if (shouldRender && document.body.dataset.view === "admin") {
      renderApp();
    }
  }
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


// -- Features ----------------------------------------------------------------

async function refreshFeatureSwitches() {
  if (!canManageClients() || state.featureSwitchesLoading) {
    return null;
  }

  state.featureSwitchesLoading = true;
  state.featureSwitchesError = "";
  updateFeatureSwitchesPanel();

  try {
    state.featureSwitches = await apiRequest("/api/admin/features", { timeoutMs: 15000 });
    return state.featureSwitches;
  } catch (error) {
    state.featureSwitchesError = formatApiErrorMessage(error, "We couldn’t load the features right now.");
    return null;
  } finally {
    state.featureSwitchesLoading = false;
    updateFeatureSwitchesPanel();
  }
}

function setFeatureSwitchLocally(featureId, allowed) {
  const features = Array.isArray(state.featureSwitches?.features) ? state.featureSwitches.features : [];
  state.featureSwitches = {
    ...state.featureSwitches,
    features: features.map((feature) => (
      feature.featureId === featureId ? { ...feature, allowed } : feature
    )),
  };
}

async function saveFeatureSwitch(featureId, allowed) {
  if (!canManageClients() || state.featureSwitchesBusy[featureId]) {
    return;
  }

  state.featureSwitchesBusy = { ...state.featureSwitchesBusy, [featureId]: true };
  setFeatureSwitchLocally(featureId, allowed);
  updateFeatureSwitchesPanel();

  try {
    const response = await apiRequest("/api/admin/features", {
      method: "POST",
      body: { featureId, allowed },
    });
    state.featureSwitches = response;
    const featureLabel = (response.features || []).find((entry) => entry.featureId === featureId)?.label || featureId;
    setStatus(`${featureLabel} ${allowed ? "on" : "off"} for every account`);
  } catch (error) {
    setFeatureSwitchLocally(featureId, !allowed);
    openAuthAlert("Couldn’t change that feature", formatApiErrorMessage(error, "The change was not saved."), {
      eyebrow: "Features",
    });
  } finally {
    const { [featureId]: _ignore, ...nextBusy } = state.featureSwitchesBusy;
    state.featureSwitchesBusy = nextBusy;
    updateFeatureSwitchesPanel();
  }
}

function createFeatureSwitch(feature) {
  const allowed = Boolean(feature.allowed);
  const label = document.createElement("label");
  label.className = "admin-switch";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = allowed;
  input.disabled = Boolean(state.featureSwitchesBusy[feature.featureId]);
  input.dataset.featureSwitch = feature.featureId;
  input.setAttribute("aria-label", `${feature.label} for every account`);

  const track = document.createElement("span");
  track.className = "admin-switch-track";
  track.setAttribute("aria-hidden", "true");

  const text = document.createElement("span");
  text.className = "feature-switches-switch-text";
  text.textContent = allowed ? "On" : "Off";

  label.append(input, track, text);
  return label;
}

function createFeatureSwitchesTable(data) {
  const features = Array.isArray(data.features) ? data.features : [];

  const card = document.createElement("article");
  card.className = "glass-card turns-table-card feature-switches-card";
  const table = document.createElement("table");
  table.className = "turns-table feature-switches-table";

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  const featureHeading = document.createElement("th");
  featureHeading.textContent = "Feature";
  const switchHeading = document.createElement("th");
  switchHeading.className = "feature-switches-switch-heading";
  switchHeading.textContent = "Everyone";
  headRow.append(featureHeading, switchHeading);
  head.append(headRow);

  const body = document.createElement("tbody");
  for (const feature of features) {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    nameCell.className = "feature-switches-feature";
    const name = document.createElement("strong");
    name.textContent = feature.label;
    const description = document.createElement("span");
    description.textContent = feature.description;
    nameCell.append(name, description);
    const cell = document.createElement("td");
    cell.className = "feature-switches-switch-cell";
    cell.append(createFeatureSwitch(feature));
    row.append(nameCell, cell);
    body.append(row);
  }

  table.append(head, body);
  card.append(table);
  return card;
}

function createFeatureSwitchesAlwaysOn(data) {
  const card = document.createElement("article");
  card.className = "glass-card feature-switches-always-on";
  const title = document.createElement("h3");
  title.textContent = "Always on, for every account";
  const list = document.createElement("ul");
  for (const entry of Array.isArray(data.alwaysOn) ? data.alwaysOn : []) {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = entry.label;
    const description = document.createElement("span");
    description.textContent = entry.description;
    item.append(label, description);
    list.append(item);
  }
  card.append(title, list);
  return card;
}

function updateFeatureSwitchesPanel() {
  if (!elements.featureSwitchesPanel || !elements.featureSwitchesContent) {
    return;
  }

  if (elements.featureSwitchesRefreshButton) {
    elements.featureSwitchesRefreshButton.disabled = state.featureSwitchesLoading || !canManageClients();
    elements.featureSwitchesRefreshButton.textContent = state.featureSwitchesLoading ? "Refreshing" : "Refresh";
  }

  if (!canManageClients()) {
    elements.featureSwitchesContent.replaceChildren();
    return;
  }

  // A reload can land on this tab before anything asked for the list.
  if (state.featureSwitches === null && !state.featureSwitchesLoading && !state.featureSwitchesError && state.activeTab === "feature-switches") {
    void refreshFeatureSwitches();
  }

  const data = state.featureSwitches;
  if (state.featureSwitchesError && !data) {
    elements.featureSwitchesContent.replaceChildren(createAdminEmptyState("The features did not load", state.featureSwitchesError));
    return;
  }
  if (!data) {
    elements.featureSwitchesContent.replaceChildren(createAdminEmptyState("Loading features", "Reading which features are switched on."));
    return;
  }

  elements.featureSwitchesContent.replaceChildren(createFeatureSwitchesTable(data), createFeatureSwitchesAlwaysOn(data));
}


// -- Turns -------------------------------------------------------------------

async function refreshAgentTurns(options = {}) {
  if (!canManageClients() || state.agentTurnsLoading) {
    return null;
  }

  state.agentTurnsLoading = true;
  state.agentTurnsError = "";
  updateTurnsPanel();

  try {
    const response = await apiRequest("/api/admin/agent-turns?limit=60", {
      timeoutMs: options.timeoutMs || 15000,
    });
    state.agentTurns = response;
    state.agentTurnsLoadedAt = Date.now();
    return response;
  } catch (error) {
    state.agentTurnsError = formatApiErrorMessage(error, "We couldn’t load the turns right now.");
    return null;
  } finally {
    state.agentTurnsLoading = false;
    updateTurnsPanel();
  }
}

function formatTurnRate(value) {
  const percent = Number(value || 0) * 100;
  return `${percent >= 10 || percent === 0 ? percent.toFixed(0) : percent.toFixed(1)}%`;
}

function describeTurnCodes(byCode) {
  const entries = Object.entries(byCode || {});
  if (!entries.length) {
    return "";
  }
  return entries.slice(0, 4).map(([code, count]) => `${code} ×${count}`).join(", ");
}

function createTurnCell(text, className = "") {
  const cell = document.createElement("td");
  if (className) {
    cell.className = className;
  }
  cell.textContent = text;
  return cell;
}

function createTurnsTable(turns) {
  const wrap = document.createElement("article");
  wrap.className = "glass-card turns-table-card";
  const table = document.createElement("table");
  table.className = "turns-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["When", "Channel", "Outcome", "Tools", "Tokens", "Time", "Asked", "Answered"]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    headRow.append(cell);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const turn of turns) {
    const row = document.createElement("tr");
    if (turn.fallbackUsed) {
      row.classList.add("is-fallback");
    }
    const toolCalls = Array.isArray(turn.toolCalls) ? turn.toolCalls : [];
    const toolsText = toolCalls.length
      ? toolCalls.map((call) => {
        const status = call.ok ? "" : (call.code || "failed");
        const diagnostic = call.detail || status;
        return `${call.name}${diagnostic ? ` (${diagnostic})` : ""}`;
      }).join(", ")
      : "";
    const outcomeText = turn.fallbackUsed ? `${turn.outcome || "fallback"} · ${turn.fallbackReason || "fallback"}` : (turn.outcome || "");
    row.append(
      createTurnCell(turn.createdAt ? formatAdminDateTime(turn.createdAt) : "", "turns-cell-when"),
      createTurnCell(turn.channel || ""),
      createTurnCell(outcomeText + (turn.incompleteResponses ? " · cut off" : ""), "turns-cell-outcome"),
      createTurnCell(toolsText, "turns-cell-tools"),
      createTurnCell(`${Number(turn.inputTokens || 0) + Number(turn.outputTokens || 0)}`),
      createTurnCell(`${(Number(turn.latencyMs || 0) / 1000).toFixed(1)}s`),
      createTurnCell(turn.userMessage || "", "turns-cell-text"),
      createTurnCell(turn.reply || (turn.fallbackUsed ? "" : "—"), "turns-cell-text"),
    );
    row.title = turn.rawOutputOnFailure ? `Raw model text: ${turn.rawOutputOnFailure}` : `Turn ${turn.turnId}`;
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function updateTurnsPanel() {
  if (!elements.turnsPanel || !elements.turnsSummary || !elements.turnsList) {
    return;
  }

  if (elements.turnsRefreshButton) {
    elements.turnsRefreshButton.disabled = state.agentTurnsLoading || !canManageClients();
    elements.turnsRefreshButton.textContent = state.agentTurnsLoading ? "Refreshing" : "Refresh";
  }

  if (!canManageClients()) {
    elements.turnsSummary.replaceChildren();
    elements.turnsList.replaceChildren();
    return;
  }

  // The tab can be the one a reload lands on, in which case nothing asked
  // for the numbers yet: the first render asks. A failure stays on screen
  // rather than retrying on every render.
  if (state.agentTurns === null && !state.agentTurnsLoading && !state.agentTurnsError && state.activeTab === "turns") {
    void refreshAgentTurns();
  }

  const data = state.agentTurns;
  const day = data?.metrics?.day || {};
  const week = data?.metrics?.week || {};
  const loadedLabel = state.agentTurnsLoadedAt
    ? `Updated ${formatAdminDateTime(new Date(state.agentTurnsLoadedAt).toISOString())}`
    : "Not loaded yet";
  const alertLine = data?.alert ? `Alert above ${formatTurnRate(data.alert.rate)} on ${data.alert.minTurns}+ turns` : "";
  elements.turnsSummary.replaceChildren(
    createOpportunityMetric("Turns today", String(day.turns ?? 0), `${week.turns ?? 0} this week · ${loadedLabel}`),
    createOpportunityMetric(
      "Fallback rate",
      formatTurnRate(day.fallbackRate),
      `${day.fallbacks ?? 0} today · ${formatTurnRate(week.fallbackRate)} this week${alertLine ? ` · ${alertLine}` : ""}`,
    ),
    createOpportunityMetric(
      "Cut-off replies",
      formatTurnRate(day.incompleteRate),
      `${day.incompleteTurns ?? 0} today · ${formatTurnRate(week.incompleteRate)} this week`,
    ),
    createOpportunityMetric(
      "Tool errors",
      formatTurnRate(day.toolErrorRate),
      `${day.toolErrors ?? 0} of ${day.toolCalls ?? 0} today · ${formatTurnRate(week.toolErrorRate)} this week${describeTurnCodes(week.toolErrorsByCode) ? ` · ${describeTurnCodes(week.toolErrorsByCode)}` : ""}`,
    ),
  );

  if (state.agentTurnsError) {
    const error = document.createElement("article");
    error.className = "glass-card empty-state opportunity-empty is-warn";
    const title = document.createElement("h3");
    title.textContent = "The turns did not load";
    const copy = document.createElement("p");
    copy.textContent = state.agentTurnsError;
    error.append(title, copy);
    elements.turnsList.replaceChildren(error);
    return;
  }

  if (state.agentTurnsLoading && !data) {
    const loading = document.createElement("article");
    loading.className = "glass-card empty-state opportunity-empty";
    const title = document.createElement("h3");
    title.textContent = "Loading turns";
    const copy = document.createElement("p");
    copy.textContent = "Reading the last week of assistant turns.";
    loading.append(title, copy);
    elements.turnsList.replaceChildren(loading);
    return;
  }

  const recent = Array.isArray(data?.recent) ? data.recent : [];
  if (!recent.length) {
    const empty = document.createElement("article");
    empty.className = "glass-card empty-state opportunity-empty";
    const title = document.createElement("h3");
    title.textContent = "No turns in the last week";
    const copy = document.createElement("p");
    copy.textContent = "Every turn the assistant takes, over WhatsApp or here, will show up on this page.";
    empty.append(title, copy);
    elements.turnsList.replaceChildren(empty);
    return;
  }

  elements.turnsList.replaceChildren(createTurnsTable(recent));
}

// -- Tabs ---------------------------------------------------------------------

const TAB_PANELS = {
  clients: () => elements.adminUsersPane,
  features: () => elements.featureSwitchesPanel,
  turns: () => elements.turnsPanel,
  opportunities: () => elements.opportunitiesPanel,
};

function allowedTabs() {
  return ADMIN_TABS.filter((entry) => entry.isAllowed());
}

function tabFromHash() {
  const wanted = window.location.hash.replace(/^#/, "").trim().toLowerCase();
  return allowedTabs().some((entry) => entry.tab === wanted) ? wanted : "";
}

function refreshTab(tab) {
  if (tab === "clients") {
    void refreshAdminUsers();
  } else if (tab === "features") {
    void refreshFeatureSwitches();
  } else if (tab === "turns") {
    void refreshAgentTurns();
  } else if (tab === "opportunities") {
    void refreshOpportunities();
  }
}

function setActiveTab(tab, options = {}) {
  const allowed = allowedTabs();
  const next = allowed.some((entry) => entry.tab === tab) ? tab : (allowed[0]?.tab || "clients");
  state.activeTab = next;
  if (options.syncHash !== false && window.location.hash !== `#${next}`) {
    window.history.replaceState(null, "", `#${next}`);
  }
  renderApp();
  if (options.refresh !== false) {
    refreshTab(next);
  }
}

// The client views still call this by its old name: it is the Clients tab.
function showClientsTab(options = {}) {
  setActiveTab("clients", { refresh: options.refresh !== false });
}

function renderTabs() {
  const buttons = allowedTabs().map((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "admin-tab";
    button.dataset.tab = entry.tab;
    button.textContent = entry.label;
    const isActive = entry.tab === state.activeTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-current", isActive ? "page" : "false");
    return button;
  });
  elements.adminTabs.replaceChildren(...buttons);
}

function renderApp() {
  if (document.body.dataset.view !== "admin") {
    return;
  }

  renderTabs();
  for (const [tab, panel] of Object.entries(TAB_PANELS)) {
    panel()?.classList.toggle("is-hidden", tab !== state.activeTab);
  }

  if (state.activeTab === "clients") {
    renderAdminUsersPane();
  } else if (state.activeTab === "features") {
    updateFeatureSwitchesPanel();
  } else if (state.activeTab === "turns") {
    updateTurnsPanel();
  } else if (state.activeTab === "opportunities") {
    updateOpportunitiesPanel();
  }
}

// -- Signing in -------------------------------------------------------------

function setView(view) {
  document.body.dataset.view = view;
  elements.loadingView.classList.toggle("is-hidden", view !== "loading");
  elements.authView.classList.toggle("is-hidden", view !== "auth");
  elements.deniedView.classList.toggle("is-hidden", view !== "denied");
  elements.adminView.classList.toggle("is-hidden", view !== "admin");
}

function renderAuth(message = "") {
  const waitingForCode = Boolean(pendingCodeEmail);
  elements.codeField.classList.toggle("is-hidden", !waitingForCode);
  elements.emailInput.disabled = authBusy || waitingForCode;
  elements.codeInput.disabled = authBusy;
  elements.authSubmitButton.disabled = authBusy;
  elements.authSubmitButton.textContent = waitingForCode ? "Sign in" : "Send code";
  elements.changeEmailButton.classList.toggle("is-hidden", !waitingForCode);
  elements.authMessage.textContent = message
    || (waitingForCode ? `We sent a code to ${pendingCodeEmail}. It expires in 10 minutes.` : "We’ll email you a sign-in code.");
}

async function requestCode() {
  const email = normalizeEmail(elements.emailInput.value);
  if (!validateEmail(email)) {
    renderAuth("Enter a valid email address.");
    elements.emailInput.focus();
    return;
  }

  authBusy = true;
  renderAuth("Sending your code…");
  try {
    const response = await apiRequest("/api/auth/otp/request", { method: "POST", body: { email } });
    pendingCodeEmail = normalizeEmail(response.email || email);
    authBusy = false;
    renderAuth();
    elements.codeInput.value = "";
    elements.codeInput.focus();
  } catch (error) {
    authBusy = false;
    renderAuth(error?.payload?.error === "not_registered"
      ? "That email has no account here."
      : formatApiErrorMessage(error, "We couldn’t send the code. Please try again."));
  }
}

async function verifyCode() {
  const code = String(elements.codeInput.value || "").replace(/\D/g, "");
  if (code.length !== 6) {
    renderAuth("Enter the 6-digit code from the email.");
    elements.codeInput.focus();
    return;
  }

  authBusy = true;
  renderAuth("Checking the code…");
  try {
    await apiRequest("/api/auth/otp/verify", { method: "POST", body: { email: pendingCodeEmail, code } });
    authBusy = false;
    pendingCodeEmail = "";
    await loadSession();
  } catch (error) {
    authBusy = false;
    const reason = error?.payload?.error;
    if (reason === "expired" || reason === "missing_challenge" || reason === "too_many_attempts") {
      pendingCodeEmail = "";
    }
    renderAuth(formatApiErrorMessage(error, "That code is not correct."));
    (pendingCodeEmail ? elements.codeInput : elements.emailInput).focus();
  }
}

function resetAdminState() {
  state.adminUsers = [];
  state.adminSpendTotals = null;
  state.adminView = "list";
  state.adminSelectedUserEmail = "";
  state.adminUserSearch = "";
  state.opportunities = [];
  state.opportunitiesLoadedAt = 0;
  state.featureSwitches = null;
  state.agentTurns = null;
  state.agentTurnsLoadedAt = 0;
}

async function loadSession() {
  try {
    const response = await apiRequest("/api/auth/session");
    session = {
      email: normalizeEmail(response.email),
      canManageClients: Boolean(response.canManageClients),
      canReviewOpportunities: Boolean(response.canReviewOpportunities),
    };
  } catch {
    session = null;
  }

  if (!session?.email) {
    setView("auth");
    renderAuth();
    elements.emailInput.focus();
    return;
  }

  if (!allowedTabs().length) {
    elements.deniedEmail.textContent = session.email;
    setView("denied");
    return;
  }

  elements.accountEmail.textContent = session.email;
  resetAdminState();
  setView("admin");
  setActiveTab(tabFromHash() || state.activeTab);
}

async function signOut() {
  try {
    await apiRequest("/api/auth/logout", { method: "POST", body: {} });
  } catch {
    // The page forgets the session either way.
  }
  session = null;
  pendingCodeEmail = "";
  resetAdminState();
  setView("auth");
  renderAuth();
}

// -- Wiring -------------------------------------------------------------------

function bindEvents() {
  elements.authForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (authBusy) {
      return;
    }
    void (pendingCodeEmail ? verifyCode() : requestCode());
  });

  elements.changeEmailButton.addEventListener("click", () => {
    pendingCodeEmail = "";
    renderAuth();
    elements.emailInput.focus();
  });

  elements.signOutButton.addEventListener("click", () => void signOut());
  elements.deniedSignOutButton.addEventListener("click", () => void signOut());

  elements.adminTabs.addEventListener("click", (event) => {
    const button = getEventTargetElement(event)?.closest("[data-tab]");
    if (button) {
      if (button.dataset.tab === "clients") {
        openAdminUsersList();
        return;
      }
      setActiveTab(button.dataset.tab);
    }
  });

  window.addEventListener("hashchange", () => {
    const tab = tabFromHash();
    if (document.body.dataset.view === "admin" && tab && tab !== state.activeTab) {
      setActiveTab(tab, { syncHash: false });
    }
  });

  elements.alertDismissButton.addEventListener("click", () => {
    const action = alertPrimaryAction;
    closeAuthAlert();
    if (action) {
      action();
    }
  });
  elements.alertSecondaryButton.addEventListener("click", closeAuthAlert);
  elements.alertOverlay.addEventListener("click", (event) => {
    if (event.target === elements.alertOverlay) {
      closeAuthAlert();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeAuthAlert();
    }
  });

  elements.opportunitiesRefreshButton.addEventListener("click", () => void refreshOpportunities());
  elements.turnsRefreshButton.addEventListener("click", () => void refreshAgentTurns());
  elements.featureSwitchesRefreshButton.addEventListener("click", () => void refreshFeatureSwitches());

  elements.featureSwitchesContent.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.dataset.featureSwitch) {
      void saveFeatureSwitch(target.dataset.featureSwitch, target.checked);
    }
  });

  bindClientsEvents();
}

function bindClientsEvents() {
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

    if (target.dataset.adminTrialUser) {
      // The trial length is saved on change, not per keystroke, and a
      // re-render here would swap out the field mid-edit.
      return;
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

    if (target instanceof HTMLInputElement && target.dataset.adminTrialUser) {
      void saveAdminUserTrial(target.dataset.adminTrialUser || "", target.value);
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

    if (event.key !== "Enter") {
      return;
    }

    if (target.dataset.adminNewEmail === "true" || target.dataset.adminNewDisplayName === "true") {
      event.preventDefault();
      void addAdminUser();
    }
  });
}

bindEvents();
setView("loading");
void loadSession();
