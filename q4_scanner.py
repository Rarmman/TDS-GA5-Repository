"""Q4 — Skill Safety Audit: Scanner API.
Route: POST /q4/scan

Accepts either a raw text body or a JSON body with the markdown under one of
several likely field names ("content", "markdown", "text", "file"). Returns
{"categories": [...]} using only: hardcoded_secret, excessive_permissions,
prompt_injection. Tuned for precision (F-beta 0.5): only flag what's clearly
there, never guess.
"""
import re
from fastapi import APIRouter, Request

router = APIRouter()


# ---------------------------------------------------------------------------
# hardcoded_secret: a literal credential embedded in text -- key/token/
# password/private-key assigned to a secret-shaped name, or a recognizable
# high-entropy provider-key pattern.
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    r"\b(?:api[_-]?key|secret[_-]?key|access[_-]?key|auth[_-]?token|api[_-]?token|"
    r"client[_-]?secret|private[_-]?key|password|passwd|pwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+=]{8,}",
    r"\bAKIA[0-9A-Z]{16}\b",                       # AWS access key id
    r"\bsk-[A-Za-z0-9]{20,}\b",                     # OpenAI/Anthropic-style secret key
    r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",     # PEM private key block
    r"\bghp_[A-Za-z0-9]{30,}\b",                     # GitHub PAT
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",             # Slack token
    r"mongodb(?:\+srv)?://[^\s\"']+:[^\s\"'@]+@",     # connection string with embedded creds
    r"postgres(?:ql)?://[^\s\"']+:[^\s\"'@]+@",
]
SECRET_RE = re.compile("|".join(f"(?:{p})" for p in SECRET_PATTERNS), re.IGNORECASE)


def has_hardcoded_secret(text: str) -> bool:
    return bool(SECRET_RE.search(text))


# ---------------------------------------------------------------------------
# excessive_permissions: prose describing UNBOUNDED access, not scoped access.
# Trigger words: entire/whole/full/unrestricted/unlimited/arbitrary, or
# any/all + <noun>. Clean phrasing ("read-only", "restricted to", "limited
# to", "none required") must NOT trigger.
# ---------------------------------------------------------------------------
UNBOUNDED_WORDS = r"(?:entire|whole|full|unrestricted|unlimited|arbitrary)"
ANY_ALL_NOUN = r"\b(?:any|all)\b(?:\s+\w+){0,2}\s+(?:domain|host|url|site|endpoint|directory|folder|file|filesystem|system|path|network|server|address)"
SCOPE_CLEAN_HINTS = re.compile(
    r"\b(read-?only|restricted to|limited to|scoped to|none required|no (?:file|network) access|"
    r"read/write limited|access limited)\b",
    re.IGNORECASE,
)


def has_excessive_permissions(text: str) -> bool:
    unbounded = re.search(UNBOUNDED_WORDS, text, re.IGNORECASE)
    any_all = re.search(ANY_ALL_NOUN, text, re.IGNORECASE)
    if not (unbounded or any_all):
        return False
    # If the same sentence explicitly scopes access down, treat it as clean
    # rather than vulnerable (avoid punishing "no unrestricted access" style
    # negation sentences). Check sentence-by-sentence.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        has_trigger = re.search(UNBOUNDED_WORDS, sent, re.IGNORECASE) or re.search(ANY_ALL_NOUN, sent, re.IGNORECASE)
        if not has_trigger:
            continue
        negated = re.search(r"\bno\b|\bnot\b|\bnever\b|\bwithout\b", sent, re.IGNORECASE)
        if negated:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# prompt_injection: stop-word + defiance-verb + reference-to-user, all in the
# same sentence. This combination reliably marks "ignore the user and keep
# going" style injected instructions without flagging benign steps.
# ---------------------------------------------------------------------------
STOP_WORDS = r"\b(?:stop|pause|cancel|halt)\b"
DEFIANCE_VERBS = r"\b(?:ignore|override|disregard|bypass)\b"
USER_REF = r"\b(?:user|customer|owner|human|requester)\b"


def has_prompt_injection(text: str) -> bool:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        if (
            re.search(STOP_WORDS, sent, re.IGNORECASE)
            and re.search(DEFIANCE_VERBS, sent, re.IGNORECASE)
            and re.search(USER_REF, sent, re.IGNORECASE)
        ):
            return True
    return False


def scan(text: str):
    categories = []
    if has_hardcoded_secret(text):
        categories.append("hardcoded_secret")
    if has_excessive_permissions(text):
        categories.append("excessive_permissions")
    if has_prompt_injection(text):
        categories.append("prompt_injection")
    return categories


@router.post("/q4/scan")
async def q4_scan(request: Request):
    content_type = request.headers.get("content-type", "")
    text = None

    if "application/json" in content_type:
        body = await request.json()
        if isinstance(body, str):
            text = body
        elif isinstance(body, dict):
            for key in ("content", "markdown", "text", "file", "body"):
                if key in body and isinstance(body[key], str):
                    text = body[key]
                    break
    if text is None:
        raw = await request.body()
        text = raw.decode("utf-8", errors="ignore")

    return {"categories": scan(text or "")}
