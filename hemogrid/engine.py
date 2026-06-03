"""
hemogrid/engine.py — Deterministic matching and forecasting engine.

Pure functions: no LLM, no randomness, no I/O, no network calls.
Every decision is encoded here; LLM agents only narrate this engine's output.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional, Union

from .models import (
    ABOGroup,
    BloodBank,
    CanonicalDataset,
    Component,
    Donor,
    InventoryUnit,
    Lever,
    Location,
    Patient,
    Phenotype,
    Request,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Recipient-side ABO compatibility for PRBC.
# Maps recipient group → acceptable donor/unit ABO groups.
_PRBC_COMPAT: dict[ABOGroup, set[ABOGroup]] = {
    ABOGroup.O:  {ABOGroup.O},
    ABOGroup.A:  {ABOGroup.A, ABOGroup.O},
    ABOGroup.B:  {ABOGroup.B, ABOGroup.O},
    ABOGroup.AB: {ABOGroup.A, ABOGroup.B, ABOGroup.AB, ABOGroup.O},
}

_ANTIGEN_ATTRS: tuple[str, ...] = ("C", "c", "E", "e", "K")

# Scoring weights for rank_matches
_W_PROXIMITY   = 0.25
_W_RELIABILITY = 0.30
_W_PHENOTYPE   = 0.20
_BOND_BONUS    = 0.40   # deliberately large — Blood Bridge is the key differentiator

_SEARCH_RADIUS_KM = 100.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _abo_of(donor_or_unit: Union[Donor, InventoryUnit]) -> ABOGroup:
    if isinstance(donor_or_unit, Donor):
        return donor_or_unit.abo_group
    return donor_or_unit.abo


def _phenotype_of(donor_or_unit: Union[Donor, InventoryUnit]) -> Optional[Phenotype]:
    if isinstance(donor_or_unit, Donor):
        return donor_or_unit.phenotype
    return donor_or_unit.phenotype_tags


def _parse_antigen(antibody: str) -> Optional[str]:
    """'anti-K' → 'K'; unrecognised format → None."""
    if antibody.lower().startswith("anti-"):
        ag = antibody[5:]
        return ag if ag in _ANTIGEN_ATTRS else None
    return None


# ---------------------------------------------------------------------------
# 1. ABO / Rh compatibility
# ---------------------------------------------------------------------------

def abo_rh_compatible(
    recipient: Patient,
    donor_or_unit: Union[Donor, InventoryUnit],
) -> bool:
    """
    True iff the donor/unit is ABO+Rh compatible for PRBC transfusion into
    this recipient (recipient-side rules).

    ABO: recipient can only receive from the groups listed in _PRBC_COMPAT.
    Rh:  Rh-negative recipient → Rh-negative source only (hard rule for
         chronically transfused thalassemia patients).
         Rh-positive recipient → either polarity.
    """
    if _abo_of(donor_or_unit) not in _PRBC_COMPAT[recipient.abo_group]:
        return False
    if not recipient.rh_d and donor_or_unit.rh_d:
        return False
    return True


# ---------------------------------------------------------------------------
# 2. Antibody-phenotype safety gate
# ---------------------------------------------------------------------------

def phenotype_antibody_safe(
    patient: Patient,
    donor_or_unit: Union[Donor, InventoryUnit],
) -> bool:
    """
    True iff the source is safe given the patient's known alloantibodies.

    For each antibody the patient carries, the source must be NEGATIVE for
    that antigen.  If the source phenotype is unknown (None) and the patient
    has ≥1 antibody, fail-safe: return False.
    """
    if not patient.known_antibodies:
        return True

    src_ph = _phenotype_of(donor_or_unit)
    if src_ph is None:
        return False  # unknown phenotype + patient has antibodies → reject

    for ab in patient.known_antibodies:
        ag = _parse_antigen(ab)
        if ag is None:
            continue
        antigen_status = getattr(src_ph, ag, None)
        if antigen_status is None:
            return False  # antigen not typed → fail-safe reject
        if antigen_status:
            return False  # source is antigen-positive → unsafe
    return True


# ---------------------------------------------------------------------------
# 3. Phenotype match quality (ranking boost, not a filter)
# ---------------------------------------------------------------------------

def phenotype_match_quality(
    patient: Patient,
    donor_or_unit: Union[Donor, InventoryUnit],
) -> float:
    """
    Normalized concordance score [0, 1] on {C, c, E, e, K}.

    Only antigens where the patient has no antibody are counted — those are
    already handled by the safety gate.  Returns 0.0 if either phenotype is
    unknown.
    """
    src_ph = _phenotype_of(donor_or_unit)
    pat_ph = patient.phenotype
    if src_ph is None or pat_ph is None:
        return 0.0

    ab_antigens = {_parse_antigen(ab) for ab in patient.known_antibodies} - {None}

    matches = total = 0
    for attr in _ANTIGEN_ATTRS:
        if attr in ab_antigens:
            continue
        pv = getattr(pat_ph, attr, None)
        sv = getattr(src_ph, attr, None)
        if pv is not None and sv is not None:
            total += 1
            if pv == sv:
                matches += 1

    return matches / total if total else 0.0


# ---------------------------------------------------------------------------
# 4. Donor eligibility
# ---------------------------------------------------------------------------

def donor_eligible(donor: Donor, today: date) -> bool:
    """
    True iff the donor may be contacted:
      - consent.contactable is True
      - ≥ 90 days since last_donation_date (NBTC deferral rule)
    """
    if not donor.consent.contactable:
        return False
    if donor.last_donation_date is None:
        return True
    return (today - donor.last_donation_date).days >= 90


# ---------------------------------------------------------------------------
# 5. Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(loc_a: Location, loc_b: Location) -> float:
    """Great-circle distance in km between two Location objects."""
    R = 6371.0
    lat1 = math.radians(loc_a.lat)
    lon1 = math.radians(loc_a.lng)
    lat2 = math.radians(loc_b.lat)
    lon2 = math.radians(loc_b.lng)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# 6. Transfusion forecast
# ---------------------------------------------------------------------------

def forecast_due(
    patient: Patient,
    today: date,
    lead_days: int = 7,
) -> tuple[date, bool]:
    """
    Return (next_need_date, is_due_soon).

    next_need_date = last_transfusion_date + transfusion_interval_days.
    is_due_soon    = True when next_need_date falls within lead_days of today.
    """
    next_need = patient.last_transfusion_date + timedelta(
        days=patient.transfusion_interval_days
    )
    is_due_soon = 0 <= (next_need - today).days <= lead_days
    return next_need, is_due_soon


# ---------------------------------------------------------------------------
# 7. Rank donor matches
# ---------------------------------------------------------------------------

def rank_matches(
    request: Request,
    candidate_donors: list[Donor],
    dataset: CanonicalDataset,
    today: date,
) -> list[dict[str, Any]]:
    """
    Filter and rank donors for a transfusion request.

    Filters: ABO+Rh compatible, donor_eligible, phenotype_antibody_safe.
    Score = proximity × 0.25 + reliability × 0.30 + phenotype_quality × 0.20
            + bond_bonus (0.40 if donor is bonded to this patient, else 0).

    Returns a sorted list (best first), each entry containing the donor and a
    breakdown dict so reasoning is fully inspectable by an LLM narrator.
    """
    patient = next(
        (p for p in dataset.patients if p.patient_id == request.patient_id), None
    )
    if patient is None:
        return []

    clinic = next(
        (c for c in dataset.clinics if c.clinic_id == patient.clinic_id), None
    )
    clinic_loc = clinic.location if clinic else None

    results: list[dict[str, Any]] = []
    for donor in candidate_donors:
        if not donor_eligible(donor, today):
            continue
        if not abo_rh_compatible(patient, donor):
            continue
        if not phenotype_antibody_safe(patient, donor):
            continue

        dist_km = haversine_km(clinic_loc, donor.location) if clinic_loc else 9999.0
        proximity_score = 1.0 / (1.0 + dist_km / 50.0)
        ph_quality = phenotype_match_quality(patient, donor)
        bonded = request.patient_id in donor.linked_patients
        bond_bonus = _BOND_BONUS if bonded else 0.0

        score = (
            _W_PROXIMITY   * proximity_score
            + _W_RELIABILITY * donor.reliability_score
            + _W_PHENOTYPE   * ph_quality
            + bond_bonus
        )

        results.append({
            "donor":   donor,
            "score":   round(score, 4),
            "breakdown": {
                "proximity_km":      round(dist_km, 1),
                "proximity_score":   round(proximity_score, 4),
                "reliability":       round(donor.reliability_score, 4),
                "phenotype_quality": round(ph_quality, 4),
                "bonded":            bonded,
                "bond_bonus":        bond_bonus,
            },
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 8. Blood desert score
# ---------------------------------------------------------------------------

def blood_desert_score(
    clinic_id: str,
    dataset: CanonicalDataset,
    today: date,
    radius_km: float = 50.0,
    lead_days: int = 7,
) -> dict[str, Any]:
    """
    Blood-desert metric for the geographic cell centred on a clinic.

    Demand: total units needed by patients at this clinic due within lead_days.
    Supply counted ONLY as immunologically compatible + antibody-safe sources:
      - inventory: non-expired PRBC units at banks within radius_km
      - donors: eligible donors within radius_km

    desert_score = max(0, demand_units − inventory_supply − donor_supply).
    Higher = worse mismatch (true desert).
    """
    clinic = next((c for c in dataset.clinics if c.clinic_id == clinic_id), None)
    if clinic is None:
        return {"error": f"clinic {clinic_id!r} not found"}

    due_patients = [
        p for p in dataset.patients
        if p.clinic_id == clinic_id and forecast_due(p, today, lead_days)[1]
    ]
    demand_units = sum(p.units_per_session for p in due_patients)

    nearby_banks = [
        b for b in dataset.blood_banks
        if b.coord_valid
        and haversine_km(clinic.location, b.location) <= radius_km
    ]
    nearby_donors = [
        d for d in dataset.donors
        if haversine_km(clinic.location, d.location) <= radius_km
    ]

    # Count supply immunologically (per-patient compatibility):
    # one eligible source per patient is enough for the demand metric.
    inventory_supply = 0
    for patient in due_patients:
        for bank in nearby_banks:
            for unit in bank.units:
                if (
                    unit.component == Component.PRBC
                    and unit.storage_status == "ok"
                    and unit.expiry_date >= today
                    and abo_rh_compatible(patient, unit)
                    and phenotype_antibody_safe(patient, unit)
                ):
                    inventory_supply += 1
                    break  # one compatible unit found for this patient
            else:
                continue
            break  # stop searching banks once this patient is covered

    donor_supply = 0
    for patient in due_patients:
        for donor in nearby_donors:
            if (
                donor_eligible(donor, today)
                and abo_rh_compatible(patient, donor)
                and phenotype_antibody_safe(patient, donor)
            ):
                donor_supply += 1
                break

    desert_score = max(0, demand_units - inventory_supply - donor_supply)

    return {
        "clinic_id":        clinic_id,
        "radius_km":        radius_km,
        "patients_due":     len(due_patients),
        "demand_units":     demand_units,
        "nearby_banks":     len(nearby_banks),
        "nearby_donors":    len(nearby_donors),
        "inventory_supply": inventory_supply,
        "donor_supply":     donor_supply,
        "desert_score":     desert_score,
    }


# ---------------------------------------------------------------------------
# 9. Inventory candidate helper (pure — used by choose_lever and the API)
# ---------------------------------------------------------------------------

def collect_inventory_candidates(
    patient: Patient,
    clinic_loc: Optional[Location],
    dataset: CanonicalDataset,
    today: date,
    radius_km: float = _SEARCH_RADIUS_KM,
) -> list[tuple[BloodBank, InventoryUnit, float, int]]:
    """
    Filter and rank PRBC inventory candidates for a patient.

    Returns list of (bank, unit, dist_km, expiry_days) sorted by
    (expiry_days, dist_km, bank_id) — soonest-to-expire first.

    This is the single source of truth for the filter/sort logic.
    choose_lever calls it internally; the API calls it for ranked display
    so both always reflect the same ordering.
    """
    candidates: list[tuple[BloodBank, InventoryUnit, float, int]] = []
    for bank in dataset.blood_banks:
        if not bank.coord_valid:
            continue
        dist = haversine_km(clinic_loc, bank.location) if clinic_loc else 9999.0
        if dist > radius_km:
            continue
        for unit in bank.units:
            if (
                unit.component == Component.PRBC
                and unit.storage_status == "ok"
                and unit.expiry_date >= today
                and abo_rh_compatible(patient, unit)
                and phenotype_antibody_safe(patient, unit)
            ):
                candidates.append((bank, unit, dist, (unit.expiry_date - today).days))
    candidates.sort(key=lambda t: (t[3], t[2], t[0].bank_id))
    return candidates


# ---------------------------------------------------------------------------
# 10. Choose lever
# ---------------------------------------------------------------------------

def choose_lever(
    request: Request,
    dataset: CanonicalDataset,
    today: date,
    radius_km: float = _SEARCH_RADIUS_KM,
) -> dict[str, Any]:
    """
    Deterministic lever selection for a transfusion request.

    Priority:
      (a) Compatible + antibody-safe PRBC inventory within radius_km, sorted
          by soonest expiry first (redistribute to prevent wastage) → "inventory".
      (b) Best ranked eligible + compatible + antibody-safe donor → "donor".
      (c) Fallback → "emergency".

    The LLM will narrate this dict; the decision is made here, deterministically.
    """
    patient = next(
        (p for p in dataset.patients if p.patient_id == request.patient_id), None
    )
    if patient is None:
        return {"error": f"patient {request.patient_id!r} not found"}

    clinic = next(
        (c for c in dataset.clinics if c.clinic_id == patient.clinic_id), None
    )
    clinic_loc = clinic.location if clinic else None

    # ── (a) Inventory ─────────────────────────────────────────────────────
    inv_candidates = collect_inventory_candidates(patient, clinic_loc, dataset, today, radius_km)

    if inv_candidates:
        best_bank, best_unit, best_dist, days_to_expiry = inv_candidates[0]
        dist_km = best_dist if clinic_loc else None

        return {
            "lever":             Lever.INVENTORY,
            "bank_id":           best_bank.bank_id,
            "bank_name":         best_bank.name,
            "unit_abo":          best_unit.abo.value,
            "unit_rh_d":         best_unit.rh_d,
            "unit_expiry":       best_unit.expiry_date.isoformat(),
            "days_to_expiry":    days_to_expiry,
            "distance_km":       round(dist_km, 1) if dist_km is not None else None,
            "inventory_options": len(inv_candidates),
            "reasoning": (
                f"Redistribute near-expiry unit from {best_bank.name} "
                f"({days_to_expiry} day(s) to expiry, "
                f"{round(dist_km, 1) if dist_km else '?'} km away). "
                "Covers patient need AND prevents wastage."
            ),
        }

    # ── (b) Donor ─────────────────────────────────────────────────────────
    nearby_donors = (
        [d for d in dataset.donors
         if haversine_km(clinic_loc, d.location) <= radius_km]
        if clinic_loc else dataset.donors
    )
    ranked = rank_matches(request, nearby_donors, dataset, today)

    if ranked:
        top = ranked[0]
        donor = top["donor"]
        bd = top["breakdown"]
        return {
            "lever":             Lever.DONOR,
            "donor_id":          donor.donor_id,
            "donor_score":       top["score"],
            "breakdown":         bd,
            "candidates_ranked": len(ranked),
            "reasoning": (
                f"No redistribution unit within {radius_km} km. "
                f"Best donor: {donor.donor_id} "
                f"(reliability={bd['reliability']:.3f}, "
                f"distance={bd['proximity_km']} km"
                + (", BONDED" if bd["bonded"] else "")
                + ")."
            ),
        }

    # ── (c) Emergency ─────────────────────────────────────────────────────
    return {
        "lever":     Lever.EMERGENCY,
        "reasoning": (
            "No compatible, antibody-safe inventory or eligible donor found "
            f"within {radius_km} km. Escalate to regional emergency network."
        ),
    }


# ---------------------------------------------------------------------------
# 11. Grid-cell desert aggregation
# ---------------------------------------------------------------------------

def compute_desert_cells(
    dataset: CanonicalDataset,
    today: date,
    radius_km: float = 50.0,
    lead_days: int = 7,
) -> list[dict[str, Any]]:
    """
    Blood-desert metrics aggregated to clinic-level geographic cells.

    Cell definition: one cell per thalassemia centre.  Patients carry clinic_id
    (not individual lat/lng), so the clinic location is the natural demand
    centroid.  9 clinics → 9 cells.

    All gap quantities are in UNITS on both sides.  Donors are NOT folded into
    the score — they are a response lever and appear only as an informational
    clock ingredient.

    Decomposition (must partition D exactly)
    -----------------------------------------
    D            total demand units (sum of units_per_session for due patients)
    S_raw        in-date PRBC units ABO/Rh-compatible for ≥1 due patient
    S_safe       subset that also passes phenotype_antibody_safe for ≥1 patient
    met          min(D, S_safe)
    compat_gap   max(0, min(D, S_raw) − S_safe)  — unmet due to antibody mismatch
    supply_gap   max(0, D − min(D, S_raw))        — unmet because shelf is thin
    desert_score compat_gap + supply_gap
    desert_type  COMPATIBILITY_LIMITED / SUPPLY_LIMITED / MIXED / OK

    Assertion: met + compat_gap + supply_gap == D (always holds algebraically).

    Clock ingredients (no logic built on them here)
    ------------------------------------------------
    nearest_safe_inventory_km   distance to closest bank with ≥1 safe unit
    eligible_matched_donors_nearby  eligible donors who are ABO/Rh + antibody-safe
                                    for ≥1 due patient

    Returns cells sorted by desert_score descending (worst first).
    """
    cells: list[dict[str, Any]] = []

    for clinic in dataset.clinics:
        loc = clinic.location

        due_patients = [
            p for p in dataset.patients
            if p.clinic_id == clinic.clinic_id and forecast_due(p, today, lead_days)[1]
        ]
        D = sum(p.units_per_session for p in due_patients)

        nearby_banks = [
            b for b in dataset.blood_banks
            if b.coord_valid and haversine_km(loc, b.location) <= radius_km
        ]

        # ── Unit-level supply counts ────────────────────────────────────────
        # S_raw: ABO/Rh-compatible for ≥1 due patient (ignores antibody gate)
        # S_safe: also passes phenotype_antibody_safe for ≥1 due patient
        # Both are unit-denominated; no patient-count arithmetic touches them.
        S_raw = 0
        S_safe = 0
        nearest_safe_km: Optional[float] = None

        for b in nearby_banks:
            bank_dist = haversine_km(loc, b.location)
            for u in b.units:
                if not (
                    u.component == Component.PRBC
                    and u.storage_status == "ok"
                    and u.expiry_date >= today
                ):
                    continue
                if not any(abo_rh_compatible(p, u) for p in due_patients):
                    continue
                S_raw += 1
                if any(
                    abo_rh_compatible(p, u) and phenotype_antibody_safe(p, u)
                    for p in due_patients
                ):
                    S_safe += 1
                    if nearest_safe_km is None or bank_dist < nearest_safe_km:
                        nearest_safe_km = bank_dist

        # ── Decompose demand into three additive parts ──────────────────────
        met             = min(D, S_safe)
        compatibility_gap = max(0, min(D, S_raw) - S_safe)
        supply_gap      = max(0, D - min(D, S_raw))

        assert met + compatibility_gap + supply_gap == D, (
            f"Partition violation at {clinic.clinic_id}: "
            f"met={met} + compat={compatibility_gap} + supply={supply_gap} != D={D}"
        )

        desert_score = compatibility_gap + supply_gap

        if desert_score == 0:
            desert_type = "OK"
        elif compatibility_gap > supply_gap:
            desert_type = "COMPATIBILITY_LIMITED"
        elif supply_gap > compatibility_gap:
            desert_type = "SUPPLY_LIMITED"
        else:
            desert_type = "MIXED"

        # ── Clock ingredients ───────────────────────────────────────────────
        nearby_donors = [
            d for d in dataset.donors
            if haversine_km(loc, d.location) <= radius_km
        ]
        eligible_matched_donors = sum(
            1 for d in nearby_donors
            if donor_eligible(d, today)
            and any(
                abo_rh_compatible(p, d) and phenotype_antibody_safe(p, d)
                for p in due_patients
            )
        )

        cells.append({
            "cell_id":                        clinic.clinic_id,
            "lat":                            float(loc.lat),
            "lng":                            float(loc.lng),
            "name":                           clinic.name,
            "patients_due":                   len(due_patients),
            "demand_units":                   D,
            "raw_units":                      S_raw,
            "safe_units":                     S_safe,
            "met":                            met,
            "compatibility_gap":              compatibility_gap,
            "supply_gap":                     supply_gap,
            "desert_score":                   desert_score,
            "desert_type":                    desert_type,
            "nearest_safe_inventory_km":      nearest_safe_km,
            "eligible_matched_donors_nearby": eligible_matched_donors,
        })

    cells.sort(key=lambda c: c["desert_score"], reverse=True)
    return cells
