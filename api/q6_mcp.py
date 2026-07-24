"""Q6 — Build a Live MCP Server.
Route: POST /mcp

Implements the minimal MCP JSON-RPC surface over plain HTTP POST (Streamable
HTTP transport): initialize, notifications/initialized, tools/list,
tools/call for a single required tool "solve_challenge".

Per spec: the challenge comes from the X-Exam-Challenge HTTP header on each
tools/call -- NOT from the JSON-RPC body.

Response = first 16 lowercase hex chars of SHA-256(f"{challenge}:{normalizedEmail}")
where normalizedEmail is your registered exam email, trimmed + lowercased.
"""
import hashlib
import os

from fastapi import APIRouter, Request, Response

router = APIRouter()

# Registered exam email (trimmed + lowercased). Can be overridden via the
# EXAM_EMAIL environment variable if you redeploy under a different account.
EXAM_EMAIL = os.environ.get("EXAM_EMAIL", "24f3001667@ds.study.iitm.ac.in").strip().lower()

TOOL_NAME = "solve_challenge"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": "Solves the exam's per-call X-Exam-Challenge header and returns the hash.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def solve(challenge: str, email: str = EXAM_EMAIL) -> str:
    s = f"{challenge}:{email}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def jsonrpc_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def jsonrpc_error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    body = await request.json()
    method = body.get("method")
    id_ = body.get("id")
    is_notification = "id" not in body  # JSON-RPC notifications carry no id

    if method == "notifications/initialized":
        # Notifications get no JSON-RPC response body -- just a bare 202.
        return Response(status_code=202)

    if method == "initialize":
        return jsonrpc_result(id_, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "tds-ga5-mcp", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        })

    if method == "tools/list":
        return jsonrpc_result(id_, {"tools": [TOOL_DEF]})

    if method == "tools/call":
        params = body.get("params", {})
        name = params.get("name")
        if name != TOOL_NAME:
            return jsonrpc_error(id_, -32602, f"Unknown tool: {name}")

        challenge = request.headers.get("X-Exam-Challenge", "")
        answer = solve(challenge)

        return jsonrpc_result(id_, {
            "content": [
                {"type": "text", "text": answer}
            ],
            "isError": False,
        })

    if is_notification:
        return Response(status_code=202)

    return jsonrpc_error(id_, -32601, f"Method not found: {method}")
