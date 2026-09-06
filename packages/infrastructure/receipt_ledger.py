"""What a receipt search has already read, so the next search reads less.

A receipt search lists the mail in a window, downloads each message, and
asks the model whether it is a receipt. The listing is one cheap call; the
downloads and the judging are what a search costs, and they were repeated
in full every time the same month was asked about.

The ledger is one row per message the judge has ruled on: what was read
off the message, and the verdict. A later search still lists the mailbox -
that is how mail that arrived since, or a mailbox connected since, gets
found - but a message already in the ledger is neither downloaded nor
judged again. A search for one vendor reads and judges the whole window,
so a later search for the whole month reuses all of it, not just that
vendor's mail.

Only a message the judge actually ruled on goes in. A batch the model could
not answer leaves its messages unjudged, and an unjudged message must be
looked at again next time rather than remembered as read.

Rows are tied to the wording of the judgement. When the prompt changes,
the version changes, every row is stale, and the next search reads the
month in full once. Clearing the ledger is always safe for the same reason.

A receipt the owner deleted from the receipts page is marked here as
dismissed, so the next search does not put it back.
"""

from __future__ import annotations

import hashlib
from typing import Any
from typing import Callable
from typing import Iterable

from packages.infrastructure.receipt_judge import RECEIPT_JUDGE_INSTRUCTIONS
from packages.infrastructure.receipt_judge import build_receipt_judgement_prompt

# The message fields a later run needs to rebuild the row a search produced.
LEDGER_ITEM_KEYS = ("id", "threadId", "from", "subject", "date", "snippet", "bodyText", "attachmentNames")
# Marks an item the ledger supplied whole, so it is neither downloaded nor
# counted against a search's download ceiling.
FROM_LEDGER_KEY = "fromLedger"
# Marks a freshly read item whose verdict the ledger supplied.
VERDICT_FROM_LEDGER_KEY = "verdictFromLedger"

KnownMessages = Callable[[list[str]], dict[str, dict[str, Any]]]


def judge_version() -> str:
    """The wording of the judgement, as a short fingerprint.

    Every ledger row records the version it was judged under. A change to
    the instructions or the prompt changes this, and rows judged under the
    old wording are read again rather than trusted.
    """

    sample = [{"ref": "1", "from": "a", "subject": "b", "date": "c", "body": "d", "attached": "none"}]
    text = RECEIPT_JUDGE_INSTRUCTIONS + "\n" + build_receipt_judgement_prompt(sample)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def has_verdict(item: Any) -> bool:
    verdict = item.get("receiptVerdict") if isinstance(item, dict) else None
    return isinstance(verdict, dict) and isinstance(verdict.get("isReceipt"), bool)


def ledger_item(item: dict[str, Any]) -> dict[str, Any]:
    """The part of a message worth keeping: what the row is rebuilt from."""

    kept: dict[str, Any] = {}
    for key in LEDGER_ITEM_KEYS:
        value = item.get(key)
        if key == "attachmentNames":
            if isinstance(value, list):
                kept[key] = [str(name) for name in value if str(name or "").strip()]
        elif value not in (None, ""):
            kept[key] = str(value)
    return kept


def _split_by_mailbox(items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if isinstance(item, dict):
            grouped.setdefault(str(item.get("mailbox") or "").strip(), []).append(item)
    return grouped


class MailReadLedger:
    """The ledger for one account, at the current judgement version."""

    def __init__(self, database: Any, *, user_id: int, version: str = "") -> None:
        self.database = database
        self.user_id = int(user_id or 0)
        self.version = version or judge_version()

    # -- reading -------------------------------------------------------------

    def lookup(self, mailbox: str, message_ids: list[str]) -> dict[str, dict[str, Any]]:
        """The remembered messages among these ids, ready to stand in for a download."""

        ids = [str(value or "").strip() for value in message_ids]
        ids = [value for value in ids if value]
        if self.user_id <= 0 or not ids:
            return {}
        try:
            rows = self.database.get_receipt_mail_reads(
                user_id=self.user_id, mailbox=mailbox, message_ids=ids, judge_version=self.version,
            )
        except Exception as exc:  # noqa: BLE001 - a ledger that cannot be read only costs a re-read
            print(f"Receipt ledger could not be read: {exc}", flush=True)
            return {}
        found: dict[str, dict[str, Any]] = {}
        for message_id, row in rows.items():
            item = row.get("item") if isinstance(row.get("item"), dict) else {}
            verdict = row.get("verdict") if isinstance(row.get("verdict"), dict) else {}
            if not isinstance(verdict.get("isReceipt"), bool):
                continue
            found[message_id] = {
                **item,
                "id": message_id,
                "mailbox": mailbox,
                "receiptVerdict": verdict,
                FROM_LEDGER_KEY: True,
            }
        return found

    def known_messages(self, mailbox: str) -> KnownMessages:
        """What a mailbox reader asks before downloading: which of these ids it may skip."""

        return lambda message_ids: self.lookup(mailbox, message_ids)

    def attach_verdicts(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Put remembered verdicts on freshly read messages that lack one.

        A run that saved attachments read every message again; it still does
        not have to judge again the ones the ledger has already judged.
        """

        pending = [item for item in items if isinstance(item, dict) and not has_verdict(item)]
        if not pending:
            return items
        remembered: dict[tuple[str, str], dict[str, Any]] = {}
        for mailbox, group in _split_by_mailbox(pending).items():
            found = self.lookup(mailbox, [str(item.get("id") or "") for item in group])
            for message_id, entry in found.items():
                remembered[(mailbox, message_id)] = entry["receiptVerdict"]
        if not remembered:
            return items
        attached: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or has_verdict(item):
                attached.append(item)
                continue
            key = (str(item.get("mailbox") or "").strip(), str(item.get("id") or "").strip())
            verdict = remembered.get(key)
            attached.append({**item, "receiptVerdict": verdict, VERDICT_FROM_LEDGER_KEY: True} if verdict else item)
        return attached

    # -- writing -------------------------------------------------------------

    def remember(self, items: Iterable[dict[str, Any]]) -> int:
        """Write down every message that was read and judged this run.

        A message the ledger supplied, or whose verdict it supplied, is
        already there. A message the judge left without a verdict is not
        written: it has to be looked at again next time.
        """

        if self.user_id <= 0:
            return 0
        entries: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or item.get(FROM_LEDGER_KEY) or item.get(VERDICT_FROM_LEDGER_KEY):
                continue
            if not has_verdict(item):
                continue
            message_id = str(item.get("id") or "").strip()
            if not message_id:
                continue
            entries.append({
                "mailbox": str(item.get("mailbox") or "").strip(),
                "messageId": message_id,
                "judgeVersion": self.version,
                "verdict": dict(item["receiptVerdict"]),
                "item": ledger_item(item),
            })
        if not entries:
            return 0
        try:
            return int(self.database.save_receipt_mail_reads(user_id=self.user_id, entries=entries) or 0)
        except Exception as exc:  # noqa: BLE001 - failing to remember only costs a re-read next time
            print(f"Receipt ledger could not be written: {exc}", flush=True)
            return 0

    def dismissed(self) -> set[str]:
        """The message ids the owner removed from the receipts page."""

        if self.user_id <= 0:
            return set()
        try:
            return set(self.database.list_dismissed_receipt_messages(user_id=self.user_id))
        except Exception as exc:  # noqa: BLE001
            print(f"Receipt ledger dismissals could not be read: {exc}", flush=True)
            return set()


def judge_only_new(
    items: list[dict[str, Any]],
    *,
    judge: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Run the judge over the messages that still need a verdict, in place.

    The judged messages go back where they were, so the result keeps the
    order the mailbox returned - which is the order a capped month is cut in.
    """

    positions = [index for index, item in enumerate(items) if not has_verdict(item)]
    if not positions:
        return list(items)
    judged = judge([items[index] for index in positions])
    merged = list(items)
    for index, item in zip(positions, judged):
        merged[index] = item
    return merged


def cap_fresh_items(items: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Hold a mailbox's freshly downloaded messages to a ceiling.

    Messages the ledger supplied cost nothing and are all kept. Of the rest,
    the newest ``limit`` stay - the providers return newest first - and
    whether anything was cut is returned beside the list.
    """

    ceiling = max(0, int(limit))
    fresh_seen = 0
    kept: list[dict[str, Any]] = []
    capped = False
    for item in items:
        if isinstance(item, dict) and item.get(FROM_LEDGER_KEY):
            kept.append(item)
            continue
        if fresh_seen >= ceiling:
            capped = True
            continue
        fresh_seen += 1
        kept.append(item)
    return kept, capped


def count_reads(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """How a run's messages were come by, for the response and the logs."""

    counts = {"fromLedger": 0, "fetched": 0, "judged": 0}
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get(FROM_LEDGER_KEY):
            counts["fromLedger"] += 1
            continue
        counts["fetched"] += 1
        if has_verdict(item) and not item.get(VERDICT_FROM_LEDGER_KEY):
            counts["judged"] += 1
    return counts
