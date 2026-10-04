// The family's week for the account holder: see it, change who drives,
// add or remove an activity, and share a read-only link. Same store the
// assistant writes to.
(() => {
  const { DAYS, countGaps, el, isSelf, renderDays, todayCode } = window.AssistycaWeek;
  const $ = (id) => document.getElementById(id);
  const state = { data: null, editing: null };

  function show(name) {
    for (const id of ["loadingView", "signedOutView", "weekView"]) {
      $(id).classList.toggle("is-hidden", id !== name);
    }
    document.body.dataset.view = name;
  }

  let toastTimer = null;
  function toast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => $("toast").classList.remove("is-visible"), 2200);
  }

  async function api(path, { method = "GET", body } = {}) {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    if (response.status === 401) {
      show("signedOutView");
      throw new Error("signed_out");
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || "That did not work. Try again in a moment.");
    }
    return payload;
  }

  function personLabel(member) {
    const item = el("li", "person");
    item.append(el("span", "", member.name));
    const details = [];
    if (member.role === "partner") details.push("partner");
    if (member.age !== null && member.age !== undefined) details.push(String(member.age));
    if (member.birthday) {
      const [month, day] = member.birthday.slice(-5).split("-").map(Number);
      const label = new Date(2000, month - 1, day).toLocaleDateString(undefined, { day: "numeric", month: "short" });
      details.push(`birthday ${label}`);
    }
    if (member.school) details.push(member.school);
    if (details.length) item.append(el("span", "person-detail", details.join(" · ")));
    return item;
  }

  function render() {
    const data = state.data;
    const activities = data.activities || [];
    const members = data.members || [];
    $("people").replaceChildren(...members.map(personLabel));
    $("peopleCard").classList.toggle("is-hidden", members.length === 0);

    const gaps = countGaps(activities, members, data.ownerName);
    $("gapsText").textContent = gaps === 1
      ? "One drop-off or pickup this week has nobody down for it yet."
      : `${gaps} drop-offs and pickups this week have nobody down for them yet.`;
    $("gapsCard").classList.toggle("is-hidden", gaps === 0);

    $("emptyWeek").classList.toggle("is-hidden", activities.length > 0);
    $("days").classList.toggle("is-hidden", activities.length === 0);
    renderDays($("days"), activities, { ownerName: data.ownerName, selfLabel: "You", onOpen: openEditor, members });

    const share = data.share || {};
    $("shareRow").classList.toggle("is-hidden", !share.enabled);
    $("shareUrl").value = share.url || "";
    $("shareToggleButton").textContent = share.enabled ? "Stop sharing" : "Make a link";
  }

  async function load() {
    try {
      state.data = await api("/api/household");
      render();
      show("weekView");
      const today = document.getElementById(`day-${todayCode()}`);
      if (today && (state.data.activities || []).length) {
        today.scrollIntoView({ block: "start" });
      }
    } catch (error) {
      if (error.message !== "signed_out") {
        show("signedOutView");
      }
    }
  }

  // -- the editor ------------------------------------------------------------

  const dayInputs = DAYS.map(([code, name]) => {
    const label = el("label", "day-toggle");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = code;
    label.append(input, el("span", "", name.slice(0, 3)));
    $("fieldDays").append(label);
    return input;
  });

  // The people in the family, as chips. "Who it is for" offers everyone
  // at home, children first, and takes a name that is not there yet - a
  // friend who comes along. Who drives is a parent: the owner as "me", so
  // it reads "You" on this page and their name on the shared one, or the
  // partner by name. Anything the chat recorded that fits none of these
  // stays as its own chip rather than being lost.
  function ownerFirstName() {
    return String((state.data || {}).ownerName || "").trim().split(" ")[0];
  }

  function household() {
    const members = (state.data || {}).members || [];
    const byRole = (role) => members.filter((member) => member.role === role);
    return { kids: byRole("child"), others: byRole("other"), partners: byRole("partner") };
  }

  function sameName(a, b) {
    return String(a || "").trim().toLowerCase() === String(b || "").trim().toLowerCase();
  }

  function renderChips(container, { name, type, options, selected }) {
    const chips = options.slice();
    for (const value of selected) {
      if (!chips.some((chip) => sameName(chip.value, value))) chips.push({ value, label: value });
    }
    container.replaceChildren();
    for (const chip of chips) {
      addChip(container, { name, type, value: chip.value, label: chip.label, checked: selected.some((value) => sameName(value, chip.value)) });
    }
  }

  function addChip(container, { name, type, value, label, checked }) {
    const wrap = el("label", "chip-toggle");
    const input = document.createElement("input");
    input.type = type;
    input.name = name;
    input.value = value;
    input.checked = Boolean(checked);
    wrap.append(input, el("span", "", label));
    container.append(wrap);
    return input;
  }

  function chipValues(container) {
    return Array.from(container.querySelectorAll("input:checked")).map((input) => input.value);
  }

  function renderWhoChips(selectedNames) {
    const { kids, others, partners } = household();
    const options = [...kids, ...others, ...partners].map((member) => ({ value: member.name, label: member.name }));
    const owner = ownerFirstName();
    if (owner && !options.some((option) => sameName(option.value, owner))) options.push({ value: owner, label: owner });
    renderChips($("fieldWho"), { name: "who", type: "checkbox", options, selected: selectedNames });
  }

  function renderDriverChips(container, name, current) {
    const options = [{ value: "me", label: "Me" }];
    for (const partner of household().partners) options.push({ value: partner.name, label: partner.name });
    const value = String(current || "").trim();
    const selected = !value ? [] : isSelf(value, (state.data || {}).ownerName) ? ["me"] : [value];
    renderChips(container, { name, type: "radio", options, selected });
  }

  // A typed name becomes a chip, ticked; a name already there is ticked instead.
  function takeTypedName() {
    const input = $("fieldWhoOther");
    const name = input.value.replace(/,/g, " ").trim().slice(0, 80);
    input.value = "";
    if (!name) return;
    const existing = Array.from($("fieldWho").querySelectorAll("input")).find((chip) => sameName(chip.value, name));
    if (existing) {
      existing.checked = true;
    } else {
      addChip($("fieldWho"), { name: "who", type: "checkbox", value: name, label: name, checked: true });
    }
    refreshSaveState();
  }

  function timesInOrder() {
    const start = $("fieldStart").value;
    const end = $("fieldEnd").value;
    return !start || !end || end > start;
  }

  // Save waits until the whole thing is there: what, who, a day, both
  // times in order, where, and who takes and collects. A half-filled row
  // is what the chat is for; the page keeps a complete one.
  function refreshSaveState() {
    const complete = Boolean($("fieldTitle").value.trim())
      && chipValues($("fieldWho")).length > 0
      && dayInputs.some((input) => input.checked)
      && Boolean($("fieldStart").value)
      && Boolean($("fieldEnd").value)
      && Boolean($("fieldPlace").value.trim())
      && chipValues($("fieldDropOff")).length === 1
      && chipValues($("fieldPickUp")).length === 1;
    const inOrder = timesInOrder();
    $("saveButton").disabled = !complete || !inOrder;
    $("editorHint").textContent = inOrder ? "" : "Until has to come after From.";
    $("editorHint").classList.toggle("is-hidden", inOrder);
  }

  function openEditor(activity) {
    state.editing = activity || null;
    $("editorTitle").textContent = activity ? "Change this" : "Add to the week";
    $("fieldTitle").value = activity ? activity.title : "";
    renderWhoChips(activity ? activity.who || [] : []);
    $("fieldWhoOther").value = "";
    for (const input of dayInputs) {
      input.checked = activity ? (activity.days || []).includes(input.value) : false;
    }
    $("fieldStart").value = activity ? activity.startTime : "";
    $("fieldEnd").value = activity ? activity.endTime : "";
    $("fieldPlace").value = activity ? activity.place : "";
    renderDriverChips($("fieldDropOff"), "dropOffBy", activity ? activity.dropOffBy : "");
    renderDriverChips($("fieldPickUp"), "pickUpBy", activity ? activity.pickUpBy : "");
    $("deleteButton").classList.toggle("is-hidden", !activity);
    $("editorError").classList.add("is-hidden");
    refreshSaveState();
    $("editor").showModal();
  }

  function closeEditor() {
    $("editor").close();
    state.editing = null;
  }

  function showError(message) {
    $("editorError").textContent = message;
    $("editorError").classList.remove("is-hidden");
  }

  $("editorForm").addEventListener("input", refreshSaveState);
  $("editorForm").addEventListener("change", refreshSaveState);
  $("fieldWhoOther").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      takeTypedName();
    }
  });
  $("fieldWhoOther").addEventListener("blur", takeTypedName);

  $("editorForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    takeTypedName();
    refreshSaveState();
    if ($("saveButton").disabled) return;
    const body = {
      title: $("fieldTitle").value.trim(),
      who: chipValues($("fieldWho")),
      days: dayInputs.filter((input) => input.checked).map((input) => input.value),
      startTime: $("fieldStart").value,
      endTime: $("fieldEnd").value,
      place: $("fieldPlace").value.trim(),
      dropOffBy: chipValues($("fieldDropOff"))[0] || "",
      pickUpBy: chipValues($("fieldPickUp"))[0] || "",
    };
    const path = state.editing ? `/api/household/activities/${state.editing.id}` : "/api/household/activities";
    try {
      state.data = await api(path, { method: "POST", body });
      closeEditor();
      render();
      toast("Saved");
    } catch (error) {
      showError(error.message);
    }
  });

  $("deleteButton").addEventListener("click", async () => {
    if (!state.editing) return;
    try {
      state.data = await api(`/api/household/activities/${state.editing.id}`, { method: "DELETE" });
      closeEditor();
      render();
      toast("Removed from the week");
    } catch (error) {
      showError(error.message);
    }
  });

  $("cancelButton").addEventListener("click", closeEditor);
  $("addButton").addEventListener("click", () => openEditor(null));

  // -- sharing ---------------------------------------------------------------

  $("shareToggleButton").addEventListener("click", async () => {
    const enabled = !(state.data.share || {}).enabled;
    try {
      state.data = await api("/api/household/share", { method: "POST", body: { enabled } });
      render();
      toast(enabled ? "Link made" : "The link no longer works");
    } catch (error) {
      toast(error.message);
    }
  });

  $("copyShareButton").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("shareUrl").value);
      toast("Link copied");
    } catch {
      $("shareUrl").select();
      toast("Select and copy the link");
    }
  });

  void load();
})();
