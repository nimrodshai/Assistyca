// The family's week for the account holder: see it, change who drives,
// add or remove an activity, and share a read-only link. Same store the
// assistant writes to.
(() => {
  const { DAYS, countGaps, el, renderDays, todayCode } = window.AssistycaWeek;
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

    const gaps = countGaps(activities);
    $("gapsText").textContent = gaps === 1
      ? "One drop-off or pickup this week has nobody down for it yet."
      : `${gaps} drop-offs and pickups this week have nobody down for them yet.`;
    $("gapsCard").classList.toggle("is-hidden", gaps === 0);

    $("emptyWeek").classList.toggle("is-hidden", activities.length > 0);
    $("days").classList.toggle("is-hidden", activities.length === 0);
    renderDays($("days"), activities, { ownerName: data.ownerName, selfLabel: "You", onOpen: openEditor });

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

  function openEditor(activity) {
    state.editing = activity || null;
    $("editorTitle").textContent = activity ? "Change this" : "Add to the week";
    $("fieldTitle").value = activity ? activity.title : "";
    $("fieldWho").value = activity ? (activity.who || []).join(", ") : "";
    for (const input of dayInputs) {
      input.checked = activity ? (activity.days || []).includes(input.value) : false;
    }
    $("fieldStart").value = activity ? activity.startTime : "";
    $("fieldEnd").value = activity ? activity.endTime : "";
    $("fieldPlace").value = activity ? activity.place : "";
    $("fieldDropOff").value = activity ? activity.dropOffBy : "";
    $("fieldPickUp").value = activity ? activity.pickUpBy : "";
    $("deleteButton").classList.toggle("is-hidden", !activity);
    $("editorError").classList.add("is-hidden");
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

  $("editorForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const days = dayInputs.filter((input) => input.checked).map((input) => input.value);
    if (!days.length) {
      showError("Pick at least one day.");
      return;
    }
    const body = {
      title: $("fieldTitle").value.trim(),
      who: $("fieldWho").value.split(",").map((name) => name.trim()).filter(Boolean),
      days,
      startTime: $("fieldStart").value,
      endTime: $("fieldEnd").value,
      place: $("fieldPlace").value.trim(),
      dropOffBy: $("fieldDropOff").value.trim(),
      pickUpBy: $("fieldPickUp").value.trim(),
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
