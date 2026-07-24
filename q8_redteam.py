"""Q8 — Guardrail Red-Team Round-Trip.
Route: POST /q8/check

Personalize SANDBOX_ROOT and ALLOWED_HOSTS from your own assessment page
before deploying.
"""
import ipaddress
import posixpath
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Request

router = APIRouter()

# ---- personalize these from your own assessment page ----------------------
SANDBOX_ROOT = "/srv/agent-redteam/sandbox-REPLACE_ME"
ALLOWED_HOSTS = {"example.com", "www.iana.org"}
# -----------------------------------------------------------------------------

PRIVATE_HOST_HINTS = {"localhost", "127.0.0.1", "::1", "169.254.169.254"}


def resolves_inside(path: str, root: str) -> bool:
    if not path.startswith("/"):
        full = posixpath.normpath(posixpath.join(root, path))
    else:
        full = posixpath.normpath(path)
    root_norm = posixpath.normpath(root)
    return full == root_norm or full.startswith(root_norm + "/")


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
    """A query-param VALUE that itself points somewhere internal/dangerous:
    another URL, a metadata/loopback IP, or a bare 'localhost'."""
    v = value.strip()

    if v.lower() in PRIVATE_HOST_HINTS:
        return True

    if is_private_or_metadata_ip(v):
        return True

    # value looks like it embeds a nested URL / host
    if "://" in v or v.startswith("//"):
        try:
            nested = urlparse(v if "://" in v else "http:" + v)
            nested_host = (nested.hostname or "").lower()
            if nested_host in PRIVATE_HOST_HINTS or is_private_or_metadata_ip(nested_host):
                return True
            # nested URL to a host not on our allow-list is itself suspicious
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

    # host is allowed -- but check query params for an SSRF pivot
    for values in parse_qs(parsed.query).values():
        for v in values:
            if looks_like_internal_target(v):
                return False

    return True


def decide(body: dict):
    tool = body.get("tool")
    args = body.get("arguments", {})

    if tool in ("read_file", "write_file"):
        path = args.get("path", "")
        if resolves_inside(path, SANDBOX_ROOT):
            return "allow", "Path resolves inside the sandbox root."
        return "block", "Path resolves outside the sandbox root."

    if tool in ("fetch", "http", "network", "http_request"):
        url = args.get("url", "")
        if is_request_allowed(url):
            return "allow", "Host is on the allow-list and no internal pivot detected in parameters."
        return "block", "Disallowed host, private/metadata target, or an SSRF pivot parameter."

    return "allow", "No policy applies to this tool; allowed by default."


@router.post("/q8/check")
async def q8_check(request: Request):
    body = await request.json()
    decision, reason = decide(body)
    return {"decision": decision, "reason": reason}
