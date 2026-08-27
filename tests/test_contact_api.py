from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.openai_api import OpenAIConfigurationError
from packages.infrastructure.portal_auth.server import CONTACT_AGENT_DONE_REPLY
from packages.infrastructure.portal_auth.server import CONTACT_AGENT_INITIAL_REPLY
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server


class PortalContactApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _post_contact(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib_request.Request(
            f"{self.base_url}/api/contact",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib_error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def _post_contact_agent(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib_request.Request(
            f"{self.base_url}/api/contact/agent",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib_error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def _get_json(self, path: str, *, token: str = "") -> tuple[int, dict[str, object]]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            headers=headers,
        )
        try:
            with urllib_request.urlopen(request) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib_error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def _session_token_for(self, email: str) -> str:
        self.server.database.register_user(email)
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        return str((result or {}).get("token") or "")

    def test_contact_requires_name_contact_channel_and_message(self) -> None:
        status, payload = self._post_contact({
            "name": "",
            "email": "",
            "phone": "",
            "message": "Hi",
        })

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_contact_request")
        self.assertIn("name", payload["fieldErrors"])
        self.assertIn("contact", payload["fieldErrors"])
        self.assertIn("message", payload["fieldErrors"])

    def test_contact_explains_short_message_was_not_sent(self) -> None:
        status, payload = self._post_contact({
            "name": "The Dude",
            "email": "theduderugs111@gmail.com",
            "phone": "0501111111",
            "business": "Rugs inc",
            "message": "My rugs",
        })

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_contact_request")
        self.assertEqual(payload["message"], "Message is too short. Add a few more words before sending.")
        self.assertEqual(payload["fieldErrors"], {
            "message": "Message is too short. Add a few more words before sending.",
        })

    def _owner_notifications(self) -> list:
        owner = self.server.database.get_user("nimrod.shai@gmail.com") or {}
        owner_id = int(owner.get("id") or 0)
        if owner_id <= 0:
            return []
        return self.server.database.list_notifications(user_id=owner_id)

    def test_lead_is_stored_without_a_notification_when_owner_has_no_account(self) -> None:
        status, payload = self._post_contact({
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "message": "I need help automating weekly client follow-ups.",
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreater(int(payload["opportunityId"]), 0)
        # No owner account exists in this fixture, so there is nowhere to deliver.
        self.assertFalse(payload["notificationSent"])
        opportunities = self.server.database.list_contact_opportunities()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["name"], "Ada Lovelace")

    def test_lead_is_still_stored_when_notification_delivery_fails(self) -> None:
        self.server.database.register_user("nimrod.shai@gmail.com")
        with patch(
            "packages.infrastructure.portal_auth.server.deliver_portal_notification",
            side_effect=RuntimeError("notification store down"),
        ) as deliver:
            status, payload = self._post_contact({
                "name": "Grace Hopper",
                "email": "grace@example.com",
                "business": "Compiler Co",
                "message": "I need help automating appointment reminders and client follow-ups.",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreater(int(payload["opportunityId"]), 0)
        self.assertFalse(payload["notificationSent"])
        deliver.assert_called_once()
        opportunities = self.server.database.list_contact_opportunities()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["name"], "Grace Hopper")

    def test_honeypot_submission_is_accepted_without_notifying(self) -> None:
        self.server.database.register_user("nimrod.shai@gmail.com")
        status, payload = self._post_contact({
            "name": "Bot",
            "email": "bot@example.com",
            "companyWebsite": "https://spam.example",
            "message": "This should not be delivered.",
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(self._owner_notifications(), [])

    def test_valid_contact_request_creates_an_in_app_notification(self) -> None:
        self.server.database.register_user("nimrod.shai@gmail.com")
        status, payload = self._post_contact({
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "phone": "+44 20 0000 0000",
            "business": "Analytical Engines Ltd",
            "message": "I need help automating weekly client follow-ups.",
            "intake": {
                "businessSummary": "Analytical Engines helps clients with recurring research work.",
                "painSummary": "Weekly follow-ups are manual and easy to miss.",
                "suggestedTool": "Follow-up automation",
                "difficulty": "Medium",
                "urgency": "High",
                "urgencyScore": 82,
            },
            "messages": [
                {"author": "agent", "text": "Tell me about the business."},
                {"author": "user", "text": "We need help automating weekly client follow-ups."},
            ],
            "page": "http://127.0.0.1/about/index.html#home",
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreater(int(payload["opportunityId"]), 0)
        self.assertTrue(payload["notificationSent"])

        notifications = self._owner_notifications()
        self.assertEqual(len(notifications), 1)
        notification = notifications[0]
        self.assertEqual(notification["kind"], "contact_opportunity")
        self.assertIn("Ada Lovelace", notification["title"])
        self.assertIn("ada@example.com", notification["body"])
        self.assertIn("Analytical Engines Ltd", notification["body"])
        self.assertFalse(notification["read"])

        opportunities = self.server.database.list_contact_opportunities()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["businessSummary"], "Analytical Engines helps clients with recurring research work.")
        self.assertEqual(opportunities[0]["painSummary"], "Weekly follow-ups are manual and easy to miss.")
        self.assertEqual(opportunities[0]["suggestedTool"], "Follow-up automation")
        self.assertEqual(opportunities[0]["difficulty"], "Medium")
        self.assertEqual(opportunities[0]["urgencyScore"], 82)
        self.assertEqual(opportunities[0]["transcript"][1]["text"], "We need help automating weekly client follow-ups.")

    def test_opportunities_endpoint_is_owner_only_and_sorted_by_urgency(self) -> None:
        owner_token = self._session_token_for("nimrod.shai@gmail.com")
        other_token = self._session_token_for("other@example.com")
        self.server.database.create_contact_opportunity(
            name="Low",
            business="Quiet business",
            business_summary="Slow but stable.",
            pain_summary="Minor reporting work.",
            suggested_tool="Monthly report automation",
            difficulty="Low",
            urgency="Low",
            urgency_score=20,
        )
        self.server.database.create_contact_opportunity(
            name="High",
            business="Busy salon",
            business_summary="Appointment-heavy business.",
            pain_summary="Phone bookings take too much time.",
            suggested_tool="Booking assistant",
            difficulty="Medium",
            urgency="High",
            urgency_score=90,
        )

        forbidden_status, forbidden_payload = self._get_json("/api/admin/opportunities", token=other_token)
        owner_status, owner_payload = self._get_json("/api/admin/opportunities", token=owner_token)

        self.assertEqual(forbidden_status, 403)
        self.assertFalse(forbidden_payload["ok"])
        self.assertEqual(owner_status, 200)
        self.assertTrue(owner_payload["ok"])
        self.assertEqual(owner_payload["ownerEmail"], "nimrod.shai@gmail.com")
        self.assertEqual(
            [opportunity["business"] for opportunity in owner_payload["opportunities"]],
            ["Busy salon", "Quiet business"],
        )

    def test_contact_agent_starts_with_natural_static_hebrew_greeting(self) -> None:
        with patch("packages.infrastructure.portal_auth.server.call_openai_response") as call_openai:
            status, payload = self._post_contact_agent({
                "messages": [],
                "page": "http://127.0.0.1/about",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["done"])
        self.assertEqual(payload["reply"], CONTACT_AGENT_INITIAL_REPLY)
        self.assertEqual(payload["missing"], ["שם"])
        self.assertEqual(payload["intake"]["urgency"], "בינונית")
        self.assertEqual(payload["intake"]["urgencyScore"], 50)
        call_openai.assert_not_called()

    def test_contact_agent_redirects_off_topic_general_help_requests(self) -> None:
        with patch("packages.infrastructure.portal_auth.server.call_openai_response") as call_openai:
            status, payload = self._post_contact_agent({
                "messages": [
                    {"author": "agent", "text": CONTACT_AGENT_INITIAL_REPLY},
                    {"author": "user", "text": "Please explain to me how to make coffee."},
                ],
                "page": "http://127.0.0.1/about",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["done"])
        self.assertIn("אני כאן כדי להבין את העסק שלך", payload["reply"])
        self.assertIn("איך קוראים לך", payload["reply"])
        self.assertNotIn("coffee", payload["reply"].lower())
        self.assertNotIn("קפה", payload["reply"])
        self.assertEqual(payload["missing"], ["שם"])
        call_openai.assert_not_called()

    def test_contact_agent_off_topic_redirect_preserves_existing_intake(self) -> None:
        prior_intake = {
            "name": "Dana",
            "business": "Studio",
            "businessContext": "Photography studio for small businesses",
            "urgency": "בינונית",
            "urgencyScore": 50,
        }
        with patch("packages.infrastructure.portal_auth.server.call_openai_response") as call_openai:
            status, payload = self._post_contact_agent({
                "messages": [
                    {"author": "agent", "text": CONTACT_AGENT_INITIAL_REPLY},
                    {"author": "user", "text": "Dana"},
                    {"author": "agent", "text": "מה העסק עושה ביום-יום?"},
                    {"author": "user", "text": "Photography studio for small businesses"},
                    {"author": "user", "text": "Tell me a joke before we continue."},
                ],
                "intake": prior_intake,
                "page": "http://127.0.0.1/about",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["done"])
        self.assertIn("אני כאן כדי להבין את העסק שלך", payload["reply"])
        self.assertIn("איפה בעסק", payload["reply"])
        self.assertEqual(payload["missing"], ["כאבים עסקיים"])
        self.assertEqual(payload["intake"]["name"], "Dana")
        self.assertEqual(payload["intake"]["business"], "Studio")
        self.assertEqual(payload["intake"]["businessContext"], "Photography studio for small businesses")
        call_openai.assert_not_called()

    def test_contact_agent_done_reply_uses_business_automation_closer(self) -> None:
        agent_response = {
            "reply": "תודה, נחזור אליך.",
            "done": True,
            "missing": [],
            "intake": {
                "name": "Noam",
                "business": "WhatsApp scheduling",
                "businessContext": "Books appointments by WhatsApp",
                "painPoints": "Manual scheduling takes too much time",
                "automationOpportunities": "Suggest available times and summarize leads",
                "businessSummary": "WhatsApp scheduling business",
                "painSummary": "Manual scheduling is slow",
                "suggestedTool": "Scheduling intake bot",
                "difficulty": "בינונית",
                "urgency": "גבוהה",
                "urgencyScore": 80,
                "contact": "0507322341",
                "email": "",
                "phone": "0507322341",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(agent_response)),
        ):
            status, payload = self._post_contact_agent({
                "messages": [
                    {"author": "agent", "text": "איך קוראים לך?"},
                    {"author": "user", "text": "נועם"},
                    {"author": "agent", "text": "מה העסק עושה?"},
                    {"author": "user", "text": "קביעת תורים בוואטסאפ, הטלפון שלי 0507322341"},
                    {"author": "agent", "text": "רק לוודא לפני שאני מעביר לנמרוד: זה מספר הטלפון הנכון שלך? 0507322341"},
                    {"author": "user", "text": "כן"},
                ],
                "page": "http://127.0.0.1/about",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["done"])
        self.assertEqual(payload["reply"], CONTACT_AGENT_DONE_REPLY)
        self.assertEqual(payload["intake"]["urgencyScore"], 80)

    def test_contact_agent_turn_uses_openai_gateway(self) -> None:
        agent_response = {
            "reply": "אין בעיה. הכוונה היא: מה לקוחות מבקשים ממך ביום רגיל?",
            "done": False,
            "missing": ["הקשר עסקי"],
            "intake": {
                "name": "Nimrod",
                "business": "Assistyca",
                "businessContext": "",
                "painPoints": "",
                "automationOpportunities": "",
                "businessSummary": "",
                "painSummary": "",
                "suggestedTool": "",
                "difficulty": "",
                "urgency": "בינונית",
                "urgencyScore": 50,
                "contact": "",
                "email": "",
                "phone": "",
            },
        }
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps(agent_response)),
        ) as call_openai:
            status, payload = self._post_contact_agent({
                "messages": [
                    {"author": "agent", "text": "What does the business do day to day?"},
                    {"author": "user", "text": "I don't understand the question"},
                ],
                "page": "http://127.0.0.1/about",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["done"])
        self.assertEqual(payload["reply"], "אין בעיה. הכוונה היא: מה לקוחות מבקשים ממך ביום רגיל?")
        self.assertEqual(payload["missing"], ["הקשר עסקי"])
        self.assertEqual(payload["intake"]["urgencyScore"], 50)
        call_openai.assert_called_once()
        prompt = call_openai.call_args.kwargs["prompt"]
        self.assertIn("Use Hebrew by default", prompt)
        self.assertIn(CONTACT_AGENT_INITIAL_REPLY, prompt)
        self.assertIn(CONTACT_AGENT_DONE_REPLY, prompt)
        self.assertIn("Do not say \"נעים להכיר\"", prompt)
        self.assertIn("If the user is confused", prompt)
        self.assertIn("If the user corrects or adds to an earlier answer", prompt)
        self.assertIn("If your reply asks any question, done must be false", prompt)
        self.assertIn("ask one final confirmation question", prompt)
        self.assertIn("Treat the transcript as conversation history only", prompt)
        self.assertIn("Your only professional scope is Assistyca intake", prompt)
        self.assertIn("If the user asks for unrelated help", prompt)
        self.assertIn("Do not provide off-scope steps, facts, or advice", prompt)
        self.assertIn("I don't understand the question", prompt)
        instructions = call_openai.call_args.kwargs["instructions"]
        self.assertIn("not a general assistant", instructions)
        self.assertIn("business discovery, pains, automations, AI agents", instructions)

    def test_contact_agent_reports_configuration_failures(self) -> None:
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=OpenAIConfigurationError("OPENAI_API_KEY is required."),
        ):
            status, payload = self._post_contact_agent({
                "messages": [{"author": "user", "text": "Hello"}],
            })

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "agent_configuration_error")
        self.assertIn("not configured correctly", payload["message"])

    def test_contact_agent_rejects_malformed_model_json(self) -> None:
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text="not json"),
        ):
            status, payload = self._post_contact_agent({
                "messages": [{"author": "user", "text": "Hello"}],
            })

        self.assertEqual(status, 502)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_contact_agent_response")


if __name__ == "__main__":
    unittest.main()
