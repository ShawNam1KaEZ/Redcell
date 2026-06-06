# 11 — Glossary

## Canonical Entity IDs

| ID Pattern | Example | Where defined | Meaning |
|------------|---------|--------------|---------|
| `PAT-NNNN` | `PAT-0001` | `hemogrid/sources/synthetic_source.py:486` | Tokenized patient ID (4-digit zero-padded integer; no real identity) |
| `PAT-LIVE-NNNN` | `PAT-LIVE-0001` | `hemogrid/sources/live_source.py:468` | Live hackathon CSV patient (Bridge Fighter/Patient role) |
| `PAT-LIVE-UNNNN` | `PAT-LIVE-U0001` | `hemogrid/sources/live_source.py:596` | Live user_data CSV patient |
| `PAT-EMERG-99` | `PAT-EMERG-99` | `hemogrid/sources/synthetic_source.py:849` | Emergency test patient (O-, 4 alloantibodies, CLN-KOL-01) |
| `DON-NNNN` | `DON-0002` | `hemogrid/sources/synthetic_source.py:426` | Tokenized synthetic donor ID |
| `DON-LIVE-NNNN` | `DON-LIVE-0001` | `hemogrid/sources/live_source.py:411` | Live hackathon CSV donor |
| `DON-LIVE-UNNNN` | `DON-LIVE-U0001` | `hemogrid/sources/live_source.py:547` | Live user_data CSV donor |
| `BB-NNNN` | `BB-0036` | `hemogrid/sources/synthetic_source.py:249` | Blood bank token (1-based sequential from CSV row order) |
| `CLN-XXX-01` | `CLN-GNT-01` | `hemogrid/sources/synthetic_source.py:347` | Clinic ID (3-letter city code + 01) |
| `REQ-GRAPH-{pid}` | `REQ-GRAPH-PAT-0001` | `hemogrid/agents/graph.py:219` | Request created by `forecast_node` in agent graph |
| `REQ-API-{pid}` | `REQ-API-PAT-0001` | `hemogrid/api/main.py:528` | Request created by `/match` endpoint |

## Clinic IDs

| ID | City | Region |
|----|------|--------|
| `CLN-GNT-01` | Guntur | Andhra Pradesh |
| `CLN-HYD-01` | Hyderabad | Telangana |
| `CLN-CHN-01` | Chennai | Tamil Nadu |
| `CLN-BLR-01` | Bengaluru | Karnataka |
| `CLN-MUM-01` | Mumbai | Maharashtra |
| `CLN-AHM-01` | Ahmedabad | Gujarat |
| `CLN-DEL-01` | Delhi | Delhi |
| `CLN-KOL-01` | Kolkata | West Bengal |
| `CLN-LKN-01` | Lucknow | Uttar Pradesh |

## Lever Names

| Lever | String value | Enum | Meaning |
|-------|-------------|------|---------|
| Inventory lever | `"inventory"` | `Lever.INVENTORY` | Redistribute PRBC unit from nearby blood bank |
| Donor lever | `"donor"` | `Lever.DONOR` | Activate eligible bonded/matched voluntary donor |
| Emergency lever | `"emergency"` | `Lever.EMERGENCY` | Escalate to regional emergency network |

## Status Values

### `RequestStatus` (enum in `models/enums.py`)

| Value | Meaning |
|-------|---------|
| `"predicted"` | Request created by engine; not yet proposed to coordinator |
| `"proposed"` | HITL proposal sent to coordinator |
| `"approved"` | Coordinator approved the action |
| `"fulfilled"` | Action completed |

### `GraphState.status` (string in `agents/graph.py`)

| Value | Set by |
|-------|--------|
| `"predicted"` | Initial state |
| `"approved"` | `approval_gate_node` when coordinator approves |
| `"declined"` | `approval_gate_node` when coordinator rejects |
| `"fulfilled"` | `redistribution_node`, `donor_matching_node`, `emergency_node` |

### `PatientSummary.status` (API, from `_DEMO_CACHE`)

| Value | Meaning |
|-------|---------|
| `"pending"` | No decision made |
| `"approved"` | Coordinator approved (`APPROVED` in `_DEMO_CACHE`) |
| `"rejected"` | Coordinator rejected (`REJECTED` in `_DEMO_CACHE`) |

## Provenance Tags

| Tag | String value | Meaning |
|-----|-------------|---------|
| `Provenance.PROVIDED` | `"provided"` | Field value came directly from source column |
| `Provenance.DERIVED` | `"derived"` | Field computed from source data |
| `Provenance.SYNTHETIC` | `"synthetic"` | Field fabricated; no source exists for it |

## Desert Classification Terms

| Term | Classification rule | Meaning |
|------|-------------------|---------|
| `"SUPPLY_LIMITED"` | `supply_gap > compatibility_gap` | Volume shortfall: shelf too thin |
| `"COMPATIBILITY_LIMITED"` | `compatibility_gap > supply_gap` | Immunological barrier: inventory exists but antibody-unsafe |
| `"MIXED"` | `compatibility_gap == supply_gap` and both > 0 | Both failure modes present |
| `"OK"` | `desert_score == 0` | Demand fully met |
| `"CHRONIC"` | `classification == "COMPATIBILITY_LIMITED"` AND `score >= 10` | Structural, persistent immunological barrier |
| `"ACUTE"` | Any non-zero score not meeting CHRONIC criteria | Transient or supply shortfall |

## Agent Names (in `trace` events)

| Agent label | Node | What it does |
|-------------|------|-------------|
| `"Demand Forecasting"` | `forecast` | Calls `forecast_due()`, builds `Request` |
| `"Blood Desert Detection"` | `desert` | Calls `compute_desert_cells()` |
| `"Supply Strategy Orchestrator"` | `orchestrate` | Calls `choose_lever()`, LLM narration |
| `"HITL Approval Gate"` | `approval` | `interrupt()` / resumes with coordinator decision |
| `"Redistribution"` | `redistribution` | Finalises inventory path |
| `"Donor Matching"` | `donor_matching` | Finalises donor path |
| `"Emergency Escalation"` | `emergency` | Finalises emergency path |
| `"Action Declined"` | `declined` | Finalises declined path |

## Environment Variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `HEMOGRID_USE_LIVE_DATA` | `"true"` | `"false"` → SyntheticSource; else → LiveHybridSource |
| `HEMOGRID_LLM_PROVIDER` | `"ollama"` | `"ollama"`, `"off"`, `"none"`, `"stub"` |
| `HEMOGRID_LLM_MODEL` | `"qwen2.5:7b"` | Ollama model name |
| `OLLAMA_HOST` | `"http://localhost:11434"` | Ollama server URL |
| `HEMOGRID_LLM_TIMEOUT` | `"20.0"` | LLM HTTP timeout in seconds |

## Acronyms

| Acronym | Full form | Context |
|---------|-----------|---------|
| PRBC | Packed Red Blood Cells | Blood component type; the only component matched by the engine |
| HITL | Human-in-the-Loop | The mandatory coordinator approval gate before any action is committed |
| RFM | Recency-Frequency-Monetary | Donor engagement model from UCI dataset; Monetary is dropped in HemoGrid |
| ABO | Blood group system (A, B, AB, O) | Standard blood compatibility classification |
| RhD | Rhesus D antigen | The +/- in blood type; HemoGrid enforces strict Rh-negative-only rule for Rh-negative recipients |
| NBTC | National Blood Transfusion Council | Indian regulatory body; 90-day deferral rule implemented in `donor_eligible()` |
| SBTC | State Blood Transfusion Council | Referred to in emergency escalation text for PAT-EMERG-99 |
| NGO | Non-Governmental Organisation | Blood Bridge is described as an NGO initiative |
| CSR | Corporate Social Responsibility | Framing context for the hackathon |
| CWD | Current Working Directory | Relevant because `SyntheticSource` resolves `data_dir` relative to `__file__`, not CWD |
| e-RaktKosh | Electronic Rakt Kosh | Government of India national blood bank registry; source of `data/blood-banks.xls` |
| UCI | University of California Irvine | Source of the blood transfusion dataset used for the reliability scorer |
| dto | Data Transfer Object | Response model classes in `api/main.py` that are separate from canonical models |
| AUC | Area Under the ROC Curve | 0.755 for the donor reliability logistic regression |

## Transport Tier Definitions

| Tier | Threshold | Meaning |
|------|-----------|---------|
| Tier 0 | `dist_km <= 5.0` | Local delivery |
| Tier 1 | `dist_km > 5.0` | Far delivery |

Tier is used as the first sort key in `collect_inventory_candidates()` — tier 0 candidates always rank above tier 1 regardless of expiry.

## Key Numerical Constants

| Constant | Value | Location | Meaning |
|----------|-------|----------|---------|
| `seed` | `42` | `SyntheticSource.__init__` default | NumPy RNG seed for reproducible synthetic data |
| `n_donors` | `900` | `_generate_donors()` | Count of synthetic donors |
| `n_patients` | `200` | `_generate_patients()` | Count of synthetic random patients (before post-RNG additions) |
| `allo_rate` | `0.20` | `_generate_patients()` | Fraction of patients with alloantibodies |
| `bond_rate` | `0.25` | `_make_bonds()` | Fraction of non-demo donors bonded to patients |
| `RHD_POS_PROB` | `0.94` | `enrichment.py:35` | P(RhD-positive) in Indian population |
| `K_PRESENT_PROB` | `0.030` | `enrichment.py:47` | P(Kell K antigen present) in Indian donors |
| `_SEARCH_RADIUS_KM` | `100.0` | `engine.py:48`, `graph.py:42` | Default search radius for candidates |
| `_TRANSPORT_LOCAL_KM` | `5.0` | `engine.py:54` | Tier 0 distance threshold |
| `_REDISTRIBUTION_SPEED_KMH` | `40.0` | `engine.py:55` | Road transport speed (km/h) |
| `_DONOR_PIPELINE_DAYS` | `4` | `engine.py:56` | Days for donor activation pipeline |
| `_BOND_BONUS` | `0.40` | `engine.py:46` | Score bonus for bonded donors |
| `_CATCHMENT_KM` | `80.0` | `live_source.py:54` | Hyderabad bank retention radius (live mode) |
| `TODAY_SIMULATION` | `date(2026, 6, 5)` | `live_source.py:52` | Hardcoded date anchor for live patient records |
| `NBTC_deferral_days` | `90` | `engine.py:201` | Minimum days between donations |
