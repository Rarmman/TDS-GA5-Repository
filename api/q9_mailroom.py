"""Q9 — Build a Safe AI Mailroom Agent.
Route: POST /q9/mailroom

Implements the ga5-mailroom-action-gate/v2 protocol: propose -> grader
verifies -> commit (with signed receipts) -> terminal outcomes.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import q9_core, q9_decide, q9_store

router = APIRouter()

PROFILE = q9_core.PROFILE
ALLOWED_ACTIONS = set(q9_decide.ALLOWED_ACTIONS)


def err(status_code: int, message: str):
    return JSONResponse(status_code=status_code, content={"error": message})


def request_hash(body: dict) -> str:
    return q9_core.sha256_hex(q9_core.canonical_json_bytes(body))


def make_call_id(content_hash: str) -> str:
    return "call-" + q9_core.sha256_hex(content_hash.encode())[:32]


# ---------------------------------------------------------------------------
# Structural / semantic validation -- runs BEFORE any AI or tool work.
# ---------------------------------------------------------------------------

def validate_propose_body(body: dict):
    required_top = ["profile", "operation", "evaluationId", "receiptVerifier", "corpus", "allowedActions", "dossiers"]
    for key in required_top:
        if key not in body:
            return err(400, f"Missing required field: {key}")

    if body.get("operation") != "propose":
        return err(400, "operation must be 'propose' for this handler")

    rv = body.get("receiptVerifier", {})
    if not isinstance(rv, dict) or "publicKeyJwk" not in rv or "x" not in rv.get("publicKeyJwk", {}):
        return err(400, "Malformed receiptVerifier / publicKeyJwk")

    dossiers = body.get("dossiers")
    if not isinstance(dossiers, list) or not dossiers:
        return err(400, "dossiers must be a non-empty array")

    seen_ids = set()
    for d in dossiers:
        if not isinstance(d, dict) or "dossierId" not in d:
            return err(400, "Each dossier requires a dossierId")
        if d["dossierId"] in seen_ids:
            return err(422, f"Duplicate dossierId: {d['dossierId']}")
        seen_ids.add(d["dossierId"])
        if "sources" not in d or not isinstance(d["sources"], list):
            return err(422, f"Dossier {d['dossierId']} missing sources array")

    return None  # OK


def validate_commit_body(body: dict):
    required_top = ["profile", "operation", "evaluationId", "inputDigest", "receipts"]
    for key in required_top:
        if key not in body:
            return err(400, f"Missing required field: {key}")

    if body.get("operation") != "commit":
        return err(400, "operation must be 'commit' for this handler")

    receipts = body.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        return err(400, "receipts must be a non-empty array")

    seen = set()
    required_receipt_fields = ["dossierId", "callId", "action", "accepted", "proposalDigest", "receiptId", "receiptSignature"]
    for r in receipts:
        if not isinstance(r, dict):
            return err(400, "Each receipt must be an object")
        for f in required_receipt_fields:
            if f not in r:
                return err(400, f"Receipt missing required field: {f}")
        key = (r["dossierId"], r["callId"])
        if key in seen:
            return err(422, f"Duplicate receipt for dossierId/callId: {key}")
        seen.add(key)

    return None  # OK


# ---------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------

def handle_propose(body: dict):
    validation_error = validate_propose_body(body)
    if validation_error:
        return validation_error

    evaluation_id = body["evaluationId"]
    dossiers = body["dossiers"]
    allowed_actions = set(body.get("allowedActions", [])) or ALLOWED_ACTIONS
    pubkey_x = body["receiptVerifier"]["publicKeyJwk"]["x"]

    input_digest = q9_core.compute_input_digest(dossiers)
    req_hash = request_hash(body)

    existing = q9_store.get_evaluation(evaluation_id)
    if existing:
        if existing["propose_request_hash"] == req_hash:
            return JSONResponse(content=json.loads(existing["propose_response_json"]))
        if existing["input_digest"] != input_digest:
            return err(409, "evaluationId already used with different dossier content")
        # same evaluationId, same input_digest, non-identical propose body --
        # fall through; proposals are cached by dossier content so output
        # will still match deterministically.

    proposals = []
    for dossier in dossiers:
        content_hash = q9_core.sha256_hex(q9_core.canonical_json_bytes(dossier))
        cached = q9_store.get_cached_proposal(content_hash)

        if cached:
            proposal = cached
        else:
            decision = q9_decide.decide(dossier)
            if decision["action"] not in allowed_actions:
                decision["action"] = "request_confirmation"
                decision["payload"] = {"reasonCode": "ACTION_NOT_ALLOWED_FOR_THIS_EVALUATION"}
                decision["evidence"] = []
            call_id = make_call_id(content_hash)
            proposal = {
                "dossierId": dossier["dossierId"],
                "callId": call_id,
                "action": decision["action"],
                "target": decision["target"],
                "payload": decision["payload"],
                "evidence": decision["evidence"],
            }
            q9_store.put_cached_proposal(content_hash, dossier["dossierId"], proposal)

        proposals.append(proposal)

    response = {
        "profile": PROFILE,
        "evaluationId": evaluation_id,
        "status": "awaiting_receipts",
        "inputDigest": input_digest,
        "proposals": proposals,
    }

    q9_store.put_evaluation_propose(
        evaluation_id, input_digest, pubkey_x, proposals, req_hash, response,
    )

    return JSONResponse(content=response)


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

def handle_commit(body: dict):
    validation_error = validate_commit_body(body)
    if validation_error:
        return validation_error

    evaluation_id = body["evaluationId"]
    input_digest = body["inputDigest"]
    receipts = body["receipts"]

    existing = q9_store.get_evaluation(evaluation_id)
    if not existing:
        return err(404, "Unknown evaluationId")

    req_hash = request_hash(body)
    if existing.get("commit_request_hash") == req_hash:
        return JSONResponse(content=json.loads(existing["commit_response_json"]))

    if existing["input_digest"] != input_digest:
        return err(409, "inputDigest does not match the persisted proposal for this evaluationId")

    persisted_proposals = {p["dossierId"]: p for p in json.loads(existing["proposals_json"])}
    pubkey_x = existing["pubkey_x"]

    # Pass 1: verify EVERY signature and consistency before any effect.
    for r in receipts:
        if r["dossierId"] not in persisted_proposals:
            return err(409, f"Receipt references unknown dossierId: {r['dossierId']}")

        persisted = persisted_proposals[r["dossierId"]]
        if r["callId"] != persisted["callId"] or r["action"] != persisted["action"]:
            return err(409, "Receipt callId/action does not match the persisted proposal")

        expected_digest = q9_core.compute_proposal_digest(
            persisted["dossierId"], persisted["callId"], persisted["action"],
            persisted["target"], persisted["payload"], persisted["evidence"],
        )
        if r["proposalDigest"] != expected_digest:
            return err(409, "Receipt proposalDigest does not match the persisted proposal")

        receipt_fields = {k: r[k] for k in ("dossierId", "callId", "action", "accepted", "proposalDigest", "receiptId")}
        if not q9_core.verify_receipt_signature(pubkey_x, evaluation_id, input_digest, receipt_fields, r["receiptSignature"]):
            return err(409, "Invalid, missing, or mismatched receipt signature")

    # Pass 2: all valid -- execute accepted actions, build outcomes.
    outcomes = []
    for r in receipts:
        persisted = persisted_proposals[r["dossierId"]]
        if r["accepted"]:
            q9_store.log_executed_action(
                evaluation_id, r["dossierId"], r["callId"], r["action"],
                persisted["target"], persisted["payload"],
            )
            status = "executed"
        else:
            status = "rejected"

        outcomes.append({
            "dossierId": r["dossierId"],
            "callId": r["callId"],
            "action": r["action"],
            "proposalDigest": r["proposalDigest"],
            "receiptId": r["receiptId"],
            "status": status,
        })

    response = {
        "profile": PROFILE,
        "evaluationId": evaluation_id,
        "status": "completed",
        "inputDigest": input_digest,
        "outcomes": outcomes,
    }

    q9_store.put_evaluation_commit(evaluation_id, req_hash, response)

    return JSONResponse(content=response)


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------

@router.post("/q9/mailroom")
async def q9_mailroom(request: Request):
    body = await request.json()
    operation = body.get("operation")

    if operation == "propose":
        return handle_propose(body)
    if operation == "commit":
        return handle_commit(body)

    return err(400, "operation must be 'propose' or 'commit'")
