from __future__ import annotations

import json
import unittest
from unittest import mock
from urllib import parse as urllib_parse

from packages.infrastructure.whatsapp_api import subscribe_whatsapp_business_account


class FakeGraphResponse:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")


class WhatsAppApiTests(unittest.TestCase):
    def test_subscribe_waba_uses_callback_override_when_configured(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"success":true}'),
        ) as urlopen:
            result = subscribe_whatsapp_business_account(
                access_token="client-token",
                business_account_id="11111",
                callback_url="https://portal.example.com/webhooks/whatsapp",
                verify_token="verify-token",
            )

        self.assertEqual(result, {"success": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://graph.facebook.com/v20.0/11111/subscribed_apps")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer client-token")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "override_callback_uri": "https://portal.example.com/webhooks/whatsapp",
                "verify_token": "verify-token",
            },
        )

    def test_subscribe_waba_keeps_form_request_without_callback_override(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            return_value=FakeGraphResponse('{"success":true}'),
        ) as urlopen:
            result = subscribe_whatsapp_business_account(
                access_token="client-token",
                business_account_id="11111",
            )

        self.assertEqual(result, {"success": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        self.assertEqual(
            urllib_parse.parse_qs(request.data.decode("utf-8")),
            {"access_token": ["client-token"]},
        )


if __name__ == "__main__":
    unittest.main()
