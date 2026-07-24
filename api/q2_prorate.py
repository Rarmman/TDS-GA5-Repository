"""Q2 — Spec-Driven Development: The Proration Bug.
Route: POST /prorate
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

router = APIRouter()


class ProrationRequest(BaseModel):
    old_price: float
    new_price: float
    days_remaining: float
    days_in_actual_month: float
    spec: Literal["v1", "v2"]


@router.post("/prorate")
def prorate(req: ProrationRequest):
    diff = req.new_price - req.old_price

    if req.spec == "v1":
        charge = diff * (req.days_remaining / 30)
    elif req.spec == "v2":
        if req.days_in_actual_month == 0:
            raise HTTPException(status_code=400, detail="days_in_actual_month cannot be 0")
        charge = diff * (req.days_remaining / req.days_in_actual_month)
    else:
        raise HTTPException(status_code=400, detail="spec must be 'v1' or 'v2'")

    return {"charge": round(charge, 2)}
