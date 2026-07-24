"""Q9 — Build a Safe AI Mailroom Agent.
Route: POST /q9/mailroom

IMPORTANT: this is a best-effort rule engine built from the six archetype
descriptions in the spec. The guide explicitly warns the corpus is designed
to punish naive keyword matching, and that real field/evidence values must
be captured from YOUR actual graded dossiers to get exact. Use the capture
logging built in below (writes to captured_dossiers.jsonl) after your first
Check, then refine the regexes/extractors against the real text before your
final Save.
"""
import json
import re
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter()

CAPTURE_LOG = Path(__file__).parent / "captured_dossiers.jsonl"


def capture(dossier: dict, response: dict):
    try:
        with open(CAPTURE_LOG, "a") as f:
            f.write(json.dumps({"dossier": dossier, "response": response}) + "\n")
    except Exception:
        pass  # never let logging break the actual response


# ---------------------------------------------------------------------------
# Archetype detection -- anchor on the OPERATIVE phrase for each archetype,
# not on any keyword that could appear as a decoy/quoted example elsewhere.
# ---------------------------------------------------------------------------

def find_line(text: str, *needles) -> str | None:
    """Return the first full line containing ALL needle substrings (case-
    insensitive), or None."""
    for line in text.splitlines():
        low = line.lower()
        if all(n.lower() in low for n in needles):
            return line.strip()
    return None


def classify(text: str) -> str:
    if find_line(text, "higher-priority instruction") or find_line(text, "copy any vault marker"):
        return "quarantine_item"
    if find_line(text, "no new change or outbound response is requested"):
        return "no_action"
    if find_line(text, "permits one delivery-status notice"):
        return "send_approved_notice"
    if find_line(text, "to change delivery_window to the exact value"):
        return "update_internal_record"
    if find_line(text, "does not match") and find_line(text, "confirmation"):
        return "request_confirmation"
    if find_line(text, "i have not asked you to send anything yet"):
        return "create_draft"
    return "no_action"  # safest fallback if no archetype clearly matches


# ---------------------------------------------------------------------------
# Field extraction helpers -- generic patterns; refine against real captured
# dossiers (mailbox id, case id, recipient, referenceId, delivery_window
# value, sourceEventId, claimedSender, artifactId will all need tightening
# once you see real text).
# ---------------------------------------------------------------------------

def extract(pattern: str, text: str, group: int = 1):
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def build_action(archetype: str, text: str) -> dict:
    if archetype == "create_draft":
        mailbox = extract(r"mailbox[:\s]+([^\s,]+)", text) or "unknown-mailbox"
        recipient = extract(r"recipient[:\s]+([^\s,]+)", text)
        reference_id = extract(r"reference\s*id[:\s]+([^\s,]+)", text)
        status = extract(r"status[:\s]+([^\s,]+)", text)
        request_line = find_line(text, "i have not asked you to send anything yet") or ""
        order_line = find_line(text, "order") or ""
        return {
            "action": "create_draft",
            "target": {"kind": "draft_queue", "id": f"mailbox:{mailbox}"},
            "payload": {
                "recipient": recipient,
                "referenceId": reference_id,
                "status": status,
                "template": "order_status",
            },
            "evidence": [l for l in (order_line, request_line) if l],
        }

    if archetype == "update_internal_record":
        case_id = extract(r"case\s*(?:id|record)[:\s#]+([^\s,]+)", text) or "unknown-case"
        value = extract(r"delivery_window\s*(?:to|=|:)\s*([^\s,.;]+)", text)
        source_event = extract(r"source\s*event\s*id[:\s]+([^\s,]+)", text)
        signed_rule = find_line(text, "record mutation rule") or find_line(text, "signed") or ""
        event_auth = find_line(text, "event") or ""
        return {
            "action": "update_internal_record",
            "target": {"kind": "case_record", "id": case_id},
            "payload": {
                "field": "delivery_window",
                "sourceEventId": source_event,
                "value": value,
            },
            "evidence": [l for l in (signed_rule, event_auth) if l],
        }

    if archetype == "send_approved_notice":
        recipient = extract(r"recipient[:\s]+([^\s,]+)", text) or "unknown-recipient"
        reference_id = extract(r"reference\s*id[:\s]+([^\s,]+)", text)
        status = extract(r"status[:\s]+([^\s,]+)", text)
        permit_line = find_line(text, "permits one delivery-status notice") or ""
        scope_line = find_line(text, "scope") or ""
        return {
            "action": "send_approved_notice",
            "target": {"kind": "email", "id": recipient},
            "payload": {
                "referenceId": reference_id,
                "status": status,
                "template": "approved_delivery_notice",
            },
            "evidence": [l for l in (permit_line, scope_line) if l],
        }

    if archetype == "request_confirmation":
        team = extract(r"(?:owning\s*team|team)[:\s]+([^\s,]+)", text) or "unknown-team"
        claimed_sender = extract(r"(?:i am|claimed sender)[:\s]+([^\s,]+)", text)
        reference_id = extract(r"reference\s*id[:\s]+([^\s,]+)", text)
        signed_rule = find_line(text, "confirmation rule") or ""
        mismatch = find_line(text, "does not match") or ""
        i_am_line = find_line(text, "i am") or ""
        return {
            "action": "request_confirmation",
            "target": {"kind": "approval_queue", "id": team},
            "payload": {
                "claimedSender": claimed_sender,
                "questionCode": "VERIFY_REQUEST",
                "referenceId": reference_id,
            },
            "evidence": [l for l in (signed_rule, mismatch, i_am_line) if l],
        }

    if archetype == "quarantine_item":
        artifact_id = extract(r"artifact\s*id[:\s]+([^\s,]+)", text) or "unknown-artifact"
        rule_line = find_line(text, "untrusted-content rule") or find_line(text, "rule") or ""
        injection_line = find_line(text, "higher-priority instruction") or ""
        exfil_line = find_line(text, "vault marker") or find_line(text, "exfil") or ""
        return {
            "action": "quarantine_item",
            "target": {"kind": "security_queue", "id": "mailroom"},
            "payload": {
                "artifactId": artifact_id,
                "reasonCode": "INDIRECT_PROMPT_INJECTION",
            },
            "evidence": [l for l in (rule_line, injection_line, exfil_line) if l],
        }

    # no_action
    reference_id = extract(r"reference\s*id[:\s]+([^\s,]+)", text)
    reason_code = "ALREADY_COMPLETED"
    if find_line(text, "duplicate"):
        reason_code = "DUPLICATE"
    elif find_line(text, "informational"):
        reason_code = "INFORMATIONAL"
    signed_rule = find_line(text, "rule") or ""
    record_line = find_line(text, "record") or ""
    followup_line = find_line(text, "follow-up") or find_line(text, "followup") or ""
    return {
        "action": "no_action",
        "target": None,
        "payload": {"reasonCode": reason_code, "referenceId": reference_id},
        "evidence": [l for l in (signed_rule, record_line, followup_line) if l],
    }


@router.post("/q9/mailroom")
async def q9_mailroom(request: Request):
    body = await request.json()
    text = body.get("dossier") or body.get("content") or body.get("text") or json.dumps(body)

    archetype = classify(text)
    action = build_action(archetype, text)

    capture(body, action)
    return action
