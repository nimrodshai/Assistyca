from __future__ import annotations

import hmac
import hashlib
import json
import unittest
from unittest import mock
from urllib import parse as urllib_parse

from packages.infrastructure.lemon_squeezy_api import LemonSqueezyClient
from packages.infrastructure.lemon_squeezy_api import LemonSqueezyConfig
from packages.infrastructure.lemon_squeezy_api import LemonSqueezySignatureError
from packages.infrastructure.lemon_squeezy_api import load_lemon_squeezy_config
from packages.infrastructure.lemon_squeezy_api import parse_webhook_event
from packages.infrastructure.lemon_squeezy_api import require_valid_webhook_signature
from packages.infrastructure.lemon_squeezy_api import verify_webhook_signature


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class LemonSqueezyApiTests(unittest.TestCase):
    def test_load_config_reads_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "LEMON_SQUEEZY_API_KEY": "live_api_key",
                "LEMON_SQUEEZY_STORE_ID": "42",
                "LEMON_SQUEEZY_SIGNING_SECRET": "secret123",
                "LEMON_SQUEEZY_TEST_MODE": "true",
            },
            clear=False,
        ):
            config = load_lemon_squeezy_config()

        self.assertEqual(config.api_key, "live_api_key")
        self.assertEqual(config.store_id, "42")
        self.assertEqual(config.signing_secret, "secret123")
        self.assertTrue(config.test_mode)

    def test_verify_and_parse_webhook_event(self) -> None:
        secret = "secret123"
        raw_body = json.dumps(
            {
                "meta": {"event_name": "subscription_created"},
                "data": {
                    "type": "subscriptions",
                    "id": "12",
                    "attributes": {"status": "active", "user_email": "billing@example.com"},
                },
            }
        ).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        self.assertTrue(
            verify_webhook_signature(raw_body=raw_body, signature=signature, signing_secret=secret)
        )
        event = parse_webhook_event(raw_body, signature=signature, signing_secret=secret)

        self.assertEqual(event.event_name, "subscription_created")
        self.assertEqual(event.resource_type, "subscriptions")
        self.assertEqual(event.resource_id, "12")
        self.assertEqual(event.attributes["status"], "active")
        self.assertEqual(event.resource["user_email"], "billing@example.com")

    def test_invalid_webhook_signature_raises(self) -> None:
        with self.assertRaises(LemonSqueezySignatureError):
            require_valid_webhook_signature(
                raw_body=b'{"meta":{"event_name":"order_created"}}',
                signature="not-valid",
                signing_secret="secret123",
            )

    @mock.patch("packages.infrastructure.lemon_squeezy_api.urllib_request.urlopen")
    def test_create_checkout_uses_default_store_and_test_mode(self, mock_urlopen: mock.Mock) -> None:
        mock_urlopen.return_value = FakeHTTPResponse(
            {
                "data": {
                    "type": "checkouts",
                    "id": "chk_123",
                    "attributes": {
                        "url": "https://example.lemonsqueezy.com/checkout/custom/chk_123",
                        "test_mode": True,
                    },
                }
            }
        )
        client = LemonSqueezyClient(
            LemonSqueezyConfig(
                api_key="live_api_key",
                store_id="100",
                test_mode=True,
            )
        )

        checkout = client.create_checkout(
            variant_id="200",
            checkout_data={"email": "customer@example.com"},
            preview=True,
        )

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))

        self.assertEqual(checkout["id"], "chk_123")
        self.assertEqual(payload["data"]["relationships"]["store"]["data"]["id"], "100")
        self.assertEqual(payload["data"]["relationships"]["variant"]["data"]["id"], "200")
        self.assertTrue(payload["data"]["attributes"]["preview"])
        self.assertTrue(payload["data"]["attributes"]["test_mode"])
        self.assertEqual(payload["data"]["attributes"]["checkout_data"]["email"], "customer@example.com")

    @mock.patch("packages.infrastructure.lemon_squeezy_api.urllib_request.urlopen")
    def test_list_subscriptions_encodes_filters(self, mock_urlopen: mock.Mock) -> None:
        mock_urlopen.return_value = FakeHTTPResponse({"data": [], "meta": {"page": {"currentPage": 2}}})
        client = LemonSqueezyClient(LemonSqueezyConfig(api_key="live_api_key"))

        result = client.list_subscriptions(
            store_id="100",
            user_email="billing@example.com",
            status="active",
            page=2,
            page_size=50,
        )

        request = mock_urlopen.call_args.args[0]
        parsed = urllib_parse.urlparse(request.full_url)
        query = urllib_parse.parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/v1/subscriptions")
        self.assertEqual(query["filter[store_id]"], ["100"])
        self.assertEqual(query["filter[user_email]"], ["billing@example.com"])
        self.assertEqual(query["filter[status]"], ["active"])
        self.assertEqual(query["page[number]"], ["2"])
        self.assertEqual(query["page[size]"], ["50"])
        self.assertEqual(result["meta"]["page"]["currentPage"], 2)

    def test_create_usage_record_rejects_invalid_action(self) -> None:
        client = LemonSqueezyClient(LemonSqueezyConfig(api_key="live_api_key"))

        with self.assertRaises(ValueError):
            client.create_usage_record(subscription_item_id="10", quantity=5, action="replace")


if __name__ == "__main__":
    unittest.main()
