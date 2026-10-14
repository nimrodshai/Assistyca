from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
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
        for path in ("/admin", "/about", "/portal/admin.js", "/api/pricing"):
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

    def test_landing_assets_are_kept_but_pages_are_not(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/assets/manrope-regular.woff2") as response:
            self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
            self.assertEqual(response.headers.get("Content-Type"), "font/woff2")
        with urllib_request.urlopen(f"{self.base_url}/assets/landing-bg-desktop.webp") as response:
            self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=3600")
        with urllib_request.urlopen(f"{self.base_url}/") as response:
            self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")
        with self.assertRaises(urllib_error.HTTPError) as missing:
            urllib_request.urlopen(f"{self.base_url}/assets/no-such-file.webp")
        self.assertEqual(missing.exception.headers.get("Cache-Control"), "no-store, max-age=0")
        missing.exception.close()

    def test_landing_page_refers_only_to_assets_that_exist(self) -> None:
        page = (self.root / "index.html").read_text(encoding="utf-8")
        for asset in set(re.findall(r"/assets/[\w.-]+", page)):
            self.assertTrue((self.root / asset.lstrip("/")).is_file(), asset)

    def test_csp_allows_everything_the_meta_signup_popup_needs(self) -> None:
        """The Embedded Signup SDK loads a script, calls facebook.com, and frames it.

        Missing any one of these makes the Connect WhatsApp button fail in a way
        that only shows up in the browser console, never in a Python test.
        """
        with urllib_request.urlopen(f"{self.base_url}/admin") as response:
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
        with urllib_request.urlopen(f"{self.base_url}/admin") as response:
            self.assertIsNone(response.headers.get("Strict-Transport-Security"))

        request = urllib_request.Request(
            f"{self.base_url}/admin",
            headers={"X-Forwarded-Proto": "https"},
        )
        with urllib_request.urlopen(request) as response:
            self.assertIn("max-age=31536000", response.headers.get("Strict-Transport-Security", ""))

    def test_served_pages_carry_no_inline_scripts(self) -> None:
        for relative in ("index.html", "privacy.html", "portal/admin.html", "about/index.html"):
            with self.subTest(page=relative):
                markup = (self.root / relative).read_text(encoding="utf-8")
                self.assertNotIn("<script>", markup)

    def test_resolve_static_page_alias_supports_about_with_or_without_trailing_slash(self) -> None:
        self.assertEqual(resolve_static_page_alias("/about"), Path("about/index.html"))
        self.assertEqual(resolve_static_page_alias("/about/"), Path("about/index.html"))
        self.assertIsNone(resolve_static_page_alias("/"))

    def test_the_root_serves_the_product_landing_page(self) -> None:
        """Searching for Assistyca lands on the root, so the root must explain the product.

        The page used to be a redirect into the portal. A person who has never heard
        of us needs the pitch and the way in. Families reach their account from
        the WhatsApp chat, so the page carries no sign-in link.
        """
        with urllib_request.urlopen(f"{self.base_url}/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers.get("Content-Type", ""))
            markup = response.read().decode("utf-8")

        self.assertNotIn("http-equiv=\"refresh\"", markup)
        # One door, for families: the business side is gone.
        self.assertNotIn('href="/register/business"', markup)
        self.assertNotIn('class="panel business"', markup)
        self.assertIn('href="/register"', markup)
        self.assertNotIn('href="/portal/"', markup)
        self.assertIn('href="/privacy.html"', markup)
        self.assertIn('src="/assets/landing-start-bar.js"', markup)
        # The footer carries only Privacy: no sign-in, no agency page.
        self.assertNotIn('href="/about"', markup)
        self.assertNotIn("About Nimrod", markup)
        self.assertIn('<link rel="canonical" href="https://assistyca.com/" />', markup)
        self.assertNotIn("noindex", markup)

    def test_landing_page_assets_are_served(self) -> None:
        markup = (self.root / "index.html").read_text(encoding="utf-8")
        referenced = set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', markup))
        self.assertTrue(referenced, "the landing page should reference its assets by absolute /assets paths")
        for path in sorted(referenced):
            with self.subTest(path=path):
                with urllib_request.urlopen(f"{self.base_url}{path}") as response:
                    self.assertEqual(response.status, 200)
                    # Drain the body so the server never sees a half-read socket.
                    self.assertTrue(response.read())

    def test_robots_lets_crawlers_index_the_landing_page_but_not_the_portal(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/robots.txt") as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
        self.assertIn("Allow: /", body)
        self.assertIn("Disallow: /portal/", body)
        self.assertIn("Disallow: /admin", body)
        self.assertIn("Disallow: /api/", body)

    def test_admin_client_type_select_applies_value_after_options_exist(self) -> None:
        body = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")
        start = body.index("function createAdminClientTypeSelect")
        end = body.index("function createAdminActiveSwitch", start)
        snippet = body[start:end]

        self.assertIn("const selectedClientType", snippet)
        self.assertIn("option.selected = type.value === selectedClientType;", snippet)
        self.assertLess(snippet.index("select.append(option);"), snippet.index("select.value = selectedClientType;"))
        self.assertIn("select.dataset.adminClientTypeValue = selectedClientType;", snippet)

    def test_clients_admin_surfaces_have_dark_mode_treatment(self) -> None:
        html = (self.root / "portal" / "admin.html").read_text(encoding="utf-8")
        styles = (self.root / "portal" / "admin.css").read_text(encoding="utf-8")

        self.assertIn("admin.css?v=", html)
        self.assertIn(':root[data-theme="dark"] .panel-intro h1', styles)
        self.assertIn(':root[data-theme="dark"] .client-metric', styles)
        self.assertIn(':root[data-theme="dark"] .admin-users-table-wrap', styles)
        self.assertIn(':root[data-theme="dark"] .admin-users-table th', styles)
        self.assertIn(':root[data-theme="dark"] .admin-users-table td', styles)
        self.assertIn(':root[data-theme="dark"] .admin-client-type-select[data-admin-client-type-value="demo"]', styles)

    def test_admin_turns_show_the_provider_failure_detail(self) -> None:
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")

        self.assertIn("const diagnostic = call.detail || status;", script)

    def test_page_scripts_resolve_from_the_url_the_page_is_served_at(self) -> None:
        """Resolve each <script src> the way a browser does, against the request URL.

        /about is served directly with no redirect to /about/, so a document-relative
        "./page.js" there resolves to /page.js at the root and 404s. Fetching the
        script's own path proves it is served; only resolving it against the page
        proves the page can actually load it.
        """
        for path in ("/about", "/about/", "/admin", "/"):
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

    def test_admin_script_declares_each_function_only_once(self) -> None:
        # A second `function foo` silently replaces the first, so a rename that
        # misses an old forwarding alias turns it into `foo() { return foo() }`
        # and every caller dies on a stack overflow. assertNotIn on the retired
        # name does not catch that: both copies carry the new name.
        # Top-level declarations only - nested helpers are indented, and two of
        # those sharing a name in different scopes is legal.
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")
        declarations: dict[str, int] = {}
        for match in re.finditer(r"^(?:async )?function ([A-Za-z0-9_$]+)\s*\(", script, re.MULTILINE):
            name = match.group(1)
            declarations[name] = declarations.get(name, 0) + 1
        duplicates = sorted(name for name, count in declarations.items() if count > 1)
        self.assertEqual(duplicates, [], f"declared more than once in admin.js: {duplicates}")


class AdminFreeTrialControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="trial-control-test-secret",
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _sign_in(self, email: str) -> str:
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        return str((result or {}).get("token") or "")

    def _post_trial(self, token: str, email: str, payload: dict[str, Any]) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}/api/admin/users/{urllib_parse.quote(email, safe='')}/trial",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=15) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return int(exc.code), json.loads(exc.read().decode("utf-8"))

    def test_the_admin_page_is_served_and_the_old_chat_page_sends_people_there(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/admin", timeout=10) as response:
            body = response.read().decode("utf-8")
        self.assertIn('src="/portal/admin.js?v=', body)
        self.assertIn('id="clientsPanel"', body)
        self.assertIn('id="featureSwitchesPanel"', body)
        self.assertIn('id="turnsPanel"', body)
        self.assertIn('id="opportunitiesPanel"', body)
        self.assertIn('name="robots" content="noindex"', body)

        class NoRedirect(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                return None

        opener = urllib_request.build_opener(NoRedirect)
        for path in ("/portal/", "/portal", "/portal/index.html"):
            with self.subTest(path=path):
                with self.assertRaises(urllib_error.HTTPError) as caught:
                    opener.open(f"{self.base_url}{path}", timeout=10)
                self.assertEqual(caught.exception.code, 303)
                self.assertEqual(caught.exception.headers.get("Location"), "/admin")
                caught.exception.close()
        for path in ("/portal/app.js", "/portal/styles.css"):
            with self.subTest(path=path):
                with self.assertRaises(urllib_error.HTTPError) as caught:
                    urllib_request.urlopen(f"{self.base_url}{path}", timeout=10)
                self.assertEqual(caught.exception.code, 404)
                caught.exception.close()

    def test_the_session_says_which_admin_tabs_to_show(self) -> None:
        self.database.register_user("client@example.com")
        self.database.register_user("boss@example.com", is_admin=True)

        def session_for(email: str) -> dict:
            request = urllib_request.Request(
                f"{self.base_url}/api/auth/session",
                headers={"Authorization": f"Bearer {self._sign_in(email)}"},
            )
            with urllib_request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        boss = session_for("boss@example.com")
        self.assertTrue(boss["canManageClients"])
        self.assertFalse(boss["canReviewOpportunities"])
        client = session_for("client@example.com")
        self.assertFalse(client["canManageClients"])
        self.assertFalse(client["canReviewOpportunities"])

    def test_the_route_the_control_posts_to_is_actually_wired_up(self) -> None:
        # A sibling route once shipped dead because the dispatch allowlist never
        # let it through, so the wiring is asserted here and not just the markup.
        self.database.register_user("client@example.com")
        self.database.register_user("boss@example.com", is_admin=True)
        token = self._sign_in("boss@example.com")

        status, payload = self._post_trial(token, "client@example.com", {"trialDays": 14})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user"]["trial"]["trialDays"], 14)
        self.assertTrue(payload["user"]["trial"]["onTrial"])

    def test_zero_days_removes_the_limit_rather_than_ending_the_trial(self) -> None:
        self.database.register_user("client@example.com")
        self.database.register_user("boss@example.com", is_admin=True)
        token = self._sign_in("boss@example.com")

        self._post_trial(token, "client@example.com", {"trialDays": 14})
        status, payload = self._post_trial(token, "client@example.com", {"trialDays": 0})

        self.assertEqual(status, 200)
        trial = payload["user"]["trial"]
        self.assertEqual(trial["trialDays"], 0)
        self.assertFalse(trial["expired"])
        self.assertTrue(trial["allowed"])

    def test_the_client_list_carries_the_trial_through_to_the_screen(self) -> None:
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")

        # Dropped here, the whole control would silently render "No limit".
        self.assertIn("trial: normalizeAdminTrial(user.trial || null),", script)
        self.assertIn('for (const heading of ["Client", "Client type", "Free trial", "Cost this month", "Avg / month",', script)
        self.assertIn("trialCell.append(createAdminTrialControl(user, {", script)
        self.assertIn("row.append(nameCell, clientTypeCell, trialCell, spendCell, averageCell,", script)
        # The email waits behind the button beside the name, not in a column.
        self.assertIn("nameWrap.append(nameButton, createAdminEmailInfo(user));", script)

    def test_the_control_posts_the_day_count_to_the_trial_route(self) -> None:
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")
        start = script.index("async function saveAdminUserTrial")
        end = script.index("function deleteAdminUser", start)
        snippet = script[start:end]

        self.assertIn("`/api/admin/users/${encodeURIComponent(normalizedEmail)}/trial`", snippet)
        self.assertIn('method: "POST"', snippet)
        self.assertIn("trialDays: nextTrialDays,", snippet)
        # The optimistic row has to be put back when the save is refused.
        self.assertIn("? { ...entry, trial: previousTrial }", snippet)
        self.assertIn("formatApiErrorMessage(error,", snippet)
        # Restarting the clock is not offered, so nothing may ask for it.
        self.assertNotIn("restart", snippet)

    def test_the_change_event_reaches_the_save(self) -> None:
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")

        self.assertIn(
            'if (target instanceof HTMLInputElement && target.dataset.adminTrialUser) {',
            script,
        )
        self.assertIn(
            'void saveAdminUserTrial(target.dataset.adminTrialUser || "", target.value);',
            script,
        )

    def test_zero_days_reads_as_no_limit_and_a_payer_never_reads_as_ended(self) -> None:
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")
        start = script.index("function describeAdminTrial")
        end = script.index("function createAdminTrialControl", start)
        snippet = script[start:end]

        # Order is the whole point: paying and zero-days are answered before the
        # expiry flag, so neither can come out as "Trial ended".
        paying = snippet.index("if (isPaying) {")
        no_limit = snippet.index("if (trial.trialDays <= 0) {")
        expired = snippet.index("if (trial.expired) {")
        self.assertLess(paying, no_limit)
        self.assertLess(no_limit, expired)

        self.assertIn('label: "No limit", note: "Paying client"', snippet)
        self.assertIn('label: "No limit", note: ""', snippet)
        self.assertIn('label: "Trial ended"', snippet)
        self.assertIn('daysLeft === 1 ? "1 day left" : daysLeft > 1 ? `${daysLeft} days left`', snippet)
        self.assertIn("`Ends ${formatAdminTrialDate(trial.endsAt)}`", snippet)

    def test_the_field_says_what_zero_means_in_plain_words(self) -> None:
        script = (self.root / "portal" / "admin.js").read_text(encoding="utf-8")

        self.assertIn('hint.textContent = "days (0 = no limit)";', script)
        self.assertIn(
            'help.textContent = "Changing the length keeps the days already used. '
            'Set 0 to remove the limit.";',
            script,
        )
        self.assertIn('input.type = "number";', script)
        self.assertIn('input.min = "0";', script)

    def test_the_trial_control_is_styled_in_both_themes(self) -> None:
        styles = (self.root / "portal" / "admin.css").read_text(encoding="utf-8")

        self.assertIn(".admin-trial-input {", styles)
        self.assertIn(".admin-trial-state.is-trial-ended {", styles)
        self.assertIn(':root[data-theme="dark"] .admin-trial-input {', styles)


class WeekImageRouteTests(unittest.TestCase):
    """The week-ahead picture is served by its code and by nothing else."""

    setUp = PortalStaticPageTests.setUp
    tearDown = PortalStaticPageTests.tearDown

    def test_a_saved_picture_is_served_as_an_image_and_a_wrong_code_is_not(self) -> None:
        database = self.server.database  # type: ignore[attr-defined]
        database.register_user("family@example.com")
        user_id = int((database.get_user("family@example.com") or {})["id"])
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        code = database.save_household_week_image(user_id=user_id, week_start="2026-10-18", image=png)
        with urllib_request.urlopen(f"{self.base_url}/week/image/{code}.png") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.headers["Cache-Control"], "public, max-age=86400")
            self.assertEqual(response.read(), png)
        for wrong in ("nope.png", "a" * 20 + ".png", "../portal.db"):
            with self.assertRaises(urllib_error.HTTPError) as caught:
                urllib_request.urlopen(f"{self.base_url}/week/image/{wrong}")
            self.assertEqual(caught.exception.code, 404, wrong)


if __name__ == "__main__":
    unittest.main()
