"""
HemoGrid matching engine — Gate → Rank → Tier.

match(patient_id) -> {"patient_id", "G1", "G2", "G3", "excluded"}

Tiers:
  G1 Exact        — typed donor, ABO identical, all tested antigens match, antibody-safe.
  G2 Compatible   — ABO-compatible + Rh+K floor + antibody-safe (untyped flagged below typed).
  G3 Emergency    — only when G1+G2 empty or auto/panreactive; never auto-issue.
  excluded        — failed Gate 1/2/3 with reason code(s).

Invariant: inventory is always derived live (status+expiry query), never a stored column.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from engine.routing import get_route_metrics, _load_location_index, LONG_HAUL_KM

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = "./data/build"
TODAY    = date(2026, 6, 6)

ANTIGEN_COLS = [
    "phenotype_C", "phenotype_c", "phenotype_E", "phenotype_e",
    "phenotype_K", "phenotype_k",
    "phenotype_Jka", "phenotype_Jkb",
    "phenotype_Fya", "phenotype_Fyb",
    "phenotype_M", "phenotype_N", "phenotype_S", "phenotype_s",
]

# Rh system (C, c, E, e) + Kell (K) — minimum floor for G2 typed donors
RH_K_COLS = ["phenotype_C", "phenotype_c", "phenotype_E", "phenotype_e", "phenotype_K"]

# ABO compatibility: donor ABO → set of compatible patient ABO groups
ABO_COMPAT: dict[str, set[str]] = {
    "O":  {"O", "A", "B", "AB"},
    "A":  {"A", "AB"},
    "B":  {"B", "AB"},
    "AB": {"AB"},
}

# ── Data loader (module-level cache) ──────────────────────────────────────────
_cache: dict[str, tuple] = {}


def _bool(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def _load_all(data_dir: str = DATA_DIR) -> tuple:
    if data_dir in _cache:
        return _cache[data_dir]

    d = Path(data_dir)
    patients   = pd.read_csv(d / "patients.csv")
    donors     = pd.read_csv(d / "donors.csv")
    bags       = pd.read_csv(d / "bags.csv")
    antibodies = pd.read_csv(d / "antibodies.csv")
    banks      = pd.read_csv(d / "banks.csv")
    facilities = pd.read_csv(d / "facilities.csv")

    bool_bag_cols = ["leukoreduced", "irradiated", "washed", "cmv_negative"]
    bool_pat_cols = [
        "special_irradiated", "special_cmv_neg", "special_washed",
        "leukoreduced_standard", "hbs_required_neg", "is_typed",
        "requires_adsorption_workup",
    ]
    bool_dnr_cols = ["is_typed"]

    for df, cols in [(bags, bool_bag_cols), (patients, bool_pat_cols), (donors, bool_dnr_cols)]:
        for c in cols:
            if c in df.columns:
                df[c] = df[c].apply(_bool)

    bags["expiry_date"] = pd.to_datetime(bags["expiry_date"]).dt.date

    result = (patients, donors, bags, antibodies, banks, facilities)
    _cache[data_dir] = result
    return result

# ── Phenotype helpers ─────────────────────────────────────────────────────────

def _phenotype_concordance(donor: pd.Series, patient: pd.Series) -> tuple[float, bool]:
    """
    Returns (concordance_ratio, all_tested_match).
    Skips antigen columns where either side is 'unknown'.
    """
    tested = matched = 0
    for col in ANTIGEN_COLS:
        dv = donor.get(col, "unknown")
        pv = patient.get(col, "unknown")
        if dv == "unknown" or pv == "unknown":
            continue
        tested += 1
        if dv == pv:
            matched += 1
    if tested == 0:
        return 0.0, False
    return matched / tested, matched == tested


def _rh_k_match(donor: pd.Series, patient: pd.Series) -> bool:
    """
    True only when ALL Rh+K antigens are non-unknown on both sides and match.
    Conservative: any unknown → False (cannot confirm compatibility floor).
    """
    for col in RH_K_COLS:
        dv = donor.get(col, "unknown")
        pv = patient.get(col, "unknown")
        if dv == "unknown" or pv == "unknown":
            return False
        if dv != pv:
            return False
    return True

# ── Routing integration ───────────────────────────────────────────────────────

def _get_route(bag: pd.Series, patient: pd.Series, loc_idx: dict) -> dict:
    """
    Compute distance + ETA from bag's current_location_id to patient's home_facility_id.
    Returns None values if either location has no geocode in the index.
    Uses real (non-jittered) coordinates exclusively — INVARIANT #3.
    """
    loc_id = str(bag["current_location_id"])
    fac_id = str(patient["home_facility_id"])

    if loc_id not in loc_idx or fac_id not in loc_idx:
        return {"distance_km": None, "eta_minutes": None, "is_long_haul": False}

    olat, olon, _ = loc_idx[loc_id]
    dlat, dlon, _ = loc_idx[fac_id]
    return get_route_metrics(olat, olon, dlat, dlon)

# ── Candidate builder ─────────────────────────────────────────────────────────

def _candidate(
    bag: pd.Series,
    donor: pd.Series,
    patient: pd.Series,
    route: dict,
    concordance: float,
    risk_flags: list[str],
) -> dict:
    return {
        "bag_id":                bag["bag_id"],
        "donor_id":              bag["donor_id"],
        "abo":                   bag["abo"],
        "rhd":                   bag["rhd"],
        "donor_typed":           bool(donor["is_typed"]),
        "phenotype_concordance": round(concordance, 4),
        "distance_km":           route.get("distance_km"),
        "eta_minutes":           route.get("eta_minutes"),
        "is_long_haul":          route.get("is_long_haul", False),
        "risk_flags":            list(risk_flags),
        "expiry_date":           str(bag["expiry_date"]),
        "component":             bag["component"],
        "current_location_id":   bag["current_location_id"],
        "home_facility_id":      patient["home_facility_id"],
    }

# ── Main matching function ────────────────────────────────────────────────────

def match(
    patient_id: str,
    data_dir:   str  = DATA_DIR,
    today:      date = TODAY,
) -> dict:
    """
    Gate → Rank → Tier matching for a single patient.

    Returns:
        {
            "patient_id": str,
            "G1": [candidate, ...],   # sorted: concordance↓, distance↑, expiry↑
            "G2": [candidate, ...],   # sorted: concordance↓, typed>untyped, distance↑, expiry↑
            "G3": [candidate, ...],   # populated only when G1+G2 empty
            "excluded": [record, ...]
        }
    """
    patients, donors, bags, antibodies, banks, facilities = _load_all(data_dir)
    loc_idx = _load_location_index(data_dir)

    pat_rows = patients[patients["patient_id"] == patient_id]
    if pat_rows.empty:
        raise ValueError(f"Patient not found: {patient_id!r}")
    patient = pat_rows.iloc[0]

    pat_abs       = antibodies[antibodies["patient_id"] == patient_id]
    is_immunized  = len(pat_abs) > 0
    has_auto_ab   = (pat_abs["type"] == "auto").any()
    # Each antigen the patient has an antibody against (allo + auto, active + historical)
    forbidden_ags = set(pat_abs["antigen"].dropna().tolist())

    pat_abo = patient["abo"]
    pat_rhd = patient["rhd"]

    # ── Live inventory: derived query, never a stored column (INVARIANT #1) ──
    avail = bags[
        (bags["status"] == "available") &
        (bags["expiry_date"] >= today)
    ].copy()

    donor_map = donors.set_index("donor_id")

    g1:      list[dict] = []
    g2:      list[dict] = []
    g3_pool: list[dict] = []  # antibody-incompatible / Rh+K-mismatch candidates
    excl:    list[dict] = []

    for _, bag in avail.iterrows():
        bag_id   = bag["bag_id"]
        donor_id = bag["donor_id"]
        bag_abo  = bag["abo"]
        bag_rhd  = bag["rhd"]

        # ── Gate 1A: component ───────────────────────────────────────────────
        if bag["component"] != "packed_rbc":
            excl.append({"bag_id": bag_id, "donor_id": donor_id,
                         "reason": "wrong_component"})
            continue

        # ── Gate 1B: processing requirements + TTI ───────────────────────────
        reasons: list[str] = []

        if bag["tti_screen_status"] != "pass":
            reasons.append("tti_fail")
        if patient["special_irradiated"] and not bag["irradiated"]:
            reasons.append("irradiated_required")
        if patient["special_cmv_neg"] and not bag["cmv_negative"]:
            reasons.append("cmv_neg_required")
        if patient["special_washed"] and not bag["washed"]:
            reasons.append("washed_required")
        if patient["leukoreduced_standard"] and not bag["leukoreduced"]:
            reasons.append("leukoreduced_required")

        if donor_id not in donor_map.index:
            excl.append({"bag_id": bag_id, "donor_id": donor_id,
                         "reason": "donor_record_missing"})
            continue

        donor = donor_map.loc[donor_id]

        if patient["hbs_required_neg"] and donor.get("hbs_status") != "neg":
            reasons.append("hbs_positive_donor")

        if reasons:
            excl.append({"bag_id": bag_id, "donor_id": donor_id,
                         "reason": "|".join(reasons)})
            continue

        # ── Gate 2: ABO/Rh-D compatibility ──────────────────────────────────
        if pat_abo not in ABO_COMPAT.get(bag_abo, set()):
            excl.append({"bag_id": bag_id, "donor_id": donor_id,
                         "reason": "abo_incompatible"})
            continue

        # D− patient → D− donor only (INVARIANT #3 / CLAUDE.md lattice rule)
        if pat_rhd == "neg" and bag_rhd != "neg":
            excl.append({"bag_id": bag_id, "donor_id": donor_id,
                         "reason": "rh_d_incompatible"})
            continue

        # ── Routing (computed for all Gate-2 survivors) ──────────────────────
        route      = _get_route(bag, patient, loc_idx)
        risk_flags: list[str] = []
        if route.get("is_long_haul"):
            risk_flags.append("long_haul_fetch")

        # ── Auto-antibody / panreactive → always G3, never auto-issue ────────
        if bool(patient["requires_adsorption_workup"]) or has_auto_ab:
            g3_pool.append(_candidate(bag, donor, patient, route, 0.0,
                                      risk_flags + ["auto_antibody_workup_required"]))
            continue

        # ── Gate 3: antibody exclusion ───────────────────────────────────────
        is_typed = bool(donor["is_typed"])

        # Untyped donor → excluded for immunized patients (cannot prove antigen-neg)
        if not is_typed and is_immunized:
            excl.append({"bag_id": bag_id, "donor_id": donor_id,
                         "reason": "untyped_donor_immunized_patient"})
            continue

        ab_reasons: list[str] = []
        for ag in forbidden_ags:
            col = f"phenotype_{ag}"
            dv  = donor.get(col, "unknown")
            if dv == "unknown":
                # Cannot confirm antigen-negativity; treat as unsafe for immunized patient
                ab_reasons.append(f"cannot_confirm_antigen_neg_{ag}")
            elif dv == "pos":
                ab_reasons.append(f"antigen_pos_{ag}")

        if ab_reasons:
            # Antigen-unsafe — pool for G3 (least-incompatible emergency tier)
            g3_pool.append(_candidate(bag, donor, patient, route, 0.0,
                                      risk_flags + ab_reasons))
            continue

        # ── Tier assignment (Gates 1-3 passed) ──────────────────────────────
        concordance, all_match = _phenotype_concordance(donor, patient)
        is_abo_identical = (bag_abo == pat_abo)

        # G1 Exact: typed + ABO identical + all tested antigens match
        if is_typed and is_abo_identical and all_match and concordance > 0.0:
            g1.append(_candidate(bag, donor, patient, route, concordance, risk_flags))
            continue

        if is_typed:
            # G2 typed: requires Rh+K floor match
            if _rh_k_match(donor, patient):
                g2.append(_candidate(bag, donor, patient, route, concordance, risk_flags))
            else:
                # Typed but Rh+K mismatch → G3 pool (not auto-issued)
                g3_pool.append(_candidate(bag, donor, patient, route, concordance,
                                          risk_flags + ["rh_k_mismatch"]))
        else:
            # Untyped, non-immunized patient: G2 flagged — ranked below typed donors
            g2.append(_candidate(bag, donor, patient, route, 0.0,
                                 risk_flags + ["phenotype_unconfirmed"]))

    # ── Sort tiers ───────────────────────────────────────────────────────────
    g1.sort(key=lambda c: (
        -c["phenotype_concordance"],
        c["distance_km"] if c["distance_km"] is not None else 9999.0,
        c["expiry_date"],
    ))

    g2.sort(key=lambda c: (
        -c["phenotype_concordance"],
        0 if c["donor_typed"] else 1,   # typed donors first
        c["distance_km"] if c["distance_km"] is not None else 9999.0,
        c["expiry_date"],
    ))

    # G3 activated only when G1+G2 are empty (CLAUDE.md: 3 immunized patients
    # with zero compatible bags must land in G3, not error)
    g3: list[dict] = []
    if not g1 and not g2:
        g3 = sorted(
            g3_pool,
            key=lambda c: (
                # Prefer least number of hard antigen conflicts
                sum(1 for f in c["risk_flags"] if f.startswith("antigen_pos")),
                c["distance_km"] if c["distance_km"] is not None else 9999.0,
                c["expiry_date"],
            ),
        )

    return {
        "patient_id": patient_id,
        "G1":         g1,
        "G2":         g2,
        "G3":         g3,
        "excluded":   excl,
    }


# ── CLI self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    patients, *_ = _load_all(data_dir)

    total_g1 = total_g2 = total_g3 = 0
    g3_patients: list[str] = []

    for pid in patients["patient_id"].tolist():
        r = match(pid, data_dir)
        total_g1 += len(r["G1"])
        total_g2 += len(r["G2"])
        total_g3 += len(r["G3"])
        if r["G3"]:
            g3_patients.append(pid)

    n = len(patients)
    print(f"\nmatch() self-test over {n} patients:")
    print(f"  Total G1 candidates : {total_g1}")
    print(f"  Total G2 candidates : {total_g2}")
    print(f"  Total G3 patients   : {len(g3_patients)}  {g3_patients}")

    sample_id = patients.iloc[0]["patient_id"]
    sample    = match(sample_id, data_dir)
    print(f"\nSample -- {sample_id}:")
    print(f"  G1={len(sample['G1'])} G2={len(sample['G2'])} "
          f"G3={len(sample['G3'])} excl={len(sample['excluded'])}")
    top = sample["G1"] or sample["G2"] or sample["G3"]
    if top:
        print("  Top candidate:", json.dumps(top[0], indent=4))
