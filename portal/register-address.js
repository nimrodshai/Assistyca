// Runs in the head, before the page is drawn. The landing page links here with
// who this is for already in the address - /register/family or
// /register/business - and the page must never show the question it answered,
// not even for the moment before register.js runs. Marking the page here lets
// the stylesheet leave that question out of the very first paint. Plain
// /register carries no answer and still asks. The older ?for= links keep
// working.
(() => {
  try {
    const fromPath = window.location.pathname.replace(/\/+$/, "").match(/^\/register\/([a-z]+)$/i);
    const fromQuery = new URLSearchParams(window.location.search).get("for");
    const kind = String((fromPath && fromPath[1]) || fromQuery || "").trim().toLowerCase();
    if (kind === "business" || kind === "family") {
      document.documentElement.setAttribute("data-kind-known", kind);
    }
  } catch (error) {
    // Without the mark the page simply asks, which is never wrong.
  }
})();
