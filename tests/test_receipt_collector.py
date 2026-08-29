from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from datetime import timezone
from pathlib import Path

from packages.infrastructure.receipt_collector import build_receipt_spend_view
from packages.infrastructure.receipt_collector import create_receipt_bundle
from packages.infrastructure.receipt_collector import extract_receipt_rows
from packages.infrastructure.receipt_collector import normalize_receipt_output_folder
from packages.infrastructure.receipt_collector import split_receipt_rows
from packages.infrastructure.receipt_collector import summarize_receipt_rows


class ReceiptCollectorExportTests(unittest.TestCase):
    def test_normalizes_default_month_folder(self) -> None:
        self.assertEqual(
            normalize_receipt_output_folder("", month_value=(2026, 8)),
            "Receipts/Aug2026/",
        )

    def test_replaces_recurring_run_month_placeholder(self) -> None:
        self.assertEqual(
            normalize_receipt_output_folder("Receipts/{RunMonth}/", month_value=(2026, 8)),
            "Receipts/Aug2026/",
        )

    def test_sanitizes_folder_traversal(self) -> None:
        self.assertEqual(
            normalize_receipt_output_folder("../Receipts//Aug 2026/../../private", month_value=(2026, 8)),
            "Receipts/Aug 2026/private/",
        )

    def test_create_receipt_bundle_writes_pdf_xlsx_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "receipt.png"
            image_path.write_bytes(b"not-a-real-image-but-saved")
            bundle = create_receipt_bundle(
                [{
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "from": "Store <receipts@example.com>",
                    "subject": "Receipt from Store",
                    "date": "Thu, 27 Aug 2026 08:15:00 +0000",
                    "snippet": "Thank you for your order. Total USD 42.10",
                    "attachments": [{
                        "filename": "receipt.png",
                        "mimeType": "image/png",
                        "path": str(image_path),
                        "url": "/output/agent_receipts/owner-key/Receipts/Aug2026/attachments/receipt.png",
                        "status": "saved",
                    }],
                }],
                output_root=Path(temp_dir),
                owner_key="owner-key",
                output_folder="Receipts/{RunMonth}/",
                month_value=(2026, 8),
                query="after:2026/08/01 before:2026/09/01 receipt",
                created_at=datetime(2026, 8, 27, 12, tzinfo=timezone.utc),
            )

            self.assertEqual(bundle["outputFolder"], "Receipts/Aug2026/")
            self.assertEqual(bundle["receiptCount"], 1)
            excel_path = Path(bundle["artifacts"]["excel"]["path"])
            pdf_path = Path(bundle["artifacts"]["pdf"]["path"])
            manifest_path = Path(bundle["artifacts"]["manifest"]["path"])
            self.assertTrue(excel_path.exists())
            self.assertTrue(pdf_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertEqual(pdf_path.read_bytes()[:4], b"%PDF")

            with zipfile.ZipFile(excel_path) as workbook:
                self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
                worksheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIn("Receipt from Store", worksheet)
                self.assertIn("42.10", worksheet)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["metadata"]["outputFolder"], "Receipts/Aug2026/")
            self.assertEqual(manifest["receipts"][0]["vendor"], "Store")
            self.assertEqual(manifest["receipts"][0]["attachmentCount"], "1")
            self.assertEqual(manifest["receipts"][0]["imageAttachments"][0]["filename"], "receipt.png")


class ReceiptAmountTests(unittest.TestCase):
    def row_for(self, **fields: str) -> dict[str, str]:
        source = {"id": "msg-1", "from": "Store <billing@store.example.com>", "subject": "Receipt"}
        source.update(fields)
        return extract_receipt_rows([source])[0]

    def test_reads_the_total_from_the_message_body(self) -> None:
        row = self.row_for(
            snippet="Thanks for your order",
            bodyText="Item A 30.00 USD Item B 15.00 USD Order total USD 45.00",
        )
        self.assertEqual((row["amount"], row["currency"]), ("45.00", "USD"))
        self.assertEqual(row["status"], "Ready")

    def test_prefers_the_total_over_earlier_line_items(self) -> None:
        row = self.row_for(bodyText="Subtotal 30.00 ILS VAT 7.00 ILS Total " + chr(8362) + "37.00")
        self.assertEqual((row["amount"], row["currency"]), ("37.00", "ILS"))

    def test_reads_currency_symbols(self) -> None:
        for text, expected in (
            ("Total charged " + chr(163) + "19.90", ("19.90", "GBP")),
            ("Amount due " + chr(8364) + "1,234.50", ("1234.50", "EUR")),
            ("Order total: $12.34", ("12.34", "USD")),
            ("You paid NIS 71.80", ("71.80", "ILS")),
        ):
            with self.subTest(text=text):
                row = self.row_for(bodyText=text)
                self.assertEqual((row["amount"], row["currency"]), expected)

    def test_falls_back_to_the_first_amount_when_no_total_is_labelled(self) -> None:
        row = self.row_for(bodyText="Your card was billed 24.90 ILS this morning")
        self.assertEqual((row["amount"], row["currency"]), ("24.90", "ILS"))

    def test_flags_a_message_with_no_amount_for_review(self) -> None:
        row = self.row_for(snippet="Your subscription renews soon", bodyText="No numbers worth reading here")
        self.assertEqual(row["amount"], "")
        self.assertEqual(row["status"], "Needs review")
        self.assertIn("No amount detected", row["notes"])


class ReceiptSummaryTests(unittest.TestCase):
    def message(self, vendor: str, amount: str, day: str, month: str = "Aug") -> dict[str, str]:
        return {
            "id": f"msg-{vendor}-{day}",
            "from": f"{vendor} <billing@{vendor.lower()}.example.com>",
            "subject": "Receipt",
            "snippet": f"Total {amount}" if amount else "Nothing to see here",
            "date": f"Mon, {day} {month} 2026 09:00:00 +0000",
        }

    def test_summarizes_spend_by_vendor_and_currency(self) -> None:
        summary = summarize_receipt_rows(extract_receipt_rows([
            self.message("Apple", "ILS 19.90", "02"),
            self.message("Apple", "ILS 30.10", "04"),
            self.message("Wild", "USD 12.00", "06"),
            self.message("Quiet", "", "08"),
        ]))
        self.assertEqual(summary["totals"], {"ILS": 50.0, "USD": 12.0})
        self.assertEqual(summary["vendorSpend"]["ILS"]["Apple"], {"amount": 50.0, "count": 2})
        self.assertEqual(summary["missingAmountCount"], 1)
        self.assertEqual(summary["vendorCounts"]["Apple"], 2)

    def test_ranks_vendors_and_carries_last_month_alongside(self) -> None:
        summary = summarize_receipt_rows(extract_receipt_rows([
            self.message("Apple", "ILS 80.00", "02"),
            self.message("Wild", "ILS 20.00", "04"),
        ]))
        previous = summarize_receipt_rows(extract_receipt_rows([
            self.message("Apple", "ILS 50.00", "02", "Jul"),
            self.message("Gone", "ILS 40.00", "04", "Jul"),
        ]))
        view = build_receipt_spend_view(summary, previous)

        self.assertEqual(view["currency"], "ILS")
        self.assertEqual(view["total"], 100.0)
        self.assertEqual(view["previousTotal"], 90.0)
        entries = {entry["vendor"]: entry for entry in view["entries"]}
        self.assertEqual([entry["vendor"] for entry in view["entries"]][:2], ["Apple", "Wild"])
        self.assertEqual(entries["Apple"]["share"], 80.0)
        self.assertEqual(entries["Apple"]["previous"], 50.0)
        # A vendor we stopped paying still shows up, so the drop is visible.
        self.assertEqual(entries["Gone"]["amount"], 0.0)
        self.assertEqual(entries["Gone"]["previous"], 40.0)

    def test_reads_last_month_bundle_for_the_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for month, day, amount in ((7, "05", "ILS 40.00"), (8, "05", "ILS 55.00")):
                bundle = create_receipt_bundle(
                    [self.message("Apple", amount, day, "Jul" if month == 7 else "Aug")],
                    output_root=root,
                    owner_key="owner-key",
                    output_folder="Receipts/{RunMonth}/",
                    month_value=(2026, month),
                    query="receipt",
                    created_at=datetime(2026, month, 28, tzinfo=timezone.utc),
                )
            metadata = json.loads(Path(bundle["artifacts"]["manifest"]["path"]).read_text(encoding="utf-8"))["metadata"]

            self.assertEqual(metadata["monthLabel"], "Aug 2026")
            self.assertEqual(metadata["summary"]["totals"], {"ILS": 55.0})
            self.assertEqual(metadata["previous"]["monthLabel"], "Jul 2026")
            self.assertEqual(metadata["previous"]["totals"], {"ILS": 40.0})

    def test_skips_the_comparison_when_last_month_has_no_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = create_receipt_bundle(
                [self.message("Apple", "ILS 55.00", "05")],
                output_root=Path(temp_dir),
                owner_key="owner-key",
                output_folder="Receipts/{RunMonth}/",
                month_value=(2026, 8),
                query="receipt",
                created_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
            )
            metadata = json.loads(Path(bundle["artifacts"]["manifest"]["path"]).read_text(encoding="utf-8"))["metadata"]
            self.assertNotIn("previous", metadata)

class ReceiptClassificationTests(unittest.TestCase):
    """The search net is broad, so what comes back still has to be checked."""

    NDA_BODY = (
        "Hi nimrod shai, Thanks for signing your NDA with Wild - a copy is attached. "
        "You can also re-download it for the next 30 days at: "
        "https://office.wild.co/signed/d94582c0-27a1-47a5-baf5-ff5c74e2e4ee - Wild"
    )

    def rows_for(self, *sources: dict) -> list[dict]:
        return extract_receipt_rows(list(sources))

    def test_a_signed_agreement_is_not_a_receipt(self) -> None:
        # Gmail matched this on the words inside the attached PDF, not the email.
        row = self.rows_for({
            "id": "msg-1",
            "from": "noreply@office.wild.co",
            "subject": "Your signed NDA with Wild",
            "snippet": "Thanks for signing your NDA with Wild",
            "bodyText": self.NDA_BODY,
            "attachments": [{"filename": "nda-signed.pdf", "path": "/tmp/nda-signed.pdf", "mimeType": "application/pdf"}],
        })[0]
        self.assertEqual(row["status"], "Not a receipt")
        self.assertIn("nothing like a receipt", row["notes"])

    def test_keeps_a_receipt_whose_total_is_only_in_the_attachment(self) -> None:
        row = self.rows_for({
            "id": "msg-2",
            "from": "Atlassian <noreply@po.atlassian.net>",
            "subject": "Your invoice is ready",
            "bodyText": "Your invoice is attached.",
        })[0]
        self.assertEqual(row["status"], "Needs review")

    def test_keeps_anything_naming_an_amount(self) -> None:
        row = self.rows_for({
            "id": "msg-3",
            "from": "Apple <no_reply@email.apple.com>",
            "subject": "Your receipt from Apple",
            "snippet": "Total ILS 40.00",
        })[0]
        self.assertEqual(row["status"], "Ready")

    def test_split_renumbers_each_list_from_one(self) -> None:
        rows = self.rows_for(
            {"id": "a", "from": "noreply@office.wild.co", "subject": "Your signed NDA with Wild", "bodyText": self.NDA_BODY},
            {"id": "b", "from": "Apple <no_reply@email.apple.com>", "subject": "Your receipt", "snippet": "Total ILS 40.00"},
            {"id": "c", "from": "PayPal <service@paypal.co.il>", "subject": "Payment sent", "snippet": "You paid ILS 71.80"},
        )
        receipts, skipped = split_receipt_rows(rows)
        self.assertEqual([row["index"] for row in receipts], ["1", "2"])
        self.assertEqual([row["index"] for row in skipped], ["1"])
        self.assertEqual(skipped[0]["subject"], "Your signed NDA with Wild")

    def test_bundle_leaves_non_receipts_out_of_the_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = create_receipt_bundle(
                [
                    {"id": "a", "from": "noreply@office.wild.co", "subject": "Your signed NDA with Wild", "bodyText": self.NDA_BODY},
                    {"id": "b", "from": "Apple <no_reply@email.apple.com>", "subject": "Your receipt", "snippet": "Total ILS 40.00"},
                ],
                output_root=Path(temp_dir),
                owner_key="owner@example.com",
                month_value=(2026, 7),
                created_at=datetime(2026, 8, 29, 10, 34, tzinfo=timezone.utc),
            )
            self.assertEqual(bundle["receiptCount"], 1)
            self.assertEqual(bundle["skippedCount"], 1)

            manifest = json.loads((Path(bundle["folderPath"]) / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["receipts"]), 1)
            self.assertEqual(manifest["skipped"][0]["subject"], "Your signed NDA with Wild")
            self.assertEqual(manifest["metadata"]["summary"]["receiptCount"], 1)


if __name__ == "__main__":
    unittest.main()
