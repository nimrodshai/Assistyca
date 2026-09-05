// The registration page: a name, a phone, what they do, one request, and a
// message on WhatsApp. The phone is structured rather than typed free: a
// country picked from a list, a national number typed as they would dial it,
// and the full international number assembled here and shown back before it
// is sent. The server records the registration and sends the first message;
// the account itself opens in the chat, once they give an email there.
window.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-register-form]");
  const done = document.querySelector("[data-register-done]");
  if (!form || !done) {
    return;
  }

  // Dial code and how many digits a national number has (without the trunk
  // zero). Enough to catch a missing digit or a pasted landline; the server
  // checks the international length again.
  const COUNTRIES = [
    ["IL", "Israel", "972", 9, 9],
    ["US", "United States", "1", 10, 10],
    ["CA", "Canada", "1", 10, 10],
    ["GB", "United Kingdom", "44", 10, 10],
    ["IE", "Ireland", "353", 9, 9],
    ["DE", "Germany", "49", 10, 11],
    ["FR", "France", "33", 9, 9],
    ["ES", "Spain", "34", 9, 9],
    ["PT", "Portugal", "351", 9, 9],
    ["IT", "Italy", "39", 9, 10],
    ["NL", "Netherlands", "31", 9, 9],
    ["BE", "Belgium", "32", 8, 9],
    ["CH", "Switzerland", "41", 9, 9],
    ["AT", "Austria", "43", 10, 13],
    ["SE", "Sweden", "46", 9, 9],
    ["NO", "Norway", "47", 8, 8],
    ["DK", "Denmark", "45", 8, 8],
    ["FI", "Finland", "358", 9, 10],
    ["PL", "Poland", "48", 9, 9],
    ["CZ", "Czechia", "420", 9, 9],
    ["HU", "Hungary", "36", 9, 9],
    ["RO", "Romania", "40", 9, 9],
    ["GR", "Greece", "30", 10, 10],
    ["CY", "Cyprus", "357", 8, 8],
    ["TR", "Türkiye", "90", 10, 10],
    ["UA", "Ukraine", "380", 9, 9],
    ["GE", "Georgia", "995", 9, 9],
    ["AE", "United Arab Emirates", "971", 9, 9],
    ["SA", "Saudi Arabia", "966", 9, 9],
    ["IN", "India", "91", 10, 10],
    ["SG", "Singapore", "65", 8, 8],
    ["HK", "Hong Kong", "852", 8, 8],
    ["TH", "Thailand", "66", 9, 9],
    ["PH", "Philippines", "63", 10, 10],
    ["JP", "Japan", "81", 10, 10],
    ["KR", "South Korea", "82", 9, 10],
    ["AU", "Australia", "61", 9, 9],
    ["NZ", "New Zealand", "64", 8, 10],
    ["ZA", "South Africa", "27", 9, 9],
    ["BR", "Brazil", "55", 10, 11],
    ["AR", "Argentina", "54", 10, 10],
    ["MX", "Mexico", "52", 10, 10],
  ];
  // Countries whose people dial a leading zero at home; it is dropped
  // internationally. North America has no trunk zero to drop.
  const NO_TRUNK_ZERO = new Set(["US", "CA"]);

  const flag = (iso) => String.fromCodePoint(...[...iso].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
  const byIso = new Map(COUNTRIES.map((row) => [row[0], row]));

  const guessCountry = () => {
    const candidates = [];
    try {
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      if (zone === "Asia/Jerusalem" || zone === "Asia/Tel_Aviv") {
        candidates.push("IL");
      }
    } catch (error) {
      // No timezone available; fall through to the language.
    }
    (navigator.languages || [navigator.language || ""]).forEach((tag) => {
      const region = String(tag || "").split("-")[1];
      if (region) {
        candidates.push(region.toUpperCase());
      }
    });
    return candidates.find((iso) => byIso.has(iso)) || "IL";
  };

  const countrySelect = form.querySelector("[data-phone-country]");
  const nationalInput = form.querySelector("[data-phone-national]");
  const dialLabel = form.querySelector("[data-phone-dial]");
  const preview = form.querySelector("[data-phone-preview]");
  const submitButton = form.querySelector("[data-register-submit]");
  const status = form.querySelector("[data-register-status]");
  const doneTitle = done.querySelector("[data-done-title]");
  const doneText = done.querySelector("[data-done-text]");
  const doneLink = done.querySelector("[data-done-link]");

  // Alphabetical by name, so a country is found where the eye expects it.
  [...COUNTRIES].sort((a, b) => a[1].localeCompare(b[1], "en")).forEach(([iso, name, dial]) => {
    const option = document.createElement("option");
    option.value = iso;
    option.textContent = `${flag(iso)} ${name} (+${dial})`;
    countrySelect.append(option);
  });
  countrySelect.value = guessCountry();

  const currentCountry = () => byIso.get(countrySelect.value) || byIso.get("IL");

  // The digits they typed, with the trunk zero gone: 050-732-2341 becomes
  // 507322341, which after +972 is the number WhatsApp knows.
  const nationalDigits = () => {
    const [iso] = currentCountry();
    let digits = String(nationalInput.value || "").replace(/\D+/g, "");
    if (!NO_TRUNK_ZERO.has(iso) && digits.startsWith("0")) {
      digits = digits.replace(/^0+/, "");
    }
    return digits;
  };

  const groupDigits = (digits) => {
    if (digits.length === 9) {
      return `${digits.slice(0, 2)}-${digits.slice(2, 5)}-${digits.slice(5)}`;
    }
    if (digits.length === 10) {
      return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
    }
    if (digits.length === 8) {
      return `${digits.slice(0, 4)}-${digits.slice(4)}`;
    }
    return digits;
  };

  const internationalNumber = () => {
    const [, , dial] = currentCountry();
    const digits = nationalDigits();
    return digits ? `+${dial}${digits}` : "";
  };

  const displayNumber = () => {
    const [, , dial] = currentCountry();
    const digits = nationalDigits();
    return digits ? `+${dial} ${groupDigits(digits)}` : "";
  };

  const phoneProblem = () => {
    const [, name, , min, max] = currentCountry();
    const digits = nationalDigits();
    if (!digits) {
      return "Enter the WhatsApp number you will text from.";
    }
    if (digits.length < min || digits.length > max) {
      const expected = min === max ? `${min} digits` : `${min} to ${max} digits`;
      return `A number in ${name} has ${expected} after the country code. This one has ${digits.length}.`;
    }
    return "";
  };

  const syncPhone = () => {
    const [, , dial] = currentCountry();
    dialLabel.textContent = `+${dial}`;
    nationalInput.parentElement.style.setProperty("--dial-width", `${1.3 + dial.length * 0.62 + 0.5}rem`);
    preview.textContent = displayNumber() ? `I'll text ${displayNumber()}` : "";
  };

  countrySelect.addEventListener("change", syncPhone);
  nationalInput.addEventListener("input", () => {
    // Digits only, but keep it readable while they type.
    const digits = String(nationalInput.value || "").replace(/[^\d]/g, "").slice(0, 15);
    nationalInput.value = digits;
    syncPhone();
  });
  syncPhone();

  const setStatus = (text, tone) => {
    status.textContent = "";
    status.removeAttribute("data-tone");
    if (!text) {
      return;
    }
    status.textContent = text;
    if (tone) {
      status.setAttribute("data-tone", tone);
    }
  };

  const setStatusWithSignIn = (text, href) => {
    setStatus(text, "error");
    const link = document.createElement("a");
    link.href = href;
    link.textContent = "Sign in";
    status.append(" ", link, ".");
  };

  const clearFieldErrors = () => {
    form.querySelectorAll("[data-field]").forEach((field) => {
      field.removeAttribute("data-invalid");
      const error = field.querySelector(".field-error");
      if (error) {
        error.textContent = "";
      }
    });
  };

  const showFieldErrors = (errors) => {
    let first = null;
    Object.entries(errors || {}).forEach(([name, message]) => {
      const field = form.querySelector(`[data-field="${name}"]`);
      if (!field) {
        return;
      }
      field.setAttribute("data-invalid", "true");
      const error = field.querySelector(".field-error");
      if (error) {
        error.textContent = String(message || "");
      }
      if (!first) {
        first = field.querySelector("input, select");
      }
    });
    if (first) {
      first.focus();
    }
  };

  const validateLocally = (values) => {
    const errors = {};
    if (values.name.length < 2) {
      errors.name = "Enter your full name.";
    } else if (values.name.split(/\s+/).length < 2) {
      errors.name = "Enter your first and last name.";
    }
    const phoneError = phoneProblem();
    if (phoneError) {
      errors.phone = phoneError;
    }
    if (values.business.length < 2) {
      errors.business = "Tell me what you do, in a few words.";
    }
    return errors;
  };

  const showDone = (payload, shownNumber) => {
    form.hidden = true;
    done.hidden = false;
    const ours = String(payload.assistycaNumber || "").trim();
    doneText.textContent = "";
    if (payload.whatsappSent) {
      doneTitle.textContent = "Check WhatsApp";
      const number = document.createElement("span");
      number.className = "number";
      number.textContent = shownNumber;
      doneText.append("I've just sent a message to ", number, ours ? ` from +${ours}. ` : ". ", "Reply to it and we'll get started.");
    } else {
      doneTitle.textContent = "Almost there";
      doneText.textContent = payload.whatsappLink
        ? "I couldn't reach your phone just now. Open WhatsApp with the button below, say hi, and we'll get started."
        : "I couldn't reach your phone just now. Please try again in a little while.";
    }
    if (payload.whatsappLink) {
      doneLink.href = payload.whatsappLink;
      doneLink.hidden = false;
      doneLink.textContent = payload.whatsappSent ? "Didn't get it? Open WhatsApp" : "Open WhatsApp";
      if (payload.whatsappSent) {
        doneLink.classList.remove("button-primary");
        doneLink.classList.add("button-secondary");
      }
    }
    done.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors();
    setStatus("");

    const data = new FormData(form);
    const values = {
      name: String(data.get("name") || "").trim(),
      phone: internationalNumber(),
      country: countrySelect.value,
      business: String(data.get("business") || "").trim(),
      companyWebsite: String(data.get("companyWebsite") || "").trim(),
    };

    const localErrors = validateLocally(values);
    if (Object.keys(localErrors).length) {
      showFieldErrors(localErrors);
      setStatus("Please fix the highlighted fields first.", "error");
      return;
    }

    const shownNumber = displayNumber();
    submitButton.disabled = true;
    setStatus("Setting things up…");
    try {
      const response = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(values),
      });
      let payload = {};
      try {
        payload = await response.json();
      } catch (error) {
        payload = {};
      }

      if (response.ok && payload.ok) {
        setStatus("");
        showDone(payload, shownNumber);
        return;
      }

      if (payload.fieldErrors) {
        showFieldErrors(payload.fieldErrors);
      }
      const message = String(payload.message || "Something went wrong. Please try again in a moment.");
      if (payload.signInUrl) {
        setStatusWithSignIn(message, payload.signInUrl);
      } else {
        setStatus(message, "error");
      }
    } catch (error) {
      setStatus("I couldn't reach the server. Check your connection and try again.", "error");
    } finally {
      submitButton.disabled = false;
    }
  });
});
