#!/usr/bin/env python3
"""Chat with the WhatsApp agent without WhatsApp.

Everything between the webhook and the reply is the real thing: the real
signature check, the real routing, the real agent turn, the real runners, the
real database. Only Meta is missing. Outbound sends are captured and printed
here instead of being handed to the Graph API, and inbound messages are built
into the same JSON shape Meta posts and signed the same way.

That makes this the way to test the flow before the WhatsApp number is
verified, and the way to test what a phone we do not know sees -- which is
awkward to try on a real handset and easy to try here.

    python3 scripts/whatsapp_simulator.py
    python3 scripts/whatsapp_simulator.py --from 14155550123
    python3 scripts/whatsapp_simulator.py --message "text me at 12:40" --canned

Needs OPENAI_API_KEY for real agent replies. Without one every turn reports
that the agent is unavailable, which is honest but dull, so --canned swaps the
model for a fixed reply when what you are testing is the routing.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import urllib.error as urllib_error
import urllib.request as urllib_request
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.chdir(REPO_ROOT)

from packages.infrastructure.portal_auth.server import PortalConfig  # noqa: E402
from packages.infrastructure.portal_auth.server import create_server  # noqa: E402


SIMULATED_APP_SECRET = "whatsapp-simulator-app-secret"
SIMULATED_PLATFORM_PHONE_NUMBER_ID = "simulator-platform-phone"
DEFAULT_OWNER_WA_ID = "972507322341"
DEFAULT_OWNER_EMAIL = "owner@example.com"


def build_inbound_payload(text: str, *, sender_wa_id: str, sender_name: str) -> dict:
    """The JSON Meta posts for one inbound text message."""

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "simulator-waba",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": SIMULATED_PLATFORM_PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {"profile": {"name": sender_name}, "wa_id": sender_wa_id}
                            ],
                            "messages": [
                                {
                                    "from": sender_wa_id,
                                    "id": f"wamid.sim-{uuid.uuid4().hex[:16]}",
                                    "timestamp": "1756700000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class Simulator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.sent: list[dict] = []
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(args.db).resolve() if args.db else Path(self.temp_dir.name) / "portal.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.server = create_server(
            "127.0.0.1",
            0,
            REPO_ROOT,
            PortalConfig(db_path=db_path, session_secret="whatsapp-simulator-session-secret"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.db_path = db_path

        # The account the owner number belongs to. Saved every run so a
        # persistent database picks up where it left off rather than losing the
        # connection that makes routing work.
        self.server.database.register_user(args.email)
        self.server.database.save_whatsapp_connection(
            args.email,
            business_account_id="simulator-waba",
            phone_number_id="simulator-client-phone",
            owner_wa_id=args.owner,
            connection_status="connected",
        )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _capture_send(self, **kwargs) -> str:
        self.sent.append(kwargs)
        return f"wamid.sim-reply-{uuid.uuid4().hex[:12]}"

    def post(self, text: str) -> dict:
        body = json.dumps(
            build_inbound_payload(text, sender_wa_id=self.args.sender, sender_name=self.args.name)
        ).encode("utf-8")
        signature = hmac.new(SIMULATED_APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(
            f"{self.base_url}/webhooks/whatsapp",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={signature}",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=300) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return {"ok": False, "httpStatus": exc.code, "body": exc.read().decode("utf-8", "replace")}

    def send_message(self, text: str) -> None:
        self.sent.clear()
        print(f"\n\033[1m{self.args.sender} →\033[0m {text}")
        result = self.post(text)

        for message in self.sent:
            reply = message.get("message_text")
            if reply is None and message.get("template"):
                reply = f"[template {message['template'].get('name')}] {json.dumps(message['template'])[:200]}"
            print(f"\033[1m← Assistyca\033[0m {reply}")

        if not self.sent:
            print("\033[2m← (nothing was sent back)\033[0m")

        # What the webhook decided. This is the part a real phone cannot show
        # you, and it is usually the answer when a message goes unanswered.
        for entry in result.get("results", []) if isinstance(result, dict) else []:
            label = entry.get("action") or entry.get("type") or "?"
            route = entry.get("route") or "-"
            detail = entry.get("error") or entry.get("outcome") or ""
            print(f"\033[2m   [routing] {label} route={route} {detail}\033[0m")
        if isinstance(result, dict) and result.get("httpStatus"):
            print(f"\033[2m   [webhook] HTTP {result['httpStatus']} {result.get('body', '')[:200]}\033[0m")

    def run(self) -> int:
        print("WhatsApp simulator — the real flow with Meta faked out.")
        print(f"  database   {self.db_path}")
        print(f"  texting as {self.args.sender} ({self.args.name})")
        print(f"  account    {self.args.email}, owner number {self.args.owner}")
        if self.args.sender != self.args.owner:
            print("  note       this number is NOT the account's owner number, so it is a stranger")
        if not self.args.canned and not os.getenv("OPENAI_API_KEY"):
            print("  warning    OPENAI_API_KEY is unset, so the agent cannot think. Use --canned to test routing.")
        print()

        if self.args.message:
            self.send_message(self.args.message)
            return 0

        print("Type a message and press enter. Ctrl-C or an empty line to quit.\n")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not text:
                return 0
            self.send_message(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Chat with the WhatsApp agent without WhatsApp.")
    parser.add_argument("--from", dest="sender", default="", help="the phone number sending the message")
    parser.add_argument("--owner", default=DEFAULT_OWNER_WA_ID, help="the number saved on the account")
    parser.add_argument("--email", default=DEFAULT_OWNER_EMAIL, help="the portal account that owns it")
    parser.add_argument("--name", default="Simulator", help="the WhatsApp profile name of the sender")
    parser.add_argument("--message", default="", help="send one message and exit instead of chatting")
    parser.add_argument("--db", default="", help="keep the database at this path instead of a temporary one")
    parser.add_argument("--canned", action="store_true", help="skip the model and reply with fixed text")
    args = parser.parse_args()
    if not args.sender:
        args.sender = args.owner

    environment = {
        "WHATSAPP_APP_SECRET": SIMULATED_APP_SECRET,
        "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": SIMULATED_PLATFORM_PHONE_NUMBER_ID,
        "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "simulator-token",
        "WHATSAPP_ALLOW_MOCK_SEND": "1",
    }

    with mock.patch.dict(os.environ, environment, clear=False):
        simulator = Simulator(args)
        patches = [
            mock.patch(
                "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message",
                side_effect=simulator._capture_send,
            ),
            mock.patch(
                "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
                side_effect=simulator._capture_send,
            ),
        ]
        if args.canned:
            patches.append(
                mock.patch(
                    "packages.infrastructure.portal_auth.server.call_openai_response",
                    return_value=SimpleNamespace(
                        output_text=json.dumps({
                            "outcome": "message",
                            "reply": "Canned reply: the model was skipped for this run.",
                        })
                    ),
                )
            )
        for patch in patches:
            patch.start()
        try:
            return simulator.run()
        finally:
            for patch in reversed(patches):
                patch.stop()
            simulator.close()


if __name__ == "__main__":
    raise SystemExit(main())
