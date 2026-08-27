from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from datetime import timezone
from pathlib import Path

from packages.infrastructure.receipt_collector import create_receipt_bundle
from packages.infrastructure.receipt_collector import normalize_receipt_output_folder


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


if __name__ == "__main__":
    unittest.main()
