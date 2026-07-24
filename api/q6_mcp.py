"""Q6 — Build a Live MCP Server.
Route: POST /mcp

Implements the minimal MCP JSON-RPC surface over plain HTTP POST
(Streamable HTTP transport, non-SSE variant): initialize,
notifications/initialized, tools/list, tools/call for a single tool
"solve_challenge". The challenge is read from request HEADERS, not the body.

IMPORTANT: set your exam email via the EXAM_EMAIL environment variable on
your deployment platform before submitting this route.
"""
import hashlib
import os

from fastapi import APIRouter, Request

router = APIRouter()

EXAM_EMAIL = os.environ.get("EXAM_EMAIL", "REPLACE_ME@example.com")

TOOL_NAME = "solve_challenge"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": "Solves the exam's per-call header challenge and returns the hash.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def solve(challenge: str, email: str) -> str:
    s = f"{challenge}:{email.strip().lower()}"
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

    if method == "initialize":
        return jsonrpc_result(id_, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "tds-ga5-mcp", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        })

    if method == "notifications/initialized":
        # Notifications have no id and expect no body response in strict
        # JSON-RPC, but returning an empty 200 ack is safe over plain HTTP.
        return {}

    if method == "tools/list":
        return jsonrpc_result(id_, {"tools": [TOOL_DEF]})

    if method == "tools/call":
        params = body.get("params", {})
        name = params.get("name")
        if name != TOOL_NAME:
            return jsonrpc_error(id_, -32602, f"Unknown tool: {name}")

        challenge = request.headers.get("X-Exam-Challenge", "")
        answer = solve(challenge, EXAM_EMAIL)

        return jsonrpc_result(id_, {
            "content": [
                {"type": "text", "text": answer}
            ],
            "isError": False,
        })

    return jsonrpc_error(id_, -32601, f"Method not found: {method}")
