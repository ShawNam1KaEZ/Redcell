# 10 — Data Flow and Known Issues

## Complete Data Path (Hop-by-Hop)

### Hop 1: Raw Files → DataSource

| Source file | Symbol | Loaded by |
|-------------|--------|----------|
| `data/blood-banks.xls` | `SyntheticSource._load_blood_banks()` | `hemogrid/sources/synthetic_source.py:211` |
| `data/uci_blood_transfusion.csv` | `SyntheticSource._build_reliability_scorer()` | `hemogrid/sources/synthetic_source.py:305` |
| `data/uci_blood_transfusion.csv` | `SyntheticSource._generate_donors()` | `hemogrid/sources/synthetic_source.py:383` |
| `newdata/Hackathon Data_5000.csv` | `LiveHybridSource._parse_hackathon_csv()` | `hemogrid/sources/live_source.py:321` |
| `newdata/BW_Sample_Data_Updated_v3.xlsx - user_data.csv` | `LiveHybridSource._parse_user_csv()` | `hemogrid/sources/live_source.py:484` |
| ~~`newdata/cleaned_thalassemia_data.csv`~~ | **NOTHING** — not referenced anywhere | — |

### Hop 2: DataSource → `CanonicalDataset`

`SyntheticSource.load()` or `LiveHybridSource.load()` returns a `CanonicalDataset` with:
- `blood_banks: list[BloodBank]`
- `donors: list[Donor]`
- `patients: list[Patient]`
- `clinics: list[Clinic]`
- `requests: []` (always empty from source)

### Hop 3: `CanonicalDataset` → `app.state`

In `hemogrid/api/main.py:lifespan()` (lines 344–385):
```python
ds = _build_dataset()
bank_repo: InMemoryRepository[BloodBank] = InMemoryRepository(BloodBank)
for bank in ds.blood_banks: bank_repo.save(bank.bank_id, bank)
# ... same for patients, donors, clinics
app.state.bank_repo    = bank_repo
app.state.patient_repo = patient_repo
app.state.donor_repo   = donor_repo
app.state.clinic_repo  = clinic_repo
app.state.dataset      = ds    # full dataset for batch engine calls
app.state.stats        = DatasetStats(...)
```

`app.state` is populated once at startup and never refreshed during the server's lifetime.

### Hop 4: `app.state` → Engine

Engine calls in endpoints always use `app.state.dataset` (the full `CanonicalDataset`):
- `engine.compute_desert_cells(app.state.dataset, date.today(), ...)` — `/api/deserts`
- `engine.choose_lever(req, dataset, today)` where `dataset = app.state.dataset` — `/match`, `/propose`, `/activity`
- `engine.collect_inventory_candidates(patient, clinic_loc, dataset, today)` — same endpoints
- `engine.rank_matches(req, nearby_donors, dataset, today)` — same

The `patient` objects in engine calls come from `app.state.dataset.patients` (not from `patient_repo.get(id)`):
```python
# In get_match():
patient = next(p for p in dataset.patients if p.patient_id == patient_id)
```
The repo is only used for existence checks (404 guard via `patient_repo.get(patient_id)`).

### Hop 5: Engine → API Response DTOs

Each endpoint converts engine output to DTOs:
- `choose_lever()` → `MatchResult` (serialised in `get_match()`)
- `compute_desert_cells()` cells → `CellDesertScore[]` + LLM narration (in `list_deserts()`)
- Graph `trace` events → `ActivityEventOut[]` (in `get_activity()`, `propose()`, `approve()`)

### Hop 6: API → `api.ts` Fetch Functions

`frontend/src/api.ts` defines typed fetch functions. Each function maps to one endpoint:
- `fetchDeserts()` → `GET /api/deserts`
- `fetchMatch(patientId)` → `GET /api/patients/{id}/match`
- `proposeAction(patientId)` → `POST /api/patients/{id}/propose`
- etc.

### Hop 7: `api.ts` → React State in `MapView.tsx`

```
fetchHealth()       → state: liveMode, healthLoaded
fetchBanks()        → state: banks
fetchDeserts()      → state: deserts
fetchDuePatients()  → state: patients
fetchMatch()        → state: matchResult
proposeAction()     → state: proposalResp
approveAction()     → state: approveResp
fetchDemoStatuses() → state: patientStatuses
```

### Hop 8: React State → UI Components

| State variable | Component/element that renders it |
|---------------|----------------------------------|
| `banks` | `Marker` components on Leaflet map |
| `deserts` | `CircleMarker` components on Leaflet map; left panel drill-down table |
| `patients` | Patient rows in left panel (when cell selected) |
| `matchResult` | Match result card in left panel (under patient list) |
| `proposalResp` | HITL approval card / activity trace in right panel |
| `approveResp` | Approved/declined result in right panel |
| `liveMode` | Map center/zoom, bank label, bank filter |
| `dynMet`, `dynSupplyGap`, etc. | Desert metrics table in left panel (local overlay) |
| PAT-0001 module | **Hardcoded values** (DON-0002, 2.4 km, 0.9141, 4 days) — NOT from React state |

---

## Investigation: "New Data Not Reflecting in UI"

The symptom: new data was added but does not appear to affect the UI. Below are all suspected breakpoints, ranked by likelihood.

### Candidate 1 (HIGH): `cleaned_thalassemia_data.csv` is never read

**Location**: `newdata/cleaned_thalassemia_data.csv`

The file exists (7,033 rows, 31 columns, 1.6MB) but **no source file reads it**. `LiveHybridSource._parse_hackathon_csv()` reads `newdata/Hackathon Data_5000.csv` (hardcoded at `live_source.py:324`). `cleaned_thalassemia_data.csv` has different bytes from `Hackathon Data_5000.csv` (different hashes, different sizes).

If someone cleaned/updated the data into `cleaned_thalassemia_data.csv` expecting it to be used, it will never reach the engine or the UI because no code path reads it.

**How to fix**: Update `live_source.py:324` to read `cleaned_thalassemia_data.csv` instead of (or in addition to) `Hackathon Data_5000.csv`.

### Candidate 2 (HIGH): `TODAY_SIMULATION` hardcoded date drift

**Location**: `hemogrid/sources/live_source.py:52`:
```python
TODAY_SIMULATION: date = date(2026, 6, 5)
```

All live-parsed patients have their `last_transfusion_date` anchored to June 5, 2026. The API uses `date.today()` (currently June 6, 2026, and advancing daily). As time passes:
- `forecast_due(patient, date.today())` computes `next_need = last_tx + interval`
- Since `last_tx` is anchored to June 5 and `date.today()` advances, the `days_until_due` calculation drifts
- Live patients who were "due soon" on June 5 may appear overdue or not-yet-due on later dates
- `due_soon` boolean (0 ≤ days ≤ 7) will be incorrect after 7+ days have passed since June 5

**Practical effect**: Live patients may disappear from the "due patients" list because `forecast_due().is_due_soon` returns False when `date.today()` has advanced far enough from June 5.

This is the most likely cause of live patient data "not appearing" in the patient list.

### Candidate 3 (MEDIUM): Dataset loaded once at startup, never refreshed

**Location**: `hemogrid/api/main.py:lifespan()` — data is loaded once. `POST /api/demo/reset` only clears `_DEMO_CACHE`, does NOT reload the dataset.

If the CSV files in `data/` or `newdata/` were updated after server startup, the changes will not be visible until the server is restarted.

### Candidate 4 (MEDIUM): Bank ID sequence dependency — hardcoded references break if CSV changes

**Location**: `hemogrid/sources/synthetic_source.py:629–654` (demo inventory unit) and `hemogrid/sources/synthetic_source.py:956–1000` (compatibility stress additions).

Bank IDs are assigned `f"BB-{idx:04d}"` based on enumeration order in `_load_blood_banks()`, which depends on the CSV row order after deduplication. The code hardcodes:
- `guntur_demo_banks[0]` — first valid-coord, does_components Guntur bank → assumed to be `BB-0036`
- `BB-2253`, `BB-2257`, `BB-2260` — hardcoded Hyderabad bank IDs
- `BB-0037`, `BB-0041` — hardcoded Guntur bank IDs

If `data/blood-banks.xls` was updated (e.g., rows added, removed, or reordered), the bank IDs shift. The `_generate_compatibility_stress()` function does:
```python
bank = next((b for b in banks if b.bank_id == "BB-2253"), None)
if bank is None:
    return []
```
If `BB-2253` no longer exists, the function returns `[]` (empty list) — silently! No error, no log, no patients or inventory are added for the Hyderabad scenario. The HYD desert score would drop to near zero, breaking the CHRONIC desert scenario.

### Candidate 5 (MEDIUM): Frontend hardcoded values diverge from engine output

**Location**: `MapView.tsx:824–831`

The PAT-0001 Intelligence Panel hardcodes:
- `DON-0002`, `B+, K-negative`, `2.4 km`, `0.9141`, `4 days`

If the engine produces different values (e.g., because the seed=42 bond was not placed on DON-0002, or a different matching order), the UI displays stale values. The donor activation message uses `proposalResp?.donor_message_draft` (live) with a hardcoded fallback — so the message will be live but the credentials panel above it will be wrong.

**Location**: `MapView.tsx:328–331`

`getTriageBadge()` hardcodes `PAT-0001` → "DONOR MATCH REQ" and `PAT-EMERG-99` → "EMERGENCY ESCALATION" regardless of what the engine actually selects. If the engine selects the inventory lever for PAT-0001 (which it does by default), the badge shows "DONOR MATCH REQ" which is incorrect.

### Candidate 6 (LOW): Frontend fetches banks filtered to 'Guntur' in synthetic mode

**Location**: `MapView.tsx:225`:
```typescript
fetchBanks(liveMode ? undefined : 'Guntur')
```

In synthetic mode (`liveMode=false`), banks are filtered to district="Guntur". If new bank data was added outside Guntur, it won't appear on the map in synthetic mode. In live mode (`liveMode=true`, default), no district filter is applied and the backend returns banks within the 80 km Hyderabad catchment.

### Candidate 7 (LOW): `fetchActivity()` is never called from the UI

`api.ts` exports `fetchActivity()` but `MapView.tsx` never calls it. The right panel uses `proposeAction()` (which runs the HITL path) for activity display. `GET /api/patients/{id}/activity` is a working endpoint that returns the same data but is not surfaced in the UI.

### Candidate 8 (LOW): Stale browser cache or dev server build

The frontend dev server (Vite 8) hot-reloads. If served from a stale build (`frontend/dist/`), changes to the source may not be reflected. Ensure `npm run dev` is running rather than a static build.

---

## Discrepancies Between Code and CLAUDE.md

### Discrepancy 1: CLAUDE.md says K-negative frequency is 0.97, Caucasian is 0.09

**CLAUDE.md**: "Indian regional probability for Kell K-negative is fixed at exactly `0.97` (Antigen frequency `K = 0.03`). Do not drift to the 0.91 Caucasian baseline."

**Code** (`enrichment.py:43`): `"K": 0.030` (P(antigen PRESENT) = 0.030, so K-negative = 0.97). Comment says: "The frequently-cited 0.09 figure is the Caucasian value — do NOT use it." **Code and CLAUDE.md agree on the value but CLAUDE.md incorrectly states the Caucasian baseline as 0.91 (should be 0.09 K-positive = 0.91 K-negative).** The actual value used is correct (K+ = 0.03).

### Discrepancy 2: CLAUDE.md says CLN-HYD-01 desert score is 16

**CLAUDE.md**: "CLN-HYD-01 (Hyderabad): Map grid cell classified mathematically as a `CHRONIC DESERT` (Score of `16`)"

**Code** (`llm.py:329`): The golden fallback text hardcodes "score of 16". But the actual engine score is `compatibility_gap + supply_gap`, computed dynamically based on `date.today()` and which HYD patients are due on that day. The score will be different on days when fewer of the 12 PAT-0301..0312 patients are due. Score 16 may only hold on a specific day configuration.

### Discrepancy 3: CLAUDE.md says "Memory Clear Gate: POST http://localhost:8000/api/demo/reset (Wipes the volatile cache dictionary and snaps parameters instantly back to default seed data)"

**Code**: `POST /api/demo/reset` clears `_DEMO_CACHE` but does **NOT** reload the dataset. The in-memory `app.state.dataset` remains unchanged. The "default seed data" description implies a full reset, but only the display counters are cleared.

### Discrepancy 4: CLAUDE.md says "Live LLM Harness: Bounded manual prompt loop inside `_agent_select` routing to local Ollama endpoints"

**Code**: The bounded loop in `_agent_select()` is only for the INVENTORY lever. For DONOR and EMERGENCY levers, there is no LLM selection — the engine result is used directly:
```python
# In orchestrate_node:
else:  # donor or emergency
    certified = []
    agent_out = {
        "lever": lever,
        "target_id": result.get("donor_id"),
        "agent_reasoning": f"{lever} lever — engine selection retained",
        "validation_result": "engine_lever",
    }
```

### Discrepancy 5: CLAUDE.md says PAT-0001 "due in 5 days (`need_clock=5d`)"

**Code**: `last_transfusion_date = today - timedelta(days=16)` and `transfusion_interval_days=21`, so `needed_by_date = today + 5`. This is correct ONLY if evaluated on the day the data was generated. Since `today` is `date.today()` at load time, the 5-day window is relative to startup date, not a fixed date.

### Discrepancy 6: `DON-0002` identity is RNG-dependent, not guaranteed by name

**CLAUDE.md**: "Resolves to the `DONOR` lever -> `DON-0002` (B+, K-neg, eligible, bonded, 2.4 km away, match score ≈0.9141, `supply_clock=4d`)"

**Code**: The demo bond in `_make_bonds()` finds `eligible_for_demo[0]` — the first eligible B+ K-neg donor in the seed=42 donor list. The comment says "should not fire at seed=42 with 900 donors" for the failsafe branch. But the specific donor chosen depends on the RNG sequence. From `uvicorn_out.txt` and the name pattern (`f"DON-{i + 1:04d}"` where i is the loop index), DON-0002 corresponds to `i=1` (second donor generated). Whether this donor happens to be B+, K-neg, and eligible with seed=42 is a property of the RNG sequence. The CLAUDE.md assertion that this is DON-0002 is consistent with the seed=42 sequence but is NOT guaranteed by any hardcoded assignment — it's the first eligible B+ K-neg donor found.

---

## Fragilities and Sequence-Coupled Objects

### Fragility 1: Seed-dependent golden objects

`DON-0002`, `BB-0036`, and the exact match score (0.9141) are properties of the `seed=42` RNG sequence and the current CSV row ordering. Any of these break the golden scenario:
- Adding/removing rows at the start of `blood-banks.xls`
- Inserting any `rng.*` call before step 8 in `SyntheticSource.load()`
- Changing the donor generation count (900)
- Adding donors before the loop that generates `DON-0002`

### Fragility 2: Bank ID hardcoded references

`BB-2253`, `BB-2257`, `BB-2260`, `BB-0037`, `BB-0041` in `_generate_compatibility_stress()` and the implicit `BB-0036` in `_generate_inventory()` are order-dependent. If `blood-banks.xls` changes, these IDs may shift, silently disabling entire scenarios. No runtime check verifies these IDs exist before running.

### Fragility 3: Thin deliverability margins

`supply_clock_days = dist_km / (40.0 * 24.0)`. For BB-0036 at 0.7 km: `supply_clock = 0.000729 days`. This is essentially instantaneous, so `deliverable = supply_clock <= need_clock` is always true for local banks. But the `transport_tier` boundary at exactly 5.0 km means a bank at 5.0001 km would be tier 1 (far) rather than tier 0 (local), changing the sort key and potentially the selected unit.

### Fragility 4: `TODAY_SIMULATION` static date

`hemogrid/sources/live_source.py:52`: `TODAY_SIMULATION = date(2026, 6, 5)`. This date does not advance. All live patient transfusion windows become stale after 7 days. This is the second most likely cause of live data not appearing in the UI.

### Fragility 5: InMemorySaver single-process limitation

`_saver: InMemorySaver = InMemorySaver()` at `graph.py:651`. Checkpointed state is not shared between uvicorn workers. If uvicorn is started with `--workers > 1`, propose/approve pairs may land on different workers and the approve call will fail to find the thread.

### Fragility 6: Unit vs bank denomination in ranked_inventory display

`ranked_inventory` in `MatchResult` is a top-10 list of **units** (multiple units from the same bank appear as separate entries). The frontend de-duplicates by bank_id for display (`const seen = new Map<string, {...}>()`), showing the first-ranked unit per bank with a count. But this means the `rank` field on non-first units of the same bank is hidden from the user. If the top-10 has 5 units from BB-0036 and 5 from BB-0037, the user sees "BB-0036 ×5, BB-0037 ×5" with ranks 1 and 6 displayed, which could be confusing.

### Fragility 7: `_DEMO_CACHE["cell_adjustments"]` logic in `/api/deserts`

The adjustment recalculates `desert_score = abs(compatibility_gap) + supply_gap`. The `abs()` on `compatibility_gap` is unnecessary (it's always non-negative from `compute_desert_cells()`) but not harmful. However, if `met_delta` exceeds `demand_units`, `met` could be set to a value larger than `demand_units`, which would be logically incorrect. No bounds check: `c["met"] = min(c["demand_units"], c["met"] + adj["met_delta"])` — actually there IS a `min()` guard, so this is safe.

---

## Deferred/Remaining Work Implied by Code

| Item | Evidence in code |
|------|----------------|
| `OrganizerAdapter` full implementation | `organizer_adapter.py` raises `NotImplementedError`; documented as "THE ONLY FILE EDITED ON HACKATHON DAY" |
| `engagement_log` population | `Donor.engagement_log` field exists but is always `[]`; no graph node writes to it |
| Phenotype-based haplotype sampling | `enrichment.py:17–20` notes that independent antigen sampling is "MVP simplification"; haplotype-based sampling is documented as "future refinement" |
| Cloud Repository swap | `storage.py` documents S3, GCS, DynamoDB, Postgres as "Day-of cloud swap" options |
| `cleaned_thalassemia_data.csv` wiring | File exists but not read; presumably intended for LiveHybridSource |
| `TODAY_SIMULATION` dynamic date | Should be `date.today()` for correct temporal behaviour |
| `create_react_agent` upgrade | `graph.py:109–111` notes it's available but `langchain-ollama` not installed |
| Provenance tooltips in UI | `CanonicalModel.provenance` dict intended for "per-field tooltips" in UI, not implemented in frontend |
| Real eligibility status check | `LiveHybridSource._build_hackathon_donor()` uses `eligibility_status` field for `last_donation_date` but doesn't validate other eligibility criteria |
| Multi-language outreach | `preferred_language` and Telugu suffix in `draft_donor_message()` are placeholders; full multilingual outreach not implemented |
