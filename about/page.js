window.addEventListener("DOMContentLoaded", () => {
  const headerShell = document.querySelector(".site-header-shell");
  const updateHeaderSpace = () => {
    if (!headerShell) {
      return;
    }

    const headerHeight = headerShell.getBoundingClientRect().height;
    document.documentElement.style.setProperty("--header-space", `${headerHeight}px`);
  };

  updateHeaderSpace();
  window.addEventListener("resize", updateHeaderSpace);
  window.addEventListener("load", updateHeaderSpace);

  const hero = document.querySelector(".hero");
  const heroActions = document.querySelector(".hero-actions");
  const heroVisual = document.querySelector(".hero-visual");
  const heroVisualImage = heroVisual ? heroVisual.querySelector("img") : null;
  const heroMobileVisualQuery = window.matchMedia("(max-width: 380px)");
  let heroVisualCollisionFrame = 0;

  const rectanglesOverlap = (first, second, buffer = 0) => (
    first.left < second.right + buffer
    && first.right > second.left - buffer
    && first.top < second.bottom + buffer
    && first.bottom > second.top - buffer
  );

  const syncHeroVisualCollision = () => {
    if (!hero || !heroActions || !heroVisualImage) {
      return;
    }

    if (heroVisualCollisionFrame) {
      window.cancelAnimationFrame(heroVisualCollisionFrame);
    }

    heroVisualCollisionFrame = window.requestAnimationFrame(() => {
      heroVisualCollisionFrame = 0;

      if (!heroMobileVisualQuery.matches) {
        hero.removeAttribute("data-mobile-visual-hidden");
        hero.removeAttribute("data-mobile-visual-measuring");
        return;
      }

      const wasHidden = hero.hasAttribute("data-mobile-visual-hidden");
      if (wasHidden) {
        hero.setAttribute("data-mobile-visual-measuring", "true");
      }
      hero.removeAttribute("data-mobile-visual-hidden");

      const imageRect = heroVisualImage.getBoundingClientRect();
      const actionTargets = Array.from(heroActions.querySelectorAll("a, button"));
      const hasVisibleImage = imageRect.width > 0 && imageRect.height > 0;
      const collidesWithButton = hasVisibleImage && actionTargets.some((target) => {
        const targetRect = target.getBoundingClientRect();
        return targetRect.width > 0
          && targetRect.height > 0
          && rectanglesOverlap(imageRect, targetRect, 8);
      });

      hero.removeAttribute("data-mobile-visual-measuring");
      if (collidesWithButton) {
        hero.setAttribute("data-mobile-visual-hidden", "true");
      }
    });
  };

  syncHeroVisualCollision();
  window.addEventListener("resize", syncHeroVisualCollision);
  window.addEventListener("orientationchange", syncHeroVisualCollision);
  window.addEventListener("load", syncHeroVisualCollision);
  if (typeof heroMobileVisualQuery.addEventListener === "function") {
    heroMobileVisualQuery.addEventListener("change", syncHeroVisualCollision);
  } else if (typeof heroMobileVisualQuery.addListener === "function") {
    heroMobileVisualQuery.addListener(syncHeroVisualCollision);
  }
  if (heroVisualImage && !heroVisualImage.complete) {
    heroVisualImage.addEventListener("load", syncHeroVisualCollision, { once: true });
  }
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(syncHeroVisualCollision).catch(() => {});
  }

  const menuToggle = document.querySelector("[data-nav-toggle]");
  const mobileNav = document.querySelector("#site-navigation");
  const closeMobileNav = () => {
    document.body.classList.remove("mobile-nav-open");
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", "false");
      menuToggle.setAttribute("aria-label", "Open navigation");
    }
  };

  if (menuToggle && mobileNav) {
    menuToggle.addEventListener("click", () => {
      const nextOpen = !document.body.classList.contains("mobile-nav-open");
      document.body.classList.toggle("mobile-nav-open", nextOpen);
      menuToggle.setAttribute("aria-expanded", String(nextOpen));
      menuToggle.setAttribute("aria-label", nextOpen ? "Close navigation" : "Open navigation");
    });

    mobileNav.querySelectorAll("a, button").forEach((item) => {
      item.addEventListener("click", closeMobileNav);
    });

    document.addEventListener("click", (event) => {
      if (
        !document.body.classList.contains("mobile-nav-open") ||
        event.target.closest(".site-header")
      ) {
        return;
      }

      closeMobileNav();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeMobileNav();
      }
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth > 720) {
        closeMobileNav();
      }
    });
  }

  const contactModal = document.querySelector("[data-contact-modal]");
  const contactForm = document.querySelector("[data-contact-form]");
  const contactOpeners = Array.from(document.querySelectorAll("[data-contact-open]"));
  const contactClosers = Array.from(document.querySelectorAll("[data-contact-close]"));
  const contactChatLog = document.querySelector("[data-contact-chat-log]");
  const contactChatStack = document.querySelector("[data-contact-chat-stack]");
  const contactInput = document.querySelector("[data-contact-input]");
  const contactStatus = document.querySelector("[data-contact-status]");
  const contactSubmit = document.querySelector("[data-contact-submit]");
  const contactBack = document.querySelector("[data-contact-back]");
  if (contactModal && contactModal.parentElement !== document.body) {
    document.body.appendChild(contactModal);
  }

  let contactLastFocus = null;
  let contactCloseTimer = 0;
  let contactAnimationTimer = 0;
  const contactAnimationMs = 340;
  const contactMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const contactMobileViewportQuery = window.matchMedia("(max-width: 640px)");
  const contactEmailPattern = /[^\s@<>]+@[^\s@<>]+\.[^\s@<>.,;:]+/;
  const contactPhonePattern = /\+?\d[\d\s().-]{6,}\d/;
  const contactChatBottomTolerance = 28;
  const contactTypingDelayMs = 1520;
  const contactKeyboardOffsetThreshold = 72;
  let contactScrollFrame = 0;
  let contactScrollAnimationFrame = 0;
  let contactScrollAnimating = false;
  let contactInputResizeFrame = 0;
  let contactInputResizeTimer = 0;
  let contactLayoutFrame = 0;
  let contactLayoutPinTimer = 0;
  let contactLayoutViewportHeight = 0;
  let contactPageScrollY = 0;
  let contactPageScrollLocked = false;
  let contactKeyboardFocusTimer = 0;
  let contactKeyboardHoldTimer = 0;
  let contactPreserveKeyboardOnSubmit = false;
  let contactSubmitPointerPreserved = false;
  let contactSubmitPointerSent = false;
  let contactChatTouchStartY = 0;
  let contactAgentAbortController = null;
  let contactAgentRequestId = 0;
  let contactTypingIndicator = null;
  let contactTypingTimer = 0;
  const contactChatState = {
    messages: [],
    intake: {},
    completed: false,
    readyToSubmit: false,
    started: false,
    submitting: false,
    followLatest: true,
  };

  const setContactStatus = (message, tone = "") => {
    if (!contactStatus) {
      return;
    }

    contactStatus.textContent = message;
    if (tone) {
      contactStatus.dataset.tone = tone;
    } else {
      delete contactStatus.dataset.tone;
    }
  };

  const removeContactTypingIndicator = () => {
    window.clearTimeout(contactTypingTimer);
    contactTypingTimer = 0;
    if (!contactTypingIndicator) {
      return;
    }

    contactTypingIndicator.remove();
    contactTypingIndicator = null;
  };

  const showContactTypingIndicator = () => {
    if (!contactChatStack) {
      return;
    }

    removeContactTypingIndicator();
    const shouldFollowLatest = contactChatState.followLatest || contactChatIsNearBottom();
    const row = document.createElement("div");
    row.className = "contact-message";
    row.dataset.author = "agent";
    row.dataset.typing = "true";
    row.setAttribute("role", "status");
    row.setAttribute("aria-label", "הסוכן מקליד");

    const avatar = document.createElement("span");
    avatar.className = "contact-message-avatar";
    avatar.textContent = "A";
    avatar.setAttribute("aria-hidden", "true");
    row.appendChild(avatar);

    const bubble = document.createElement("div");
    bubble.className = "contact-message-bubble";
    bubble.dir = "ltr";
    bubble.setAttribute("aria-hidden", "true");

    const dots = document.createElement("span");
    dots.className = "contact-typing";
    for (let index = 0; index < 3; index += 1) {
      const dot = document.createElement("span");
      dot.className = "contact-typing-dot";
      dots.appendChild(dot);
    }

    bubble.appendChild(dots);
    row.appendChild(bubble);
    contactTypingIndicator = row;
    contactChatStack.appendChild(row);
    syncContactChatScrollable();

    if (shouldFollowLatest) {
      scrollContactChat({ force: true, animated: true });
    }
  };

  const scheduleContactTypingIndicator = (requestId) => {
    window.clearTimeout(contactTypingTimer);
    contactTypingTimer = window.setTimeout(() => {
      if (requestId !== contactAgentRequestId || !contactChatState.submitting) {
        return;
      }

      showContactTypingIndicator();
    }, contactTypingDelayMs);
  };

  const normalizeContactAnswer = (value) => (
    String(value || "").replace(/\s+/g, " ").trim()
  );

  const getContactTime = () => (
    new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit" }).format(new Date())
  );

  const contactChatHasOverflow = () => (
    Boolean(contactChatLog) &&
    contactChatLog.scrollHeight - contactChatLog.clientHeight > 2
  );

  const syncContactChatScrollable = () => {
    if (!contactChatLog) {
      return false;
    }

    const isScrollable = contactChatHasOverflow();
    if (isScrollable) {
      contactChatLog.dataset.scrollable = "true";
    } else {
      delete contactChatLog.dataset.scrollable;
      contactChatLog.scrollTop = 0;
      contactChatState.followLatest = true;
      window.cancelAnimationFrame(contactScrollFrame);
      window.cancelAnimationFrame(contactScrollAnimationFrame);
      contactScrollFrame = 0;
      contactScrollAnimationFrame = 0;
      contactScrollAnimating = false;
    }

    return isScrollable;
  };

  const contactChatIsNearBottom = () => {
    if (!contactChatLog) {
      return true;
    }

    if (!contactChatHasOverflow()) {
      return true;
    }

    return (
      contactChatLog.scrollHeight -
      contactChatLog.scrollTop -
      contactChatLog.clientHeight <=
      contactChatBottomTolerance
    );
  };

  const animateContactChatScroll = (targetTop) => {
    if (!contactChatLog) {
      return;
    }

    window.cancelAnimationFrame(contactScrollAnimationFrame);
    const startTop = contactChatLog.scrollTop;
    const distance = targetTop - startTop;
    if (Math.abs(distance) < 2 || contactMotionQuery.matches) {
      contactChatLog.scrollTop = targetTop;
      contactScrollAnimating = false;
      return;
    }

    const duration = Math.min(360, Math.max(180, Math.abs(distance) * 0.38));
    const startTime = performance.now();
    contactScrollAnimating = true;

    const step = (now) => {
      const progress = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      contactChatLog.scrollTop = startTop + distance * eased;

      if (progress < 1) {
        contactScrollAnimationFrame = window.requestAnimationFrame(step);
        return;
      }

      contactChatLog.scrollTop = targetTop;
      contactScrollAnimationFrame = 0;
      contactScrollAnimating = false;
    };

    contactScrollAnimationFrame = window.requestAnimationFrame(step);
  };

  const scrollContactChat = (options = {}) => {
    if (!contactChatLog) {
      return;
    }

    const force = Boolean(options.force);
    const animated = Boolean(options.animated);
    if (!force && !contactChatState.followLatest && !contactChatIsNearBottom()) {
      return;
    }

    contactChatState.followLatest = true;
    if (!syncContactChatScrollable()) {
      return;
    }

    const targetTop = Math.max(0, contactChatLog.scrollHeight - contactChatLog.clientHeight);
    if (animated) {
      animateContactChatScroll(targetTop);
    } else {
      window.cancelAnimationFrame(contactScrollAnimationFrame);
      contactScrollAnimating = false;
      contactChatLog.scrollTop = targetTop;
    }
    window.cancelAnimationFrame(contactScrollFrame);
    contactScrollFrame = window.requestAnimationFrame(() => {
      if (contactChatState.followLatest || contactChatIsNearBottom()) {
        if (animated) {
          animateContactChatScroll(Math.max(0, contactChatLog.scrollHeight - contactChatLog.clientHeight));
        } else {
          contactChatLog.scrollTop = Math.max(0, contactChatLog.scrollHeight - contactChatLog.clientHeight);
        }
      }
    });
  };

  const lockContactPageScroll = () => {
    if (!contactMobileViewportQuery.matches || contactPageScrollLocked) {
      return;
    }

    contactPageScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    document.body.style.top = `-${Math.round(contactPageScrollY)}px`;
    contactPageScrollLocked = true;
  };

  const unlockContactPageScroll = () => {
    if (!contactPageScrollLocked) {
      return;
    }

    const restoreScrollY = contactPageScrollY;
    contactPageScrollLocked = false;
    contactPageScrollY = 0;
    document.body.style.removeProperty("top");
    window.scrollTo(0, restoreScrollY);
  };

  const shouldKeepContactKeyboardOpen = () => (
    contactMobileViewportQuery.matches &&
    contactInput &&
    !contactInput.disabled &&
    !contactChatState.completed
  );

  const markContactKeyboardHold = () => {
    if (!shouldKeepContactKeyboardOpen()) {
      return false;
    }

    contactPreserveKeyboardOnSubmit = true;
    window.clearTimeout(contactKeyboardHoldTimer);
    contactKeyboardHoldTimer = window.setTimeout(() => {
      if (contactChatState.submitting) {
        return;
      }

      contactPreserveKeyboardOnSubmit = false;
      syncContactInputFocusState();
    }, 900);
    return true;
  };

  const releaseContactKeyboardHoldAfterRefocus = () => {
    window.clearTimeout(contactKeyboardHoldTimer);
    contactKeyboardHoldTimer = window.setTimeout(() => {
      contactPreserveKeyboardOnSubmit = false;
      syncContactInputFocusState();
    }, 520);
  };

  const refocusContactInputForKeyboard = () => {
    if (!shouldKeepContactKeyboardOpen()) {
      return;
    }

    if (contactModal) {
      contactModal.dataset.inputFocused = "true";
    }
    contactInput.focus({ preventScroll: true });
    syncContactViewportMetrics();
    keepContactLayoutPinned();
    window.requestAnimationFrame(keepContactLayoutPinned);
    window.clearTimeout(contactKeyboardFocusTimer);
    contactKeyboardFocusTimer = window.setTimeout(() => {
      if (!shouldKeepContactKeyboardOpen()) {
        return;
      }

      contactInput.focus({ preventScroll: true });
      keepContactLayoutPinned();
    }, 48);
  };

  const dismissContactKeyboard = () => {
    window.clearTimeout(contactKeyboardFocusTimer);
    window.clearTimeout(contactKeyboardHoldTimer);
    contactPreserveKeyboardOnSubmit = false;
    contactSubmitPointerPreserved = false;
    contactSubmitPointerSent = false;

    if (contactInput && document.activeElement === contactInput) {
      contactInput.blur();
    }

    if (contactModal) {
      delete contactModal.dataset.inputFocused;
      delete contactModal.dataset.keyboard;
    }
  };

  const syncContactInputFocusState = () => {
    if (!contactModal) {
      return;
    }

    if (document.activeElement === contactInput || contactPreserveKeyboardOnSubmit) {
      contactModal.dataset.inputFocused = "true";
    } else {
      delete contactModal.dataset.inputFocused;
    }
  };

  const resetContactViewportMetrics = () => {
    contactLayoutViewportHeight = 0;
    window.cancelAnimationFrame(contactScrollAnimationFrame);
    window.cancelAnimationFrame(contactLayoutFrame);
    window.clearTimeout(contactLayoutPinTimer);
    window.clearTimeout(contactKeyboardFocusTimer);
    window.clearTimeout(contactKeyboardHoldTimer);
    contactScrollAnimationFrame = 0;
    contactScrollAnimating = false;
    contactPreserveKeyboardOnSubmit = false;
    contactSubmitPointerPreserved = false;
    contactSubmitPointerSent = false;
    if (contactModal) {
      delete contactModal.dataset.inputFocused;
      delete contactModal.dataset.keyboard;
    }
    document.documentElement.style.removeProperty("--contact-keyboard-offset");
    document.documentElement.style.removeProperty("--contact-mobile-viewport-top");
    document.documentElement.style.removeProperty("--contact-mobile-viewport-height");
    document.documentElement.style.removeProperty("--contact-mobile-visible-height");
  };

  const getContactLayoutViewportHeight = () => {
    const visualViewport = window.visualViewport;
    const visualViewportBottom = visualViewport
      ? visualViewport.height + visualViewport.offsetTop
      : 0;

    return Math.max(
      document.documentElement.clientHeight || 0,
      window.innerHeight || 0,
      visualViewportBottom,
    );
  };

  const getContactVisualKeyboardOffset = (layoutHeight = contactLayoutViewportHeight) => {
    const visualViewport = window.visualViewport;
    if (!visualViewport || !contactMobileViewportQuery.matches || !layoutHeight) {
      return 0;
    }

    const visualViewportBottom = visualViewport.height + visualViewport.offsetTop;
    return Math.max(0, layoutHeight - visualViewportBottom);
  };

  const contactKeyboardAppearsOpen = () => (
    getContactVisualKeyboardOffset(contactLayoutViewportHeight || getContactLayoutViewportHeight()) >
      contactKeyboardOffsetThreshold ||
    contactModal?.dataset.keyboard === "open"
  );

  const syncContactViewportMetrics = (options = {}) => {
    if (!contactModal || contactModal.hidden || !contactMobileViewportQuery.matches) {
      resetContactViewportMetrics();
      return;
    }

    const visualViewport = window.visualViewport;
    const inputFocused =
      document.activeElement === contactInput ||
      contactPreserveKeyboardOnSubmit ||
      contactSubmitPointerPreserved ||
      contactSubmitPointerSent;
    syncContactInputFocusState();
    const nextLayoutHeight = getContactLayoutViewportHeight();
    const previousLayoutHeight = contactLayoutViewportHeight;
    const keyboardGeometryActive =
      getContactVisualKeyboardOffset(previousLayoutHeight) > contactKeyboardOffsetThreshold;
    const shouldUseVisualViewport = inputFocused || keyboardGeometryActive;

    if (options.reset || !previousLayoutHeight) {
      contactLayoutViewportHeight = nextLayoutHeight;
    } else if (shouldUseVisualViewport) {
      contactLayoutViewportHeight = Math.max(previousLayoutHeight, nextLayoutHeight);
    } else {
      contactLayoutViewportHeight = nextLayoutHeight;
    }

    const rawVisibleHeight = visualViewport
      ? visualViewport.height
      : contactLayoutViewportHeight;
    const candidateVisibleHeight = shouldUseVisualViewport && visualViewport
      ? Math.max(320, Math.min(contactLayoutViewportHeight, rawVisibleHeight))
      : contactLayoutViewportHeight;
    const candidateViewportTop = shouldUseVisualViewport && visualViewport
      ? Math.max(0, Math.min(contactLayoutViewportHeight - candidateVisibleHeight, visualViewport.offsetTop))
      : 0;
    const candidateVisibleBottom = shouldUseVisualViewport && visualViewport
      ? candidateViewportTop + candidateVisibleHeight
      : contactLayoutViewportHeight;
    const candidateKeyboardOffset = shouldUseVisualViewport && visualViewport
      ? Math.max(0, contactLayoutViewportHeight - candidateVisibleBottom)
      : 0;
    const keyboardOpen =
      Boolean(visualViewport) &&
      shouldUseVisualViewport &&
      candidateKeyboardOffset > contactKeyboardOffsetThreshold;
    const visibleHeight = keyboardOpen ? candidateVisibleHeight : contactLayoutViewportHeight;
    const viewportTop = keyboardOpen ? candidateViewportTop : 0;
    const keyboardOffset = keyboardOpen ? candidateKeyboardOffset : 0;

    if (contactModal) {
      if (keyboardOpen) {
        contactModal.dataset.keyboard = "open";
      } else {
        delete contactModal.dataset.keyboard;
      }
    }

    document.documentElement.style.setProperty(
      "--contact-mobile-viewport-height",
      `${Math.round(contactLayoutViewportHeight)}px`,
    );
    document.documentElement.style.setProperty(
      "--contact-mobile-viewport-top",
      `${Math.round(viewportTop)}px`,
    );
    document.documentElement.style.setProperty(
      "--contact-mobile-visible-height",
      `${Math.round(visibleHeight)}px`,
    );
    document.documentElement.style.setProperty(
      "--contact-keyboard-offset",
      `${Math.round(keyboardOffset)}px`,
    );
  };

  const populateContactMessageBubble = (bubble, message, options = {}) => {
    bubble.replaceChildren();
    bubble.dir = "auto";
    bubble.removeAttribute("aria-hidden");
    if (options.reveal) {
      bubble.dataset.reveal = "pending";
    } else {
      delete bubble.dataset.reveal;
    }

    const text = document.createElement("p");
    text.textContent = message;
    text.dir = "auto";
    bubble.appendChild(text);

    const time = document.createElement("span");
    time.className = "contact-message-time";
    time.textContent = getContactTime();
    bubble.appendChild(time);
  };

  const measureContactBubbleSize = (row, bubble) => {
    if (!contactChatLog || !contactChatStack) {
      return { width: 0, height: 0 };
    }

    const rowRect = row.getBoundingClientRect();
    const measureRow = document.createElement("div");
    measureRow.className = row.className;
    measureRow.dataset.author = "agent";
    measureRow.style.position = "absolute";
    measureRow.style.visibility = "hidden";
    measureRow.style.pointerEvents = "none";
    measureRow.style.left = "0";
    measureRow.style.top = "0";
    measureRow.style.width = `${Math.ceil(rowRect.width || contactChatLog.clientWidth)}px`;

    const avatar = row.querySelector(".contact-message-avatar");
    if (avatar) {
      measureRow.appendChild(avatar.cloneNode(true));
    }

    const bubbleClone = bubble.cloneNode(true);
    bubbleClone.removeAttribute("style");
    delete bubbleClone.dataset.reveal;
    measureRow.appendChild(bubbleClone);
    contactChatStack.appendChild(measureRow);
    const bubbleRect = bubbleClone.getBoundingClientRect();
    measureRow.remove();

    return {
      width: Math.ceil(bubbleRect.width),
      height: Math.ceil(bubbleRect.height),
    };
  };

  const revealMorphedContactBubble = (bubble) => {
    window.requestAnimationFrame(() => {
      delete bubble.dataset.reveal;
    });
  };

  const cleanupMorphedContactBubble = (row, bubble) => {
    delete row.dataset.morphingReply;
    bubble.style.removeProperty("width");
    bubble.style.removeProperty("height");
    bubble.style.removeProperty("min-width");
    bubble.style.removeProperty("min-height");
    bubble.style.removeProperty("overflow");
    bubble.style.removeProperty("transform");
    bubble.style.removeProperty("transform-origin");
    bubble.style.removeProperty("transition");
    syncContactChatScrollable();
    if (contactChatState.followLatest) {
      scrollContactChat({ force: true });
    }
  };

  const morphContactTypingIndicatorToMessage = (message) => {
    if (!contactTypingIndicator) {
      appendContactMessage("agent", message);
      return;
    }

    const row = contactTypingIndicator;
    const bubble = row.querySelector(".contact-message-bubble");
    if (!bubble) {
      removeContactTypingIndicator();
      appendContactMessage("agent", message);
      return;
    }

    window.clearTimeout(contactTypingTimer);
    contactTypingTimer = 0;
    contactTypingIndicator = null;

    const shouldFollowLatest = contactChatState.followLatest || contactChatIsNearBottom();
    const startRect = bubble.getBoundingClientRect();
    const startWidth = Math.max(1, Math.ceil(startRect.width));
    const startHeight = Math.max(1, Math.ceil(startRect.height));

    row.dataset.morphingReply = "true";
    if (shouldFollowLatest) {
      scrollContactChat({ force: true });
    }

    const finishImmediately = () => {
      delete row.dataset.typing;
      delete row.dataset.morphingReply;
      row.removeAttribute("role");
      row.removeAttribute("aria-label");
      populateContactMessageBubble(bubble, message);
      if (shouldFollowLatest) {
        scrollContactChat({ force: true });
      }
    };

    if (contactMotionQuery.matches) {
      finishImmediately();
      return;
    }

    window.setTimeout(() => {
      delete row.dataset.typing;
      row.removeAttribute("role");
      row.removeAttribute("aria-label");
      populateContactMessageBubble(bubble, message, { reveal: true });
      const finalSize = measureContactBubbleSize(row, bubble);
      const finalWidth = Math.max(1, finalSize.width || startWidth);
      const finalHeight = Math.max(1, finalSize.height || startHeight);

      bubble.style.width = `${startWidth}px`;
      bubble.style.height = `${startHeight}px`;
      bubble.style.minWidth = `${startWidth}px`;
      bubble.style.minHeight = `${startHeight}px`;
      bubble.style.overflow = "hidden";
      bubble.style.transformOrigin = "top left";
      bubble.style.transform = "scale(0.98)";
      bubble.style.transition = [
        "width 320ms cubic-bezier(0.16, 1, 0.3, 1)",
        "height 320ms cubic-bezier(0.16, 1, 0.3, 1)",
        "min-width 320ms cubic-bezier(0.16, 1, 0.3, 1)",
        "min-height 320ms cubic-bezier(0.16, 1, 0.3, 1)",
        "transform 320ms cubic-bezier(0.16, 1, 0.3, 1)",
      ].join(", ");

      window.requestAnimationFrame(() => {
        bubble.style.width = `${finalWidth}px`;
        bubble.style.height = `${finalHeight}px`;
        bubble.style.minWidth = `${finalWidth}px`;
        bubble.style.minHeight = `${finalHeight}px`;
        bubble.style.transform = "scale(1)";
        window.setTimeout(() => revealMorphedContactBubble(bubble), 120);
        window.setTimeout(() => cleanupMorphedContactBubble(row, bubble), 380);
        if (shouldFollowLatest) {
          scrollContactChat({ force: true });
        }
      });
    }, 160);
  };

  const appendContactMessage = (author, message) => {
    if (!contactChatStack) {
      return;
    }

    const shouldFollowLatest = contactChatState.followLatest || contactChatIsNearBottom();
    const row = document.createElement("div");
    row.className = "contact-message";
    row.dataset.author = author;

    if (author === "agent") {
      const avatar = document.createElement("span");
      avatar.className = "contact-message-avatar";
      avatar.textContent = "A";
      avatar.setAttribute("aria-hidden", "true");
      row.appendChild(avatar);
    }

    const bubble = document.createElement("div");
    bubble.className = "contact-message-bubble";
    populateContactMessageBubble(bubble, message);

    row.appendChild(bubble);
    contactChatStack.appendChild(row);
    syncContactChatScrollable();
    if (shouldFollowLatest) {
      scrollContactChat({ force: true });
    }
  };

  const rememberContactMessage = (author, message) => {
    const text = normalizeContactAnswer(message);
    if (!text) {
      return;
    }

    contactChatState.messages.push({ author, text });
    if (contactChatState.messages.length > 18) {
      contactChatState.messages = contactChatState.messages.slice(-18);
    }
  };

  const addContactMessage = (author, message) => {
    appendContactMessage(author, message);
    rememberContactMessage(author, message);
  };

  const addContactAgentMessage = (message) => {
    morphContactTypingIndicatorToMessage(message);
    rememberContactMessage("agent", message);
  };

  const setContactComposerEnabled = (enabled) => {
    if (contactInput) {
      contactInput.disabled = !enabled;
    }

    if (contactSubmit) {
      contactSubmit.disabled = !enabled;
    }
  };

  const setContactSubmitLabel = (label) => {
    if (!contactSubmit) {
      return;
    }

    const normalizedLabel = String(label || "שליחה");
    contactSubmit.setAttribute("aria-label", normalizedLabel);
    const labelElement = contactSubmit.querySelector(".contact-send-label");
    if (labelElement) {
      labelElement.textContent = normalizedLabel;
    }
  };

  const syncContactInputSize = () => {
    if (!contactInput) {
      return;
    }

    syncContactViewportMetrics();
    const shouldFollowLatest = contactChatState.followLatest || contactChatIsNearBottom();
    const maxHeight = Number.parseFloat(window.getComputedStyle(contactInput).maxHeight) || 132;
    contactInput.style.height = "auto";
    contactInput.style.height = `${Math.min(Math.ceil(contactInput.scrollHeight) + 2, maxHeight)}px`;
    contactInput.scrollTop = contactInput.scrollHeight;
    syncContactChatScrollable();

    if (shouldFollowLatest) {
      scrollContactChat({ force: true });
    }
  };

  const resizeContactInput = () => {
    syncContactInputSize();
    window.cancelAnimationFrame(contactInputResizeFrame);
    window.clearTimeout(contactInputResizeTimer);
    contactInputResizeFrame = window.requestAnimationFrame(() => {
      syncContactInputSize();
      contactInputResizeTimer = window.setTimeout(syncContactInputSize, 80);
    });
  };

  const cancelContactAgentReply = () => {
    contactAgentRequestId += 1;
    if (contactAgentAbortController) {
      contactAgentAbortController.abort();
      contactAgentAbortController = null;
    }
    contactChatState.submitting = false;
    removeContactTypingIndicator();
  };

  const resetContactChat = (options = {}) => {
    cancelContactAgentReply();
    contactChatState.messages = [];
    contactChatState.intake = {};
    contactChatState.completed = false;
    contactChatState.readyToSubmit = false;
    contactChatState.started = false;
    contactChatState.submitting = false;
    contactChatState.followLatest = true;
    contactTypingIndicator = null;

    if (contactChatStack) {
      contactChatStack.innerHTML = "";
    }
    syncContactChatScrollable();

    if (contactForm) {
      delete contactForm.dataset.complete;
      contactForm.reset();
    }

    setContactStatus("");
    setContactComposerEnabled(true);
    if (contactInput) {
      contactInput.value = "";
      contactInput.placeholder = "הקלידו הודעה";
      resizeContactInput();
    }

    setContactSubmitLabel("שליחה");

    if (options.focus && contactInput) {
      window.setTimeout(() => contactInput.focus({ preventScroll: true }), 0);
    }

    if (window.location.protocol === "file:") {
      addContactMessage(
        "agent",
        "היי, אני סוכן הקליטה של Assistyca. באתר החי אני משתמש בבינה מלאכותית כדי להבין את העסק שלך ולשאול שאלות המשך טובות יותר. התצוגה המקומית לא יכולה להגיע לסוכן הזה.",
      );
      return;
    }

    void requestContactAgentReply();
  };

  const extractContactChannels = (answer) => {
    const emailMatch = answer.match(contactEmailPattern);
    const phoneMatch = answer.match(contactPhonePattern);
    const email = emailMatch ? emailMatch[0].replace(/[.,;:]$/, "") : "";
    const phone = phoneMatch ? phoneMatch[0].trim() : "";

    return {
      email,
      phone: phone || (email ? "" : answer),
    };
  };

  const buildContactPayload = (intake = {}) => {
    const channels = extractContactChannels(intake.contact || "");
    const transcript = contactChatState.messages
      .map((message) => `${message.author === "agent" ? "Agent" : "User"}: ${message.text}`)
      .join("\n");
    const message = [
      "שיחת קליטה מונחית AI מעמוד האודות.",
      "",
      `עסק: ${intake.business || ""}`,
      "",
      "סיכום העסק:",
      intake.businessSummary || intake.businessContext || "",
      "",
      "סיכום הכאבים:",
      intake.painSummary || intake.painPoints || "",
      "",
      "כלי או אוטומציה מוצעים:",
      intake.suggestedTool || intake.automationOpportunities || "",
      "",
      `קושי עבודה: ${intake.difficulty || ""}`,
      `דחיפות: ${intake.urgency || ""}`,
      "",
      `פרטי קשר מועדפים: ${intake.contact || ""}`,
      "",
      "תמלול:",
      transcript,
    ].join("\n");
    const formData = contactForm ? new FormData(contactForm) : new FormData();

    return {
      name: intake.name || "Website visitor",
      business: intake.business || "",
      email: intake.email || channels.email,
      phone: intake.phone || channels.phone,
      message,
      companyWebsite: String(formData.get("companyWebsite") || ""),
      page: window.location.href,
      intake,
      messages: contactChatState.messages,
    };
  };

  const finishContactChat = () => {
    contactChatState.completed = true;
    contactChatState.readyToSubmit = false;
    contactChatState.submitting = false;
    dismissContactKeyboard();
    setContactComposerEnabled(false);
    setContactStatus("");

    if (contactForm) {
      contactForm.dataset.complete = "true";
    }

    if (contactInput) {
      contactInput.value = "";
      resizeContactInput();
    }

    scrollContactChat({ force: true });
    window.setTimeout(keepContactLayoutPinned, 120);
    window.setTimeout(keepContactLayoutPinned, 320);
  };

  const submitContactIntake = async (intake = contactChatState.intake) => {
    if (contactChatState.submitting || contactChatState.completed || !contactChatState.readyToSubmit) {
      return;
    }

    contactChatState.submitting = true;
    setContactComposerEnabled(false);
    setContactStatus("שולח לבדיקה אנושית...");

    setContactSubmitLabel("שולח");

    if (window.location.protocol === "file:") {
      finishContactChat();
      setContactStatus("תצוגה מקומית בלבד. פתח/י את assistyca.com/about כדי לשלוח את השיחה באמת.", "error");
      return;
    }

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildContactPayload(intake)),
      });
      const data = await response.json().catch(() => ({}));

      if (!response.ok || !data.ok) {
        throw new Error(data.message || "לא הצלחתי לשלוח את השיחה כרגע.");
      }

      finishContactChat();
    } catch (error) {
      contactChatState.submitting = false;
      contactChatState.readyToSubmit = true;
      setContactComposerEnabled(true);
      setContactStatus(error.message || "לא הצלחתי לשלוח את השיחה כרגע.", "error");
      addContactMessage(
        "agent",
        "אני מבין/ה את המקרה, אבל לא הצלחתי להעביר אותו לבדיקה אנושית כרגע. אפשר ללחוץ שוב בעוד רגע.",
      );

      setContactSubmitLabel("ניסיון חוזר");
    }
  };

  const requestContactAgentReply = async (options = {}) => {
    if (contactChatState.completed) {
      return;
    }

    const keepKeyboardOpen = Boolean(options.keepKeyboardOpen) && shouldKeepContactKeyboardOpen();
    if (contactAgentAbortController) {
      contactAgentAbortController.abort();
    }

    const requestId = contactAgentRequestId + 1;
    contactAgentRequestId = requestId;
    contactAgentAbortController = new AbortController();
    contactChatState.submitting = true;
    setContactComposerEnabled(true);
    setContactStatus("");
    removeContactTypingIndicator();
    scheduleContactTypingIndicator(requestId);

    setContactSubmitLabel("שליחה");
    if (keepKeyboardOpen) {
      refocusContactInputForKeyboard();
    }

    try {
      const response = await fetch("/api/contact/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: contactAgentAbortController.signal,
        body: JSON.stringify({
          messages: contactChatState.messages,
          intake: contactChatState.intake,
          page: window.location.href,
        }),
      });
      const data = await response.json().catch(() => ({}));

      if (!response.ok || !data.ok) {
        throw new Error(data.message || "סוכן הקליטה לא יכול לענות כרגע.");
      }

      if (requestId !== contactAgentRequestId) {
        return;
      }

      const reply = normalizeContactAnswer(data.reply);
      if (reply) {
        addContactAgentMessage(reply);
      } else {
        removeContactTypingIndicator();
      }

      contactChatState.intake = data.intake && typeof data.intake === "object" ? data.intake : {};
      contactChatState.readyToSubmit = Boolean(data.done);
      contactChatState.started = true;

      if (contactChatState.readyToSubmit) {
        contactChatState.submitting = false;
        if (requestId === contactAgentRequestId) {
          contactAgentAbortController = null;
        }
        await submitContactIntake(contactChatState.intake);
        return;
      }

      setContactStatus("");
      if (contactInput) {
        contactInput.placeholder = "הקלידו הודעה";
      }
    } catch (error) {
      if (requestId !== contactAgentRequestId || error?.name === "AbortError") {
        return;
      }

      removeContactTypingIndicator();
      const fallback = contactChatState.started
        ? "יש לי כרגע בעיה להתחבר לחשיבה של הסוכן. אפשר לנסות שוב בעוד רגע."
        : "יש לי כרגע בעיה להתחיל את שיחת הקליטה. אפשר לנסות שוב בעוד רגע.";
      appendContactMessage("agent", fallback);
      setContactStatus(error.message || "סוכן הקליטה לא יכול לענות כרגע.", "error");
    } finally {
      if (requestId !== contactAgentRequestId) {
        return;
      }

      contactAgentAbortController = null;
      if (!contactChatState.completed && !contactChatState.readyToSubmit) {
        contactChatState.submitting = false;
        setContactComposerEnabled(true);
        setContactSubmitLabel("שליחה");
        if (keepKeyboardOpen) {
          refocusContactInputForKeyboard();
          releaseContactKeyboardHoldAfterRefocus();
        } else if (contactInput && !contactMobileViewportQuery.matches) {
          contactInput.focus({ preventScroll: true });
        }
      }
    }
  };

  const handleContactReply = async (options = {}) => {
    if (contactChatState.completed) {
      return;
    }

    const keepKeyboardOpen = Boolean(options.keepKeyboardOpen) && shouldKeepContactKeyboardOpen();
    if (keepKeyboardOpen) {
      markContactKeyboardHold();
    }

    if (contactChatState.readyToSubmit && !contactChatState.submitting) {
      await submitContactIntake(contactChatState.intake);
      return;
    }

    const answer = normalizeContactAnswer(contactInput ? contactInput.value : "");
    if (!answer) {
      setContactStatus("כתוב/י תשובה לפני השליחה.", "error");
      if (keepKeyboardOpen) {
        refocusContactInputForKeyboard();
      }
      return;
    }

    contactChatState.followLatest = true;
    contactChatState.readyToSubmit = false;
    addContactMessage("user", answer);
    setContactStatus("");

    if (contactInput) {
      contactInput.value = "";
      resizeContactInput();
      if (keepKeyboardOpen) {
        refocusContactInputForKeyboard();
      }
    }

    await requestContactAgentReply({ keepKeyboardOpen });
  };

  const shouldKeepContactKeyboardForSubmit = () => (
    shouldKeepContactKeyboardOpen() &&
    (
      document.activeElement === contactInput ||
      contactPreserveKeyboardOnSubmit ||
      contactSubmitPointerPreserved ||
      contactSubmitPointerSent ||
      contactKeyboardAppearsOpen()
    )
  );

  const getContactFocusable = () => {
    if (!contactModal || contactModal.hidden || contactModal.dataset.state === "closing") {
      return [];
    }

    return Array.from(
      contactModal.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.offsetParent !== null);
  };

  const openContactModal = () => {
    if (!contactModal || !contactForm) {
      return;
    }

    window.clearTimeout(contactCloseTimer);
    window.clearTimeout(contactAnimationTimer);
    contactLastFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    lockContactPageScroll();
    contactModal.hidden = false;
    contactModal.dataset.state = "opening";
    document.body.classList.add("contact-modal-open");
    syncContactViewportMetrics({ reset: true });
    if (!contactChatStack || contactChatStack.children.length === 0 || contactChatState.completed) {
      resetContactChat();
    }

    const completeOpen = () => {
      contactModal.dataset.state = "open";
      syncContactViewportMetrics();
      if (contactInput) {
        resizeContactInput();
        if (!contactMobileViewportQuery.matches) {
          contactInput.focus({ preventScroll: true });
        }
      }
      if (contactChatState.followLatest) {
        scrollContactChat({ force: true });
      }
    };

    if (contactMotionQuery.matches) {
      completeOpen();
      return;
    }

    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(completeOpen);
    });
  };

  const closeContactModal = () => {
    if (!contactModal || contactModal.hidden || contactModal.dataset.state === "closing") {
      return;
    }

    window.clearTimeout(contactCloseTimer);
    window.clearTimeout(contactAnimationTimer);
    contactModal.dataset.state = "closing";

    const finishClose = () => {
      cancelContactAgentReply();
      contactModal.hidden = true;
      delete contactModal.dataset.state;
      document.body.classList.remove("contact-modal-open");
      resetContactViewportMetrics();
      unlockContactPageScroll();
      if (contactLastFocus && typeof contactLastFocus.focus === "function") {
        contactLastFocus.focus({ preventScroll: true });
      }
    };

    if (contactMotionQuery.matches) {
      finishClose();
      return;
    }

    contactAnimationTimer = window.setTimeout(finishClose, contactAnimationMs);
  };

  contactOpeners.forEach((opener) => {
    opener.addEventListener("click", () => {
      openContactModal();
    });
  });

  contactClosers.forEach((closer) => {
    closer.addEventListener("click", () => {
      closeContactModal();
    });
  });

  if (contactBack) {
    contactBack.addEventListener("click", () => {
      closeContactModal();
    });
  }

  if (contactSubmit) {
    contactSubmit.addEventListener("pointerdown", (event) => {
      if (!shouldKeepContactKeyboardOpen() || contactChatState.readyToSubmit) {
        return;
      }

      event.preventDefault();
      contactSubmitPointerPreserved = true;
      markContactKeyboardHold();
      refocusContactInputForKeyboard();
    });

    contactSubmit.addEventListener("pointerup", (event) => {
      if (!contactSubmitPointerPreserved) {
        return;
      }

      event.preventDefault();
      contactSubmitPointerPreserved = false;
      contactSubmitPointerSent = true;
      if (contactForm && typeof contactForm.requestSubmit === "function") {
        contactForm.requestSubmit();
      } else {
        void handleContactReply({ keepKeyboardOpen: true });
      }
      window.setTimeout(() => {
        contactSubmitPointerSent = false;
      }, 350);
    });

    contactSubmit.addEventListener("pointercancel", () => {
      contactSubmitPointerPreserved = false;
    });

    contactSubmit.addEventListener("click", (event) => {
      if (contactSubmitPointerSent) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }

      if (contactPreserveKeyboardOnSubmit) {
        refocusContactInputForKeyboard();
      }
    });
  }

  if (contactModal) {
    contactModal.addEventListener("mousedown", (event) => {
      if (event.target === contactModal) {
        closeContactModal();
      }
    });
  }

  if (contactChatLog) {
    contactChatLog.addEventListener("touchstart", (event) => {
      contactChatTouchStartY = event.touches && event.touches.length > 0
        ? event.touches[0].clientY
        : 0;
    }, { passive: true });

    contactChatLog.addEventListener("touchmove", (event) => {
      const isScrollable = syncContactChatScrollable();
      if (!isScrollable) {
        event.preventDefault();
        return;
      }

      const nextTouchY = event.touches && event.touches.length > 0
        ? event.touches[0].clientY
        : contactChatTouchStartY;
      const touchDeltaY = nextTouchY - contactChatTouchStartY;
      const atTop = contactChatLog.scrollTop <= 0;
      const atBottom =
        contactChatLog.scrollTop + contactChatLog.clientHeight >=
        contactChatLog.scrollHeight - 1;

      if ((atTop && touchDeltaY > 0) || (atBottom && touchDeltaY < 0)) {
        event.preventDefault();
      }
    }, { passive: false });

    contactChatLog.addEventListener("scroll", () => {
      if (contactScrollAnimating) {
        return;
      }

      const isNearBottom = contactChatIsNearBottom();
      contactChatState.followLatest = isNearBottom;
      if (!isNearBottom) {
        window.cancelAnimationFrame(contactScrollFrame);
        window.cancelAnimationFrame(contactScrollAnimationFrame);
        contactScrollFrame = 0;
        contactScrollAnimationFrame = 0;
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (!contactModal || contactModal.hidden) {
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      closeContactModal();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = getContactFocusable();
    if (focusable.length === 0) {
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  if (contactForm) {
    contactForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await handleContactReply({
        keepKeyboardOpen: shouldKeepContactKeyboardForSubmit(),
      });
    });
  }

  if (contactInput) {
    ["input", "change", "paste", "cut", "keyup", "compositionupdate", "compositionend"].forEach((eventName) => {
      contactInput.addEventListener(eventName, resizeContactInput);
    });
    contactInput.addEventListener("focus", () => {
      syncContactInputFocusState();
      contactChatState.followLatest = true;
      resizeContactInput();
      keepContactLayoutPinned();
      window.setTimeout(keepContactLayoutPinned, 140);
      window.setTimeout(keepContactLayoutPinned, 360);
    });
    contactInput.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (contactPreserveKeyboardOnSubmit && shouldKeepContactKeyboardOpen()) {
          syncContactInputFocusState();
          refocusContactInputForKeyboard();
          return;
        }

        syncContactInputFocusState();
        syncContactViewportMetrics();
        if (contactChatState.followLatest) {
          scrollContactChat({ force: true });
        }
      }, 80);
    });
    document.addEventListener("selectionchange", () => {
      if (document.activeElement === contactInput) {
        resizeContactInput();
      }
    });
    contactInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (contactForm) {
          contactForm.requestSubmit();
        }
      }
    });
  }

  const keepContactLayoutPinned = () => {
    if (!contactModal || contactModal.hidden) {
      return;
    }

    window.cancelAnimationFrame(contactLayoutFrame);
    contactLayoutFrame = window.requestAnimationFrame(() => {
      if (!contactModal || contactModal.hidden) {
        return;
      }

      syncContactViewportMetrics();
      resizeContactInput();
      syncContactChatScrollable();
      if (contactChatState.followLatest) {
        scrollContactChat({ force: true });
      }
    });

    window.clearTimeout(contactLayoutPinTimer);
    contactLayoutPinTimer = window.setTimeout(() => {
      if (!contactModal || contactModal.hidden) {
        return;
      }

      syncContactViewportMetrics();
      resizeContactInput();
      syncContactChatScrollable();
      if (contactChatState.followLatest) {
        scrollContactChat({ force: true });
      }
    }, 360);
  };

  window.addEventListener("resize", keepContactLayoutPinned);
  if (typeof contactMobileViewportQuery.addEventListener === "function") {
    contactMobileViewportQuery.addEventListener("change", keepContactLayoutPinned);
  } else if (typeof contactMobileViewportQuery.addListener === "function") {
    contactMobileViewportQuery.addListener(keepContactLayoutPinned);
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", keepContactLayoutPinned);
    window.visualViewport.addEventListener("scroll", keepContactLayoutPinned);
  }

  document.querySelectorAll("[data-keyed-image]").forEach((imageElement) => {
    if (imageElement.dataset.keyed === "true") {
      return;
    }

    const source = imageElement.dataset.source || imageElement.getAttribute("src");
    if (!source) {
      return;
    }

    const clearThreshold = Number(imageElement.dataset.keyClear || 243);
    const softThreshold = Number(imageElement.dataset.keySoft || 228);
    const spreadLimit = Number(imageElement.dataset.keySpread || 24);
    const softSpreadLimit = Number(imageElement.dataset.keySoftSpread || 22);
    const fadeRange = Math.max(1, clearThreshold - softThreshold);

    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;

        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) {
          return;
        }

        context.drawImage(image, 0, 0);
        const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
        const data = imageData.data;

        for (let index = 0; index < data.length; index += 4) {
          const red = data[index];
          const green = data[index + 1];
          const blue = data[index + 2];
          const alpha = data[index + 3];
          const brightest = Math.max(red, green, blue);
          const darkest = Math.min(red, green, blue);
          const average = (red + green + blue) / 3;
          const spread = brightest - darkest;

          if (average > clearThreshold && spread < spreadLimit) {
            data[index + 3] = 0;
            continue;
          }

          if (average > softThreshold && spread < softSpreadLimit) {
            const keepRatio = Math.max(
              0,
              Math.min(1, (clearThreshold - average) / fadeRange),
            );
            data[index + 3] = Math.round(alpha * keepRatio);
          }
        }

        context.putImageData(imageData, 0, 0);
        imageElement.src = canvas.toDataURL("image/png");
        imageElement.dataset.keyed = "true";
      } catch (error) {
        console.warn("Image cleanup skipped.", error);
      }
    };

    image.src = source;
  });

  const nav = document.querySelector(".nav");
  const navLinks = Array.from(document.querySelectorAll(".nav a[data-section]"));
  const navIndicator = document.querySelector(".nav-indicator");
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sectionTargets = navLinks
    .map((link) => document.getElementById(link.dataset.section || ""))
    .filter(Boolean);

  const updateNavIndicator = () => {
    if (!navIndicator) {
      return;
    }

    const activeLink = navLinks.find((link) => link.dataset.active === "true");
    if (!activeLink) {
      navIndicator.style.opacity = "0";
      return;
    }

    const indicatorWidth = navIndicator.getBoundingClientRect().width || 40;
    const offset = activeLink.offsetLeft + (activeLink.offsetWidth - indicatorWidth) / 2;
    navIndicator.style.transform = `translateX(${offset}px)`;
    navIndicator.style.opacity = "1";
  };

  const setActiveLink = (activeId) => {
    const currentActiveLink =
      navLinks.find((link) => link.dataset.active === "true") || null;
    const nextActiveLink =
      navLinks.find((link) => link.dataset.section === activeId) || null;

    navLinks.forEach((link) => {
      link.dataset.active = link.dataset.section === activeId ? "true" : "false";
    });

    updateNavIndicator();

    if (
      nav &&
      nextActiveLink &&
      nextActiveLink !== currentActiveLink &&
      nav.scrollWidth > nav.clientWidth + 4
    ) {
      nextActiveLink.scrollIntoView({
        block: "nearest",
        inline: "center",
        behavior: prefersReducedMotion ? "auto" : "smooth",
      });
    }
  };

  const initialHash = window.location.hash.replace("#", "");
  if (initialHash) {
    setActiveLink(initialHash);
  } else {
    setActiveLink("home");
  }

  if (sectionTargets.length > 0) {
    const observer = new IntersectionObserver(
      (entries) => {
        const visibleEntries = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio);

        if (visibleEntries.length > 0) {
          setActiveLink(visibleEntries[0].target.id);
        }
      },
      {
        rootMargin: "-24% 0px -45% 0px",
        threshold: [0.22, 0.38, 0.6],
      },
    );

    sectionTargets.forEach((section) => observer.observe(section));
  }

  window.addEventListener("load", updateNavIndicator);
  window.addEventListener("resize", updateNavIndicator);
});
