// The read-only week a shared link opens. The token is the rest of the
// address after /w/; nothing here needs a sign-in.
(() => {
  const { countGaps, renderDays, todayCode } = window.AssistycaWeek;
  const $ = (id) => document.getElementById(id);
  const token = decodeURIComponent(window.location.pathname.replace(/^\/w\//, "")).replace(/\/+$/, "");

  function show(name) {
    for (const id of ["loadingView", "missingView", "weekView"]) {
      $(id).classList.toggle("is-hidden", id !== name);
    }
    document.body.dataset.view = name;
  }

  async function load() {
    if (!token) {
      show("missingView");
      return;
    }
    try {
      const response = await fetch(`/api/public/week/${encodeURIComponent(token)}`, { credentials: "omit" });
      if (!response.ok) {
        show("missingView");
        return;
      }
      const data = await response.json();
      const activities = data.activities || [];
      const owner = data.ownerName || "";
      const title = owner ? `${owner}'s family week` : "Our week";
      $("pageTitle").textContent = title;
      document.title = title;
      const gaps = countGaps(activities);
      $("gapsText").textContent = gaps === 1
        ? "One drop-off or pickup this week has nobody down for it yet."
        : `${gaps} drop-offs and pickups this week have nobody down for them yet.`;
      $("gapsCard").classList.toggle("is-hidden", gaps === 0);
      $("emptyWeek").classList.toggle("is-hidden", activities.length > 0);
      renderDays($("days"), activities, { ownerName: owner, selfLabel: owner.split(" ")[0] || "Them", onOpen: null });
      show("weekView");
      const today = document.getElementById(`day-${todayCode()}`);
      if (today && activities.length) {
        today.scrollIntoView({ block: "start" });
      }
    } catch {
      show("missingView");
    }
  }

  void load();
})();
