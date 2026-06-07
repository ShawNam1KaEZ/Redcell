"""
Deterministic day-by-day inventory depletion forecast for HemoGrid.

Run:  python -m engine.forecast [--horizon N] [--data-dir PATH]
API:  from engine.forecast import run_global_forecast
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from engine.routing import haversine

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR     = "./data/build"
TODAY        = date(2026, 6, 6)
HORIZON_DAYS = 30

_RHD = {"pos": "+", "neg": "-"}


def _bt(abo: str, rhd: str) -> str:
    return f"{abo}{_RHD.get(rhd, rhd)}"


# ── Data loading ──────────────────────────────────────────────────────────────

def _load(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = Path(data_dir)
    patients   = pd.read_csv(d / "patients.csv",  dtype=str)
    bags       = pd.read_csv(d / "bags.csv",       dtype=str)
    banks      = pd.read_csv(d / "banks.csv",      dtype=str)
    facilities = pd.read_csv(d / "facilities.csv", dtype=str)

    patients["expected_transfusion_date"] = (
        pd.to_datetime(patients["expected_transfusion_date"]).dt.date
    )
    patients["transfusion_interval_days"] = patients["transfusion_interval_days"].astype(int)
    patients["units_per_session"] = (
        pd.to_numeric(patients["units_per_session"], errors="coerce").fillna(1).astype(int)
    )

    bags["expiry_date"]     = pd.to_datetime(bags["expiry_date"]).dt.date
    banks["latitude"]       = banks["latitude"].astype(float)
    banks["longitude"]      = banks["longitude"].astype(float)
    facilities["latitude"]  = facilities["latitude"].astype(float)
    facilities["longitude"] = facilities["longitude"].astype(float)

    return patients, bags, banks, facilities


# ── Facility → nearest active bank ───────────────────────────────────────────

def _fac_bank_map(facilities: pd.DataFrame, banks: pd.DataFrame) -> dict[str, str]:
    """Map facility_id → nearest bank_id among banks with valid (non-zero) coords."""
    active = banks[(banks["latitude"] != 0.0) | (banks["longitude"] != 0.0)].reset_index(drop=True)
    if active.empty:
        return {}
    mapping: dict[str, str] = {}
    for _, frow in facilities.iterrows():
        flat, flon = float(frow["latitude"]), float(frow["longitude"])
        dists = [
            haversine(flat, flon, float(r["latitude"]), float(r["longitude"]))
            for _, r in active.iterrows()
        ]
        closest = int(min(range(len(dists)), key=lambda i: dists[i]))
        mapping[str(frow["facility_id"])] = str(active.iloc[closest]["bank_id"])
    return mapping


# ── Demand event expansion ────────────────────────────────────────────────────

def _demand_events(
    patients: pd.DataFrame,
    fac_bank: dict[str, str],
    horizon: int,
    today: date,
) -> list[dict]:
    """Expand each patient's transfusion schedule into per-day demand events."""
    end_date = today + timedelta(days=horizon)
    events: list[dict] = []

    for _, p in patients.iterrows():
        bank_id = fac_bank.get(str(p["home_facility_id"]))
        if bank_id is None:
            continue
        bt       = _bt(str(p["abo"]), str(p["rhd"]))
        units    = int(p["units_per_session"])
        interval = int(p["transfusion_interval_days"])
        ev_date: date = p["expected_transfusion_date"]

        # Fast-forward past events to first occurrence >= today
        if ev_date < today:
            skip = (today - ev_date).days // interval
            ev_date = ev_date + timedelta(days=skip * interval)
            while ev_date < today:
                ev_date += timedelta(days=interval)

        while ev_date <= end_date:
            events.append({"day": ev_date, "bank_id": bank_id,
                           "blood_type": bt, "units": units})
            ev_date += timedelta(days=interval)

    return events


# ── Core simulation ───────────────────────────────────────────────────────────

def _simulate(
    horizon: int = HORIZON_DAYS,
    data_dir: str = DATA_DIR,
    today: date = TODAY,
) -> tuple[dict, list[tuple[str, bool, str]], dict]:
    """
    Returns (result_dict, assert_results, stats).
    Raises AssertionError (with print) on any invariant violation.
    """
    patients, bags, banks, facilities = _load(data_dir)

    # ── Baseline supply ───────────────────────────────────────────────────────
    live = bags[
        (bags["status"] == "available") &
        (bags["expiry_date"] >= today)
    ].copy()
    live["bt"] = live.apply(lambda r: _bt(str(r["abo"]), str(r["rhd"])), axis=1)

    bank_ids = set(banks["bank_id"].astype(str))

    # Aggregate live available bags per (bank, blood_type)
    bank_stock: dict[tuple[str, str], int] = defaultdict(int)
    live_at_banks = live[live["current_location_id"].isin(bank_ids)]
    for _, bag in live_at_banks.iterrows():
        bank_stock[(str(bag["current_location_id"]), str(bag["bt"]))] += 1

    # ── Facility → bank mapping via routing ───────────────────────────────────
    fbmap  = _fac_bank_map(facilities, banks)
    events = _demand_events(patients, fbmap, horizon, today)

    demand_by_day: dict[date, list[dict]] = defaultdict(list)
    for ev in events:
        demand_by_day[ev["day"]].append(ev)

    # ── Relevant (bank, blood_type) pairs ─────────────────────────────────────
    relevant: set[tuple[str, str]] = set(bank_stock)
    for ev in events:
        relevant.add((ev["bank_id"], ev["blood_type"]))

    # Expiry schedule: how many bags of each (bank, bt) expire on each date
    expiry_sched: dict[tuple[str, str, date], int] = defaultdict(int)
    for _, bag in live_at_banks.iterrows():
        expiry_sched[
            (str(bag["current_location_id"]), str(bag["bt"]), bag["expiry_date"])
        ] += 1

    # ── Day-by-day simulation ─────────────────────────────────────────────────
    sim: dict[tuple[str, str], int] = {k: bank_stock.get(k, 0) for k in relevant}
    depletion_day: dict[tuple[str, str], int] = {}
    total_consumed = 0

    for offset in range(horizon + 1):
        current_date = today + timedelta(days=offset)

        # Step 1: expire bags whose expiry_date == today
        for (bid, bt, exp_d), cnt in expiry_sched.items():
            if exp_d == current_date:
                key = (bid, bt)
                sim[key] = max(0, sim.get(key, 0) - cnt)

        # Step 2: consume demand scheduled for this day
        for ev in demand_by_day.get(current_date, []):
            key = (ev["bank_id"], ev["blood_type"])
            before   = sim.get(key, 0)
            consumed = min(before, ev["units"])
            sim[key] = before - consumed
            total_consumed += consumed

        # Step 3: record first day stock reaches zero
        for key in relevant:
            if key not in depletion_day and sim.get(key, 0) <= 0:
                depletion_day[key] = offset

    total_patient_demand = sum(ev["units"] for ev in events)

    # ── Asserts ───────────────────────────────────────────────────────────────
    assert_results: list[tuple[str, bool, str]] = []

    def _fail(msg: str) -> None:
        print(f"ASSERT FAIL: {msg}", file=sys.stderr)
        raise AssertionError(msg)

    # A1: total initial bank stock == count of live available bags in bags.csv
    total_initial = sum(bank_stock.values())
    live_total    = len(live)
    a1_msg = f"bank_stock={total_initial}, live_bags={live_total}"
    if total_initial != live_total:
        _fail(f"A1 -- {a1_msg}")
    print(f"[PASS] A1  Total bank stock == live available bags  --  {a1_msg}")
    assert_results.append(("A1  Total bank stock == live available bags", True, a1_msg))

    # A2: total forecasted consumption <= sum of all patients' demands over horizon
    a2_msg = f"consumed={total_consumed}, patient_demand={total_patient_demand}"
    if total_consumed > total_patient_demand:
        _fail(f"A2 -- {a2_msg}")
    print(f"[PASS] A2  Consumed <= patient demand over horizon  --  {a2_msg}")
    assert_results.append(("A2  Consumed <= patient demand over horizon", True, a2_msg))

    # A3: 0-stock + immediate demand on day 0 → days_to_depletion == 0
    a3_count = 0
    for key in relevant:
        if bank_stock.get(key, 0) == 0:
            day0_demand = [ev for ev in demand_by_day.get(today, [])
                           if (ev["bank_id"], ev["blood_type"]) == key]
            if day0_demand:
                dtd = depletion_day.get(key, 999)
                if dtd != 0:
                    _fail(f"A3 -- {key} has 0 stock + day-0 demand but dtd={dtd}")
                a3_count += 1
    a3_msg = f"{a3_count} qualifying pair(s) verified"
    print(f"[PASS] A3  0-stock + day-0 demand -> dtd == 0  --  {a3_msg}")
    assert_results.append(("A3  0-stock + day-0 demand -> dtd == 0", True, a3_msg))

    # A4: days_to_depletion is never a negative integer
    negatives = [(k, v) for k, v in depletion_day.items() if v < 0]
    a4_msg = f"0 negative dtd values" if not negatives else f"{len(negatives)} negative dtd found"
    if negatives:
        _fail(f"A4 -- {a4_msg}: {negatives[:3]}")
    print(f"[PASS] A4  days_to_depletion is never negative  --  {a4_msg}")
    assert_results.append(("A4  days_to_depletion is never negative", True, a4_msg))

    # ── Assemble result dict ──────────────────────────────────────────────────
    result: dict[str, dict[str, dict]] = {}
    for (bid, bt) in relevant:
        dtd     = depletion_day.get((bid, bt), 999)
        initial = bank_stock.get((bid, bt), 0)
        if dtd < 7:
            severity = "CRITICAL"
        elif dtd <= horizon:
            severity = "WARNING"
        else:
            severity = "STABLE"
        result.setdefault(bid, {})[bt] = {
            "initial_stock":     initial,
            "days_to_depletion": dtd,
            "shortage_severity": severity,
        }

    stats = {
        "total_initial_stock":  total_initial,
        "total_consumed":       total_consumed,
        "total_patient_demand": total_patient_demand,
        "total_events":         len(events),
    }

    return result, assert_results, stats


# ── Public API ────────────────────────────────────────────────────────────────

def run_global_forecast(horizon: int = HORIZON_DAYS, data_dir: str = DATA_DIR) -> dict:
    """
    Deterministic 30-day inventory depletion forecast.

    Returns:
      {
        bank_id: {
          "O+": {
            "initial_stock":     int,
            "days_to_depletion": int,   # 0–30 or 999 (stable)
            "shortage_severity": "CRITICAL" | "WARNING" | "STABLE"
          }, ...
        }, ...
      }
    Raises AssertionError on any invariant violation.
    """
    result, _, _ = _simulate(horizon, data_dir)
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

_SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "STABLE": 2}
_BT_ORDER  = {"O-": 0, "O+": 1, "A-": 2, "A+": 3, "B-": 4, "B+": 5, "AB-": 6, "AB+": 7}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m engine.forecast",
        description="HemoGrid deterministic inventory depletion forecast",
    )
    parser.add_argument("--horizon", type=int, default=HORIZON_DAYS,
                        help=f"Forecast horizon in days (default: {HORIZON_DAYS})")
    parser.add_argument("--data-dir", default=DATA_DIR,
                        help=f"Path to data/build directory (default: {DATA_DIR})")
    args = parser.parse_args()

    result, assert_results, stats = _simulate(args.horizon, args.data_dir)

    # Flatten result to sortable rows
    rows: list[dict] = []
    for bid, bts in result.items():
        for bt, info in bts.items():
            rows.append({
                "bank_id":           bid,
                "blood_type":        bt,
                "initial_stock":     info["initial_stock"],
                "days_to_depletion": info["days_to_depletion"],
                "shortage_severity": info["shortage_severity"],
            })

    rows.sort(key=lambda r: (
        _SEV_ORDER.get(r["shortage_severity"], 9),
        r["bank_id"],
        _BT_ORDER.get(r["blood_type"], 99),
    ))

    def _dtd_str(d: int) -> str:
        return str(d) if d < 999 else ">30"

    print()
    print(f"# HemoGrid Inventory Depletion Forecast")
    print(f"# Horizon: {TODAY} -> {TODAY + timedelta(days=args.horizon)} ({args.horizon} days)")
    print()
    print(f"| {'Bank ID':<10} | {'Type':<5} | {'Stock':>5} | {'Days->Dep':>9} | {'Severity':<10} |")
    print(f"|{'-'*12}|{'-'*7}|{'-'*7}|{'-'*11}|{'-'*12}|")

    for r in rows:
        print(
            f"| {r['bank_id']:<10} | {r['blood_type']:<5} | {r['initial_stock']:>5} | "
            f"{_dtd_str(r['days_to_depletion']):>9} | {r['shortage_severity']:<10} |"
        )

    print()

    critical = [r for r in rows if r["shortage_severity"] == "CRITICAL"]
    warning  = [r for r in rows if r["shortage_severity"] == "WARNING"]
    stable   = [r for r in rows if r["shortage_severity"] == "STABLE"]

    print(
        f"**SYSTEM SUMMARY** | {len(critical)} CRITICAL shortage(s) | "
        f"{len(warning)} WARNING | {len(stable)} STABLE | "
        f"horizon={args.horizon}d | initial_stock={stats['total_initial_stock']} bags | "
        f"total_demand={stats['total_patient_demand']} units | "
        f"consumed={stats['total_consumed']} units | "
        f"events={stats['total_events']}"
    )
    print()
    print("## Assert Validation")
    for label, passed, detail in assert_results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}  --  {detail}")


if __name__ == "__main__":
    main()
