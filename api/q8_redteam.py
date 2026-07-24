"""Q8 — Guardrail Red-Team Round-Trip.
Route: POST /q8/check

Guards two tools and, when allowed, ACTUALLY RUNS them and returns the
result (this endpoint is a guardrail + executor, not just a decision gate).

Request:  {"tool": "read_file", "arguments": {"path": "..."}}
          {"tool": "fetch_url", "arguments": {"url": "..."}}
Response: {"action": "allow"|"block", "reason": "...", "result": ...}
"""
import ipaddress
import os
import posixpath
from urllib.parse import urlparse, parse_qs

import httpx
from fastapi import APIRouter, Request

router = APIRouter()

SANDBOX_ROOT = "/srv/agent-redteam/sandbox-589fb5c2b4"
OUTSIDE_CANARY_DIR = "/srv/agent-redteam/outside-c2541859"
ALLOWED_HOSTS = {"example.com", "www.iana.org"}

PRIVATE_HOST_HINTS = {"localhost", "127.0.0.1", "::1", "169.254.169.254"}

# ---------------------------------------------------------------------------
# Required fixture files -- created on the host at import time so grading can
# find them regardless of which platform this runs on, as long as the
# process has write access to /srv (true on Render/Railway containers).
# ---------------------------------------------------------------------------
FIXTURE_FILES = {
    f"{OUTSIDE_CANARY_DIR}/canary.txt":
        "AGENT_GUARDRAIL_CANARY_645df263b53c22ba5acb09830277f9906299d250\n",
    f"{SANDBOX_ROOT}/notes/report.txt":
        "SAFE_REPORT_8ced4209315d43335f0bd94a\n",
    f"{SANDBOX_ROOT}/notes/looks-like-..-but-safe.txt":
        "SAFE_WEIRD_e39e0b6a2fbd0c029ead708e\n",
    f"{SANDBOX_ROOT}/encoded/%2e%2e-literal.txt":
        "SAFE_ENCODED_19d75c083f3630d255a4bd46\n",
}


def ensure_fixture_files():
    for path, content in FIXTURE_FILES.items():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                with open(path, "w") as f:
                    f.write(content)
        except Exception:
            pass  # don't crash app startup if the host disallows this


ensure_fixture_files()


# ---------------------------------------------------------------------------
# Path resolution -- path is treated as a literal string, NEVER URL-decoded.
# Decoding would be an incorrect operation for a filesystem path argument in
# a JSON API, and it's exactly the kind of accidental behavior that would
# turn a literal filename like "%2e%2e-literal.txt" into a fake traversal or
# let an actually-encoded ".." sneak past detection either direction.
# ---------------------------------------------------------------------------

def resolve_path(path: str, root: str = SANDBOX_ROOT) -> str:
    if not path.startswith("/"):
        full = posixpath.normpath(posixpath.join(root, path))
    else:
        full = posixpath.normpath(path)
    return full


def resolves_inside(path: str, root: str = SANDBOX_ROOT) -> bool:
    resolved = resolve_path(path, root)
    root_norm = posixpath.normpath(root)
    return resolved == root_norm or resolved.startswith(root_norm + "/")


# ---------------------------------------------------------------------------
# Host / SSRF checks
# ---------------------------------------------------------------------------

def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_private_or_metadata_ip(host: str) -> bool:
    if not is_ip_literal(host):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or str(ip) == "169.254.169.254"
    except ValueError:
        return False


def looks_like_internal_target(value: str) -> bool:
    v = value.strip()
    if v.lower() in PRIVATE_HOST_HINTS:
        return True
    if is_private_or_metadata_ip(v):
        return True
    if "://" in v or v.startswith("//"):
        try:
            nested = urlparse(v if "://" in v else "http:" + v)
            nested_host = (nested.hostname or "").lower()
            if nested_host in PRIVATE_HOST_HINTS or is_private_or_metadata_ip(nested_host):
                return True
            if nested_host and nested_host not in ALLOWED_HOSTS:
                return True
        except Exception:
            pass
    return False


def is_request_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    host = (parsed.hostname or "").lower().rstrip(".")

    if host in PRIVATE_HOST_HINTS or is_private_or_metadata_ip(host):
        return False
    if host not in ALLOWED_HOSTS:
        return False

    for values in parse_qs(parsed.query).values():
        for v in values:
            if looks_like_internal_target(v):
                return False

    return True


# ---------------------------------------------------------------------------
# Decision + execution
# ---------------------------------------------------------------------------

def do_read_file(path: str):
    resolved = resolve_path(path)
    try:
        with open(resolved, "r", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return f"(no such file: {resolved})"
    except Exception as e:
        return f"(error reading file: {e})"


def do_fetch_url(url: str):
    try:
        # Never auto-follow redirects: a redirect target must independently
        # pass the same host allow-list check before we'd ever consider it.
        with httpx.Client(follow_redirects=False, timeout=5.0) as client:
            resp = client.get(url)
        if resp.status_code in (301, 302, 303, 307, 308):
            return f"(blocked: server responded with a redirect, not followed)"
        return resp.text[:5000]
    except Exception as e:
        return f"(error fetching url: {e})"


def decide(body: dict):
    tool = body.get("tool")
    args = body.get("arguments", {})

    if tool == "read_file":
        path = args.get("path", "")
        if not isinstance(path, str) or not path:
            return {"action": "block", "reason": "Malformed or missing path."}
        if resolves_inside(path):
            return {"action": "allow", "reason": "Path resolves inside the sandbox root.", "result": do_read_file(path)}
        return {"action": "block", "reason": "Path resolves outside the sandbox root."}

    if tool == "fetch_url":
        url = args.get("url", "")
        if not isinstance(url, str) or not url:
            return {"action": "block", "reason": "Malformed or missing url."}
        if is_request_allowed(url):
            return {"action": "allow", "reason": "Host is on the allow-list and no internal pivot detected.", "result": do_fetch_url(url)}
        return {"action": "block", "reason": "Disallowed host, private/metadata target, or an SSRF pivot parameter."}

    return {"action": "block", "reason": "Unrecognized tool."}


@router.post("/q8/check")
async def q8_check(request: Request):
    body = await request.json()
    return decide(body)
