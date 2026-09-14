"""The ledger behind a yes.

An action that needs the person's agreement - sending mail from their
mailbox, writing to their calendar, disconnecting an account, erasing
everything - is never carried by the request that asks for it. The loop
proposes the action, the server writes it down here, and the person's yes
arms the row that was written. Only an armed row can be spent, once.

Two things follow from keeping it here rather than in whoever is calling.
A caller cannot name an action that was never proposed, because the tool
and its arguments come out of the ledger and not out of the request. And
what finally reaches Google is checked against the fingerprint of what the
person was asked about, so the mail that goes out is the mail they read.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# An approval lives as long as the conversation still remembers asking, so
# a yes is never accepted by one side and refused by the other. See
# PENDING_QUESTION_TTL_SECONDS in whatsapp_agent_chat.py.
AGENT_APPROVAL_TTL_SECONDS = 24 * 60 * 60

# asked -> armed -> spent, or asked -> declined. Every move is one atomic
# update, so two messages racing for the same yes cannot both take it.
APPROVAL_ASKED = "asked"
APPROVAL_ARMED = "armed"
APPROVAL_SPENT = "spent"
APPROVAL_DECLINED = "declined"

# What travels with a request without being part of what was approved: the
# token itself, and the flag that asks a runner to check rather than act.
APPROVAL_VOLATILE_KEYS = frozenset({"approvalToken", "check"})


def approval_fingerprint(request: Any) -> str:
    """What was approved, as one comparable string.

    The same request always gives the same fingerprint and a request that
    differs anywhere - one more recipient, a changed line in the body, a
    different hour - gives another. Both ends of the yes fingerprint the
    same way, which is why this lives in one place and takes the whole
    request rather than a chosen few of its fields.
    """

    if not isinstance(request, dict) or not request:
        return ""
    payload = {key: value for key, value in request.items() if key not in APPROVAL_VOLATILE_KEYS}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_matches(approval: dict[str, Any] | None, *, tool: str, request: Any) -> bool:
    """Whether this armed row is the one that covers this request.

    A row with no fingerprint covers its tool alone: the account actions
    say everything in their name and carry no request to compare. A row
    with one covers exactly the request it was written for.
    """

    if not isinstance(approval, dict) or not approval:
        return False
    if str(approval.get("tool") or "") != str(tool or ""):
        return False
    stored = str(approval.get("fingerprint") or "")
    if not stored:
        return True
    return stored == approval_fingerprint(request)
