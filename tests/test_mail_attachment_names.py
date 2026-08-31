"""What a message was sent with, as the mailbox reads it out.

A judgement can only weigh the sender's own receipt file if the run that read
the mailbox wrote down that there was one. Reading the names is free where the
whole message is already in hand, and these are the cases that decide whether
the judgement is handed a fact, a wrong fact, or nothing at all.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.gmail_summary import list_attachment_filenames
from packages.infrastructure.receipt_judge import describe_attached_files


def part(filename: str = "", *, mime_type: str = "application/pdf", headers: list | None = None) -> dict:
    return {"filename": filename, "mimeType": mime_type, "headers": headers or []}


class GmailAttachmentNameTests(unittest.TestCase):
    def test_the_files_a_message_carries_are_named(self) -> None:
        message = {"payload": {"parts": [
            part(mime_type="text/html"),
            part("receipt-2026-06.pdf"),
        ]}}
        self.assertEqual(list_attachment_filenames(message), ["receipt-2026-06.pdf"])

    def test_a_message_carrying_nothing_names_nothing(self) -> None:
        message = {"payload": {"parts": [part(mime_type="text/plain"), part(mime_type="text/html")]}}
        self.assertEqual(list_attachment_filenames(message), [])

    def test_a_picture_drawn_into_the_mail_is_not_a_file_that_was_sent(self) -> None:
        # The shop's logo, its mascot and the thumbnail of the thing that was
        # bought all arrive as image parts with names. Counting them as
        # attachments would tell a judgement that an order confirmation came
        # with paperwork, which is exactly backwards.
        message = {"payload": {"parts": [
            part("logo.png", mime_type="image/png", headers=[{"name": "Content-ID", "value": "<logo@ali>"}]),
            part("product.jpg", mime_type="image/jpeg", headers=[
                {"name": "Content-Disposition", "value": "inline; filename=product.jpg"},
            ]),
        ]}}
        self.assertEqual(list_attachment_filenames(message), [])

    def test_a_photographed_receipt_is_still_a_file_that_was_sent(self) -> None:
        message = {"payload": {"parts": [part("IMG_4471.jpeg", mime_type="image/jpeg", headers=[
            {"name": "Content-Disposition", "value": "attachment; filename=IMG_4471.jpeg"},
        ])]}}
        self.assertEqual(list_attachment_filenames(message), ["IMG_4471.jpeg"])

    def test_the_names_are_found_however_deep_the_message_nests_them(self) -> None:
        message = {"payload": {"parts": [
            {"mimeType": "multipart/mixed", "parts": [part("invoice.pdf")]},
        ]}}
        self.assertEqual(list_attachment_filenames(message), ["invoice.pdf"])

    def test_a_message_that_was_never_opened_names_nothing_rather_than_guessing(self) -> None:
        self.assertEqual(list_attachment_filenames({}), [])


class TheNamesReachTheJudgementTests(unittest.TestCase):
    def test_what_the_mailbox_wrote_down_is_what_the_judgement_reads(self) -> None:
        message = {"payload": {"parts": [part("receipt.pdf")]}}
        item = {"subject": "Your receipt", "attachmentNames": list_attachment_filenames(message)}
        self.assertEqual(describe_attached_files(item), "receipt.pdf")

    def test_a_headers_only_read_leaves_the_files_unspoken_for(self) -> None:
        # Nothing was opened, so nothing is claimed. "none" here would be a
        # lie about every message in the run.
        self.assertEqual(describe_attached_files({"subject": "Your receipt"}), "")


if __name__ == "__main__":
    unittest.main()
