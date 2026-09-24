from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.infrastructure.notification_delivery import send_whatsapp_notification
from packages.infrastructure.registration_welcome import REGISTRATION_WELCOME_CLOSING
from packages.infrastructure.registration_welcome import build_registration_welcome_message
from packages.infrastructure.registration_welcome import REGISTRATION_WELCOME_LINE
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


class FamilyWelcomeTemplateTests(unittest.TestCase):
    def test_a_family_with_an_english_name_gets_the_english_family_welcome(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            template = resolve_registration_welcome_template(kind="family", name="Dana Levi")

        self.assertEqual((template.name, template.language), ("assistyca_welcome_family_1", "en"))
        self.assertEqual(
            registration_welcome_template_parameters(name="Dana Levi", kind="family"),
            ["Dana", 'No more "Did you remember to take Noah to soccer?". I\'ll keep track of who\'s '
             "taking who, and remind them in time."],
        )

    def test_a_family_with_a_hebrew_name_gets_the_hebrew_family_welcome(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            template = resolve_registration_welcome_template(kind="family", name="יוני כהן")

        self.assertEqual((template.name, template.language), ("assistyca_welcome_family_1_hebrew", "he"))
        self.assertEqual(
            registration_welcome_template_parameters(name="יוני כהן", kind="family"),
            ["יוני", 'בואו נשים סוף להודעות כמו "זכרת לקחת את יוני לכדורגל?". אני אעקוב מי לוקח את מי, '
             "ואזכיר להם בזמן."],
        )

    def test_every_welcome_carries_both_variables(self) -> None:
        """Meta refuses a send that is one parameter short, family included.

        Dropping the family line on 2026-09-23 - on the reading that the
        template carries it as fixed text - got "(#132000) Number of
        parameters does not match the expected number of params" and a family
        with no welcome at all.
        """

        for kind in ("business", "family"):
            for name in ("Dana Levi", "יוני כהן", ""):
                with self.subTest(kind=kind, name=name):
                    self.assertEqual(
                        len(registration_welcome_template_parameters(name=name, kind=kind)), 2
                    )

    def test_any_other_language_gets_english(self) -> None:
        for name in ("Мария", "محمد", "José", ""):
            with self.subTest(name=name):
                self.assertEqual(
                    resolve_registration_welcome_template(kind="family", name=name).name,
                    "assistyca_welcome_family_1",
                )

    def test_a_family_welcome_carries_the_waving_robot(self) -> None:
        for name in ("Dana Levi", "דנה לוי"):
            with self.subTest(name=name), mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    resolve_registration_welcome_template(
                        base_url="https://assistyca.com/", kind="family", name=name
                    ).header_image_url,
                    "https://assistyca.com/assets/assistyca-whatsapp-header-family.jpg",
                )

    def test_a_business_keeps_its_welcome_whatever_the_language(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            template = resolve_registration_welcome_template(kind="business", name="דנה לוי")

        self.assertEqual((template.name, template.language), ("assistyca_welcome1", "en"))


class RegistrationWelcomeMessageTests(unittest.TestCase):
    def test_the_message_reads_as_the_template_will_render_it(self) -> None:
        message = build_registration_welcome_message(name="Dana Levi")

        self.assertEqual(
            message,
            "Hi Dana \U0001F44B I'm Assistyca and I'm here to help.\n"
            f"{REGISTRATION_WELCOME_LINE}\n{REGISTRATION_WELCOME_CLOSING}",
        )

    def test_the_variables_are_the_first_name_and_the_fixed_line(self) -> None:
        self.assertEqual(
            registration_welcome_template_parameters(name="Dana Levi"),
            [
                "Dana",
                "Since you’re a software developer, you can tell me things like “what did I spend on "
                "software last month?”, “did the plumber ever send the invoice?”, or “summarise "
                "that long thread in three lines.”",
            ],
        )

    def test_a_registrant_with_no_name_is_still_greeted(self) -> None:
        parameters = registration_welcome_template_parameters(name="")

        self.assertEqual(parameters[0], "there")


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
        """Meta answers "(#131008) Required parameter is missing" to a blank.

        Proven on production on 2026-09-24. Refusing it here costs a caller
        one exception instead of a round trip and a registrant with nothing.
        """

        with self.assertRaises(RuntimeError):
            self.send(
                message_text="anything",
                template_name="assistyca_welcome1",
                template_language="en",
                template_parameters=["Dana", "   "],
            )


if __name__ == "__main__":
    unittest.main()
