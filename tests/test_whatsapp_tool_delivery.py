from __future__ import annotations

import unittest

from packages.infrastructure.whatsapp_tool_delivery import normalize_whatsapp_tool_delivery_settings


class WhatsAppToolDeliveryTests(unittest.TestCase):
    def test_missing_channels_default_to_empty_platform_list(self) -> None:
        settings = normalize_whatsapp_tool_delivery_settings({})

        self.assertEqual(settings["deliveryChannels"], [])

    def test_normalizes_both_delivery_channels(self) -> None:
        settings = normalize_whatsapp_tool_delivery_settings(
            {
                "deliveryChannel": "both",
                "telegramChatId": " 12345 ",
            }
        )

        self.assertEqual(settings["deliveryChannels"], ["whatsapp", "telegram"])
        self.assertEqual(settings["telegramChatId"], "12345")

    def test_normalizes_comma_separated_channels(self) -> None:
        settings = normalize_whatsapp_tool_delivery_settings(
            {
                "deliveryChannels": "telegram, whatsapp, telegram",
            }
        )

        self.assertEqual(settings["deliveryChannels"], ["telegram", "whatsapp"])

    def test_explicit_empty_channels_stay_empty(self) -> None:
        settings = normalize_whatsapp_tool_delivery_settings(
            {
                "deliveryChannels": [],
            }
        )

        self.assertEqual(settings["deliveryChannels"], [])

    def test_invalid_explicit_channels_stay_empty(self) -> None:
        settings = normalize_whatsapp_tool_delivery_settings(
            {
                "deliveryChannels": ["email"],
            }
        )

        self.assertEqual(settings["deliveryChannels"], [])


if __name__ == "__main__":
    unittest.main()
