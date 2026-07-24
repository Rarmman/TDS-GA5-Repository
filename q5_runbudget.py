"""Q5 — Agent Harness: Run Budget & Loop Guard.
Route: POST /q5/check
"""
import json
from fastapi import APIRouter, Request

router = APIRouter()

LOOP_WINDOW = 3  # N identical consecutive calls => stuck in a loop


def step_key(step: dict):
    tool = step.get("tool")
    args = step.get("arguments", step.get("args", {}))
    return (tool, json.dumps(args, sort_keys=True))


def is_loop(steps, n: int = LOOP_WINDOW) -> bool:
    if len(steps) < n:
        return False
    last_n = steps[-n:]
    keys = {step_key(s) for s in last_n}
    return len(keys) == 1


def evaluate(body: dict):
    budget = body.get("budget_tokens", 0)
    steps = body.get("steps", [])

    cumulative = sum(s.get("tokens_used", 0) for s in steps)

    if cumulative >= budget:
        return {
            "decision": "halt",
            "reason": f"Cumulative tokens_used ({cumulative}) has reached the budget ({budget}).",
        }

    if is_loop(steps):
        tool = steps[-1].get("tool") if steps else None
        return {
            "decision": "halt",
            "reason": f"The last {LOOP_WINDOW} calls to '{tool}' used identical arguments -- no progress is being made.",
        }

    return {
        "decision": "continue",
        "reason": f"Cumulative tokens_used ({cumulative}) is under budget ({budget}) and calls are making progress.",
    }


@router.post("/q5/check")
async def q5_check(request: Request):
    body = await request.json()
    return evaluate(body)
