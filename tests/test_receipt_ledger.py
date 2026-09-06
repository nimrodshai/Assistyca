"""A receipt search remembers what it read, so asking again reads only what is new.

A search lists a month's mail, downloads each message and asks the model
which are receipts. Asked about the same month again, it used to do all of
that again. Now every message the judge ruled on is written down, and a
later search downloads and judges only the mail that arrived since - even
when the earlier search was for one vendor and the later one for the month.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from urllib import parse as urllib_parse
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import receipt_ledger
from packages.infrastructure.gmail_summary import GmailDigestRunner
from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase

SERVER_MODULE = "packages.infrastructure.portal_auth.server"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class FakeGmail:
    """A Gmail that answers the listing and the per-message downloads, and counts them."""

    def __init__(self, messages: dict[str, dict[str, str]]) -> None:
        self.messages = dict(messages)
        self.listings = 0
        self.downloads: list[str] = []

    def get_json(self, url: str, _token: str) -> dict[str, Any]:
        if "/messages/" in url:
            message_id = urllib_parse.unquote(url.split("/messages/")[1].split("?")[0])
            self.downloads.append(message_id)
            source = self.messages[message_id]
            return {
                "id": message_id,
                "threadId": f"thread-{message_id}",
                "snippet": source["body"][:60],
                "payload": {
                    "headers": [
                        {"name": "From", "value": source["from"]},
                        {"name": "Subject", "value": source["subject"]},
                        {"name": "Date", "value": source.get("date", "Tue, 1 Sep 2026 09:00:00 +0000")},
                    ],
                    "parts": [{"mimeType": "text/plain", "body": {"data": _b64(source["body"])}}],
                },
            }
        self.listings += 1
        return {"messages": [{"id": message_id} for message_id in self.messages]}


SEPTEMBER = {
    "render": {"from": "Render <billing@render.com>", "subject": "Your receipt from Render", "body": "Total charged $19.00", "date": "Tue, 1 Sep 2026 09:00:00 +0000"},
    "apple": {"from": "Apple <no_reply@apple.com>", "subject": "Your receipt from Apple", "body": "Total ILS 11.90", "date": "Sat, 5 Sep 2026 09:00:00 +0000"},
    "sale": {"from": "Render <deals@render.com>", "subject": "Big sale this week", "body": "Plans from $1.99", "date": "Thu, 3 Sep 2026 09:00:00 +0000"},
}


class FakeJudge:
    """The judging model: a receipt is any message whose subject says so."""

    def __init__(self, *, silent: bool = False) -> None:
        self.silent = silent
        self.judged: list[list[str]] = []
        self.other_tools: list[str] = []

    def __call__(self, **kwargs: Any) -> Any:
        if kwargs.get("tool_name") != "portal_receipt_judge":
            self.other_tools.append(str(kwargs.get("tool_name")))
            return mock.Mock(output_text="")
        prompt = str(kwargs.get("prompt") or "")
        context = json.loads(prompt.split("CONTEXT\n", 1)[1])
        candidates = context["messages"]
        self.judged.append([c["subject"] for c in candidates])
        if self.silent:
            return mock.Mock(output_text="")
        return mock.Mock(output_text=json.dumps({"verdicts": [
            {"ref": c["ref"], "isReceipt": "receipt" in c["subject"].lower(), "reason": "read"}
            for c in candidates
        ]}))


class _FakeTokenResponse:
    def __enter__(self) -> "_FakeTokenResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"access_token": "gmail-access-token", "expires_in": 3600}).encode("utf-8")


def _token_endpoint_patch():  # type: ignore[no-untyped-def]
    real_urlopen = urllib_request.urlopen

    def fake_urlopen(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        if "oauth2.googleapis.com" in url:
            return _FakeTokenResponse()
        return real_urlopen(request, timeout=timeout, **kwargs)

    return mock.patch(f"{SERVER_MODULE}.urllib_request.urlopen", side_effect=fake_urlopen)


class LedgerHelperTests(unittest.TestCase):
    def test_the_ceiling_counts_downloads_not_remembered_messages(self) -> None:
        items = [
            {"id": "n1"},
            {"id": "k1", "fromLedger": True},
            {"id": "n2"},
            {"id": "k2", "fromLedger": True},
            {"id": "n3"},
        ]
        kept, capped = receipt_ledger.cap_fresh_items(items, 2)
        self.assertTrue(capped)
        self.assertEqual([item["id"] for item in kept], ["n1", "k1", "n2", "k2"])
        kept, capped = receipt_ledger.cap_fresh_items(items, 3)
        self.assertFalse(capped)
        self.assertEqual(len(kept), 5)

    def test_only_messages_without_a_verdict_go_to_the_judge(self) -> None:
        items = [
            {"id": "a", "receiptVerdict": {"isReceipt": True}},
            {"id": "b"},
            {"id": "c", "receiptVerdict": {"isReceipt": False}},
            {"id": "d"},
        ]
        seen: list[list[str]] = []

        def judge(pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen.append([item["id"] for item in pending])
            return [{**item, "receiptVerdict": {"isReceipt": True}} for item in pending]

        judged = receipt_ledger.judge_only_new(items, judge=judge)
        self.assertEqual(seen, [["b", "d"]])
        self.assertEqual([item["id"] for item in judged], ["a", "b", "c", "d"])
        self.assertTrue(all(receipt_ledger.has_verdict(item) for item in judged))

    def test_the_version_follows_the_wording_of_the_judgement(self) -> None:
        before = receipt_ledger.judge_version()
        with mock.patch("packages.infrastructure.receipt_ledger.RECEIPT_JUDGE_INSTRUCTIONS", "other words"):
            after = receipt_ledger.judge_version()
        self.assertNotEqual(before, after)
        self.assertEqual(before, receipt_ledger.judge_version())


class LedgerStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)
        self.ledger = receipt_ledger.MailReadLedger(self.database, user_id=self.user_id, version="v1")

    def _item(self, message_id: str, *, verdict: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
        item = {
            "id": message_id,
            "mailbox": "owner@gmail.com",
            "from": "Render <billing@render.com>",
            "subject": "Your receipt from Render",
            "date": "Tue, 1 Sep 2026 09:00:00 +0000",
            "bodyText": "Total charged $19.00",
            "attachmentNames": ["receipt.pdf"],
            **extra,
        }
        if verdict is not None:
            item["receiptVerdict"] = verdict
        return item

    def test_a_judged_message_comes_back_whole_and_an_unjudged_one_is_not_kept(self) -> None:
        written = self.ledger.remember([
            self._item("m1", verdict={"isReceipt": True, "paidTo": "Render"}),
            self._item("m2", verdict=None),
        ])
        self.assertEqual(written, 1)
        found = self.ledger.lookup("owner@gmail.com", ["m1", "m2", "m3"])
        self.assertEqual(set(found), {"m1"})
        self.assertEqual(found["m1"]["bodyText"], "Total charged $19.00")
        self.assertEqual(found["m1"]["attachmentNames"], ["receipt.pdf"])
        self.assertEqual(found["m1"]["receiptVerdict"]["paidTo"], "Render")
        self.assertTrue(found["m1"]["fromLedger"])

    def test_a_row_judged_under_other_wording_reads_as_unknown(self) -> None:
        self.ledger.remember([self._item("m1", verdict={"isReceipt": True})])
        newer = receipt_ledger.MailReadLedger(self.database, user_id=self.user_id, version="v2")
        self.assertEqual(newer.lookup("owner@gmail.com", ["m1"]), {})
        self.assertEqual(set(self.ledger.lookup("owner@gmail.com", ["m1"])), {"m1"})

    def test_what_the_ledger_supplied_is_not_written_again(self) -> None:
        self.ledger.remember([self._item("m1", verdict={"isReceipt": True})])
        found = self.ledger.lookup("owner@gmail.com", ["m1"])
        self.assertEqual(self.ledger.remember(list(found.values())), 0)

    def test_a_dismissal_survives_a_later_read(self) -> None:
        self.database.dismiss_receipt_mail_read(user_id=self.user_id, mailbox="owner@gmail.com", message_id="m1")
        self.ledger.remember([self._item("m1", verdict={"isReceipt": True})])
        self.assertEqual(self.ledger.dismissed(), {"m1"})
        self.assertEqual(set(self.ledger.lookup("owner@gmail.com", ["m1"])), {"m1"})

    def test_the_oldest_reads_go_when_the_ledger_is_full(self) -> None:
        with mock.patch("packages.infrastructure.portal_db.RECEIPT_MAIL_READS_MAX_ROWS", 3):
            for index in range(5):
                self.ledger.remember([self._item(f"m{index}", verdict={"isReceipt": False})])
        self.assertEqual(self.database.count_receipt_mail_reads(user_id=self.user_id), 3)
        self.assertEqual(set(self.ledger.lookup("owner@gmail.com", [f"m{i}" for i in range(5)])), {"m2", "m3", "m4"})


class GmailReaderLedgerTests(unittest.TestCase):
    def test_remembered_messages_are_not_downloaded_and_do_not_count(self) -> None:
        mailbox = FakeGmail({f"m{i}": {"from": "A <a@a.com>", "subject": f"Receipt {i}", "body": "$1.00"} for i in range(5)})
        remembered = {
            "m1": {"id": "m1", "subject": "Receipt 1", "bodyText": "$1.00", "receiptVerdict": {"isReceipt": True}, "fromLedger": True},
            "m3": {"id": "m3", "subject": "Receipt 3", "bodyText": "$1.00", "receiptVerdict": {"isReceipt": True}, "fromLedger": True},
        }
        asked: list[list[str]] = []

        def known(ids: list[str]) -> dict[str, dict[str, Any]]:
            asked.append(list(ids))
            return {key: value for key, value in remembered.items() if key in ids}

        with mock.patch.object(GmailDigestRunner, "_get_json", side_effect=mailbox.get_json):
            items = GmailDigestRunner().fetch_message_summaries(
                "token", query=MailQuery(), max_results=2, include_body=True, known=known,
            )

        self.assertEqual(asked, [["m0", "m1", "m2", "m3", "m4"]])
        # Two downloads, the newest first; the remembered ones ride along.
        self.assertEqual(mailbox.downloads, ["m0", "m2"])
        self.assertEqual([item["id"] for item in items], ["m0", "m1", "m2", "m3"])
        self.assertTrue(items[1]["fromLedger"])
        self.assertNotIn("fromLedger", items[0])

    def test_without_a_ledger_the_reader_is_as_it_was(self) -> None:
        mailbox = FakeGmail({f"m{i}": {"from": "A <a@a.com>", "subject": f"Receipt {i}", "body": "$1.00"} for i in range(3)})
        with mock.patch.object(GmailDigestRunner, "_get_json", side_effect=mailbox.get_json):
            items = GmailDigestRunner().fetch_message_summaries("token", query=MailQuery(), max_results=2, include_body=True)
        self.assertEqual(mailbox.downloads, ["m0", "m1"])
        self.assertEqual(len(items), 2)


class ReceiptSearchLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.server = create_server(
            "127.0.0.1",
            0,
            root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
                agent_output_dir=Path(self.temp_dir.name) / "agent_outputs",
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
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
        self.user_id = int((self.server.database.get_user("owner@example.com") or {}).get("id") or 0)
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({
                "type": GOOGLE_OAUTH_SECRET_TYPE,
                "provider": "google",
                "refreshToken": "refresh-token",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,
            connection_status="connected",
            account_address="owner@gmail.com",
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _search(self, mailbox: FakeGmail, judge: FakeJudge, *, vendor: str = "", what: str = "Find my receipts for September 2026") -> dict[str, Any]:
        fields: dict[str, Any] = {"result": what, "manualRunMonth": "2026-09"}
        if vendor:
            fields["vendor"] = vendor
        with _token_endpoint_patch():
            with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner._get_json", side_effect=mailbox.get_json):
                with mock.patch(f"{SERVER_MODULE}.call_openai_response", side_effect=judge):
                    return self._request("POST", "/api/agent/proposals/run", {
                        "proposalType": "custom",
                        "mode": "answer",
                        "fields": fields,
                        "deliveryChannel": "portal",
                        "timezone": "Asia/Jerusalem",
                    })

    def _page_vendors(self) -> list[str]:
        payload = self._request("GET", "/api/receipts?from=2026-09-01&to=2026-09-30")
        return sorted(str(record.get("vendor")) for record in payload["receipts"])

    def test_a_month_asked_twice_is_downloaded_and_judged_once(self) -> None:
        mailbox = FakeGmail(SEPTEMBER)
        judge = FakeJudge()

        first = self._search(mailbox, judge)
        self.assertTrue(first["ok"])
        self.assertEqual(sorted(mailbox.downloads), ["apple", "render", "sale"])
        self.assertEqual(len(judge.judged), 1)
        self.assertEqual(first["mailReads"], {"fromLedger": 0, "fetched": 3, "judged": 3})

        mailbox.downloads.clear()
        judge.judged.clear()
        second = self._search(mailbox, judge)

        self.assertEqual(mailbox.downloads, [])
        self.assertEqual(judge.judged, [])
        self.assertEqual(second["mailReads"], {"fromLedger": 3, "fetched": 0, "judged": 0})
        self.assertEqual(second["answer"], first["answer"])
        self.assertEqual(self._page_vendors(), ["Apple", "Render"])

    def test_a_vendor_search_leaves_the_whole_month_read(self) -> None:
        # September 20: "pull my Render receipt". October 1: "pull September".
        # The second run only reads what arrived in between.
        mailbox = FakeGmail(SEPTEMBER)
        judge = FakeJudge()

        first = self._search(mailbox, judge, vendor="Render", what="Pull my receipt from Render for September 2026")
        self.assertEqual(sorted(mailbox.downloads), ["apple", "render", "sale"])
        self.assertIn("19.00 USD", first["answer"])
        self.assertEqual(self._page_vendors(), ["Render"])

        mailbox.messages["wolt"] = {"from": "Wolt <no-reply@wolt.com>", "subject": "Your Wolt receipt", "body": "Total ILS 41.61", "date": "Mon, 28 Sep 2026 09:00:00 +0000"}
        mailbox.downloads.clear()
        judge.judged.clear()
        second = self._search(mailbox, judge)

        self.assertEqual(mailbox.downloads, ["wolt"])
        self.assertEqual(judge.judged, [["Your Wolt receipt"]])
        self.assertEqual(second["mailReads"], {"fromLedger": 3, "fetched": 1, "judged": 1})
        self.assertIn("3 receipts", second["answer"])
        self.assertEqual(self._page_vendors(), ["Apple", "Render", "Wolt"])

    def test_a_message_the_judge_could_not_rule_on_is_read_again(self) -> None:
        mailbox = FakeGmail(SEPTEMBER)
        silent = FakeJudge(silent=True)
        self._search(mailbox, silent)
        self.assertEqual(self.server.database.count_receipt_mail_reads(user_id=self.user_id), 0)

        mailbox.downloads.clear()
        judge = FakeJudge()
        payload = self._search(mailbox, judge)
        self.assertEqual(sorted(mailbox.downloads), ["apple", "render", "sale"])
        self.assertEqual(len(judge.judged), 1)
        self.assertEqual(payload["mailReads"]["fromLedger"], 0)
        self.assertEqual(self.server.database.count_receipt_mail_reads(user_id=self.user_id), 3)

    def test_a_changed_judgement_reads_the_month_afresh(self) -> None:
        mailbox = FakeGmail(SEPTEMBER)
        judge = FakeJudge()
        self._search(mailbox, judge)
        mailbox.downloads.clear()
        judge.judged.clear()

        with mock.patch("packages.infrastructure.receipt_ledger.judge_version", return_value="reworded"):
            payload = self._search(mailbox, judge)

        self.assertEqual(sorted(mailbox.downloads), ["apple", "render", "sale"])
        self.assertEqual(len(judge.judged), 1)
        self.assertEqual(payload["mailReads"]["fromLedger"], 0)

    def test_a_receipt_deleted_from_the_page_does_not_come_back(self) -> None:
        mailbox = FakeGmail(SEPTEMBER)
        judge = FakeJudge()
        self._search(mailbox, judge)
        listed = self._request("GET", "/api/receipts?from=2026-09-01&to=2026-09-30")["receipts"]
        render = next(record for record in listed if record["vendor"] == "Render")
        self.assertTrue(self._request("DELETE", f"/api/receipts/{render['id']}")["deleted"])
        self.assertEqual(self._page_vendors(), ["Apple"])

        mailbox.downloads.clear()
        payload = self._search(mailbox, judge)

        self.assertEqual(mailbox.downloads, [])
        self.assertIn("19.00 USD", payload["answer"])
        self.assertEqual(self._page_vendors(), ["Apple"])


if __name__ == "__main__":
    unittest.main()
