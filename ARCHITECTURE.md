# HemoGrid — Architecture

This document covers the technical design of HemoGrid: how the system is structured, how a request flows through it, and the key decisions behind the design.

---

## High-level overview

HemoGrid is a three-layer system:

1. **Offline build pipeline** — a one-time process that ingests raw source data (a 7 033-row CSV and a blood-bank XLS) and produces a canonical set of CSV files in `data/build/`. These CSVs are the source of truth. They are never modified at runtime.

2. **FastAPI backend** — reads from `data/build/` CSVs at startup, loads them into a SQLite simulation database (`data/working_sim.db`), and exposes 11 HTTP endpoints. The matching engine, routing, forecast, and AI explanation modules all live here.

3. **React frontend** — a three-column single-page dashboard (React 19 + TypeScript + Vite + React-Leaflet) that proxies all API calls to the backend. No state is stored in the frontend beyond what was fetched from the server.

---

## Component map

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           React Frontend (:5173)                         │
│                       frontend/src/App.tsx                               │
│                                                                          │
│  ┌─────────────┐    ┌──────────────────────┐    ┌──────────────────────┐ │
│  │ Left Panel  │    │   Centre — Map        │    │ Right Panel          │ │
│  │             │    │   (React-Leaflet)     │    │                      │ │
│  │ Patient     │    │   Banks (red dots)    │    │ Match results        │ │
│  │ roster      │    │   Facilities (blue)   │    │ G1 / G2 / G3 cards  │ │
│  │             │    │   Donor layer (≤500)  │    │ Activity log         │ │
│  │ Donor       │    │   Click → inventory   │    │ AI explanation       │ │
│  │ roster      │    │   popup               │    │ Issue / Donate       │ │
│  │             │    │                       │    │ Reset button         │ │
│  │ Bank filter │    │                       │    │                      │ │
│  └─────────────┘    └──────────────────────┘    └──────────────────────┘ │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │  HTTP /api/*  (Vite dev proxy → :8000)
                                   │  (served from frontend/dist/ in production)
┌──────────────────────────────────▼───────────────────────────────────────┐
│                         FastAPI Gateway (:8000)                          │
│                              main.py                                     │
│                                                                          │
│  GET  /api/inventory            GET  /api/patients                       │
│  GET  /api/patient/{id}/match   GET  /api/donors                         │
│  GET  /api/match/{id}/explain   GET  /api/map-data                       │
│  GET  /api/forecast             GET  /api/logs                           │
│  POST /api/actions/treat        POST /api/actions/donate                 │
│  POST /api/state/reset                                                   │
└───────┬──────────┬──────────────┬───────────────┬────────────────────────┘
        │          │              │               │
        ▼          ▼              ▼               ▼
┌────────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐
│ engine/    │ │ engine/  │ │ engine/      │ │ engine/      │
│ match.py   │ │ state.py │ │ forecast.py  │ │ ai.py        │
│            │ │          │ │              │ │              │
│ Gate→Rank  │ │ SQLite   │ │ 30-day day-  │ │ Ollama phi3  │
│ →Tier algo │ │ CRUD +   │ │ by-day       │ │ match        │
│ G1/G2/G3/  │ │ mutation │ │ depletion    │ │ explanations │
│ excluded   │ │ guards   │ │ simulation   │ │ + log        │
└────────────┘ └────┬─────┘ └──────────────┘ │ summaries    │
    uses             │                         └──────┬───────┘
    ▼                ▼                                ▼
┌──────────┐  ┌─────────────────┐             ┌─────────────┐
│ engine/  │  │ data/           │             │ Ollama      │
│ routing  │  │ working_sim.db  │             │ :11434      │
│ .py      │  │ (SQLite)        │             │ (local)     │
│          │  │                 │             └─────────────┘
│ haversine│  │ reset reloads   │
│ ETA      │  │ from CSVs ──────┼──────────────────────────┐
│ long-haul│  └─────────────────┘                          │
└──────────┘                                               ▼
                                                ┌────────────────────┐
                                                │  data/build/       │
                                                │  (canonical CSVs)  │
                                                │                    │
                                                │  donors.csv        │
                                                │  patients.csv      │
                                                │  bags.csv          │
                                                │  antibodies.csv    │
                                                │  banks.csv         │
                                                │  facilities.csv    │
                                                │  reservations_log  │
                                                │  potential_donors  │
                                                └────────┬───────────┘
                                                         │ built by
                                                         ▼
                                                ┌────────────────────┐
                                                │  build pipeline    │
                                                │                    │
                                                │ build_datasets.py  │
                                                │ build_jitter.py    │
                                                │ build_map.py       │
                                                └────────┬───────────┘
                                                         │ ingests
                                                         ▼
                                                ┌────────────────────┐
                                                │  data/             │
                                                │  Dataset.csv       │
                                                │  blood-banks.xls   │
                                                └────────────────────┘
```

---

## Module responsibilities

### `main.py` — FastAPI gateway

- Owns all HTTP routing, CORS configuration, Pydantic request models, and startup asserts.
- On startup: verifies that `data/build/bags.csv` contains exactly 536 available bags, then ensures the SQLite DB is initialised (calls `state.reset_simulation_state()` if tables are absent).
- All business logic is delegated to the engine modules — `main.py` contains no matching, routing, or forecast logic itself.

### `engine/match.py` — Gate → Rank → Tier

The core of HemoGrid. Given a `patient_id`, it:

1. Derives the live inventory in a single Pandas filter (`status=available AND expiry_date >= TODAY`) — never reads a stored count.
2. Applies gates in order: component filter → processing requirements → ABO/Rh-D lattice → antibody exclusion.
3. Assigns tier (G1 / G2 / G3-pool / excluded) per bag.
4. Sorts each tier: G1/G2 by `phenotype_concordance ↓ → typed > untyped → distance_km ↑ → expiry_date ↑`; G3 by `antigen_conflict_count ↑ → distance_km ↑ → expiry_date ↑`.
5. G3 is only populated in the response when G1 and G2 are both empty.

Key invariant: a donor with `phenotype = unknown` can never reach G1, and is excluded entirely when the patient has any antibody.

### `engine/state.py` — SQLite simulation state

- Owns the connection singleton to `data/working_sim.db`.
- `reset_simulation_state()` drops all tables and reloads from the canonical CSVs, then asserts exactly 536 available bags.
- `issue_bag_to_patient()`, `register_donation()`, `transfer_bag()` are the three mutation operations. Each carries loud post-condition asserts (available count changes by exactly ±1; total row count is stable; activity log grew by the expected amount). If any assert fails, an `AssertionError` is raised and the mutation is left in its failed state for inspection.
- One SQLite column-naming workaround: `phenotype_C` and `phenotype_c` are case-insensitively identical in SQLite. `_sanitize_columns()` renames the second member of each clashing pair with an `_alt` suffix (`phenotype_c_alt`, etc.).

### `engine/routing.py` — Haversine routing

- Pure-Python haversine formula. No external network dependency.
- Builds a location index from `banks.csv` and `facilities.csv` at load time.
- `get_route_metrics()` returns `{distance_km, eta_minutes, is_long_haul}`.
- Urban speed assumption: 25 km/h (Hyderabad traffic model). Long-haul threshold: 50 km.
- **Only real coordinates are ever passed here.** `display_latitude`/`display_longitude` are map-only jitter (Rayleigh σ = 300 m) and must never be used in routing calculations.

### `engine/forecast.py` — 30-day depletion simulation

- Loads available bag stock per bank+blood_type at the start of the horizon.
- Maps each treatment facility to its nearest active bank (haversine minimum).
- Expands each patient's transfusion schedule (interval + units_per_session) into day-by-day demand events over the 30-day horizon.
- Simulates day by day: expire bags whose `expiry_date == current_day`, consume demand, record the first day stock reaches zero.
- Returns `{ bank_id: { blood_type: { initial_stock, days_to_depletion, shortage_severity } } }`.
- Severity thresholds: CRITICAL < 7 days, WARNING 7–30 days, STABLE > 30 days (or 999 if no depletion).

### `engine/ai.py` — Ollama integration

- Calls Ollama's `/api/generate` endpoint at `http://localhost:11434` with model `phi3` and `temperature=0`.
- Two functions: `explain_match()` (2–4 bullet clinical rationale) and `generate_issue_summary()` (one-sentence activity log entry).
- Gracefully returns empty string on any error — the AI layer is optional and must never cause a 500.

---

## Request flow: matching a patient

```
User clicks a patient card
        │
        └─ GET /api/patient/{patient_id}/match  (FastAPI)
                │
                engine.match.match(patient_id)
                │
                ├─ Derive live inventory: bags WHERE status=available AND expiry>=TODAY
                ├─ Load patient row, antibody rows
                │
                ├─ GATE 1A  component == packed_rbc
                ├─ GATE 1B  processing requirements (irradiated, CMV-neg, washed, TTI, HbsAg)
                ├─ GATE 2   ABO/Rh-D lattice  (D− patient → D− donor only)
                ├─ GATE 3   antibody exclusion
                │             auto-antibody          → G3 pool (workup_required)
                │             immunized + untyped    → excluded
                │             antigen-pos/unconfirmed→ G3 pool
                │
                ├─ TIER
                │     G1 Exact     typed + ABO identical + all antigens match + ab-safe
                │     G2 Compatible compatible + Rh+K floor + ab-safe
                │                  (untyped for non-immunized: G2 flagged, ranked last)
                │     G3 Emergency populated only when G1+G2 empty
                │     excluded     with reason code
                │
                ├─ SORT each tier (concordance ↓, typed > untyped, distance ↑, expiry ↑)
                │
                └─ Return { patient_id, G1, G2, G3, excluded }
                        │
                        React renders tiered match cards
```

---

## Data model summary

| Table | Key fields | Notes |
|-------|-----------|-------|
| `donors` | `donor_id`, `abo`, `rhd`, `phenotype_*` (14 cols), `is_typed` | Extended phenotype lives here, not on bags |
| `patients` | `patient_id`, `abo`, `rhd`, `phenotype_*`, `home_facility_id`, `immunized` | 100% typed in this dataset |
| `bags` | `bag_id`, `donor_id`, `abo`, `rhd`, `status`, `expiry_date`, `current_location_id` | ABO/Rh only — no phenotype columns |
| `antibodies` | `patient_id`, `antigen`, `type` (allo/auto), `status` (active/historical) | All rows checked by Gate 3 |
| `banks` | `bank_id`, `latitude`, `longitude` | 149 banks; 13 have live inventory |
| `facilities` | `facility_id`, `latitude`, `longitude` | 21 treatment centres |
| `reservations_log` | `patient_id`, `donor_id`, `bag_id`, `status` | Historical; not used by live matcher |
| `potential_donors` | `donor_id`, ... | Pool for future mobilisation feature |
| `activity_log` | `id`, `timestamp`, `action_type`, `description` | Written by state mutations; read by `/api/logs` |

---

## Key design decisions

### Inventory is a derived query — never a stored value

Storing "available count" as a column or a separate table would require keeping it in sync with every issue, donation, expiry, and transfer. A derived query on `status + expiry_date` is always correct. This is enforced as an invariant: no code in the repo stores or caches a bag count.

### Thin bag layer — phenotype on the donor

A bag can move between facilities and change status, but its phenotypic characteristics never change — those belong to the donor. Keeping phenotype on the donor row means the matching engine only needs to join through `bag.donor_id` to get the full antigen profile; the bag table stays lean and mutation-safe.

### SQLite for simulation state

The demo dataset is small enough (≤ 5 000 rows per table) that SQLite is the right call. No external database to configure, no connection pooling, no migrations. The simulation database is entirely ephemeral — `reset_simulation_state()` can recreate it from the CSV source of truth in under a second.

### Loud asserts, not silent failure

Every mutation in `engine/state.py` asserts a post-condition. This is a deliberate choice: in a clinical demo, a silent wrong count is worse than a noisy crash. The asserts are documentation as well as guards — they make the expected invariants explicit in code.

### Local Ollama, not a cloud LLM API

The AI explanation feature uses a locally-hosted `phi3` model via Ollama. This was a deliberate choice for the hackathon context: no API key, no egress cost, no patient data leaving the machine. The feature degrades gracefully — if Ollama is not running, the endpoint returns an empty string and no other functionality is affected.

### Privacy-preserving display coordinates

Real GPS coordinates are precise enough that, combined with a known population (thalassemia patients are a small, identifiable group), they could re-identify individuals. Display coordinates on the Leaflet map are jittered using a Rayleigh distribution (σ = 300 m, hard cap 700 m). The matching engine always uses the real `latitude`/`longitude` columns — never the display columns.

---

## External dependencies

| Service | Purpose | Required? |
|---------|---------|-----------|
| Ollama `:11434` | AI explanations and log summaries | Optional — endpoint silently returns `""` if down |
| CartoDB Positron tiles | Leaflet basemap | Yes at runtime (CDN, no API key) |
| No others | — | All routing is haversine; no paid mapping API |

---

## What is not yet implemented

| Area | Status |
|------|--------|
| Redistribution algorithm | Deferred — move units from oversupplied to undersupplied banks |
| Multi-scenario simulation | Deferred — compare strategies across simulated time |
| Mobilise-donor backend | Stubbed — `handleMobilizeRequest()` in App.tsx logs to console only |
| Authentication / RBAC | None — CORS allows all origins (`*`) |
| Production Dockerfile | Not present — no Nginx config or gunicorn setup |
| Automated test suite | Not present — correctness relies on engine-level assertion guards |
