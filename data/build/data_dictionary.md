# Data Dictionary — HemoGrid v2

## donors.csv
| Column | Type | Source | Description |
|---|---|---|---|
| donor_id | string PK | real | Stable donor ID (DNR-##### format, remapped from raw user_id) |
| abo | string | real/synth | ABO blood group |
| rhd | string | real | RhD: pos/neg (never redrawn) |
| sex | string | real/synth | Sex |
| latitude | float | real/synth | GPS latitude |
| longitude | float | real/synth | GPS longitude |
| donor_type | string | real | Role from hackathon |
| donor_subtype | string | real | Donor subtype |
| eligibility_status | string | real | Current eligibility |
| last_donation_date | ISO date | real | Last donation |
| next_eligible_date | ISO date | real | Next eligible date |
| donation_count | int | real | Total donations |
| active_status | string | real | Platform active status |
| registration_date | ISO date | real | Registration date |
| home_bank_id | string FK→banks | synth | Nearest bank to donor coords |
| is_typed | bool | synth | Full extended phenotype recorded |
| hbs_status | string | synth | HbS status |
| cmv_status | string | synth | CMV serostatus |
| rare_phenotype_flag | bool | synth | Negative for high-prevalence antigen |
| consent_to_recall | bool | synth | Consents to recall |
| is_synthetic | bool | synth | True for augmented rows |
| source | string | meta | real / synthetic |
| email | string | synth | Format-valid fake email |
| phone | string | synth | Format-valid fake phone (+91...) |
| phenotype_C … phenotype_s | string | synth | Extended antigen (14 cols): pos/neg/unknown |

| display_latitude  | float | synth | Jitter-offset lat for map display; real GPS preserved in `latitude` |
| display_longitude | float | synth | Jitter-offset lng for map display; real GPS preserved in `longitude` |
## bags.csv
| Column | Type | Source | Description |
|---|---|---|---|
| bag_id | string PK | synth | Stable bag ID |
| donor_id | string FK→donors | real | Source donor |
| abo | string | real | Denormalized from donor |
| rhd | string | real | Denormalized from donor |
| collection_date | ISO date | synth | Date collected (≤ TODAY-1) |
| expiry_date | ISO date | computed | collection + 42 days |
| status | string | computed | available/expired/reserved/available_tti_pending |
| current_location_id | string FK→banks | synth | Nearest bank to donor coords |
| component | string | synth | packed_rbc / whole_blood |
| leukoreduced | bool | synth | Leukoreduced |
| irradiated | bool | synth | Irradiated |
| washed | bool | synth | Washed |
| cmv_negative | bool | synth | CMV-negative tested |
| tti_screen_status | string | synth | pass / pending |
| volume_ml | int | synth | Volume mL |
| hct_percent | float | synth | Haematocrit % |
| reserved_for_patient_id | string | computed | Set when reserved |
| source | string | meta | derived |

## patients.csv
| Column | Type | Source | Description |
|---|---|---|---|
| patient_id | string PK | real/synth | Stable patient ID (PAT-##### format, remapped from user_id/bridge) |
| source | string | meta | explicit / bridge |
| abo | string | real/synth | ABO blood group |
| rhd | string | real/synth | RhD |
| sex | string | real/synth | Sex |
| latitude | float | real/synth | GPS latitude |
| longitude | float | real/synth | GPS longitude |
| home_facility_id | string FK→facilities | synth | Nearest facility |
| diagnosis | string | synth | thalassemia_major / intermedia |
| extended_match_policy | string | synth | Rh+K |
| units_per_session | int | real/synth | Units per transfusion |
| transfusion_interval_days | int | synth | Days between transfusions |
| last_transfusion_date | ISO date | real/synth | Most recent transfusion |
| expected_transfusion_date | ISO date | real/synth | Next scheduled |
| required_units | int | real/synth | Units required |
| special_irradiated | bool | synth | Needs irradiated product |
| special_cmv_neg | bool | synth | Needs CMV-negative |
| special_washed | bool | synth | Needs washed |
| leukoreduced_standard | bool | const | Always True |
| hbs_required_neg | bool | synth | Must receive HbS-negative |
| has_transfusion_history | bool | real/synth | Prior transfusion history |
| requires_adsorption_workup | bool | computed | Set True for autoantibody |
| age_years | int | synth | Approximate age |
| weight_kg | float | synth | Weight kg |
| pre_transfusion_hb_min_gdl | float | synth | Pre-tx Hb floor |
| post_transfusion_hb_target_gdl | float | synth | Post-tx Hb target |
| sample_collection_window_days | int | synth | Cross-match window |
| is_typed | bool | synth | Extended phenotype typed |
| registration_date | ISO date | real | Registration date |
| email | string | synth | Fake email |
| phone | string | synth | Fake phone |
| phenotype_C … phenotype_s | string | synth | Extended antigen (14 cols) |

| display_latitude  | float | synth | Jitter-offset lat for map display; real GPS preserved in `latitude` |
| display_longitude | float | synth | Jitter-offset lng for map display; real GPS preserved in `longitude` |
## antibodies.csv
| Column | Type | Description |
|---|---|---|
| antibody_id | string PK | Stable ID |
| patient_id | string FK→patients | Patient |
| specificity | string | e.g. anti-K |
| antigen | string | Antigen name |
| type | string | allo / auto |
| status | string | active / historical |
| date_identified | ISO date | When identified |

## potential_donors.csv
| Column | Type | Description |
|---|---|---|
| potential_donor_id | string PK | Stable ID |
| latitude | float | GPS (approx) |
| longitude | float | GPS (approx) |
| abo | string | Self-reported (nullable) |
| rhd | string | Self-reported (nullable) |
| contacted_status | string | not-contacted / contacted / converted |
| signup_date | ISO date | Date registered |
| source | string | synthetic |
| email | string | Fake email |
| phone | string | Fake phone |

## facilities.csv
| Column | Type | Description |
|---|---|---|
| facility_id | string PK | Stable ID |
| name | string | Facility name |
| type | string | clinic / hospital / day-transfusion-center |
| city | string | City |
| latitude | float | GPS |
| longitude | float | GPS |
| bootstrap | bool | True = bootstrapped |
| source | string | clean_file / bootstrap |
| has_own_bank | bool | Has own blood bank |
| associated_bank_id | string FK→banks | Nearest bank |
| processing_capability_irradiate | bool | Can irradiate |
| processing_capability_wash | bool | Can wash |
| daily_transfusion_capacity | int | Approx daily capacity |

## banks.csv
| Column | Type | Description |
|---|---|---|
| bank_id | string PK | Stable ID |
| name | string | Bank name |
| category | string | Government / Private / Charitable |
| address | string | Address |
| city | string | City |
| latitude | float | GPS |
| longitude | float | GPS |
| contact_no | string | Contact number |
| apheresis | string | Apheresis available |
| service_time | string | Operating hours |
| bootstrap | bool | False (all from real file) |
| source | string | real |

## reservations_log.csv
| Column | Type | Description |
|---|---|---|
| reservation_id | string PK | Stable ID |
| donor_id | string FK→donors | Bridge donor |
| patient_id | string FK→patients | Resolved patient (ZERO orphans) |
| status | string | reserved / reserved_pending_fetch |
| bag_id | string FK→bags | Reserved bag (null if pending) |
| expected_txn_date | ISO date | Expected transfusion |
| units_reserved | int | 1 if reserved, 0 if pending |
| source | string | bridge |

## *_field_sources.json
Per-entity provenance map: `column -> {real: n, synth: n}`.
- **real**: non-null in extracted (from hackathon/banks file)
- **synth**: null in extracted, filled by synthesis logic
