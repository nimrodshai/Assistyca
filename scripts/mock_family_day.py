#!/usr/bin/env python3
"""Mock families through the real family opening, then one simulated day.

Setup: a stranger phone registered on the web as a family, the welcome in the
transcript, and a model playing the parent from a fact sheet, through the real
webhook - the real routing, the real agent turn, the real tools, a throwaway
database. Where the fact sheet names a partner and the assistant offers the
invite, the partner joins from their own phone with the join code.

Day: the family week nudger and the scheduled-action runner are driven with the
clock set by hand - Sunday 20:00 for the evening before, then Monday 06:00 to
21:30 in ten-minute steps - and every message to every phone is captured. No
school calendar is consulted, so the day is the usual week.

    python3 scripts/mock_family_day.py                 # all families, in parallel
    python3 scripts/mock_family_day.py peretz levi     # by id
    MOCK_FAMILY_OUT=/tmp/out python3 scripts/mock_family_day.py

Each family writes <out>/<id>.json: setup transcript, what was saved, the
partner's conversation, the day's messages and the scheduled-action rows.
Needs OPENAI_API_KEY; a run is a few dollars across the five families.

The simulator only reads message_text, so a reply that is a link button would
show as nothing sent; this reads the interactive body too.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import traceback
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from scripts.whatsapp_simulator import (  # noqa: E402
    SIMULATED_APP_SECRET,
    SIMULATED_PLATFORM_PHONE_NUMBER_ID,
    Simulator,
    build_inbound_payload,
)
import hashlib  # noqa: E402
import hmac  # noqa: E402
import urllib.request as urllib_request  # noqa: E402
import urllib.error as urllib_error  # noqa: E402

from packages.infrastructure import household  # noqa: E402
from packages.infrastructure.chat_flow import describe_chat_flow  # noqa: E402
from packages.infrastructure.family_week_nudges import FamilyWeekNudger, load_family_week_nudge_config  # noqa: E402
from packages.infrastructure.openai_api import call_openai_response, load_openai_config  # noqa: E402
from packages.infrastructure.registration_welcome import registration_welcome_attempts  # noqa: E402
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler, load_scheduled_action_config  # noqa: E402
from packages.infrastructure.standing_tasks import StandingTaskRunner  # noqa: E402
from packages.infrastructure.portal_auth.server import mint_agent_session_token  # noqa: E402
from packages.infrastructure.task_complexity import TaskComplexity, resolve_task_model, resolve_task_reasoning  # noqa: E402

OUT = Path(os.environ.get("MOCK_FAMILY_OUT") or tempfile.mkdtemp(prefix="mock-family-day-"))
OUT.mkdir(parents=True, exist_ok=True)
ZONE = ZoneInfo("Asia/Jerusalem")
SUNDAY = date(2026, 10, 4)
MONDAY = date(2026, 10, 5)
MAX_TURNS = 20

# ---------------------------------------------------------------- capture
CAPTURE_LOCK = threading.Lock()
CAPTURED: dict[str, list[dict]] = {}


def flatten_interactive(payload: dict | None) -> str:
    if not payload:
        return ""
    parts = []
    body = (payload.get("body") or {}).get("text")
    if body:
        parts.append(body)
    action = payload.get("action") or {}
    if action.get("name") == "cta_url":
        params = action.get("parameters") or {}
        parts.append(f"[button: {params.get('display_text')} -> {params.get('url')}]")
    for button in action.get("buttons") or []:
        reply = button.get("reply") or {}
        parts.append(f"[button: {reply.get('title')}]")
    return "\n".join(parts)


def capture_send(**kwargs) -> str:
    recipient = str(kwargs.get("recipient_wa_id") or "")
    text = kwargs.get("message_text")
    if text is None and kwargs.get("interactive"):
        text = flatten_interactive(kwargs["interactive"])
    elif kwargs.get("interactive"):
        text = f"{text}\n{flatten_interactive(kwargs['interactive'])}"
    if text is None and kwargs.get("template"):
        text = f"[template {kwargs['template'].get('name')}]"
    if kwargs.get("template_name"):
        text = f"[template {kwargs['template_name']}] {text}"
    with CAPTURE_LOCK:
        CAPTURED.setdefault(recipient, []).append({"text": text or "", "raw_keys": sorted(kwargs)})
    return f"wamid.sim-reply-{uuid.uuid4().hex[:12]}"


def drain(recipient: str) -> list[str]:
    with CAPTURE_LOCK:
        items = CAPTURED.pop(recipient, [])
    return [item["text"] for item in items]


# ---------------------------------------------------------------- families
FAMILIES = [
    {
        "id": "peretz",
        "owner": {"name": "Dana Peretz", "phone": "972501110001"},
        "partner": {"name": "Yoav", "phone": "972501110002"},
        "line": "Two kids, judo twice a week, a gan and a school",
        "language": "English",
        "facts": """
You are Dana Peretz, mum in Tel Aviv. Partner: Yoav (husband). You type in English, casually.
Kids:
- Noa, 8, at Gretz school, Sun-Thu 08:00-13:30. Yoav drops her off, Dana (you) collect her.
  Judo on Monday and Wednesday 16:30-17:30 at the Maccabi gym. Yoav takes her, you collect.
  Noa's birthday is 20 October 2018.
- Itai, 4, at gan Shaked, Sun-Thu 07:30-16:00. You drop him off, Yoav collects.
  Itai's birthday is 3 March 2022.
Your own week: you work Sun-Thu 09:00-17:00 at an office in Ramat Gan. If asked whether to put your hours in, say yes and give them.
Google Calendar: if offered, say "not now".
If offered to bring Yoav onto the account / invite him: yes, Yoav.
""",
    },
    {
        "id": "levi",
        "owner": {"name": "מיכל לוי", "phone": "972501110011"},
        "partner": {"name": "אורי", "phone": "972501110012"},
        "line": "שני ילדים, גן ובית ספר, חוג שחייה",
        "language": "Hebrew",
        "facts": """
את מיכל לוי, אמא מרעננה. כותבת בעברית, קצר וטבעי. בן זוג: אורי.
ילדים:
- תמר, בת 10, בית ספר "אוסטרובסקי", א'-ה' 08:00-13:30. תמר הולכת לבית הספר ברגל וחוזרת באוטובוס - אף אחד לא מסיע.
  חוג ציור ביום שני 16:00-17:00 במתנ"ס. את לוקחת, סבתא רותי אוספת.
  יום הולדת של תמר: 12 בדצמבר 2015.
- עומר, בן 6, גן "אלון", א'-ה' 07:45-16:30. את מביאה בבוקר, אורי אוסף.
  שחייה ביום שלישי 17:00-17:45 בבריכה העירונית, אורי לוקח ומחזיר.
  יום הולדת של עומר: 5 ביוני 2020.
השבוע שלך: עובדת חצי משרה א'-ה' 08:30-14:00. אם שואלים אם להכניס את השעות שלך - כן.
יומן גוגל: אם מציעים, "לא עכשיו".
אם מציעים להוסיף את אורי לחשבון / לשלוח לו קישור: כן, אורי.
""",
    },
    {
        "id": "okafor",
        "owner": {"name": "Sam Okafor", "phone": "972501110021"},
        "partner": None,
        "line": "Single dad, one daughter, after-school club and ballet",
        "language": "English",
        "facts": """
You are Sam Okafor, a single dad in Haifa. No partner; it is just you and Maya. You type in English, brief.
- Maya, 7, at Hugim school, Sun-Thu 08:00-13:00, then the tzaharon (after-school club) at the school until 16:30.
  You drop her at 08:00 and collect her at 16:30 every day.
  Ballet on Thursday 17:00-18:00 at Studio Dance Haifa, you take and collect.
  Maya's birthday is 14 November 2019.
Your own week: you work Sun-Thu 08:30-16:00 in Matam. If asked whether to put your hours in, say yes and give them.
Google Calendar: if offered, say yes, you would like to connect it (you will not actually be able to; if a link comes, say thanks you'll do it later).
There is nobody else to invite; if offered, say it is just the two of you.
""",
    },
    {
        "id": "cohen-adler",
        "owner": {"name": "Ruth Cohen-Adler", "phone": "972501110031"},
        "partner": {"name": "Daniel", "phone": "972501110032"},
        "line": "Three kids, teen goes on his own, basketball with nobody to collect yet",
        "language": "English",
        "facts": """
You are Ruth Cohen-Adler, mum of three in Modiin. Partner: Daniel. You type in English, a bit chatty.
Kids:
- Lior, 14, at Mor high school, Sun-Thu 08:00-14:30. He goes on his own (bus), nobody takes or collects.
- Shira, 11, at Nitzanim school, Sun-Thu 08:00-13:45. Daniel drops her off and Daniel collects.
  Basketball Monday and Wednesday 18:00-19:30 at the city sports hall. Daniel takes her. Nobody is set to collect her yet - you and Daniel haven't sorted it; if asked, say "we haven't worked that out yet, leave it open".
  Shira's birthday is 2 February 2015.
- Adam, 5, at gan Rimon, Sun-Thu 07:40-16:00. You drop him off, Daniel collects.
  Adam's birthday is 30 October 2021.
Your own week: you work from home, flexible hours. If asked whether to put your hours in, say no, it's flexible.
Google Calendar: if offered, "no thanks".
If offered to invite Daniel: yes.
""",
    },
    {
        "id": "friedman",
        "owner": {"name": "Tom Friedman", "phone": "972501110041"},
        "partner": {"name": "Noa", "phone": "972501110042"},
        "line": "Dad does both morning drop-offs back to back, piano on Mondays",
        "language": "English",
        "facts": """
You are Tom Friedman, dad in Herzliya. Partner: Noa (wife). You type in English, short and practical.
Kids:
- Ella, 9, at Bar Ilan school, Sun-Thu 07:45-13:30. You drop her off, Noa collects.
  Piano on Monday 17:00-17:45 at the conservatory, you take and collect.
  Ella's birthday is 8 October 2017 (this week!).
- Ben, 3, at gan Tut, Sun-Thu 08:00-16:00. You drop him off right after Ella, Noa collects.
  Ben's birthday is 19 January 2023.
Your own week: you work Sun-Thu 09:00-18:00 in Tel Aviv. If asked whether to put your hours in, say yes.
Google Calendar: if offered, "maybe later".
If offered to invite Noa: yes.
""",
    },
]

PARENT_INSTRUCTIONS = """You are role-playing a parent texting a new WhatsApp assistant that is getting to know their family so it can manage the weekly schedule (who takes and collects whom). Stay fully in character and reply ONLY with the parent's next WhatsApp message - no quotes, no narration.
Rules:
- Answer what the assistant actually asked, in the parent's language. Give the relevant facts from the fact sheet, naturally, a few at a time (a real person does not dump everything at once, but does answer the question fully).
- Do not invent facts beyond the sheet. If asked something the sheet does not cover, say you are not sure / it varies.
- Keep messages short, like real texts. Vary the wording. No bullet lists unless listing several children's times.
- When the assistant says the week is set up / all done and asks nothing further, or after you have replied to the invite link (say you forwarded it), reply with exactly: DONE
- If the assistant gives you an invite link for your partner, say you'll forward it (one short line), and then on the following turn reply DONE.
- If the assistant sends a link to a week page, you can say thanks; if there is nothing left to answer, reply DONE.
- Never reply DONE while the assistant still has an open question for you.
"""


def parent_reply(family: dict, transcript: list[dict]) -> str:
    model = resolve_task_model(TaskComplexity.MEDIUM, "OPENAI_MODEL")
    prompt = json.dumps({"factSheet": family["facts"], "conversation": transcript}, ensure_ascii=False)
    result = call_openai_response(
        tool_name="mock_family_parent",
        prompt=f"Fact sheet and conversation so far (you are 'user'). Write the parent's next message.\n{prompt}",
        model=model,
        instructions=PARENT_INSTRUCTIONS,
        reasoning=resolve_task_reasoning(TaskComplexity.MEDIUM),
        max_output_tokens=1500,
        config=load_openai_config(default_model=model, strict_tracking=False, include_prompt_in_metadata=False),
    )
    return str(result.output_text or "").strip()


# ---------------------------------------------------------------- one family
class Run:
    def __init__(self, family: dict) -> None:
        self.family = family
        self.log: list[str] = []
        self.transcript: list[dict] = []
        self.partner_transcript: list[dict] = []
        self.day: list[dict] = []
        owner = family["owner"]
        self.args = SimpleNamespace(
            sender=owner["phone"], owner="972500000000", email=f"sim-{family['id']}@example.com",
            name=owner["name"], db="", canned=False, issue_code=False, message="",
        )
        self.sim = Simulator(self.args)
        self.db = self.sim.server.database

    def say(self, line: str) -> None:
        self.log.append(line)
        print(f"[{self.family['id']}] {line}", flush=True)

    def post_as(self, text: str, sender: str, name: str) -> dict:
        body = json.dumps(build_inbound_payload(text, sender_wa_id=sender, sender_name=name)).encode("utf-8")
        signature = hmac.new(SIMULATED_APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(
            f"{self.sim.base_url}/webhooks/whatsapp", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
        )
        try:
            with urllib_request.urlopen(request, timeout=300) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return {"ok": False, "httpStatus": exc.code, "body": exc.read().decode("utf-8", "replace")}

    def user_id(self) -> int:
        return int(self.db.get_user_id_for_whatsapp_number(self.family["owner"]["phone"]) or 0)

    def household_state(self) -> dict:
        uid = self.user_id()
        if uid <= 0:
            return {"accountOpen": False}
        user = self.db.get_user_by_id(uid) or {}
        profile = self.db.get_household_profile(user_id=uid) or {}
        members = self.db.list_household_members(user_id=uid)
        activities = self.db.list_household_activities(user_id=uid)
        block = household.describe_household(
            profile=profile, members=members, activities=activities, today=SUNDAY,
            owner_names=[user.get("displayName") or ""],
        )
        flow = describe_chat_flow(
            account_type=user.get("accountType") or user.get("account_type"), profile=profile, connected=[],
            today=SUNDAY.isoformat(), household_block=block,
        )
        return {
            "accountOpen": True, "userId": uid, "accountType": user.get("accountType") or user.get("account_type"),
            "gettingToKnow": profile.get("gettingToKnow"), "weekReady": flow.get("weekReady"),
            "weekGaps": flow.get("weekGaps"), "flow": flow.get("flow") or flow.get("stage"),
            "members": members, "activities": activities,
        }

    def setup(self) -> None:
        owner = self.family["owner"]
        self.db.start_web_registration(wa_id=owner["phone"], name=owner["name"], business=self.family["line"], kind="family")
        welcome = registration_welcome_attempts(name=owner["name"], kind="family")[0].message
        self.db.append_whatsapp_signup_message(wa_id=owner["phone"], role="assistant", text=welcome)
        self.transcript.append({"role": "assistant", "text": welcome})
        self.say(f"welcome: {welcome!r}")
        invite_code = ""
        for turn in range(MAX_TURNS):
            message = parent_reply(self.family, self.transcript)
            if message.strip().upper() == "DONE":
                self.say("parent: DONE")
                break
            self.transcript.append({"role": "user", "text": message})
            self.say(f"parent -> {message!r}")
            drain(owner["phone"])
            result = self.post_as(message, owner["phone"], owner["name"])
            replies = drain(owner["phone"])
            if not replies:
                routing = json.dumps(result)[:300]
                self.say(f"assistant -> (nothing sent) {routing}")
                self.transcript.append({"role": "assistant", "text": "(no reply)"})
            for reply in replies:
                self.say(f"assistant -> {reply!r}")
                self.transcript.append({"role": "assistant", "text": reply})
                found = re.search(r"/join/([A-Za-z0-9]+)", reply)
                if found:
                    invite_code = found.group(1)
            state = self.household_state()
            self.say(f"state: gtk={state.get('gettingToKnow')} ready={state.get('weekReady')} gaps={[g.get('kind') if isinstance(g, dict) else g for g in (state.get('weekGaps') or [])]}")
        self.final_state = self.household_state()
        if invite_code and self.family.get("partner"):
            self.join_partner(invite_code)

    def join_partner(self, code: str) -> None:
        partner = self.family["partner"]
        text = f"Assistyca family {code}"
        self.say(f"partner {partner['name']} -> {text!r}")
        drain(partner["phone"])
        self.post_as(text, partner["phone"], partner["name"])
        replies = drain(partner["phone"])
        self.partner_transcript.append({"role": "user", "text": text})
        for reply in replies:
            self.say(f"assistant (to partner) -> {reply!r}")
            self.partner_transcript.append({"role": "assistant", "text": reply})
        if not replies:
            self.say("assistant (to partner) -> (nothing sent)")
        follow = "תודה, מה יש השבוע?" if self.family["language"] == "Hebrew" else "Thanks! What's on this week?"
        self.say(f"partner -> {follow!r}")
        self.post_as(follow, partner["phone"], partner["name"])
        replies = drain(partner["phone"])
        self.partner_transcript.append({"role": "user", "text": follow})
        for reply in replies:
            self.say(f"assistant (to partner) -> {reply!r}")
            self.partner_transcript.append({"role": "assistant", "text": reply})
        self.members_after_join = self.db.list_household_members(user_id=self.user_id())

    def run_day(self) -> None:
        server = self.sim.server
        nudge_config = load_family_week_nudge_config()
        nudger = FamilyWeekNudger(self.db, config=nudge_config, school_calendar=None, calendar_reader=None)
        runner = StandingTaskRunner(
            database=self.db, base_url=self.sim.base_url,
            session_token_factory=lambda email: mint_agent_session_token(server.store, email),
        )
        scheduler = ScheduledActionScheduler(self.db, config=load_scheduled_action_config(), task_runner=runner.run)
        phones = {self.family["owner"]["phone"]: "owner"}
        if self.family.get("partner"):
            phones[self.family["partner"]["phone"]] = f"partner {self.family['partner']['name']}"
        moments = [datetime.combine(SUNDAY, datetime.min.time(), ZONE).replace(hour=20, minute=5)]
        t = datetime.combine(MONDAY, datetime.min.time(), ZONE).replace(hour=6, minute=0)
        end = t.replace(hour=21, minute=30)
        while t <= end:
            moments.append(t)
            t += timedelta(minutes=10)
        for moment in moments:
            summary = nudger.run_pending(now=moment)
            queued = sum(int(summary.get(k) or 0) for k in ("morning", "evening", "rides", "birthdays", "askedAgain"))
            if not queued:
                continue
            for phone in phones:
                drain(phone)
            # Dispatch at the same simulated time. The runner writes the words.
            dispatched = scheduler.run_pending(now=moment)
            stamp = moment.strftime("%a %H:%M")
            self.say(f"{stamp} nudger={summary} scheduler={dispatched}")
            for phone, who in phones.items():
                for text in drain(phone):
                    self.day.append({"at": stamp, "to": who, "text": text})
                    self.say(f"{stamp} -> {who}: {text!r}")
        # Anything still queued (e.g. a failed run) for the record.
        leftovers = self.db.list_scheduled_actions_for_user(self.user_id(), limit=50)
        self.leftovers = [
            {"id": a.get("id"), "status": a.get("status"), "title": (a.get("payload") or {}).get("title"),
             "error": a.get("lastError"), "runAt": a.get("runAt"), "delivered": (a.get("payload") or {}).get("deliveredVia"),
             "mode": (a.get("payload") or {}).get("whatsappSendMode")}
            for a in leftovers
        ]

    def save(self) -> None:
        payload = {
            "family": {k: v for k, v in self.family.items() if k != "facts"},
            "transcript": self.transcript,
            "partnerTranscript": self.partner_transcript,
            "finalState": getattr(self, "final_state", None),
            "membersAfterJoin": getattr(self, "members_after_join", None),
            "day": self.day,
            "scheduledActions": getattr(self, "leftovers", None),
            "log": self.log,
        }
        (OUT / f"{self.family['id']}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    def go(self) -> None:
        try:
            self.setup()
            self.run_day()
        except Exception:
            self.say("ERROR\n" + traceback.format_exc())
        finally:
            self.save()
            try:
                self.sim.close()
            except Exception:
                pass


def main() -> int:
    only = set(sys.argv[1:])
    families = [f for f in FAMILIES if not only or f["id"] in only]
    store_root = Path(tempfile.mkdtemp(prefix="mock-families-")) / "portal-whatsapp"
    environment = {
        "PORTAL_WHATSAPP_STORE_ROOT": str(store_root),
        "WHATSAPP_APP_SECRET": SIMULATED_APP_SECRET,
        "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": SIMULATED_PLATFORM_PHONE_NUMBER_ID,
        "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "simulator-token",
        "ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": "15550000000",
        "WHATSAPP_ALLOW_MOCK_SEND": "1",
        "PORTAL_FAMILY_NUDGES_ENABLED": "1",
    }
    patches = [
        mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", side_effect=capture_send),
        mock.patch("packages.infrastructure.whatsapp_portal_service.send_whatsapp_message", side_effect=capture_send),
        mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator", return_value=None),
        mock.patch("packages.infrastructure.scheduled_actions.send_whatsapp_notification", side_effect=capture_send),
        mock.patch("packages.infrastructure.notification_delivery.send_whatsapp_notification", side_effect=capture_send),
    ]
    with mock.patch.dict(os.environ, environment, clear=False):
        for p in patches:
            p.start()
        try:
            runs = [Run(f) for f in families]
            threads = [threading.Thread(target=run.go, name=run.family["id"]) for run in runs]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        finally:
            for p in reversed(patches):
                p.stop()
    print("ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
