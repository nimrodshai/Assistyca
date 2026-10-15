// The page a parent opens from WhatsApp to give the school platform's login
// for the homework check. The code is the rest of the address after
// /homework/; the login goes straight to the server, which keeps it
// encrypted, and is never read back to this page.
(() => {
  const $ = (id) => document.getElementById(id);
  const code = decodeURIComponent(window.location.pathname.replace(/^\/homework\//, "")).replace(/\/+$/, "");
  const hebrew = !/^en\b/i.test(navigator.language || "") || /^he\b/i.test(navigator.language || "");

  const ENGLISH = {
    title: "Homework",
    goneTitle: "This link isn't active any more",
    goneBody: "Ask me for a new one on WhatsApp.",
    intro: "Your school platform's login, so I can check the homework for you every day.",
    platform: "Which platform does the school use?",
    otherPlatform: "What is it called?",
    schoolCode: "School code (Mashov needs it)",
    username: "Username",
    password: "Password",
    safe: "🔒 Kept encrypted, never shown again to anyone, and used only to check the homework. You can remove it any time - just tell me on WhatsApp.",
    save: "Save",
    doneTitle: "Saved 🙂",
    doneBody: "You can close this page and go back to WhatsApp.",
  };
  const ERRORS = {
    he: {
      platform_required: "צריך לבחור מערכת.",
      login_required: "חסרים שם משתמש או סיסמה.",
      too_long: "אחד השדות ארוך מדי.",
      not_kept: "לא הצלחתי לשמור כרגע. אפשר לנסות שוב עוד מעט.",
      other: "משהו השתבש. אפשר לנסות שוב.",
    },
    en: {
      platform_required: "Choose a platform.",
      login_required: "The username or password is missing.",
      too_long: "One of the fields is too long.",
      not_kept: "I couldn't save it just now. Try again in a little while.",
      other: "Something went wrong. Please try again.",
    },
  };
  const language = hebrew ? "he" : "en";

  if (!hebrew) {
    document.documentElement.lang = "en";
    document.documentElement.dir = "ltr";
    for (const element of document.querySelectorAll("[data-text]")) {
      const text = ENGLISH[element.dataset.text];
      if (text) element.textContent = text;
    }
    document.title = ENGLISH.title;
  }

  function show(name) {
    for (const id of ["loadingView", "goneView", "formView", "doneView"]) {
      $(id).classList.toggle("is-hidden", id !== name);
    }
    document.body.dataset.view = name;
  }

  function chosenPlatform() {
    const checked = document.querySelector('input[name="platform"]:checked');
    return checked ? checked.value : "";
  }

  function renderPlatforms(platforms) {
    const holder = $("platforms");
    holder.textContent = "";
    for (const platform of platforms) {
      const label = document.createElement("label");
      label.className = "chip-toggle";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "platform";
      input.value = platform.id;
      const span = document.createElement("span");
      span.textContent = hebrew ? platform.labelHe : platform.label;
      label.append(input, span);
      holder.append(label);
      input.addEventListener("change", () => {
        $("otherField").classList.toggle("is-hidden", chosenPlatform() !== "other");
        $("schoolField").classList.toggle("is-hidden", chosenPlatform() === "google_classroom");
      });
    }
  }

  function showError(key) {
    const box = $("formError");
    box.textContent = ERRORS[language][key] || ERRORS[language].other;
    box.classList.remove("is-hidden");
  }

  async function save(event) {
    event.preventDefault();
    $("formError").classList.add("is-hidden");
    const body = {
      platform: chosenPlatform(),
      otherPlatform: $("otherPlatform").value,
      schoolCode: $("schoolCode").value,
      username: $("username").value,
      password: $("password").value,
    };
    if (!body.platform || (body.platform === "other" && !body.otherPlatform.trim())) {
      showError("platform_required");
      return;
    }
    if (!body.username.trim() || !body.password.trim()) {
      showError("login_required");
      return;
    }
    $("saveButton").disabled = true;
    try {
      const response = await fetch(`/api/public/homework/${encodeURIComponent(code)}`, {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.ok) {
        $("password").value = "";
        show("doneView");
        return;
      }
      if (response.status === 410) {
        show("goneView");
        return;
      }
      showError(data.error);
    } catch {
      showError("other");
    } finally {
      $("saveButton").disabled = false;
    }
  }

  async function load() {
    if (!code) {
      show("goneView");
      return;
    }
    try {
      const response = await fetch(`/api/public/homework/${encodeURIComponent(code)}`, { credentials: "omit" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status !== "live") {
        show("goneView");
        return;
      }
      renderPlatforms(data.platforms || []);
      $("loginForm").addEventListener("submit", save);
      show("formView");
    } catch {
      show("goneView");
    }
  }

  void load();
})();
