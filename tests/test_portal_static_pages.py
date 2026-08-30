from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
import re
from urllib import error as urllib_error
from urllib import parse as urllib_parse
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

    def test_every_response_carries_the_hardening_headers(self) -> None:
        for path in ("/portal/", "/about", "/portal/app.js", "/api/pricing"):
            with self.subTest(path=path):
                try:
                    with urllib_request.urlopen(f"{self.base_url}{path}") as response:
                        headers = response.headers
                except urllib_error.HTTPError as exc:
                    headers = exc.headers

                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(headers.get("X-Frame-Options"), "DENY")
                self.assertEqual(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
                self.assertEqual(headers.get("Cross-Origin-Opener-Policy"), "same-origin-allow-popups")
                self.assertIn("geolocation=()", headers.get("Permissions-Policy", ""))

                policy = headers.get("Content-Security-Policy", "")
                self.assertIn("default-src 'self'", policy)
                self.assertIn("frame-ancestors 'none'", policy)
                self.assertIn("object-src 'none'", policy)
                # The whole point of extracting the inline scripts: no 'unsafe-inline'
                # and no 'unsafe-eval' anywhere in script-src.
                script_src = next(part for part in policy.split("; ") if part.startswith("script-src"))
                self.assertNotIn("unsafe-inline", script_src)
                self.assertNotIn("unsafe-eval", script_src)
                self.assertIn("https://accounts.google.com", script_src)

    def test_csp_allows_everything_the_meta_signup_popup_needs(self) -> None:
        """The Embedded Signup SDK loads a script, calls facebook.com, and frames it.

        Missing any one of these makes the Connect WhatsApp button fail in a way
        that only shows up in the browser console, never in a Python test.
        """
        with urllib_request.urlopen(f"{self.base_url}/portal/") as response:
            policy = response.headers.get("Content-Security-Policy", "")

        directives = {
            part.split(" ", 1)[0]: part
            for part in policy.split("; ")
            if " " in part
        }
        self.assertIn("https://connect.facebook.net", directives["script-src"])
        self.assertIn("https://graph.facebook.com", directives["connect-src"])
        self.assertIn("https://www.facebook.com", directives["connect-src"])
        self.assertIn("https://www.facebook.com", directives["frame-src"])

    def test_hsts_is_sent_only_when_the_request_arrived_over_https(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/portal/") as response:
            self.assertIsNone(response.headers.get("Strict-Transport-Security"))

        request = urllib_request.Request(
            f"{self.base_url}/portal/",
            headers={"X-Forwarded-Proto": "https"},
        )
        with urllib_request.urlopen(request) as response:
            self.assertIn("max-age=31536000", response.headers.get("Strict-Transport-Security", ""))

    def test_served_pages_carry_no_inline_scripts(self) -> None:
        for relative in ("index.html", "privacy.html", "portal/index.html", "about/index.html"):
            with self.subTest(page=relative):
                markup = (self.root / relative).read_text(encoding="utf-8")
                self.assertNotIn("<script>", markup)

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

    def test_clients_admin_surfaces_have_dark_mode_treatment(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("styles.css?v=156", html)
        self.assertIn(':root[data-theme="dark"] .panel-intro h1', styles)
        self.assertIn(':root[data-theme="dark"] .client-metric', styles)
        self.assertIn(':root[data-theme="dark"] .admin-users-table-wrap', styles)
        self.assertIn(':root[data-theme="dark"] .admin-users-table th', styles)
        self.assertIn(':root[data-theme="dark"] .admin-users-table td', styles)
        self.assertIn(':root[data-theme="dark"] .admin-client-type-select[data-admin-client-type-value="demo"]', styles)

    def test_an_answer_says_which_mailbox_it_could_not_read(self) -> None:
        # A partial answer that says nothing about the mailbox it skipped
        # passes a smaller total off as the whole one.
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function describeAgentAnswerSkippedMailboxes", script)
        self.assertIn("skippedMailboxes", script)
        self.assertIn("Here is what I found in the rest of your mail", script)
        self.assertIn("const skippedNote = describeAgentAnswerSkippedMailboxes(results);", script)

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
        self.assertIn('deliveryChannels: hasExplicitDelivery ? normalized.deliveryChannels : ["portal"]', script)
        self.assertIn('return WHATSAPP_TOOL_PLATFORM_OPTIONS.filter((option) => ["whatsapp", "telegram", "portal"].includes(option.id))', script)
        self.assertIn('id: "portal"', script)
        self.assertIn('kind: "whatsapp-reply-suggestion"', script)
        self.assertIn('/api/approvals?status=pending&delivery=portal', script)
        self.assertIn('data-agent-whatsapp-action', script)
        self.assertIn('saveAndActivateAgentWhatsAppProposal', script)
        self.assertIn('WhatsApp reply assistant is active.', script)
        self.assertIn(".agent-message-whatsapp-card", styles)
        self.assertIn("dataset.deliveryPlatformRemove", script)
        self.assertIn("No platforms added yet", script)
        self.assertIn(".delivery-platform-row", styles)

    def test_agent_scheduled_whatsapp_request_uses_scheduled_action_flow(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")
        server_source = (self.root / "packages" / "infrastructure" / "portal_auth" / "server.py").read_text(encoding="utf-8")

        self.assertIn('type: "scheduled-message"', script)
        self.assertIn("function isAgentScheduledMessageRequest", script)
        self.assertLess(
            script.index("if (isAgentScheduledMessageRequest(value))"),
            script.index('return AGENT_BLUEPRINTS.whatsappReplies;'),
        )
        self.assertIn("function buildAgentScheduledMessageDetails", script)
        self.assertIn("function getWhatsAppConnectionSetupState", script)
        self.assertIn("function isWhatsAppConnectionReady", script)
        self.assertIn("function canRefreshFeatureActivationWebhook", script)
        self.assertIn('const refreshOnly = !hasActivationChanges && canRefreshWebhook;', script)
        self.assertIn('"Refresh webhook"', script)
        self.assertIn("featureActivationWebhookStatusTitle", script)
        self.assertIn('"Webhook refreshed"', script)
        self.assertIn('"Business number verified"', script)
        self.assertIn("Customer messages must be sent to", script)
        self.assertIn("only receives approval alerts", script)
        self.assertIn("messages webhook field", script)
        self.assertIn('id="featureActivationCustomerNumberCard"', html)
        self.assertIn("Customer WhatsApp number", html)
        self.assertIn("function updateFeatureActivationCustomerNumber", script)
        self.assertIn("formatWhatsAppHumanPhoneNumber", script)
        self.assertIn(".feature-activation-customer-number", styles)
        self.assertIn('"whatsapp_webhook_subscription_refreshed"', server_source)
        self.assertIn('setStatus(refreshOnly ? "WhatsApp webhook refreshed." : "WhatsApp details saved.");', script)
        self.assertIn("function buildAgentToolContext", script)
        self.assertIn("function isAgentWhatsAppMonitoringRequest", script)
        self.assertIn('show-whatsapp-setup', script)
        self.assertIn('open-whatsapp-setup', script)
        self.assertIn('kind: "connection-setup"', script)
        self.assertIn("function createAgentConnectionSetupCard", script)
        self.assertIn("toolContext: buildAgentToolContext()", script)
        self.assertIn("Needs details", script)
        self.assertIn(".agent-message-connection-card", styles)
        self.assertIn("function scheduleAgentScheduledMessageProposal", script)
        self.assertIn('apiRequest("/api/agent/turn"', script)
        self.assertIn('apiRequest("/api/scheduled-actions"', script)
        self.assertIn('apiRequest("/api/scheduled-actions?limit=100"', script)
        self.assertIn("function renderAgentActions", script)
        self.assertIn("function getScheduledActionCreatedTime", script)
        self.assertIn("function sortScheduledActionsByCreatedAt", script)
        self.assertIn("sortScheduledActionsByCreatedAt(", script)
        self.assertIn("Number.NEGATIVE_INFINITY", script)
        self.assertIn("function isAgentActionsInitialLoading", script)
        self.assertIn("scheduledActionsInitialLoadPending", script)
        self.assertIn("sourceActionsInitialLoadPending", script)
        self.assertIn('renderScheduledActionLoadingList(elements.agentPendingActionList, "Loading actions…");', script)
        self.assertIn("resetAgentWorkspaceRemoteState({ loading: true });", script)
        self.assertIn("function renderScheduledActionList", script)
        action_item_renderer = script[
            script.index("function renderScheduledActionItemContent"):
            script.index("function createScheduledActionItem")
        ]
        self.assertIn("item.replaceChildren(trigger, expansion);", action_item_renderer)
        self.assertNotIn("item.append(trigger, expansion);", action_item_renderer)

    def test_calendar_action_lists_calendars_as_tags(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        # The calendar is a list of connections, not a sentence someone typed.
        self.assertNotIn('["Calendar", "calendar", "Connected calendar"],', script)
        self.assertIn('["Calendars", "calendar", ""],', script)
        self.assertIn("function createAgentCalendarTagsField", script)
        self.assertIn("createAgentCalendarTagsField(label, draft[key])", script)
        self.assertIn("function getConnectedCalendarTagLabel", script)
        self.assertIn('return address ? `Google Calendar (${address})` : "Google Calendar";', script)
        self.assertIn("function getAgentCalendarAddressTags", script)
        self.assertIn("function formatAgentCalendarFieldValue", script)
        self.assertIn("const AGENT_CALENDAR_TAG_LIMIT = 5;", script)

        tags_field = script[
            script.index("function createAgentCalendarTagsField"):
            script.index("function createAgentCalendarSummaryDateRangeField")
        ]
        # Nobody knows a calendar's address by heart, so the field never asks
        # for one: calendars are picked from what the connection can read.
        self.assertNotIn("Add a calendar email address", script)
        self.assertIn('placeholder.textContent = "Add another calendar…";', tags_field)
        self.assertIn("agent-action-editor-chip", tags_field)
        self.assertIn("agentCalendarTagRemove", tags_field)
        self.assertIn('setHint("Connect Google Calendar so this action has a calendar to read.");', tags_field)
        self.assertIn(".agent-action-editor-chip.is-fixed", styles)
        self.assertIn(".agent-action-editor-hint", styles)
        self.assertIn(':root[data-theme="dark"] .agent-action-editor-chip {', styles)

    def test_calendar_action_picks_calendars_from_inside_the_account(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        # A connection holds several calendars, so the field offers those rather
        # than asking anyone to find a calendar ID in Google's settings.
        self.assertIn('const AGENT_CALENDAR_PRIMARY_ID = "primary";', script)
        self.assertIn("function getAgentCalendarSelectionIds", script)
        self.assertIn("function refreshAgentCalendarSources", script)
        self.assertIn('apiRequest("/api/platform-connections/calendars"', script)
        self.assertIn("function getAgentCalendarConnectionSignature", script)
        self.assertIn("function renderOpenAgentCalendarFields", script)
        self.assertIn("agentCalendarSources: []", script)
        self.assertIn("resetAgentCalendarSources();", script)

        tags_field = script[
            script.index("function createAgentCalendarTagsField"):
            script.index("function createAgentCalendarSummaryDateRangeField")
        ]
        # Each connected account is its own group of chips, and the dropdown
        # offers the calendars inside it that the action does not read yet.
        self.assertIn("getAgentCalendarSourceHeading(source)", tags_field)
        self.assertIn("function renderPicker", tags_field)
        self.assertIn("option.value = calendar.id;", tags_field)
        self.assertIn("parent = document.createElement(\"optgroup\");", tags_field)
        self.assertIn("void refreshAgentCalendarSources();", tags_field)
        # An action that reads no calendar at all is not a setting to land on by
        # unticking, and a calendar the account stopped listing is still named.
        self.assertIn('setHint("This action needs at least one calendar to read.", true);', tags_field)
        self.assertIn('const heading = sources.length ? "Also reading" : getConnectedCalendarTagLabel();', tags_field)
        self.assertIn("Loading the calendars in this account…", tags_field)
        # A connection that cannot list its calendars has nothing to offer, so
        # the row says so and reconnecting is the one thing it can do.
        self.assertIn('placeholder.textContent = "Reconnect to list your calendars";', tags_field)
        self.assertIn('openPlatformConnection("calendar");', tags_field)
        # An action with no calendar at all is the same dead end, so the button
        # beside the dropdown connects one rather than only reconnecting.
        self.assertIn('connectButton.textContent = connected ? "Reconnect" : "Connect";', tags_field)
        self.assertIn("connectButton.hidden = connected && !needsReconnect();", tags_field)
        self.assertIn(".agent-calendar-add {", styles)
        self.assertIn(".agent-calendar-add .agent-action-editor-select-wrap {", styles)
        self.assertIn(".agent-calendar-source-name", styles)
        # The tickable chips are gone, and so is the styling only they used.
        self.assertNotIn(".agent-action-editor-chip.is-selectable", styles)
        self.assertNotIn(".agent-action-editor-chip-mark", styles)

    def test_monitor_actions_support_manual_runs_and_manual_only_mode(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="monitorManualOnly"', html)
        self.assertIn("Run manually only", html)
        self.assertIn('id="agentAddToolBackdrop"', html)
        self.assertIn('data-agent-run-monitor-action', script)
        self.assertIn("function appendAgentActionButton", script)
        self.assertIn('text: isBusy ? "Running…" : "Run now",', script)
        self.assertIn('String(monitorActionRunBusy.has(featureId))', script)
        self.assertIn('status.className = `agent-action-status is-${isRunBusy ? "run-busy" : isLifecycleBusy ? "lifecycle-busy" : statusClass}`;', script)
        self.assertIn("async function runMonitorActionNow", script)
        self.assertIn('status: "manual_only"', script)
        self.assertIn('return "Manual";', script)
        self.assertIn("function isActiveAgentActionStatus", script)
        self.assertIn("isActiveAgentActionStatus(action.status, action)", script)
        self.assertIn("function getAgentProposalWebMonitorManualOnly", script)
        self.assertIn("getSavedFeatureSettings(backendFeature).manualOnly", script)
        self.assertIn("agentWebMonitorTextSuggestsManualOnly", script)
        self.assertIn("proposal.executionPlan?.backendFeatureId || proposal.relatedFeatureId", script)
        self.assertIn("manualOnly,", script)
        self.assertNotIn("No background checks. Use Run now whenever you want a fresh top-five summary.", script)
        self.assertIn("function createAgentMonitorEditor", script)
        self.assertIn("agentMonitorEditForm", script)
        self.assertNotIn('subtitle.textContent = "Changes save automatically.";', script)
        self.assertNotIn('title.textContent = "Edit action";', script)
        self.assertNotIn('title.textContent = "Edit monitor";', script)
        self.assertNotIn('title.textContent = "Edit source action";', script)
        self.assertNotIn("agent-action-editor-heading", script)
        self.assertNotIn(".agent-action-editor-heading", styles)

        monitor_editor = script[
            script.index("function createAgentMonitorEditor"):
            script.index("async function saveAgentMonitorActionSettings")
        ]
        # Delivery is fixed to the in-app notification centre, so no editor
        # offers a channel picker any more.
        self.assertIn('const AGENT_ACTION_DELIVERY_CHANNEL = "portal";', script)
        self.assertNotIn("function getAgentMonitorDeliveryOptionItems", script)
        self.assertNotIn("normalizeAgentMonitorDeliveryChannel", script)
        self.assertNotIn('"Delivery",', script)
        self.assertNotIn("deliverySelect", script)
        self.assertIn("deliveryChannel: AGENT_ACTION_DELIVERY_CHANNEL,", monitor_editor)
        self.assertIn("createAgentActionEditorStatusElement(\"agent-action-editor-status\", \"p\")", monitor_editor)
        detail_card_styles = styles[
            styles.index(".agent-action-detail-card {"):
            styles.index(".agent-action-editor {")
        ]
        editor_styles = styles[
            styles.index(".agent-action-editor {"):
            styles.index(".agent-action-editor-status {")
        ]
        self.assertIn("background: transparent;", detail_card_styles)
        self.assertIn("box-shadow: none;", detail_card_styles)
        self.assertIn("border-top: 1px solid rgba(20, 28, 38, 0.065);", detail_card_styles)
        self.assertIn(".agent-action-detail-card > * + *", detail_card_styles)
        self.assertIn("background: transparent;", editor_styles)
        self.assertIn("padding: 0;", editor_styles)
        self.assertNotIn("border-top:", editor_styles)
        self.assertIn("function resizeAgentActionEditorTextarea", script)
        self.assertIn("input.scrollHeight + borderBlock", script)
        self.assertIn("input.rows = Number(options.rows || 1);", script)
        self.assertIn("scheduleAgentActionEditorTextareaResize(control.input);", script)
        self.assertIn("agent-action-editor-textarea", script)
        self.assertIn(".agent-action-editor-textarea", styles)
        self.assertIn("function createAgentActionEditorStatusElement", script)
        self.assertIn("function setAgentActionEditorFieldStatus", script)
        self.assertIn("agent-action-editor-field-status", script)
        self.assertIn("scheduleAgentLocalActionAutoSave(action, draft, form, frequency.field, { renderOnSave: true });", script)
        self.assertIn("manualRunMonth", script)
        self.assertIn("outputFolder", script)
        self.assertIn("function getAgentManualRunMonthOptions", script)
        self.assertIn("function getAgentMonthlyBatchResultText", script)
        self.assertIn("function getAgentMonthlyBatchOutputFolder", script)
        self.assertIn("Receipts/{RunMonth}/", script)
        self.assertIn('"Save folder"', script)
        self.assertIn(".agent-action-editor-field[hidden]", styles)
        self.assertIn("function isAgentProposalCustomGoogleBatchRunner", script)
        self.assertIn("function getAgentProposalPurposeTitle", script)
        self.assertIn("function getAgentPurposeTitleFromText", script)
        self.assertIn('return "Receipt collector";', script)
        self.assertIn('title.textContent = getAgentProposalPurposeTitle(proposal);', script)
        self.assertIn("action.payload.title = getAgentProposalLocalActionTitle(proposal);", script)
        self.assertNotIn("Custom task agent", script)
        self.assertIn("custom-google-batch", script)
        self.assertIn("Mailbox setup required", script)
        self.assertIn("Receipt search ready", script)
        self.assertIn("Receipt bundle ready", script)
        self.assertIn("hrefLabel: response.hrefLabel || response.href_label || \"Open PDF\"", script)
        self.assertIn("artifacts?.pdf?.url", script)
        self.assertIn("proposalType: proposal.type", script)
        self.assertIn("function shouldShowAgentManualRunMonthField", script)
        self.assertIn("function shouldAllowAgentManualRunMonthChoice", script)
        self.assertIn("the\\s+the\\s+", script)
        self.assertIn('value: "previous-month", label: "Previous month"', script)
        self.assertIn('const manualRunMonth = createAgentLocalActionEditorField(', script)
        self.assertNotIn("agent-action-editor-delivery", script)
        self.assertNotIn("agent-action-editor-delivery", styles)
        self.assertNotIn("You can change the delivery channel without recreating the action.", script)
        self.assertIn('"Run month"', script)
        self.assertIn("manualRunMonth.input.disabled = !canChooseMonth;", script)
        self.assertIn("setAgentLocalActionSettingsBusy(action, true);", script)
        self.assertIn("createAgentActionSavingIndicator", script)
        self.assertIn(".agent-action-detail-saving", styles)
        self.assertIn('setAgentLocalActionEditorStatus(editor, "Saving changes…", false, true, changedField);', script)
        self.assertIn("setAgentActionEditorFieldStatus(changedField, \"Saving\", false, true);", script)
        self.assertIn(".agent-action-editor-status-spinner", styles)
        self.assertIn(".agent-action-detail-saving.is-saving .agent-action-editor-status-spinner", styles)
        self.assertIn(".agent-action-editor-field.is-saving .agent-action-editor-select", styles)
        self.assertIn("@keyframes agent-action-editor-spin", styles)
        self.assertIn("function getAgentActionPresentationStatus", script)
        self.assertIn("function agentActionFrequencyLooksRecurring", script)
        self.assertIn("agentActionFrequencyLooksRecurring(payload.frequency)", script)
        self.assertIn('const nextLabel = paused ? "Start" : "Stop";', script)
        self.assertIn('return "Stopped";', script)
        self.assertIn("actions.filter((action) => isActiveAgentActionStatus(action.status, action))", script)
        self.assertIn('className: `${paused ? "primary-button agent-action-start-button" : "ghost-button agent-action-stop-button"} small`,', script)
        self.assertIn("function getAgentDeliveryOptionsSignature", script)
        self.assertIn("getAgentDeliveryOptionsSignature(),", script)
        self.assertIn("function getAgentCalendarSummaryDateRangeOptions", script)
        self.assertIn('{ value: "tomorrow", label: "tomorrow" }', script)
        self.assertIn('{ value: "next week", label: "next week" }', script)
        self.assertIn("preview: formatAgentTimeWindowPreview(option.value)", script)
        self.assertIn("const sameDay = sameMonth && range.start.getUTCDate() === range.end.getUTCDate();", script)
        self.assertIn("const fullCalendarMonth = sameMonth", script)
        self.assertIn("return `${startLabel} ${startMonth}`;", script)
        self.assertIn("return `${startMonth} ${range.start.getUTCFullYear()}`;", script)
        self.assertIn("function createAgentCalendarSummaryDateRangeField", script)
        self.assertIn("agent-date-range-dropdown-option-meta", script)
        self.assertIn("optionPreview.textContent = option.preview || \"\";", script)
        self.assertIn("const control = createAgentCalendarSummaryDateRangeField(label, draft[key]);", script)
        self.assertIn(".agent-date-range-dropdown-menu", styles)
        self.assertIn(".agent-date-range-dropdown-option-meta", styles)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto;", styles)
        self.assertIn("function canToggleAgentActionLifecycle", script)
        self.assertIn("async function saveAgentMonitorLifecycleStatus", script)
        self.assertIn("async function activateAgentBackendFeature", script)
        self.assertIn("async function stopAgentLocalAction", script)
        self.assertIn("async function resumeAgentLocalAction", script)
        self.assertIn("async function updateSourceActionLifecycle", script)
        self.assertIn('dataset[paused ? "agentResumeSourceAction" : "agentStopSourceAction"] = sourceActionId;', script)
        self.assertIn('dataset[paused ? "agentResumeLocalAction" : "agentStopLocalAction"] = actionId;', script)
        self.assertIn('target?.closest("[data-agent-stop-source-action]")', script)
        self.assertIn('target?.closest("[data-agent-resume-source-action]")', script)
        self.assertIn('target?.closest("[data-agent-stop-local-action]")', script)
        self.assertIn('target?.closest("[data-agent-resume-local-action]")', script)
        self.assertIn('text: lifecycleBusy ? busyText : nextLabel,', script)
        self.assertIn('hideTime ? "" : formatScheduledActionDate', script)
        self.assertIn('String(isAgentActionLifecycleBusy(action))', script)
        self.assertIn('dataset: { agentRemoveLocalAction: String(action.id || "") },', script)
        self.assertNotIn('createScheduledActionDetailRow("Watching"', script)
        self.assertNotIn("function createScheduledActionMoreDetails", script)
        self.assertNotIn('summary.textContent = "More details";', script)
        self.assertNotIn("agent-action-primary-details", script)
        self.assertNotIn("agent-action-more-details", script)
        self.assertNotIn(".agent-action-primary-details", styles)
        self.assertNotIn(".agent-action-more-details", styles)
        self.assertIn("agent-action-item-expansion", script)
        self.assertIn("grid-template-rows: 0fr", styles)
        self.assertIn("addAgentNotification({", script)
        self.assertIn('source: "web-monitor",', script)
        self.assertIn("href: getAgentResponseResultHref(response),", script)
        self.assertIn('manualOnly: true', script)
        self.assertIn('runMode: "manual"', script)
        self.assertIn('runMode: manualOnly ? "manual" : "recurring"', script)
        self.assertIn('return "manual only";', script)
        self.assertIn("state.agentAddToolMenuClosing", script)
        self.assertIn("agentAddToolMenuOpenFrame", script)
        self.assertIn("agent-tool-picker-background-blurred", script)
        self.assertIn(".agent-add-tool-backdrop", styles)
        self.assertIn("@keyframes agent-tool-menu-enter", styles)
        self.assertIn(".monitor-manual-only-toggle", styles)
        self.assertIn(".agent-action-item.is-manual_only::before", styles)
        self.assertIn(".agent-action-status.is-manual_only", styles)
        self.assertIn("SCHEDULED_ACTIONS_REFRESH_ERROR_THRESHOLD", script)
        self.assertIn("function markScheduledActionsRefreshSuccess", script)
        self.assertIn("function markScheduledActionsRefreshFailure", script)
        self.assertIn("scheduledActionsFailureCount", script)
        self.assertIn("scheduledActionsLastError", script)
        self.assertIn("userInitiated", script)
        self.assertIn("dataset.agentActionListSignature", script)
        self.assertIn("agent-action-item-expansion", script)
        self.assertIn("function createScheduledActionDetail", script)
        self.assertIn("function createAgentActionDetailActions", script)
        self.assertIn("function removeAgentProposalLocalAction", script)
        self.assertIn("function cancelScheduledAction", script)
        self.assertIn("function buildAgentWebMonitorSettings", script)
        self.assertIn("const manualOnly = requestsManualRuns || !requestedFrequency;", script)
        self.assertIn("function saveAndActivateAgentWebMonitorProposal", script)
        self.assertIn("function runAgentWebMonitorInitialCheck", script)
        self.assertIn("function createMonitorFeatureLiveAction", script)
        self.assertIn("function getAgentFeatureLiveActions", script)
        self.assertIn("function isAgentFeatureLiveAction", script)
        self.assertIn("function isAgentLocalAction", script)
        self.assertIn('source: "feature"', script)
        self.assertIn("const featureActions = getAgentFeatureLiveActions()", script)
        self.assertIn("...featureActions", script)
        self.assertIn("feature:${feature.id}", script)
        self.assertIn("function deactivateAgentProposalBackendFeature", script)
        self.assertIn("function deactivateAgentBackendFeature", script)
        self.assertIn("function getSignedInDeliveryEmail", script)
        self.assertIn("function getAgentProposalDeliveryTarget", script)
        self.assertIn("function formatAgentDeliveryTargetDetail", script)
        self.assertIn("function formatAgentDeliveryTargetSentence", script)
        self.assertIn("intervalMinutes", script)
        self.assertIn("backendFeatureId", script)
        self.assertIn("deliveryTarget", script)
        self.assertIn("deliveryLabel", script)
        local_action_detail = script[
            script.index("if (isAgentLocalAction(action))"):
            script.index("if (payload.initialRunError)")
        ]
        self.assertNotIn('createScheduledActionDetailRow("Delivery"', local_action_detail)
        self.assertNotIn('} else {\n      const primaryDetails = document.createElement("dl");', local_action_detail)
        save_monitor_action = script[
            script.index("async function saveAgentMonitorActionSettings"):
            script.index("function getAgentLocalActionProposal")
        ]
        self.assertIn("deliveryChannel: AGENT_ACTION_DELIVERY_CHANNEL,", save_monitor_action)
        self.assertIn("action.payload.deliveryChannel = deliveryChannel", save_monitor_action)
        self.assertIn("action.payload.deliveryLabel = formatAgentDeliveryTargetDetail(deliveryChannel, deliveryTarget)", save_monitor_action)
        self.assertIn("→", script)
        self.assertIn("by ${channelLabel} to ${targetLabel}", script)
        self.assertIn('action: "activate"', script)
        self.assertIn('action: "deactivate"', script)
        self.assertIn("timeoutMs: 90000", script)
        self.assertIn("data-agent-remove-local-action", script)
        self.assertIn("data-agent-cancel-scheduled-action", script)
        self.assertIn('elements.agentToolsPanel.addEventListener("click"', script)
        self.assertIn('elements.agentAddToolMenu.addEventListener("click", handleAgentWorkspaceClick)', script)
        self.assertIn("function selectScheduledAction", script)
        self.assertIn("function syncScheduledActionSelection", script)
        self.assertIn("function preserveAgentActionsScrollPosition", script)
        self.assertNotIn('scrollIntoView({ block: "nearest"', script)
        self.assertIn("agentHistoryExpanded", script)
        self.assertIn('elements.agentHistoryToggleButton.addEventListener("click"', script)
        self.assertIn("Hide action history", script)
        self.assertIn('trigger.dataset.agentScheduledActionTrigger', script)
        self.assertIn("function handleScheduledActionListClick", script)
        self.assertIn('actionList?.addEventListener("click", handleScheduledActionListClick, { capture: true })', script)
        self.assertIn("selectScheduledAction(actionId)", script)
        self.assertIn("state.selectedScheduledActionId = state.selectedScheduledActionId === normalizedActionId", script)
        self.assertIn('method: "DELETE"', script)
        self.assertIn("No active actions.", script)
        self.assertNotIn("`Action ${action.id}`", script)
        self.assertIn("SCHEDULED_ACTIONS_POLL_MS", script)
        self.assertIn("AGENT_CHAT_IDLE_MS", script)
        self.assertIn("4 * 60 * 60 * 1000", script)
        self.assertIn("function rollOverIdleAgentChatIfNeeded", script)
        self.assertIn("function startNewAgentChat", script)
        self.assertIn("function selectAgentChat", script)
        self.assertIn("function renderAgentChats", script)
        self.assertIn("function renderAgentFolders", script)
        self.assertIn("function addAgentFolder", script)
        self.assertIn("function sortAgentFolders", script)
        self.assertIn("function setAgentFolderCreateOpen", script)
        self.assertIn("function setAgentFolderFilterOpen", script)
        self.assertIn("function setAgentFolderSortOpen", script)
        self.assertIn("function syncAgentFolderDisclosureControls", script)
        self.assertIn('const VALID_AGENT_PANEL_MODES = new Set(["actions", "chats", "folders"]);', script)
        self.assertIn("AGENT_FOLDER_TYPES", script)
        self.assertIn("function setAgentPanelMode", script)
        self.assertIn('id="agentActionsPanel"', html)
        self.assertNotIn(">Action center<", html)
        self.assertNotIn('id="agentActionsTitle"', html)
        self.assertNotIn('id="agentActionsRefreshButton"', html)
        self.assertNotIn('id="agentActionsStatus"', html)
        self.assertNotIn('class="agent-actions-sync-row"', html)
        self.assertIn('id="agentPanelActionsModeButton"', html)
        self.assertIn('id="agentPanelChatsModeButton"', html)
        self.assertIn('id="agentPanelFoldersModeButton"', html)
        self.assertIn('id="agentPanelModeSwitch"', html)
        self.assertIn('role="tablist" aria-label="Agent panel mode"', html)
        self.assertIn('id="agentChatsListView"', html)
        self.assertIn('id="agentNewChatButton"', html)
        self.assertIn('id="agentChatList"', html)
        self.assertIn('id="agentFoldersListView"', html)
        self.assertIn('id="agentFolderCreateToggleButton"', html)
        self.assertIn('id="agentFolderFilterButton"', html)
        self.assertIn('id="agentFolderSortButton"', html)
        self.assertIn('aria-label="Filter folders"', html)
        self.assertIn('aria-label="Sort folders"', html)
        self.assertIn('class="agent-folder-utility-icon"', html)
        self.assertIn('id="agentFolderCreateForm"', html)
        self.assertIn('id="agentFolderCreateForm" class="agent-folder-create is-hidden" hidden', html)
        self.assertIn('id="agentFolderFilterPanel" class="agent-folder-controls is-hidden" hidden', html)
        self.assertIn('id="agentFolderSortPanel" class="agent-folder-sort-panel is-hidden" hidden', html)
        self.assertNotIn('id="agentFolderTypeSelect"', html)
        self.assertIn('id="agentFolderSearchInput"', html)
        self.assertIn('id="agentFolderSortSelect"', html)
        self.assertIn('id="agentFolderList"', html)
        self.assertIn(".agent-folder-item", styles)
        self.assertIn(".agent-folder-controls", styles)
        self.assertIn(".agent-folder-head-actions", styles)
        self.assertIn(".agent-folder-utility-button", styles)
        self.assertIn(".agent-folder-utility-icon", styles)
        self.assertIn("width: 2.35rem;", styles)
        self.assertIn(".agent-folder-create-toggle", styles)
        self.assertIn(".agent-folder-sort-panel", styles)
        self.assertIn(".agent-folder-create[hidden]", styles)
        self.assertNotIn(">Run history<", html)
        self.assertIn(">Active<", html)
        self.assertIn('id="agentHistoryToggleButton"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('id="agentCompletedActionList" class="agent-action-list" hidden', html)
        self.assertIn("overflow-anchor: none", styles)
        self.assertIn('id="agentPendingActionList"', html)
        self.assertIn('id="agentCompletedActionList"', html)
        self.assertIn('id="agentActionDetailView"', html)
        self.assertIn('id="agentAddToolButton"', html)
        self.assertIn('id="agentAddToolMenu"', html)
        add_tool_control = html[
            html.index('<div class="agent-add-tool-control">'):
            html.index('<div id="agentToolShelf"', html.index('<div class="agent-add-tool-control">'))
        ]
        self.assertIn('id="agentAddToolButton"', add_tool_control)
        self.assertNotIn('id="agentAddToolMenu"', add_tool_control)
        app_view_start = html.index('<section id="appView"')
        tool_overlay_start = html.index('<div id="agentAddToolBackdrop"')
        billing_overlay_start = html.index('<div\n      id="billingHelpPopover"')
        app_view_markup = html[app_view_start:tool_overlay_start]
        self.assertLess(app_view_start, tool_overlay_start)
        self.assertLess(tool_overlay_start, billing_overlay_start)
        self.assertNotIn('id="agentAddToolBackdrop"', app_view_markup)
        self.assertNotIn('id="agentAddToolMenu"', app_view_markup)
        self.assertIn('\n    </section>\n\n    <div id="agentAddToolBackdrop"', html)
        self.assertIn('<div id="agentAddToolBackdrop" class="agent-add-tool-backdrop is-hidden"', html)
        self.assertIn('<div id="agentAddToolMenu" class="agent-add-tool-menu is-hidden"', html)
        self.assertIn(".agent-action-error", styles)
        self.assertIn(".agent-history-toggle", styles)
        self.assertIn(".agent-history-section.is-expanded .agent-history-chevron", styles)
        self.assertIn(".agent-panel-mode-switch", styles)
        self.assertIn('.agent-panel-mode-switch[data-agent-panel-current-mode="chats"]', styles)
        self.assertIn(".agent-panel-mode-switch::before", styles)
        self.assertIn(".agent-panel-mode-button.is-active", styles)
        self.assertIn(".agent-panel-mode-button.is-guided", styles)
        self.assertIn("@keyframes agent-tab-guide", styles)
        self.assertIn(".agent-action-inline-link", styles)
        # Email is a mailbox, not a Google product: either provider satisfies it.
        self.assertIn("function isEmailConnectionReady", script)
        self.assertIn("function getConnectedEmailProvider", script)
        self.assertIn('const EMAIL_PROVIDER_OUTLOOK = "microsoft_outlook";', script)
        self.assertIn("function createOutlookConnectButton", script)
        self.assertIn("/api/oauth/microsoft/email/start", script)
        self.assertIn("function consumeEmailOAuthReturn", script)
        self.assertNotIn("function isGmailConnectionReady", script)
        self.assertIn(".calendar-oauth-alternate", styles)
        self.assertIn(".agent-action-item.is-spotlighted", styles)
        self.assertIn(".agent-action-item.is-spotlighted::after", styles)
        # One pass, not two, and the last stretch of it is a fade rather than a
        # cut with the band still lying across the card.
        self.assertIn(
            "animation: agent-action-card-shimmer 1800ms linear both;",
            styles,
        )
        self.assertIn("@keyframes agent-action-card-shimmer", styles)
        # The spotlight is the sweep alone now: no teal ring around the card and
        # no box-shadow that breathes with it.
        self.assertNotIn("agent-action-card-glow", styles)
        self.assertNotIn("box-shadow: 0 0 0 2px rgba(55, 184, 171", styles)
        # The dark theme overrides the band's gradient, so it has to carry the
        # same wide stops or the sweep shows up as a thin streak there.
        self.assertIn(
            ':root[data-theme="dark"] .agent-action-item.is-spotlighted::after',
            styles,
        )
        self.assertIn("rgba(124, 245, 233, 0.54) 44%", styles)
        self.assertNotIn("@keyframes agent-action-spotlight-dot", styles)
        self.assertNotIn("agent-action-card-border-pulse", styles)
        self.assertIn(".agent-chat-item", styles)
        self.assertIn(".agent-chat-item.is-active", styles)
        self.assertIn(".agent-action-detail-actions", styles)
        self.assertIn(".agent-action-danger-button", styles)
        self.assertIn(".agent-action-stop-button", styles)
        self.assertIn(".agent-action-item.is-running::before", styles)
        self.assertIn(".agent-action-item.is-paused::before", styles)
        self.assertIn(".agent-action-status.is-paused", styles)
        self.assertIn(":root[data-theme=\"dark\"] .agent-action-status.is-running", styles)
        self.assertIn(".agent-action-item.is-failed::before", styles)
        self.assertIn("#agentCompletedActionList .agent-action-item::before", styles)
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
        chat_workspace_message_styles = styles[
            styles.index(".app-shell.is-chat-workspace .agent-message-list {"):
            styles.index(".app-shell.is-chat-workspace .agent-tools-panel {")
        ]
        self.assertIn("padding-bottom: 30px;", chat_workspace_message_styles)
        self.assertIn("scroll-padding-bottom: 30px;", chat_workspace_message_styles)
        action_panel_styles = styles[
            styles.index(".agent-actions-panel {"):
            styles.index(".agent-tools-head {")
        ]
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto;", action_panel_styles)
        self.assertIn("align-items: stretch;", action_panel_styles)
        self.assertIn("align-content: stretch;", action_panel_styles)
        self.assertIn("overflow: hidden;", action_panel_styles)
        self.assertIn(".app-shell.is-chat-workspace .agent-actions-panel-body", styles)
        self.assertIn(".agent-actions-panel-body {\n  height: 100%;", styles)
        self.assertIn("scroll-padding-bottom: clamp(2rem, 5vh, 3.5rem);", styles)
        self.assertIn(".app-shell.is-chat-workspace .agent-tool-shelf", styles)
        self.assertIn("overflow: visible;", styles)
        self.assertNotIn(".app-shell.is-chat-workspace .agent-tool-shelf {\n  min-height: 0;\n  overflow-y: auto;", styles)
        self.assertIn("AGENT_ADD_TOOL_OPTIONS", script)
        add_tool_options = script[
            script.index("const AGENT_ADD_TOOL_OPTIONS"):
            script.index("const PLATFORM_CONNECTION_OPTIONS")
        ]
        self.assertNotIn('label: "Email"', add_tool_options)
        self.assertIn('label: "Google"', script)
        # Microsoft is a platform like any other, so it gets its own row in the
        # picker instead of hiding behind the Google email card.
        self.assertIn('label: "Microsoft"', add_tool_options)
        self.assertIn('platformId: "microsoft"', add_tool_options)
        self.assertIn("function createMicrosoftBrandLogo", script)
        self.assertIn("function openMicrosoftOAuthConnection", script)
        self.assertIn("async function requestMicrosoftEmailSignInUrl", script)
        self.assertIn('if (option.id === "microsoft") {\n    openMicrosoftOAuthConnection(option);', script)
        self.assertIn('["calendar", "email", "microsoft"].includes(option.id) ? "oauth"', script)
        # A connected Outlook mailbox is stored on the email platform, so the
        # tool shelf has to name its provider or Microsoft never shows up.
        self.assertIn("function isOutlookPlatformConnection", script)
        self.assertIn('platform: "microsoft",\n        label: "Microsoft",', script)
        self.assertIn("&& !isOutlookPlatformConnection(connection)", script)
        # Connecting an app from the tools panel is not a chat turn, so nothing
        # about it is announced in chat.
        self.assertIn("function wasPlatformConnectionStartedFromChat", script)
        self.assertIn("const startedFromChat = wasPlatformConnectionStartedFromChat();", script)
        self.assertIn(
            "if (options.startedFromChat === false && !didAgentAskForConnection(proposal)) {",
            script,
        )
        self.assertIn(
            "if (startedFromChat) {\n      pushAgentMessage(\"assistant\", message);"
            "\n      persistAgentWorkspace(\"Outlook connected through Microsoft.\");",
            script,
        )
        self.assertIn('openPlatformConnection(requirement.setupPlatformId || "calendar", { origin: "chat" });', script)
        self.assertIn("GOOGLE_CONNECTION_SCOPE_OPTIONS", script)
        self.assertIn("https://www.googleapis.com/auth/calendar.events.readonly", script)
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", script)
        self.assertIn("https://www.googleapis.com/auth/drive.readonly", script)
        self.assertIn("Read Gmail messages when an action runs.", script)
        self.assertIn("Read Google Drive files when an action runs.", script)
        self.assertNotIn('label: "Calendar events"', script)
        self.assertNotIn('label: "Email summaries"', script)
        self.assertNotIn('label: "Drive files"', script)
        self.assertNotIn("Available later", script)
        self.assertIn("PLATFORM_CONNECTION_STORAGE_UNAVAILABLE_MESSAGE", script)
        self.assertIn("platformConnectionStorageAvailable", script)
        self.assertIn("credential_storage_unavailable", script)
        self.assertIn("Storage unavailable", script)
        self.assertIn("consumeCalendarOAuthReturn(); consumeEmailOAuthReturn();", script)
        self.assertNotIn("void refreshPlatformConnections({ render: false });", script)
        self.assertIn("iconNode: createAgentAddToolLogo(option)", script)
        self.assertNotIn('icon: "↗"', script)
        self.assertIn(".platform-connection-status", styles)
        self.assertIn(".platform-connection-status[hidden]", styles)
        self.assertIn("function openCalendarOAuthConnection", script)
        # The mailbox account has to survive the client-side normalizer, or
        # every connected mailbox looks identical in the interface.
        self.assertIn("accountAddress: String(source.accountAddress || source.account_address", script)
        self.assertIn("accountLabel: String(source.accountLabel || source.account_label", script)
        # Saving one Google connection must not drop a user's other mailboxes
        # from local state, so the merge keys on connection id.
        self.assertIn("const savedIds = new Set(savedConnections.map((savedConnection) => savedConnection.id)", script)
        self.assertIn(".connected-mailbox-row", styles)
        self.assertIn("connected-mailbox-disconnect", styles)
        calendar_oauth_flow = script[
            script.index("function openCalendarOAuthConnection"):
            script.index("function openPlatformConnection(optionId, options = {})")
        ]
        self.assertIn("const usesAggregateGoogleConnection = option.id === \"calendar\";", calendar_oauth_flow)
        self.assertIn("const connectedGoogleConnections = usesAggregateGoogleConnection", calendar_oauth_flow)
        self.assertIn("? getConnectedGoogleOAuthConnections()", calendar_oauth_flow)
        self.assertIn("? connectedGoogleConnections.length > 0", calendar_oauth_flow)
        # The Email card counts the connected mailboxes; the Google card still
        # talks about Google permissions.
        self.assertIn('? (mailboxCount > 1 ? `${mailboxCount} mailboxes connected` : `${connectedEmailLabel} connected`)', calendar_oauth_flow)
        self.assertIn('"These Google permissions are connected and ready to use."', calendar_oauth_flow)
        # The Outlook button is offered whether or not a mailbox is connected,
        # because a second mailbox is added rather than swapped in.
        self.assertIn("createOutlookConnectButton(setStatus, () => storageAvailable, {", calendar_oauth_flow)
        self.assertIn("addingAnother: mailboxCount > 0,", calendar_oauth_flow)
        self.assertIn("createConnectedMailboxList(option, connectedMailboxes)", calendar_oauth_flow)
        self.assertIn("createGoogleOAuthPermissionList(option, { readOnly: isConnected });", calendar_oauth_flow)
        self.assertIn("? createGoogleConnectionDisconnectButton(option, connectedGoogleConnections)", calendar_oauth_flow)
        self.assertIn("hidePrimaryButton: isConnected && !isEmailConnection,", calendar_oauth_flow)
        self.assertIn('secondaryButtonLabel: "Cancel"', calendar_oauth_flow)
        self.assertIn("onPrimary: (isConnected && !isEmailConnection) ? null : startOAuth,", calendar_oauth_flow)
        self.assertIn('elements.authAlertIcon.classList.remove("is-spinner");', calendar_oauth_flow)
        self.assertNotIn('elements.authAlertIcon.classList.add("is-spinner");', calendar_oauth_flow)
        self.assertIn('setCalendarOAuthPrimaryButton("Opening Google", { loading: true });', calendar_oauth_flow)
        self.assertIn("if (!isConnected || isEmailConnection) {", calendar_oauth_flow)
        self.assertIn('isEmailConnection && isConnected ? "Add another Google mailbox" : primaryLabel', calendar_oauth_flow)
        self.assertIn("function getConnectedGoogleOAuthConnections", script)
        self.assertIn("function createGoogleConnectionDisconnectButton", script)
        self.assertIn("/api/oauth/google/calendar/start?scopes=", script)
        self.assertIn("/api/oauth/google/calendar/code", script)
        self.assertIn("body: { code: authorization.code, scopes: selectedScopeIds }", script)
        self.assertIn("function consumeCalendarOAuthReturn", script)
        self.assertIn("calendar_oauth", script)
        self.assertIn("Sign in with Google", script)
        self.assertIn("function createGoogleBrandLogo", script)
        self.assertIn("function createGoogleOAuthPermissionList", script)
        calendar_oauth_status_renderer = script[
            script.index("function createCalendarOAuthStatusNode"):
            script.index("function getGoogleOAuthPermissionState")
        ]
        self.assertIn('icon.classList.remove("is-spinner");', calendar_oauth_status_renderer)
        self.assertIn('dot.className = "calendar-oauth-status-dot";', calendar_oauth_status_renderer)
        self.assertNotIn('icon.classList.toggle("is-spinner"', calendar_oauth_status_renderer)
        google_scope_options = script[
            script.index("const GOOGLE_CONNECTION_SCOPE_OPTIONS"):
            script.index("const AGENT_ADD_TOOL_OPTIONS")
        ]
        self.assertIn('id: "drive"', google_scope_options)
        self.assertIn('platformId: "drive"', google_scope_options)
        self.assertIn('label: "Calendar"', google_scope_options)
        self.assertIn('label: "Email"', google_scope_options)
        self.assertIn('label: "Drive"', google_scope_options)
        self.assertIn('accessLabel: "Read-only"', google_scope_options)
        self.assertNotIn("stateLabel", google_scope_options)
        self.assertNotIn("requiredFor", google_scope_options)
        google_permissions_renderer = script[
            script.index("function getGoogleOAuthPermissionState"):
            script.index("function openCalendarOAuthConnection")
        ]
        self.assertIn("checkbox.dataset.googleScopeId = scopeOption.id;", google_permissions_renderer)
        self.assertIn("checkbox.dataset.googleScope = scopeOption.scope;", google_permissions_renderer)
        self.assertIn("const readOnly = Boolean(options.readOnly);", google_permissions_renderer)
        self.assertIn("checked: readOnly ? connected : true,", google_permissions_renderer)
        self.assertIn("disabled: readOnly,", google_permissions_renderer)
        self.assertIn('item.classList.toggle("is-readonly", Boolean(permissionState.disabled));', google_permissions_renderer)
        self.assertIn('accessLabel.className = "calendar-oauth-permission-access";', google_permissions_renderer)
        self.assertIn("accessLabel.textContent = scopeOption.accessLabel;", google_permissions_renderer)
        self.assertNotIn("permissionState.stateLabel", google_permissions_renderer)
        self.assertNotIn("calendar-oauth-permission-badge", google_permissions_renderer)
        self.assertNotIn('"Connected"', google_permissions_renderer)
        self.assertNotIn("Required", google_permissions_renderer)
        self.assertNotIn("Optional", google_permissions_renderer)
        self.assertNotIn("scope.textContent = scopeOption.scope;", google_permissions_renderer)
        self.assertNotIn('document.createElement("code")', google_permissions_renderer)
        self.assertIn("requestGoogleCalendarAuthorizationCode", script)
        self.assertIn("X-Requested-With", script)
        self.assertIn("Authorized JavaScript origin", script)
        self.assertIn("Google OAuth client ID and secret in Render", script)
        self.assertIn("Opening Google", script)
        self.assertNotIn("OAuth setup", script)
        self.assertNotIn("Open Google sign-in", script)
        self.assertIn('src="./theme-init.js', html)
        theme_script = (self.root / "portal" / "theme-init.js").read_text(encoding="utf-8")
        self.assertIn("assistyca.portal.theme", theme_script)
        self.assertIn('id="themeToggleButton"', html)
        self.assertIn('role="switch"', html)
        self.assertIn("THEME_STORAGE_KEY", script)
        self.assertIn("function toggleThemePreference", script)
        self.assertIn("handleSystemThemePreferenceChange", script)
        self.assertIn(".calendar-oauth-flow", styles)
        self.assertIn(".calendar-oauth-copy", styles)
        self.assertIn(".calendar-oauth-permissions", styles)
        self.assertIn(".calendar-oauth-permission-access", styles)
        self.assertIn(".calendar-oauth-status-dot", styles)
        self.assertIn(".calendar-oauth-button-spinner::before", styles)
        self.assertNotIn(".calendar-oauth-status-icon.is-spinner::before", styles)
        self.assertNotIn(".calendar-oauth-permission-badge", styles)
        self.assertNotIn(".calendar-oauth-permission code", styles)
        self.assertIn("--calendar-oauth-column-offset", styles)
        self.assertIn(".calendar-oauth-status", styles)
        calendar_oauth_dark_styles = styles[
            styles.index(':root[data-theme="dark"] .calendar-oauth-permissions {'):
            styles.index(':root[data-theme="dark"] .agent-composer textarea {')
        ]
        self.assertIn("background: transparent;", calendar_oauth_dark_styles)
        self.assertIn("border-color: var(--line-strong);", calendar_oauth_dark_styles)
        self.assertNotIn(".calendar-oauth-steps", styles)
        self.assertNotIn(".calendar-oauth-provider", styles)
        self.assertIn(".calendar-oauth-button-logo", styles)
        self.assertIn(":root[data-theme=\"dark\"]", styles)
        self.assertIn(":root[data-theme=\"dark\"] .settings-switcher .subtab-button.is-active", styles)
        self.assertIn(":root[data-theme=\"dark\"] .agent-action-detail-card,\n:root[data-theme=\"dark\"] .agent-action-editor", styles)
        self.assertIn(":root[data-theme=\"dark\"] .agent-action-editor-input,\n:root[data-theme=\"dark\"] .agent-action-editor-select", styles)
        self.assertIn(".theme-switch", styles)
        self.assertIn("background: #ffffff;", styles)
        self.assertIn("background: #131314;", styles)
        self.assertIn("grid-template-columns: minmax(5.5rem, 0.62fr) minmax(13.5rem, 1.38fr);", styles)
        self.assertIn("rgba(66, 133, 244, 0.18)", styles)
        self.assertIn("rgba(138, 180, 248, 0.26)", styles)
        self.assertIn(".auth-alert-icon svg", styles)
        self.assertIn("function createAgentAddToolLogo", script)
        self.assertIn("function createAgentToolIconOption", script)
        self.assertIn("function createPlatformConnectionIconOption", script)
        self.assertIn('icon: "whatsapp"', script)
        self.assertIn('icon: "web-monitor"', script)
        self.assertIn("icon.append(createAgentAddToolLogo(createAgentToolIconOption(feature)))", script)
        self.assertIn("icon.append(createAgentAddToolLogo(createPlatformConnectionIconOption(connection)))", script)
        self.assertNotIn("icon.textContent = label.slice(0, 1).toUpperCase();", script)
        self.assertIn('icon: "telegram"', script)
        self.assertIn("function renderAgentAddToolMenu", script)
        self.assertIn("data-agent-add-tool", script)
        self.assertIn("function openAgentToolDetails", script)
        self.assertIn("function getAgentToolDetailsView", script)
        self.assertIn("function shouldRenderAgentToolShelfFeature", script)
        self.assertIn("return Boolean(feature && !isMonitorFeature(feature));", script)
        self.assertIn("if (!shouldRenderAgentToolShelfFeature(feature))", script)
        self.assertIn("ACTION_ONLY_PLATFORM_CONNECTION_IDS", script)
        action_only_connection_ids = script[
            script.index("const ACTION_ONLY_PLATFORM_CONNECTION_IDS"):
            script.index("function shouldRenderAgentToolShelfConnection")
        ]
        self.assertIn('"email"', action_only_connection_ids)
        self.assertIn('"drive"', action_only_connection_ids)
        self.assertIn("GOOGLE_TOOL_PLATFORM_CONNECTION_IDS", script)
        self.assertIn("function shouldRenderAgentToolShelfConnection", script)
        self.assertIn("function getAgentToolShelfConnections", script)
        self.assertIn("function isAgentToolsInitialLoading", script)
        self.assertIn("featureActivationInitialLoadPending", script)
        self.assertIn("platformConnectionsInitialLoadPending", script)
        self.assertIn("function sortFeaturesByDisplayOrder", script)
        self.assertIn("function sortAgentToolShelfConnections", script)
        self.assertIn('target.replaceChildren(createAgentLoadingRow("Loading tools…"));', script)
        self.assertIn("const visibleConnections = sortAgentToolShelfConnections(getAgentToolShelfConnections(connections));", script)
        self.assertIn("if (!visibleFeatures.length && !visibleConnections.length)", script)
        self.assertIn("item.dataset.agentToolFeatureId = feature.id;", script)
        self.assertIn('const toolButton = target?.closest("[data-agent-tool-feature-id]");', script)
        self.assertIn('openFeatureStudio(feature.id, getAgentToolDetailsView(feature));', script)
        self.assertNotIn("dataset.agentToolPrompt", script)
        self.assertNotIn("Help me use ${getAgentToolLabel(feature)}", script)
        add_tool_menu_styles = styles[
            styles.index(".agent-add-tool-menu {"):
            styles.index(".agent-add-tool-option {")
        ]
        self.assertIn("position: fixed;", add_tool_menu_styles)
        self.assertIn("z-index: 30;", add_tool_menu_styles)
        self.assertIn("top: 50%;", add_tool_menu_styles)
        self.assertIn("left: 50%;", add_tool_menu_styles)
        self.assertIn("transform: translate(-50%, -50%);", add_tool_menu_styles)
        self.assertIn("opacity: 0;", add_tool_menu_styles)
        self.assertIn("agent-tool-menu-enter", styles)
        self.assertIn(".app-shell.agent-tool-picker-background-blurred", styles)
        self.assertIn("filter: blur(8px);", styles)
        self.assertIn("overflow-y: auto;", add_tool_menu_styles)
        dark_add_tool_menu_start = styles.index(':root[data-theme="dark"] .agent-add-tool-menu {')
        dark_add_tool_menu_styles = styles[
            dark_add_tool_menu_start:
            styles.index(':root[data-theme="dark"] .agent-action-detail-card,', dark_add_tool_menu_start)
        ]
        self.assertIn("background:", dark_add_tool_menu_styles)
        self.assertIn("rgba(22, 33, 42, 0.98)", dark_add_tool_menu_styles)
        self.assertIn(':root[data-theme="dark"] .agent-add-tool-option .agent-tool-copy span', styles)
        self.assertIn(':root[data-theme="dark"] .agent-add-tool-option:hover .agent-add-tool-icon', styles)
        self.assertIn(".agent-add-tool-icon svg", styles)
        self.assertIn(".agent-tool-icon svg", styles)
        self.assertIn(".agent-loading-row", styles)
        self.assertIn(".agent-loading-spinner", styles)
        self.assertNotIn("nextIndex < 3 && !/\\b(calendar|schedule|agenda|appointments?)\\b/i.test", script)

    def test_month_based_batch_actions_default_to_a_manual_monthly_run(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # A "pull my August receipts" request is a one-off. It must not become a
        # live daily action just because no cadence was ever stated.
        self.assertIn("function agentTextSuggestsOneTimeRun", script)
        self.assertIn("just once|only once|one[-\\s]?time|one[-\\s]?off|run once|single run", script)
        self.assertIn("manualTexts.some(agentWebMonitorTextSuggestsManualOnly) || manualTexts.some(agentTextSuggestsOneTimeRun)", script)
        self.assertIn(
            "return ![...cadenceFields, proposal?.requestText].some((text) => Boolean(extractAgentFrequencyField(text)));",
            script,
        )

        # When it is recurring, the cadence is monthly, not the generic daily default.
        self.assertIn(
            'const fallbackFrequency = agentContextSuggestsMonthlyBatchTask(proposal) ? "monthly" : "daily";',
            script,
        )
        self.assertIn("|| fallbackFrequency,", script)
        self.assertIn("  return fallbackFrequency;\n}", script)

    def test_every_scheduled_action_names_the_date_and_hour_it_runs(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")
        server_source = (self.root / "packages" / "infrastructure" / "portal_auth" / "server.py").read_text(encoding="utf-8")
        monitor_source = (self.root / "packages" / "tools" / "scheduled_monitor" / "monitor.py").read_text(encoding="utf-8")

        # A cadence on its own never says when a task runs, so each editor asks
        # for the date and the hour and answers with the moment it next fires.
        self.assertEqual(script.count('createAgentLocalActionEditorField("Run date", draft.runDate, { inputType: "date" })'), 3)
        self.assertEqual(script.count('createAgentLocalActionEditorField("Run time", draft.runTime, { inputType: "time" })'), 3)
        self.assertIn('input.type = options.inputType || "text";', script)
        self.assertIn("function resolveAgentActionNextRunAt", script)
        self.assertIn("function getAgentActionDefaultRunDate", script)
        self.assertIn("`Next run ${formatScheduledActionDate(nextRunAt, getWorkspaceTimeZone())}`", script)
        self.assertIn(".agent-action-editor-field-row", styles)
        self.assertIn(".agent-action-editor-note", styles)

        # An approved action carries the schedule, so the card can show it
        # before anyone opens the editor.
        self.assertIn("const runSchedule = getAgentProposalRunSchedule(proposal, manualOnly);", script)
        self.assertIn("      nextRunAt: runSchedule.nextRunAt,", script)
        self.assertIn("  action.payload.nextRunAt = runSchedule.nextRunAt;", script)

        # A source check and a monitor keep their schedule on the server.
        self.assertIn("body: { intervalMinutes: selected.intervalMinutes, nextRunAt },", script)
        self.assertIn("next_run_at=next_run_at,", server_source)
        self.assertIn("...getAgentMonitorEditorScheduleSettings(draft, editor.frequencySelect?.value),", script)
        self.assertIn("def normalize_schedule_start_at", monitor_source)
        self.assertIn("        if start_at > current_time:\n            return start_at", monitor_source)

    def test_saved_chats_can_actually_be_deleted(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # The trash button renders for every chat that is not the open one, so
        # the delete guard must use that same test. Refusing on chat.status too
        # left a visible button that silently did nothing.
        self.assertIn("if (!chat || chat.id === agent.activeChatId) {", script)
        self.assertNotIn('chat.id === agent.activeChatId || chat.status === "active"', script)

        # status is re-anchored to activeChatId so the two cannot drift apart.
        self.assertIn('chat.status = chat.id === activeChat?.id ? "active" : "historical";', script)

    def test_two_actions_never_share_the_same_name(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # Names are derived from the request ("Receipt collector"), so two
        # similar requests used to produce two identically named cards. Every
        # rendered list now runs through the numbering pass, and the title
        # lookup reads the numbered name instead of the derived one.
        self.assertIn("function refreshScheduledActionUniqueTitles", script)
        self.assertIn("function getScheduledActionBaseTitle", script)
        self.assertIn("return refreshScheduledActionUniqueTitles([", script)
        self.assertIn(
            "return scheduledActionUniqueTitles.get(String(action?.id ?? \"\")) "
            "|| getScheduledActionBaseTitle(action);",
            script,
        )

        # The oldest action keeps the plain name and later ones become "#2",
        # "#3", so an existing card is never renamed when a new one arrives.
        self.assertIn("(getScheduledActionCreatedTime(left.action) - getScheduledActionCreatedTime(right.action))", script)
        self.assertIn("title = `${rootTitle} #${suffix}`;", script)

        # A name that already ends in "#2" is numbered from its root, so the
        # next duplicate is "#3" rather than "Receipt collector #2 #2".
        self.assertIn('const rootTitle = baseTitle.replace(/\\s*#\\d+$/, "").trim() || baseTitle;', script)

    def test_the_chat_carries_out_a_delete_instead_of_agreeing_to_one(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # Confirming a removal in chat used to change nothing at all: the agent
        # could only talk, so the actions stayed in the panel. A command now
        # resolves to real actions and runs the same removal the panel runs.
        self.assertIn('if (outcome === "action_command" && pushAgentActionCommandPrompt(turn)) {', script)
        self.assertIn("function pushAgentActionCommandPrompt", script)
        self.assertIn("function runAgentActionCommand", script)
        self.assertIn("function findActiveAgentActionsByName", script)
        self.assertIn("removeAgentProposalLocalAction(actionId)", script)
        self.assertIn("cancelScheduledAction(actionId)", script)
        self.assertIn("removeSourceAction(sourceActionId)", script)

        # The application owns the confirmation, so the buttons are the only
        # thing that carries the change out.
        self.assertIn('createAgentAction("run-action-command"', script)
        self.assertIn('createAgentAction("cancel-action-command"', script)
        self.assertIn('if (action === "run-action-command") {', script)

        # Nothing is claimed before it happens: an unknown name, an action
        # already in that state, and a failure each get their own answer.
        self.assertIn("I couldn’t find ${formatAgentActionNameList(wanted)} among your actions", script)
        self.assertIn("function canRunAgentActionCommand", script)
        self.assertIn("function describeSkippedAgentActionCommand", script)
        self.assertIn("already ${state}", script)
        self.assertIn("wording.failed", script)

    def test_receipts_example_names_last_month(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # The example must not name a fixed month.
        self.assertNotIn("Pull all my receipts from August", html)
        self.assertIn('id="agentReceiptsQuickAction"', html)
        self.assertIn("function updateAgentReceiptsQuickAction", script)
        self.assertIn("function formatAgentPreviousMonth", script)
        self.assertIn("shiftAgentMonth(getAgentWorkspaceMonthDate(), -1)", script)

        # The visible label is short ("July 26") but the prompt spells the year
        # out, because both month parsers assume the current year otherwise -
        # "December 26" typed in January would resolve to the wrong year.
        self.assertIn('month: "long", year: "2-digit"', script)
        self.assertIn('month: "long", year: "numeric"', script)
        self.assertIn("updateAgentReceiptsQuickAction();", script)

    def test_a_running_manual_action_shows_that_it_is_running(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # The action list only re-renders when its signature changes, so a run
        # that is missing from the signature leaves the card untouched: the
        # button keeps saying "Run now" and clicking it looks like nothing
        # happened, even while the run is in flight.
        self.assertIn("function isAgentLocalActionRunBusy", script)
        self.assertIn("    String(isAgentLocalActionRunBusy(action)),\n  ]);", script)
        self.assertIn("const isRunBusy = isAgentLocalActionRunBusy(action)", script)
        self.assertIn("const runBusy = isAgentLocalActionRunBusy(action);", script)

    def test_action_results_use_notification_center(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="notificationCenterButton"', html)
        self.assertIn('id="notificationCenterPopover"', html)
        self.assertIn('id="notificationCenterList"', html)
        self.assertIn('id="notificationCenterBadge"', html)
        self.assertIn("function addAgentNotification", script)
        self.assertIn("function renderNotificationCenter", script)
        self.assertIn("notifyScheduledActionTransitions", script)
        self.assertIn('title: "Meeting summary ready"', script)
        self.assertIn('title: "Email digest ready"', script)
        self.assertIn('source: "web-monitor"', script)
        self.assertIn('source: "whatsapp-reengagement"', script)
        self.assertIn("getReengagementDemoAlertTitle(response.run)", script)
        self.assertIn('{ value: "portal", label: "Notifications" }', script)
        self.assertIn('return "the notification center";', script)
        self.assertIn(".notification-center-popover", styles)
        self.assertIn(".notification-center-item.is-unread", styles)
        self.assertIn("notification-center-enter", styles)

    def test_notifications_are_grouped_by_day_with_the_time_on_each_row(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        # The day is said once, in a heading above the rows it covers.
        self.assertIn("function groupNotificationsByDay", script)
        self.assertIn("function renderNotificationCenterDayGroup", script)
        self.assertIn("function formatAgentNotificationDayHeading", script)
        self.assertIn('return "Today";', script)
        self.assertIn('return "Yesterday";', script)
        # The heading stays at the top of the list while its rows scroll past.
        self.assertIn(".notification-center-day-heading", styles)
        self.assertIn("position: sticky;", styles)
        # Each row carries only the clock time, in its top right corner.
        self.assertIn("function formatAgentNotificationTime", script)
        self.assertIn('time.className = "notification-center-item-time";', script)
        self.assertIn(".notification-center-item-time", styles)

    def test_notification_feed_pages_instead_of_capping(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("const NOTIFICATIONS_PAGE_SIZE = 20;", script)
        self.assertIn("function loadOlderNotifications", script)
        self.assertIn("function maybeLoadMoreNotifications", script)
        self.assertIn("function getOldestServerNotificationId", script)
        # Scrolling near the end asks for the next page rather than stopping at
        # a fixed number of notifications.
        self.assertIn("params.set(\"beforeId\", String(Number(beforeId)));", script)
        self.assertIn('id="notificationCenterStatus"', html)
        self.assertIn(".notification-center-status", styles)
        # Nothing left in the browser trims the feed to a fixed size, and the
        # portal never asks the server to remove a notification.
        self.assertNotIn("AGENT_MAX_NOTIFICATIONS", script)
        self.assertIn("const AGENT_PERSISTED_NOTIFICATIONS = 100;", script)
        self.assertNotIn("/api/notifications/delete", script)
        for line in script.splitlines():
            if "/api/notifications" in line:
                self.assertNotIn("DELETE", line)

    def test_notifications_can_be_searched(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="notificationCenterSearch"', html)
        self.assertIn('id="notificationCenterSearchClear"', html)
        self.assertIn("function setNotificationSearchQuery", script)
        self.assertIn("function runNotificationSearch", script)
        self.assertIn("function getNotificationSearchMatches", script)
        # Local matches render as the owner types; the server fills in the older
        # ones a moment later.
        self.assertIn("function notificationMatchesSearch", script)
        self.assertIn('params.set("search", search);', script)
        self.assertIn("const NOTIFICATION_SEARCH_DEBOUNCE_MS = 180;", script)
        self.assertIn(".notification-center-search-input", styles)

    def test_agent_proposal_changes_use_contextual_structured_revision(self) -> None:
        html = (self.root / "portal" / "index.html").read_text(encoding="utf-8")
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function applyAgentScheduledMessageRevision", script)
        self.assertIn("getAgentDefaultScheduledMessageText(details.timeLocal)", script)
        self.assertIn("patch.preserveMessageText !== true", script)
        self.assertIn("proposal.revision", script)
        self.assertIn("proposalRevision", script)
        self.assertIn('apiRequest("/api/agent/turn"', script)
        self.assertIn("styles.css?v=156", html)
        self.assertIn("app.js?v=193", html)
        self.assertIn("https://accounts.google.com/gsi/client", html)
        self.assertIn('data-google-identity-services="true"', html)
        self.assertIn('id="featureActivationResult"', html)
        self.assertIn('id="featureActivationResultIcon"', html)
        self.assertIn('id="featureActivationResultText"', html)
        self.assertIn("function updateFeatureActivationResult", script)
        self.assertIn('text: refreshOnly ? "Refreshing..." : "Saving..."', script)
        self.assertIn('icon: isWarning ? "x" : "check"', script)
        self.assertIn("function createFeatureActivationResultIcon", script)
        self.assertIn('createSvgElement("svg"', script)
        self.assertIn("featureActivationResultIcon.replaceChildren", script)
        self.assertIn('webhookSuccess ? "Refresh succeeded" : "Save succeeded"', script)
        self.assertIn("getFeatureWhatsAppHealth(feature)", script)
        self.assertNotIn("getSelectedFeatureWhatsAppMetadata", script)
        self.assertIn(".feature-activation-result {", styles)
        self.assertIn(".feature-activation-result-icon {", styles)
        self.assertIn(".feature-activation-result-icon svg {", styles)
        agent_turn_request = script[
            script.index('const turn = await apiRequest("/api/agent/turn"'):
            script.index('await applyAgentTurnResponse(turn, cleanText);')
        ]
        self.assertIn("timeoutMs: 90000", agent_turn_request)
        self.assertIn("agentTurnBusy = true", script)
        self.assertIn('pushAgentMessage("assistant", message, {', script)
        self.assertIn('technical: getAgentErrorTechnicalInfo(error)', script)
        self.assertIn("I couldn’t get a response right now", script)
        self.assertIn('wrap="soft"', html)
        composer_markup = html[
            html.index('<form id="agentComposerForm"'):
            html.index('<button id="agentComposerButton"', html.index('<form id="agentComposerForm"'))
        ]
        self.assertIn('id="agentAttachSourceMenu"', composer_markup)
        self.assertIn('aria-haspopup="menu"', composer_markup)
        self.assertIn('<span aria-hidden="true">+</span>', composer_markup)
        self.assertIn('id="agentAttachSourceFileOption"', composer_markup)
        self.assertIn('id="agentAttachSourceUrlOption"', composer_markup)
        self.assertIn('id="agentSourceUrlInput"', composer_markup)
        self.assertIn("agent-attach-source-option-icon-file", composer_markup)
        self.assertIn("agent-attach-source-option-icon-url", composer_markup)
        self.assertIn("<svg viewBox=", composer_markup)
        self.assertIn(">www</span>", composer_markup)
        self.assertNotIn('aria-label="Attach a file as a recurring source">Attach file</button>', composer_markup)
        self.assertIn("function normalizeAgentComposerPastedText", script)
        self.assertIn("function handleAgentComposerPaste", script)
        self.assertIn("const AGENT_COMPOSER_MAX_LINES = 5;", script)
        self.assertIn("function resizeAgentComposerInput", script)
        self.assertIn("function scheduleAgentComposerInputResize", script)
        self.assertIn("function isAgentComposerCaretAtEnd", script)
        self.assertIn("function scrollAgentComposerInputToBottom", script)
        self.assertIn("scrollToBottom: isAgentComposerCaretAtEnd(event.currentTarget)", script)
        self.assertIn("input.scrollTop = input.scrollHeight", script)
        self.assertNotIn('elements.agentComposerInput.addEventListener("input", resizeAgentComposerInput);', script)
        self.assertIn('elements.agentComposerInput.addEventListener("paste", handleAgentComposerPaste);', script)
        self.assertIn("function setAgentAttachSourceMenuOpen", script)
        self.assertIn("function normalizeAgentSourceUrl", script)
        self.assertIn("function attachAgentSourceUrl", script)
        self.assertIn('agentSourceAttachment?.sourceType === "url"', script)
        self.assertIn("config.owner_wa_id || config.display_phone_number", script)
        self.assertIn("elements.agentAttachSourceFileOption.addEventListener", script)
        self.assertIn("elements.agentAttachSourceUrlOption.addEventListener", script)
        self.assertIn("elements.agentSourceUrlAttachButton.addEventListener", script)
        self.assertIn('replace(/[ \\t]*\\n+[ \\t]*/g, " ")', script)
        self.assertIn("white-space: pre-wrap;", styles)
        self.assertIn("overflow-x: hidden;", styles)
        self.assertIn("overflow-y: hidden;", styles)
        self.assertIn(".agent-composer.is-multiline", styles)
        self.assertIn(".agent-composer.is-multiline .agent-attach-source-control", styles)
        self.assertIn(".agent-composer.is-scrollable textarea", styles)
        self.assertIn(".agent-attach-source-control", styles)
        self.assertIn(".agent-attach-source-menu", styles)
        self.assertIn('.agent-attach-source-menu[data-mode="url"]', styles)
        self.assertIn(".agent-source-url-row", styles)
        self.assertIn(".field-error[hidden]", styles)
        self.assertIn("#agentComposerButton", styles)
        self.assertIn(".agent-attach-source-option-icon", styles)
        self.assertIn(".agent-attach-source-option-icon svg", styles)
        self.assertIn(".agent-attach-source-option-icon-url", styles)
        self.assertNotIn("agent-attach-source-button.is-open span {\n  transform: translateY(-0.08rem) rotate(45deg);", styles)
        self.assertIn('kind: "thinking"', script)
        self.assertIn(".agent-thinking-dots", styles)
        self.assertIn("function openAgentErrorHelp", script)
        self.assertIn("function createAgentErrorHelpBody", script)
        self.assertIn("getAgentErrorTechnicalInfo(error)", script)
        self.assertIn('"client_timeout"', script)
        self.assertIn('agent_billing_required', script)
        self.assertIn('agent_quota_unclear', script)
        self.assertIn('providerCode', script)
        self.assertIn('credit_balance_exhausted', script)
        self.assertIn('agent_configuration_error', script)
        self.assertIn('upstreamStatus', script)
        self.assertIn('eyebrow: "Technical details"', script)
        self.assertIn("agent-message-help-icon", script)
        self.assertIn("agent-message-help-button", script)
        self.assertIn("Show technical details for this failure", script)
        self.assertIn("/api/agent/turn", script)
        self.assertIn(".agent-error-help-details", styles)
        self.assertIn(".agent-message-help-button", styles)
        self.assertIn("function pushAgentApprovalPrompt(proposal, reply = \"\")", script)
        self.assertIn("function pushAgentProposalNextStep(proposal, reply = \"\")", script)
        self.assertIn("function findAgentProposalReadyAfterConnection", script)
        self.assertIn("function resumeAgentProposalAfterConnectedPlatforms", script)
        self.assertIn("function getAgentDefaultProposalQuestionText", script)
        self.assertIn("function getAgentDefaultApprovalPromptText", script)
        self.assertIn("function isAgentConnectionSetupReply", script)
        self.assertIn("requirement.actionLabel || \"Open setup\"", script)
        self.assertIn("pushAgentRequiredConnectionSetupPrompt(proposal, requirement, reply)", script)
        self.assertIn('const deliveryChannel = getAgentProposalDeliveryChannel(proposal);', script)
        self.assertIn('const nextStepReply = deliveryChannel === "portal" && isAgentDeliveryQuestionText(reply)', script)
        self.assertIn("reply || getAgentDefaultProposalQuestionText(proposal, missingIndex)", script)
        self.assertIn("pushAgentApprovalPrompt(proposal, nextStepReply || getAgentDefaultApprovalPromptText(proposal))", script)
        self.assertIn("Should I pull this just once for the requested month", script)
        self.assertIn("resumeAgentProposalAfterConnectedPlatforms(connectedPlatforms", script)
        self.assertIn('resumeAgentProposalAfterConnectedPlatforms(["google"]', script)
        self.assertIn("approvalPendingAfterConnection: true", script)
        self.assertIn("function shouldAttachAgentApprovalActions", script)
        self.assertIn("function getAgentApprovalPromptActions", script)
        self.assertIn("asksToConfirmSetup && offersChangePath", script)
        self.assertIn("if (kind === \"approval\" && proposal)", script)
        self.assertIn("return getAgentApprovalPromptActions(proposal, message.text);", script)
        self.assertIn("function pushAgentActionIntentMessage", script)
        self.assertIn("function startAgentProposalApproval", script)
        self.assertIn('agentTurnProgressText = "Setting it up"', script)
        self.assertIn("function pushAgentProposalResult", script)
        self.assertIn("function isGoogleDriveConnectionReady", script)
        self.assertIn("function getAgentProposalRequiredConnection", script)
        self.assertIn("function ensureAgentProposalRequiredConnectionReady", script)
        self.assertIn('proposal.type === "custom" && agentTextSuggestsGoogleWorkspaceBatch(contextText)', script)
        self.assertIn('"google-workspace"', script)
        self.assertIn("No API key is needed.", script)
        self.assertIn("openPlatformConnection(requirement.setupPlatformId || \"calendar\", { origin: \"chat\" })", script)
        self.assertIn("gmail: {", script)
        self.assertIn("drive: {", script)
        self.assertNotIn('proposal.type === "web-monitor" && agentTextSuggestsGoogleWorkspaceBatch', script)
        approve_agent = script[
            script.index("async function approveAgentProposal"):
            script.index("function requestAgentProposalChanges")
        ]
        self.assertIn("if (!ensureAgentProposalRequiredConnectionReady(proposal))", approve_agent)
        self.assertLess(
            approve_agent.index("if (!ensureAgentProposalRequiredConnectionReady(proposal))"),
            approve_agent.index("let scheduledAction = null"),
        )
        approval_turn = script[
            script.index('if (outcome === "approve_proposal" && activeProposal && !activeProposal.approved)'):
            script.index('if (outcome === "approve_proposal")')
        ]
        self.assertNotIn("hasCurrentApprovalPrompt", approval_turn)
        self.assertIn('agentTurnProgressText = "Setting it up"', approval_turn)
        self.assertIn("renderApp({ preserveStatus: true });", approval_turn)
        self.assertIn("await approveAgentProposal(activeProposal.id, currentRevision);", approval_turn)
        self.assertIn('return "Set it up please";', script)
        self.assertIn('pushAgentMessage("user", text, {', script)
        self.assertIn("function getAgentProposalLocalActions", script)
        self.assertIn("function getRenderableAgentActions", script)
        self.assertIn("const proposalActions = getAgentProposalLocalActions();", script)
        self.assertIn("const featureActions = getAgentFeatureLiveActions()", script)
        self.assertIn("...proposalActions", script)
        self.assertIn("const actions = getRenderableAgentActions();", script)
        self.assertIn("isAgentProposalLocalAction(action)", script)
        self.assertIn("isAgentLocalAction(action)", script)
        remove_local_action = script[
            script.index("async function removeAgentProposalLocalAction"):
            script.index("async function cancelScheduledAction")
        ]
        self.assertIn("const featureId = getAgentFeatureIdFromLocalActionId(actionId);", remove_local_action)
        self.assertIn("await deactivateAgentBackendFeature(featureId)", remove_local_action)
        self.assertIn("const proposal = getAgentWorkspace().proposals.find", remove_local_action)
        self.assertIn("const agent = getAgentWorkspace();\n  agent.proposals = agent.proposals.filter", remove_local_action)
        self.assertLess(
            remove_local_action.index("await deactivateAgentProposalBackendFeature(proposal)"),
            remove_local_action.index("const agent = getAgentWorkspace();"),
        )
        self.assertNotIn("Approved from chat", script)
        self.assertNotIn("This helper was created from the approved chat plan", script)
        self.assertIn("function resolveAgentMessageActions", script)
        self.assertIn("function resolvePendingAgentMessageActions", script)
        self.assertIn("function areAgentMessageActionsResolved", script)
        self.assertIn("AGENT_PROPOSAL_FIELD_SCHEMAS", script)
        # Someone with Gmail and Outlook both connected answers the mailbox
        # question with "both", so it is a chip rather than a typed reply, and
        # the answer has to record both providers instead of only the first.
        self.assertIn(
            'actions: ["Gmail", "Outlook", { label: "Both", value: "Gmail and Outlook" }],',
            script,
        )
        self.assertIn('fields.mailbox = "Gmail and Outlook";', script)
        self.assertIn("(namesGmail && namesOutlook)", script)
        self.assertIn("function getAgentNextMissingQuestionIndex", script)
        self.assertIn('question: "How often should this happen?",\n      actions: ["Daily", "Weekly", "Monthly"],', script)
        self.assertIn("function getAgentQuestionFieldIndexFromText", script)
        self.assertIn("function getAgentQuestionActionFieldIndex", script)
        self.assertIn("Prefer the wording when metadata and visible text disagree", script)
        self.assertIn("function agentContextSuggestsMonthlyBatchTask", script)
        self.assertIn("function isAgentFrequencyQuestionText", script)
        self.assertIn("function isAgentMonthlyBatchCadenceConfirmationText", script)
        self.assertIn("function getAgentContextualQuestionActions", script)
        self.assertIn("function getAgentMonthlyBatchScheduleActions", script)
        self.assertIn("function getAgentDisplayMessageText", script)
        self.assertIn("function renderAgentMessageBubbleContent", script)
        self.assertIn("function getAgentProposalResultActionId", script)
        self.assertIn("function appendAgentResultActionLink", script)
        self.assertIn("function showAgentActionInPanel", script)
        self.assertIn("function handleAgentActionReferenceClick", script)
        self.assertIn('const message = "Action created.";', script)
        self.assertIn("linkButton.dataset.agentShowAction = actionId", script)
        self.assertIn("setAgentPanelMode(\"actions\")", script)
        self.assertIn("agentActionSpotlightId = normalizedActionId", script)
        self.assertIn('state.selectedScheduledActionId = "";', script)
        self.assertNotIn("state.selectedScheduledActionId = normalizedActionId", script)
        self.assertIn("item.scrollIntoView({", script)
        self.assertIn('block: "center"', script)
        self.assertIn("showActionLink: true", script)
        self.assertIn("function filterAgentQuestionActions", script)
        self.assertIn("return normalizedActions.length > 1 ? normalizedActions : [];", script)
        self.assertIn('createAgentAction("choose", "Yes, monthly"', script)
        self.assertIn('"Every month"', script)
        self.assertIn("just once for the requested month", script)
        self.assertIn("monthly, at the beginning of each month for the previous month", script)
        self.assertNotIn("function getAgentMonthlyBatchQuestionText", script)
        self.assertNotIn("Should I pull ${oneTimeTarget} once", script)
        self.assertNotIn("set this up so each month pulls the previous month's ${objectLabel}", script)
        self.assertIn('field?.key !== "frequency"', script)
        self.assertIn("isAgentRunModeQuestionText(questionText)", script)
        self.assertIn("bubble.textContent = displayText;", script)
        self.assertIn("getAgentQuestionActions(proposal, actionIndex, messageText, field?.key || requestedFieldKey)", script)
        self.assertIn("function getAgentRenderableMessageActions", script)
        self.assertIn("const questionText = getAgentDisplayMessageText(message, kind, proposal);", script)
        self.assertIn("getAgentQuestionActions(proposal, questionIndex, questionText, questionFieldKey)", script)
        self.assertIn("getAgentQuestionActions(proposal, questionIndex, message.text)", script)
        self.assertIn("const actions = getAgentRenderableMessageActions(message, kind, proposal);", script)
        self.assertIn("getAgentRenderableMessageActions(message, kind, proposal).map", script)
        self.assertNotIn("const rawActions = kind === \"connection-setup\"", script)
        self.assertIn("&& /\\b(calendar|agenda|appointments?)\\b/i.test(requestText)", script)
        self.assertNotIn("&& /\\b(calendar|schedule|agenda|appointments?)\\b/i.test(requestText)", script)
        self.assertIn("function applyAgentFieldProposalRevision", script)
        self.assertIn("fields: proposal.fields", script)
        self.assertIn('outcome === "proposal" || (outcome === "question" && turn?.proposalType)', script)
        self.assertIn("button.dataset.agentActionMessage = message.id", script)
        self.assertIn("button.disabled = Boolean(isStaleApproval || actionsResolved || agentTurnBusy)", script)
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
        self.assertIn(
            'apiRequest("/api/scheduled-actions", {\n'
            '    method: "POST",\n',
            script,
        )
        # Auth rides on the httpOnly session cookie, so no request builds an
        # Authorization header and no token is readable from JavaScript.
        self.assertNotIn("getSessionAuthHeaders", script)
        self.assertNotIn("Authorization: `Bearer", script)
        handler = script[
            script.index("async function handleAgentUserText"):
            script.index("function handleAgentComposerSubmit")
        ]
        self.assertIn('apiRequest("/api/agent/turn"', handler)
        self.assertIn('resolvePendingAgentMessageActions("user-message")', handler)
        self.assertNotIn("createAgentProposalFromRequest(cleanText)", handler)

    def test_the_action_created_reply_grows_out_of_the_thinking_bubble(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")

        # "Action created." used to appear with only a fade, because approving
        # drew it while the turn was still busy. The morph is read from the
        # thinking bubble that is still on screen, and only on the first draw
        # of a message, so that early draw used up its entrance.
        approve = script[
            script.index("async function approveAgentProposal"):
            script.index("function requestAgentProposalChanges")
        ]
        self.assertIn('const message = "Action created.";', approve)
        self.assertNotIn(
            'persistAgentWorkspace(message);\n  }\n  renderApp({ preserveStatus: true });',
            approve,
        )

        # Both ways in turn the busy state off and redraw once approval is
        # done, so the reply is first drawn with the thinking bubble still
        # there and morphs out of it like any other agent message.
        start = script[
            script.index("function startAgentProposalApproval"):
            script.index("function pushAgentProposalResult")
        ]
        self.assertIn(
            ".finally(() => {\n      agentTurnBusy = false;",
            start,
        )
        self.assertIn("renderApp({ preserveStatus: true });", start)
        turn = script[
            script.index("async function applyAgentTurnResponse"):
            script.index("function pushAgentActionCommandPrompt")
        ]
        self.assertIn("await approveAgentProposal(activeProposal.id, currentRevision);", turn)

    def test_chat_offers_an_action_picker_instead_of_asking_for_a_name(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        # The agent sees the same active actions the panel shows, so it can ask
        # which one the user means instead of guessing.
        self.assertIn("function buildAgentActionContext", script)
        self.assertIn("actionContext: buildAgentActionContext(),", script)
        self.assertIn("function getAgentActionChoices", script)
        self.assertIn("isActiveAgentActionStatus(action.status, action)", script)
        self.assertIn("AGENT_ACTION_CHOICE_LIMIT", script)

        reply_metadata = script[
            script.index("function buildAgentReplyMetadata"):
            script.index("async function handleAgentUserText")
        ]
        self.assertIn("turn?.needsActionChoice ? getAgentActionChoices() : []", reply_metadata)
        self.assertIn('kind: "action-choice"', reply_metadata)
        self.assertIn('createAgentAction(\n        "choose",', reply_metadata)

        # Picking a card answers in chat with a name the numbering pass keeps unique.
        choice_value = script[
            script.index("function getAgentActionChoiceValue"):
            script.index("function buildAgentActionContext")
        ]
        self.assertIn("return `The \u201c${String(choice?.name || \"\").trim()}\u201d action`;", choice_value)
        self.assertIn("return refreshScheduledActionUniqueTitles([", script)

        picker = script[
            script.index("function createAgentActionChoiceCard"):
            script.index("function renderAgentMessageBubbleContent")
        ]
        self.assertIn('button.dataset.agentMessageAction = multiple ? "toggle-choice" : "choose";', picker)
        self.assertIn("button.dataset.agentActionValue = getAgentActionChoiceValue(choice);", picker)
        self.assertIn("areAgentMessageActionsResolved(message, agent.messages)", picker)

        # The card replaces the plain chip row rather than doubling it.
        renderable = script[
            script.index("function getAgentRenderableMessageActions"):
            script.index("function normalizeAgentProposalFieldKey")
        ]
        self.assertIn('if (kind === "action-choice") {\n    return [];', renderable)
        self.assertIn(
            'if (kind === "action-choice" && getAgentMessageActionChoices(message).length) {',
            script,
        )

        # Each option carries its own details button, so a repeated title can be
        # checked before it is picked.
        self.assertIn("row.append(button, createAgentActionChoiceDetailsButton(choice));", picker)
        self.assertIn('button.dataset.agentActionDetails = String(choice?.id || "");', picker)
        self.assertIn("bodyNode: createAgentActionChoiceDetailsBody(action, choice),", picker)
        self.assertIn("returnFocus: button,", picker)

        # The details button opens a popup instead of answering the question.
        self.assertNotIn("agentMessageAction", script[
            script.index("function createAgentActionChoiceDetailsButton"):
            script.index("function findAgentActionChoiceAction")
        ])
        workspace_click = script[
            script.index("function handleAgentWorkspaceClick"):
        ]
        self.assertLess(
            workspace_click.index("handleAgentActionChoiceDetailsClick(event)"),
            workspace_click.index("handleAgentMessageAction(event)"),
        )

        self.assertIn(".agent-message-action-picker {", styles)
        self.assertIn(".agent-message-action-picker-option {", styles)
        self.assertIn(".agent-message-action-picker-details {", styles)
        self.assertIn(".agent-action-choice-details-grid {", styles)
        self.assertIn("background: var(--surface-soft);", styles)

    def test_a_plural_request_gets_a_multi_select_action_picker(self) -> None:
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "styles.css").read_text(encoding="utf-8")

        # The agent says how many actions the message pointed at; the picker
        # follows that instead of forcing one pick at a time.
        self.assertIn("actionChoiceMode: normalizeAgentActionChoiceMode(turn?.actionChoiceMode),", script)
        self.assertIn("function agentMessageAllowsMultipleActionChoices", script)
        self.assertIn('=== "multiple" ? "multiple" : "single"', script)

        picker = script[
            script.index("function createAgentActionChoiceCard"):
            script.index("function createAgentActionChoiceDetailsButton")
        ]
        self.assertIn("const multiple = agentMessageAllowsMultipleActionChoices(message);", picker)
        self.assertIn('button.setAttribute("aria-pressed", picked ? "true" : "false");', picker)
        self.assertIn("createAgentActionChoiceConfirmRow(message, selected.size, resolved)", picker)
        self.assertIn('button.dataset.agentMessageAction = "choose-multiple";', picker)
        self.assertIn("button.disabled = Boolean(resolved || !selectedCount);", picker)

        # Ticking a box must not count as the answer, so only Continue sends one.
        handler = script[
            script.index("function handleAgentMessageAction"):
            script.index("function handleAgentActionReferenceClick")
        ]
        self.assertIn('if (action === "toggle-choice") {', handler)
        self.assertIn("toggleAgentActionChoiceSelection(messageId, button.dataset.agentActionChoiceId", handler)
        self.assertIn('if (action === "choose-multiple") {', handler)
        self.assertIn("getAgentActionChoiceListValue(", handler)
        # The picker stays usable while boxes are ticked; only Continue resolves it.
        toggle_block = handler[handler.index('if (action === "toggle-choice") {'):handler.index('if (action === "choose-multiple") {')]
        self.assertNotIn("resolveAgentMessageActions", toggle_block)

        # Several picks answer in one sentence rather than several messages.
        list_value = script[
            script.index("function getAgentActionChoiceListValue"):
            script.index("function buildAgentActionContext")
        ]
        self.assertIn("return `The ${names.slice(0, -1).join(\", \")} and ${last} actions`;", list_value)

        # A re-render has to keep the ticks the user already made.
        self.assertIn("const agentActionChoiceSelections = new Map();", script)
        self.assertIn("Array.from(getAgentActionChoiceSelection(message.id)).sort()", script)

        self.assertIn(".agent-message-action-picker-option.is-selected {", styles)
        self.assertIn(".agent-message-action-picker-confirm {", styles)
    def test_page_scripts_resolve_from_the_url_the_page_is_served_at(self) -> None:
        """Resolve each <script src> the way a browser does, against the request URL.

        /about is served directly with no redirect to /about/, so a document-relative
        "./page.js" there resolves to /page.js at the root and 404s. Fetching the
        script's own path proves it is served; only resolving it against the page
        proves the page can actually load it.
        """
        for path in ("/about", "/about/", "/portal/", "/"):
            with self.subTest(page=path):
                with urllib_request.urlopen(f"{self.base_url}{path}") as response:
                    markup = response.read().decode("utf-8")
                    page_url = response.geturl()

                for src in re.findall(r'<script[^>]+src="([^"]+)"', markup):
                    if src.startswith(("http://", "https://", "//")):
                        continue
                    resolved = urllib_parse.urljoin(page_url, src)
                    with self.subTest(script=src):
                        with urllib_request.urlopen(resolved) as script_response:
                            self.assertEqual(script_response.status, 200)
                            self.assertIn(
                                "javascript",
                                script_response.headers.get("Content-Type", ""),
                            )

    def _fetch_about_script(self) -> str:
        """The about page ships as HTML plus an extracted script file."""
        with urllib_request.urlopen(f"{self.base_url}/about/page.js") as response:
            return response.read().decode("utf-8")

    def test_about_pretty_route_serves_without_redirect(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/about") as response:
            body = response.read().decode("utf-8")
            final_url = response.geturl()
            status_code = response.status

        body = f"{body}\n{self._fetch_about_script()}"

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

        body = f"{body}\n{self._fetch_about_script()}"

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

        body = f"{body}\n{self._fetch_about_script()}"

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

    def test_portal_app_declares_each_function_only_once(self) -> None:
        # A second `function foo` silently replaces the first, so a rename that
        # misses an old forwarding alias turns it into `foo() { return foo() }`
        # and every caller dies on a stack overflow. assertNotIn on the retired
        # name does not catch that: both copies carry the new name.
        # Top-level declarations only - nested helpers are indented, and two of
        # those sharing a name in different scopes is legal.
        script = (self.root / "portal" / "app.js").read_text(encoding="utf-8")
        declarations: dict[str, int] = {}
        for match in re.finditer(r"^(?:async )?function ([A-Za-z0-9_$]+)\s*\(", script, re.MULTILINE):
            name = match.group(1)
            declarations[name] = declarations.get(name, 0) + 1
        duplicates = sorted(name for name, count in declarations.items() if count > 1)
        self.assertEqual(duplicates, [], f"declared more than once in app.js: {duplicates}")


if __name__ == "__main__":
    unittest.main()
