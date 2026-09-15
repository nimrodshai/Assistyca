from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.infrastructure.notification_delivery import send_whatsapp_notification
from packages.infrastructure.registration_welcome import REGISTRATION_WELCOME_CLOSING
from packages.infrastructure.registration_welcome import build_registration_welcome_line_prompt
from packages.infrastructure.registration_welcome import build_registration_welcome_message
from packages.infrastructure.registration_welcome import compose_registration_welcome_line
from packages.infrastructure.registration_welcome import registration_welcome_line_fallback
from packages.infrastructure.registration_welcome import registration_welcome_template_parameters
from packages.infrastructure.registration_welcome import resolve_registration_welcome_template


class RegistrationWelcomeTemplateTests(unittest.TestCase):
    def test_the_approved_template_is_the_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            template = resolve_registration_welcome_template(base_url="https://assistyca.com/")

        self.assertEqual(template.name, "assistyca_welcome1")
        # "English" in WhatsApp Manager is `en`; `en_US` is a template we do not have.
        self.assertEqual(template.language, "en")
        self.assertEqual(
            template.header_image_url,
            "https://assistyca.com/assets/assistyca-whatsapp-header-tagline.png",
        )

    def test_the_environment_can_name_another_template_and_picture(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_NAME": "assistyca_welcome2",
                "WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE": "he",
                "WHATSAPP_REGISTRATION_WELCOME_HEADER_IMAGE_URL": "https://cdn.example.com/top.png",
            },
            clear=True,
        ):
            template = resolve_registration_welcome_template(base_url="https://assistyca.com")

        self.assertEqual(template.name, "assistyca_welcome2")
        self.assertEqual(template.language, "he")
        self.assertEqual(template.header_image_url, "https://cdn.example.com/top.png")

    def test_a_portal_with_no_public_address_sends_no_picture(self) -> None:
        # Meta fetches the header image itself, so a laptop address is no
        # address at all - and a picture it cannot fetch fails the whole
        # message, not just the header. Better a welcome without the picture.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_registration_welcome_template(base_url="").header_image_url, "")
            self.assertEqual(
                resolve_registration_welcome_template(base_url="http://127.0.0.1:8765").header_image_url,
                "",
            )
            self.assertEqual(
                resolve_registration_welcome_template(base_url="http://assistyca.com").header_image_url,
                "",
            )


class RegistrationWelcomeMessageTests(unittest.TestCase):
    def test_the_message_reads_as_the_template_will_render_it(self) -> None:
        line = compose_registration_welcome_line("I can chase the receipts and keep the calendar tidy.")
        message = build_registration_welcome_message(name="Dana Levi", line=line)

        self.assertTrue(message.startswith("Hi Dana \U0001F44B I'm Assistyca and I'm here to help.\n"))
        self.assertIn("I can chase the receipts and keep the calendar tidy.", message)
        self.assertTrue(message.endswith(f"\n{REGISTRATION_WELCOME_CLOSING}"))

    def test_the_line_carries_the_way_out_for_a_mistyped_number(self) -> None:
        line = compose_registration_welcome_line("Hand me the follow-ups.")

        self.assertIn("If you didn't register at assistyca.com", line)

    def test_a_line_the_model_did_not_write_falls_back(self) -> None:
        self.assertTrue(compose_registration_welcome_line("").startswith(registration_welcome_line_fallback()))
        self.assertTrue(
            compose_registration_welcome_line("", kind="family").startswith(
                registration_welcome_line_fallback(kind="family")
            )
        )

    def test_a_family_registrant_is_answered_about_their_week(self) -> None:
        self.assertIn("pickup", registration_welcome_line_fallback(kind="family"))
        self.assertIn("receipts", registration_welcome_line_fallback())

    def test_the_variables_are_the_first_name_and_the_line(self) -> None:
        line = compose_registration_welcome_line("Two things:\nthe inbox and the calendar.")
        parameters = registration_welcome_template_parameters(name="Dana Levi", line=line)

        self.assertEqual(parameters[0], "Dana")
        self.assertNotIn("\n", parameters[1])
        self.assertIn("the inbox and the calendar.", parameters[1])

    def test_a_registrant_with_no_name_is_still_greeted(self) -> None:
        parameters = registration_welcome_template_parameters(name="", line="anything")

        self.assertEqual(parameters[0], "there")

    def test_the_prompt_asks_for_the_middle_line_only(self) -> None:
        prompt = build_registration_welcome_line_prompt(name="Dana", business="A physiotherapy clinic")

        self.assertIn("Write only the middle line", prompt)
        self.assertIn("Do not greet them", prompt)
        self.assertIn("A physiotherapy clinic", prompt)


class RegistrationWelcomeSendTests(unittest.TestCase):
    def send(self, **kwargs: object) -> dict:
        with mock.patch(
            "packages.tools.whatsapp_reply_approval.server.send_whatsapp_message",
            return_value="wamid.welcome-1",
        ) as send:
            send_whatsapp_notification(
                recipient_wa_id="972500000000",
                access_token="test-token",
                phone_number_id="1186653017865246",
                **kwargs,
            )
        return send.call_args.kwargs["template"]

    def test_the_welcome_goes_out_with_its_picture_and_both_variables(self) -> None:
        template = self.send(
            message_text="Hi Dana, I'm Assistyca.",
            template_name="assistyca_welcome1",
            template_language="en",
            template_parameters=["Dana", "Hand me the receipts."],
            template_header_image_url="https://assistyca.com/assets/top.png",
        )

        self.assertEqual(template["name"], "assistyca_welcome1")
        self.assertEqual(template["language"], {"code": "en"})
        header, body = template["components"]
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["parameters"][0]["image"], {"link": "https://assistyca.com/assets/top.png"})
        self.assertEqual(
            [parameter["text"] for parameter in body["parameters"]],
            ["Dana", "Hand me the receipts."],
        )

    def test_a_template_without_parameters_still_carries_the_message(self) -> None:
        # The scheduled notification template has one variable and no picture,
        # and goes on being sent the way it always was.
        template = self.send(
            message_text="It's 12:40.",
            template_name="notification_message",
            template_language="en",
        )

        self.assertEqual(len(template["components"]), 1)
        self.assertEqual(template["components"][0]["parameters"][0]["text"], "It's 12:40.")

    def test_an_empty_variable_is_refused_before_it_reaches_meta(self) -> None:
        with self.assertRaises(RuntimeError):
            self.send(
                message_text="anything",
                template_name="assistyca_welcome1",
                template_language="en",
                template_parameters=["Dana", "   "],
            )


if __name__ == "__main__":
    unittest.main()
