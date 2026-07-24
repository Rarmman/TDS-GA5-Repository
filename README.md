# TDS GA5 — Combined API (Q2–Q6, Q8–Q10)

One FastAPI app, one deployment, many routes. **Q1 (maze) and Q7 (LXD
sandbox) are NOT here** — they're solved locally and submitted as a raw
string / pasted log, with no deployment involved.

## Routes

| Question | Method | Path | File |
|---|---|---|---|
| Q2 — Proration | POST | `/prorate` | `app/q2_prorate.py` |
| Q3 — Guardrail hook | POST | `/q3/check` | `app/q3_guardrail.py` |
| Q4 — Skill scanner | POST | `/q4/scan` | `app/q4_scanner.py` |
| Q5 — Run budget / loop guard | POST | `/q5/check` | `app/q5_runbudget.py` |
| Q6 — MCP server | POST | `/mcp` | `app/q6_mcp.py` |
| Q8 — Redteam guardrail | POST | `/q8/check` | `app/q8_redteam.py` |
| Q9 — Mailroom agent | POST | `/q9/mailroom` | `app/q9_mailroom.py` |
| Q10 — A2A invoice agent | POST/GET | `/a2a/...`, `/.well-known/agent-card.json` | `app/q10_a2a.py` |
| health check | GET | `/health` | `app/main.py` |

All routes have been unit-tested against the router logic directly (see the
test snippets used to build this — every module's core function was
exercised with edge cases before being wired in).

## Before you deploy: personalize these

Several files hardcode placeholder values that **must be replaced with your
own assessment page's specific values** before submitting:

- `app/q3_guardrail.py` — `RESTRICTED_FILE`, `WRITE_ROOT`, `ALLOWED_HOSTS`, `HOME`, `CWD`
- `app/q8_redteam.py` — `SANDBOX_ROOT`, `ALLOWED_HOSTS`
- `app/q6_mcp.py` — reads `EXAM_EMAIL` from an environment variable (set this on your host, don't hardcode it in the file)
- `app/q10_a2a.py` — reads `A2A_BEARER_TOKEN` from an environment variable; also replace the `url` field in the agent card with your real deployed base URL once you know it
- `app/q9_mailroom.py` — the field-extraction regexes are a best-effort starting point built from the six archetype *descriptions* only. **Capture your real graded dossiers** (the module logs every request/response pair to `app/captured_dossiers.jsonl` automatically) and tighten the regexes against real text before your final submission.
- `app/q10_a2a.py` — `propose_actions()` and `execute_accepted()` are stubs. Fill in real invoice-reading logic once you see your actual invoice payload shape.

## Why Render/Railway, not Vercel, for this combined app

Q9 needs nothing persistent, but **Q10 needs Tasks to survive across
multiple requests** (create → get → cancel/result), and Q6's MCP handshake
is easiest as one continuously-running process. Stateless serverless
platforms (Vercel-style) don't guarantee your in-memory Python dict survives
between invocations. Use a host that runs one persistent process:

### Deploy to Render (recommended)
1. Push this repo to GitHub.
2. Go to https://dashboard.render.com/blueprints, connect the repo — it'll
   pick up `render.yaml` automatically.
3. Set the `EXAM_EMAIL` and `A2A_BEARER_TOKEN` environment variables in the
   Render dashboard (marked `sync: false` so they're not committed to git).
4. Deploy. You'll get a URL like `https://tds-ga5-api.onrender.com`.
5. Free tier sleeps after inactivity — hit `/health` a minute or two before
   the grader runs, to warm it up.

### Or Railway
1. https://railway.app/new → deploy from GitHub repo.
2. Add the same two environment variables under the service's Variables tab.
3. Railway auto-detects the `Procfile` start command.

## Submitting

Once deployed, your base URL (e.g. `https://tds-ga5-api.onrender.com`) plus
each path above is what goes into each question's URL field:

- Q2: `https://tds-ga5-api.onrender.com/prorate`
- Q3: `https://tds-ga5-api.onrender.com/q3/check`
- Q4: `https://tds-ga5-api.onrender.com/q4/scan`
- Q5: `https://tds-ga5-api.onrender.com/q5/check`
- Q6: `https://tds-ga5-api.onrender.com/mcp`
- Q8: `https://tds-ga5-api.onrender.com/q8/check`
- Q9: `https://tds-ga5-api.onrender.com/q9/mailroom`
- Q10: `https://tds-ga5-api.onrender.com` (agent discovers `/a2a/` routes via the agent card)

## Run locally

```bash
pip install -r requirements.txt
export EXAM_EMAIL="you@example.com"
export A2A_BEARER_TOKEN="pick-any-secret-string"
uvicorn app.main:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/prorate \
  -H "Content-Type: application/json" \
  -d '{"old_price":19,"new_price":69,"days_remaining":15,"days_in_actual_month":30,"spec":"v1"}'
```
