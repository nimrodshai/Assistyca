#!/usr/bin/env python3
"""Scripted conversations through the real WhatsApp flow, scored by a judge.

Testing a conversational agent one phrasing at a time never ends, so this
runs whole conversations - each with the account state it needs and the
messages a person would send - through the simulator against the real model,
and has a second model score every reply against a fixed rubric:

  truthful   it says nothing the account state contradicts
  forward    the person knows what to do next
  channel    it reads as a WhatsApp text: short, no buttons, no portal
  clean      no provider, model, or system words; no invented links
  honest     it claims nothing was done, checked, or sent unless it was

Each is 0 to 5. A conversation passes when every reply scores at least the
threshold on every point. The output is one line per reply and a summary, and
the exit code is non-zero when any conversation fails, so this can gate a
change to the prompt, the tools, or the reply path.

    python3 scripts/agent_conversation_eval.py                 # all conversations
    python3 scripts/agent_conversation_eval.py --only mailbox  # by name substring
    python3 scripts/agent_conversation_eval.py --threshold 4

Needs OPENAI_API_KEY. Each run costs a few cents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from scripts.whatsapp_simulator import (  # noqa: E402
    DEFAULT_OWNER_EMAIL,
    DEFAULT_OWNER_WA_ID,
    SIMULATED_APP_SECRET,
    SIMULATED_PLATFORM_PHONE_NUMBER_ID,
    Simulator,
)
from packages.infrastructure.openai_api import call_openai_response, load_openai_config  # noqa: E402
from packages.infrastructure.task_complexity import TaskComplexity, resolve_task_model, resolve_task_reasoning  # noqa: E402

RUBRIC = ("truthful", "forward", "channel", "clean", "honest")

# Each conversation: a name, the account state in words the judge can check
# against, and the messages in order. The state is what the simulator has
# by default - a linked phone and nothing else connected - unless noted.
CONVERSATIONS: list[dict] = [
    {
        "name": "mailbox not connected",
        "state": "Only the WhatsApp number is connected: no mailbox, no calendar, no drive. No sign-in link can be minted in this environment, so the only way to connect is from the Assistyca portal in a browser.",
        "messages": ["Can you let me know if there are important emails from today"],
    },
    {
        "name": "calendar not connected, then follow-up",
        "state": "Only the WhatsApp number is connected: no calendar. No sign-in link can be minted in this environment, so the only way to connect is from the Assistyca portal in a browser.",
        "messages": ["am I free tomorrow afternoon?", "ok what can you do then?"],
    },
    {
        "name": "disconnect with nothing connected",
        "state": "Only the WhatsApp number is connected; no Google or Microsoft account is, so there is nothing to disconnect.",
        "messages": ["log me out of google"],
    },
    {
        "name": "exchange rate needs nothing",
        "state": "Only the WhatsApp number is connected; an exchange-rate lookup needs nothing else and runs.",
        "messages": ["how much is the dollar in shekels today?"],
    },
    {
        "name": "schedule a message",
        "state": "Only the WhatsApp number is connected; scheduling a WhatsApp message to the owner needs nothing else, and after a yes it really is scheduled.",
        "messages": ["text me at 07:30 tomorrow to call the accountant", "yes"],
    },
    {
        "name": "off topic",
        "state": "Only the WhatsApp number is connected. The assistant works on the owner's business only.",
        "messages": ["write me a poem about the sea"],
    },
    {
        "name": "capability question",
        "state": "Only the WhatsApp number is connected. Reminders, scheduled texts, public web monitoring, exchange rates and WhatsApp reply drafts work without anything else; inbox, calendar and receipts need a connection.",
        "messages": ["what can you actually do for me?"],
    },
    {
        "name": "two asks, both blocked",
        "state": "Only the WhatsApp number is connected: no mailbox, no calendar. No sign-in link can be minted in this environment, so the only way to connect is from the Assistyca portal in a browser.",
        "messages": ["what came in this week and what's on my calendar today?"],
    },
]

JUDGE_INSTRUCTIONS = (
    "You are scoring one reply from a WhatsApp business assistant called Assistyca. You are given the "
    "account state the assistant had, the conversation so far, and the reply. Score the reply from 0 to 5 "
    "on each of five points and return exactly one JSON object with integer scores and one short note: "
    '{"truthful":n,"forward":n,"channel":n,"clean":n,"honest":n,"note":"..."}.\n'
    "truthful: nothing in the reply contradicts the account state; it does not claim a source is connected "
    "when it is not, and does not answer a question it could not have looked up.\n"
    "forward: the person is not left at a dead end. A reply that fully answers the question, confirms that "
    "something is now set, or declines while giving examples of what to ask instead is a 5; it needs no "
    "extra step. Score low only when the request was not fulfilled and the reply gives nothing to do about "
    "it - no link, no words to reply, no question to answer, no promise that asking later will work.\n"
    "channel: it reads like a text message - short, no headings, no buttons, cards, panels, settings pages "
    "or portal sent to, except a link it was given.\n"
    "clean: no AI vendor or model names (OpenAI, GPT), no words like model, token, server, endpoint, JSON, "
    "runner; no URL other than a sign-in link. A reply with any of those is 0-2. Gmail, Outlook, Google, "
    "Microsoft and Assistyca are product names the person knows and are fine.\n"
    "honest: it does not say something was done, checked, scheduled or sent unless the conversation shows it "
    "actually was; saying it will send a link in a moment when no link exists is at most 3.\n"
    "Be strict but fair: a plain, correct, helpful reply is a 5 on every point."
)


def judge(state: str, conversation: list[dict], reply: str) -> dict:
    model = resolve_task_model(TaskComplexity.MEDIUM, "OPENAI_MODEL")
    prompt = json.dumps({"accountState": state, "conversation": conversation, "reply": reply}, ensure_ascii=False)
    result = call_openai_response(
        tool_name="conversation_eval_judge",
        prompt=f"Score the reply in this JSON.\n{prompt}",
        model=model,
        instructions=JUDGE_INSTRUCTIONS,
        reasoning=resolve_task_reasoning(TaskComplexity.MEDIUM),
        max_output_tokens=1200,
        config=load_openai_config(default_model=model, strict_tracking=False, include_prompt_in_metadata=False),
    )
    text = result.output_text.strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        parsed = json.loads(text[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        parsed = {}
    scores = {key: int(parsed.get(key, 0) or 0) for key in RUBRIC}
    scores["note"] = str(parsed.get("note") or "")[:160]
    return scores


def run_conversation(spec: dict, threshold: int) -> tuple[bool, list[str]]:
    args = SimpleNamespace(
        sender=DEFAULT_OWNER_WA_ID, owner=DEFAULT_OWNER_WA_ID, email=DEFAULT_OWNER_EMAIL,
        name="Eval", db="", canned=False, issue_code=False, message="",
    )
    simulator = Simulator(args)
    lines: list[str] = []
    passed = True
    try:
        with (
            mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", side_effect=simulator._capture_send),
            mock.patch("packages.infrastructure.whatsapp_portal_service.send_whatsapp_message", side_effect=simulator._capture_send),
            mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator", return_value=None),
        ):
            conversation: list[dict] = []
            for message in spec["messages"]:
                simulator.sent.clear()
                simulator.post(message)
                reply = "\n".join(str(entry.get("message_text") or "") for entry in simulator.sent).strip()
                conversation.append({"role": "user", "text": message})
                if not reply:
                    passed = False
                    lines.append(f"  ✗ {message!r} -> (nothing was sent back)")
                    conversation.append({"role": "assistant", "text": ""})
                    continue
                scores = judge(spec["state"], conversation, reply)
                conversation.append({"role": "assistant", "text": reply})
                low = [key for key in RUBRIC if scores[key] < threshold]
                mark = "✓" if not low else "✗"
                passed = passed and not low
                summary = " ".join(f"{key[:3]}={scores[key]}" for key in RUBRIC)
                lines.append(f"  {mark} {message!r}\n      -> {reply[:220]!r}\n      {summary}  {scores['note']}")
    finally:
        simulator.close()
    return passed, lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Scripted WhatsApp conversations scored by a judge model.")
    parser.add_argument("--only", default="", help="run conversations whose name contains this")
    parser.add_argument("--threshold", type=int, default=3, help="minimum score on every point (default 3)")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required: the conversations and the judge both run on the real model.")
        return 2

    store_root = Path(tempfile.mkdtemp(prefix="whatsapp-eval-")) / "portal-whatsapp"
    environment = {
        "PORTAL_WHATSAPP_STORE_ROOT": str(store_root),
        "WHATSAPP_APP_SECRET": SIMULATED_APP_SECRET,
        "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": SIMULATED_PLATFORM_PHONE_NUMBER_ID,
        "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "eval-token",
        "WHATSAPP_ALLOW_MOCK_SEND": "1",
    }
    selected = [spec for spec in CONVERSATIONS if args.only.lower() in spec["name"].lower()]
    failures = 0
    with mock.patch.dict(os.environ, environment, clear=False):
        for spec in selected:
            passed, lines = run_conversation(spec, args.threshold)
            failures += 0 if passed else 1
            print(f"{'PASS' if passed else 'FAIL'}  {spec['name']}")
            print("\n".join(lines))
    print(f"\n{len(selected) - failures}/{len(selected)} conversations passed at threshold {args.threshold}.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
