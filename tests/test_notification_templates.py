from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packages.infrastructure.message_language import detect_message_language
from packages.infrastructure.message_language import remember_message_language
from packages.infrastructure.message_language import resolve_message_language
from packages.infrastructure.notification_templates import TEMPLATE_KIND_PAYLOAD_KEY
from packages.infrastructure.notification_templates import image_template_for
from packages.infrastructure.notification_templates import normalize_template_kind
from packages.infrastructure.notification_templates import template_for
from packages.infrastructure.portal_db import PortalDatabase


class MessageLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_script_of_the_words_says_the_language(self) -> None:
        self.assertEqual(detect_message_language("תזכיר לי מחר בבוקר"), "he")
        self.assertEqual(detect_message_language("Remind me tomorrow"), "en")
        self.assertEqual(detect_message_language("Dana: מחר ב-8"), "he")
        self.assertEqual(detect_message_language("👍"), "")
        self.assertEqual(detect_message_language("12:40"), "")
        self.assertEqual(detect_message_language(""), "")

    def test_nothing_written_yet_reads_the_name_and_then_falls_back_to_english(self) -> None:
        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "en")
        with mock.patch.object(self.database, "get_user_by_id", return_value={"displayName": "נמרוד"}):
            self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "he")
        with mock.patch.object(self.database, "get_user_by_id", return_value={"displayName": "Dana"}):
            self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "en")

    def test_the_language_they_write_in_is_kept_and_wins(self) -> None:
        self.assertEqual(remember_message_language(self.database, user_id=self.user_id, text="היי, מה קורה"), "he")
        self.assertEqual((self.database.get_household_profile(user_id=self.user_id) or {})["language"], "he")
        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "he")
        # An emoji on its own changes nothing.
        self.assertEqual(remember_message_language(self.database, user_id=self.user_id, text="👍"), "")
        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "he")
        # Writing in English from now on switches them.
        self.assertEqual(remember_message_language(self.database, user_id=self.user_id, text="thanks, see you"), "en")
        self.assertEqual(resolve_message_language(self.database, user_id=self.user_id), "en")

    def test_the_profile_refuses_a_language_it_does_not_know(self) -> None:
        with self.assertRaises(ValueError):
            self.database.save_household_profile(user_id=self.user_id, language="fr")


class NotificationTemplateTests(unittest.TestCase):
    def test_each_kind_has_one_name_in_both_languages(self) -> None:
        self.assertEqual(template_for("morning_digest", "he"), ("assistyca_morning_digest", "he"))
        self.assertEqual(template_for("morning_digest", "en"), ("assistyca_morning_digest", "en"))
        self.assertEqual(template_for("evening_glance", "he"), ("assistyca_evening_glance", "he"))
        self.assertEqual(template_for("reminder", ""), ("assistyca_reminder", "en"))

    def test_an_unnamed_kind_is_a_reminder(self) -> None:
        self.assertEqual(normalize_template_kind(""), "reminder")
        self.assertEqual(normalize_template_kind(None), "reminder")
        self.assertEqual(normalize_template_kind("something_else"), "reminder")
        self.assertEqual(TEMPLATE_KIND_PAYLOAD_KEY, "templateKind")

    def test_the_week_ahead_template_goes_only_with_its_picture(self) -> None:
        self.assertEqual(template_for("week_ahead", "he"), ("", ""))
        self.assertEqual(template_for("week_ahead", "he", with_image=True), ("assistyca_week_ahead", "he"))
        self.assertEqual(image_template_for("he"), ("assistyca_week_ahead", "he"))
        self.assertEqual(image_template_for("xx"), ("assistyca_week_ahead", "en"))


if __name__ == "__main__":
    unittest.main()
