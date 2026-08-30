"""Keeping a spending answer keeps the receipt it was read from.

A question asked in chat runs, answers and writes nothing. "Save to a folder"
used to write the sentence and nothing else, which left the client with a note
about a receipt instead of the receipt. The emails behind the answer are named
in the run's reply, so keeping the answer goes back to the mailbox for them.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.gmail_summary import GmailSummaryError
from packages.infrastructure.mail_attachments import safe_attachment_filename
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import normalize_saved_answer_sources
from packages.infrastructure.receipt_collector import answer_receipt_question

SERVER_MODULE = "packages.infrastructure.portal_auth.server"
PDF_BYTES = b"%PDF-1.4 a receipt from the vendor"


def _gmail_message_with_pdf(filename: str = "invoice-8891.pdf") -> dict[str, object]:
    return {
        "id": "msg-1",
        "payload": {
            "parts": [
                {
                    "filename": filename,
                    "mimeType": "application/pdf",
                    "body": {
                        "size": len(PDF_BYTES),
                        "data": base64.urlsafe_b64encode(PDF_BYTES).decode("ascii"),
                    },
                },
            ],
        },
    }


class SavedAnswerReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
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
        if self.server.credential_vault is None:
            self.server.server_close()
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.owner_key = build_agent_receipt_owner_key("owner@example.com")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _connect_gmail(self, address: str) -> None:
        # A hand-entered access token, so the save needs no token endpoint.
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="token",
            secret_ciphertext=self.server.credential_vault.encrypt("gmail-access-token"),  # type: ignore[union-attr]
            secret_hint="Gmail token",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            account_address=address,
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )

    def _save_answer(self, body: dict[str, object]) -> dict[str, object]:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/folders/save",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _saved_folder(self) -> Path:
        return self.output_dir / self.owner_key / "Saved answers"

    def _render_sources(self, mailbox: str = "owner@gmail.com") -> list[dict[str, str]]:
        return [{"messageId": "msg-1", "mailbox": mailbox, "vendor": "Render"}]

    def test_keeping_an_answer_keeps_the_receipt_pdf_from_the_email(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({
                "title": "How much am i paying to render?",
                "text": "You paid 13.35 USD to Render in Aug 2026, across 1 receipt.",
                "sources": self._render_sources(),
            })

        self.assertTrue(payload["ok"])
        receipts = payload["receipts"]
        self.assertEqual(len(receipts), 1)
        saved = self._saved_folder() / str(receipts[0]["name"])
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), PDF_BYTES)

    def test_the_kept_receipt_is_named_after_who_sent_it(self) -> None:
        # The file sits next to a note in a folder someone browses, so the
        # vendor's name beats the message id a bundle would use.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({
                "title": "Render receipts",
                "text": "You paid 13.35 USD to Render.",
                "sources": self._render_sources(),
            })

        self.assertEqual(payload["receipts"][0]["name"], "Render - invoice-8891.pdf")

    def test_the_reply_says_the_receipt_came_with_the_answer(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({
                "title": "Render receipts",
                "text": "You paid 13.35 USD to Render.",
                "sources": self._render_sources(),
            })

        self.assertEqual(payload["message"], "Saved to Saved answers, with 1 receipt PDF.")

    def test_the_note_names_the_receipts_filed_beside_it(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({
                "title": "Render receipts",
                "text": "You paid 13.35 USD to Render.",
                "sources": self._render_sources(),
            })

        note = (self._saved_folder() / str(payload["name"])).read_text(encoding="utf-8")
        self.assertIn("You paid 13.35 USD to Render.", note)
        self.assertIn("- Render - invoice-8891.pdf", note)

    def test_a_source_with_no_mailbox_name_belongs_to_the_only_mailbox(self) -> None:
        # An answer run records the mailbox each item came from, but an answer
        # kept from an older reply has none, and one mailbox owns all of them.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({
                "title": "Render receipts",
                "text": "You paid 13.35 USD to Render.",
                "sources": [{"messageId": "msg-1", "vendor": "Render"}],
            })

        self.assertEqual(len(payload["receipts"]), 1)

    def test_a_receipt_that_cannot_be_read_does_not_lose_the_answer(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            side_effect=GmailSummaryError("Gmail is unhappy.", code="gmail_provider_error"),
        ):
            payload = self._save_answer({
                "title": "Render receipts",
                "text": "You paid 13.35 USD to Render.",
                "sources": self._render_sources(),
            })

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["receipts"], [])
        self.assertEqual(payload["message"], "Saved to Saved answers.")
        self.assertTrue((self._saved_folder() / str(payload["name"])).is_file())

    def test_an_answer_with_no_receipts_behind_it_saves_as_it_always_did(self) -> None:
        payload = self._save_answer({"title": "Email summary", "text": "14 messages this week."})

        self.assertEqual(payload["receipts"], [])
        self.assertEqual(payload["message"], "Saved to Saved answers.")

    def test_a_kept_receipt_shows_up_in_the_folder_listing(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            self._save_answer({
                "title": "Render receipts",
                "text": "You paid 13.35 USD to Render.",
                "sources": self._render_sources(),
            })

        request = urllib_request.Request(
            f"{self.base_url}/api/agent/folder-contents?folder=Saved%20answers",
            method="GET",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            contents = json.loads(response.read().decode("utf-8"))

        self.assertIn("Render - invoice-8891.pdf", [item["name"] for item in contents["items"]])


class SavedAnswerSourceTests(unittest.TestCase):
    """What the run hands over, and what the save endpoint accepts back."""

    def test_an_answer_names_the_emails_its_total_came_from(self) -> None:
        items = [{
            "id": "msg-1",
            "mailbox": "owner@gmail.com",
            "from": "Render <billing@render.com>",
            "subject": "Your receipt from Render",
            "date": "Fri, 1 Aug 2026 09:00:00 +0000",
            "bodyText": "Total $13.35 paid",
        }]

        answer = answer_receipt_question(items, vendor="Render", month_label="Aug 2026")

        self.assertEqual(answer["sources"], [{
            "messageId": "msg-1",
            "mailbox": "owner@gmail.com",
            "vendor": "Render",
            "subject": "Your receipt from Render",
            "date": "Fri, 1 Aug 2026 09:00:00 +0000",
        }])

    def test_a_receipt_from_another_vendor_is_not_kept_with_this_answer(self) -> None:
        items = [
            {"id": "msg-1", "from": "Render <billing@render.com>", "subject": "Receipt", "bodyText": "Total $13.35"},
            {"id": "msg-2", "from": "Netlify <billing@netlify.com>", "subject": "Receipt", "bodyText": "Total $19.00"},
        ]

        answer = answer_receipt_question(items, vendor="Render")

        self.assertEqual([source["messageId"] for source in answer["sources"]], ["msg-1"])

    def test_a_receipt_from_a_sender_with_no_name_is_not_filed_under_one(self) -> None:
        # "Unknown vendor" is a label for the report, not a name to put on a
        # file someone opens.
        items = [{"id": "msg-1", "from": "", "subject": "Receipt", "bodyText": "Total $4.00"}]

        answer = answer_receipt_question(items)

        self.assertEqual(answer["sources"][0]["vendor"], "")

    def test_the_endpoint_keeps_only_the_fields_it_uses(self) -> None:
        sources = normalize_saved_answer_sources([
            {"messageId": "msg-1", "mailbox": "owner@gmail.com", "vendor": "Render", "path": "/etc/passwd"},
        ])

        self.assertEqual(sources, [{"messageId": "msg-1", "mailbox": "owner@gmail.com", "vendor": "Render"}])

    def test_the_endpoint_refuses_to_fetch_a_mailbox_full_of_messages(self) -> None:
        sources = normalize_saved_answer_sources([
            {"messageId": f"msg-{index}", "mailbox": "owner@gmail.com"} for index in range(80)
        ])

        self.assertEqual(len(sources), 25)

    def test_nonsense_in_place_of_sources_is_ignored(self) -> None:
        self.assertEqual(normalize_saved_answer_sources("msg-1"), [])
        self.assertEqual(normalize_saved_answer_sources([None, {}, {"mailbox": "owner@gmail.com"}]), [])

    def test_a_bundle_still_names_its_files_after_the_message(self) -> None:
        # The report beside them is what a reader goes through, so nothing
        # about the bundle's naming changed.
        name = safe_attachment_filename(
            "invoice.pdf",
            fallback="receipt-01",
            mime_type="application/pdf",
            message_id="19a2b3c4d5e6f7",
            part_index=1,
        )

        self.assertEqual(name, "19a2b3c4d5e6-01-invoice.pdf")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the portal script")
class SavedAnswerChatTests(unittest.TestCase):
    """The chat side: what it remembers, and what it says it kept."""

    def setUp(self) -> None:
        self.script = (Path(__file__).resolve().parents[1] / "portal" / "app.js").read_text(encoding="utf-8")

    def _run(self, expression: str) -> object:
        helpers = self.script[
            self.script.index("const AGENT_ANSWER_RECEIPT_SOURCE_LIMIT"):
            self.script.index("function getAgentAnswerResultFolder")
        ] + self.script[
            self.script.index("function describeAgentSavedAnswer"):
            self.script.index("async function saveAgentAnswerToFolder")
        ]
        completed = subprocess.run(
            ["node", "-e", f"{helpers}\nconsole.log(JSON.stringify({expression}));"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_the_chat_remembers_which_emails_the_answer_came_from(self) -> None:
        sources = self._run(
            'collectAgentAnswerReceiptSources([{ receiptSources: '
            '[{ messageId: "msg-1", mailbox: "owner@gmail.com", vendor: "Render" }] }])'
        )

        self.assertEqual(sources, [{"messageId": "msg-1", "mailbox": "owner@gmail.com", "vendor": "Render"}])

    def test_a_question_answered_month_by_month_keeps_each_months_receipts(self) -> None:
        sources = self._run(
            "collectAgentAnswerReceiptSources(["
            '{ receiptSources: [{ messageId: "msg-1", mailbox: "owner@gmail.com" }] },'
            '{ receiptSources: [{ messageId: "msg-2", mailbox: "owner@gmail.com" }] },'
            '{ receiptSources: [{ messageId: "msg-1", mailbox: "owner@gmail.com" }] }])'
        )

        self.assertEqual([source["messageId"] for source in sources], ["msg-1", "msg-2"])

    def test_a_run_that_saved_files_of_its_own_carries_no_sources(self) -> None:
        self.assertEqual(self._run("collectAgentAnswerReceiptSources([{ outputFolder: 'Receipts/Aug2026' }])"), [])

    def test_the_chat_says_the_receipt_was_kept_too(self) -> None:
        sentence = self._run(
            'describeAgentSavedAnswer("Saved answers", { receipts: [{ name: "Render - invoice.pdf" }] }, '
            '[{ messageId: "msg-1" }])'
        )

        self.assertEqual(
            sentence,
            "Kept that in Saved answers, with the receipt itself. You can open it from the Folders panel.",
        )

    def test_an_email_with_nothing_attached_is_said_out_loud(self) -> None:
        sentence = self._run('describeAgentSavedAnswer("Saved answers", { receipts: [] }, [{ messageId: "msg-1" }])')

        self.assertIn("nothing attached", str(sentence))

    def test_an_answer_with_no_receipts_reads_as_it_always_did(self) -> None:
        sentence = self._run('describeAgentSavedAnswer("Saved answers", {}, [])')

        self.assertEqual(sentence, "Kept that in Saved answers. You can open it from the Folders panel.")

    def test_the_save_sends_the_receipts_it_remembered(self) -> None:
        saver = self.script[
            self.script.index("async function saveAgentAnswerToFolder"):
            self.script.index("async function saveAgentOneOffAsAction")
        ]

        self.assertIn("body: sources.length ? { title, text, sources } : { title, text },", saver)
        # Fetching a receipt per email takes longer than writing a note.
        self.assertIn("timeoutMs: 90000,", saver)

    def test_a_finished_answer_remembers_its_receipts(self) -> None:
        runner = self.script[
            self.script.index("async function runAgentAnswerNow"):
            self.script.index("async function applyAgentTurnResponse")
        ]

        self.assertIn("receipts: collectAgentAnswerReceiptSources(runResults),", runner)


if __name__ == "__main__":
    unittest.main()
