# HemoGrid — File Index

Generated: 2026-06-06 | Branch: main | Commit: 4e34dba (phase 2)

Every file in the repository is listed below (excluding `.git/`, `node_modules/`, `__pycache__/`, `frontend/dist/`, `.venv/`).

---

## Python source files

| Path | Lines | Description |
|------|-------|-------------|
| `hemogrid/__init__.py` | 7 | Package root; documents public surface (`hemogrid.models`, `hemogrid.sources`). |
| `hemogrid/enrichment.py` | 105 | Indian population-frequency constants (ABO, RhD, extended Rh, Kell) and RNG sampling helpers for synthetic generation. |
| `hemogrid/engine.py` | 751 | Pure deterministic matching, ranking, forecasting, desert decomposition, lever selection, and deliverability engine. No LLM, no I/O. |
| `hemogrid/llm.py` | 577 | Single LLM call site (`generate()`), three public narration/draft functions, deterministic fallback templates, golden profile intercepts, Ollama HTTP helpers. |
| `hemogrid/profiler.py` | 431 | Day-of dataset profiler: shape, coordinate quality, canonical readiness via token-overlap Jaccard matching. |
| `hemogrid/storage.py` | 78 | Abstract `Repository[T]` interface and `InMemoryRepository` implementation. Cloud-swap point. |
| `hemogrid/models/__init__.py` | 39 | Re-exports all canonical models and enums from the `models/` sub-package. |
| `hemogrid/models/enums.py` | 39 | All enumerations: `Provenance`, `ABOGroup`, `Component`, `BankCategory`, `Lever`, `RequestStatus`. |
| `hemogrid/models/common.py` | 51 | `CanonicalModel` base (provenance dict), `Location`, `Phenotype`, `Consent` sub-models. |
| `hemogrid/models/patient.py` | 31 | `Patient` canonical model. |
| `hemogrid/models/donor.py` | 37 | `Donor` canonical model. |
| `hemogrid/models/blood_bank.py` | 59 | `BloodBank` and `InventoryUnit` canonical models. |
| `hemogrid/models/clinic.py` | 16 | `Clinic` canonical model. |
| `hemogrid/models/request.py` | 27 | `Request` canonical model. |
| `hemogrid/models/dataset.py` | 24 | `CanonicalDataset` container returned by every `DataSource.load()`. |
| `hemogrid/sources/__init__.py` | 5 | Exports `DataSource` (abstract), `OrganizerAdapter` (stub), `SyntheticSource`, `LiveHybridSource`. |
| `hemogrid/sources/base.py` | 37 | `DataSource` ABC with `source_name` property and `load() -> CanonicalDataset` method. |
| `hemogrid/sources/organizer_adapter.py` | 40 | Stub `OrganizerAdapter` — the one file to edit on hackathon day. Both methods raise `NotImplementedError`. |
| `hemogrid/sources/synthetic_source.py` | 1030 | `SyntheticSource` — working data source. Loads real blood banks from e-RaktKosh CSV; generates synthetic clinics, donors, patients, bonds, inventory with seed=42 RNG. |
| `hemogrid/sources/live_source.py` | 826 | `LiveHybridSource` — hybrid source. Runs `SyntheticSource` first, then parses `newdata/` CSV files, prunes banks to 80 km Hyderabad catchment, seeds inventory. |
| `hemogrid/agents/__init__.py` | 15 | Re-exports `GraphState`, `approve_request`, `build_graph`, `propose_request`, `run_request`. |
| `hemogrid/agents/graph.py` | 825 | LangGraph orchestration: `GraphState`, 8 nodes, HITL interrupt gate, `_agent_select` bounded loop, `run_request` / `propose_request` / `approve_request` entry points. |
| `hemogrid/api/__init__.py` | 0 | Empty init (package marker). |
| `hemogrid/api/main.py` | 812 | FastAPI application: response DTOs, lifespan (data load + repo init), all endpoints, `_DEMO_CACHE` volatile state. |

## Frontend source files

| Path | Lines | Description |
|------|-------|-------------|
| `frontend/src/main.tsx` | 10 | React entry point; mounts `<App />` into `#root`. |
| `frontend/src/App.tsx` | 7 | Root component; renders `<MapView />` only. |
| `frontend/src/MapView.tsx` | 1136 | Primary UI: 3-column split-grid layout (Triage Matrix / Map / Intelligence Panel), Leaflet map, HITL approval workflow, SMS gateway panel. |
| `frontend/src/MapView.css` | 2338 | Complete stylesheet for `MapView.tsx`; defines all `.hg-*` and `.tactical-*` class rules. |
| `frontend/src/GridSimulator.tsx` | 255 | Slide-up `GridSimulator` widget: 2-slider demand/allo simulation, 3×3 city grid, deterministic CHRONIC/ACUTE/MIXED classification. |
| `frontend/src/api.ts` | 343 | Typed API client: all interfaces mirroring backend DTOs, fetch functions for every endpoint, chaos-mode header injection. |
| `frontend/src/App.css` | 184 | Root app styles; mostly unused given MapView.css covers all UI. |
| `frontend/src/index.css` | 12 | Global CSS resets. |
| `frontend/index.html` | 13 | HTML entry point; mounts `<div id="root">`. |

## Configuration files

| Path | Lines | Description |
|------|-------|-------------|
| `frontend/package.json` | 33 | Frontend deps (React 19, Leaflet, react-leaflet) and devDeps (Vite 8, TypeScript 6, ESLint). |
| `frontend/package-lock.json` | 2778 | Lockfile for frontend npm dependencies. |
| `frontend/vite.config.ts` | 7 | Vite config; only plugin: `@vitejs/plugin-react`. No proxy configured. |
| `frontend/tsconfig.json` | 7 | TypeScript project references config (delegates to tsconfig.app.json and tsconfig.node.json). |
| `frontend/tsconfig.app.json` | 25 | App TS config: target ES2020, bundler module resolution, strict mode, `noUnusedLocals`, `noUnusedParameters`. |
| `frontend/tsconfig.node.json` | 24 | Node TS config for Vite tooling. |
| `frontend/eslint.config.js` | 22 | ESLint config: `react-hooks` and `react-refresh` plugins, type-checked TS rules. |
| `frontend/.gitignore` | 24 | Frontend-specific gitignore (dist, node_modules, .env). |
| `frontend/README.md` | 73 | Vite-generated default README (not project-specific). |
| `.gitignore` | 27 | Root gitignore: Python artifacts, venv, IDE, OS files. |
| `CLAUDE.md` | 40 | Project specification/instructions for Claude (may be stale — see [docs/10](10-data-flow-and-known-issues.md)). |
| `README.md` | 1 | Placeholder root README (single line). |

## Data files

| Path | Lines (rows+header) | Encoding | Columns | Verified rows | Description |
|------|---------------------|----------|---------|---------------|-------------|
| `data/blood-banks.xls` | 3384 (3383+1) | cp1252 | 27 | 2823 (parsed by pandas; 6 `(Repeated)` dropped → 2817 canonical banks) | e-RaktKosh national blood bank directory. Extension is `.xls` but file is actually a CSV. |
| `data/uci_blood_transfusion.csv` | 749 (748+1) | UTF-8 | 5 | 748 | UCI Blood Transfusion Service Center dataset. Columns: `Recency`, `Frequency`, `Monetary`, `Time`, `Donated_Blood`. Used to train the donor reliability logistic regression. |
| `newdata/Hackathon Data_5000.csv` | ~7034 | UTF-8 | 31 | 7033 | Live hackathon Blood Bridge registry. Contains donors (Bridge/Emergency Donor roles) and patients (Fighter/Patient roles) with blood groups, coordinates, and donation metadata. Read by `LiveHybridSource`. |
| `newdata/BW_Sample_Data_Updated_v3.xlsx - user_data.csv` | ~201 | UTF-8 | 10 | 200 | Supplementary user registry (city-based geocoding). Columns: `user_id`, `name`, `gender`, `mobile`, `date_of_birth`, `blood_group`, `city`, `pincode`, `role`, `insert_time`. Read by `LiveHybridSource`. |
| `newdata/cleaned_thalassemia_data.csv` | 7034 | UTF-8 | 31 | 7033 | Cleaned version of `Hackathon Data_5000.csv` (different bytes/size; same shape). **NOT read by any source code.** Candidate "new data" that is not wired up. |

### blood-banks.xls — Full column list
`Sr No`, `Blood Bank Name`, `State`, `District`, `City`, `Address`, `Pincode`, `Contact No`, `Mobile`, `Helpline`, `Fax`, `Email`, `Website`, `Nodal Officer`, `Contact Nodal Officer`, `Mobile Nodal Officer`, `Email Nodal Officer`, `Qualification Nodal Officer`, `Category`, `Blood Component Available`, `Apheresis`, `Service Time`, `License #`, `Date License Obtained`, `Date of Renewal`, `Latitude`, `Longitude`

### Hackathon Data_5000.csv — Full column list
`user_id`, `bridge_id`, `role`, `role_status`, `bridge_status`, `blood_group`, `gender`, `latitude`, `longitude`, `bridge_gender`, `bridge_blood_group`, `quantity_required`, `last_transfusion_date`, `expected_next_transfusion_date`, `registration_date`, `donor_type`, `last_contacted_date`, `last_donation_date`, `next_eligible_date`, `donations_till_date`, `eligibility_status`, `cycle_of_donations`, `total_calls`, `frequency_in_days`, `status_of_bridge`, `status`, `donated_earlier`, `last_bridge_donation_date`, `calls_to_donations_ratio`, `user_donation_active_status`, `inactive_trigger_comment`

### BW_Sample_Data_Updated_v3.xlsx - user_data.csv — Full column list
`user_id`, `name`, `gender`, `mobile`, `date_of_birth`, `blood_group`, `city`, `pincode`, `role`, `insert_time`

## Scripts and utility files

| Path | Lines | Description |
|------|-------|-------------|
| `scripts/verify_p4s1.py` | 109 | Phase 4 Step 1 verification: PAT-0001 inventory lever, BB-0036, distance, expiry. |
| `scripts/verify_p4s2.py` | 255 | Phase 4 Step 2 verification: PAT-0001 donor lever (bypassed inventory), DON-0002 bond, match score. |
| `scripts/verify_p4s3.py` | 122 | Phase 4 Step 3 verification: PAT-EMERG-99 emergency lever. |
| `scripts/verify_live_agent.py` | 153 | Verification script for LiveHybridSource with LangGraph agent. |
| `scripts/verify_live_source.py` | 202 | Verification script for LiveHybridSource loading and data counts. |
| `stage_dry_run_audit.py` | 321 | Comprehensive audit script: checks BB-0036 inventory, DON-0002 bond, CLN-HYD-01 desert score, PAT-EMERG-99 emergency lever. |
| `test_p5_s1_fallback.py` | 197 | Phase 5 Step 1 test: verifies LLM chaos intercept and golden fallback narration. |
| `verify_step3.py` | 193 | Step 3 verification: engine choose_lever, rank_matches. |
| `verify_step3_5.py` | 230 | Step 3.5 verification: desert decomposition. |
| `verify_step3_6.py` | 414 | Step 3.6 verification: compute_desert_cells, HITL graph flow. |
| `uvicorn_out.txt` | 7 | Captured stdout from a previous uvicorn startup (SyntheticSource load log). |
| `uvicorn_err.txt` | 6 | Captured stderr from a previous uvicorn startup (port conflict error). |

## Frontend public and asset files

| Path | Description |
|------|-------------|
| `frontend/public/favicon.svg` | Favicon SVG. |
| `frontend/public/icons.svg` | Icon sprite SVG. |
| `frontend/src/assets/hero.png` | Hero image asset (not referenced by any visible component). |
| `frontend/src/assets/react.svg` | Default React logo SVG (unused in production code). |
| `frontend/src/assets/vite.svg` | Default Vite logo SVG (unused in production code). |
