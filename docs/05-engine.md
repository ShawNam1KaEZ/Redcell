# 05 — Engine

`hemogrid/engine.py` — 751 lines. Pure functions, no LLM, no randomness, no I/O.

## Named Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `_PRBC_COMPAT` | dict (see below) | Recipient-side ABO compatibility for PRBC |
| `_ANTIGEN_ATTRS` | `("C", "c", "E", "e", "K")` | Antigens tracked for phenotype matching |
| `_W_PROXIMITY` | `0.25` | Proximity weight in donor rank score |
| `_W_RELIABILITY` | `0.30` | Reliability weight in donor rank score |
| `_W_PHENOTYPE` | `0.20` | Phenotype quality weight in donor rank score |
| `_BOND_BONUS` | `0.40` | Blood Bridge bond bonus (deliberately large) |
| `_SEARCH_RADIUS_KM` | `100.0` | Default search radius for candidates |
| `_TRANSPORT_LOCAL_KM` | `5.0` | Distance threshold: ≤ this → tier 0 (local) |
| `_REDISTRIBUTION_SPEED_KMH` | `40.0` | Road transport speed for supply_clock calculation |
| `_DONOR_PIPELINE_DAYS` | `4` | Days for donor contact + consent + travel + donation + testing |

**`_PRBC_COMPAT`** (recipient → acceptable donor/unit ABO groups):
```python
{
    ABOGroup.O:  {ABOGroup.O},
    ABOGroup.A:  {ABOGroup.A, ABOGroup.O},
    ABOGroup.B:  {ABOGroup.B, ABOGroup.O},
    ABOGroup.AB: {ABOGroup.A, ABOGroup.B, ABOGroup.AB, ABOGroup.O},
}
```
Note: this is recipient-centred (who can the recipient receive from). The `SyntheticSource` also has `_ABO_COMPAT` which is donor-centred (who can the donor give to) — these are inverses of each other.

## Internal Helpers

### `_abo_of(donor_or_unit: Union[Donor, InventoryUnit]) → ABOGroup`
Returns `donor.abo_group` for Donor, `unit.abo` for InventoryUnit.

### `_phenotype_of(donor_or_unit: Union[Donor, InventoryUnit]) → Optional[Phenotype]`
Returns `donor.phenotype` for Donor, `unit.phenotype_tags` for InventoryUnit.

### `_parse_antigen(antibody: str) → Optional[str]`
`"anti-K"` → `"K"`. Returns None if format is unrecognised or antigen not in `_ANTIGEN_ATTRS`.

### `_transport_tier(dist_km: float) → int`
`0` if `dist_km <= 5.0` (local), `1` otherwise.

### `_inv_supply_clock(dist_km: float) → float`
`dist_km / (40.0 * 24.0)` = fractional days to deliver by road at 40 km/h.

## Public Functions

### 1. `abo_rh_compatible(recipient: Patient, donor_or_unit: Union[Donor, InventoryUnit]) → bool`

True iff ABO and Rh are compatible for PRBC transfusion.

**ABO rule**: `_abo_of(donor_or_unit) in _PRBC_COMPAT[recipient.abo_group]`

**Rh rule**: If `not recipient.rh_d` (Rh-negative recipient) and `donor_or_unit.rh_d` (Rh-positive source) → `False`. Rh-positive recipients accept both polarities.

This is a hard filter: returns `False` on mismatch.

### 2. `phenotype_antibody_safe(patient: Patient, donor_or_unit: Union[Donor, InventoryUnit]) → bool`

True iff the source is safe given the patient's known alloantibodies.

- If `patient.known_antibodies` is empty → always `True`
- If `_phenotype_of(donor_or_unit)` is `None` and patient has antibodies → `False` (fail-safe)
- For each antibody `ab` in `patient.known_antibodies`:
  - Parse antigen via `_parse_antigen(ab)` (e.g., `"anti-K"` → `"K"`)
  - If antigen not recognised → continue (skip)
  - `antigen_status = getattr(src_ph, ag, None)`
  - If `antigen_status is None` → `False` (antigen not typed → fail-safe reject)
  - If `antigen_status == True` → `False` (source is antigen-positive → unsafe)
- Returns `True` only if all antibody checks pass

**Critical**: Unknown phenotype (`None`) combined with any antibody always returns `False`. This is why the 60% of synthetic PRBC units with `phenotype_tags=None` cannot be used for any alloimmunized patient.

### 3. `phenotype_match_quality(patient: Patient, donor_or_unit: Union[Donor, InventoryUnit]) → float`

Normalized concordance score `[0, 1]` on `{C, c, E, e, K}` for ranking purposes (not a safety filter).

- Returns `0.0` if either phenotype is `None`
- Excludes antigens already handled by the antibody safety gate (`ab_antigens` set)
- Counts matching antigen values over total typed antigen pairs
- Formula: `matches / total` where `total` is the count of antigens where both patient and source have non-None values

### 4. `donor_eligible(donor: Donor, today: date) → bool`

True iff:
1. `donor.consent.contactable == True`
2. `donor.last_donation_date is None` OR `(today - donor.last_donation_date).days >= 90`

The 90-day interval is the NBTC (National Blood Transfusion Council) deferral rule for whole blood donation.

### 5. `haversine_km(loc_a: Location, loc_b: Location) → float`

Great-circle distance in kilometres using the haversine formula with `R = 6371.0` km.

```python
dlat = lat2 - lat1
dlon = lon2 - lon1
a = sin(dlat/2)^2 + cos(lat1) * cos(lat2) * sin(dlon/2)^2
dist = R * 2 * asin(sqrt(a))
```

### 6. `forecast_due(patient: Patient, today: date, lead_days: int = 7) → tuple[date, bool]`

```
next_need_date = patient.last_transfusion_date + timedelta(days=patient.transfusion_interval_days)
is_due_soon    = 0 <= (next_need_date - today).days <= lead_days
```

Returns `(next_need_date, is_due_soon)`. Note: `lead_days=7` is the default used everywhere.

### 7. `rank_matches(request: Request, candidate_donors: list[Donor], dataset: CanonicalDataset, today: date) → list[dict[str, Any]]`

Filter and rank donors for a transfusion request.

**Filters applied** (all three must pass):
1. `donor_eligible(donor, today)`
2. `abo_rh_compatible(patient, donor)`
3. `phenotype_antibody_safe(patient, donor)`

**Scoring formula**:
```
proximity_score = 1.0 / (1.0 + dist_km / 50.0)
score = _W_PROXIMITY * proximity_score
      + _W_RELIABILITY * donor.reliability_score
      + _W_PHENOTYPE * phenotype_match_quality(patient, donor)
      + bond_bonus   # _BOND_BONUS (0.40) if donor.linked_patients contains patient_id, else 0
```

The bond bonus (0.40) is deliberately large — it ensures a bonded matched donor almost always outranks an unrelated donor.

**Returns**: List of dicts sorted by `score` descending. Each dict:
```python
{
    "donor": Donor,
    "score": float (rounded to 4 decimal places),
    "breakdown": {
        "proximity_km": float,
        "proximity_score": float,
        "reliability": float,
        "phenotype_quality": float,
        "bonded": bool,
        "bond_bonus": float,
    }
}
```

**Important**: `rank_matches` returns **donor-denominated** results (one entry per eligible donor), not unit-denominated. This is different from inventory candidates which are unit-denominated.

### 8. `blood_desert_score(clinic_id: str, dataset: CanonicalDataset, today: date, radius_km: float = 50.0, lead_days: int = 7) → dict[str, Any]`

Note: This function exists but is NOT called by the API or agents. The API uses `compute_desert_cells()` instead. `blood_desert_score()` uses a simpler per-patient search (not the decomposition model) and counts inventory and donor supply separately.

### 9. `collect_inventory_candidates(patient: Patient, clinic_loc: Optional[Location], dataset: CanonicalDataset, today: date, radius_km: float = _SEARCH_RADIUS_KM) → list[tuple[BloodBank, InventoryUnit, float, int]]`

Filter and rank PRBC inventory candidates.

**Filters**:
1. `bank.coord_valid == True`
2. `haversine_km(clinic_loc, bank.location) <= radius_km`
3. `unit.component == Component.PRBC`
4. `unit.storage_status == "ok"`
5. `unit.expiry_date >= today`
6. `abo_rh_compatible(patient, unit)`
7. `phenotype_antibody_safe(patient, unit)`

**Sort key**: `(transport_tier, expiry_days, dist_km, bank.bank_id)` — ascending (soonest expiry first within each tier).

**Returns**: `list[tuple[BloodBank, InventoryUnit, float, int]]` where each tuple is `(bank, unit, dist_km, expiry_days)`.

**Important**: Returns **unit-denominated** results (one entry per compatible unit, not per bank). Multiple units from the same bank produce multiple entries.

### 10. `choose_lever(request: Request, dataset: CanonicalDataset, today: date, radius_km: float = _SEARCH_RADIUS_KM) → dict[str, Any]`

Deterministic lever selection. Priority: inventory → donor → emergency.

**Step (a): Inventory**
- Calls `collect_inventory_candidates(patient, clinic_loc, dataset, today, radius_km)`
- If non-empty: returns `Lever.INVENTORY` dict with `bank_id`, `bank_name`, `unit_abo`, `unit_rh_d`, `unit_expiry`, `days_to_expiry`, `distance_km`, `inventory_options` (count), `need_clock_days`, `supply_clock_days`, `transport_tier`, `deliverable`

**Step (b): Donor**
- `nearby_donors` = donors within `radius_km` of clinic
- Calls `rank_matches(request, nearby_donors, dataset, today)`
- If ranked list non-empty: returns `Lever.DONOR` dict with `donor_id`, `donor_score`, `breakdown`, `candidates_ranked`, `need_clock_days`, `supply_clock_days` (= `_DONOR_PIPELINE_DAYS = 4`), `deliverable` (= `_DONOR_PIPELINE_DAYS <= need_clk`)

**Step (c): Emergency**
- Returns `Lever.EMERGENCY` dict with no target, `deliverable=False`

**`need_clock_days`**: `(request.needed_by_date - today).days`

**`supply_clock_days` for inventory**: `dist_km / (40.0 * 24.0)` = hours to deliver / 24. Very small for local banks (e.g., 0.7 km → `0.000729` days).

**`deliverable`**: `supply_clock_days <= need_clock_days`.

### 11. `certified_inventory_candidates(patient: Patient, clinic_loc: Optional[Location], dataset: CanonicalDataset, today: date, radius_km: float = _SEARCH_RADIUS_KM) → list[dict[str, Any]]`

Engine-certified SAFE + DELIVERABLE inventory candidates. Wraps `collect_inventory_candidates`, applies the deliverability filter (`supply_clock <= need_clock`), and enriches each entry with tier/clock fields.

This is the only candidate set that `_agent_select()` may choose from (Lock 1 guardrail).

**Returns list of dicts** (not tuples):
```python
{
    "bank_id": str,
    "bank_name": str,
    "abo": str,
    "rh_d": bool,
    "dist_km": float,
    "expiry_days": int,
    "supply_clock_days": float,
    "need_clock_days": int,
    "transport_tier": int,
    "deliverable": True,  # always True in this list
}
```

### 12. `classify_desert_nature(score: int, desert_type: str) → dict`

```python
if score == 0:   return {"classification": "OK"}
if desert_type == "COMPATIBILITY_LIMITED" and score >= 10:
                 return {"classification": "CHRONIC"}
return           {"classification": "ACUTE"}
```

The `CHRONIC` classification requires both `COMPATIBILITY_LIMITED` type AND `score >= 10`. All other non-zero scores → `ACUTE`.

### 13. `compute_desert_cells(dataset: CanonicalDataset, today: date, radius_km: float = 50.0, lead_days: int = 7) → list[dict[str, Any]]`

Blood-desert metrics aggregated to clinic-level geographic cells. This is the main function called by `/api/deserts`.

**Cell definition**: One cell per clinic. All patients with `clinic_id == clinic.clinic_id` belong to that cell.

**Due patients**: `forecast_due(p, today, lead_days)[1] == True` (is_due_soon within lead_days).

**Demand** `D`: `sum(p.units_per_session for p in due_patients)`

**`S_raw`** (unit count): In-date PRBC units at banks within `radius_km` that pass `abo_rh_compatible` for at least one due patient. Ignores antibody gate. Unit-denominated.

**`S_safe`** (unit count): Subset of `S_raw` that also passes `phenotype_antibody_safe` for at least one due patient.

**Decomposition** (provably partitions D):
```
met              = min(D, S_safe)
compatibility_gap = max(0, min(D, S_raw) - S_safe)
supply_gap        = max(0, D - min(D, S_raw))
desert_score      = compatibility_gap + supply_gap
assert met + compatibility_gap + supply_gap == D
```

**Desert type**:
- `desert_score == 0` → `"OK"`
- `compatibility_gap > supply_gap` → `"COMPATIBILITY_LIMITED"`
- `supply_gap > compatibility_gap` → `"SUPPLY_LIMITED"`
- `compatibility_gap == supply_gap` → `"MIXED"`

**Classification**: `classify_desert_nature(desert_score, desert_type)["classification"]`

**Clock ingredients** (informational only, no logic built on them here):
- `nearest_safe_inventory_km`: distance to closest bank with ≥1 safe unit
- `eligible_matched_donors_nearby`: count of donors within `radius_km` who are eligible AND (ABO/Rh + antibody-safe) for at least one due patient

**Returns**: List of cell dicts sorted by `desert_score` descending (worst first).

**Note on `blood_desert_score()` vs `compute_desert_cells()`**: They use different supply-counting logic. `blood_desert_score()` counts per-patient (one compatible source satisfies one patient's demand); `compute_desert_cells()` counts all unit-level matches (S_raw and S_safe). Only `compute_desert_cells()` is used in the production API.

## The Blood Desert Model: Current Cell Scores

**UNVERIFIED**: The exact current scores depend on `date.today()` at runtime (which patients are due) and the exact seed=42 inventory generated. The golden assertion from `CLAUDE.md` is that CLN-HYD-01 should have a score of 16 and `CHRONIC` classification. The LLM fallback in `llm.py` hardcodes this value in the `narrate_structural_recommendation()` golden intercept. Whether the live engine produces exactly score=16 on any given day depends on how many of the 12 HYD stressed patients (PAT-0301..0312) are due within the 7-day window on that day.

## Candidate Denominations: Unit vs Bank

This is a significant design consideration:

| Function | Returns | Denominated by |
|----------|---------|---------------|
| `collect_inventory_candidates()` | `list[tuple[BloodBank, InventoryUnit, float, int]]` | Unit — each compatible unit is a separate entry |
| `certified_inventory_candidates()` | `list[dict]` | Unit — same as above, filtered and enriched |
| `rank_matches()` | `list[dict]` | Donor — each eligible donor is one entry |
| `compute_desert_cells()` | S_raw, S_safe counts | Unit — total unit counts across all banks |

In `get_match()` (API), `ranked_inventory` is built from `collect_inventory_candidates()[:10]` — 10 units, which may include multiple units from the same bank. The frontend's "Show details" table de-duplicates by `bank_id` for display (showing count of units per bank), but the underlying ranked list is unit-denominated. This is called out as a fragility in [docs/10](10-data-flow-and-known-issues.md).
