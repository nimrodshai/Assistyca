"""A photo sent with a chat message reaches the model as an image."""

from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.agent_proposals import AGENT_PHOTO_DEFAULT_TEXT
from packages.infrastructure.agent_proposals import AGENT_PHOTO_MAX_BYTES
from packages.infrastructure.agent_proposals import build_agent_turn_input
from packages.infrastructure.agent_proposals import build_agent_turn_prompt
from packages.infrastructure.agent_proposals import normalize_agent_photo_context
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")
PNG_DATA_URL = f"data:image/png;base64,{PNG_BASE64}"


class PhotoContextTests(unittest.TestCase):
    def test_a_data_url_photo_is_kept_with_its_name_and_size(self) -> None:
        photo = normalize_agent_photo_context({"dataUrl": PNG_DATA_URL, "fileName": " receipt.png "})

        self.assertEqual(photo["mimeType"], "image/png")
        self.assertEqual(photo["fileName"], "receipt.png")
        self.assertEqual(photo["size"], len(PNG_BYTES))
        self.assertEqual(photo["dataUrl"], PNG_DATA_URL)

    def test_a_bare_base64_body_with_its_type_is_kept_too(self) -> None:
        photo = normalize_agent_photo_context({"imageBase64": PNG_BASE64, "mimeType": "image/jpg"})

        self.assertEqual(photo["mimeType"], "image/jpeg")
        self.assertTrue(photo["dataUrl"].startswith("data:image/jpeg;base64,"))

    def test_anything_that_is_not_a_readable_image_is_dropped(self) -> None:
        self.assertEqual(normalize_agent_photo_context(None), {})
        self.assertEqual(normalize_agent_photo_context({}), {})
        self.assertEqual(normalize_agent_photo_context({"dataUrl": f"data:text/plain;base64,{PNG_BASE64}"}), {})
        self.assertEqual(normalize_agent_photo_context({"dataUrl": "data:image/png;base64,not*base64"}), {})
        self.assertEqual(normalize_agent_photo_context({"dataUrl": "https://example.com/a.png"}), {})
        self.assertEqual(normalize_agent_photo_context({"imageBase64": PNG_BASE64, "mimeType": "image/svg+xml"}), {})

    def test_a_photo_over_the_cap_is_dropped_before_it_is_decoded(self) -> None:
        too_big = base64.b64encode(b"\x00" * (AGENT_PHOTO_MAX_BYTES + 1)).decode("ascii")

        self.assertEqual(normalize_agent_photo_context({"dataUrl": f"data:image/jpeg;base64,{too_big}"}), {})

    def test_the_prompt_names_the_photo_and_never_carries_its_bytes(self) -> None:
        photo = normalize_agent_photo_context({"dataUrl": PNG_DATA_URL, "fileName": "receipt.png"})

        prompt = build_agent_turn_prompt(
            user_message="what did I pay here?",
            conversation=[],
            timezone_name="UTC",
            photo_context=photo,
        )

        self.assertIn('"attachedPhoto":{"fileName":"receipt.png","mimeType":"image/png"}', prompt)
        self.assertIn("A photo is attached to this message", prompt)
        self.assertNotIn(PNG_BASE64[:40], prompt)

    def test_without_a_photo_the_prompt_says_so_and_skips_the_rules(self) -> None:
        prompt = build_agent_turn_prompt(user_message="hello", conversation=[], timezone_name="UTC")

        self.assertIn('"attachedPhoto":null', prompt)
        self.assertNotIn("A photo is attached to this message", prompt)

    def test_the_turn_input_puts_the_text_before_the_image(self) -> None:
        photo = normalize_agent_photo_context({"dataUrl": PNG_DATA_URL})

        items = build_agent_turn_input("PROMPT", photo)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["role"], "user")
        self.assertEqual(items[0]["content"][0], {"type": "input_text", "text": "PROMPT"})
        self.assertEqual(items[0]["content"][1]["type"], "input_image")
        self.assertEqual(items[0]["content"][1]["image_url"], PNG_DATA_URL)
        self.assertIsNone(build_agent_turn_input("PROMPT", {}))
        self.assertIsNone(build_agent_turn_input("PROMPT", None))


class PhotoTurnApiTests(unittest.TestCase):
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

    def _token(self, email: str = "owner@example.com") -> str:
        self.server.database.register_user(email)
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        return str((result or {}).get("token") or "")

    def _post_turn(self, payload: dict[str, object], token: str) -> tuple[int, dict[str, object]]:
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/turn",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    @staticmethod
    def _reply(text: str) -> SimpleNamespace:
        return SimpleNamespace(output_text=json.dumps({
            "outcome": "message",
            "reply": text,
            "proposalType": "",
            "changes": {},
        }))

    def test_a_photo_travels_to_the_model_as_an_image_beside_the_prompt(self) -> None:
        token = self._token()
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._reply("That receipt is for 84.50 at Cafe Noir."),
        ) as call_openai:
            status, payload = self._post_turn({
                "userMessage": "how much did I pay here?",
                "timezone": "UTC",
                "conversation": [{"role": "user", "text": "how much did I pay here?"}],
                "photoContext": {"fileName": "receipt.png", "dataUrl": PNG_DATA_URL},
            }, token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["reply"], "That receipt is for 84.50 at Cafe Noir.")
        call_openai.assert_called_once()
        kwargs = call_openai.call_args.kwargs
        content = kwargs["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertEqual(content[0]["text"], kwargs["prompt"])
        self.assertEqual(content[1], {"type": "input_image", "image_url": PNG_DATA_URL, "detail": "auto"})
        self.assertIn('"attachedPhoto":{"fileName":"receipt.png","mimeType":"image/png"}', kwargs["prompt"])
        self.assertNotIn(PNG_BASE64[:40], kwargs["prompt"])
        self.assertTrue(kwargs["metadata"]["hasPhoto"])
        self.assertFalse(kwargs["config"].include_prompt_in_metadata)

    def test_a_repair_retry_carries_the_photo_again(self) -> None:
        token = self._token()
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=[SimpleNamespace(output_text="not json at all"), self._reply("Looks like a parking ticket.")],
        ) as call_openai:
            status, payload = self._post_turn({
                "userMessage": "what is this?",
                "timezone": "UTC",
                "photoContext": {"fileName": "ticket.png", "dataUrl": PNG_DATA_URL},
            }, token)

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["reply"], "Looks like a parking ticket.")
        self.assertEqual(call_openai.call_count, 2)
        repair = call_openai.call_args_list[1].kwargs
        self.assertEqual(repair["input"][0]["content"][1]["image_url"], PNG_DATA_URL)
        self.assertIn("Your previous reply could not be used", repair["input"][0]["content"][0]["text"])

    def test_a_photo_on_its_own_is_a_message(self) -> None:
        token = self._token()
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._reply("That is a receipt from yesterday."),
        ) as call_openai:
            status, payload = self._post_turn({
                "userMessage": "",
                "timezone": "UTC",
                "photoContext": {"fileName": "receipt.png", "dataUrl": PNG_DATA_URL},
            }, token)

        self.assertEqual(status, 200, payload)
        self.assertIn(f'"latestUserMessage":"{AGENT_PHOTO_DEFAULT_TEXT}"', call_openai.call_args.kwargs["prompt"])

    def test_without_a_photo_the_request_is_the_prompt_string(self) -> None:
        token = self._token()
        with patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._reply("Hello."),
        ) as call_openai:
            status, _ = self._post_turn({
                "userMessage": "hello",
                "timezone": "UTC",
                "photoContext": {"fileName": "x.txt", "dataUrl": f"data:text/plain;base64,{PNG_BASE64}"},
            }, token)

        self.assertEqual(status, 200)
        kwargs = call_openai.call_args.kwargs
        self.assertIsNone(kwargs["input"])
        self.assertFalse(kwargs["metadata"]["hasPhoto"])
        self.assertIn('"attachedPhoto":null', kwargs["prompt"])


class PhotoComposerMarkupTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.html = (root / "portal" / "index.html").read_text(encoding="utf-8")
        self.script = (root / "portal" / "app.js").read_text(encoding="utf-8")
        self.styles = (root / "portal" / "styles.css").read_text(encoding="utf-8")

    def test_the_composer_offers_a_photo_and_previews_it(self) -> None:
        composer = self.html[
            self.html.index('<form id="agentComposerForm"'):
            self.html.index('<button id="agentComposerButton"')
        ]
        self.assertIn('id="agentPhotoFileInput"', composer)
        self.assertIn('accept="image/*"', composer)
        self.assertIn('id="agentAttachSourcePhotoOption"', composer)
        self.assertIn("Attach photo", composer)
        self.assertIn('id="agentPhotoAttachment"', composer)
        self.assertIn('id="agentPhotoAttachmentRemove"', composer)
        self.assertIn(".agent-photo-attachment {", self.styles)
        self.assertIn(".agent-message-photo {", self.styles)

    def test_the_photo_goes_with_the_message_and_stays_in_the_bubble(self) -> None:
        self.assertIn("async function attachAgentPhoto", self.script)
        self.assertIn("function drawAgentPhoto", self.script)
        self.assertIn("photoContext,", self.script)
        self.assertIn("thumbnailUrl: photo.thumbnailUrl", self.script)
        self.assertIn('image.className = "agent-message-photo"', self.script)
        self.assertIn("function normalizeAgentMessagePhoto", self.script)
        self.assertIn("void attachAgentPhoto(pastedPhoto)", self.script)
        self.assertIn('addEventListener("drop", handleAgentComposerDrop)', self.script)
        # The full-size image is sent, never stored: only the thumbnail lives
        # in the transcript.
        self.assertNotIn("dataUrl: photo.dataUrl, thumbnailUrl", self.script)


if __name__ == "__main__":
    unittest.main()
