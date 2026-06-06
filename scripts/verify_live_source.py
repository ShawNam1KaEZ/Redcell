"""
scripts/verify_live_source.py — Audit checks A through E for LiveHybridSource.

Run from project root:
    python scripts/verify_live_source.py

Prints audit values A–E without starting the FastAPI server.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SEPARATOR = "=" * 72


def _section(label: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {label}")
    print(SEPARATOR)


# ── Audit A & B: CSV parsing stats ───────────────────────────────────────────
_section("AUDIT A+B  CSV parsing & hygiene counts")

import pandas as pd

hack_path = PROJECT_ROOT / "newdata" / "Hackathon Data_5000.csv"
user_path  = PROJECT_ROOT / "newdata" / "BW_Sample_Data_Updated_v3.xlsx - user_data.csv"

hack_df = pd.read_csv(hack_path, low_memory=False)
user_df  = pd.read_csv(user_path, low_memory=False)

# Hackathon hygiene masks
skip_dnk        = hack_df["blood_group"] == "Do not Know"
skip_nan_bg     = hack_df["blood_group"].isna()
skip_null_coords = hack_df["latitude"].isna() | hack_df["longitude"].isna()
skip_any        = skip_dnk | skip_nan_bg | skip_null_coords

print(f"\n[A] Hackathon Data_5000.csv")
print(f"    Raw rows                : {len(hack_df):>6}")
print(f"    Successfully retained   : {(~skip_any).sum():>6}")

print(f"\n[B] Hackathon Data_5000.csv — skipped entries")
print(f"    'Do not Know' blood grp : {skip_dnk.sum():>6}")
print(f"    NaN / unknown blood grp : {skip_nan_bg.sum():>6}")
print(f"    Null lat or lon         : {(skip_null_coords & ~skip_dnk & ~skip_nan_bg).sum():>6}")
print(f"    TOTAL dropped           : {skip_any.sum():>6}")

print(f"\n[A] user_data CSV")
print(f"    Raw rows                : {len(user_df):>6}")
user_skip = user_df["blood_group"].isna() | (user_df["blood_group"].astype(str) == "Do not Know")
print(f"    Skipped                 : {int(user_skip.sum()):>6}")
print(f"    Successfully retained   : {int((~user_skip).sum()):>6}")


# ── Audit C: blood bank pruning counts ───────────────────────────────────────
_section("AUDIT C  Blood bank pruning (80 km Hyderabad catchment)")

from hemogrid.sources.synthetic_source import SyntheticSource
from hemogrid.engine import haversine_km
from hemogrid.models import Location

HYD_LOC = Location(lat=17.3850, lng=78.4867)

print("\nLoading blood banks via SyntheticSource (silent)…")
import io
import contextlib

_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    _ss = SyntheticSource()
    # Load only banks — we don't need full synthetic generation here
    all_banks = _ss._load_blood_banks()

nationwide_total = len(all_banks)
retained, pruned_coord, pruned_dist = [], 0, 0
for b in all_banks:
    if not b.coord_valid:
        pruned_coord += 1
        continue
    dist = haversine_km(b.location, HYD_LOC)
    if dist <= 80.0:
        retained.append(b)
    else:
        pruned_dist += 1

print(f"    Nationwide banks (post-dedup) : {nationwide_total:>5}")
print(f"    Invalid coordinates (pruned)  : {pruned_coord:>5}")
print(f"    Valid but outside 80 km       : {pruned_dist:>5}")
print(f"    RETAINED within 80 km HYD     : {len(retained):>5}")
print(f"    TOTAL pruned                  : {pruned_coord + pruned_dist:>5}")


# ── Audit D: seed isolation invariant — live flag OFF ────────────────────────
_section("AUDIT D  Seed isolation -- HEMOGRID_USE_LIVE_DATA=false -> PAT-0001 -> BB-0036")

os.environ["HEMOGRID_USE_LIVE_DATA"] = "false"

from hemogrid.sources.synthetic_source import SyntheticSource
from hemogrid.engine import choose_lever, forecast_due
from hemogrid.models import Component, Request

print("\nLoading SyntheticSource (seed=42)…")
with contextlib.redirect_stdout(io.StringIO()):
    ds = SyntheticSource().load()

today = date(2026, 6, 5)
patient = next(p for p in ds.patients if p.patient_id == "PAT-0001")
next_need, _ = forecast_due(patient, today)
req = Request(
    request_id="AUDIT-D-REQ",
    patient_id="PAT-0001",
    needed_by_date=next_need,
    component=Component.PRBC,
    units=patient.units_per_session,
)
result = choose_lever(req, ds, today)

import re

lever_val = result["lever"].value
# engine.choose_lever returns bank_id as a top-level key when lever=inventory
bank_id = result.get("bank_id", "")
# Fallback: scan reasoning string for bank ID pattern
if not bank_id:
    reasoning = result.get("reasoning", "")
    m = re.search(r"BB-\d+", reasoning)
    bank_id = m.group(0) if m else "(not found)"

print(f"    Lever    : {lever_val}")
print(f"    Bank ID  : {bank_id}")

expected_lever = "inventory"
expected_bank  = "BB-0036"
lever_ok = lever_val == expected_lever
bank_ok  = bank_id == expected_bank

if lever_ok and bank_ok:
    print(f"\n    [PASS] lever={lever_val!r}, bank={bank_id!r} matches golden target")
else:
    print(f"\n    [FAIL] got lever={lever_val!r}, bank={bank_id!r}")
    print(f"             expected lever={expected_lever!r}, bank={expected_bank!r}")


# ── Audit E: live flag ON → dummy allocation → _DEMO_CACHE dump ──────────────
_section("AUDIT E  HEMOGRID_USE_LIVE_DATA=true -> dummy allocation -> _DEMO_CACHE dump")

os.environ["HEMOGRID_USE_LIVE_DATA"] = "true"

from hemogrid.sources.live_source import LiveHybridSource

print("\nLoading LiveHybridSource…")
live_ds = LiveHybridSource().load()

# Simulate _reset_demo_cache + dummy approval flow inline
_DEMO_CACHE: dict = {
    "patient_statuses":  {},
    "pending_proposals": {},
    "bank_adjustments":  {},
    "cell_adjustments":  {},
}

# Find a live patient that has a clinic in the HYD catchment
live_pat = next(
    (p for p in live_ds.patients if p.patient_id.startswith("LIVE-P-")),
    None,
)

if live_pat is None:
    print("    No LIVE-P- patient found — cannot run dummy allocation.")
else:
    # Simulate an approve-action adjustment (inventory lever, arbitrary bank)
    hyd_banks = [
        b for b in live_ds.blood_banks
        if b.units and b.bank_id.startswith("BB-")
    ]
    dummy_bank = hyd_banks[0] if hyd_banks else None
    dummy_bank_id = dummy_bank.bank_id if dummy_bank else "BB-DUMMY"
    dummy_clinic  = live_pat.clinic_id

    _DEMO_CACHE["patient_statuses"][live_pat.patient_id]  = "APPROVED"
    _DEMO_CACHE["bank_adjustments"][dummy_bank_id] = 1
    _DEMO_CACHE["cell_adjustments"][dummy_clinic]  = {"met_delta": 1, "supply_gap_delta": 1}

    print(f"\n    Dummy allocation:")
    print(f"      patient_id  : {live_pat.patient_id}")
    print(f"      bank_id     : {dummy_bank_id}")
    print(f"      clinic_id   : {dummy_clinic}")
    print(f"\n    _DEMO_CACHE dump:")
    for k, v in _DEMO_CACHE.items():
        print(f"      {k:<25} : {v}")

print(f"\n{SEPARATOR}")
print("  All audit checks complete.")
print(SEPARATOR)
