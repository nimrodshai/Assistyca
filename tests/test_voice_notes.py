"""A voice note becomes words, on the account's bill, before the turn runs."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import openai_api
from packages.infrastructure.openai_api import OpenAIConfig
from packages.infrastructure.openai_api import OpenAIGateway
from packages.infrastructure.openai_api import OpenAITrackingError
from packages.infrastructure.openai_api import OpenAITranscriptionRequest
from packages.infrastructure.openai_api import encode_multipart_form
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.task_complexity import TRANSCRIPTION_MODEL
from packages.infrastructure.voice_notes import VOICE_NOTE_MAX_BYTES
from packages.infrastructure.voice_notes import VoiceNoteError
from packages.infrastructure.voice_notes import describe_voice_note_problem
from packages.infrastructure.voice_notes import normalize_voice_note
from packages.infrastructure.voice_notes import transcribe_voice_note
from packages.infrastructure.voice_notes import voice_note_transcript_text

MODULE = "packages.infrastructure.openai_api"
AUDIO_BYTES = b"\x1aE\xdf\xa3" + bytes(range(256)) * 8
AUDIO_BASE64 = base64.b64encode(AUDIO_BYTES).decode("ascii")


class VoiceNoteShapeTests(unittest.TestCase):
    def test_a_browser_data_url_with_a_codec_is_read(self) -> None:
        note = normalize_voice_note({"dataUrl": f"data:audio/webm;codecs=opus;base64,{AUDIO_BASE64}", "durationSeconds": "4.26"})

        self.assertEqual(note["mimeType"], "audio/webm")
        self.assertEqual(note["audioBytes"], AUDIO_BYTES)
        self.assertEqual(note["size"], len(AUDIO_BYTES))
        self.assertEqual(note["durationSeconds"], 4.3)

    def test_a_bare_base64_body_beside_its_type_is_read_too(self) -> None:
        note = normalize_voice_note({"audioBase64": AUDIO_BASE64, "mimeType": "audio/ogg; codecs=opus", "fileName": " note.ogg "})

        self.assertEqual(note["mimeType"], "audio/ogg")
        self.assertEqual(note["fileName"], "note.ogg")

    def test_anything_that_is_not_a_recording_is_dropped(self) -> None:
        self.assertEqual(normalize_voice_note(None), {})
        self.assertEqual(normalize_voice_note({}), {})
        self.assertEqual(normalize_voice_note({"dataUrl": f"data:image/png;base64,{AUDIO_BASE64}"}), {})
        self.assertEqual(normalize_voice_note({"dataUrl": "data:audio/webm;base64,not*base64"}), {})
        self.assertEqual(normalize_voice_note({"dataUrl": "https://example.com/a.webm"}), {})
        self.assertEqual(normalize_voice_note({"audioBase64": AUDIO_BASE64, "mimeType": "video/mp4"}), {})
        too_big = base64.b64encode(b"\x00" * (VOICE_NOTE_MAX_BYTES + 1)).decode("ascii")
        self.assertEqual(normalize_voice_note({"audioBase64": too_big, "mimeType": "audio/wav"}), {})

    def test_the_problem_is_named_for_the_browser(self) -> None:
        self.assertIn("image/png", describe_voice_note_problem({"dataUrl": f"data:image/png;base64,{AUDIO_BASE64}"}))
        self.assertIn("not a base64", describe_voice_note_problem({"dataUrl": "https://example.com/a.webm"}))
        self.assertIn("MB", describe_voice_note_problem({"audioBase64": "", "mimeType": "audio/webm"}))
        self.assertIn("no voice note", describe_voice_note_problem(None))

    def test_the_transcript_keeps_that_the_words_were_spoken(self) -> None:
        self.assertEqual(voice_note_transcript_text("  pull my receipts "), "pull my receipts [voice note]")
        self.assertEqual(voice_note_transcript_text(""), "[voice note]")


class _Recorder:
    def __init__(self, price: dict[str, Any] | None) -> None:
        self.price = price
        self.records: list[dict[str, Any]] = []

    def get_model_price(self, model_name: str) -> dict[str, Any] | None:
        return self.price

    def upsert_model_price(self, *args: Any, **kwargs: Any) -> None:
        return None

    def record_usage(self, email: str, model_name: str, **kwargs: Any) -> dict[str, Any]:
        record = {"email": email, "model": model_name, **kwargs}
        self.records.append(record)
        return {"id": len(self.records)}


PRICE_ROW = {"input_price_cents_per_1k_tokens": 0.125, "output_price_cents_per_1k_tokens": 0.5, "currency": "USD"}


class GatewayTranscriptionTests(unittest.TestCase):
    def test_the_recording_goes_up_as_a_file_and_the_words_come_back_billed(self) -> None:
        recorder = _Recorder(PRICE_ROW)
        gateway = OpenAIGateway(
            config=OpenAIConfig(api_key="test-key", strict_tracking=True),
            usage_recorder=recorder,
            billing_email="owner@example.com",
        )
        with (
            mock.patch(f"{MODULE}.resolve_current_openai_model_price", create=True, return_value=PRICE_ROW),
            mock.patch(
                f"{MODULE}._multipart_request",
                return_value=({"text": " Pull my receipts from last month. ", "usage": {"type": "tokens", "input_tokens": 40, "output_tokens": 9}}, 200),
            ) as upload,
        ):
            result = gateway.transcribe_audio(
                OpenAITranscriptionRequest(tool_name="voice_note_transcription", audio_bytes=AUDIO_BYTES, mime_type="audio/mp4")
            )

        self.assertEqual(result.text, "Pull my receipts from last month.")
        self.assertEqual(result.model, TRANSCRIPTION_MODEL)
        self.assertTrue(upload.call_args.args[0].endswith("/audio/transcriptions"))
        kwargs = upload.call_args.kwargs
        self.assertEqual(kwargs["fields"]["model"], TRANSCRIPTION_MODEL)
        file_name, data, content_type = kwargs["files"]["file"]
        self.assertEqual(file_name, "voice-note.m4a")
        self.assertEqual(data, AUDIO_BYTES)
        self.assertEqual(content_type, "audio/mp4")
        self.assertEqual(len(recorder.records), 1)
        record = recorder.records[0]
        self.assertEqual(record["email"], "owner@example.com")
        self.assertEqual(record["model"], TRANSCRIPTION_MODEL)
        self.assertEqual((record["input_tokens"], record["output_tokens"]), (40, 9))
        self.assertEqual(record["metadata"]["kind"], "transcription")
        self.assertNotIn("prompt", record["metadata"])

    def test_a_model_that_reports_only_seconds_is_not_billed_and_says_so(self) -> None:
        recorder = _Recorder(PRICE_ROW)
        events: list[dict[str, Any]] = []
        gateway = OpenAIGateway(
            config=OpenAIConfig(api_key="test-key", strict_tracking=False),
            usage_recorder=recorder,
            billing_email="owner@example.com",
            event_sink=events.append,
        )
        with mock.patch(
            f"{MODULE}._multipart_request",
            return_value=({"text": "Hello", "usage": {"type": "duration", "seconds": 4}}, 200),
        ):
            result = gateway.transcribe_audio(
                OpenAITranscriptionRequest(tool_name="voice_note_transcription", audio_bytes=AUDIO_BYTES, model="whisper-1")
            )

        self.assertEqual(result.text, "Hello")
        self.assertEqual(recorder.records, [])
        skipped = [event for event in events if event["event"] == "openai.usage.skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("token usage", skipped[0]["reason"])

        strict = OpenAIGateway(
            config=OpenAIConfig(api_key="test-key", strict_tracking=True),
            usage_recorder=recorder,
            billing_email="owner@example.com",
        )
        with (
            mock.patch(f"{MODULE}._multipart_request", return_value=({"text": "Hello", "usage": {"type": "duration", "seconds": 4}}, 200)),
            self.assertRaises(OpenAITrackingError),
        ):
            strict.transcribe_audio(OpenAITranscriptionRequest(tool_name="voice_note_transcription", audio_bytes=AUDIO_BYTES))

    def test_the_multipart_body_carries_the_file_with_its_name_and_type(self) -> None:
        body, content_type = encode_multipart_form({"model": "m"}, {"file": ("note.webm", b"abc", "audio/webm")})

        boundary = content_type.split("boundary=")[1]
        self.assertIn(f"--{boundary}\r\n".encode(), body)
        self.assertIn(b'Content-Disposition: form-data; name="model"\r\n\r\nm\r\n', body)
        self.assertIn(b'Content-Disposition: form-data; name="file"; filename="note.webm"\r\nContent-Type: audio/webm\r\n\r\nabc\r\n', body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_the_shared_helper_raises_in_plain_words(self) -> None:
        with mock.patch(
            "packages.infrastructure.voice_notes.call_openai_transcription",
            side_effect=openai_api.OpenAIRequestError("OpenAI returned HTTP 500."),
        ):
            with self.assertRaises(VoiceNoteError) as raised:
                transcribe_voice_note({"mimeType": "audio/webm", "audioBytes": AUDIO_BYTES}, billing_email="owner@example.com")
        self.assertIn("HTTP 500", str(raised.exception))

        with mock.patch(
            "packages.infrastructure.voice_notes.call_openai_transcription",
            return_value=SimpleNamespace(text="   "),
        ):
            with self.assertRaises(VoiceNoteError):
                transcribe_voice_note({"mimeType": "audio/webm", "audioBytes": AUDIO_BYTES}, billing_email="owner@example.com")

        with self.assertRaises(VoiceNoteError):
            transcribe_voice_note({}, billing_email="owner@example.com")


class TranscribeEndpointTests(unittest.TestCase):
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

    def _post(self, payload: dict[str, object], token: str = "") -> tuple[int, dict[str, object]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(
            f"{self.base_url}/api/agent/transcribe",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_the_words_come_back_to_the_composer(self) -> None:
        token = self._token()
        with mock.patch(
            "packages.infrastructure.voice_notes.call_openai_transcription",
            return_value=SimpleNamespace(text="Pull all my receipts from last month."),
        ) as transcribe:
            status, payload = self._post(
                {"voiceNote": {"dataUrl": f"data:audio/webm;codecs=opus;base64,{AUDIO_BASE64}", "durationSeconds": 3.2}},
                token,
            )

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["text"], "Pull all my receipts from last month.")
        self.assertEqual(payload["durationSeconds"], 3.2)
        kwargs = transcribe.call_args.kwargs
        self.assertEqual(kwargs["billing_email"], "owner@example.com")
        self.assertEqual(kwargs["mime_type"], "audio/webm")
        self.assertEqual(kwargs["audio_bytes"], AUDIO_BYTES)
        self.assertEqual(kwargs["model"], TRANSCRIPTION_MODEL)
        self.assertIs(kwargs["usage_recorder"], self.server.database)
        self.assertFalse(kwargs["config"].strict_tracking)

    def test_a_recording_nobody_is_signed_in_for_is_refused(self) -> None:
        status, payload = self._post({"voiceNote": {"audioBase64": AUDIO_BASE64, "mimeType": "audio/webm"}})

        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "unauthorized")

    def test_something_that_is_not_a_recording_is_named(self) -> None:
        token = self._token()
        status, payload = self._post({"voiceNote": {"audioBase64": AUDIO_BASE64, "mimeType": "video/mp4"}}, token)

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_voice_note")
        self.assertIn("video/mp4", payload["message"])

    def test_a_transcription_that_fails_says_so_without_provider_details(self) -> None:
        token = self._token()
        with mock.patch(
            "packages.infrastructure.voice_notes.call_openai_transcription",
            side_effect=openai_api.OpenAIRequestError("OpenAI returned HTTP 500.", details="{...}"),
        ):
            status, payload = self._post({"voiceNote": {"audioBase64": AUDIO_BASE64, "mimeType": "audio/ogg"}}, token)

        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "transcription_failed")
        self.assertNotIn("500", payload["message"])
        self.assertIn("type it instead", payload["message"])


if __name__ == "__main__":
    unittest.main()
