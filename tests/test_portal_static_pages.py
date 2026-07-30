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
        self.assertIn("--contact-mobile-viewport-height", body)
        self.assertIn("--contact-mobile-visible-height", body)
        self.assertIn('window.matchMedia("(max-width: 640px)")', body)
        self.assertIn('window.visualViewport.addEventListener("scroll", keepContactLayoutPinned)', body)


if __name__ == "__main__":
    unittest.main()
