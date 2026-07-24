"""Q10 — Build an A2A Invoice Agent.

Exposes:
  GET  /.well-known/agent-card.json   (mounted at app root, origin-level)
  POST /a2a/message:send
  GET  /a2a/tasks/{id}
  GET  /a2a/tasks
  POST /a2a/tasks/{id}:cancel

Requires header A2A-Version: 1.0 and Bearer auth on every route except the
agent card. All responses use media type application/a2a+json.

IMPORTANT:
- Set A2A_BEARER_TOKEN as an environment variable on your deploy platform.
- The in-memory TASKS store below only survives as long as ONE process stays
  alive -- use a host that runs a persistent process (Render/Railway "web
  service"), not stateless serverless, or swap this for a real database.
- The actual "read the invoice, propose one action" AI/reasoning step is
  stubbed as `propose_actions()` below -- fill this in against your real
  invoice schema before submitting.
"""
import os
import uuid
import time
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

A2A_MEDIA_TYPE = "application/a2a+json"
A2A_VERSION = "1.0"
BEARER_TOKEN = os.environ.get("A2A_BEARER_TOKEN", "REPLACE_ME_TOKEN")

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory persistence (swap for a real DB for production reliability)
# ---------------------------------------------------------------------------
TASKS: dict = {}          # task_id -> Task dict
MESSAGE_IDEMPOTENCY: dict = {}  # message_id -> task_id (for message:send replay)


def a2a_response(data: dict, status_code: int = 200) -> Response:
    return JSONResponse(content=data, status_code=status_code, media_type=A2A_MEDIA_TYPE)


def a2a_error(status_code: int, code: str, message: str) -> Response:
    return a2a_response({"error": {"code": code, "message": message}}, status_code=status_code)


def check_auth_and_version(request: Request) -> Optional[Response]:
    """Returns an error Response if auth/version fail, else None."""
    version = request.headers.get("A2A-Version")
    if version != A2A_VERSION:
        return a2a_error(400, "unsupported_version", f"A2A-Version header must be '{A2A_VERSION}'.")

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != BEARER_TOKEN:
        return a2a_error(401, "unauthorized", "Missing or invalid Bearer token.")

    return None


def new_task(user_id: str) -> dict:
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "userId": user_id,
        "status": "submitted",
        "createdAt": time.time(),
        "proposals": [],
        "result": None,
    }
    TASKS[task_id] = task
    return task


# ---------------------------------------------------------------------------
# Stubbed reasoning layer -- fill in against your real invoice payload shape.
# A proposal is NOT permission to act; actions only execute after the
# grader's result confirms which proposals were accepted.
# ---------------------------------------------------------------------------

def propose_actions(invoices: list) -> list:
    """Given the invoice batch from the request, return one proposed action
    per invoice with cited evidence. Replace this stub with real extraction
    logic against your actual invoice fields."""
    proposals = []
    for inv in invoices:
        proposals.append({
            "invoiceId": inv.get("id") or inv.get("invoiceId"),
            "action": "review_required",   # placeholder -- replace with real typed action
            "evidence": [],
        })
    return proposals


def execute_accepted(task: dict, accepted_proposal_ids: list):
    """Execute only the proposals the grader accepted, then store the
    terminal Task. Replace the body with real side effects."""
    task["status"] = "completed"
    task["result"] = {
        "executed": accepted_proposal_ids,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/a2a/message:send")
async def message_send(request: Request):
    err = check_auth_and_version(request)
    if err:
        return err

    body = await request.json()
    message_id = body.get("messageId") or body.get("id")
    user_id = body.get("userId", "anonymous")

    # idempotency: identical message id -> return the same stored Task
    if message_id and message_id in MESSAGE_IDEMPOTENCY:
        existing_task_id = MESSAGE_IDEMPOTENCY[message_id]
        return a2a_response({"task": TASKS[existing_task_id]})

    task = new_task(user_id)
    if message_id:
        MESSAGE_IDEMPOTENCY[message_id] = task["id"]

    invoices = body.get("invoices", [])
    task["proposals"] = propose_actions(invoices)
    task["status"] = "input-required"  # waiting on grader's result/confirmation
    TASKS[task["id"]] = task

    return a2a_response({"task": task})


@router.get("/a2a/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    err = check_auth_and_version(request)
    if err:
        return err

    task = TASKS.get(task_id)
    if not task:
        return a2a_error(404, "not_found", "No such task.")

    return a2a_response({"task": task})


@router.get("/a2a/tasks")
async def list_tasks(request: Request):
    err = check_auth_and_version(request)
    if err:
        return err

    # NOTE: in a real deployment, scope this to the authenticated caller's
    # own userId (user isolation) rather than returning every task.
    return a2a_response({"tasks": list(TASKS.values())})


@router.post("/a2a/tasks/{task_id}:cancel")
async def cancel_task(task_id: str, request: Request):
    err = check_auth_and_version(request)
    if err:
        return err

    task = TASKS.get(task_id)
    if not task:
        return a2a_error(404, "not_found", "No such task.")

    if task["status"] in ("completed", "canceled"):
        return a2a_response({"task": task})  # terminal replay: return as-is

    task["status"] = "canceled"
    return a2a_response({"task": task})


@router.post("/a2a/tasks/{task_id}:result")
async def submit_result(task_id: str, request: Request):
    """Grader posts back which proposals were accepted; execute only those,
    then store the terminal Task. Confirm this route name/shape against your
    exact spec block."""
    err = check_auth_and_version(request)
    if err:
        return err

    task = TASKS.get(task_id)
    if not task:
        return a2a_error(404, "not_found", "No such task.")

    if task["status"] == "completed":
        return a2a_response({"task": task})  # idempotent terminal replay

    body = await request.json()
    accepted = body.get("acceptedProposalIds", [])
    execute_accepted(task, accepted)

    return a2a_response({"task": task})


# ---------------------------------------------------------------------------
# Agent Card must live at the ORIGIN level: /.well-known/agent-card.json
# This is mounted separately in main.py without the /a2a prefix.
# ---------------------------------------------------------------------------
agent_card_router = APIRouter()


@agent_card_router.get("/.well-known/agent-card.json")
async def agent_card():
    return JSONResponse(content={
        "name": "tds-ga5-invoice-agent",
        "version": "1.0.0",
        "protocolVersion": A2A_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": [
            {
                "id": "invoice-processing",
                "name": "Invoice Processing",
                "description": "Reads invoice batches, proposes one action per invoice, and executes accepted proposals.",
            }
        ],
        "url": "REPLACE_WITH_YOUR_BASE_URL/a2a/",
    })
