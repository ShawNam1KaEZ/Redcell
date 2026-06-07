# HemoGrid

> **The right unit, not just a compatible unit** — extended-phenotype blood matching for thalassemia patients in Hyderabad & Telangana, India.

[![Python](https://img.shields.io/badge/Python-3.10+-3776ab?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61dafb?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-6-3178c6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The problem

Thalassemia patients receive blood transfusions every 2–4 weeks for life. Most blood bank systems issue the nearest ABO-compatible unit and stop there — ignoring 14 additional red-cell antigens (C, c, E, e, K, k, Jka, Jkb, Fya, Fyb, M, N, S, s). Over years of transfusions this causes **alloimmunization**: the patient's immune system forms antibodies against donor antigens, making every future match harder and, eventually, life-threatening.

No open-source extended-phenotype matching tool exists for India's thalassemia centres.

## The solution

HemoGrid checks up to 14 antigens against every antibody a patient has ever formed, then ranks blood-bag candidates by **phenotype concordance** — how closely the donor's full antigen profile mirrors the patient's own. The result is a tiered recommendation a clinician can act on in seconds:

| Tier | Meaning |
|------|---------|
| **G1 Exact** | Typed donor · ABO identical · all tested antigens match · antibody-safe |
| **G2 Compatible** | ABO-compatible · Rh+K floor · antibody-safe (untyped donors flagged below typed) |
| **G3 Emergency** | Only when G1+G2 are empty; never auto-issued — requires clinical review |
| **Excluded** | Failed a safety gate, with a machine-readable reason code |

---

## Demo

<!-- TODO: Replace the placeholder below with your actual screenshot or GIF -->
<!-- Suggested content: a screen recording of selecting a patient and watching G1/G2/G3 tiers populate in the right panel, then clicking "Explain" for the AI rationale -->

```
[Drop your dashboard screenshot or animated GIF here]
```

---

## Key features

- **14-antigen extended-phenotype matching** — phenotype concordance % is the primary sort key, not an afterthought
- **Hard antibody safety gate** — every allo and auto antibody (active *and* historical) is checked; auto-antibody patients route directly to G3 and can never be auto-issued
- **Untyped-donor policy** — untyped donors are blocked entirely for immunized patients; allowed but explicitly flagged for non-immunized ones
- **Live inventory by derived query** — bag counts are never stored; always computed as `status='available' AND expiry_date >= TODAY`, guaranteeing consistency mid-simulation
- **30-day depletion forecast** — day-by-day simulation with CRITICAL / WARNING / STABLE severity per blood type per bank
- **Haversine routing** — distance and ETA (25 km/h Hyderabad urban speed) from real GPS coordinates; units >50 km get a `long_haul_fetch` risk flag
- **Mutation-safe simulation** — issue, donate, transfer, and reset operations carry loud assertion guards; any failure rolls back immediately
- **Local AI explanations** — `/api/match/{id}/explain` calls a locally-hosted Ollama `phi3` model for 2–4 bullet clinical rationales; zero cloud cost, zero data leakage
- **Interactive Leaflet map** — real Hyderabad basemap; click any blood bank for live inventory; click any facility for its patient roster
- **Privacy-preserving display** — map uses jittered coordinates (Rayleigh σ = 300 m); the matcher always uses real GPS

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Data layer | Pandas, SQLite (stdlib `sqlite3`), openpyxl |
| Frontend | React 19, TypeScript, Vite 8, React-Leaflet |
| AI (optional) | Ollama `phi3` — local, no cloud key required |
| Map tiles | CartoDB Positron (free, no API key) |

---

## Setup & installation

### Prerequisites

- Python 3.10+ with pip
- Node.js 18+ with npm
- [Ollama](https://ollama.com) — **optional**, only needed for the AI explanation endpoint

### 1. Clone

```bash
# TODO: Replace with your actual repo URL
git clone https://github.com/<!-- TODO: your-github-username -->/hemogrid.git
cd hemogrid
```

### 2. Backend

```bash
pip install -r requirements.txt
python main.py
```

Expected startup output:

```
[PASS] Startup assert: 536 available bags in baseline CSV.
[INFO] Live DB currently has 536 available bags.
FastAPI server successfully active with CORS middleware enabled. Ready for UI binding.
```

Server: `http://localhost:8000` · Interactive API docs: `http://localhost:8000/docs`

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard: `http://localhost:5173` — all `/api/*` calls proxy automatically to `:8000`.

### 4. AI explanations (optional)

```bash
# Install Ollama from https://ollama.com, then:
ollama pull phi3
# Ollama listens on http://localhost:11434 by default
```

If Ollama is not running, the `/api/match/{id}/explain` endpoint returns an empty string silently — all other functionality works without it.

---

## Environment variables

The app runs without any `.env` file — all values have hardcoded defaults for local development. For deployment, copy `.env.example` to `.env` and adjust:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint for AI explanations |
| `PORT` | `8000` | FastAPI server bind port |
| `DATA_DIR` | `./data/build` | Path to canonical CSV dataset |
| `TODAY` | `2026-06-06` | Pinned demo date (intentional — dataset is forward-dated to match synthetic data) |

> **Note:** The app currently uses hardcoded defaults. For AWS or other cloud deployment, update `main.py` and the engine modules to read from `os.environ` before setting env vars.

---

## CLI utilities

```bash
# Run the matching engine over all 164 patients (prints G1/G2/G3 tier counts)
python -m engine.match

# Full state engine self-test: reset → issue → donate → all assertion guards
python -m engine.state --test-flow

# Routing self-test: haversine + ETA spot checks
python -m engine.routing --self-test

# Rebuild the dataset from raw inputs (deterministic, RANDOM_SEED=42)
python build_datasets.py && python build_jitter.py && python build_map.py
```

## Reset simulation

```bash
# Via HTTP (while server is running)
curl -X POST http://localhost:8000/api/state/reset

# Or directly from Python
python -c "from engine import state; state.reset_simulation_state()"
```

---

## API reference

FastAPI auto-generates interactive docs at `http://localhost:8000/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/inventory` | Live derived bag counts per bank per blood type |
| `GET` | `/api/patient/{id}/match` | Full G1/G2/G3/excluded tier results for a patient |
| `GET` | `/api/match/{id}/explain` | AI-generated clinical rationale (requires Ollama) |
| `GET` | `/api/forecast` | 30-day depletion forecast with CRITICAL/WARNING/STABLE severity |
| `GET` | `/api/patients` | Patient roster |
| `GET` | `/api/donors` | Donor roster |
| `GET` | `/api/map-data` | Spatial data for Leaflet map |
| `GET` | `/api/logs` | Activity log entries, newest first |
| `POST` | `/api/actions/treat` | Issue a bag to a patient |
| `POST` | `/api/actions/donate` | Register a new donation |
| `POST` | `/api/state/reset` | Reset simulation to 536-bag baseline |

---

## Project structure

```
hemogrid/
├── main.py                     FastAPI gateway — 11 endpoints, startup asserts
├── requirements.txt            Python dependencies
│
├── engine/
│   ├── match.py                Gate → Rank → Tier matching algorithm
│   ├── state.py                SQLite state manager + mutation guards
│   ├── routing.py              Haversine distance, ETA, long-haul detection
│   ├── forecast.py             30-day inventory depletion simulation
│   └── ai.py                   Ollama phi3 integration
│
├── frontend/
│   ├── src/App.tsx             3-column dashboard (patients · map · matches)
│   ├── src/App.css             Component styles
│   ├── package.json            Frontend dependencies (React 19 + Leaflet + Vite)
│   └── vite.config.ts          Dev server config + /api proxy
│
├── data/
│   ├── Dataset.csv             Raw source data (7 033 rows × 33 columns)
│   ├── blood-banks.xls         Blood-bank reference — Telangana state directory
│   └── build/                  Canonical processed dataset (source of truth — do not edit by hand)
│       ├── donors.csv          4 439 donors (85% phenotype-typed)
│       ├── patients.csv        164 thalassemia patients (100% typed)
│       ├── bags.csv            2 417 blood bags (536 available at baseline)
│       ├── antibodies.csv      51 patient antibody records
│       ├── banks.csv           149 blood banks (13 with live inventory)
│       ├── facilities.csv      21 treatment facilities
│       └── map/                Static Leaflet map (open via python -m http.server)
│
├── build_datasets.py           Phase 1: extract real data + fill synthetic gaps
├── build_jitter.py             Phase 2: add privacy-jittered display coordinates
└── build_map.py                Phase 3: generate Leaflet map files
```

---

## Dataset & methodology

- **4 439 donors** (85% phenotype-typed), **164 thalassemia patients** (100% typed), **2 417 blood bags**
- Real data: geocoordinates from Telangana state blood-bank directory; blood-type antigen frequencies from Makroo et al. (2013)
- Synthetic gap-fill: 18% alloimmunization rate (literature-grounded); all synthesis seeded at `RANDOM_SEED=42` for full reproducibility
- Privacy: display coordinates on the map are jittered (Rayleigh σ = 300 m, capped at 700 m); the matching engine always uses precise real GPS

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for component diagrams and design decisions.

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## License

<!-- TODO: Confirm author/organization name -->
MIT © 2026 <!-- TODO: Author Name -->. See [LICENSE](LICENSE).
