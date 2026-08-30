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
from packages.infrastructure.file_tags import read_file_tags
from packages.infrastructure.file_tags import write_file_tags


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

    def _delete_folders(self, body: dict[str, object], *, token: str | None = "") -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        auth_token = self.session_token if token == "" else token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/folders/delete",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _delete_files(self, body: dict[str, object], *, token: str | None = "") -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        auth_token = self.session_token if token == "" else token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/files/delete",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_deletes_picked_files_and_leaves_the_folder_standing(self) -> None:
        folder = self._write_bundle()

        payload = self._delete_files({
            "folder": "Receipts/Jul2026",
            # A listing carries the path inside the folder, so a pick can name
            # a file in a subfolder.
            "files": ["receipts.xlsx", "attachments/msg-1-01-receipt.png"],
        })

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted"], ["receipts.xlsx", "attachments/msg-1-01-receipt.png"])
        self.assertEqual(payload["failed"], [])
        self.assertTrue(folder.is_dir())
        self.assertTrue((folder / "receipt-report.pdf").exists())
        self.assertFalse((folder / "receipts.xlsx").exists())
        self.assertFalse((folder / "attachments" / "msg-1-01-receipt.png").exists())
        # An attachments folder holding nothing is a leftover, not content.
        self.assertFalse((folder / "attachments").exists())
        # bundle.json describes the folder rather than sitting in it, so what
        # is left is the report alone.
        self.assertEqual(payload["remaining"], 1)

    def test_a_file_the_listing_showed_but_disk_lost_is_not_a_failure(self) -> None:
        self._write_bundle()

        payload = self._delete_files({"folder": "Receipts/Jul2026", "files": ["gone.pdf"]})

        self.assertEqual(payload["deleted"], [])
        self.assertEqual(payload["missing"], ["gone.pdf"])
        self.assertEqual(payload["failed"], [])

    def test_a_file_name_cannot_delete_outside_the_folder(self) -> None:
        folder = self._write_bundle()
        outside = self.output_dir / "secrets.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("private", encoding="utf-8")
        sibling = folder.parent / "Jun2026"
        sibling.mkdir(parents=True, exist_ok=True)
        (sibling / "receipt.pdf").write_bytes(b"other month")

        payload = self._delete_files({
            "folder": "Receipts/Jul2026",
            "files": ["../../../secrets.txt", "../Jun2026/receipt.pdf", "/etc/hosts"],
        })

        self.assertEqual(payload["deleted"], [])
        self.assertTrue(outside.exists())
        self.assertTrue((sibling / "receipt.pdf").exists())

    def test_the_manifest_is_not_a_file_the_chat_can_delete(self) -> None:
        # It never appeared in a listing, so nothing could have picked it, and
        # removing it would break reading the bundle back.
        folder = self._write_bundle()

        payload = self._delete_files({"folder": "Receipts/Jul2026", "files": ["bundle.json"]})

        self.assertEqual(payload["failed"], ["bundle.json"])
        self.assertTrue((folder / "bundle.json").exists())

    def test_deleting_a_file_forgets_the_tags_that_described_it(self) -> None:
        folder = self._write_bundle()
        write_file_tags(folder, {
            "receipt-report.pdf": ["Render", "Aug"],
            "receipts.xlsx": ["Render", "Jul"],
        })

        self._delete_files({"folder": "Receipts/Jul2026", "files": ["receipts.xlsx"]})

        self.assertEqual(read_file_tags(folder), {"receipt-report.pdf": ["Render", "Aug"]})

    def test_deleting_files_needs_a_signed_in_owner(self) -> None:
        folder = self._write_bundle()

        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._delete_files(
                {"folder": "Receipts/Jul2026", "files": ["receipts.xlsx"]},
                token=None,
            )

        self.assertEqual(caught.exception.code, 401)
        self.assertTrue((folder / "receipts.xlsx").exists())

    def test_rejects_a_file_delete_with_nothing_named(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._delete_files({"folder": "Receipts/Jul2026", "files": []})

        self.assertEqual(caught.exception.code, 400)

        with self.assertRaises(urllib_error.HTTPError) as missing_folder:
            self._delete_files({"files": ["receipts.xlsx"]})

        self.assertEqual(missing_folder.exception.code, 400)

    def test_deletes_a_folder_with_the_files_inside_it(self) -> None:
        folder = self._write_bundle()

        payload = self._delete_folders({"folders": ["Receipts/Jul2026"]})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted"], ["Receipts/Jul2026"])
        self.assertEqual(payload["failed"], [])
        self.assertFalse(folder.exists())

    def test_a_folder_the_panel_remembers_but_disk_never_held_is_not_a_failure(self) -> None:
        # The user asked for it gone and it is gone. Reporting that as a
        # failure would send them to a panel to retry something already done.
        payload = self._delete_folders({"folders": ["Receipts/May2026"]})

        self.assertEqual(payload["deleted"], [])
        self.assertEqual(payload["missing"], ["Receipts/May2026"])
        self.assertEqual(payload["failed"], [])

    def test_a_folder_name_cannot_delete_outside_the_owner_directory(self) -> None:
        outside = self.output_dir / "secrets.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("private", encoding="utf-8")
        other_owner = self.output_dir / "someone-else"
        other_owner.mkdir(parents=True, exist_ok=True)
        (other_owner / "receipt.pdf").write_bytes(b"theirs")

        self._delete_folders({"folders": ["../../", "../someone-else", "../.."]})

        self.assertTrue(outside.exists())
        self.assertTrue((other_owner / "receipt.pdf").exists())

    def test_deleting_needs_a_signed_in_owner(self) -> None:
        folder = self._write_bundle()

        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._delete_folders({"folders": ["Receipts/Jul2026"]}, token=None)

        self.assertEqual(caught.exception.code, 401)
        self.assertTrue(folder.exists())

    def test_rejects_a_delete_with_no_folder_named(self) -> None:
        with self.assertRaises(urllib_error.HTTPError) as caught:
            self._delete_folders({"folders": []})

        self.assertEqual(caught.exception.code, 400)

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
