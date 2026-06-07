RUN_ID: seed42-20260606-8330edb7

# HemoGrid Thalassemia Dataset Build Report (v2)

Generated: 2026-06-06  |  RANDOM_SEED: 42

---

## A. Provenance & Row Reconciliation
- Input: `C:\Users\Shawn\hackathon-project\data\Dataset.csv` — shape (7033, 33)
- Blood banks: `C:\Users\Shawn\hackathon-project\data\blood-banks.xls` — shape (2823, 27)
- Facilities: bootstrapped
- Output: `C:\Users\Shawn\hackathon-project\data\build`

**Shape:** (7033, 33) — previous report incorrectly said 33; actual is 33 columns.
**Unmapped columns (not in extraction pipeline):** `['role_status', 'bridge_status', 'last_contacted_date', 'cycle_of_donations', 'total_calls', 'frequency_in_days', 'status_of_bridge', 'status', 'donated_earlier', 'last_bridge_donation_date', 'calls_to_donations_ratio', 'inactive_trigger_comment']`

### Input row disposition
| Role | Count |
|---|---|
| Guest | 2420 |
| Emergency Donor | 2385 |
| Bridge Donor | 2061 |
| Patient | 84 |
| Volunteer | 83 |
| **TOTAL** | **7033** |

- Donor rows (Emergency+Bridge, after dedup): **4439**
- Explicit patients (role=Patient): **84**
- Bridge patients (unique bridge_id): **80**
- Bridge reservation rows: **786**
- Dropped (guest/other): **2503**
- bridge_id ∩ patient_ids overlap: 0 (separate namespaces)

### FIX-0 verdict
- Bridge rows carry patient fields: **yes**
- Detected columns: `['bridge_blood_group', 'quantity_required', 'expected_next_transfusion_date', 'last_transfusion_date']`

### Column Mapping
| Raw Column | Canonical Name | Status |
|---|---|---|
| blood_group | abo + rhd | FOUND |
| latitude | latitude | FOUND |
| longitude | longitude | FOUND |
| role | donor_type | FOUND |
| donor_type | donor_subtype | FOUND |
| eligibility_status | eligibility_status | FOUND |
| next_eligible_date | next_eligible_date | FOUND |
| donations_till_date | donation_count | FOUND |
| user_donation_active_status | active_status | FOUND |
| last_donation_date | last_donation_date | FOUND |
| bridge_id | build-time key (not persisted) | FOUND |
| quantity_required | required_units | FOUND |
| expected_next_transfusion_date | expected_transfusion_date | FOUND |
| last_transfusion_date | last_transfusion_date | FOUND |
| gender | sex | FOUND |
| registration_date | registration_date | FOUND |
| bridge_blood_group | patient abo+rhd (bridge) | FOUND |

## B. Row Counts
| Table | Rows | Source breakdown |
|---|---|---|
| donors | 4439 | real=4439, synthetic=0 |
| bags | 2417 | derived |
| patients | 164 | explicit=84, bridge=80 |
| antibodies | 51 | synthesized |
| potential_donors | 400 | synthetic |
| facilities | 21 | bootstrap |
| banks | 149 | real |
| reservations_log | 909 | bridge |

**Donors typed/untyped:** typed=3775, untyped=664

### Patients by source
| Source | Count |
|---|---|
| explicit (role=Patient) | 84 |
| bridge (unique bridge_id) | 80 |
| **Total** | **164** |

## C. EXTRACT vs FILL — Per Entity (top fields)

### Donors
| Column | Real | Synth |
|---|---|---|
| donor_id | 4439 | 0 |
| abo | 4334 | 105 |
| rhd | 4334 | 105 |
| sex | 2089 | 2350 |
| latitude | 4439 | 0 |
| longitude | 4439 | 0 |
| donor_type | 4439 | 0 |
| donor_subtype | 4439 | 0 |
| eligibility_status | 4439 | 0 |
| donation_count | 4439 | 0 |

### Patients
| Column | Real | Synth |
|---|---|---|
| patient_id | 164 | 0 |
| abo | 164 | 0 |
| rhd | 164 | 0 |
| sex | 79 | 85 |
| latitude | 84 | 80 |
| longitude | 84 | 80 |
| last_transfusion_date | 79 | 85 |
| expected_transfusion_date | 159 | 5 |
| source | 164 | 0 |
| home_facility_id | 0 | 164 |

### Bags
| Column | Real | Synth |
|---|---|---|
| bag_id | 2417 | 0 |
| donor_id | 2417 | 0 |
| abo | 2417 | 0 |
| rhd | 2417 | 0 |
| collection_date | 0 | 2417 |
| expiry_date | 0 | 2417 |
| status | 0 | 2417 |
| current_location_id | 0 | 2417 |
| component | 0 | 2417 |
| leukoreduced | 0 | 2417 |

### Reservations
| Column | Real | Synth |
|---|---|---|
| reservation_id | 0 | 909 |
| donor_id | 909 | 0 |
| patient_id | 909 | 0 |
| status | 0 | 909 |
| expected_txn_date | 909 | 0 |
| units_reserved | 909 | 0 |
| source | 0 | 909 |
| bag_id | 0 | 304 |

### Banks
| Column | Real | Synth |
|---|---|---|
| bank_id | 149 | 0 |
| name | 149 | 0 |
| address | 149 | 0 |
| city | 149 | 0 |
| latitude | 149 | 0 |
| longitude | 149 | 0 |
| bootstrap | 149 | 0 |
| source | 149 | 0 |

## D. Antigen Prevalence: Achieved vs Makroo Target
| Antigen | Target | Donors | Flag | Patients | Flag |
|---|---|---|---|---|---|
| C | 0.870 | 0.903 | * | 0.921 | * |
| c | 0.580 | 0.612 | * | 0.616 | * |
| E | 0.200 | 0.206 |  | 0.146 | * |
| e | 0.980 | 0.994 |  | 1.000 |  |
| K | 0.035 | 0.037 |  | 0.043 |  |
| k | 1.000 | 1.000 |  | 1.000 |  |
| Jka | 0.815 | 0.839 |  | 0.884 | * |
| Jkb | 0.674 | 0.709 | * | 0.659 |  |
| Fya | 0.874 | 0.902 |  | 0.927 | * |
| Fyb | 0.576 | 0.605 |  | 0.598 |  |
| M | 0.887 | 0.910 |  | 0.945 | * |
| N | 0.654 | 0.666 |  | 0.598 | * |
| S | 0.548 | 0.571 |  | 0.549 |  |
| s | 0.887 | 0.915 |  | 0.915 |  |
*(* = >3pp deviation from target)*

## E. ABO/Rh Distribution

### Donors
| ABO | Rh | Count |
|---|---|---|
| A | neg | 48 |
| A | pos | 778 |
| AB | neg | 35 |
| AB | pos | 277 |
| B | neg | 88 |
| B | pos | 1300 |
| O | neg | 118 |
| O | pos | 1795 |

### Patients
| ABO | Rh | Count |
|---|---|---|
| A | neg | 2 |
| A | pos | 15 |
| AB | neg | 2 |
| AB | pos | 10 |
| B | neg | 2 |
| B | pos | 61 |
| O | neg | 4 |
| O | pos | 68 |

## F. Antibody Summary
- Patients immunized: 30 / 164 (18.3%)
- Total antibodies: 51
  - allo: 45
  - auto: 6
- Historical: 19
- Patients requiring adsorption workup: 6
- Patients with historical anti-Jka: 3 (evanescence guarantee: ≥2)

### Specificity Histogram
| Specificity | Count |
|---|---|
| anti-K | 20 |
| anti-E | 16 |
| anti-c | 6 |
| anti-Jka | 4 |
| anti-e | 3 |
| anti-Fya | 2 |

## G. Bag / Inventory Summary
| Status | Count |
|---|---|
| expired | 1559 |
| available | 536 |
| reserved | 304 |
| available_tti_pending | 18 |

- Available bags with extended-typed donor: 84.5%
- Oldest collection_date: 2020-03-01
- Newest collection_date: 2026-06-05 (clamped to ≤ 2026-06-05)
- Pending-fetch reservations: 605

### Available Bags by Bank (top 10)
| Bank ID | Available Bags |
|---|---|
| BNK0057 | 320 |
| BNK0031 | 178 |
| BNK0098 | 23 |
| BNK0020 | 5 |
| BNK0034 | 2 |
| BNK0035 | 1 |
| BNK0048 | 1 |
| BNK0071 | 1 |
| BNK0072 | 1 |
| BNK0086 | 1 |

## H. Honest Match-Coverage Probe
*(Immunized patients require TYPED-donor bags; untyped-donor bags excluded for them)*
| Metric | All patients | Immunized | Non-immunized |
|---|---|---|---|
| Count | 164 | 30 | 134 |
| With ≥1 compatible bag | 161 | 27 | 134 |
| With ZERO compatible bags | 3 | 3 | 0 |
| Median compatible bags | 222 | 143 | 333 |
| 10th pct compatible | 30 | 2 | 222 |

RECOMMENDATION: Coverage adequate — fewer than 10% of patients have zero matches.

## I. BEFORE → AFTER Delta
| Metric | Before | After | Delta |
|---|---|---|---|
| patients (total) | 164 | 164 | +0 |
| explicit patients | N/A | 84 | — |
| bridge patients | N/A | 80 | — |
| available bags | 381 | 536 | +155 |
| max collection_date | 2026-06-05 | 2026-06-05 | clamped |
| pending-fetch reservations | 794 | 605 | -189 |
| orphaned reservations | N/A | 0 | asserted |
| prevalence flags (donors) | 3 | 3 | — |

## J. Stage-9 Assert Results
| Assert | Status | Detail |
|---|---|---|
| 1: RhD field present and valid on donors | **PASS** | rhd values: {'pos': 4150, 'neg': 289} |
| 2: No antithetical double-negatives outside allowed rate | **PASS** | all pairs OK |
| 3: Every alloantibody: patient antigen-negative AND has txn history | **PASS** | OK |
| 4: Every autoantibody: patient antigen-positive AND requires_adsorption_workup=True | **PASS** | OK |
| 5: Historical antibodies present and retained | **PASS** | Historical count: 19 |
| 6: Bags carry ABO/Rh only — no phenotype_ columns | **PASS** | OK |
| 7: No stored inventory table or per-bank count columns | **PASS** | OK |
| 8a: All emails pass regex | **PASS** | Total: 5003, invalid: 0 |
| 8b: All phones match regex | **PASS** | Invalid: 0 |
| 8c: Emails globally unique | **PASS** | Total: 5003, unique: 5003 |
| 8d: Phones globally unique | **PASS** | Total: 5003, unique: 5003 |
| 9: Potential donors — no phenotype columns, not in bags | **PASS** | OK |
| 10a: Live available inventory non-empty | **PASS** | Available: 536 |
| 10b: Available inventory spread >1 bank | **PASS** | Banks with available: 13 |
| 11a: Primary keys unique | **PASS** | donor_id, bag_id, patient_id, pd_id all unique |
| 11b: No derived per-entity aggregate count columns | **PASS** | OK |
| 12: bags.donor_id ∈ donors | **PASS** | Missing: 0 |
| 13: bags.current_location_id ∈ banks∪facilities | **PASS** | Missing: 0 |
| 14: patients.home_facility_id ∈ facilities | **PASS** | Missing: 0 |
| 15: donors.home_bank_id ∈ banks | **PASS** | Missing: 0 |
| 16: antibodies.patient_id ∈ patients | **PASS** | Missing: 0 |
| 17: reservations.patient_id ∈ patients (ZERO orphans) | **PASS** | Orphans: 0 |
| 18: reservations.donor_id ∈ donors | **PASS** | Missing: 0 |
| 19: non-null reservations.bag_id ∈ bags | **PASS** | Missing: 0 |
| 20: reserved bags have reserved_for_patient_id ∈ patients | **PASS** | Missing: 0 |
| 21: all banks have valid lat/lng | **PASS** | lat_ok=True, lon_ok=True |
| 22: max(bags.collection_date) <= TODAY-1 | **PASS** | max=2026-06-05, limit=2026-06-05 |
| 23: expiry == collection + RBC_SHELF_LIFE_DAYS for all bags | **PASS** | Mismatches: 0 |
| 24: status=available implies expiry >= TODAY | **PASS** | Violations: 0 |
| 25: ≥2 patients have historical anti-Jka | **PASS** | Patients with historical anti-Jka: 3 |
| 26: all entities have field-source maps (verified after write) | **PASS** | all 7 field-source JSON files written |
| 27: pending-fetch donors genuinely have no available bags | **PASS** | OK |
| 28: donor is_typed fraction in [0.83, 0.87] (FIX 6) | **PASS** | Actual: 0.850 |
| 29: all patients is_typed=True | **PASS** | Untyped: 0 |
| 30: no id in any table contains '\x' (FIX 2) | **PASS** | OK |
| 31: 0 patients have expected_transfusion_date <= TODAY (FIX 1) | **PASS** | Past/today dates: 0  Range: [2026-06-07, 2026-07-03] |

## K. Config Echo
| Knob | Value |
|---|---|
| RANDOM_SEED | 42 |
| TODAY | 2026-06-06 |
| DONOR_TYPED_FRACTION | 0.85 |
| PATIENT_TYPED_FRACTION | 1.0 |
| PATIENT_ALLOIMMUNIZED_RATE | 0.18 |
| AUTO_AMONG_IMMUNIZED_RATE | 0.12 |
| HISTORICAL_ANTIBODY_RATE | 0.3 |
| THAL_MAJOR_FRACTION | 0.7 |
| FRESH_COLLECTION_FRACTION | 0.6 |
| RBC_SHELF_LIFE_DAYS | 42 |
| AUGMENT_DONORS_TO | None |
| POTENTIAL_DONOR_COUNT | 400 |
| WHOLE_BLOOD_FRACTION | 0.08 |
| TTI_PENDING_FRACTION | 0.03 |
| MIN_HISTORICAL_JKA | 2 |
## L. Stage-A Jitter — Display Coordinates
Generated: 2026-06-06 23:14  |  RANDOM_SEED: 42

| Entity   | Distinct (lat,lng) BEFORE | Distinct (display_lat,lng) AFTER |
|---|---|---|
| donors   | 131 | 4439 |
| patients | 85 | 164 |

- Rayleigh sigma = 300 m (mode = 300 m), hard cap = 700 m
- Assert donors distinct > 4000: PASS
- Assert max displacement <= 1.0 km: PASS (donors + patients)
- New columns added: `display_latitude`, `display_longitude` in donors.csv and patients.csv
