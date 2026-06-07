# PROJECT_REPORT.md — HemoGrid Thalassemia Matching System

> Generated: 2026-06-07 | RUN_ID: seed42-20260606-8330edb7 | Branch: main

---

## 1. Overview

**HemoGrid** is a real-time blood-unit matching and inventory-management system built specifically for thalassemia patients in Hyderabad and Telangana, India. Thalassemia patients receive blood transfusions every two to four weeks for life; most systems issue the nearest ABO-compatible unit and move on. HemoGrid's core differentiator is **proactive extended-phenotype matching**: before recommending a blood bag, it checks up to 14 red-cell antigens (beyond ABO/Rh) against every antibody the patient has ever formed, then ranks candidates by how closely the donor's full antigen profile mirrors the patient's own — dramatically reducing the chance of new alloimmunization with each transfusion. The system presents results in a live three-column React dashboard backed by a FastAPI engine, and can explain its recommendations in plain clinical English via a locally-hosted AI model.

---

## 2. Purpose & Goals

| Goal | Detail |
|------|--------|
| **Reduce alloimmunization** | Extended-phenotype matching minimises antigen exposure at every transfusion, not just ABO/Rh |
| **Serve immunized patients safely** | Hard gates reject antigen-positive units for any patient with a matching antibody (allo or auto, active or historical) |
| **Operate in a resource-constrained context** | Routing is haversine-only (no paid mapping API); AI runs on local Ollama (no cloud LLM cost) |
| **Support clinical decision-making** | Three-tier output (Exact / Compatible / Emergency) with explicit reason codes for every exclusion |
| **Demonstrate hackathon viability** | Fully runnable end-to-end: real Hyderabad geocoordinates, real blood-bank data, synthetic but epidemiologically grounded patient/donor cohort |

---

## 3. Key Features

- **Three-tier matching engine** (Gate → Rank → Tier): automatically classifies every available blood bag for a given patient as G1 Exact, G2 Ranked Compatible, G3 Emergency, or Excluded — with a machine-readable reason for every excluded unit.
- **Extended phenotype scoring**: phenotype concordance (0–1 proportion of tested antigens that match) is the primary sort key, making it the first system criterion rather than an afterthought.
- **Antibody safety hard gate**: every allo and auto antibody — active and historical — is checked. Auto-antibody patients route directly to G3 ("Review Required") and can never be auto-issued.
- **Untyped-donor policy**: donors with unknown phenotype are allowed for non-immunized patients (flagged "phenotype unconfirmed") and entirely blocked for immunized patients.
- **Live inventory derived from query**: stock figures are never stored; they are always computed as `COUNT(bags WHERE status='available' AND expiry_date >= TODAY)`, guaranteeing consistency even mid-simulation.
- **Haversine routing with long-haul flagging**: distance and ETA (at 25 km/h urban speed) computed from real GPS coordinates; units > 50 km receive a `long_haul_fetch` risk flag.
- **30-day inventory depletion forecast**: day-by-day simulation mapping patient transfusion schedules onto bank stock, reporting days-to-zero with CRITICAL / WARNING / STABLE severity tiers per blood type per bank.
- **SQLite simulation state with mutation guards**: issue, donate, transfer, and reset operations each run loud assertion checks (e.g., available count drops by exactly 1 after issue) — if any assert fails, the mutation is rolled back and an error is surfaced.
- **Local AI explanations**: the `/api/match/{patient_id}/explain` endpoint calls a locally-running Ollama `phi3` model to produce 2–4 bullet-point clinical rationales — no cloud API key required.
- **Interactive Leaflet map**: blood banks and treatment facilities plotted on a real Hyderabad basemap; click any bank for a live blood-type inventory popup; click any facility for its patient roster and stock.
- **Donor and patient rosters with live filtering**: left-panel search narrows the 4 439-donor and 164-patient lists in real time; selecting a patient immediately fetches their match results.
- **Reset simulation**: one button returns the live SQLite state to the 536-unit baseline without restarting the server.
- **Privacy-preserving map display**: donor/patient coordinates on the map use jittered `display_latitude/longitude` (Rayleigh σ = 300 m, capped 700 m); the matcher always uses real GPS.

---

## 4. How It Works — Main Flow

### 4.1 Data Build (one-time, offline)

```
Dataset.csv (7033 rows, 33 columns)   blood-banks.xls
        │                                    │
        └─────────── build_datasets.py ──────┘
                         │
                 EXTRACT real values
                 FILL synthetic gaps
                 (RANDOM_SEED=42, deterministic)
                         │
              ┌──────────┼──────────────────────┐
              │          │                      │
           donors.csv  patients.csv  bags.csv  antibodies.csv
           banks.csv   facilities.csv ...
                         │
                  build_jitter.py   ← adds display_lat/lng for privacy
                         │
                   build_map.py     ← emits map_data.json + index.html
```

`build_datasets.py` operates in two passes:
1. **EXTRACT** — pull real donor records (blood type, donation history, coordinates) from the hackathon CSV; pull blood-bank records from the XLS.
2. **FILL** — synthesise extended phenotype distributions (Makroo 2013 frequency tables), antibody history (18% alloimmunization rate, 12% auto-among-immunized, 30% historical), donation schedules, and bag inventory. All synthesis is seeded (`RANDOM_SEED=42`) for full reproducibility.

### 4.2 Server Startup

```
python main.py
    │
    ├─ bags.csv baseline assert → must have exactly 536 available bags
    ├─ engine.state.reset_simulation_state() if no DB tables found
    │    └─ loads all CSVs into SQLite + creates activity_log table
    └─ FastAPI + CORS ready on :8000
```

### 4.3 Typical User Action — Matching a Patient

```
User clicks a patient card in the left panel
        │
        └─ GET /api/patient/{patient_id}/match
                │
                engine/match.py::match(patient_id)
                │
                ├─ Load patient row, antibody rows, ALL available bags (status=available, expiry≥TODAY)
                │
                ├─ GATE 1A: component filter (packed_rbc only)
                ├─ GATE 1B: processing requirements (irradiated, CMV-neg, washed, leukoreduced, TTI pass)
                ├─ GATE 2:  ABO/Rh-D compatibility lattice (D− patient → D− donor only)
                ├─ GATE 3:  antibody exclusion
                │            ├─ immunized + untyped donor → excluded
                │            ├─ antigen-positive against any antibody → G3 pool
                │            └─ auto-antibody → G3, requires_adsorption_workup=True
                │
                ├─ TIER ASSIGNMENT:
                │   G1 Exact    → typed + ABO identical + all tested antigens match + antibody-safe
                │   G2 Compatible → compatible + Rh+K floor + antibody-safe (untyped go here, ranked below typed)
                │   G3 Emergency → only when G1+G2 empty, or auto/panreactive (never auto-issued)
                │   Excluded    → failed gate, with reason code
                │
                ├─ SORT each tier:
                │   G1/G2: phenotype_concordance↓, typed>untyped, distance_km↑, expiry_date↑
                │   G3:    antigen_conflict_count↑, distance_km↑, expiry_date↑
                │
                └─ Return { patient_id, G1:[...], G2:[...], G3:[...], excluded:[...] }
                        │
              React right panel renders tiered match cards
              with distance, ETA, concordance %, expiry, risk flags
```

### 4.4 Issuing a Unit

```
User clicks "Issue Unit" on a G1 or G2 card
        │
        └─ POST /api/actions/treat  { patient_id, bag_id }
                │
                engine.state.issue_bag_to_patient(bag_id, patient_id)
                │
                ├─ UPDATE bags SET status='issued', reserved_for_patient_id=patient_id
                ├─ UPDATE patients SET last_transfusion_date=TODAY
                ├─ If inter-facility: UPDATE bags SET current_location_id=patient_facility
                │                    INSERT activity_log (TRANSIT) + activity_log (CONSUMED)
                └─ Else:             INSERT activity_log (CONSUMED)
                        │
                        └─ ASSERT: available count dropped by exactly 1
                                   total bag rows unchanged
                                   activity_log grew by 1 or 2
                │
                engine.ai.generate_issue_summary() → Ollama phi3 → one-sentence log entry
                │
                Response: { status:"issued", bag_id, patient_id, ai_summary }
                        │
                Frontend toasts success, refreshes header unit count + activity log
```

### 4.5 Inventory Forecast

```
GET /api/forecast
        │
        engine/forecast.py::run_global_forecast(horizon=30)
        │
        ├─ Load all available bags grouped by bank + blood type
        ├─ Map each treatment facility → nearest active bank (haversine)
        ├─ Expand patient transfusion schedules → per-day demand events over 30 days
        ├─ Day-by-day loop:
        │   1. Expire bags whose expiry_date == current_day
        │   2. Consume demand for that day
        │   3. Record first day stock → 0
        └─ Return { bank_id: { blood_type: { initial_stock, days_to_depletion, shortage_severity } } }
            severity: CRITICAL (<7d), WARNING (7–30d), STABLE (>30d or 999)
```

---

## 5. Architecture

### High-Level Text Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        React Frontend                               │
│   frontend/src/App.tsx  (TypeScript, React 19, Leaflet, Vite)       │
│                                                                     │
│  ┌──────────┐   ┌───────────────────────┐   ┌───────────────────┐  │
│  │ Left     │   │   Center Map          │   │ Right Panel       │  │
│  │ Panel    │   │  (React-Leaflet)      │   │ Match Results     │  │
│  │ Patients │   │  Banks + Facilities   │   │ Activity Log      │  │
│  │ Donors   │   │  Donor layer (≤500)   │   │ AI Explanation    │  │
│  │ Banks    │   │                       │   │ Issue / Donate    │  │
│  └──────────┘   └───────────────────────┘   └───────────────────┘  │
│            │              │                           │              │
│            └──────────────┼───────────────────────────┘              │
│                           │  HTTP /api/*  (Vite proxy)               │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
              ┌─────────────▼──────────────────┐
              │     FastAPI Gateway             │
              │       main.py  :8000            │
              │                                 │
              │  /api/inventory                 │
              │  /api/patient/{id}/match        │
              │  /api/match/{id}/explain        │
              │  /api/forecast                  │
              │  /api/actions/treat             │
              │  /api/actions/donate            │
              │  /api/state/reset               │
              │  /api/logs                      │
              │  /api/patients                  │
              │  /api/donors                    │
              │  /api/map-data                  │
              └──────┬──────┬──────┬────────────┘
                     │      │      │
         ┌───────────┘  ┌───┘  ┌───┘
         ▼              ▼      ▼
  ┌────────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐
  │ engine/    │  │ engine/  │  │  engine/     │  │  engine/     │
  │ match.py   │  │ state.py │  │  forecast.py │  │  routing.py  │
  │            │  │          │  │              │  │              │
  │ Gate→Rank  │  │ SQLite   │  │ 30-day sim   │  │ Haversine    │
  │ →Tier algo │  │ mutations│  │ depletion    │  │ ETA calc     │
  └────────────┘  └────┬─────┘  └──────────────┘  └──────────────┘
                       │
              ┌────────▼────────┐
              │  data/working_  │
              │  sim.db (SQLite)│
              └────────┬────────┘
                       │  (reset reloads from)
              ┌────────▼────────────────────────────────┐
              │  data/build/  (canonical dataset)        │
              │  donors.csv · patients.csv · bags.csv    │
              │  antibodies.csv · banks.csv · etc.       │
              └─────────────────────────────────────────-┘
                       ▲
                       │ (built by)
              ┌────────┴────────┐
              │  build_*.py     │
              │  pipeline       │
              └─────────────────┘
                       ▲
              ┌────────┴────────────────┐
              │  data/Dataset.csv       │
              │  data/blood-banks.xls   │
              └─────────────────────────┘

                    ┌──────────┐
  /api/explain ────►│engine/   │
                    │ai.py     │──► Ollama :11434  (phi3, local)
                    └──────────┘
```

### Component Responsibilities

| Component | File(s) | Responsibility |
|-----------|---------|----------------|
| **FastAPI gateway** | `main.py` | HTTP routing, startup assert, CORS, request/response marshalling |
| **Matching engine** | `engine/match.py` | Gate → Rank → Tier algorithm; returns G1/G2/G3/excluded |
| **State manager** | `engine/state.py` | SQLite CRUD, mutation guards, activity log, reset |
| **Routing module** | `engine/routing.py` | Haversine distance, ETA, long-haul flag |
| **Forecast engine** | `engine/forecast.py` | 30-day day-by-day depletion simulation |
| **AI module** | `engine/ai.py` | Ollama `phi3` call — match explanations + issue log summaries |
| **React dashboard** | `frontend/src/App.tsx` | 3-column UI, Leaflet map, roster panels, match display |
| **Build pipeline** | `build_datasets.py`, `build_jitter.py`, `build_map.py` | One-time offline data construction |
| **Dataset** | `data/build/*.csv` | Canonical source of truth (read-only; never modified at runtime) |
| **Live DB** | `data/working_sim.db` | SQLite simulation state (mutations here; reset reloads from CSVs) |

---

## 6. Tech Stack

### Backend

| Technology | Version / Notes |
|------------|----------------|
| Python | 3.x (no explicit pin in requirements) |
| FastAPI | latest (`fastapi`) |
| Uvicorn | `uvicorn[standard]` — ASGI server |
| Pandas | latest (`pandas`) — data manipulation, CSV loading |
| openpyxl | latest — reads `blood-banks.xls` |
| requests | latest — HTTP client for Ollama calls |
| SQLite | stdlib `sqlite3` — simulation state |
| Pydantic | bundled with FastAPI — request model validation |
| Ollama | `phi3` model, locally hosted on :11434 — AI explanations |

### Frontend

| Technology | Version |
|------------|---------|
| React | 19.2.6 |
| TypeScript | ~6.0.2 |
| Vite | ^8.0.12 |
| React-Leaflet | ^5.0.0 |
| Leaflet | ^1.9.4 |
| ESLint | ^10.3.0 |

### Data & Deployment

| Item | Detail |
|------|--------|
| Primary data store | SQLite (`data/working_sim.db`) — lightweight, no external DB |
| Dataset format | CSV (pandas DataFrames) |
| Basemap | CARTO Light (`CartoDB.Positron` tile layer, free) |
| Map serving (static) | Python built-in HTTP server (`python -m http.server`) |
| AI inference | Ollama (local, no cloud API key needed) |
| Platform | Windows 11 (developed on); cross-platform Python |

---

## 7. Project Structure

```
hackathon-project/
│
├── main.py                     FastAPI gateway (11 endpoints, startup asserts)
├── requirements.txt            Python dependencies (5 packages)
├── CLAUDE.md                   Project memory / invariants for AI assistant
├── PROJECT_REPORT.md           This file
│
├── engine/                     Core Python engine
│   ├── __init__.py
│   ├── match.py                Gate→Rank→Tier matching algorithm (~400 lines)
│   ├── state.py                SQLite state manager + mutation guards (~485 lines)
│   ├── routing.py              Haversine distance, ETA, long-haul flag (~288 lines)
│   ├── forecast.py             30-day depletion forecast simulation (~360 lines)
│   └── ai.py                   Ollama phi3 integration — explanations + log summaries
│
├── frontend/
│   ├── package.json            React 19.2.6 + React-Leaflet + TypeScript + Vite
│   ├── vite.config.ts          Dev server :5173, /api proxy → :8000
│   ├── tsconfig.json
│   ├── src/
│   │   ├── main.tsx            React entry point
│   │   ├── App.tsx             Entire dashboard (3-column layout, ~993 lines)
│   │   ├── App.css             Component styles
│   │   └── index.css           Base styles
│   └── dist/                   Compiled frontend (produced by npm run build)
│
├── data/
│   ├── Dataset.csv             Raw hackathon source data (7033 rows × 33 columns)
│   ├── blood-banks.xls         Blood-bank reference (Telangana state data)
│   ├── uci_blood_transfusion.csv  Reference dataset (not primary)
│   ├── working_sim.db          Live SQLite simulation state
│   └── build/                  Canonical processed dataset (source of truth)
│       ├── donors.csv          4439 donors (85% phenotype-typed)
│       ├── patients.csv        164 patients (100% typed)
│       ├── bags.csv            2417 blood bags (536 available at baseline)
│       ├── antibodies.csv      51 patient antibody records
│       ├── reservations_log.csv  909 reservation entries
│       ├── banks.csv           149 blood banks (13 with live inventory)
│       ├── facilities.csv      21 treatment facilities
│       ├── potential_donors.csv  400 potential donor profiles
│       ├── data_dictionary.md  Full column-by-column schema documentation
│       ├── *_field_sources.json  Per-column provenance (real vs. synthetic counts)
│       ├── REPORT.md           Build run report (RUN_ID-stamped)
│       ├── _run_history.json   Build run history log
│       └── map/
│           ├── map_data.json   Spatial export (banks, facilities, patients, donors)
│           └── index.html      Static map viewer (open via python -m http.server)
│
├── build_datasets.py           Phase 1: Extract real data + fill synthetic gaps
├── build_jitter.py             Phase 2: Add display_lat/lng (privacy jitter)
└── build_map.py                Phase 3: Generate map_data.json + static map HTML
```

---

## 8. Setup & Run

### Prerequisites

- Python 3.10+ with pip
- Node.js 18+ with npm
- Ollama (optional; needed only for `/api/explain` endpoint)
  - Install from https://ollama.com and run: `ollama pull phi3`

### Backend

```bash
# From project root
pip install -r requirements.txt
python main.py
# Server starts on http://localhost:8000
# Startup output confirms: "[PASS] Startup assert: 536 available bags in baseline CSV."
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Dev server starts on http://localhost:5173
# All /api/* calls are proxied automatically to http://localhost:8000
```

### Static Map (standalone)

```bash
cd data/build/map
python -m http.server 8000
# Open http://localhost:8000/index.html in a browser
```

### Rebuild Dataset (if needed)

```bash
# From project root — takes several minutes; deterministic with RANDOM_SEED=42
python build_datasets.py
python build_jitter.py
python build_map.py
```

### Run Matcher in CLI Mode

```bash
# Runs the matcher over all 164 patients and prints results
python -m engine.match
```

### Reset Simulation to Baseline

```bash
# Via HTTP (while server is running)
curl -X POST http://localhost:8000/api/state/reset

# Or programmatically
python -c "from engine import state; state.reset_simulation_state()"
```

---

## 9. Current State

### Complete

| Area | Detail |
|------|--------|
| Dataset pipeline | `build_datasets.py` / `build_jitter.py` / `build_map.py` fully functional; output checksums verified |
| Matching engine | All three tiers (G1 Exact, G2 Compatible, G3 Emergency) + Excluded; antibody gate, untyped gate, Rh-D gate all implemented |
| Routing | Haversine + ETA + long-haul detection; assert suite passes |
| State manager | SQLite mutations with loud assert guards; reset verified to restore exactly 536 units |
| Forecast engine | 30-day day-by-day simulation with CRITICAL/WARNING/STABLE severity |
| FastAPI backend | 11 endpoints fully wired; CORS enabled; startup assert in place |
| React dashboard | 3-column layout; Leaflet map with bank/facility/donor layers; match results panel; activity log with auto-refresh; toast notifications; reset button |
| AI module | Ollama `phi3` integration for match explanations and issue log summaries |

### Incomplete / Stubbed / Known Gaps

| Area | Detail |
|------|--------|
| `backend/main.py` | Placeholder FastAPI app — superseded by root `main.py`; dead code |
| AI explanations | Ollama must be running separately; if it's down, the endpoint returns empty string silently |
| Mobilise donor | `handleMobilizeRequest()` in App.tsx logs to console only — no backend endpoint wired |
| Simulation phase | Redistribution algorithms and multi-scenario simulation (deferred per CLAUDE.md) |
| REPORT.md §A cosmetic debt | Broken "previous report incorrectly said 33; actual is 33" line; "Bridge reservation rows: 786" not reconciled to 909 |
| Frontend build | `dist/` is committed — should be in `.gitignore` for a clean repo |
| Authentication | No auth layer; CORS allows all origins (`*`) |
| Production deployment | No Dockerfile, no Nginx config, no `gunicorn`/`hypercorn` config |
| Test suite | No automated tests (`pytest`, `jest`); correctness relies on engine-level asserts |
| `.gitignore` | `data/working_sim.db` (mutable sim state) and `frontend/dist/` should be ignored |

---

## 10. Data Integrity Guarantees (Invariants)

These invariants are enforced by loud assertions throughout the codebase and must never be broken:

1. **Inventory is a derived query** — `available = bags WHERE status='available' AND expiry_date >= TODAY`. Never a stored column or table.
2. **Bags carry ABO/Rh only** — extended phenotype (14 antigens) lives on the donor row, not the bag.
3. **Matcher uses real GPS** — `latitude`/`longitude` are precise; `display_latitude`/`display_longitude` are map-only jitter.
4. **Antibody safety is universal** — an antigen-positive unit is never issued against any antibody (allo or auto, active or historical). Auto-antibody → `requires_adsorption_workup=True` → G3 only, never auto-issued.
5. **Untyped donor + immunized patient = excluded** — phenotype cannot be proven safe, so the unit is blocked entirely for immunized patients.
6. **Primary keys unique; zero orphaned foreign keys** across all eight tables.
7. **`expiry_date = collection_date + 42`** (42-day pRBC shelf life); `max(collection_date) ≤ TODAY - 1`; `status=available` implies `expiry_date ≥ TODAY`.
8. **Emails and phone numbers are format-valid and globally unique** — phones match `^\+91[6-9]\d{9}$`.

---

## 11. Suggested Presentation Slides

### Slide 1 — Title Slide
- **HemoGrid: Extended-Phenotype Blood Matching for Thalassemia**
- Hackathon project | Hyderabad / Telangana, India
- Tagline: "The right unit, not just a compatible unit"

### Slide 2 — The Problem
- Thalassemia patients need transfusions every 2–4 weeks, for life
- Standard systems match ABO + Rh-D; ignoring 14 other red-cell antigens causes alloimmunization
- Alloimmunization makes future matching harder and can become life-threatening
- No open-source extended-phenotype matching tool exists for India's thalassemia centres

### Slide 3 — Our Solution
- HemoGrid matches on 14 antigens beyond ABO/Rh (C, c, E, e, K, k, Jka, Jkb, Fya, Fyb, M, N, S, s)
- Hard safety gate: every antibody (allo + auto, active + historical) is checked before issuing
- Three-tier output: G1 Exact → G2 Compatible → G3 Emergency (review required)
- Clinical AI (local Ollama) explains rankings in plain English — no cloud required

### Slide 4 — How It Works (Matching Flow)
- Gate 1: Component + processing requirements (irradiation, CMV, TTI)
- Gate 2: ABO/Rh-D compatibility lattice (D− patient receives D− only)
- Gate 3: Antibody exclusion + untyped-donor policy
- Rank: phenotype concordance % → typed > untyped → distance → earliest expiry
- Result: tiered list of candidates with distance, ETA, concordance, risk flags

### Slide 5 — Live Dashboard
- Screenshot: 3-column React dashboard on real Hyderabad data
- Left: searchable patient / donor / bank roster (164 patients, 4439 donors, 149 banks)
- Centre: interactive Leaflet map — click any bank for live blood-type inventory
- Right: match results with "Issue Unit" button; live activity log

### Slide 6 — Forecast & Simulation
- 30-day inventory depletion forecast per bank per blood type
- CRITICAL (<7 days), WARNING (7–30 days), STABLE
- Simulation state: issue units, register donations, reset to baseline — all with integrity asserts
- Enables "what-if" redistribution planning (next phase)

### Slide 7 — Dataset & Methodology
- 4 439 donors (85% phenotype-typed), 164 thalassemia patients (100% typed), 2 417 blood bags
- Real data: geocoordinates from Telangana state blood-bank directory; donor distribution from Makroo et al. 2013
- Synthetic gap-filling: antibody prevalence 18% alloimmunization rate (literature-grounded), RANDOM_SEED=42 (reproducible)
- Privacy: display coordinates jittered (Rayleigh σ = 300 m); real coordinates used only in routing

### Slide 8 — Tech Stack & Architecture
- Backend: FastAPI + Python + Pandas + SQLite (no heavy infrastructure)
- Frontend: React 19 + TypeScript + Vite + React-Leaflet
- AI: Ollama `phi3` (runs locally — zero cloud cost, zero data leakage)
- Architecture: offline build pipeline → canonical CSVs → SQLite sim DB → FastAPI → React

### Slide 9 — Impact & Next Steps
- Deployed in a thalassemia centre: every transfusion gets the best phenotype match available
- Reduces antigen exposure → fewer new antibodies → simpler future matching → better outcomes
- Next: redistribution algorithm (move units from oversupplied to undersupplied banks), multi-scenario simulation, mobile-friendly view
- Open source, deployable with `pip install -r requirements.txt && python main.py`

### Slide 10 — Demo / Q&A
- Live demo: select a patient → see G1/G2/G3 match tiers instantly
- Click "Explain" → AI rationale in plain English
- Issue a unit → inventory updates live; see the activity log entry
- Reset simulation → back to 536-unit baseline in one click

---

## 12. Documentation To Write

### Files That Should Exist (Checklist)

- [ ] **README.md** (root)
  - One-paragraph project description
  - Prerequisites (Python 3.10+, Node 18+, Ollama optional)
  - `pip install -r requirements.txt && python main.py` quickstart
  - `cd frontend && npm install && npm run dev` frontend quickstart
  - Link to data_dictionary.md for schema reference
  - Screenshot of the dashboard
  - License statement

- [ ] **CONTRIBUTING.md**
  - Do not modify `data/build/` CSV files manually — run `build_datasets.py`
  - Keep `RANDOM_SEED=42` and `TODAY=2026-06-06` in all scripts
  - Invariants list (copy from CLAUDE.md §INVARIANTS) — breaking these will fail asserts
  - How to run the matcher in CLI mode for verification
  - PR checklist: assert suite still passes, no `\x` in IDs, no hand-typed constants in reports

- [ ] **LICENSE**
  - Project has no license file — choose MIT or Apache 2.0 for a hackathon open-source release
  - If data sourced from government sources (blood bank XLS), note attribution

- [ ] **.gitignore** (update existing)
  - `data/working_sim.db` — mutable simulation state, should not be committed
  - `frontend/dist/` — compiled output, should be regenerated
  - `__pycache__/`, `*.pyc`
  - `.env` (if added later)
  - `frontend/node_modules/` (already likely ignored)

- [ ] **data/build/data_dictionary.md** (exists, keep updated)
  - Verify all 14 phenotype antigen columns documented
  - Note the `display_latitude`/`display_longitude` jitter specification (Rayleigh σ=300m)
  - Document invariants for `expiry_date`, `status`, and `current_location_id` fields

- [ ] **ARCHITECTURE.md** (optional but valuable)
  - The text diagram from §5 of this report
  - One-paragraph description of each engine module
  - Explanation of the EXTRACT/FILL two-pass dataset build
  - Note that `backend/main.py` is dead code / superseded by root `main.py`

- [ ] **API.md** or OpenAPI usage note
  - FastAPI auto-generates docs at `http://localhost:8000/docs`
  - Document the 11 endpoints: route, method, body shape, response shape, error codes
  - Note: `GET /api/match/{patient_id}/explain` requires Ollama running on :11434

- [ ] **data/build/REPORT.md** (exists, cosmetic fixes needed)
  - Fix broken line: "previous report incorrectly said 33; actual is 33"
  - Reconcile "Bridge reservation rows: 786" against actual 909 total reservation rows
  - Ensure RUN_ID is regenerated from live data on every build (currently stamped on line 1 ✓)

---

*End of PROJECT_REPORT.md*
