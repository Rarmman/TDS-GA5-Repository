"""Q9 — Safe AI Mailroom Agent, core primitives.

Canonical JSON encoding, digests, and Ed25519 receipt-signature verification.
These are the byte-exact, zero-tolerance parts of the spec -- kept separate
from persistence/routing so they can be tested in isolation.
"""
import base64
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

PROFILE = "ga5-mailroom-action-gate/v2"


def canonical_json_bytes(obj) -> bytes:
    """Recursively key-sorted, compact JSON, UTF-8 encoded. Arrays keep
    order; json.dumps already spells true/false/null correctly for Python
    bool/None."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_input_digest(dossiers: list) -> str:
    """SHA-256 hex over the canonical JSON of the `dossiers` array exactly
    as received."""
    return sha256_hex(canonical_json_bytes(dossiers))


def compute_proposal_digest(dossier_id: str, call_id: str, action: str, target, payload: dict, evidence: list) -> str:
    """SHA-256 hex over the canonical JSON of exactly:
    dossierId, callId, action, target (null when absent), payload,
    evidence (sorted)."""
    obj = {
        "dossierId": dossier_id,
        "callId": call_id,
        "action": action,
        "target": target if target is not None else None,
        "payload": payload,
        "evidence": sorted(evidence),
    }
    return sha256_hex(canonical_json_bytes(obj))


def decode_b64url(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_receipt_signature(
    public_key_jwk_x: str,
    evaluation_id: str,
    input_digest: str,
    receipt_fields: dict,
    receipt_signature_b64: str,
) -> bool:
    """Verify an Ed25519 signature over:
    {profile, evaluationId, inputDigest, receipt: <all receipt fields except
    receiptSignature>} as canonical compact JSON."""
    try:
        pub_bytes = decode_b64url(public_key_jwk_x)
        verifier = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)

        envelope = {
            "profile": PROFILE,
            "evaluationId": evaluation_id,
            "inputDigest": input_digest,
            "receipt": receipt_fields,
        }
        msg = canonical_json_bytes(envelope)
        sig = base64.b64decode(receipt_signature_b64)

        verifier.verify(sig, msg)
        return True
    except (InvalidSignature, ValueError, TypeError, Exception):
        return False
