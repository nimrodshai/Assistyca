"""Answering from the folders the account already keeps.

The receipts were read from the mailbox once, counted, and filed. Asking about
them again should read the folder, not the mailbox: it is the same answer, and
it is still there after the mail is gone.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.file_tags import write_file_tags
from packages.infrastructure.receipt_collector import answer_receipt_rows
from packages.infrastructure.saved_files import count_saved_files
from packages.infrastructure.saved_files import describe_saved_file_records
from packages.infrastructure.saved_files import describe_months_read
from packages.infrastructure.saved_files import describe_saved_folder
from packages.infrastructure.saved_files import list_folder_files
from packages.infrastructure.saved_files import read_bundle_rows
from packages.infrastructure.saved_files import select_saved_rows
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import build_agent_receipt_owner_key
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.receipt_collector import normalize_receipt_output_folder
from packages.infrastructure.receipt_collector import resolve_receipt_bundle_folder


def write_bundle(folder: Path, receipts: list[dict], metadata: dict | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bundle.json").write_text(
        json.dumps({"metadata": metadata or {}, "receipts": receipts, "skipped": []}),
        encoding="utf-8",
    )


class SavedFolderReadingTests(unittest.TestCase):
    def test_a_filed_folder_still_holds_the_rows_it_was_counted_from(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Render"
            write_bundle(folder, [
                {"vendor": "Render", "amount": "20.00", "currency": "USD", "date": "1 Aug 2026"},
                {"vendor": "Render", "amount": "20.00", "currency": "USD", "date": "1 Sep 2026"},
            ])

            rows = read_bundle_rows(folder)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["vendor"], "Render")

    def test_a_folder_with_no_manifest_reads_as_one_with_no_figures(self) -> None:
        # Folders can be made by hand. Not knowing what the files cost is a
        # true answer; refusing to look at the folder is not.
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Handmade"
            folder.mkdir()
            (folder / "note.pdf").write_bytes(b"%PDF-1.4")

            described = describe_saved_folder(folder, folder="Handmade")

        self.assertEqual(described["receipts"], [])
        self.assertEqual(described["fileCount"], 1)
        self.assertEqual(described["files"][0]["name"], "note.pdf")

    def test_a_manifest_edited_into_nonsense_loses_the_figures_not_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Broken"
            folder.mkdir()
            (folder / "bundle.json").write_text("{not json", encoding="utf-8")
            (folder / "receipt.pdf").write_bytes(b"%PDF-1.4")

            described = describe_saved_folder(folder, folder="Broken")

        self.assertEqual(described["receipts"], [])
        self.assertEqual(described["fileCount"], 1)

    def test_the_listing_leaves_out_the_files_that_describe_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Render"
            write_bundle(folder, [])
            (folder / "receipt-report.pdf").write_bytes(b"%PDF-1.4")
            (folder / "attachments").mkdir()
            (folder / "attachments" / "aug.pdf").write_bytes(b"%PDF-1.4")
            write_file_tags(folder, {"attachments/aug.pdf": ["Render", "Aug", "2026", "Receipt"]})

            files = list_folder_files(folder)

        names = [item["name"] for item in files]
        self.assertNotIn("bundle.json", names)
        self.assertNotIn("tags.json", names)
        self.assertIn("attachments/aug.pdf", names)
        self.assertIn("receipt-report.pdf", names)

    def test_a_file_keeps_the_tags_it_was_filed_under(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Render"
            folder.mkdir()
            (folder / "aug.pdf").write_bytes(b"%PDF-1.4")
            write_file_tags(folder, {"aug.pdf": ["Render", "Aug", "2026", "Receipt"]})

            files = list_folder_files(folder)

        self.assertEqual(files[0]["tags"], ["Render", "Aug", "2026", "Receipt"])

    def test_a_folder_that_is_not_there_is_empty_rather_than_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            described = describe_saved_folder(Path(raw) / "Gone", folder="Gone")

        self.assertEqual(described["fileCount"], 0)
        self.assertEqual(described["receipts"], [])

    def test_the_folder_carries_what_the_run_was_looking_for(self) -> None:
        # Every file in a receipt folder is called whatever the vendor called
        # it, so what the run searched for is the honest answer to "what is in
        # here".
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Aug2026"
            write_bundle(folder, [], {"query": "receipts after 2026/08/01", "monthLabel": "August 2026"})

            described = describe_saved_folder(folder, folder="Receipts/Aug2026")

        self.assertEqual(described["query"], "receipts after 2026/08/01")
        self.assertEqual(described["monthLabel"], "August 2026")


class SavedRowSelectionTests(unittest.TestCase):
    ROWS = [
        {"vendor": "Render", "subject": "Your receipt from Render", "amount": "20.00", "currency": "USD"},
        {"vendor": "Render", "subject": "Invoice 8891", "amount": "35.00", "currency": "USD"},
        {"vendor": "Fastly", "subject": "Your receipt", "amount": "10.00", "currency": "USD"},
    ]

    def test_asking_for_invoices_leaves_the_receipts_out(self) -> None:
        rows = select_saved_rows(self.ROWS, kind="invoices")

        self.assertEqual([row["subject"] for row in rows], ["Invoice 8891"])

    def test_asking_for_receipts_keeps_everything_in_the_folder(self) -> None:
        # "Receipts" is what people call everything in a folder of them.
        # Reading it as "the ones that are not invoices" dropped the largest
        # charge of the month out of the total, and said nothing about it.
        rows = select_saved_rows(self.ROWS, kind="receipts")

        self.assertEqual(len(rows), 3)
        self.assertIn("Invoice 8891", [row["subject"] for row in rows])

    def test_an_invoice_is_decided_by_what_the_subject_calls_it(self) -> None:
        # The word turning up in a body or a note is not the document calling
        # itself an invoice, and the tags on the filed files agree.
        rows = select_saved_rows(
            [
                {"vendor": "Render", "subject": "Your receipt", "detail": "see invoice attached"},
                {"vendor": "Apple", "subject": "Invoice 8891", "detail": ""},
            ],
            kind="invoices",
        )

        self.assertEqual([row["vendor"] for row in rows], ["Apple"])

    def test_no_narrowing_keeps_everything(self) -> None:
        self.assertEqual(len(select_saved_rows(self.ROWS)), 3)


class MonthsReadTests(unittest.TestCase):
    """The period an answer covers, when it covers more than one folder."""

    def test_one_folder_keeps_its_own_month(self) -> None:
        self.assertEqual(
            describe_months_read([{"monthLabel": "August 2026"}]),
            "August 2026",
        )

    def test_two_folders_name_both_months(self) -> None:
        # Putting the first folder's month on the whole answer said "you paid
        # 40.00 in July" over a total that was half August.
        self.assertEqual(
            describe_months_read([{"monthLabel": "July 2026"}, {"monthLabel": "August 2026"}]),
            "July 2026 and August 2026",
        )

    def test_three_folders_read_as_a_list(self) -> None:
        self.assertEqual(
            describe_months_read([
                {"monthLabel": "June 2026"},
                {"monthLabel": "July 2026"},
                {"monthLabel": "August 2026"},
            ]),
            "June 2026, July 2026 and August 2026",
        )

    def test_the_same_month_twice_is_said_once(self) -> None:
        self.assertEqual(
            describe_months_read([{"monthLabel": "August 2026"}, {"monthLabel": "August 2026"}]),
            "August 2026",
        )

    def test_a_folder_with_no_month_leaves_the_answer_without_one(self) -> None:
        # Borrowing its neighbour's month would name a period that half the
        # money is not in. No period at all is the honest answer.
        self.assertEqual(
            describe_months_read([{"monthLabel": "July 2026"}, {"monthLabel": ""}]),
            "",
        )
        self.assertEqual(describe_months_read([]), "")


class SavedAnswerTests(unittest.TestCase):
    def test_a_folder_answers_the_same_question_the_mailbox_did(self) -> None:
        # The rows came out of a folder rather than a search, and everything
        # after that is the receipt code that was already there.
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "Render"
            write_bundle(folder, [
                {
                    "vendor": "Render",
                    "subject": "Your receipt from Render",
                    "amount": "20.00",
                    "currency": "USD",
                    "date": "Fri, 1 Aug 2026 09:00:00 +0000",
                    "status": "Ready",
                },
                {
                    "vendor": "Render",
                    "subject": "Your receipt from Render",
                    "amount": "35.50",
                    "currency": "USD",
                    "date": "Mon, 11 Aug 2026 09:00:00 +0000",
                    "status": "Ready",
                },
            ])

            answer = answer_receipt_rows(
                read_bundle_rows(folder),
                vendor="Render",
                month_label="August 2026",
            )

        self.assertEqual(answer["receiptCount"], 2)
        self.assertEqual(answer["totals"], {"USD": 55.5})
        self.assertIn("55.50 USD", answer["answer"])
        self.assertIn("August 2026", answer["answer"])
        self.assertEqual(answer["questions"], [])

    def test_an_empty_folder_says_so_rather_than_naming_a_total(self) -> None:
        answer = answer_receipt_rows([], vendor="Render", month_label="August 2026")

        self.assertEqual(answer["receiptCount"], 0)
        self.assertIn("couldn't find", answer["answer"])


class SavedFileRecordTests(unittest.TestCase):
    def test_the_files_are_described_one_line_each(self) -> None:
        records = describe_saved_file_records([
            {
                "folder": "Receipts/Aug2026",
                "files": [
                    {"name": "attachments/aug.pdf", "tags": ["Render", "Aug"]},
                    {"name": "receipt-report.pdf"},
                    {"name": ""},
                ],
            },
        ])

        self.assertEqual(records, [
            {"file": "attachments/aug.pdf", "folder": "Receipts/Aug2026", "tags": "Render, Aug"},
            {"file": "receipt-report.pdf", "folder": "Receipts/Aug2026"},
        ])

    def test_the_files_of_every_folder_are_counted_together(self) -> None:
        self.assertEqual(
            count_saved_files([{"fileCount": 3}, {"fileCount": 2}, {}]),
            5,
        )


class SavedFilesRunnerTests(unittest.TestCase):
    """The chat asking a folder a question, over the real endpoint."""

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
                session_secret="test-session-secret-that-is-long-enough-to-sign",
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
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _folder(self, name: str) -> Path:
        return resolve_receipt_bundle_folder(
            self.output_dir,
            owner_key=build_agent_receipt_owner_key("owner@example.com"),
            output_folder=normalize_receipt_output_folder(name),
        )

    def _ask(self, fields: dict, expect: int = 200) -> dict:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/proposals/run",
            data=json.dumps({
                "proposalType": "saved-files",
                "mode": "answer",
                "fields": fields,
                "timezone": "Asia/Jerusalem",
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                self.assertEqual(response.status, expect)
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as error:
            self.assertEqual(error.code, expect)
            return json.loads(error.read().decode("utf-8"))

    def test_a_folder_answers_without_the_mailbox_being_touched(self) -> None:
        # Nothing is connected in this test at all. The receipts were filed
        # once and the folder is the whole source.
        folder = self._folder("Receipts/Aug2026")
        write_bundle(folder, [
            {
                "vendor": "Render",
                "subject": "Your receipt from Render",
                "amount": "20.00",
                "currency": "USD",
                "date": "Fri, 1 Aug 2026 09:00:00 +0000",
                "status": "Ready",
            },
            {
                "vendor": "Fastly",
                "subject": "Your receipt from Fastly",
                "amount": "10.00",
                "currency": "USD",
                "date": "Mon, 11 Aug 2026 09:00:00 +0000",
                "status": "Ready",
            },
        ], {"monthLabel": "August 2026"})

        payload = self._ask({"savedFolder": "Receipts/Aug2026"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["receiptCount"], 2)
        self.assertEqual(payload["totals"], {"USD": 30.0})
        self.assertIn("30.00 USD", payload["answer"])
        self.assertEqual(len(payload["answerRecords"]), 2)

    def test_a_vendor_narrows_the_answer_the_folder_gives(self) -> None:
        folder = self._folder("Receipts/Aug2026")
        write_bundle(folder, [
            {"vendor": "Render", "subject": "receipt", "amount": "20.00", "currency": "USD", "status": "Ready"},
            {"vendor": "Fastly", "subject": "receipt", "amount": "10.00", "currency": "USD", "status": "Ready"},
        ])

        payload = self._ask({"savedFolder": "Receipts/Aug2026", "vendor": "Render"})

        self.assertEqual(payload["receiptCount"], 1)
        self.assertEqual(payload["totals"], {"USD": 20.0})

    def test_two_folders_are_read_as_one_question(self) -> None:
        for name, amount in (("Receipts/Jul2026", "15.00"), ("Receipts/Aug2026", "25.00")):
            write_bundle(self._folder(name), [
                {"vendor": "Render", "subject": "receipt", "amount": amount, "currency": "USD", "status": "Ready"},
            ])

        payload = self._ask({"savedFolder": "Receipts/Jul2026, Receipts/Aug2026"})

        self.assertEqual(payload["receiptCount"], 2)
        self.assertEqual(payload["totals"], {"USD": 40.0})

    def test_two_folders_are_answered_for_both_their_months(self) -> None:
        for name, month, amount in (
            ("Receipts/Jul2026", "July 2026", "15.00"),
            ("Receipts/Aug2026", "August 2026", "25.00"),
        ):
            write_bundle(
                self._folder(name),
                [{"vendor": "Render", "subject": "receipt", "amount": amount,
                  "currency": "USD", "status": "Ready"}],
                {"monthLabel": month},
            )

        payload = self._ask({"savedFolder": "Receipts/Jul2026, Receipts/Aug2026"})

        self.assertEqual(payload["totals"], {"USD": 40.0})
        self.assertIn("July 2026 and August 2026", payload["answer"])

    def test_a_question_about_receipts_counts_the_invoices_in_the_folder(self) -> None:
        # "Receipts" is what the folder is called and what everything in it
        # gets called. Reading it as "not the invoices" dropped the largest
        # charge of the month and said nothing.
        write_bundle(self._folder("Receipts/Aug2026"), [
            {"vendor": "Render", "subject": "Your receipt from Render", "amount": "20.00",
             "currency": "USD", "status": "Ready"},
            {"vendor": "Apple", "subject": "Invoice 8891", "amount": "199.90",
             "currency": "USD", "status": "Ready"},
        ])

        payload = self._ask({"savedFolder": "Receipts/Aug2026", "documentKind": "receipts"})

        self.assertEqual(payload["receiptCount"], 2)
        self.assertEqual(payload["totals"], {"USD": 219.9})

    def test_a_question_about_invoices_still_narrows_to_them(self) -> None:
        write_bundle(self._folder("Receipts/Aug2026"), [
            {"vendor": "Render", "subject": "Your receipt from Render", "amount": "20.00",
             "currency": "USD", "status": "Ready"},
            {"vendor": "Apple", "subject": "Invoice 8891", "amount": "199.90",
             "currency": "USD", "status": "Ready"},
        ])

        payload = self._ask({"savedFolder": "Receipts/Aug2026", "documentKind": "invoices"})

        self.assertEqual(payload["receiptCount"], 1)
        self.assertEqual(payload["totals"], {"USD": 199.9})

    def test_a_handmade_folder_names_its_files_instead_of_a_total(self) -> None:
        # No manifest, so there is nothing to add up. Saying what is in there
        # is still an answer; inventing a figure would not be.
        folder = self._folder("Contracts")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "lease.pdf").write_bytes(b"%PDF-1.4")

        payload = self._ask({"savedFolder": "Contracts"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["fileCount"], 1)
        self.assertNotIn("receiptCount", payload)
        self.assertIn("no amounts", payload["answer"])
        self.assertEqual(payload["answerRecords"][0]["file"], "lease.pdf")

    def test_a_folder_that_was_never_filed_says_it_is_empty(self) -> None:
        payload = self._ask({"savedFolder": "Nothing"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["fileCount"], 0)
        self.assertIn("couldn't find", payload["answer"])

    def test_a_question_with_no_folder_asks_rather_than_guessing(self) -> None:
        # Reading whichever folder happens to be first would answer a question
        # nobody asked.
        payload = self._ask({}, expect=400)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "folder_required")

    def test_one_account_cannot_read_another_account_folder(self) -> None:
        # The owner key comes from the session, so a folder name that climbs
        # out of it lands back inside it.
        other = resolve_receipt_bundle_folder(
            self.output_dir,
            owner_key=build_agent_receipt_owner_key("someone@example.com"),
            output_folder=normalize_receipt_output_folder("Receipts/Aug2026"),
        )
        write_bundle(other, [
            {"vendor": "Render", "subject": "receipt", "amount": "99.00", "currency": "USD", "status": "Ready"},
        ])

        payload = self._ask({"savedFolder": "../../someone_at_example.com/Receipts/Aug2026"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload.get("fileCount"), 0)
        self.assertNotIn("99.00", payload["answer"])


if __name__ == "__main__":
    unittest.main()
