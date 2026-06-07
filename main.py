"""
HemoGrid FastAPI gateway — links engine (match, routing, forecast, state) to
the React frontend.

Startup asserts:
  - bags.csv baseline has 536 available bags (clean environment check).
  - SQLite DB is initialized before serving any request.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ─────────────────────────────────────────────────────────────────────
HOST     = "0.0.0.0"
PORT     = 8000
DATA_DIR = "./data/build"
TODAY    = "2026-06-06"
TODAY_D  = date(2026, 6, 6)

# ── Startup lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from engine import state as _state

    # Ensure DB tables exist; initialize from CSV if not.
    try:
        count = _state._total_available()
    except sqlite3.OperationalError:
        print("  [INIT] No DB tables found — running reset_simulation_state() ...")
        _state.reset_simulation_state()
        count = _state._total_available()

    # Baseline assert: verify the CSV source of truth always carries 536 available bags.
    bags_csv = pd.read_csv(Path(DATA_DIR) / "bags.csv")
    bags_csv["expiry_date"] = pd.to_datetime(bags_csv["expiry_date"]).dt.date
    csv_avail = int(
        ((bags_csv["status"] == "available") & (bags_csv["expiry_date"] >= TODAY_D)).sum()
    )
    if csv_avail != 536:
        raise AssertionError(
            f"[FAIL] Startup assert: baseline CSV has {csv_avail} available bags, expected 536"
        )
    print(f"  [PASS] Startup assert: {csv_avail} available bags in baseline CSV.")
    print(f"  [INFO] Live DB currently has {count} available bags.")
    print(
        "FastAPI server successfully active with CORS middleware enabled. "
        "Ready for UI binding."
    )
    yield


app = FastAPI(title="HemoGrid API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ─────────────────────────────────────────────────────────────

class TreatRequest(BaseModel):
    patient_id: str
    bag_id: str


class DonateRequest(BaseModel):
    donor_id: str
    bank_id: str
    abo: str
    rhd: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/inventory")
async def get_inventory():
    """
    Live derived inventory across all banks.
    Returns: { bank_id: { blood_type: count } }
    blood_type format: abo || rhd, e.g. "Opos", "Aneg", "ABpos".
    """
    try:
        from engine import state as _state
        conn = _state.get_conn()
        rows = conn.execute(
            """
            SELECT current_location_id AS bank_id,
                   abo || rhd          AS blood_type,
                   COUNT(*)            AS count
            FROM bags
            WHERE status = 'available'
              AND expiry_date >= ?
            GROUP BY current_location_id, abo || rhd
            """,
            (TODAY,),
        ).fetchall()
        result: dict = {}
        for r in rows:
            result.setdefault(r["bank_id"], {})[r["blood_type"]] = r["count"]
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/patient/{patient_id}/match")
def match_patient(patient_id: str):
    """
    Full tiered match for a single patient.
    Returns: { patient_id, G1, G2, G3, excluded } with haversine metrics.
    """
    try:
        from engine import match as _match
        return _match.match(patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/forecast")
def get_forecast():
    """
    30-day deterministic inventory depletion forecast.
    Returns: { bank_id: { blood_type: { initial_stock, days_to_depletion, shortage_severity } } }
    """
    try:
        from engine import forecast as _forecast
        return _forecast.run_global_forecast(horizon=30)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/actions/treat")
async def treat(req: TreatRequest):
    """
    Issue a bag to a patient.
    Body: { "patient_id": "PAT-#####", "bag_id": "BAG-#####" }
    """
    try:
        from engine import state as _state
        _state.issue_bag_to_patient(req.bag_id, req.patient_id)
        return {"status": "issued", "bag_id": req.bag_id, "patient_id": req.patient_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/actions/donate")
async def donate(req: DonateRequest):
    """
    Register a donation and return the new bag ID.
    Body: { "donor_id": "DNR-#####", "bank_id": "BNK-#####", "abo": str, "rhd": str }
    """
    try:
        from engine import state as _state
        new_bag_id = _state.register_donation(req.donor_id, req.bank_id, req.abo, req.rhd)
        return {"status": "registered", "bag_id": new_bag_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/state/reset")
async def reset_state():
    """
    Reset simulation to baseline CSV state.
    Returns: { status, available_bags, baseline_check }
    """
    try:
        from engine import state as _state
        _state.reset_simulation_state()
        available = _state._total_available()
        return {
            "status":         "reset",
            "available_bags": available,
            "baseline_check": available == 536,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/logs")
async def get_logs():
    """Activity log entries, newest first."""
    try:
        from engine import state as _state
        conn = _state.get_conn()
        rows = conn.execute(
            "SELECT id, timestamp, action_type, actor, description, affected_ids "
            "FROM activity_log ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/patients")
async def get_patients():
    """Roster of all patients — key fields for the left panel."""
    try:
        d = Path(DATA_DIR)
        df = pd.read_csv(d / "patients.csv", dtype=str)
        keep = ["patient_id", "abo", "rhd", "sex", "latitude", "longitude",
                "expected_transfusion_date", "home_facility_id"]
        for col in ["immunized", "diagnosis"]:
            if col in df.columns:
                keep.append(col)
        keep += [c for c in df.columns if c.startswith("phenotype_")]
        keep = [c for c in keep if c in df.columns]
        return df[keep].fillna("").to_dict(orient="records")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/donors")
async def get_donors():
    """Roster of all donors — key fields for the left panel."""
    try:
        d = Path(DATA_DIR)
        df = pd.read_csv(d / "donors.csv", dtype=str)
        keep = ["donor_id", "abo", "rhd", "sex", "latitude", "longitude",
                "eligibility_status", "home_bank_id", "donor_type",
                "donor_subtype", "active_status", "donation_count", "last_donation_date"]
        if "phenotype" in df.columns:
            keep.append("phenotype")
        keep = [c for c in keep if c in df.columns]
        return df[keep].fillna("").to_dict(orient="records")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/map-data")
async def get_map_data():
    """
    Spatial coordinate array for banks and facilities merged with live stock summaries.
    Each entry: { id, type, name, latitude, longitude, available_bags?, patient_ids? }
    Facilities include list of patient_ids with that facility as home_facility_id.
    """
    try:
        from engine import state as _state

        d          = Path(DATA_DIR)
        banks      = pd.read_csv(d / "banks.csv", dtype=str)
        facilities = pd.read_csv(d / "facilities.csv", dtype=str)
        patients   = pd.read_csv(d / "patients.csv", dtype=str)

        # Live available bag count per bank
        conn = _state.get_conn()
        stock_rows = conn.execute(
            """
            SELECT current_location_id AS bank_id, COUNT(*) AS available_count
            FROM bags
            WHERE status = 'available' AND expiry_date >= ?
            GROUP BY current_location_id
            """,
            (TODAY,),
        ).fetchall()
        stock_map = {r["bank_id"]: r["available_count"] for r in stock_rows}

        # Map patients to their home facility
        facility_patients = {}
        for _, pat in patients.iterrows():
            fid = str(pat.get("home_facility_id", ""))
            if fid and fid != "":
                if fid not in facility_patients:
                    facility_patients[fid] = []
                facility_patients[fid].append(str(pat["patient_id"]))

        result = []

        for _, row in banks.iterrows():
            bid = str(row["bank_id"])
            result.append({
                "id":             bid,
                "type":           "bank",
                "name":           str(row.get("name", "")),
                "latitude":       float(row["latitude"]),
                "longitude":      float(row["longitude"]),
                "available_bags": stock_map.get(bid, 0),
            })

        for _, row in facilities.iterrows():
            fid = str(row["facility_id"])
            result.append({
                "id":          fid,
                "type":        "facility",
                "name":        str(row.get("name", "")),
                "latitude":    float(row["latitude"]),
                "longitude":   float(row["longitude"]),
                "patient_ids": facility_patients.get(fid, []),
            })

        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
