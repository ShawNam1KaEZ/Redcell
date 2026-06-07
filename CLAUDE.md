# CLAUDE.md — HemoGrid Thalassemia Matching System

Project memory for Claude Code. Read before any build step. Keep `RANDOM_SEED=42`, `TODAY=2026-06-06`.

## What this is
Donor–patient matching for thalassemia patients (Hyderabad/Telangana). Differentiator = proactive
**extended-phenotype matching**. Stages: datasets ✅ → map ✅ → **matching engine (current)** →
simulation → redistribution (deferred).

## Repo / paths
- Build outputs: `./data/build/` (the canonical dataset — treat as source of truth).
- CSVs: `donors.csv, patients.csv, bags.csv, antibodies.csv, reservations_log.csv,
  potential_donors.csv, facilities.csv, banks.csv`.
- Provenance: `*_field_sources.json` (per-column real/synth counts), `data_dictionary.md`.
- Report: `REPORT.md` (RUN_ID-stamped on line 1), run history: `_run_history.json`.
- Map: `./data/build/map/{map_data.json,index.html}` — view via
  `cd ./data/build/map && python -m http.server 8000`.
- Raw inputs: `./data/Dataset.csv` (7033×33), `./data/blood-banks.xls`.

## Current dataset facts (post-#3f, RUN_ID seed42-20260606-8330edb7)
- donors 4439 (85% typed) · patients 164 (84 explicit + 80 bridge, 100% typed) · bags 2417
  (available 536 / reserved 304 / expired 1559 / tti 18) · antibodies 51 · reservations 909
  (resolved 304 / pending_fetch 605) · banks 149 (13 with live inventory) · facilities 21.
- IDs are `DNR-#####` / `PAT-#####`. No `\x` anywhere (asserts enforce).
- 84.5% of available bags trace to a typed donor.
- `expected_transfusion_date` is forward-dated [2026-06-07, 2026-07-03].

## INVARIANTS — never break these (asserts depend on them)
1. **Inventory is a derived query, never a stored table/column.**
   `available = bags[current_location_id==X & status=='available' & expiry_date>=TODAY]`.
2. **Bags carry ABO/Rh only — never `phenotype_*` columns.** Extended phenotype lives on the donor.
3. **Matcher uses real `latitude`/`longitude`.** `display_latitude/longitude` are MAP-ONLY (jitter).
4. **Antibody safety is universal:** never issue an antigen-positive unit against any antibody
   (allo+auto, active+historical). Auto antibody ⇒ `requires_adsorption_workup=True` ⇒ never
   auto-issue (route to emergency/review tier).
5. **Untyped donor (`phenotype=unknown`)** can never be an exact match, and is **excluded for
   immunized patients** (cannot prove antigen-negativity). Usable (flagged) for non-immunized.
6. **Primary keys unique; zero orphaned FKs.** bags→donors, bags→banks∪facilities,
   patients→facilities, donors→banks, antibodies→patients, reservations→patients/donors/bags,
   reserved bags→patients.
7. **`expiry_date == collection_date + 42`**; `max(collection_date) <= TODAY-1`; `status==available
   ⇒ expiry >= TODAY`.
8. **Emails/phones format-valid, globally unique.** Phones `^\+91[6-9]\d{9}$`.
9. Keep entities **mutation-friendly** for the sim: stable PKs, no baked-in derived values, dates as
   real date fields.

## Matching engine (current build target)
Gate→rank→tier. Gates: (1) component+requirements+available+reachable; (2) ABO/Rh compatible
(lattice, D− patient→D− only); (3) antibody-exclusion (universal; untyped excluded for immunized);
(4) phenotype rank. Tiers:
- **G1 Exact** — typed donor, ABO identical, all tested antigens match, antibody-safe. Untyped never G1.
- **G2 Ranked compatible** — compatible + Rh+K match + antibody-safe. Untyped donors live here,
  flagged "phenotype unconfirmed," ranked below typed. Sort: phenotype concordance → typed>untyped →
  distance → soonest expiry.
- **G3 Emergency / least-incompatible** — only when G1+G2 empty or auto/panreactive. Never auto-issue.
- **Excluded** — with reason code.
Output: `match(patient_id) -> {G1,G2,G3,excluded}`, deterministic, inventory derived live.
The 3 immunized patients with zero compatible bags must land in G3, not error.

## Conventions
- Python + pandas. Config knobs at top of every script. Asserts loud (raise), never swallowed.
- Reports: ALWAYS overwrite (open 'w'), stamp RUN_ID line 1, regenerate numbers from live
  dataframes (no hand-typed constants), re-read after write and assert on-disk RUN_ID == in-memory.
- Every build prints to stdout: RUN_ID, headline counts, assert pass/fail summary.

## Do NOT relitigate
Donor-centric matching · thin bag layer · bag = ABO/Rh only · inventory = query · 85% donor /
100% patient typing · keep the untyped tail · real-vs-display coords split · Rh+K policy floor.

## Known cosmetic debt (fix when convenient, not blocking)
- REPORT.md §A: broken "previous report incorrectly said 33; actual is 33" line.
- REPORT.md §A: "Bridge reservation rows: 786" not reconciled to 909 (786 links × required units).

## Workflow
Planning assistant writes prompts → run here → paste output back → reviewed against
`HANDOFF_matching_engine.md` before next step. One buildable artifact per prompt.