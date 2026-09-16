// The registration page: a name, a phone, a line about them, one request, and
// a message on WhatsApp. They are asked one at a time, the way the assistant
// would ask them: an answered question slides off to the left and the next
// arrives from the right. Who this is for - a business or a family - is asked
// on the landing page and arrives in the address, and it is what the rest of
// the page is written around: the headline, the last question, and the first
// WhatsApp message all follow it. It is only asked here when nobody has.
// The phone is structured rather than typed
// free: a country picked from a list, a national number typed as they would
// dial it, and the full international number assembled here and shown back
// before it is sent. The server records the registration and sends the first
// message; the account itself opens in the chat, once they give an email
// there.
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

  // One question on screen at a time. The panels are stacked on top of each
  // other and slid sideways, so the box has to be told how tall the question
  // in view is; a ResizeObserver keeps that true when an error appears, a
  // font lands, or the window changes width.
  const flow = form.querySelector("[data-flow]");
  const viewport = form.querySelector("[data-viewport]");
  const steps = [...form.querySelectorAll("[data-step]")];
  const dots = [...form.querySelectorAll("[data-progress] li")];
  const backButtons = [...form.querySelectorAll("[data-back]")];
  let current = 0;

  const measure = () => {
    viewport.style.height = `${steps[current].offsetHeight}px`;
    // Older browsers treat the box as scrollable; never let it hold a scroll.
    viewport.scrollTop = 0;
    viewport.scrollLeft = 0;
  };

  const render = (focus) => {
    steps.forEach((step, index) => {
      step.setAttribute("data-state", index === current ? "current" : index < current ? "past" : "next");
      step.setAttribute("aria-hidden", index === current ? "false" : "true");
      // Belt and braces with the CSS visibility: neither the mouse nor Tab
      // should reach a question that has slid off the side.
      step.toggleAttribute("inert", index !== current);
    });
    dots.forEach((dot, index) => {
      dot.setAttribute("data-state", index === current ? "current" : index < current ? "done" : "todo");
    });
    measure();
    if (focus) {
      // The text field, not the country list: the country is already guessed.
      // On a question answered by picking, the card they picked - landing on
      // the first card instead would ring a choice they did not make.
      const control =
        steps[current].querySelector("input:checked") ||
        steps[current].querySelector("input") ||
        steps[current].querySelector("select");
      if (control) {
        control.focus({ preventScroll: true });
      }
    }
  };

  const goTo = (index) => {
    current = Math.min(Math.max(index, 0), steps.length - 1);
    render(true);
  };

  if (window.ResizeObserver) {
    const observer = new ResizeObserver(() => measure());
    steps.forEach((step) => observer.observe(step));
  }

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

  // Tidy the text fields when they leave them: each word of the name with a
  // capital, the business with a capital first letter. The server does the
  // same, so what is stored matches what they saw.
  const capitalizeName = (value) => value
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("-"))
    .join(" ");
  const capitalizeSentence = (value) => {
    const text = value.trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
  };
  const firstNameInput = form.querySelector('input[name="firstName"]');
  const lastNameInput = form.querySelector('input[name="lastName"]');
  const businessInput = form.querySelector('input[name="business"]');
  // Two fields, one answer: what the server is told is still a single name.
  const fullName = () => [capitalizeName(firstNameInput.value), capitalizeName(lastNameInput.value)]
    .filter(Boolean)
    .join(" ");
  [firstNameInput, lastNameInput].forEach((input) => {
    input.addEventListener("blur", () => {
      input.value = capitalizeName(input.value);
    });
  });
  businessInput.addEventListener("blur", () => {
    businessInput.value = capitalizeSentence(businessInput.value);
  });

  // Everything the choice rewrites. The page is the same four questions
  // either way; only the words change, so a family is never asked what its
  // business is and a business is never asked who drives on Tuesdays.
  const KINDS = {
    business: {
      heroWord: "your business",
      question: "And what do you do?",
      hint: 'A line is enough, for example "I run a small architecture studio".',
      autocomplete: "organization-title",
      missing: "Tell me what you do, in a few words.",
    },
    family: {
      heroWord: "your family",
      question: "Tell me about your family.",
      hint: 'A line is enough, for example "Three kids, 6 to 12, football and ballet most afternoons".',
      autocomplete: "off",
      missing: "Tell me about your family, in a few words.",
    },
  };

  const heroWord = document.querySelector("[data-hero-word]");
  const aboutStep = form.querySelector('[data-step="business"]');
  const aboutQuestion = form.querySelector("[data-about-question]");
  const aboutHint = form.querySelector("[data-about-hint]");
  const kindChoices = [...form.querySelectorAll("[data-kind-choice]")];

  const chosenKind = () => {
    const picked = kindChoices.find((choice) => choice.checked);
    return picked && KINDS[picked.value] ? picked.value : "";
  };

  // Written out whenever the choice changes, and once more when they come
  // back and change their mind; the last question is the same field either
  // way, so only its wording is swapped.
  const applyKind = () => {
    const kind = chosenKind();
    const copy = KINDS[kind] || null;
    heroWord.textContent = copy ? copy.heroWord : "you";
    aboutStep.setAttribute("data-kind", kind || "business");
    aboutQuestion.textContent = (copy || KINDS.business).question;
    aboutHint.textContent = (copy || KINDS.business).hint;
    businessInput.setAttribute("autocomplete", (copy || KINDS.business).autocomplete);
    measure();
  };

  kindChoices.forEach((choice) => {
    // This question costs one click: the card is the answer, so a tap picks
    // and moves on in the same motion - even when they came back and picked
    // the same card again, which fires no change at all. The keyboard keeps
    // its own pace: arrowing through the options rewrites the page without
    // jumping off it, and Enter moves on. Arrowing a radio group fires a
    // click too, with no pointer behind it - detail is 0 there and 1 for a
    // hand, which is what tells the two apart.
    choice.addEventListener("change", applyKind);
    choice.addEventListener("click", (event) => {
      applyKind();
      if (event.detail > 0) {
        advance();
      }
    });
  });

  // Who this is for is decided on the landing page, which links here with the
  // answer in the address: /register/family or /register/business. When the
  // address says so, the question is already answered: it is taken out of the
  // flow and the page opens on the name. Someone who came straight to
  // /register - a link passed on by hand, a typed address - is still asked
  // here rather than guessed at. The older ?for= links keep working.
  const requestedKind = (() => {
    try {
      const fromPath = window.location.pathname.replace(/\/+$/, "").match(/^\/register\/([a-z]+)$/i);
      const fromQuery = new URLSearchParams(window.location.search).get("for");
      return String((fromPath && fromPath[1]) || fromQuery || "").trim().toLowerCase();
    } catch (error) {
      return "";
    }
  })();
  const presetChoice = kindChoices.find((choice) => choice.value === requestedKind);
  const kindIndex = steps.findIndex((step) => step.getAttribute("data-step") === "kind");
  if (presetChoice && kindIndex >= 0) {
    presetChoice.checked = true;
    steps.splice(kindIndex, 1)[0].remove();
    const dot = dots.splice(kindIndex, 1)[0];
    if (dot) {
      dot.remove();
    }
  }

  // Back belongs only where there is something behind it. Which question comes
  // first is settled by now, so this is decided once rather than on every slide.
  backButtons.forEach((button) => {
    button.hidden = Boolean(steps[0] && steps[0].contains(button));
  });

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
    measure();
  };

  // An error is only useful where it can be seen: if it belongs to a question
  // that has already slid away, come back to that question first.
  const showFieldErrors = (errors) => {
    let first = null;
    let firstStep = -1;
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
        // A question can hold more than one box; land on the empty one.
        const boxes = Array.from(field.querySelectorAll("input, select"));
        first = boxes.find((box) => !String(box.value || "").trim()) || boxes[0];
        firstStep = steps.findIndex((step) => step.contains(field));
      }
    });
    if (firstStep >= 0 && firstStep !== current) {
      goTo(firstStep);
      return;
    }
    measure();
    if (first) {
      first.focus({ preventScroll: true });
    }
  };

  // What is wrong with one question's answer, if anything. Each question is
  // checked on its own so nobody is told about a field they cannot see.
  // Each question is known by its name rather than by where it sits: the
  // first one is dropped when the landing page has already asked it, and
  // everything after it moves up.
  const stepErrors = (index) => {
    const step = steps[index];
    const name = step ? step.getAttribute("data-step") : "";
    if (name === "kind") {
      return chosenKind() ? {} : { kind: "Pick the one that fits you." };
    }
    if (name === "name") {
      if (capitalizeName(firstNameInput.value).length < 2) {
        return { name: "Enter your first name." };
      }
      if (capitalizeName(lastNameInput.value).length < 2) {
        return { name: "Enter your last name." };
      }
      return {};
    }
    if (name === "phone") {
      const problem = phoneProblem();
      return problem ? { phone: problem } : {};
    }
    if (name === "business") {
      const about = businessInput.value.trim();
      return about.length < 2 ? { business: (KINDS[chosenKind()] || KINDS.business).missing } : {};
    }
    return {};
  };

  const validateLocally = () =>
    steps.reduce((all, _step, index) => Object.assign(all, stepErrors(index)), {});

  // Enter moves on without the field ever losing focus, so tidy it here too.
  const tidyStep = (index) => {
    const step = steps[index];
    const name = step ? step.getAttribute("data-step") : "";
    if (name === "name") {
      firstNameInput.value = capitalizeName(firstNameInput.value);
      lastNameInput.value = capitalizeName(lastNameInput.value);
    }
    if (name === "business") {
      businessInput.value = capitalizeSentence(businessInput.value);
    }
  };

  const advance = () => {
    tidyStep(current);
    clearFieldErrors();
    setStatus("");
    const errors = stepErrors(current);
    if (Object.keys(errors).length) {
      showFieldErrors(errors);
      return;
    }
    if (current < steps.length - 1) {
      goTo(current + 1);
    }
  };

  form.querySelectorAll("[data-next]").forEach((button) => {
    button.addEventListener("click", advance);
  });
  backButtons.forEach((button) => {
    button.addEventListener("click", () => {
      clearFieldErrors();
      setStatus("");
      goTo(current - 1);
    });
  });

  // Enter is how a conversation moves on: to the next question, or on the
  // last one to sending. Asked for outright rather than left to the browser,
  // which only submits on its own when a form looks like an ordinary one.
  steps.forEach((step, index) => {
    step.querySelectorAll("input").forEach((input) => {
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") {
          return;
        }
        event.preventDefault();
        if (index < steps.length - 1) {
          advance();
        } else {
          form.requestSubmit();
        }
      });
    });
  });

  applyKind();
  render(false);
  flow.setAttribute("data-ready", "true");

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
    if (current < steps.length - 1) {
      advance();
      return;
    }
    tidyStep(current);
    clearFieldErrors();
    setStatus("");

    const data = new FormData(form);
    const values = {
      kind: chosenKind() || "business",
      name: fullName(),
      phone: internationalNumber(),
      country: countrySelect.value,
      business: capitalizeSentence(String(data.get("business") || "")),
      companyWebsite: String(data.get("companyWebsite") || "").trim(),
    };

    const localErrors = validateLocally();
    if (Object.keys(localErrors).length) {
      showFieldErrors(localErrors);
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
