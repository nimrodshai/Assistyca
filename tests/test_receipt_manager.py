"""The receipt manager: what a search pulled, kept, questioned, and exported.

What these prove: a search's rows land in the store once, however many
times the search runs; a reading the judge was not sure about is kept as a
question and never as a total; the owner's yes, no, kind and amount outlive
the next search; the file the vendor attached is fetched when the run did
not save it; the figures are worked out in code, per currency; and the
exports carry the confirmed receipts in a period and nothing else.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import receipt_manager
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import _run_lookup
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import resolve_static_page_alias
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.receipt_collector import answer_receipt_question
from packages.infrastructure.receipt_collector import extract_receipt_rows
from packages.infrastructure.receipt_judge import normalize_receipt_verdict


def message(
    message_id: str,
    *,
    sender: str = "Render <billing@render.com>",
    subject: str = "Your receipt from Render",
    body: str = "Thanks for your payment. Total charged: $25.00",
    date: str = "Fri, 14 Aug 2026 09:00:00 +0000",
    verdict: dict | None = None,
    attachment_names: list[str] | None = None,
) -> dict:
    item = {
        "id": message_id,
        "from": sender,
        "subject": subject,
        "bodyText": body,
        "snippet": body[:60],
        "date": date,
        "mailbox": "owner@gmail.com",
    }
    if verdict is not None:
        item["receiptVerdict"] = verdict
    if attachment_names is not None:
        item["attachmentNames"] = attachment_names
    return item


class ReadingTests(unittest.TestCase):
    def test_a_row_the_search_counted_is_a_confirmed_receipt(self) -> None:
        row = extract_receipt_rows([message("m1", verdict={"isReceipt": True, "confidence": "high"})])[0]
        self.assertEqual(receipt_manager.classify_collected_row(row), "confirmed")
        record = receipt_manager.build_receipt_record(row)
        self.assertEqual((record["vendor"], record["amount"], record["currency"]), ("Render", "25.00", "USD"))
        self.assertEqual(record["receiptDate"], "2026-08-14")
        self.assertEqual(record["kind"], "receipt")

    def test_a_reading_the_judge_was_not_sure_of_is_a_question_not_a_total(self) -> None:
        unsure_yes = extract_receipt_rows([message("m1", verdict={"isReceipt": True, "confidence": "low", "reason": "possibly an order note"})])[0]
        unsure_no = extract_receipt_rows([message("m2", verdict={"isReceipt": False, "confidence": "low", "reason": "possibly a receipt"})])[0]
        sure_no = extract_receipt_rows([message("m3", verdict={"isReceipt": False, "confidence": "high", "reason": "a sale announcement"})])[0]
        self.assertEqual(receipt_manager.classify_collected_row(unsure_yes), "unsure")
        self.assertEqual(receipt_manager.classify_collected_row(unsure_no), "unsure")
        self.assertEqual(receipt_manager.classify_collected_row(sure_no), "")
        self.assertEqual(receipt_manager.build_receipt_record(unsure_no)["reason"], "possibly a receipt")

    def test_the_judge_reads_confidence_and_stands_by_silence(self) -> None:
        self.assertEqual(normalize_receipt_verdict({"isReceipt": True, "confidence": "low"})["confidence"], "low")
        self.assertEqual(normalize_receipt_verdict({"isReceipt": True})["confidence"], "high")
        self.assertEqual(normalize_receipt_verdict({"isReceipt": True, "confidence": "shrug"})["confidence"], "high")

    def test_an_invoice_is_told_from_a_receipt_by_its_own_words(self) -> None:
        invoice = extract_receipt_rows([message("m1", subject="Invoice #4411 from Render", verdict={"isReceipt": True})])[0]
        receipt = extract_receipt_rows([message("m2", subject="Your order", attachment_names=["receipt-4411.pdf"], verdict={"isReceipt": True})])[0]
        plain = extract_receipt_rows([message("m3", subject="Payment confirmation", verdict={"isReceipt": True})])[0]
        self.assertEqual(receipt_manager.describe_row_kind(invoice), "invoice")
        self.assertEqual(receipt_manager.describe_row_kind(receipt), "receipt")
        self.assertEqual(receipt_manager.describe_row_kind(plain), "receipt")

    def test_the_answer_carries_every_row_it_read_not_only_the_vendors(self) -> None:
        items = [
            message("m1", verdict={"isReceipt": True}),
            message("m2", sender="Apple <no_reply@apple.com>", subject="Your receipt from Apple", body="Total ILS 39.90", verdict={"isReceipt": True}),
            message("m3", sender="Shop <deals@shop.com>", subject="Sale", body="Save $5", verdict={"isReceipt": False, "confidence": "low"}),
        ]
        answer = answer_receipt_question(items, vendor="Render")
        self.assertEqual(answer["receiptCount"], 1)
        self.assertEqual({row["sourceRef"] for row in answer["rows"]}, {"m1", "m2"})
        self.assertEqual([row["sourceRef"] for row in answer["skippedRows"]], ["m3"])


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)

    def _rows(self, *items: dict) -> tuple[list[dict], list[dict]]:
        answer = answer_receipt_question(list(items))
        return answer["rows"], answer["skippedRows"]

    def test_a_search_run_twice_keeps_each_receipt_once(self) -> None:
        rows, skipped = self._rows(message("m1", verdict={"isReceipt": True}), message("m2", verdict={"isReceipt": False, "confidence": "low"}))
        first = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        second = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        self.assertEqual((first["stored"], first["added"], first["unsure"]), (2, 2, 1))
        self.assertEqual((second["stored"], second["added"]), (2, 0))
        self.assertEqual(len(self.database.list_account_receipts(user_id=self.user_id)), 2)

    def test_the_owners_ruling_outlives_the_next_search(self) -> None:
        rows, skipped = self._rows(message("m1", verdict={"isReceipt": False, "confidence": "low"}))
        stored = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        receipt_id = stored["records"][0]["id"]
        self.database.update_account_receipt(user_id=self.user_id, receipt_id=receipt_id, status="confirmed", kind="invoice")
        self.database.update_account_receipt(user_id=self.user_id, receipt_id=receipt_id, amount="31.50", currency="EUR")

        receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        record = self.database.get_account_receipt(user_id=self.user_id, receipt_id=receipt_id)
        self.assertEqual((record["status"], record["kind"]), ("confirmed", "invoice"))
        self.assertEqual((record["amount"], record["currency"], record["manualAmount"]), ("31.50", "EUR", True))

    def test_a_no_is_remembered_so_the_email_is_never_asked_about_twice(self) -> None:
        rows, skipped = self._rows(message("m1", verdict={"isReceipt": True, "confidence": "low"}))
        stored = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        self.database.update_account_receipt(user_id=self.user_id, receipt_id=stored["records"][0]["id"], status="rejected")
        again = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        self.assertEqual(again["unsure"], 0)
        self.assertEqual(again["records"][0]["status"], "rejected")

    def test_the_file_the_vendor_attached_is_fetched_when_the_run_did_not_save_it(self) -> None:
        rows, skipped = self._rows(
            message("m1", verdict={"isReceipt": True}, attachment_names=["receipt.pdf"]),
            message("m2", subject="Payment received", verdict={"isReceipt": True}, attachment_names=[]),
        )
        asked: list[str] = []

        def fetch(record: dict) -> list[dict]:
            asked.append(record["messageId"])
            return [{"filename": "receipt.pdf", "mimeType": "application/pdf", "size": 1200, "status": "saved", "url": "/output/agent_receipts/k/Receipt manager/2026-08/receipt.pdf"}]

        outcome = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped, fetch_files=fetch)
        self.assertEqual(asked, ["m1"])
        self.assertEqual(outcome["filesSaved"], 1)
        kept = self.database.find_account_receipt_by_message(user_id=self.user_id, message_id="m1")
        self.assertEqual(kept["attachments"][0]["filename"], "receipt.pdf")

        # A second search finds the file already there and does not fetch again.
        asked.clear()
        receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped, fetch_files=fetch)
        self.assertEqual(asked, [])

    def test_a_file_the_run_saved_itself_is_kept_as_it_is(self) -> None:
        item = message("m1", subject="Your order from Render", verdict={"isReceipt": True})
        item["attachments"] = [{"filename": "invoice.pdf", "mimeType": "application/pdf", "size": 900, "status": "saved", "url": "/output/agent_receipts/k/Receipts/Aug2026/attachments/invoice.pdf", "path": "/x/invoice.pdf"}]
        rows, skipped = self._rows(item)
        outcome = receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped, fetch_files=lambda record: self.fail("fetched a file the run had saved"))
        self.assertEqual(outcome["records"][0]["attachments"][0]["url"], "/output/agent_receipts/k/Receipts/Aug2026/attachments/invoice.pdf")
        self.assertEqual(outcome["records"][0]["kind"], "invoice")

    def test_a_range_keeps_dated_receipts_inside_it(self) -> None:
        rows, skipped = self._rows(
            message("m1", verdict={"isReceipt": True}, date="Fri, 14 Aug 2026 09:00:00 +0000"),
            message("m2", verdict={"isReceipt": True}, date="Wed, 1 Jul 2026 09:00:00 +0000"),
            message("m3", verdict={"isReceipt": True}, date=""),
        )
        receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        august = self.database.list_account_receipts(user_id=self.user_id, date_from="2026-08-01", date_to="2026-08-31")
        self.assertEqual([record["messageId"] for record in august], ["m1"])
        everything = self.database.list_account_receipts(user_id=self.user_id)
        self.assertEqual([record["messageId"] for record in everything], ["m1", "m2", "m3"])

    def test_the_figures_are_per_currency_and_only_for_confirmed_receipts(self) -> None:
        records = [
            {"status": "confirmed", "kind": "receipt", "amount": "25.00", "currency": "USD", "receiptDate": "2026-08-14", "vendor": "Render"},
            {"status": "confirmed", "kind": "invoice", "amount": "100", "currency": "ILS", "receiptDate": "2026-08-02", "vendor": "Bezeq"},
            {"status": "confirmed", "kind": "receipt", "amount": "", "currency": "", "receiptDate": "2026-07-02", "vendor": "Cafe"},
            {"status": "unsure", "kind": "receipt", "amount": "999", "currency": "USD", "receiptDate": "2026-08-20", "vendor": "Shop"},
            {"status": "rejected", "kind": "receipt", "amount": "5", "currency": "USD", "receiptDate": "2026-08-21", "vendor": "Ad"},
        ]
        summary = receipt_manager.summarize_receipt_records(records)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["totals"], {"ILS": 100.0, "USD": 25.0})
        self.assertEqual(summary["byKind"]["invoice"], {"count": 1, "totals": {"ILS": 100.0}})
        self.assertEqual(summary["missingAmountCount"], 1)
        self.assertEqual([entry["month"] for entry in summary["byMonth"]], ["2026-08", "2026-07"])
        self.assertEqual(summary["byVendor"][0]["vendor"], "Bezeq")
        self.assertEqual((summary["unsureCount"], summary["rejectedCount"]), (1, 1))

    def test_a_receipt_typed_in_by_hand_is_the_owners_from_the_start(self) -> None:
        record = self.database.create_account_receipt(user_id=self.user_id, record={"vendor": "Corner cafe", "amount": "18", "currency": "ILS", "receiptDate": "2026-09-01", "kind": "receipt"})
        self.assertEqual((record["status"], record["manualAmount"], record["messageId"]), ("confirmed", True, ""))
        second = self.database.create_account_receipt(user_id=self.user_id, record={"vendor": "Corner cafe", "amount": "18", "currency": "ILS"})
        self.assertNotEqual(record["id"], second["id"])

    def test_receipts_go_with_the_account(self) -> None:
        rows, skipped = self._rows(message("m1", verdict={"isReceipt": True}))
        receipt_manager.store_collected_receipts(self.database, user_id=self.user_id, receipts=rows, skipped=skipped)
        self.database.delete_user("owner@example.com")
        self.assertEqual(self.database.list_account_receipts(user_id=self.user_id), [])


class ExportTests(unittest.TestCase):
    RECORDS = [
        {"id": 1, "status": "confirmed", "kind": "receipt", "vendor": "Render", "paidTo": "", "subject": "Your receipt", "mailbox": "owner@gmail.com", "amount": "25.00", "currency": "USD", "receiptDate": "2026-08-14", "attachments": [{"filename": "receipt.pdf", "url": "/x"}], "notes": ""},
        {"id": 2, "status": "confirmed", "kind": "invoice", "vendor": "Bezeq", "paidTo": "", "subject": "Invoice 12", "mailbox": "owner@gmail.com", "amount": "100", "currency": "ILS", "receiptDate": "2026-08-02", "attachments": [], "notes": "Office line"},
    ]

    def test_csv_lists_the_receipts_then_the_figures(self) -> None:
        text = receipt_manager.write_receipt_export_csv(self.RECORDS, range_label="2026-08-01 to 2026-08-31").decode("utf-8-sig")
        lines = text.splitlines()
        self.assertEqual(lines[0], "Date,Vendor,Paid to,Type,Amount,Currency,Subject,Mailbox,File,Notes")
        self.assertIn("2026-08-02,Bezeq,,Invoice,100,ILS,Invoice 12,owner@gmail.com,,Office line", lines)
        self.assertIn("Total ILS,100.00", lines)
        self.assertIn("Total USD,25.00", lines)
        self.assertIn("Invoices,1", lines)

    def test_xlsx_is_a_workbook_with_receipts_and_a_summary(self) -> None:
        data = receipt_manager.write_receipt_export_xlsx(self.RECORDS, range_label="all dates")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            summary = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
        self.assertIn("xl/workbook.xml", names)
        self.assertIn("Render", sheet)
        self.assertIn("Total USD", summary)

    def test_pdf_is_a_pdf(self) -> None:
        data = receipt_manager.write_receipt_export_pdf(self.RECORDS, range_label="all dates")
        self.assertTrue(data.startswith(b"%PDF"))
        plain = receipt_manager._write_plain_pdf(self.RECORDS, range_label="all dates")
        self.assertTrue(plain.startswith(b"%PDF"))
        self.assertIn(b"Total USD: 25.00", plain)

    def test_the_file_is_named_after_the_period(self) -> None:
        self.assertEqual(receipt_manager.export_filename("2026-08-01", "2026-08-31", "csv"), "receipts-2026-08-01-to-2026-08-31.csv")
        self.assertEqual(receipt_manager.export_filename("", "", "xlsx"), "receipts-all.xlsx")


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="receipts-test-secret-that-is-long-enough"),
        )
        self.server.database.register_user("owner@example.com")
        self.user_id = int((self.server.database.get_user("owner@example.com") or {}).get("id") or 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cookie = self._sign_in()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _sign_in(self, email: str = "owner@example.com") -> str:
        code, _ = self.server.store.issue_challenge(email)
        request = urllib_request.Request(
            f"{self.base_url}/api/auth/otp/verify",
            data=json.dumps({"email": email, "code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib_request.urlopen(request) as response:
            return response.headers.get("Set-Cookie", "").split(";", 1)[0]

    def _request(self, method: str, path: str, body: dict | None = None, *, cookie: str | None = "", raw: bool = False):
        headers = {"Content-Type": "application/json"}
        if cookie is not None:
            headers["Cookie"] = cookie or self.cookie
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers, method=method,
        )
        try:
            with urllib_request.urlopen(request) as response:
                data = response.read()
                return response.status, (data if raw else json.loads(data.decode("utf-8"))), dict(response.headers)
        except urllib_error.HTTPError as exc:
            data = exc.read()
            try:
                return exc.code, json.loads(data.decode("utf-8")), dict(exc.headers)
            except ValueError:
                return exc.code, data, dict(exc.headers)

    def _seed(self) -> list[dict]:
        answer = answer_receipt_question([
            message("m1", verdict={"isReceipt": True}),
            message("m2", sender="Bezeq <billing@bezeq.co.il>", subject="Invoice 12", body="Total ILS 100.00", date="Sun, 2 Aug 2026 09:00:00 +0000", verdict={"isReceipt": True}),
            message("m3", sender="Shop <deals@shop.com>", subject="Your order", body="Order total $40", verdict={"isReceipt": False, "confidence": "low", "reason": "possibly an order note"}),
        ])
        return receipt_manager.store_collected_receipts(
            self.server.database, user_id=self.user_id, receipts=answer["rows"], skipped=answer["skippedRows"],
        )["records"]

    def test_the_page_lives_at_receipts_and_needs_no_inline_script(self) -> None:
        self.assertEqual(resolve_static_page_alias("/receipts"), Path("portal/receipts.html"))
        for path in ("/receipts", "/receipts/"):
            with urllib_request.urlopen(f"{self.base_url}{path}") as response:
                markup = response.read().decode("utf-8")
            self.assertIn("Assistyca | Receipts", markup)
            self.assertNotIn("<script>", markup)

    def test_the_api_needs_a_session(self) -> None:
        status, _, _ = self._request("GET", "/api/receipts", cookie=None)
        self.assertEqual(status, 401)

    def test_the_list_carries_the_receipts_the_figures_and_the_questions(self) -> None:
        self._seed()
        status, payload, _ = self._request("GET", "/api/receipts?from=2026-08-01&to=2026-08-31")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["receipts"]), 3)
        self.assertEqual(payload["summary"]["totals"], {"ILS": 100.0, "USD": 25.0})
        self.assertEqual(payload["summary"]["unsureCount"], 1)
        self.assertEqual(payload["unsureTotal"], 1)
        self.assertEqual(payload["range"], {"from": "2026-08-01", "to": "2026-08-31"})
        self.assertNotIn("userId", payload["receipts"][0])

    def test_a_yes_keeps_the_receipt_with_the_kind_and_amount_the_owner_gave(self) -> None:
        unsure = next(record for record in self._seed() if record["status"] == "unsure")
        status, payload, _ = self._request("POST", f"/api/receipts/{unsure['id']}", {"status": "confirmed", "kind": "invoice", "amount": "40", "currency": "usd"})
        self.assertEqual(status, 200)
        receipt = payload["receipt"]
        self.assertEqual((receipt["status"], receipt["kind"], receipt["amount"], receipt["currency"], receipt["manualAmount"]), ("confirmed", "invoice", "40", "USD", True))
        status, listing, _ = self._request("GET", "/api/receipts")
        self.assertEqual(listing["summary"]["totals"], {"ILS": 100.0, "USD": 65.0})

    def test_a_no_leaves_it_out_of_the_totals(self) -> None:
        unsure = next(record for record in self._seed() if record["status"] == "unsure")
        status, payload, _ = self._request("POST", f"/api/receipts/{unsure['id']}", {"status": "rejected"})
        self.assertEqual(payload["receipt"]["status"], "rejected")
        status, listing, _ = self._request("GET", "/api/receipts")
        self.assertEqual(listing["summary"]["rejectedCount"], 1)
        self.assertEqual(listing["unsureTotal"], 0)

    def test_an_amount_that_is_not_a_number_is_refused(self) -> None:
        record = self._seed()[0]
        status, payload, _ = self._request("POST", f"/api/receipts/{record['id']}", {"amount": "twenty"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_receipt")

    def test_a_receipt_can_be_added_by_hand_and_deleted(self) -> None:
        status, payload, _ = self._request("POST", "/api/receipts", {"vendor": "Corner cafe", "amount": "18", "currency": "ILS", "receiptDate": "2026-09-01"})
        self.assertEqual(status, 200)
        receipt_id = payload["receipt"]["id"]
        status, gone, _ = self._request("DELETE", f"/api/receipts/{receipt_id}")
        self.assertTrue(gone["deleted"])
        status, _, _ = self._request("GET", f"/api/receipts/{receipt_id}")
        self.assertEqual(status, 404)

    def test_another_account_cannot_see_or_change_these_receipts(self) -> None:
        record = self._seed()[0]
        self.server.database.register_user("other@example.com")
        other = self._sign_in("other@example.com")
        status, _, _ = self._request("GET", f"/api/receipts/{record['id']}", cookie=other)
        self.assertEqual(status, 404)
        status, _, _ = self._request("POST", f"/api/receipts/{record['id']}", {"status": "rejected"}, cookie=other)
        self.assertEqual(status, 404)

    def test_the_export_carries_only_confirmed_receipts_in_the_period(self) -> None:
        self._seed()
        status, body, headers = self._request("GET", "/api/receipts/export?from=2026-08-01&to=2026-08-31&format=csv", raw=True)
        self.assertEqual(status, 200)
        self.assertIn('filename="receipts-2026-08-01-to-2026-08-31.csv"', headers.get("Content-Disposition", ""))
        text = body.decode("utf-8-sig")
        self.assertIn("Render", text)
        self.assertIn("Bezeq", text)
        self.assertNotIn("deals@shop.com", text)
        self.assertNotIn("Your order", text)
        status, body, headers = self._request("GET", "/api/receipts/export?format=xlsx", raw=True)
        self.assertEqual(headers.get("Content-Type"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(body.startswith(b"PK"))
        status, payload, _ = self._request("GET", "/api/receipts/export?format=docx")
        self.assertEqual(status, 400)


class LoopTests(unittest.TestCase):
    def test_the_lookup_tells_the_model_the_receipts_are_kept_and_where(self) -> None:
        response = {
            "ok": True,
            "answer": "You paid 25.00 USD.",
            "answerRecords": [],
            "receiptManager": {"stored": 3, "added": 3, "unsure": 1, "filesSaved": 2, "url": "https://assistyca.test/receipts"},
        }
        context = LoopContext(api=lambda method, path, payload: (response, 200), database=None, email="owner@example.com", user_id=1, channel="portal")
        result = _run_lookup(context, "custom", {"result": "receipts"})
        self.assertEqual(result["receiptsPage"], "https://assistyca.test/receipts")
        self.assertIn("3 receipt(s)", result["receiptsPageNote"])
        self.assertIn("1 of them are waiting", result["receiptsPageNote"])
        self.assertEqual(context.link_labels["https://assistyca.test/receipts"], "Open receipts")

        whatsapp = LoopContext(api=lambda method, path, payload: (response, 200), database=None, email="owner@example.com", user_id=1, channel="whatsapp")
        result = _run_lookup(whatsapp, "custom", {"result": "receipts"})
        self.assertNotIn("receiptsPage", result)
        self.assertEqual(whatsapp.links_offered, [])


if __name__ == "__main__":
    unittest.main()
