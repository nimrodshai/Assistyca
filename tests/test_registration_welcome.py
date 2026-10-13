from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.infrastructure.notification_delivery import send_whatsapp_notification
from packages.infrastructure.registration_welcome import FAMILY_WELCOME_BODY
from packages.infrastructure.registration_welcome import HEBREW_FAMILY_WELCOME_BODY
from packages.infrastructure.registration_welcome import build_registration_welcome_message
from packages.infrastructure.registration_welcome import registration_welcome_plan
from packages.infrastructure.registration_welcome import registration_welcome_template_parameters
from packages.infrastructure.registration_welcome import resolve_registration_welcome_template


class RegistrationWelcomeTemplateTests(unittest.TestCase):
    def test_the_family_welcome_is_the_only_welcome(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            template = resolve_registration_welcome_template(base_url="https://assistyca.com/", name="Dana Levi")

        self.assertEqual((template.name, template.language), ("assistyca_welcome_family", "en"))
        self.assertEqual(template.parameters, ("Dana",))
        self.assertEqual(
            template.header_image_url,
            "https://assistyca.com/assets/assistyca-whatsapp-header-family.jpg",
        )
        self.assertTrue(template.message.startswith("Hi Dana 👋\nI'm your new assistant"))

    def test_the_environment_no_longer_names_a_template(self) -> None:
        # The business welcome could be swapped from the environment. The
        # family welcome is the welcome, in both languages, under one name.
        with mock.patch.dict(
            os.environ,
            {"WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_NAME": "assistyca_welcome2", "WHATSAPP_REGISTRATION_WELCOME_TEMPLATE_LANGUAGE": "he"},
            clear=True,
        ):
            template = resolve_registration_welcome_template(base_url="https://assistyca.com", name="Dana Levi")
        self.assertEqual((template.name, template.language), ("assistyca_welcome_family", "en"))

    def test_a_portal_with_no_public_address_sends_no_picture(self) -> None:
        # Meta fetches the header image itself, so a laptop address is no
        # address at all - and a picture it cannot fetch fails the whole
        # message, not just the header. Better a welcome without the picture.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_registration_welcome_template(base_url="", name="Dana").header_image_url, "")
            self.assertEqual(
                resolve_registration_welcome_template(base_url="http://127.0.0.1:8765", name="Dana").header_image_url,
                "",
            )
            self.assertEqual(
                resolve_registration_welcome_template(base_url="http://assistyca.com", name="Dana").header_image_url,
                "",
            )

    def test_a_hebrew_name_gets_the_hebrew_welcome(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            template = resolve_registration_welcome_template(name="יוני כהן")

        self.assertEqual((template.name, template.language), ("assistyca_welcome_family", "he"))
        self.assertEqual(template.parameters, ("יוני",))
        self.assertTrue(template.message.startswith("היי יוני 👋\nאני העוזר החדש שלך!"))

    def test_the_earlier_english_welcome_stands_behind_the_new_one(self) -> None:
        """Meta refuses a template it is still reviewing. The English family
        welcome it approved earlier takes one variable like the new one, so
        it carries the welcome - in English - until the new pair is through."""

        for name in ("Dana Levi", "יוני כהן", ""):
            with self.subTest(name=name), mock.patch.dict(os.environ, {}, clear=True):
                plan = registration_welcome_plan(name=name)
                self.assertEqual([(t.name, t.language) for t in plan], [
                    ("assistyca_welcome_family", "he" if name == "יוני כהן" else "en"),
                    ("assistyca_welcome_family_english_short", "en"),
                ])
                self.assertEqual([len(t.parameters) for t in plan], [1, 1])
                self.assertTrue(plan[-1].message.startswith("Hi "))

    def test_any_other_language_gets_english(self) -> None:
        for name in ("Мария", "محمد", "José", ""):
            with self.subTest(name=name), mock.patch.dict(os.environ, {}, clear=True):
                template = resolve_registration_welcome_template(name=name)
                self.assertEqual((template.name, template.language), ("assistyca_welcome_family", "en"))


class RegistrationWelcomeMessageTests(unittest.TestCase):
    def test_the_message_reads_as_the_template_will_render_it(self) -> None:
        self.assertEqual(build_registration_welcome_message(name="Dana Levi"), f"Hi Dana \U0001F44B\n{FAMILY_WELCOME_BODY}")
        self.assertEqual(build_registration_welcome_message(name="דנה לוי"), f"היי דנה \U0001F44B\n{HEBREW_FAMILY_WELCOME_BODY}")

    def test_the_one_variable_is_the_first_name(self) -> None:
        self.assertEqual(registration_welcome_template_parameters(name="Dana Levi"), ["Dana"])

    def test_a_registrant_with_no_name_is_still_greeted(self) -> None:
        self.assertEqual(registration_welcome_template_parameters(name=""), ["there"])


class RegistrationWelcomeSendTests(unittest.TestCase):
    def send(self, **kwargs: object) -> dict:
        with mock.patch(
            "packages.infrastructure.whatsapp_messaging.send_whatsapp_message",
            return_value="wamid.welcome-1",
        ) as send:
            send_whatsapp_notification(
                recipient_wa_id="972500000000",
                access_token="test-token",
                phone_number_id="1186653017865246",
                **kwargs,
            )
        return send.call_args.kwargs["template"]

    def test_the_welcome_goes_out_with_its_picture_and_its_variables(self) -> None:
        template = self.send(
            message_text="Hi Dana, I'm Assistyca.",
            template_name="assistyca_welcome_family",
            template_language="en",
            template_parameters=["Dana"],
            template_header_image_url="https://assistyca.com/assets/top.png",
        )

        self.assertEqual(template["name"], "assistyca_welcome_family")
        self.assertEqual(template["language"], {"code": "en"})
        header, body = template["components"]
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["parameters"][0]["image"], {"link": "https://assistyca.com/assets/top.png"})
        self.assertEqual([parameter["text"] for parameter in body["parameters"]], ["Dana"])

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
                template_name="assistyca_welcome_family",
                template_language="en",
                template_parameters=["   "],
            )


if __name__ == "__main__":
    unittest.main()
