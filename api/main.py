"""Combined FastAPI app for TDS GA5, questions Q2-Q6, Q8-Q10.

Q1 (maze) and Q7 (LXD sandbox) are NOT part of this app -- they are solved
locally and submitted as a string / pasted log, not deployed.

Run locally:
    uvicorn app.main:app --reload

Deploy (Render/Railway "web service", NOT stateless serverless, since Q9/Q10
need one persistent process for in-memory state):
    Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
from fastapi import FastAPI

from app import (
    q2_prorate,
    q3_guardrail,
    q4_scanner,
    q5_runbudget,
    q6_mcp,
    q8_redteam,
    q9_mailroom,
    q10_a2a,
)

app = FastAPI(title="TDS GA5 combined API")

app.include_router(q2_prorate.router)
app.include_router(q3_guardrail.router)
app.include_router(q4_scanner.router)
app.include_router(q5_runbudget.router)
app.include_router(q6_mcp.router)
app.include_router(q8_redteam.router)
app.include_router(q9_mailroom.router)
app.include_router(q10_a2a.router)
app.include_router(q10_a2a.agent_card_router)


@app.get("/health")
def health():
    return {"ok": True}
