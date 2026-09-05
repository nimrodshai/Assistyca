// The registration page: a few fields, one request, and a message on WhatsApp.
// The server creates the account and sends the first message; this only asks,
// shows what came back, and hands over the tap-to-open link when there is one.
window.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-register-form]");
  const done = document.querySelector("[data-register-done]");
  if (!form || !done) {
    return;
  }

  const submitButton = form.querySelector("[data-register-submit]");
  const status = form.querySelector("[data-register-status]");
  const doneTitle = done.querySelector("[data-done-title]");
  const doneText = done.querySelector("[data-done-text]");
  const doneLink = done.querySelector("[data-done-link]");

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
        first = field.querySelector("input, textarea");
      }
    });
    if (first) {
      first.focus();
    }
  };

  const validateLocally = (values) => {
    const errors = {};
    if (values.name.length < 2) {
      errors.name = "Enter your name.";
    }
    if (!/^\S+@\S+\.\S+$/.test(values.email)) {
      errors.email = "Enter a valid email address.";
    }
    const digits = values.phone.replace(/\D+/g, "");
    if (digits.length < 8 || digits.length > 15) {
      errors.phone = "Enter the WhatsApp number you will text from, with the country code.";
    }
    return errors;
  };

  const showDone = (payload) => {
    form.hidden = true;
    done.hidden = false;
    const number = String(payload.assistycaNumber || "").trim();
    if (payload.whatsappSent) {
      doneTitle.textContent = "Check WhatsApp";
      doneText.textContent = number
        ? `I've just sent you a message from +${number}. Reply to it and we'll get started.`
        : "I've just sent you a message. Reply to it and we'll get started.";
    } else {
      doneTitle.textContent = "Your account is ready";
      doneText.textContent = payload.whatsappLink
        ? "I couldn't reach your phone just now. Open WhatsApp with the button below and send me the code that appears, and we'll get started."
        : "I couldn't reach your phone just now. Sign in to the web portal and get a code from Settings to connect your WhatsApp.";
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
      email: String(data.get("email") || "").trim(),
      phone: String(data.get("phone") || "").trim(),
      business: String(data.get("business") || "").trim(),
      wants: String(data.get("wants") || "").trim(),
      companyWebsite: String(data.get("companyWebsite") || "").trim(),
    };

    const localErrors = validateLocally(values);
    if (Object.keys(localErrors).length) {
      showFieldErrors(localErrors);
      setStatus("Please fix the highlighted fields first.", "error");
      return;
    }

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
        showDone(payload);
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
