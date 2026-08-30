"""Keeping a spending answer keeps the receipts, filed under the vendor.

A question asked in chat runs, answers and writes nothing. Keeping it used to
write the sentence into a folder called "Saved answers", which left the client
with a note about a receipt instead of the receipt.

What a client files is the PDF the vendor sent. So the emails behind the
answer are fetched, the files land in a folder named after the vendor, and
each one is tagged with who it is from, the month and year it is from, and
whether it calls itself an invoice or a receipt.
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
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.gmail_summary import GmailSummaryError
from packages.infrastructure.mail_attachments import safe_attachment_filename
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.file_tags import FILE_TAGS_FILENAME
from packages.infrastructure.file_tags import read_file_tags
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

    def _save_answer_refusal(self, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        try:
            self._save_answer(body)
        except urllib_error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))
        raise AssertionError("the save was expected to refuse")

    def _folder(self, name: str = "Render") -> Path:
        return self.output_dir / self.owner_key / name

    def _list_folder(self, name: str) -> dict[str, object]:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/folder-contents?folder={urllib_parse.quote(name)}",
            method="GET",
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _render_sources(self, mailbox: str = "owner@gmail.com") -> list[dict[str, str]]:
        return [{
            "messageId": "msg-1",
            "mailbox": mailbox,
            "vendor": "Render",
            "subject": "Your receipt from Render",
            "date": "Fri, 1 Aug 2026 09:00:00 +0000",
        }]

    def test_keeping_an_answer_keeps_the_receipt_pdf_from_the_email(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertTrue(payload["ok"])
        receipts = payload["receipts"]
        self.assertEqual(len(receipts), 1)
        saved = self._folder() / str(receipts[0]["name"])
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), PDF_BYTES)

    def test_the_receipt_is_filed_under_the_vendor_that_sent_it(self) -> None:
        # A client looking for a Render invoice looks under Render, not under
        # the question they once asked.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertEqual(payload["folder"], "Render/")
        self.assertEqual(payload["folders"], [{"name": "Render/", "itemCount": 1}])
        self.assertEqual(payload["receipts"][0]["name"], "Render - invoice-8891.pdf")

    def test_the_answer_itself_is_not_written_to_the_folder(self) -> None:
        # The sentence was said in the conversation. What is kept is the file
        # the vendor sent, and nothing beside it but the tags.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            self._save_answer({"sources": self._render_sources()})

        written = sorted(path.name for path in self._folder().iterdir())
        self.assertEqual(written, ["Render - invoice-8891.pdf", FILE_TAGS_FILENAME])

    def test_a_kept_receipt_is_tagged_with_who_when_and_what(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf("receipt-8891.pdf"),
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertEqual(payload["receipts"][0]["tags"], ["Render", "Aug", "2026", "Receipt"])
        self.assertEqual(
            read_file_tags(self._folder()),
            {"Render - receipt-8891.pdf": ["Render", "Aug", "2026", "Receipt"]},
        )

    def test_an_invoice_and_a_receipt_are_not_tagged_the_same(self) -> None:
        # A vendor sends both for the same charge, and the difference is the
        # one thing a bookkeeper sorts on.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf("invoice-8891.pdf"),
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertIn("Invoice", payload["receipts"][0]["tags"])
        self.assertNotIn("Receipt", payload["receipts"][0]["tags"])

    def test_receipts_from_two_vendors_go_to_two_folders(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": [
                {"messageId": "msg-1", "mailbox": "owner@gmail.com", "vendor": "Render"},
                {"messageId": "msg-2", "mailbox": "owner@gmail.com", "vendor": "Netlify"},
            ]})

        self.assertEqual(
            sorted(folder["name"] for folder in payload["folders"]),
            ["Netlify/", "Render/"],
        )
        self.assertTrue((self._folder("Netlify") / "Netlify - invoice-8891.pdf").is_file())
        self.assertTrue((self._folder("Render") / "Render - invoice-8891.pdf").is_file())

    def test_a_receipt_whose_sender_could_not_be_read_still_has_somewhere_to_go(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": [{"messageId": "msg-1", "mailbox": "owner@gmail.com"}]})

        self.assertEqual(payload["folder"], "Saved receipts/")

    def test_the_reply_says_what_was_filed_and_where(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertEqual(payload["message"], "Saved 1 receipt PDF to Render.")

    def test_a_source_with_no_mailbox_name_belongs_to_the_only_mailbox(self) -> None:
        # An answer run records the mailbox each item came from, but an answer
        # kept from an older reply has none, and one mailbox owns all of them.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": [{"messageId": "msg-1", "vendor": "Render"}]})

        self.assertEqual(len(payload["receipts"]), 1)

    def test_a_receipt_is_looked_for_in_every_mailbox_when_its_own_is_not_recognised(self) -> None:
        # Two mailboxes can report the same address, so the name a run wrote
        # down is not guaranteed to still name a connection at save time.
        # Dropping the receipt over that would be silent and wrong.
        self._connect_gmail("owner@gmail.com")
        self._connect_gmail("second@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf(),
        ):
            payload = self._save_answer({"sources": self._render_sources(mailbox="an-old-name@gmail.com")})

        self.assertEqual(len(payload["receipts"]), 1)

    def test_a_receipt_no_mailbox_would_hand_over_is_counted(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            side_effect=GmailSummaryError("Gmail is unhappy.", code="gmail_provider_error"),
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["receipts"], [])
        self.assertEqual(payload["receiptsMissed"], 1)
        self.assertEqual(
            payload["message"],
            "I couldn\u2019t fetch 1 receipt from your mailbox.",
        )

    def test_an_email_that_carried_no_file_is_not_counted_as_a_miss(self) -> None:
        # Nothing to keep is a fact about the email. It must not read as a
        # mailbox that refused to answer.
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value={"id": "msg-1", "payload": {"parts": []}},
        ):
            payload = self._save_answer({"sources": self._render_sources()})

        self.assertEqual(payload["receipts"], [])
        self.assertEqual(payload["receiptsMissed"], 0)
        self.assertEqual(payload["message"], "Those emails carried no file, so there was nothing to keep.")

    def test_an_answer_with_no_receipt_behind_it_has_nothing_to_file(self) -> None:
        status, payload = self._save_answer_refusal({"title": "Email summary", "text": "14 messages this week."})

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "nothing_to_file")

    def test_a_kept_receipt_shows_up_in_the_folder_listing_with_its_tags(self) -> None:
        self._connect_gmail("owner@gmail.com")

        with mock.patch(
            f"{SERVER_MODULE}.GmailDigestRunner._get_json",
            return_value=_gmail_message_with_pdf("receipt-8891.pdf"),
        ):
            self._save_answer({"sources": self._render_sources()})

        contents = self._list_folder("Render")

        self.assertEqual(
            [(item["name"], item["tags"]) for item in contents["items"]],
            [("Render - receipt-8891.pdf", ["Render", "Aug", "2026", "Receipt"])],
        )
        # The tag file is bookkeeping, not something to open.
        self.assertNotIn(FILE_TAGS_FILENAME, [item["name"] for item in contents["items"]])
        self.assertEqual(contents["tags"], ["2026", "Aug", "Receipt", "Render"])


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

        self.assertEqual(sources, [{
            "messageId": "msg-1",
            "mailbox": "owner@gmail.com",
            "vendor": "Render",
            "subject": "",
            "date": "",
        }])

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
            self.script.index("function describeAgentSavedReceipts"):
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
            '[{ messageId: "msg-1", mailbox: "owner@gmail.com", vendor: "Render", '
            'subject: "Your receipt from Render", date: "Fri, 1 Aug 2026 09:00:00 +0000" }] }])'
        )

        self.assertEqual(sources, [{
            "messageId": "msg-1",
            "mailbox": "owner@gmail.com",
            "vendor": "Render",
            # Who it is from names the folder; the subject and the date make
            # the tags it is found by.
            "subject": "Your receipt from Render",
            "date": "Fri, 1 Aug 2026 09:00:00 +0000",
        }])

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

    def test_the_chat_says_where_the_receipt_was_filed_and_how_it_is_tagged(self) -> None:
        sentence = self._run(
            'describeAgentSavedReceipts({ folders: [{ name: "Render/" }], receipts: '
            '[{ name: "Render - invoice.pdf", tags: ["Render", "Aug", "2026", "Invoice"] }] }, '
            '[{ messageId: "msg-1" }])'
        )

        self.assertEqual(
            sentence,
            "Filed the receipt in Render. Tagged Render, Aug, 2026, Invoice. "
            "You can open it from the Folders panel.",
        )

    def test_receipts_from_two_vendors_name_both_folders(self) -> None:
        sentence = self._run(
            'describeAgentSavedReceipts({ folders: [{ name: "Render/" }, { name: "Netlify/" }], '
            'receipts: [{ name: "a.pdf", tags: ["Render"] }, { name: "b.pdf", tags: ["Netlify"] }] }, '
            '[{ messageId: "msg-1" }, { messageId: "msg-2" }])'
        )

        self.assertIn("all 2 receipts in Render and Netlify", str(sentence))

    def test_an_email_with_nothing_attached_is_said_out_loud(self) -> None:
        sentence = self._run('describeAgentSavedReceipts({ receipts: [] }, [{ messageId: "msg-1" }])')

        self.assertIn("carried no file", str(sentence))

    def test_a_mailbox_that_would_not_hand_the_receipt_over_reads_differently(self) -> None:
        sentence = self._run(
            'describeAgentSavedReceipts({ receipts: [], receiptsMissed: 1 }, [{ messageId: "msg-1" }])'
        )

        self.assertIn("couldn\u2019t fetch that receipt from your mailbox", str(sentence))
        self.assertNotIn("carried no file", str(sentence))

    def test_the_save_sends_the_receipts_it_remembered(self) -> None:
        saver = self.script[
            self.script.index("async function saveAgentAnswerToFolder"):
            self.script.index("async function saveAgentOneOffAsAction")
        ]

        # The receipts are the whole request now: the answer itself stays in
        # the conversation, so there is nothing else to send.
        self.assertIn("body: { sources },", saver)
        self.assertNotIn("text", saver.split("apiRequest")[1].split("});")[0])
        # Fetching a receipt per email takes longer than writing a note.
        self.assertIn("timeoutMs: 90000,", saver)

    def test_an_answer_with_no_receipt_behind_it_is_never_sent(self) -> None:
        saver = self.script[
            self.script.index("async function saveAgentAnswerToFolder"):
            self.script.index("async function saveAgentOneOffAsAction")
        ]

        self.assertIn("if (!sources.length) {\n    return;\n  }", saver)
