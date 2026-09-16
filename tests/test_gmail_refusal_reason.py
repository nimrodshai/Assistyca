"""A Gmail refusal keeps Google's own reason, so the log can tell them apart."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from urllib import error as urllib_error

from packages.infrastructure.gmail_summary import GmailAuthorizationError, GmailDigestRunner


def _refusing_opener(status: int, body: dict):
    def opener(_request, *, timeout):  # type: ignore[no-untyped-def]
        raise urllib_error.HTTPError(
            "https://gmail.googleapis.com", status, "Refused", {}, io.BytesIO(json.dumps(body).encode("utf-8")),
        )
    return opener


class GmailRefusalReasonTests(unittest.TestCase):
    def test_a_missing_permission_is_told_apart_from_an_expired_token(self) -> None:
        opener = _refusing_opener(403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "details": [
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"},
        ]}})
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(GmailAuthorizationError) as context:
            GmailDigestRunner(opener=opener).save_message_attachments(
                "token", message_id="m1", output_dir=folder, url_prefix="/r",
            )
        self.assertEqual(context.exception.provider_code, "access_token_scope_insufficient")
        self.assertEqual(context.exception.provider_subtype, "http_403")

    def test_a_refusal_without_a_readable_body_still_raises_the_same_error(self) -> None:
        def opener(_request, *, timeout):  # type: ignore[no-untyped-def]
            raise urllib_error.HTTPError("https://gmail.googleapis.com", 401, "Unauthorized", {}, None)

        with tempfile.TemporaryDirectory() as folder, self.assertRaises(GmailAuthorizationError) as context:
            GmailDigestRunner(opener=opener).save_message_attachments(
                "token", message_id="m1", output_dir=folder, url_prefix="/r",
            )
        self.assertEqual(context.exception.provider_code, "")
        self.assertEqual(context.exception.provider_subtype, "http_401")


if __name__ == "__main__":
    unittest.main()
