// The lists page: every list the account keeps, one list with its items,
// and the share link for other apps. Same store the agent writes to.
(() => {
  const state = {
    lists: [],
    archived: [],
    current: null,
    signedIn: false,
    busy: false,
  };

  const $ = (id) => document.getElementById(id);
  const elements = {
    body: document.body,
    backButton: $("backButton"),
    pageTitle: $("pageTitle"),
    loadingView: $("loadingView"),
    signedOutView: $("signedOutView"),
    signedOutText: $("signedOutText"),
    homeView: $("homeView"),
    listView: $("listView"),
    createForm: $("createForm"),
    createName: $("createName"),
    listCards: $("listCards"),
    emptyHome: $("emptyHome"),
    archivedSection: $("archivedSection"),
    archivedCards: $("archivedCards"),
    listName: $("listName"),
    renameButton: $("renameButton"),
    renameForm: $("renameForm"),
    renameInput: $("renameInput"),
    renameCancel: $("renameCancel"),
    listKind: $("listKind"),
    listCounts: $("listCounts"),
    items: $("items"),
    emptyList: $("emptyList"),
    addForm: $("addForm"),
    addInput: $("addInput"),
    clearDoneButton: $("clearDoneButton"),
    shareToggleButton: $("shareToggleButton"),
    archiveButton: $("archiveButton"),
    restoreButton: $("restoreButton"),
    deleteButton: $("deleteButton"),
    sharePanel: $("sharePanel"),
    shareUrl: $("shareUrl"),
    copyShareButton: $("copyShareButton"),
    openShareLink: $("openShareLink"),
    copyJsonButton: $("copyJsonButton"),
    copyCsvButton: $("copyCsvButton"),
    shareOffButton: $("shareOffButton"),
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
    elements.listView.classList.toggle("is-hidden", name !== "list");
    elements.backButton.classList.toggle("is-hidden", name !== "list");
    elements.body.dataset.view = name;
    if (name !== "list") {
      elements.pageTitle.textContent = "Lists";
    }
  }

  function currentRoute() {
    const match = window.location.hash.match(/^#\/list\/(\d+)/);
    return match ? { listId: Number(match[1]) } : { listId: 0 };
  }

  function kindLabel(kind) {
    return kind === "todo" ? "To-do" : "List";
  }

  function describeCounts(list) {
    const total = Number(list.itemCount || (list.items || []).length || 0);
    if (list.kind === "todo") {
      const open = Number(list.openCount ?? (list.items || []).filter((item) => !item.done).length);
      if (!total) return "empty";
      return open ? `${open} of ${total} left` : `all ${total} done`;
    }
    return total === 1 ? "1 item" : `${total} items`;
  }

  function renderCard(list) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "list-card";
    const name = document.createElement("span");
    name.className = "list-card-name";
    name.textContent = list.name;
    const meta = document.createElement("span");
    meta.className = "list-card-meta";
    meta.textContent = `${kindLabel(list.kind)} · ${describeCounts(list)}${list.shared ? " · shared" : ""}`;
    const arrow = document.createElement("span");
    arrow.className = "list-card-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "›";
    card.append(name, arrow, meta);
    card.addEventListener("click", () => {
      window.location.hash = `#/list/${list.id}`;
    });
    return card;
  }

  function renderHome() {
    elements.listCards.replaceChildren(...state.lists.map(renderCard));
    elements.emptyHome.classList.toggle("is-hidden", state.lists.length > 0);
    elements.archivedCards.replaceChildren(...state.archived.map(renderCard));
    elements.archivedSection.classList.toggle("is-hidden", state.archived.length === 0);
    showView("home");
  }

  function renderItem(item) {
    const list = state.current;
    const row = document.createElement("li");
    row.className = `item${item.done ? " done" : ""}`;
    row.dataset.itemId = String(item.id);

    if (list.kind === "todo") {
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "item-check";
      check.checked = Boolean(item.done);
      check.setAttribute("aria-label", `Done: ${item.text}`);
      check.addEventListener("change", () => void updateItem(item.id, { done: check.checked }));
      row.append(check);
    } else {
      const bullet = document.createElement("span");
      bullet.className = "item-bullet";
      bullet.setAttribute("aria-hidden", "true");
      row.append(bullet);
    }

    const text = document.createElement("button");
    text.type = "button";
    text.className = "item-text";
    text.textContent = item.text;
    text.title = "Tap to edit";
    text.addEventListener("click", () => startItemEdit(row, item));
    row.append(text);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "item-remove";
    remove.setAttribute("aria-label", `Remove ${item.text}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => void removeItem(item.id));
    row.append(remove);
    return row;
  }

  function startItemEdit(row, item) {
    const text = row.querySelector(".item-text");
    if (!text) return;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "item-edit";
    input.maxLength = 300;
    input.value = item.text;
    let finished = false;
    const finish = async (save) => {
      if (finished) return;
      finished = true;
      const next = input.value.trim();
      if (save && next && next !== item.text) {
        await updateItem(item.id, { text: next });
        return;
      }
      renderList();
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void finish(true);
      } else if (event.key === "Escape") {
        void finish(false);
      }
    });
    input.addEventListener("blur", () => void finish(true));
    text.replaceWith(input);
    input.focus();
    input.select();
  }

  function renderList() {
    const list = state.current;
    if (!list) return;
    elements.pageTitle.textContent = list.name;
    elements.listName.textContent = list.name;
    elements.listKind.textContent = kindLabel(list.kind);
    elements.listCounts.textContent = describeCounts(list) + (list.archived ? " · archived" : "");
    const items = list.items || [];
    elements.items.replaceChildren(...items.map(renderItem));
    elements.emptyList.classList.toggle("is-hidden", items.length > 0);
    elements.clearDoneButton.classList.toggle("is-hidden", !(list.kind === "todo" && items.some((item) => item.done)));
    elements.archiveButton.classList.toggle("is-hidden", Boolean(list.archived));
    elements.restoreButton.classList.toggle("is-hidden", !list.archived);
    elements.addForm.classList.toggle("is-hidden", Boolean(list.archived));
    elements.renameForm.classList.add("is-hidden");
    elements.renameButton.classList.remove("is-hidden");

    const shared = Boolean(list.shared && list.shareUrl);
    elements.sharePanel.classList.toggle("is-hidden", !shared);
    elements.shareToggleButton.classList.toggle("is-hidden", shared);
    if (shared) {
      elements.shareUrl.value = list.shareUrl;
      elements.openShareLink.href = list.shareUrl;
    }
    showView("list");
  }

  async function copyText(value, label) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const scratch = document.createElement("textarea");
        scratch.value = value;
        scratch.setAttribute("readonly", "");
        scratch.style.position = "fixed";
        scratch.style.opacity = "0";
        document.body.append(scratch);
        scratch.select();
        document.execCommand("copy");
        scratch.remove();
      }
      toast(`${label} copied`);
    } catch {
      elements.shareUrl.value = value;
      elements.shareUrl.focus();
      elements.shareUrl.select();
      toast("Select the link and copy it");
    }
  }

  async function loadHome() {
    const payload = await api("/api/lists?archived=1");
    const all = Array.isArray(payload.lists) ? payload.lists : [];
    state.lists = all.filter((list) => !list.archived);
    state.archived = all.filter((list) => list.archived);
    state.signedIn = true;
    renderHome();
  }

  async function loadList(listId) {
    const payload = await api(`/api/lists/${listId}`);
    state.current = payload.list;
    state.signedIn = true;
    renderList();
  }

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

  async function updateItem(itemId, changes) {
    const list = state.current;
    await withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}/items/${itemId}`, { method: "POST", body: changes });
      state.current = payload.list;
      renderList();
    }, "The item could not be changed");
  }

  async function removeItem(itemId) {
    const list = state.current;
    await withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}/items/${itemId}`, { method: "DELETE" });
      state.current = payload.list;
      renderList();
    }, "The item could not be removed");
  }

  async function route() {
    const { listId } = currentRoute();
    try {
      if (listId > 0) {
        await loadList(listId);
      } else {
        state.current = null;
        await loadHome();
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        toast("That list is not here");
        window.location.hash = "";
        return;
      }
      if (!(error instanceof ApiError && error.status === 401)) {
        toast(error?.message || "The lists could not be loaded");
      }
    }
  }

  elements.backButton.addEventListener("click", () => {
    window.location.hash = "";
  });

  elements.createForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = elements.createName.value.trim();
    const kind = elements.createForm.querySelector('input[name="kind"]:checked')?.value || "general";
    if (!name) return;
    void withBusy(async () => {
      const payload = await api("/api/lists", { method: "POST", body: { name, kind, items: [] } });
      elements.createName.value = "";
      window.location.hash = `#/list/${payload.list.id}`;
    }, "The list could not be created");
  });

  // The phone keyboard's Done key is an Enter: submit the form it sits in,
  // rather than leaving the words in the box.
  for (const input of [elements.addInput, elements.createName]) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        input.form?.requestSubmit();
      }
    });
  }

  elements.addForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = elements.addInput.value.trim();
    const list = state.current;
    if (!text || !list) return;
    void withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}/items`, { method: "POST", body: { items: [text] } });
      elements.addInput.value = "";
      state.current = payload.list;
      renderList();
      if (payload.skipped && payload.skipped.length) {
        toast("Already on the list");
      }
      elements.addInput.focus();
    }, "The item could not be added");
  });

  elements.renameButton.addEventListener("click", () => {
    elements.renameInput.value = state.current?.name || "";
    elements.renameForm.classList.remove("is-hidden");
    elements.renameButton.classList.add("is-hidden");
    elements.renameInput.focus();
    elements.renameInput.select();
  });

  elements.renameCancel.addEventListener("click", () => renderList());

  elements.renameForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = elements.renameInput.value.trim();
    const list = state.current;
    if (!name || !list) return;
    void withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}`, { method: "POST", body: { name } });
      state.current = payload.list;
      renderList();
      toast("Renamed");
    }, "The list could not be renamed");
  });

  elements.clearDoneButton.addEventListener("click", () => {
    const list = state.current;
    if (!list) return;
    void withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}/items/clear-done`, { method: "POST", body: {} });
      state.current = payload.list;
      renderList();
      toast(payload.cleared === 1 ? "1 item cleared" : `${payload.cleared} items cleared`);
    }, "Ticked items could not be cleared");
  });

  async function setShare(enabled) {
    const list = state.current;
    if (!list) return;
    await withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}/share`, { method: "POST", body: { enabled } });
      state.current = payload.list;
      renderList();
      toast(enabled ? "Sharing is on" : "Sharing is off");
    }, "Sharing could not be changed");
  }

  elements.shareToggleButton.addEventListener("click", () => void setShare(true));
  elements.shareOffButton.addEventListener("click", () => void setShare(false));
  elements.copyShareButton.addEventListener("click", () => void copyText(state.current?.shareUrl || "", "Link"));
  elements.copyJsonButton.addEventListener("click", () => void copyText(state.current?.shareJsonUrl || "", "JSON link"));
  elements.copyCsvButton.addEventListener("click", () => void copyText(state.current?.shareCsvUrl || "", "CSV link"));

  async function setArchived(archived) {
    const list = state.current;
    if (!list) return;
    await withBusy(async () => {
      const payload = await api(`/api/lists/${list.id}`, { method: "POST", body: { archived } });
      state.current = payload.list;
      renderList();
      toast(archived ? "Archived" : "Restored");
    }, "The list could not be changed");
  }

  elements.archiveButton.addEventListener("click", () => void setArchived(true));
  elements.restoreButton.addEventListener("click", () => void setArchived(false));

  elements.deleteButton.addEventListener("click", () => {
    const list = state.current;
    if (!list) return;
    if (!window.confirm(`Delete "${list.name}" for good? This cannot be undone.`)) return;
    void withBusy(async () => {
      await api(`/api/lists/${list.id}`, { method: "DELETE" });
      toast("Deleted");
      window.location.hash = "";
    }, "The list could not be deleted");
  });

  window.addEventListener("hashchange", () => void route());

  const params = new URLSearchParams(window.location.search);
  if (params.get("expired") === "1") {
    elements.signedOutText.textContent = "That link has expired or was already used. Sign in to see your lists, or ask Assistyca for a fresh link.";
  }
  showView("loading");
  void route();
})();
