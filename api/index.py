from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal

app = FastAPI()


class ProrationRequest(BaseModel):
    old_price: float
    new_price: float
    days_remaining: float
    days_in_actual_month: float
    spec: Literal["v1", "v2"]


@app.post("/")
@app.post("/api")
@app.post("/api/index")
def calculate_charge(req: ProrationRequest):
    diff = req.new_price - req.old_price

    if req.spec == "v1":
        # Legacy rule: always divide by 30, regardless of actual month length
        charge = diff * (req.days_remaining / 30)
    elif req.spec == "v2":
        # Corrected rule: divide by the actual number of days in the billing month
        if req.days_in_actual_month == 0:
            raise HTTPException(status_code=400, detail="days_in_actual_month cannot be 0")
        charge = diff * (req.days_remaining / req.days_in_actual_month)
    else:
        raise HTTPException(status_code=400, detail="spec must be 'v1' or 'v2'")

    return {"charge": round(charge, 10)}
