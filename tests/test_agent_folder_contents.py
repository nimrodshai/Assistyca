from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key
from packages.infrastructure.portal_auth.server import build_saved_receipt_folder
from packages.infrastructure.portal_auth.server import create_server


class AgentFolderContentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.output_dir = Path(self.temp_dir.name) / "agent_outputs"
        self.server = create_server(
            "127.0.0.1",
            0,
            root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
                agent_output_dir=self.output_dir,
            ),
        )
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.owner_key = build_agent_receipt_owner_key("owner@example.com")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _write_bundle(self) -> Path:
        folder = self.output_dir / self.owner_key / "Receipts" / "Jul2026"
        (folder / "attachments").mkdir(parents=True, exist_ok=True)
        (folder / "receipt-report.pdf").write_bytes(b"pdf-bytes")
        (folder / "receipts.xlsx").write_bytes(b"xlsx-bytes")
        (folder / "bundle.json").write_text("{}", encoding="utf-8")
        (folder / "attachments" / "msg-1-01-receipt.png").write_bytes(b"png-bytes")
        return folder

    def _get_contents(self, folder: str, *, token: str | None = "") -> dict[str, object]:
        query = urllib_parse.urlencode({"folder": folder})
        headers = {}
        auth_token = self.session_token if token == "" else token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/folder-contents?{query}",
            method="GET",
            headers=headers,
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _save_answer(self, body: dict[str, object], *, token: str | None = "") -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        auth_token = self.session_token if token == "" else token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/folders/save",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_an_answer_with_no_receipt_behind_it_is_refused(self) -> None:
        # What the save files is the receipt, not the sentence. An answer with
        # no receipt behind it has nothing to file.
        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._save_answer({"title": "Email summary", "text": "14 messages this week."})

        self.assertEqual(caught.exception.code, 400)

    def test_a_vendor_name_cannot_climb_out_of_the_owner_directory(self) -> None:
        # The vendor names the folder, and a vendor name arrives from a
        # mailbox, so it is put through the same traversal-safe normalizer the
        # receipt bundles use.
        self.assertEqual(build_saved_receipt_folder("../../../etc"), "etc/")
        self.assertEqual(build_saved_receipt_folder("../.."), "Saved receipts/")

    def test_saving_needs_a_signed_in_owner(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._save_answer({"sources": [{"messageId": "msg-1"}]}, token=None)

        self.assertEqual(caught.exception.code, 401)

    def test_lists_bundle_files_with_download_urls(self) -> None:
        self._write_bundle()

        payload = self._get_contents("Receipts/Jul2026")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["folder"], "Receipts/Jul2026/")
        names = [item["name"] for item in payload["items"]]
        # The manifest is an internal file, so it stays out of the listing, and
        # the exports come before the attachments they were built from.
        self.assertEqual(
            names,
            ["receipt-report.pdf", "receipts.xlsx", "attachments/msg-1-01-receipt.png"],
        )
        self.assertEqual(
            payload["items"][0]["url"],
            f"/output/agent_receipts/{self.owner_key}/Receipts/Jul2026/receipt-report.pdf",
        )
        self.assertEqual(payload["items"][0]["size"], len(b"pdf-bytes"))

    def test_returns_empty_listing_for_folder_without_files(self) -> None:
        payload = self._get_contents("Receipts/Jun2026")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["items"], [])

    def test_folder_name_cannot_escape_the_owner_directory(self) -> None:
        outside = self.output_dir / "secrets.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("private", encoding="utf-8")

        payload = self._get_contents("../../")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["items"], [])
        self.assertNotIn("..", str(payload["folder"]))

    def test_requires_a_session(self) -> None:
        self._write_bundle()

        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._get_contents("Receipts/Jul2026", token=None)

        self.assertEqual(caught.exception.code, 401)

    def test_rejects_a_missing_folder_name(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._get_contents("")

        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
