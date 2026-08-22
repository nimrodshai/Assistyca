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
        self.assertIn("header.append(titleGroup);", script)
        self.assertIn("function resizeReengagementDemoDraftTextarea", script)
        self.assertIn("scheduleReengagementDemoDraftResize(textarea);", script)
        self.assertIn("function formatReengagementElapsedDuration", script)
        self.assertIn("function getReengagementDemoCandidateInactiveMilliseconds", script)
        self.assertIn("return inactiveLabel ? `Inactive for ${inactiveLabel}` : \"Inactive\";", script)
        self.assertNotIn("return `Inactive for ${formatReengagementInactivityLabel(settings)}`;", script)
        self.assertNotIn("Last active ${lastMessageAt}", script)
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

    def test_whatsapp_delivery_uses_platform_list(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="deliveryPlatformManager"', html)
        self.assertIn('id="deliveryPlatformList"', html)
        self.assertNotIn('data-delivery-platform-option="telegram"', html)
        self.assertIn('id="monitorWhatsAppSetupButton"', html)
        self.assertNotIn('id="featureStudioWhatsAppDetailsButton"', html)
        self.assertNotIn(">WhatsApp details<", html)
        self.assertNotIn('<option value="both">WhatsApp + Telegram</option>', html)
        self.assertIn("function renderDeliveryPlatformList", script)
        self.assertIn("elements.deliveryPlatformMenu.replaceChildren(...buttons)", script)
        self.assertIn("function normalizeFeatureWhatsAppReplyAssistantSettings", script)
        self.assertIn('deliveryChannels: normalized.deliveryChannels.filter((channel) => channel === "whatsapp")', script)
        self.assertIn('return WHATSAPP_TOOL_PLATFORM_OPTIONS.filter((option) => option.id === "whatsapp")', script)
        self.assertIn("dataset.deliveryPlatformRemove", script)
        self.assertIn("No platforms added yet", script)
        self.assertIn(".delivery-platform-row", styles)

    def test_agent_scheduled_whatsapp_request_uses_scheduled_action_flow(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('type: "scheduled-message"', script)
        self.assertIn("function isAgentScheduledMessageRequest", script)
        self.assertLess(
            script.index("if (isAgentScheduledMessageRequest(value))"),
            script.index('return AGENT_BLUEPRINTS.whatsappReplies;'),
        )
        self.assertIn("function buildAgentScheduledMessageDetails", script)
        self.assertIn("function scheduleAgentScheduledMessageProposal", script)
        self.assertIn('apiRequest("/api/agent/turn"', script)
        self.assertIn('apiRequest("/api/scheduled-actions"', script)
        self.assertIn('apiRequest("/api/scheduled-actions?limit=100"', script)
        self.assertIn("function renderAgentActions", script)
        self.assertIn("function renderScheduledActionList", script)
        self.assertIn("dataset.agentActionListSignature", script)
        self.assertIn("dataset.agentActionDetailSignature", script)
        self.assertIn("function createScheduledActionDetail", script)
        self.assertNotIn("`Action ${action.id}`", script)
        self.assertIn("SCHEDULED_ACTIONS_POLL_MS", script)
        self.assertIn('id="agentActionsPanel"', html)
        self.assertIn('id="agentPendingActionList"', html)
        self.assertIn('id="agentCompletedActionList"', html)
        self.assertIn('id="agentActionDetailView"', html)
        self.assertIn('id="agentAddToolButton"', html)
        self.assertIn('id="agentAddToolMenu"', html)
        self.assertIn(".agent-action-error", styles)
        self.assertIn(".agent-action-item.is-failed::before", styles)
        self.assertIn(".agent-add-tool-button", styles)
        self.assertIn(".agent-add-tool-menu", styles)
        self.assertIn("function getAgentMessageRenderSignature", script)
        self.assertIn("function shouldPinAgentMessagesToBottom", script)
        self.assertIn("dataset.agentMessageRenderSignature", script)
        self.assertIn("dataset.agentMessageLastId", script)
        render_messages = script[
            script.index("function renderAgentMessages"):
            script.index("function createAgentList")
        ]
        self.assertNotIn(
            "replaceChildren(...visibleMessages.map(renderAgentMessage));\n"
            "  elements.agentMessageList.scrollTop = elements.agentMessageList.scrollHeight;",
            render_messages,
        )
        self.assertIn(".agent-message-list::before", styles)
        self.assertIn("margin-top: auto;", styles)
        self.assertIn(".app-shell.is-chat-workspace .agent-actions-panel-body", styles)
        self.assertIn("scroll-padding-bottom: clamp(2rem, 5vh, 3.5rem);", styles)
        self.assertIn(".app-shell.is-chat-workspace .agent-tool-shelf", styles)
        self.assertIn("overflow: visible;", styles)
        self.assertNotIn(".app-shell.is-chat-workspace .agent-tool-shelf {\n  min-height: 0;\n  overflow-y: auto;", styles)
        self.assertIn("AGENT_ADD_TOOL_OPTIONS", script)
        self.assertIn('label: "Email"', script)
        self.assertIn('label: "Calendar"', script)
        self.assertIn("function createAgentAddToolLogo", script)
        self.assertIn('icon: "telegram"', script)
        self.assertIn("function renderAgentAddToolMenu", script)
        self.assertIn("data-agent-add-tool", script)
        self.assertNotIn(".agent-add-tool-menu {\n  position: absolute;", styles)
        self.assertIn(".agent-add-tool-icon svg", styles)
        self.assertNotIn("nextIndex < 3 && !/\\b(calendar|schedule|agenda|appointments?)\\b/i.test", script)

    def test_agent_proposal_changes_use_contextual_structured_revision(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function applyAgentScheduledMessageRevision", script)
        self.assertIn("getAgentDefaultScheduledMessageText(details.timeLocal)", script)
        self.assertIn("patch.preserveMessageText !== true", script)
        self.assertIn("proposal.revision", script)
        self.assertIn("proposalRevision", script)
        self.assertIn('apiRequest("/api/agent/turn"', script)
        self.assertIn("agentTurnBusy = true", script)
        self.assertIn('kind: "thinking"', script)
        self.assertIn(".agent-thinking-dots", styles)
        self.assertIn("function pushAgentApprovalPrompt(proposal, reply = \"\")", script)
        self.assertIn("function pushAgentProposalNextStep(proposal, reply = \"\")", script)
        self.assertIn("pushAgentApprovalPrompt(proposal, reply)", script)
        self.assertIn("function pushAgentActionIntentMessage", script)
        self.assertIn('return "Set it up please";', script)
        self.assertIn('pushAgentMessage("user", text, {', script)
        self.assertIn("function getAgentProposalLocalActions", script)
        self.assertIn("function getRenderableAgentActions", script)
        self.assertIn("...getAgentProposalLocalActions()", script)
        self.assertIn("const actions = getRenderableAgentActions();", script)
        self.assertIn("isAgentProposalLocalAction(action)", script)
        self.assertIn("Approved from chat", script)
        self.assertIn("function resolveAgentMessageActions", script)
        self.assertIn("function resolvePendingAgentMessageActions", script)
        self.assertIn("function areAgentMessageActionsResolved", script)
        self.assertIn("AGENT_PROPOSAL_FIELD_SCHEMAS", script)
        self.assertIn("function getAgentNextMissingQuestionIndex", script)
        self.assertIn("function applyAgentFieldProposalRevision", script)
        self.assertIn("fields: proposal.fields", script)
        self.assertIn('outcome === "proposal" || (outcome === "question" && turn?.proposalType)', script)
        self.assertIn("button.dataset.agentActionMessage = message.id", script)
        self.assertIn("button.disabled = Boolean(isStaleApproval || actionsResolved)", script)
        self.assertIn('resolveAgentMessageActions(messageId, action)', script)
        self.assertIn("return pushAgentMessage(\"assistant\", messageText", script)
        self.assertNotIn("function getAgentConversationQuestion", script)
        self.assertNotIn("function getPendingAgentQuestion", script)
        self.assertNotIn("function getPendingAgentProposalChange", script)
        self.assertNotIn("function handleAgentQuestionAnswer", script)
        self.assertNotIn("function shouldTreatAgentInputAsNewRequest", script)
        self.assertNotIn("function reviseAgentProposal", script)
        self.assertNotIn('apiRequest("/api/agent/proposals/revise"', script)
        self.assertNotIn("function getAgentApprovalCopy", script)
        self.assertNotIn("naturalIntroduction", script)
        self.assertNotIn("Want me to schedule it?", script)
        self.assertNotIn("Should I set it up?", script)
        self.assertNotIn("Action #${scheduledAction.id}", script)
        self.assertNotIn("Would you like me to schedule it?", script)
        handler = script[
            script.index("async function handleAgentUserText"):
            script.index("function handleAgentComposerSubmit")
        ]
        self.assertIn('apiRequest("/api/agent/turn"', handler)
        self.assertIn('resolvePendingAgentMessageActions("user-message")', handler)
        self.assertNotIn("createAgentProposalFromRequest(cleanText)", handler)

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
