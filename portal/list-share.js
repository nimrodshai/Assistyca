// The public, read-only view of one shared list. The token is the rest of
// the address after /l/; nothing here needs a sign-in.
(() => {
  const $ = (id) => document.getElementById(id);
  const token = decodeURIComponent(window.location.pathname.replace(/^\/l\//, "")).replace(/\/+$/, "");
  const show = (name) => {
    for (const id of ["loadingView", "missingView", "listView"]) {
      $(id).classList.toggle("is-hidden", id !== name);
    }
    document.body.dataset.view = name;
  };

  function renderItem(item, kind) {
    const row = document.createElement("li");
    row.className = `item${item.done ? " done" : ""}`;
    if (kind === "todo") {
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "item-check";
      check.checked = Boolean(item.done);
      check.disabled = true;
      row.append(check);
    } else {
      const bullet = document.createElement("span");
      bullet.className = "item-bullet";
      row.append(bullet);
    }
    const text = document.createElement("span");
    text.className = "item-text";
    text.textContent = item.text;
    row.append(text);
    return row;
  }

  async function load() {
    if (!token) {
      show("missingView");
      return;
    }
    try {
      const response = await fetch(`/api/public/lists/${encodeURIComponent(token)}`, { credentials: "omit" });
      if (!response.ok) {
        show("missingView");
        return;
      }
      const payload = await response.json();
      const list = payload.list || {};
      const items = Array.isArray(list.items) ? list.items : [];
      document.title = `${list.name || "Shared list"} | Assistyca`;
      $("pageTitle").textContent = list.name || "Shared list";
      $("listName").textContent = list.name || "";
      $("listKind").textContent = list.kind === "todo" ? "To-do" : "List";
      const open = items.filter((item) => !item.done).length;
      $("listCounts").textContent = list.kind === "todo"
        ? (items.length ? (open ? `${open} of ${items.length} left` : `all ${items.length} done`) : "empty")
        : (items.length === 1 ? "1 item" : `${items.length} items`);
      $("items").replaceChildren(...items.map((item) => renderItem(item, list.kind)));
      $("emptyList").classList.toggle("is-hidden", items.length > 0);
      $("jsonLink").href = `/api/public/lists/${encodeURIComponent(token)}`;
      $("csvLink").href = `/api/public/lists/${encodeURIComponent(token)}.csv`;
      show("listView");
    } catch {
      show("missingView");
    }
  }

  void load();
})();
