from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import resolve_static_page_alias


class PortalStaticPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_resolve_static_page_alias_supports_about_with_or_without_trailing_slash(self) -> None:
        self.assertEqual(resolve_static_page_alias("/about"), Path("about/index.html"))
        self.assertEqual(resolve_static_page_alias("/about/"), Path("about/index.html"))
        self.assertIsNone(resolve_static_page_alias("/"))

    def test_admin_client_type_select_applies_value_after_options_exist(self) -> None:
        body = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        start = body.index("function createAdminClientTypeSelect")
        end = body.index("function createAdminActiveSwitch", start)
        snippet = body[start:end]

        self.assertIn("const selectedClientType", snippet)
        self.assertIn("option.selected = type.value === selectedClientType;", snippet)
        self.assertLess(snippet.index("select.append(option);"), snippet.index("select.value = selectedClientType;"))
        self.assertIn("select.dataset.adminClientTypeValue = selectedClientType;", snippet)

    def test_reengagement_demo_results_use_completion_popup_not_editor_card(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn('id="reengagementDemoResultsCard"', html)
        self.assertNotIn('id="reengagementDemoResultsSummary"', html)
        self.assertNotIn('id="reengagementDemoResultsList"', html)
        self.assertIn('id="authAlertBody"', html)
        self.assertIn("function formatReengagementSkippedSummary", script)
        self.assertIn("skippedConversations", script)
        self.assertIn("function formatReengagementCheckedConversationsLabel", script)
        self.assertIn("No saved conversations are available yet", script)
        self.assertNotIn("WhatsApp delivery also failed", script)
        self.assertNotIn("Demo results ready", script)
        self.assertIn("state.reengagementDemoResult =", script)
        self.assertIn("const errorPayload = error?.payload", script)
        self.assertIn("const errorRun = errorPayload.run", script)
        self.assertIn("function createReengagementDemoAlertBody", script)
        self.assertIn("function openReengagementDemoResultsAlert", script)
        self.assertIn('label.textContent = "Draft";', script)
        self.assertIn("textarea.rows = 2;", script)
        self.assertIn("Inactive ${formatReengagementInactivityLabel(settings)}", script)
        self.assertNotIn("Fallback draft", script)
        self.assertNotIn("AI draft", script)
        self.assertNotIn("used for draft context", script)
        self.assertNotIn("reengagement-demo-preview", script)
        self.assertNotIn("reengagement-demo-badge", script)
        self.assertNotIn('badge.textContent = "Matched";', script)
        self.assertNotIn("saved ${messageCount === 1 ? \"message\" : \"messages\"}", script)
        self.assertIn("getReengagementDemoAlertIcon(run)", script)
        self.assertIn("openReengagementDemoResultsAlert(", script)
        self.assertIn('variant: hasCandidateResults ? "demo-results" : "default"', script)
        self.assertIn("openAuthAlert(", script)
        self.assertIn('.auth-alert-dialog[data-variant="demo-results"]', styles)
        self.assertIn(".reengagement-demo-alert-results", styles)

    def test_about_pretty_route_serves_without_redirect(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/about") as response:
            body = response.read().decode("utf-8")
            final_url = response.geturl()
            status_code = response.status

        self.assertEqual(status_code, 200)
        self.assertEqual(final_url, f"{self.base_url}/about")
        self.assertIn("Assistyca | Nimrod Shai", body)
        self.assertIn("AI Agents &amp; Automations", body)
        self.assertIn("I build smart systems", body)
        self.assertIn("With a background in technology since 2009 and a passion for", body)
        self.assertIn("data-contact-modal", body)
        self.assertIn("/api/contact", body)
        self.assertIn("/api/contact/agent", body)
        self.assertIn("Assistyca intake agent", body)
        self.assertNotIn("mailto:nimrod.shai@gmail.com", body)

    def test_about_contact_modal_includes_mobile_keyboard_layout_hooks(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/about") as response:
            body = response.read().decode("utf-8")

        self.assertIn("--contact-keyboard-offset", body)
        self.assertIn("--contact-mobile-viewport-top", body)
        self.assertIn("--contact-mobile-viewport-height", body)
        self.assertIn("--contact-mobile-visible-height", body)
        self.assertIn("data-contact-chat-stack", body)
        self.assertIn(".contact-chat-stack", body)
        self.assertIn("justify-content: flex-end", body)
        self.assertIn("grid-template-rows: minmax(0, 1fr) auto auto", body)
        self.assertIn("body.contact-modal-open .page", body)
        self.assertIn("position: fixed;", body)
        self.assertIn("lockContactPageScroll", body)
        self.assertIn("contactModal.dataset.keyboard", body)
        self.assertIn("contactModal.dataset.inputFocused", body)
        self.assertIn("syncContactInputFocusState", body)
        self.assertIn("dismissContactKeyboard", body)
        self.assertIn("contactInput.blur()", body)
        self.assertIn("contactPreserveKeyboardOnSubmit = false", body)
        self.assertIn("window.clearTimeout(contactKeyboardFocusTimer)", body)
        self.assertIn("window.clearTimeout(contactKeyboardHoldTimer)", body)
        self.assertIn("contactKeyboardOffsetThreshold", body)
        self.assertIn("releaseContactKeyboardHoldAfterRefocus", body)
        self.assertIn("getContactVisualKeyboardOffset(previousLayoutHeight)", body)
        self.assertIn("contactKeyboardAppearsOpen", body)
        self.assertIn("shouldKeepContactKeyboardForSubmit", body)
        self.assertIn("keepKeyboardOpen: shouldKeepContactKeyboardForSubmit()", body)
        self.assertIn("keyboardGeometryActive", body)
        self.assertIn("shouldUseVisualViewport", body)
        self.assertIn("inputFocused || keyboardGeometryActive", body)
        self.assertIn("window.requestAnimationFrame(keepContactLayoutPinned)", body)
        self.assertIn("contactChatHasOverflow", body)
        self.assertIn("syncContactChatScrollable", body)
        self.assertIn('.contact-chat-thread[data-scrollable="true"]', body)
        self.assertIn("overflow-y: hidden", body)
        self.assertIn("overflow-y: auto", body)
        self.assertIn("contactChatStack.appendChild(row)", body)
        self.assertIn("contactChatStack.innerHTML = \"\"", body)
        self.assertIn("contactChatStack.children.length === 0", body)
        self.assertIn('contactChatLog.addEventListener("touchmove"', body)
        self.assertIn("event.preventDefault()", body)
        self.assertIn("{ passive: false }", body)
        self.assertIn("height: var(--contact-mobile-visible-height)", body)
        self.assertIn("transform: translate3d(0, var(--contact-mobile-viewport-top), 0)", body)
        self.assertIn("padding: 1rem 0.82rem 0.82rem", body)
        self.assertNotIn("syncContactControlHeights", body)
        self.assertNotIn("margin-top: auto", body)
        self.assertNotIn("position: fixed;\n          left: 0;\n          right: 0;\n          bottom: var(--contact-keyboard-offset)", body)
        self.assertNotIn("calc(0.82rem + var(--contact-keyboard-offset)", body)
        self.assertIn('window.matchMedia("(max-width: 640px)")', body)
        self.assertIn('window.visualViewport.addEventListener("scroll", keepContactLayoutPinned)', body)

    def test_about_contact_modal_supports_steering_while_agent_thinks(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/about") as response:
            body = response.read().decode("utf-8")

        self.assertIn("contactAgentAbortController", body)
        self.assertIn("const contactTypingDelayMs = 1520", body)
        self.assertIn("scheduleContactTypingIndicator", body)
        self.assertIn("setTimeout", body)
        self.assertIn("signal: contactAgentAbortController.signal", body)
        self.assertIn("morphContactTypingIndicatorToMessage", body)
        self.assertIn("measureContactBubbleSize", body)
        self.assertIn("data-morphing-reply", body)
        self.assertIn('data-reveal="pending"', body)
        self.assertIn("animateContactChatScroll", body)
        self.assertIn("contactScrollAnimating", body)
        self.assertIn("scrollContactChat({ force: true, animated: true })", body)
        self.assertIn("keepKeyboardOpen", body)
        self.assertIn("pointerdown", body)
        self.assertIn("contactSubmitPointerPreserved", body)
        self.assertNotIn("scrollbar-gutter: stable", body)
        self.assertIn("scrollbar-width: none", body)
        self.assertIn(".contact-message-input::-webkit-scrollbar", body)
        self.assertIn("data-contact-back", body)
        self.assertIn("חזור לאתר", body)
        self.assertNotIn('.contact-form[data-complete="true"] .contact-privacy', body)


if __name__ == "__main__":
    unittest.main()
