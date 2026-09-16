// Marks the section being read in the "On this page" list.
(() => {
  const links = [...document.querySelectorAll(".toc a")];
  const byId = new Map(links.map((link) => [link.hash.slice(1), link]));
  const sections = [...byId.keys()].map((id) => document.getElementById(id)).filter(Boolean);
  if (!sections.length) return;

  const mark = () => {
    const line = window.innerHeight * 0.3;
    let current = sections[0];
    for (const section of sections) {
      if (section.getBoundingClientRect().top <= line) current = section;
    }
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
      current = sections[sections.length - 1];
    }
    links.forEach((link) => link.removeAttribute("aria-current"));
    byId.get(current.id).setAttribute("aria-current", "true");
  };

  let queued = false;
  window.addEventListener("scroll", () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      mark();
    });
  }, { passive: true });
  window.addEventListener("resize", mark);
  mark();
})();
