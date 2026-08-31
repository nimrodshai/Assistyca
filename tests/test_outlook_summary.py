"""The Outlook reader, against a stubbed Microsoft Graph.

These tests pin the shape of what the reader returns, because the receipt
bundle and the digest formatter cannot tell a Gmail run from an Outlook one and
must not have to.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import contextlib
import io
import unittest
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.mail_search import month_window
from packages.infrastructure.outlook_summary import GRAPH_ME_API_URL
from packages.infrastructure.outlook_summary import OutlookAccessValidator
from packages.infrastructure.outlook_summary import OutlookAuthorizationError
from packages.infrastructure.outlook_summary import OutlookDigestRunner
from packages.infrastructure.outlook_summary import OutlookSummaryError

INBOX_QUERY = MailQuery(in_inbox=True)
DEFAULT_DIGEST = MailQuery(in_inbox=True, newer_than_days=1)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _message(
    message_id: str = "msg-1",
    *,
    subject: str = "Proposal review",
    received: str = "2026-07-14T08:15:00Z",
    preview: str = "Please review the proposal by Friday.",
    name: str = "Maya",
    address: str = "maya@example.com",
    has_attachments: bool = False,
) -> dict[str, object]:
    return {
        "id": message_id,
        "conversationId": f"thread-{message_id}",
        "subject": subject,
        "receivedDateTime": received,
        "bodyPreview": preview,
        "hasAttachments": has_attachments,
        "from": {"emailAddress": {"name": name, "address": address}},
    }


class OutlookDigestTests(unittest.TestCase):
    def test_runner_lists_messages_and_builds_a_digest(self) -> None:
        requests: list[object] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            requests.append(request)
            self.assertEqual(timeout, 20)
            return _FakeResponse({"value": [_message()]})

        result = OutlookDigestRunner(opener=opener).run("outlook-token", query=INBOX_QUERY)

        self.assertEqual(result["messageCount"], 1)
        self.assertIn("Proposal review", result["message"])
        self.assertIn("Maya", result["message"])
        self.assertIn("Please review", result["message"])
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer outlook-token")  # type: ignore[attr-defined]
        self.assertNotIn("outlook-token", result["message"])

    def test_an_item_carries_the_same_keys_a_gmail_item_does(self) -> None:
        # The receipt bundle reads these keys and never learns which mailbox
        # produced them.
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse({"value": [_message()]})

        item = OutlookDigestRunner(opener=opener).run("token", query=INBOX_QUERY)["items"][0]

        self.assertEqual(
            sorted(item.keys()),
            ["date", "from", "id", "snippet", "subject", "threadId"],
        )
        self.assertEqual(item["from"], "Maya <maya@example.com>")
        self.assertEqual(item["threadId"], "thread-msg-1")

    def test_the_date_reads_like_a_mail_header_not_an_iso_timestamp(self) -> None:
        # It is printed straight into the receipts Excel and PDF next to Gmail
        # rows, so it has to look the same as one.
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse({"value": [_message(received="2026-07-14T08:15:00Z")]})

        item = OutlookDigestRunner(opener=opener).run("token", query=INBOX_QUERY)["items"][0]

        self.assertEqual(item["date"], "Tue, 14 Jul 2026 08:15:00 +0000")

    def test_the_search_string_carries_the_query(self) -> None:
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": []})

        window = month_window(2026, 7)
        query = MailQuery(terms=("receipt", "invoice"), after=window.after, before=window.before)
        OutlookDigestRunner(opener=opener).run("token", query=query)

        self.assertIn("%24search=", urls[0])
        self.assertIn("receipt", urls[0])
        # Graph rejects $orderby alongside $search.
        self.assertNotIn("%24orderby", urls[0])

    def test_the_search_terms_own_quotes_do_not_close_the_search_literal(self) -> None:
        # $search takes a quoted string, and the KQL inside quotes every word
        # it looks for. Unescaped, the first of those closes the literal early
        # and Graph refuses the request - which is not an authorization error,
        # so the mailbox goes on reading as connected while nothing can be
        # read from it.
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": []})

        query = MailQuery(terms=("receipt", "invoice"), required_terms=("Render",))
        OutlookDigestRunner(opener=opener).run("token", query=query)

        search = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)["$search"][0]
        self.assertTrue(search.startswith('"') and search.endswith('"'))
        self.assertNotIn('"', search[1:-1].replace('\\"', ""))
        self.assertIn('\\"receipt\\"', search)
        self.assertIn('\\"Render\\"', search)

    def test_a_search_with_no_terms_needs_no_escaping(self) -> None:
        # A digest searches on the date alone, which carries no quotes of its
        # own, so nothing here should start escaping a string that is fine.
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": []})

        OutlookDigestRunner(opener=opener).run("token", query=DEFAULT_DIGEST)

        search = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)["$search"][0]
        self.assertNotIn("\\", search)

    def test_an_inbox_digest_reads_the_inbox_folder_not_the_whole_mailbox(self) -> None:
        # Gmail's in:inbox has no KQL equivalent, so without the folder
        # endpoint a digest would summarise Sent mail too.
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": []})

        OutlookDigestRunner(opener=opener).run("token", query=DEFAULT_DIGEST)

        self.assertTrue(urls[0].startswith("https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?"))

    def test_a_search_that_is_not_inbox_only_reads_the_whole_mailbox(self) -> None:
        # A receipts run must find filed and archived receipts, not just what
        # is still sitting in the inbox.
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": []})

        OutlookDigestRunner(opener=opener).run("token", query=MailQuery(terms=("receipt",)))

        self.assertTrue(urls[0].startswith("https://graph.microsoft.com/v1.0/me/messages?"))

    def test_a_query_with_no_search_terms_is_ordered_newest_first(self) -> None:
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": []})

        OutlookDigestRunner(opener=opener).run("token", query=MailQuery())

        self.assertIn("%24orderby=receivedDateTime+desc", urls[0])
        self.assertNotIn("%24search", urls[0])

    def test_a_message_outside_the_asked_for_month_is_dropped(self) -> None:
        # Graph's KQL date handling is looser than Gmail's operators. A receipts
        # run for July must not put a June receipt in the bundle.
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse({"value": [
                _message("in-window", received="2026-07-14T08:15:00Z", subject="July receipt"),
                _message("too-early", received="2026-06-30T23:59:00Z", subject="June receipt"),
                _message("too-late", received="2026-08-01T00:01:00Z", subject="August receipt"),
            ]})

        window = month_window(2026, 7)
        query = MailQuery(terms=("receipt",), after=window.after, before=window.before)
        result = OutlookDigestRunner(opener=opener).run("token", query=query)

        self.assertEqual([item["id"] for item in result["items"]], ["in-window"])

    def test_it_follows_paging_until_it_has_enough_matches(self) -> None:
        pages = [
            {
                "value": [_message("old", received="2026-06-02T09:00:00Z", subject="receipt")],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?page=2",
            },
            {"value": [_message("wanted", received="2026-07-02T09:00:00Z", subject="receipt")]},
        ]

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse(pages.pop(0))

        window = month_window(2026, 7)
        query = MailQuery(terms=("receipt",), after=window.after, before=window.before)
        result = OutlookDigestRunner(opener=opener).run("token", query=query)

        self.assertEqual([item["id"] for item in result["items"]], ["wanted"])

    def test_an_empty_mailbox_says_so_without_leaking_the_token(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse({"value": []})

        result = OutlookDigestRunner(opener=opener).run("secret-token", query=INBOX_QUERY)

        self.assertEqual(result["messageCount"], 0)
        self.assertIn("No Outlook messages found", result["message"])
        self.assertNotIn("secret-token", json.dumps(result))


def _selected_fields(url: str) -> list[str]:
    """The message fields one request asked Graph for."""

    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return query["$select"][0].split(",")


class OutlookDraftTests(unittest.TestCase):
    """A reply someone started writing is not a second receipt."""

    def _payload(self, *, is_draft: bool) -> dict[str, object]:
        receipt = _message(
            "receipt-1",
            subject="Your payment to Netflix.com",
            received="2026-08-20T06:00:00Z",
            preview="You sent a payment of 71.80 ILS to Netflix.com",
            name="PayPal",
            address="service@paypal.com",
        )
        # A reply quotes what it answers, so the draft carries the receipt's
        # own words and its amount.
        draft = _message(
            "draft-1",
            subject="Re: Your payment to Netflix.com",
            received="2026-08-28T06:00:00Z",
            preview="You sent a payment of 71.80 ILS to Netflix.com",
            name="Owner",
            address="owner@example.com",
        )
        draft["isDraft"] = is_draft
        return {"value": [receipt, draft]}

    def _items(self, *, is_draft: bool) -> list[dict[str, object]]:
        payload = self._payload(is_draft=is_draft)

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse(payload)

        return OutlookDigestRunner(opener=opener).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("payment",), required_terms=("Netflix",)),
        )

    def test_a_draft_reply_to_a_receipt_is_not_read_as_mail(self) -> None:
        self.assertEqual([item["id"] for item in self._items(is_draft=True)], ["receipt-1"])

    def test_a_sent_message_is_left_alone(self) -> None:
        self.assertEqual(
            [item["id"] for item in self._items(is_draft=False)],
            ["receipt-1", "draft-1"],
        )

    def test_the_read_asks_graph_whether_a_message_is_a_draft(self) -> None:
        # Graph only returns the fields the select names, so an unasked-for
        # isDraft comes back missing and every draft reads as real mail.
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(getattr(request, "full_url", str(request)))
            return _FakeResponse({"value": []})

        OutlookDigestRunner(opener=opener).fetch_message_summaries("token", query=INBOX_QUERY)

        self.assertIn("isDraft", urllib.parse.unquote(urls[0]))


class OutlookBodyTests(unittest.TestCase):
    """Reading the total means reading the body, with or without a bundle."""

    def _opener(self, urls: list[str]):  # type: ignore[no-untyped-def]
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            message = _message(subject="Your receipt from Render")
            message["body"] = {
                "contentType": "html",
                "content": "<p>Amount paid</p><p>$13.35</p>",
            }
            return _FakeResponse({"value": [message]})

        return opener

    def test_a_chat_answer_asks_graph_for_the_body(self) -> None:
        urls: list[str] = []
        items = OutlookDigestRunner(opener=self._opener(urls)).fetch_message_summaries(
            "token",
            query=MailQuery(terms=("receipt",)),
            include_body=True,
        )

        self.assertIn("body", _selected_fields(urls[0]))
        self.assertIn("$13.35", items[0]["bodyText"])
        # No bundle is being written, so nothing should be downloaded for one.
        self.assertNotIn("attachments", items[0])

    def test_a_digest_leaves_the_body_behind(self) -> None:
        urls: list[str] = []
        items = OutlookDigestRunner(opener=self._opener(urls)).fetch_message_summaries(
            "token",
            query=INBOX_QUERY,
        )

        self.assertNotIn("body", _selected_fields(urls[0]))
        self.assertNotIn("bodyText", items[0])


class OutlookAttachmentTests(unittest.TestCase):
    def test_runner_saves_a_receipt_attachment(self) -> None:
        pdf_bytes = b"%PDF-1.4 small receipt"

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = request.full_url  # type: ignore[attr-defined]
            if "/attachments" in url:
                return _FakeResponse({"value": [{
                    "id": "att-1",
                    "name": "receipt july.pdf",
                    "contentType": "application/pdf",
                    "size": len(pdf_bytes),
                    "contentBytes": base64.b64encode(pdf_bytes).decode("ascii"),
                }]})
            return _FakeResponse({"value": [_message("msg-1", subject="receipt", has_attachments=True)]})

        with tempfile.TemporaryDirectory() as temp_dir:
            result = OutlookDigestRunner(opener=opener).run(
                "token",
                query=MailQuery(terms=("receipt",)),
                include_attachments=True,
                attachment_output_dir=Path(temp_dir),
                attachment_url_prefix="/output/agent_receipts/owner/Receipts/Jul2026/attachments",
            )

            attachment = result["items"][0]["attachments"][0]
            saved = Path(attachment["path"])
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), pdf_bytes)
            self.assertEqual(attachment["status"], "saved")
            self.assertEqual(attachment["mimeType"], "application/pdf")
            self.assertEqual(
                attachment["url"],
                "/output/agent_receipts/owner/Receipts/Jul2026/attachments/"
                + urllib.parse.quote(saved.name),
            )

    def test_a_message_with_no_attachment_flag_is_never_asked_about_one(self) -> None:
        urls: list[str] = []

        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": [_message("msg-1", has_attachments=False)]})

        with tempfile.TemporaryDirectory() as temp_dir:
            result = OutlookDigestRunner(opener=opener).run(
                "token",
                query=INBOX_QUERY,
                include_attachments=True,
                attachment_output_dir=Path(temp_dir),
            )

        self.assertEqual(result["items"][0]["attachments"], [])
        self.assertFalse([url for url in urls if "/attachments" in url])

    def test_an_oversized_attachment_is_recorded_as_skipped_not_downloaded(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = request.full_url  # type: ignore[attr-defined]
            if "/attachments" in url:
                return _FakeResponse({"value": [{
                    "id": "att-1",
                    "name": "huge.pdf",
                    "contentType": "application/pdf",
                    "size": 64 * 1024 * 1024,
                }]})
            return _FakeResponse({"value": [_message("msg-1", subject="receipt", has_attachments=True)]})

        with tempfile.TemporaryDirectory() as temp_dir:
            result = OutlookDigestRunner(opener=opener).run(
                "token",
                query=MailQuery(terms=("receipt",)),
                include_attachments=True,
                attachment_output_dir=Path(temp_dir),
            )

            attachment = result["items"][0]["attachments"][0]
            self.assertEqual(attachment["status"], "skipped")
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_a_calendar_invite_is_not_treated_as_a_receipt(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            url = request.full_url  # type: ignore[attr-defined]
            if "/attachments" in url:
                return _FakeResponse({"value": [{
                    "id": "att-1",
                    "name": "meeting.ics",
                    "contentType": "text/calendar",
                    "size": 40,
                    "contentBytes": base64.b64encode(b"BEGIN:VCALENDAR").decode("ascii"),
                }]})
            return _FakeResponse({"value": [_message("msg-1", subject="receipt", has_attachments=True)]})

        with tempfile.TemporaryDirectory() as temp_dir:
            result = OutlookDigestRunner(opener=opener).run(
                "token",
                query=MailQuery(terms=("receipt",)),
                include_attachments=True,
                attachment_output_dir=Path(temp_dir),
            )

            self.assertEqual(result["items"][0]["attachments"], [])


class OutlookFailureTests(unittest.TestCase):
    def _failing_opener(self, code: int):  # type: ignore[no-untyped-def]
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib.error.HTTPError(request.full_url, code, "nope", {}, None)  # type: ignore[attr-defined]

        return opener

    def test_a_rejected_credential_asks_for_a_reconnect(self) -> None:
        for code in (401, 403):
            with self.subTest(code=code):
                with self.assertRaises(OutlookAuthorizationError) as caught:
                    OutlookDigestRunner(opener=self._failing_opener(code)).run("token", query=INBOX_QUERY)

                self.assertEqual(caught.exception.code, "outlook_authorization_failed")
                self.assertIn("Reconnect Outlook", str(caught.exception))

    def test_a_provider_error_is_not_reported_as_an_authorization_problem(self) -> None:
        with self.assertRaises(OutlookSummaryError) as caught:
            OutlookDigestRunner(opener=self._failing_opener(500)).run("token", query=INBOX_QUERY)

        self.assertEqual(caught.exception.code, "outlook_provider_error")

    def test_a_provider_error_reads_as_english_rather_than_an_http_code(self) -> None:
        # This sentence is shown to a client in chat. The status code belongs
        # in ``code`` and the logs, not in what they read.
        with self.assertRaises(OutlookSummaryError) as caught:
            OutlookDigestRunner(opener=self._failing_opener(400)).run("token", query=INBOX_QUERY)

        message = str(caught.exception)
        self.assertNotIn("400", message)
        self.assertIn("Outlook", message)

    def test_an_unreachable_provider_says_so(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib.error.URLError("no route")

        with self.assertRaises(OutlookSummaryError) as caught:
            OutlookDigestRunner(opener=opener).run("token", query=INBOX_QUERY)

        self.assertEqual(caught.exception.code, "outlook_network_error")

    def test_a_refused_read_is_written_down_with_what_graph_said(self) -> None:
        # The client only ever sees "try it again later", so without this the
        # cause leaves no trace anywhere and cannot be chased down.
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"error":{"code":"BadRequest","message":"Invalid $search"}}'),
            )

        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            with self.assertRaises(OutlookSummaryError):
                OutlookDigestRunner(opener=opener).run("token", query=MailQuery(terms=("receipt",)))

        written = log.getvalue()
        self.assertIn("status=400", written)
        self.assertIn("Invalid $search", written)
        # The URL says which query failed; the credential is a header and must
        # never end up in a log line.
        self.assertIn("graph.microsoft.com", written)
        self.assertNotIn("token", written.replace("%24search", ""))

    def test_an_error_carrying_no_body_still_reports_the_status(self) -> None:
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            with self.assertRaises(OutlookSummaryError):
                OutlookDigestRunner(opener=self._failing_opener(500)).run("token", query=INBOX_QUERY)

        self.assertIn("status=500", log.getvalue())

    def test_an_unreachable_provider_is_written_down_too(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib.error.URLError("no route")

        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            with self.assertRaises(OutlookSummaryError):
                OutlookDigestRunner(opener=opener).run("token", query=INBOX_QUERY)

        self.assertIn("no route", log.getvalue())

    def test_a_missing_token_never_reaches_the_network(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            raise AssertionError("should not have been called")

        with self.assertRaises(OutlookAuthorizationError):
            OutlookDigestRunner(opener=opener).run("", query=INBOX_QUERY)


class OutlookValidatorTests(unittest.TestCase):
    def test_a_working_grant_validates(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            # Validating also reads the mailbox address, so a user can tell
            # two connected Outlook accounts apart.
            if request.full_url.startswith(f"{GRAPH_ME_API_URL}?"):  # type: ignore[attr-defined]
                return _FakeResponse({"mail": "Owner@Contoso.com"})
            self.assertIn("%24top=1", request.full_url)  # type: ignore[attr-defined]
            return _FakeResponse({"value": [{"id": "msg-1"}]})

        self.assertEqual(
            OutlookAccessValidator(opener=opener).validate("token"),
            {
                "outlookValidation": "ok",
                "messageCount": 1,
                "emailAddress": "owner@contoso.com",
            },
        )

    def test_a_mailbox_without_a_mail_attribute_falls_back_to_the_principal_name(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            if request.full_url.startswith(f"{GRAPH_ME_API_URL}?"):  # type: ignore[attr-defined]
                return _FakeResponse({"mail": "", "userPrincipalName": "owner@contoso.onmicrosoft.com"})
            return _FakeResponse({"value": []})

        self.assertEqual(
            OutlookAccessValidator(opener=opener).validate("token")["emailAddress"],
            "owner@contoso.onmicrosoft.com",
        )

    def test_a_refused_profile_read_still_leaves_the_grant_usable(self) -> None:
        # An Outlook connection made before User.Read was requested can still
        # read mail. It just has no address until it is reconnected.
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            if request.full_url.startswith(f"{GRAPH_ME_API_URL}?"):  # type: ignore[attr-defined]
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)  # type: ignore[arg-type]
            return _FakeResponse({"value": [{"id": "msg-1"}]})

        result = OutlookAccessValidator(opener=opener).validate("token")
        self.assertEqual(result["outlookValidation"], "ok")
        self.assertEqual(result["emailAddress"], "")

    def test_an_empty_mailbox_still_validates(self) -> None:
        def opener(request, *, timeout):  # type: ignore[no-untyped-def]
            return _FakeResponse({"value": []})

        self.assertEqual(
            OutlookAccessValidator(opener=opener).validate("token")["outlookValidation"],
            "ok",
        )

    def test_a_blank_token_is_refused_before_the_call(self) -> None:
        with self.assertRaises(OutlookAuthorizationError):
            OutlookAccessValidator().validate("")


if __name__ == "__main__":
    unittest.main()
