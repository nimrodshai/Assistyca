from __future__ import annotations

import unittest

from packages.infrastructure import mail_attachments

PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 32
HTML = b"<!doctype html><html><body>Not a receipt</body></html>"


class AttachmentContentTests(unittest.TestCase):
    """A mailbox reports a type and a name; the bytes decide what gets saved."""

    def test_a_pdf_that_says_it_is_a_pdf_is_saved(self) -> None:
        self.assertTrue(mail_attachments.content_is_receipt_attachment(PDF, mime_type="application/pdf", filename="receipt.pdf"))

    def test_a_pdf_named_as_one_is_saved_whatever_type_the_mailbox_guessed(self) -> None:
        self.assertTrue(mail_attachments.content_is_receipt_attachment(PDF, mime_type="application/octet-stream", filename="receipt.pdf"))

    def test_a_pdf_may_open_with_a_little_junk_before_its_header(self) -> None:
        self.assertTrue(mail_attachments.content_is_receipt_attachment(b"\r\n" * 20 + PDF, mime_type="application/pdf", filename="receipt.pdf"))

    def test_every_kind_of_picture_is_saved_under_its_own_name(self) -> None:
        for content, filename in ((PNG, "receipt.png"), (JPEG, "receipt.jpg"), (WEBP, "receipt.webp")):
            with self.subTest(filename=filename):
                self.assertTrue(mail_attachments.content_is_receipt_attachment(content, mime_type="", filename=filename))

    def test_a_web_page_wearing_a_pdf_name_is_refused(self) -> None:
        self.assertFalse(mail_attachments.content_is_receipt_attachment(HTML, mime_type="application/pdf", filename="receipt.pdf"))

    def test_a_picture_wearing_a_pdf_name_is_refused(self) -> None:
        self.assertFalse(mail_attachments.content_is_receipt_attachment(PNG, mime_type="application/pdf", filename="receipt.pdf"))

    def test_a_pdf_wearing_a_picture_name_is_refused(self) -> None:
        self.assertFalse(mail_attachments.content_is_receipt_attachment(PDF, mime_type="image/png", filename="receipt.png"))

    def test_an_empty_file_is_nothing(self) -> None:
        self.assertEqual(mail_attachments.sniff_attachment_kind(b""), "")
        self.assertFalse(mail_attachments.content_is_receipt_attachment(b"", mime_type="application/pdf", filename="receipt.pdf"))

    def test_a_refused_file_is_reported_with_the_reason(self) -> None:
        skipped = mail_attachments.skipped_attachment(
            "receipt.pdf",
            mime_type="application/pdf",
            size=len(HTML),
            reason=mail_attachments.ATTACHMENT_NOT_A_RECEIPT_FILE_REASON,
        )

        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], mail_attachments.ATTACHMENT_NOT_A_RECEIPT_FILE_REASON)


if __name__ == "__main__":
    unittest.main()
