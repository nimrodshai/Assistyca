// The receipts page: every receipt and invoice a search pulled from the
// mail, kept with its file; the ones Assistyca was not sure about, waiting
// for a yes or a no; the totals for a period; and the export an accountant
// gets. All the arithmetic is done on the server. This page shows it.
(() => {
  const state = {
    receipts: [],
    summary: null,
    unsureTotal: 0,
    range: { from: "", to: "" },
    preset: "3-months",
    filter: "all",
    current: null,
    signedIn: false,
    busy: false,
  };

  const $ = (id) => document.getElementById(id);
  const elements = {
    body: document.body,
    backButton: $("backButton"),
    pageTitle: $("pageTitle"),
    exportButton: $("exportButton"),
    loadingView: $("loadingView"),
    signedOutView: $("signedOutView"),
    homeView: $("homeView"),
    detailView: $("detailView"),
    rangeForm: $("rangeForm"),
    rangePreset: $("rangePreset"),
    rangeFrom: $("rangeFrom"),
    rangeTo: $("rangeTo"),
    unsureBadge: $("unsureBadge"),
    summaryTotals: $("summaryTotals"),
    summaryMeta: $("summaryMeta"),
    unsureSection: $("unsureSection"),
    unsureCards: $("unsureCards"),
    receiptsSection: $("receiptsSection"),
    monthGroups: $("monthGroups"),
    emptyHome: $("emptyHome"),
    rejectedSection: $("rejectedSection"),
    rejectedCount: $("rejectedCount"),
    rejectedCards: $("rejectedCards"),
    addManualButton: $("addManualButton"),
    manualSheet: $("manualSheet"),
    manualForm: $("manualForm"),
    manualVendor: $("manualVendor"),
    manualAmount: $("manualAmount"),
    manualCurrency: $("manualCurrency"),
    manualDate: $("manualDate"),
    manualKind: $("manualKind"),
    manualNotes: $("manualNotes"),
    manualCancel: $("manualCancel"),
    detailKind: $("detailKind"),
    detailStatus: $("detailStatus"),
    detailVendor: $("detailVendor"),
    detailSubject: $("detailSubject"),
    detailAmount: $("detailAmount"),
    detailMeta: $("detailMeta"),
    detailReason: $("detailReason"),
    detailFiles: $("detailFiles"),
    fileList: $("fileList"),
    detailForm: $("detailForm"),
    detailAmountInput: $("detailAmountInput"),
    detailCurrencyInput: $("detailCurrencyInput"),
    detailDateInput: $("detailDateInput"),
    detailKindInput: $("detailKindInput"),
    detailVendorInput: $("detailVendorInput"),
    detailPaidToInput: $("detailPaidToInput"),
    detailNotesInput: $("detailNotesInput"),
    detailSnippetCard: $("detailSnippetCard"),
    detailSnippet: $("detailSnippet"),
    detailConfirmButton: $("detailConfirmButton"),
    detailRejectButton: $("detailRejectButton"),
    detailRestoreButton: $("detailRestoreButton"),
    detailDeleteButton: $("detailDeleteButton"),
    exportSheet: $("exportSheet"),
    exportRangeText: $("exportRangeText"),
    exportXlsx: $("exportXlsx"),
    exportCsv: $("exportCsv"),
    exportPdf: $("exportPdf"),
    exportClose: $("exportClose"),
    toast: $("toast"),
  };

  let toastTimer = null;
  function toast(message) {
    elements.toast.textContent = message;
    elements.toast.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => elements.toast.classList.remove("is-visible"), 2200);
  }

  class ApiError extends Error {
    constructor(status, payload) {
      super((payload && payload.message) || `Request failed (${status})`);
      this.status = status;
      this.payload = payload || {};
    }
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: options.body ? { "Content-Type": "application/json" } : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    if (response.status === 401) {
      state.signedIn = false;
      showView("signedOut");
      throw new ApiError(401, payload);
    }
    if (!response.ok || payload.ok === false) {
      throw new ApiError(response.status, payload);
    }
    return payload;
  }

  function showView(name) {
    elements.loadingView.classList.toggle("is-hidden", name !== "loading");
    elements.signedOutView.classList.toggle("is-hidden", name !== "signedOut");
    elements.homeView.classList.toggle("is-hidden", name !== "home");
    elements.detailView.classList.toggle("is-hidden", name !== "detail");
    elements.backButton.classList.toggle("is-hidden", name !== "detail");
    elements.exportButton.classList.toggle("is-hidden", name !== "home");
    elements.body.dataset.view = name;
    if (name !== "detail") {
      elements.pageTitle.textContent = "Receipts";
    }
  }

  function currentRoute() {
    const match = window.location.hash.match(/^#\/receipt\/(\d+)/);
    return match ? { receiptId: Number(match[1]) } : { receiptId: 0 };
  }

  // -- dates and money -------------------------------------------------

  function isoDate(value) {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function presetRange(preset) {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const endOfMonth = (y, m) => new Date(y, m + 1, 0);
    switch (preset) {
      case "month":
        return { from: isoDate(new Date(year, month, 1)), to: isoDate(endOfMonth(year, month)) };
      case "last-month":
        return { from: isoDate(new Date(year, month - 1, 1)), to: isoDate(endOfMonth(year, month - 1)) };
      case "3-months":
        return { from: isoDate(new Date(year, month - 2, 1)), to: isoDate(endOfMonth(year, month)) };
      case "quarter": {
        const start = month - (month % 3);
        return { from: isoDate(new Date(year, start, 1)), to: isoDate(endOfMonth(year, start + 2)) };
      }
      case "year":
        return { from: `${year}-01-01`, to: `${year}-12-31` };
      case "last-year":
        return { from: `${year - 1}-01-01`, to: `${year - 1}-12-31` };
      case "custom":
        return { from: elements.rangeFrom.value || "", to: elements.rangeTo.value || "" };
      default:
        return { from: "", to: "" };
    }
  }

  function formatMoney(amount, currency) {
    const number = Number(String(amount || "").replace(/,/g, ""));
    if (!Number.isFinite(number) || amount === "" || amount === null || amount === undefined) return "";
    const text = number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return currency ? `${text} ${currency}` : text;
  }

  function formatTotals(totals) {
    const entries = Object.entries(totals || {});
    if (!entries.length) return "";
    return entries.map(([code, value]) => formatMoney(value, code)).join(" · ");
  }

  function monthLabel(key) {
    if (!key) return "Undated";
    const [year, month] = key.split("-").map(Number);
    return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  }

  function shortDate(value) {
    if (!value) return "";
    const [year, month, day] = value.split("-").map(Number);
    if (!year || !month || !day) return value;
    return new Date(year, month - 1, day).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function longDate(record) {
    if (record.receiptDate) {
      const [year, month, day] = record.receiptDate.split("-").map(Number);
      return new Date(year, month - 1, day).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "long", year: "numeric" });
    }
    return record.mailDate || "No date";
  }

  function kindLabel(kind) {
    return kind === "invoice" ? "Invoice" : "Receipt";
  }

  function vendorLabel(record) {
    return record.paidTo || record.vendor || "Unknown vendor";
  }

  // -- home ----------------------------------------------------------------

  function describeRange() {
    const { from, to } = state.range;
    if (from && to) return `${from} to ${to}`;
    if (from) return `from ${from}`;
    if (to) return `up to ${to}`;
    return "all dates";
  }

  function renderSummary() {
    const summary = state.summary || {};
    const totals = Object.entries(summary.totals || {});
    elements.summaryTotals.replaceChildren();
    if (!totals.length) {
      const empty = document.createElement("p");
      empty.className = "summary-empty";
      empty.textContent = summary.count ? "No amounts read yet. Tap a receipt to set one." : "No receipts in this period.";
      elements.summaryTotals.append(empty);
    }
    for (const [code, value] of totals) {
      const tile = document.createElement("div");
      tile.className = "total";
      const figure = document.createElement("strong");
      figure.textContent = formatMoney(value, "");
      const label = document.createElement("span");
      label.textContent = code;
      tile.append(figure, label);
      elements.summaryTotals.append(tile);
    }
    const byKind = summary.byKind || {};
    const parts = [];
    const count = Number(summary.count || 0);
    parts.push(`${count} ${count === 1 ? "document" : "documents"}`);
    const receipts = Number((byKind.receipt || {}).count || 0);
    const invoices = Number((byKind.invoice || {}).count || 0);
    if (receipts || invoices) parts.push(`${receipts} receipt${receipts === 1 ? "" : "s"}, ${invoices} invoice${invoices === 1 ? "" : "s"}`);
    if (summary.missingAmountCount) parts.push(`${summary.missingAmountCount} without an amount`);
    if (summary.unsureCount) parts.push(`${summary.unsureCount} waiting for a yes or no`);
    elements.summaryMeta.textContent = `${describeRange()} · ${parts.join(" · ")}`;
  }

  function fileLink(record) {
    const files = Array.isArray(record.attachments) ? record.attachments : [];
    if (!files.length) return null;
    const link = document.createElement("a");
    link.className = "file-chip";
    link.href = files[0].url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = files.length === 1 ? "File" : `${files.length} files`;
    link.title = files.map((file) => file.filename).join(", ");
    link.setAttribute("aria-label", `Open ${files[0].filename}`);
    link.addEventListener("click", (event) => event.stopPropagation());
    return link;
  }

  function renderReceiptRow(record) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `receipt-row kind-${record.kind}`;
    const when = document.createElement("span");
    when.className = "receipt-date";
    when.textContent = record.receiptDate ? shortDate(record.receiptDate) : "—";
    const body = document.createElement("span");
    body.className = "receipt-body";
    const name = document.createElement("span");
    name.className = "receipt-vendor";
    name.textContent = vendorLabel(record);
    const subject = document.createElement("span");
    subject.className = "receipt-subject";
    subject.textContent = record.subject || record.notes || "";
    body.append(name, subject);
    const side = document.createElement("span");
    side.className = "receipt-side";
    const amount = document.createElement("span");
    amount.className = `receipt-amount${record.amount ? "" : " is-missing"}`;
    amount.textContent = record.amount ? formatMoney(record.amount, record.currency) : "Set amount";
    const badge = document.createElement("span");
    badge.className = `badge small kind-${record.kind}`;
    badge.textContent = kindLabel(record.kind);
    side.append(amount, badge);
    const file = fileLink(record);
    if (file) side.append(file);
    row.append(when, body, side);
    row.addEventListener("click", () => {
      window.location.hash = `#/receipt/${record.id}`;
    });
    return row;
  }

  function renderMonths(records) {
    const groups = new Map();
    for (const record of records) {
      const key = record.receiptDate ? record.receiptDate.slice(0, 7) : "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(record);
    }
    const keys = [...groups.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : b.localeCompare(a)));
    const monthTotals = new Map((state.summary?.byMonth || []).map((entry) => [entry.month || "", entry]));
    elements.monthGroups.replaceChildren(
      ...keys.map((key) => {
        const section = document.createElement("section");
        section.className = "month";
        const head = document.createElement("h3");
        head.className = "month-title";
        const label = document.createElement("span");
        label.textContent = monthLabel(key);
        const figure = document.createElement("span");
        figure.className = "month-total";
        const entry = monthTotals.get(key);
        figure.textContent = entry ? `${entry.count} · ${formatTotals(entry.totals) || "no amounts"}` : `${groups.get(key).length}`;
        head.append(label, figure);
        const list = document.createElement("div");
        list.className = "rows";
        list.append(...groups.get(key).map(renderReceiptRow));
        section.append(head, list);
        return section;
      }),
    );
  }

  function renderUnsureCard(record) {
    const card = document.createElement("article");
    card.className = "card unsure-card";
    const head = document.createElement("div");
    head.className = "unsure-head";
    const name = document.createElement("strong");
    name.textContent = vendorLabel(record);
    const when = document.createElement("span");
    when.className = "unsure-date";
    when.textContent = record.receiptDate ? shortDate(record.receiptDate) : record.mailDate || "";
    head.append(name, when);
    const subject = document.createElement("p");
    subject.className = "unsure-subject";
    subject.textContent = record.subject || "";
    const reason = document.createElement("p");
    reason.className = "unsure-reason";
    reason.textContent = record.reason ? `Read as ${record.reason}.` : "";
    const facts = document.createElement("p");
    facts.className = "unsure-facts";
    const parts = [];
    if (record.amount) parts.push(formatMoney(record.amount, record.currency));
    const files = Array.isArray(record.attachments) ? record.attachments : [];
    if (files.length) parts.push(files.map((file) => file.filename).join(", "));
    facts.textContent = parts.join(" · ");
    card.append(head, subject);
    if (record.reason) card.append(reason);
    if (parts.length) card.append(facts);
    const file = fileLink(record);
    if (file) {
      file.textContent = files.length === 1 ? `Open ${files[0].filename}` : `Open ${files.length} files`;
      card.append(file);
    }
    const detail = document.createElement("button");
    detail.type = "button";
    detail.className = "text-button";
    detail.textContent = "See the email text";
    detail.addEventListener("click", () => {
      window.location.hash = `#/receipt/${record.id}`;
    });
    const actions = document.createElement("div");
    actions.className = "button-row";
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "button primary";
    yes.textContent = "Yes";
    yes.addEventListener("click", () => startConfirm(card, record));
    const no = document.createElement("button");
    no.type = "button";
    no.className = "button";
    no.textContent = "No";
    no.addEventListener("click", () => void decide(record.id, { status: "rejected" }, "Left out"));
    actions.append(yes, no, detail);
    card.append(actions);
    return card;
  }

  // Yes opens the two things a kept receipt still needs from the person:
  // which kind it is, and the amount when none was read.
  function startConfirm(card, record) {
    if (card.querySelector(".confirm-form")) return;
    const form = document.createElement("form");
    form.className = "confirm-form";
    const kindRow = document.createElement("div");
    kindRow.className = "chip-row";
    for (const kind of ["receipt", "invoice"]) {
      const label = document.createElement("label");
      label.className = "chip";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `kind-${record.id}`;
      input.value = kind;
      input.checked = (record.kind || "receipt") === kind;
      const text = document.createElement("span");
      text.textContent = kindLabel(kind);
      label.append(input, text);
      kindRow.append(label);
    }
    const amountRow = document.createElement("div");
    amountRow.className = "field-row";
    const amount = document.createElement("input");
    amount.type = "text";
    amount.inputMode = "decimal";
    amount.placeholder = "Amount";
    amount.maxLength = 24;
    amount.value = record.amount || "";
    amount.setAttribute("aria-label", "Amount");
    const currency = document.createElement("input");
    currency.type = "text";
    currency.placeholder = "Currency";
    currency.maxLength = 8;
    currency.value = record.currency || "";
    currency.setAttribute("aria-label", "Currency");
    amountRow.append(amount, currency);
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "button primary";
    save.textContent = "Keep it";
    form.append(kindRow, amountRow, save);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const kind = form.querySelector(`input[name="kind-${record.id}"]:checked`)?.value || "receipt";
      const changes = { status: "confirmed", kind };
      const amountValue = amount.value.trim();
      if (amountValue !== (record.amount || "") || currency.value.trim().toUpperCase() !== (record.currency || "")) {
        changes.amount = amountValue;
        changes.currency = currency.value.trim().toUpperCase();
      }
      void decide(record.id, changes, "Kept");
    });
    card.append(form);
    if (!record.amount) amount.focus();
  }

  function renderRejectedCard(record) {
    const card = document.createElement("div");
    card.className = "rejected-row";
    const text = document.createElement("span");
    text.className = "rejected-text";
    text.textContent = `${vendorLabel(record)} · ${record.subject || ""}`;
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "text-button";
    restore.textContent = "It is a receipt";
    restore.addEventListener("click", () => void decide(record.id, { status: "confirmed" }, "Kept"));
    card.append(text, restore);
    return card;
  }

  function visibleReceipts() {
    const confirmed = state.receipts.filter((record) => record.status === "confirmed");
    if (state.filter === "receipt" || state.filter === "invoice") {
      return confirmed.filter((record) => record.kind === state.filter);
    }
    return confirmed;
  }

  function renderHome() {
    renderSummary();
    const unsure = state.receipts.filter((record) => record.status === "unsure");
    const rejected = state.receipts.filter((record) => record.status === "rejected");
    const showingUnsureOnly = state.filter === "unsure";
    elements.unsureSection.classList.toggle("is-hidden", unsure.length === 0);
    elements.unsureCards.replaceChildren(...unsure.map(renderUnsureCard));
    elements.unsureBadge.textContent = String(state.unsureTotal || "");
    elements.unsureBadge.classList.toggle("is-hidden", !state.unsureTotal);
    elements.receiptsSection.classList.toggle("is-hidden", showingUnsureOnly);
    const confirmed = visibleReceipts();
    renderMonths(confirmed);
    elements.emptyHome.classList.toggle("is-hidden", confirmed.length > 0);
    elements.rejectedSection.classList.toggle("is-hidden", rejected.length === 0 || showingUnsureOnly);
    elements.rejectedCount.textContent = String(rejected.length);
    elements.rejectedCards.replaceChildren(...rejected.map(renderRejectedCard));
    if (showingUnsureOnly && !unsure.length) {
      elements.receiptsSection.classList.remove("is-hidden");
      elements.monthGroups.replaceChildren();
      elements.emptyHome.textContent = state.unsureTotal
        ? "Nothing to look at in this period. Widen the period to see the rest."
        : "Nothing waiting for a yes or no.";
      elements.emptyHome.classList.remove("is-hidden");
    } else {
      elements.emptyHome.textContent = 'Nothing here yet. Ask Assistyca in chat: "pull my receipts from last month", and they will show up here with their files.';
    }
    showView("home");
  }

  // -- detail ---------------------------------------------------------------

  function renderDetail() {
    const record = state.current;
    if (!record) return;
    elements.pageTitle.textContent = vendorLabel(record);
    elements.detailKind.textContent = kindLabel(record.kind);
    elements.detailKind.className = `badge kind-${record.kind}`;
    elements.detailStatus.textContent = record.status === "unsure" ? "Needs a look" : record.status === "rejected" ? "Not a receipt" : record.manualAmount ? "Amount set by you" : "";
    elements.detailStatus.classList.toggle("is-hidden", !elements.detailStatus.textContent);
    elements.detailVendor.textContent = vendorLabel(record);
    elements.detailSubject.textContent = record.subject || "";
    elements.detailAmount.textContent = record.amount ? formatMoney(record.amount, record.currency) : "No amount yet";
    elements.detailAmount.classList.toggle("is-missing", !record.amount);
    const meta = [longDate(record)];
    if (record.vendor && record.paidTo && record.vendor !== record.paidTo) meta.push(`sent by ${record.vendor}`);
    if (record.mailbox) meta.push(record.mailbox);
    elements.detailMeta.textContent = meta.join(" · ");
    elements.detailReason.textContent = record.reason ? `Assistyca read this as ${record.reason}.` : "";
    elements.detailReason.classList.toggle("is-hidden", !record.reason);

    const files = Array.isArray(record.attachments) ? record.attachments : [];
    elements.detailFiles.classList.toggle("is-hidden", files.length === 0);
    elements.fileList.replaceChildren(
      ...files.map((file) => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = file.url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = file.filename;
        const size = document.createElement("span");
        size.className = "file-size";
        size.textContent = file.size ? `${Math.max(1, Math.round(file.size / 1024))} KB` : "";
        item.append(link, size);
        return item;
      }),
    );

    elements.detailAmountInput.value = record.amount || "";
    elements.detailCurrencyInput.value = record.currency || "";
    elements.detailDateInput.value = record.receiptDate || "";
    elements.detailKindInput.value = record.kind || "receipt";
    elements.detailVendorInput.value = record.vendor || "";
    elements.detailPaidToInput.value = record.paidTo || "";
    elements.detailNotesInput.value = record.notes || "";

    elements.detailSnippetCard.classList.toggle("is-hidden", !record.snippet);
    elements.detailSnippet.textContent = record.snippet || "";

    elements.detailConfirmButton.classList.toggle("is-hidden", record.status !== "unsure");
    elements.detailRejectButton.classList.toggle("is-hidden", record.status === "rejected");
    elements.detailRestoreButton.classList.toggle("is-hidden", record.status !== "rejected");
    showView("detail");
  }

  // -- loading and changing -----------------------------------------------

  async function withBusy(work, fallbackMessage) {
    if (state.busy) return;
    state.busy = true;
    try {
      await work();
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        toast(error?.message || fallbackMessage || "That didn't work");
      }
    } finally {
      state.busy = false;
    }
  }

  function listQuery() {
    const params = new URLSearchParams();
    if (state.range.from) params.set("from", state.range.from);
    if (state.range.to) params.set("to", state.range.to);
    const text = params.toString();
    return text ? `?${text}` : "";
  }

  async function loadHome() {
    const payload = await api(`/api/receipts${listQuery()}`);
    state.receipts = Array.isArray(payload.receipts) ? payload.receipts : [];
    state.summary = payload.summary || null;
    state.unsureTotal = Number(payload.unsureTotal || 0);
    state.signedIn = true;
    renderHome();
  }

  async function loadDetail(receiptId) {
    const payload = await api(`/api/receipts/${receiptId}`);
    state.current = payload.receipt;
    state.signedIn = true;
    renderDetail();
  }

  async function decide(receiptId, changes, message) {
    await withBusy(async () => {
      await api(`/api/receipts/${receiptId}`, { method: "POST", body: changes });
      toast(message);
      await loadHome();
    }, "That could not be saved");
  }

  async function route() {
    const { receiptId } = currentRoute();
    try {
      if (receiptId > 0) {
        await loadDetail(receiptId);
      } else {
        state.current = null;
        await loadHome();
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        toast("That receipt is not here");
        window.location.hash = "";
        return;
      }
      if (!(error instanceof ApiError && error.status === 401)) {
        toast(error?.message || "The receipts could not be loaded");
      }
    }
  }

  // -- wiring ----------------------------------------------------------------

  function applyPreset() {
    state.preset = elements.rangePreset.value;
    const custom = state.preset === "custom";
    for (const field of elements.rangeForm.querySelectorAll(".range-date")) {
      field.classList.toggle("is-hidden", !custom);
    }
    state.range = presetRange(state.preset);
    try {
      window.localStorage.setItem("assistyca.receipts.preset", state.preset);
    } catch {
      // Remembering the period is a convenience, not a requirement.
    }
  }

  elements.rangePreset.addEventListener("change", () => {
    applyPreset();
    void route();
  });
  for (const input of [elements.rangeFrom, elements.rangeTo]) {
    input.addEventListener("change", () => {
      if (state.preset !== "custom") return;
      state.range = presetRange("custom");
      void route();
    });
  }
  elements.rangeForm.addEventListener("submit", (event) => event.preventDefault());
  elements.rangeForm.addEventListener("change", (event) => {
    if (event.target && event.target.name === "filter") {
      state.filter = event.target.value;
      renderHome();
    }
  });

  elements.backButton.addEventListener("click", () => {
    window.location.hash = "";
  });

  elements.detailForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const record = state.current;
    if (!record) return;
    const changes = {};
    const amount = elements.detailAmountInput.value.trim();
    const currency = elements.detailCurrencyInput.value.trim().toUpperCase();
    if (amount !== (record.amount || "") || currency !== (record.currency || "")) {
      changes.amount = amount;
      changes.currency = currency;
    }
    if (elements.detailDateInput.value !== (record.receiptDate || "")) changes.receiptDate = elements.detailDateInput.value;
    if (elements.detailKindInput.value !== record.kind) changes.kind = elements.detailKindInput.value;
    if (elements.detailVendorInput.value.trim() !== (record.vendor || "")) changes.vendor = elements.detailVendorInput.value.trim();
    if (elements.detailPaidToInput.value.trim() !== (record.paidTo || "")) changes.paidTo = elements.detailPaidToInput.value.trim();
    if (elements.detailNotesInput.value.trim() !== (record.notes || "")) changes.notes = elements.detailNotesInput.value.trim();
    if (!Object.keys(changes).length) {
      toast("Nothing changed");
      return;
    }
    void withBusy(async () => {
      const payload = await api(`/api/receipts/${record.id}`, { method: "POST", body: changes });
      state.current = payload.receipt;
      renderDetail();
      toast("Saved");
    }, "The receipt could not be saved");
  });

  async function setStatus(status, message) {
    const record = state.current;
    if (!record) return;
    await withBusy(async () => {
      const payload = await api(`/api/receipts/${record.id}`, { method: "POST", body: { status } });
      state.current = payload.receipt;
      renderDetail();
      toast(message);
    }, "The receipt could not be changed");
  }

  elements.detailConfirmButton.addEventListener("click", () => void setStatus("confirmed", "Kept"));
  elements.detailRejectButton.addEventListener("click", () => void setStatus("rejected", "Left out of the totals"));
  elements.detailRestoreButton.addEventListener("click", () => void setStatus("confirmed", "Kept"));
  elements.detailDeleteButton.addEventListener("click", () => {
    const record = state.current;
    if (!record) return;
    if (!window.confirm("Delete this receipt from the page? The email stays in your mailbox.")) return;
    void withBusy(async () => {
      await api(`/api/receipts/${record.id}`, { method: "DELETE" });
      toast("Deleted");
      window.location.hash = "";
    }, "The receipt could not be deleted");
  });

  // Sheets fade and slide: `is-hidden` (display none) comes off first, the
  // next frame adds `is-open` so the transition runs, and closing waits for the
  // exit transition before hiding again.
  const SHEET_EXIT_MS = 240;
  function openSheet(sheet) {
    window.clearTimeout(sheet.closeTimer);
    sheet.classList.remove("is-closing");
    sheet.classList.remove("is-hidden");
    void sheet.offsetWidth;
    sheet.classList.add("is-open");
  }
  function closeSheet(sheet) {
    if (sheet.classList.contains("is-hidden")) return;
    sheet.classList.remove("is-open");
    sheet.classList.add("is-closing");
    window.clearTimeout(sheet.closeTimer);
    sheet.closeTimer = window.setTimeout(() => {
      sheet.classList.remove("is-closing");
      sheet.classList.add("is-hidden");
    }, SHEET_EXIT_MS);
  }

  function openManual() {
    elements.manualForm.reset();
    elements.manualDate.value = isoDate(new Date());
    openSheet(elements.manualSheet);
    elements.manualVendor.focus();
  }
  function closeManual() {
    closeSheet(elements.manualSheet);
  }
  elements.addManualButton.addEventListener("click", openManual);
  elements.manualCancel.addEventListener("click", closeManual);
  elements.manualSheet.addEventListener("click", (event) => {
    if (event.target === elements.manualSheet) closeManual();
  });
  elements.manualForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const vendor = elements.manualVendor.value.trim();
    if (!vendor) return;
    void withBusy(async () => {
      await api("/api/receipts", {
        method: "POST",
        body: {
          vendor,
          amount: elements.manualAmount.value.trim(),
          currency: elements.manualCurrency.value.trim().toUpperCase(),
          receiptDate: elements.manualDate.value,
          kind: elements.manualKind.value,
          notes: elements.manualNotes.value.trim(),
        },
      });
      closeManual();
      toast("Added");
      await loadHome();
    }, "The receipt could not be added");
  });

  function openExport() {
    const params = new URLSearchParams();
    if (state.range.from) params.set("from", state.range.from);
    if (state.range.to) params.set("to", state.range.to);
    const base = `/api/receipts/export?${params.toString()}${params.toString() ? "&" : ""}format=`;
    elements.exportXlsx.href = `${base}xlsx`;
    elements.exportCsv.href = `${base}csv`;
    elements.exportPdf.href = `${base}pdf`;
    elements.exportRangeText.textContent = `Period: ${describeRange()}.`;
    openSheet(elements.exportSheet);
  }
  elements.exportButton.addEventListener("click", openExport);
  elements.exportClose.addEventListener("click", () => closeSheet(elements.exportSheet));
  elements.exportSheet.addEventListener("click", (event) => {
    if (event.target === elements.exportSheet) closeSheet(elements.exportSheet);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeSheet(elements.exportSheet);
    closeManual();
  });

  window.addEventListener("hashchange", () => void route());

  try {
    const remembered = window.localStorage.getItem("assistyca.receipts.preset");
    if (remembered && [...elements.rangePreset.options].some((option) => option.value === remembered && remembered !== "custom")) {
      elements.rangePreset.value = remembered;
    }
  } catch {
    // No stored preference; the default period stands.
  }
  applyPreset();
  showView("loading");
  void route();
})();
