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

  // A grown-up's own week - the owner's work hours, the partner's shift -
  // sits in the same week to say when they cannot do a pickup. Nobody takes
  // or collects a grown-up, so those rows have no rides and no gaps.
  function isGrownUp(activity, members, ownerName) {
    const who = (activity.who || []).map((name) => String(name || "").trim()).filter(Boolean);
    if (!who.length) return false;
    const adults = new Set(
      (members || [])
        .filter((member) => member.role !== "child")
        .map((member) => String(member.name || "").trim().toLowerCase()),
    );
    return who.every((name) => isSelf(name, ownerName) || adults.has(name.toLowerCase()));
  }

  // A start and an end read "08:00 / until 13:30". With only an end, the
  // end is the figure and "until" the small word above it; a made-up
  // "Any time" would say more than the family told us. With neither the
  // column stays blank.
  function renderTime(activity) {
    const time = el("div", "activity-time");
    if (activity.startTime) {
      time.append(activity.startTime);
      if (activity.endTime) time.append(el("small", "", `until ${activity.endTime}`));
    } else if (activity.endTime) {
      time.append(el("small", "", "until"));
      time.append(activity.endTime);
    }
    return time;
  }

  function renderActivity(activity, { ownerName, selfLabel, onOpen, members }) {
    const node = onOpen ? el("button", "activity") : el("div", "activity");
    if (onOpen) {
      node.type = "button";
      node.addEventListener("click", () => onOpen(activity));
    }
    node.append(renderTime(activity));
    node.append(el("div", "activity-title", activity.title));
    const who = (activity.who || []).map((name) => rideLabel(name, ownerName, selfLabel)).join(", ");
    const meta = [who, activity.place].filter(Boolean).join(" · ");
    if (meta) node.append(el("div", "activity-meta", meta));
    if (isGrownUp(activity, members, ownerName)) return node;
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

  function countGaps(activities, members, ownerName) {
    let gaps = 0;
    for (const activity of activities) {
      if (isGrownUp(activity, members, ownerName)) continue;
      const days = (activity.days || []).length;
      if (!String(activity.dropOffBy || "").trim()) gaps += days;
      if (!String(activity.pickUpBy || "").trim()) gaps += days;
    }
    return gaps;
  }

  window.AssistycaWeek = { DAYS, countGaps, el, isGrownUp, isSelf, renderDays, todayCode };
})();
