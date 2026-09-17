// What the owner's week page and the shared one both draw: a day's
// activities, with who takes and who collects, and what nobody is down for.
(() => {
  const DAYS = [
    ["sun", "Sunday"],
    ["mon", "Monday"],
    ["tue", "Tuesday"],
    ["wed", "Wednesday"],
    ["thu", "Thursday"],
    ["fri", "Friday"],
    ["sat", "Saturday"],
  ];
  const SELF_WORDS = new Set(["me", "myself", "i", "owner", "אני"]);

  function isSelf(who, ownerName) {
    const text = String(who || "").trim().toLowerCase();
    if (!text) return false;
    if (SELF_WORDS.has(text)) return true;
    const owner = String(ownerName || "").trim().toLowerCase();
    return Boolean(owner) && (text === owner || text === owner.split(" ")[0]);
  }

  function todayCode() {
    return DAYS[new Date().getDay()][0];
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // "me" reads as "You" to the owner and as their first name to anyone
  // else holding the link.
  function rideLabel(who, ownerName, selfLabel) {
    if (isSelf(who, ownerName)) return selfLabel;
    return String(who || "").trim();
  }

  function renderActivity(activity, { ownerName, selfLabel, onOpen }) {
    const node = onOpen ? el("button", "activity") : el("div", "activity");
    if (onOpen) {
      node.type = "button";
      node.addEventListener("click", () => onOpen(activity));
    }
    const time = el("div", "activity-time", activity.startTime || "Any time");
    if (activity.endTime) time.append(el("small", "", `until ${activity.endTime}`));
    node.append(time);
    node.append(el("div", "activity-title", activity.title));
    const meta = [(activity.who || []).join(", "), activity.place].filter(Boolean).join(" · ");
    if (meta) node.append(el("div", "activity-meta", meta));
    const rides = el("div", "activity-rides");
    const takes = rideLabel(activity.dropOffBy, ownerName, selfLabel);
    const collects = rideLabel(activity.pickUpBy, ownerName, selfLabel);
    rides.append(el("span", `ride${takes ? "" : " is-gap"}`, takes ? `Takes: ${takes}` : "Nobody takes them yet"));
    rides.append(el("span", `ride${collects ? "" : " is-gap"}`, collects ? `Collects: ${collects}` : "Nobody collects them yet"));
    node.append(rides);
    return node;
  }

  function renderDays(container, activities, options) {
    const today = todayCode();
    const sections = DAYS.map(([code, name]) => {
      const items = activities.filter((activity) => (activity.days || []).includes(code));
      const section = el("section", `day${code === today ? " is-today" : ""}`);
      section.id = `day-${code}`;
      const head = el("div", "day-head");
      head.append(el("h2", "day-name", name));
      if (code === today) head.append(el("span", "today-mark", "Today"));
      section.append(head);
      if (!items.length) {
        section.append(el("p", "day-empty", "Nothing on"));
      }
      for (const activity of items) {
        section.append(renderActivity(activity, options));
      }
      return section;
    });
    container.replaceChildren(...sections);
  }

  function countGaps(activities) {
    let gaps = 0;
    for (const activity of activities) {
      const days = (activity.days || []).length;
      if (!String(activity.dropOffBy || "").trim()) gaps += days;
      if (!String(activity.pickUpBy || "").trim()) gaps += days;
    }
    return gaps;
  }

  window.AssistycaWeek = { DAYS, countGaps, el, isSelf, renderDays, todayCode };
})();
