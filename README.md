# Proration Endpoint

FastAPI endpoint that computes a prorated subscription charge, supporting both
the legacy 30-day-divisor rule (`spec: "v1"`) and the corrected actual-days
rule (`spec: "v2"`).

## Files

```
TDS-GA5-Repository/
├── api/
│   └── index.py       # the FastAPI app (all routing logic lives here)
├── vercel.json        # routes all paths to api/index.py
├── requirements.txt   # fastapi + pydantic
└── .gitignore
```

## Request format

```json
{
  "old_price": 19,
  "new_price": 69,
  "days_remaining": 15,
  "days_in_actual_month": 30,
  "spec": "v1"
}
```

## Response format

```json
{ "charge": 25.0 }
```

## Formula

- `spec == "v1"`: `charge = (new_price - old_price) * (days_remaining / 30)`
- `spec == "v2"`: `charge = (new_price - old_price) * (days_remaining / days_in_actual_month)`

## Deploy to Vercel

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. Go to https://vercel.com/new, import `Rarmman/TDS-GA5-Repository`, keep all
   defaults (Vercel auto-detects the Python function under `api/`), and click Deploy.
3. Your endpoint will be live at `https://<your-project>.vercel.app/`.

## Test locally

```bash
pip install -r requirements.txt uvicorn
uvicorn api.index:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" \
  -d '{"old_price":19,"new_price":69,"days_remaining":15,"days_in_actual_month":30,"spec":"v1"}'
# {"charge":25.0}
```
