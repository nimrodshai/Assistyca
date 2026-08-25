from __future__ import annotations

import io
import json
import unittest
from unittest import mock
from urllib import error as urllib_error
from urllib import parse as urllib_parse

from packages.infrastructure.whatsapp_api import WhatsAppConnectionError
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
    def test_subscribe_waba_establishes_baseline_then_uses_callback_override(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            side_effect=[
                FakeGraphResponse('{"success":true}'),
                FakeGraphResponse('{"success":true}'),
            ],
        ) as urlopen:
            result = subscribe_whatsapp_business_account(
                access_token="client-token",
                business_account_id="11111",
                callback_url="https://portal.example.com/webhooks/whatsapp",
                verify_token="verify-token",
            )

        self.assertEqual(result, {"success": True, "baselineSubscription": {"success": True}})
        self.assertEqual(urlopen.call_count, 2)
        baseline_request = urlopen.call_args_list[0].args[0]
        self.assertEqual(baseline_request.full_url, "https://graph.facebook.com/v20.0/11111/subscribed_apps")
        self.assertEqual(baseline_request.get_method(), "POST")
        self.assertEqual(baseline_request.get_header("Content-type"), "application/x-www-form-urlencoded")
        self.assertEqual(
            urllib_parse.parse_qs(baseline_request.data.decode("utf-8")),
            {"access_token": ["client-token"]},
        )

        override_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(override_request.full_url, "https://graph.facebook.com/v20.0/11111/subscribed_apps")
        self.assertEqual(override_request.get_method(), "POST")
        self.assertEqual(override_request.get_header("Authorization"), "Bearer client-token")
        self.assertEqual(override_request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(override_request.data.decode("utf-8")),
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

    def test_graph_http_errors_include_provider_message(self) -> None:
        error_body = {
            "error": {
                "message": "Error validating access token: Session has expired.",
                "type": "OAuthException",
                "code": 190,
            },
        }
        http_error = urllib_error.HTTPError(
            "https://graph.facebook.com/v20.0/11111/subscribed_apps",
            401,
            "Unauthorized",
            {},
            io.BytesIO(json.dumps(error_body).encode("utf-8")),
        )
        with mock.patch(
            "packages.infrastructure.whatsapp_api.urllib_request.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaises(WhatsAppConnectionError) as raised:
                subscribe_whatsapp_business_account(
                    access_token="expired-token",
                    business_account_id="11111",
                )

        self.assertIn("Session has expired", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
