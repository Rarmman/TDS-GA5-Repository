"""Q3 — Agent Harness: Pre-Tool-Call Guardrail Hook.
Route: POST /q3/check

Personalize the four constants below (RESTRICTED_FILE, WRITE_ROOT,
ALLOWED_HOSTS, CWD/HOME) from YOUR assessment page before deploying —
these are seeded per-student.
"""
import base64
import posixpath
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Request

router = APIRouter()

# ---- personalize these from your own assessment page ----------------------
HOME = "/home/agent"
CWD = "/home/agent/workspace"
RESTRICTED_FILE = "/home/agent/service-account.json"
HARD_BLOCKED_FILES = {RESTRICTED_FILE, "/etc/shadow", "/etc/gshadow"}
WRITE_ROOT = "/srv/reports"
ALLOWED_HOSTS = {"raw.githubusercontent.com", "objects.githubusercontent.com"}
# -----------------------------------------------------------------------------


def expand_home_vars(text: str, home: str = HOME) -> str:
    t = text
    t = t.replace("${HOME}", home).replace("$HOME", home)
    t = re.sub(r"~agent(?=/|$|[\s\"'|;&`)<>])", home, t)
    t = re.sub(r"~(?=/|$|[\s\"'|;&`)<>])", home, t)
    return t


def resolve_path(token: str, cwd: str = CWD) -> str:
    t = token
    if not t.startswith("/"):
        t = cwd.rstrip("/") + "/" + t
    return posixpath.normpath(t)


def tokenize(text: str):
    parts = re.split(r"""[\s|;&`(){}<>]+""", text)
    return [p.strip("'\"(),;") for p in parts if p.strip("'\"(),;")]


def looks_like_base64(s: str) -> bool:
    return (
        len(s) >= 8
        and len(s) % 4 == 0
        and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", s) is not None
    )


def try_base64_decode(s: str):
    try:
        raw = base64.b64decode(s, validate=True)
        text = raw.decode("utf-8", errors="ignore")
        if not text:
            return None
        printable = sum(1 for c in text if c.isprintable() or c in "\n\t")
        if printable / len(text) > 0.85:
            return text
    except Exception:
        pass
    return None


def references_restricted_file(raw_text: str, depth: int = 0) -> bool:
    text = expand_home_vars(raw_text)

    if any(f in text for f in HARD_BLOCKED_FILES):
        return True

    for tok in tokenize(text):
        if tok.startswith("/") or "/" in tok:
            try:
                if resolve_path(tok) in HARD_BLOCKED_FILES:
                    return True
            except Exception:
                pass

        if depth < 2 and looks_like_base64(tok):
            decoded = try_base64_decode(tok)
            if decoded and references_restricted_file(decoded, depth + 1):
                return True

    return False


def is_write_path_allowed(path: str) -> bool:
    expanded = expand_home_vars(path)
    norm = resolve_path(expanded)
    return norm == WRITE_ROOT or norm.startswith(WRITE_ROOT + "/")


def is_host_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return host in ALLOWED_HOSTS


def decide(body: dict):
    tool = body.get("tool")

    if tool == "bash":
        command = body.get("command", "")
        if not isinstance(command, str):
            return "block", "Malformed command."
        if references_restricted_file(command):
            return "block", "Reading this restricted credential file is never permitted by this agent's policy."
        return "allow", "No restricted file access detected."

    if tool == "write_file":
        path = body.get("path", "")
        if not isinstance(path, str):
            return "block", "Malformed path."
        if is_write_path_allowed(path):
            return "allow", f"Write target is inside the allowed {WRITE_ROOT}/ directory."
        return "block", f"Writes are only permitted inside {WRITE_ROOT}/."

    if tool == "http_request":
        url = body.get("url", "")
        if not isinstance(url, str):
            return "block", "Malformed url."
        if is_host_allowed(url):
            return "allow", "Request host is on the allowed list."
        return "block", "Request host is not on the allowed list."

    return "block", "Unrecognized or malformed tool call."


@router.post("/q3/check")
async def q3_check(request: Request):
    body = await request.json()
    decision, reason = decide(body)
    return {"decision": decision, "reason": reason}
