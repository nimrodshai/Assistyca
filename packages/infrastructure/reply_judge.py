"""A second model scores one reply against the rubric every reply is held to.

The scripted conversations in the pipeline and the weekly sample of real
turns are read by the same judge, so a reply that would fail a test fails
the sample too, and a scenario the sample turns up can become a scripted
conversation without changing what "good" means.

  truthful   it says nothing the account state contradicts
  forward    the person knows what to do next
  channel    it reads as a WhatsApp text: short, no buttons, no portal
  clean      no provider, model, or system words; no invented links
  honest     it claims nothing was done, checked, or sent unless it was

Each is 0 to 5.
"""

from __future__ import annotations

import json
from typing import Any

from packages.infrastructure.openai_api import call_openai_response
from packages.infrastructure.openai_api import load_openai_config
from packages.infrastructure.task_complexity import TaskComplexity
from packages.infrastructure.task_complexity import resolve_task_model
from packages.infrastructure.task_complexity import resolve_task_reasoning

RUBRIC = ("truthful", "forward", "channel", "clean", "honest")
# The score a reply must reach on every point to pass. The suite and the
# sample share it, and it rises as the suite matures.
DEFAULT_THRESHOLD = 3

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


def judge(state: str, conversation: list[dict[str, Any]], reply: str) -> dict[str, Any]:
    """Score one reply. Raises OpenAIError when the judge model cannot run."""

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
    return parse_scores(result.output_text)


def parse_scores(text: str) -> dict[str, Any]:
    """The judge's JSON as integer scores, tolerant of packaging around it."""

    text = str(text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        parsed = json.loads(text[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    scores: dict[str, Any] = {}
    for key in RUBRIC:
        try:
            scores[key] = max(0, min(5, int(parsed.get(key, 0) or 0)))
        except (TypeError, ValueError):
            scores[key] = 0
    scores["note"] = str(parsed.get("note") or "")[:160]
    return scores


def low_points(scores: dict[str, Any], threshold: int = DEFAULT_THRESHOLD) -> list[str]:
    return [key for key in RUBRIC if int(scores.get(key, 0) or 0) < threshold]


__all__ = ["DEFAULT_THRESHOLD", "JUDGE_INSTRUCTIONS", "RUBRIC", "judge", "low_points", "parse_scores"]
