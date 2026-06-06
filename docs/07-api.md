# 07 — API

Base URL: `http://localhost:8000`

CORS: `allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]`, `allow_methods=["GET", "POST"]`, `allow_headers=["*"]`

App: `FastAPI(title="HemoGrid API", version="0.1.0")`

---

## `GET /api/health`

Response model: `HealthResponse`

No parameters.

**Response**:
```json
{
  "status": "ok",
  "dataset": {
    "donors": 900,
    "patients": 217,
    "banks": 2817,
    "valid_coord_banks": 1842,
    "inventory_units": 1295
  },
  "live_mode": false
}
```

`live_mode` reflects `HEMOGRID_USE_LIVE_DATA != "false"`. The frontend reads this to switch map viewport between India-wide (synthetic) and Hyderabad-centred (live).

---

## `GET /api/banks`

Response model: `list[BankSummary]`

**Query parameters**:
- `valid_only: bool = True` — if true, only returns banks with `coord_valid=True`
- `district: Optional[str] = None` — case-insensitive district filter

**Response** (each item):
```json
{
  "bank_id": "BB-0036",
  "name": "Government General Hospital Guntur",
  "lat": 16.3069,
  "lng": 80.4365,
  "category": "Government",
  "does_components": true,
  "district": "Guntur",
  "state": "Andhra Pradesh",
  "coord_valid": true
}
```

Source: `app.state.bank_repo.list_all()` → filter → `_to_summary()` DTO conversion.

Decision logic: None. Pure data retrieval.

---

## `GET /api/deserts`

Response model: `list[CellDesertScore]`

**Query parameters**:
- `radius_km: float = 50.0` (ge=10.0, le=200.0) — supply search radius around each clinic
- `lead_days: int = 7` (ge=1, le=30) — patients due within this many days count as demand
- `simulate_timeout: bool = False` — stage demo: force LLM fallback

**Header**: `X-HemoGrid-Chaos: inject-timeout` — same effect as `simulate_timeout=true`

**Response** (each item):
```json
{
  "cell_id": "CLN-HYD-01",
  "lat": 17.385,
  "lng": 78.4867,
  "name": "Hyderabad Thalassaemia Centre",
  "patients_due": 12,
  "demand_units": 24,
  "raw_units": 38,
  "safe_units": 4,
  "met": 4,
  "compatibility_gap": 20,
  "supply_gap": 0,
  "desert_score": 20,
  "desert_type": "COMPATIBILITY_LIMITED",
  "nearest_safe_inventory_km": 0.3,
  "eligible_matched_donors_nearby": 2,
  "classification": "CHRONIC",
  "structural_recommendation": "Cell CLN-HYD-01 (Hyderabad) carries a chronic structural blood desert score..."
}
```

**Processing**:
1. Calls `engine.compute_desert_cells(app.state.dataset, date.today(), radius_km, lead_days)`
2. Applies `_DEMO_CACHE["cell_adjustments"]` if any approved dispatches exist
3. For each cell: calls `llm.narrate_structural_recommendation(cell_id, classification, score, desert_type)`
4. Prints CLN-HYD-01 debug log

**Demo adjustment logic**: When an inventory dispatch is approved via `/approve`, `cell_adjustments[clinic_id]` is incremented. At `/api/deserts` call time, `c["met"]` is incremented by `met_delta` and `c["supply_gap"]` is decremented by `supply_gap_delta`. `desert_score` is recalculated as `abs(compatibility_gap) + supply_gap`. This is purely cosmetic/display logic — it does not change `app.state.dataset`.

---

## `GET /api/patients`

Response model: `list[PatientSummary]`

**Query parameters**:
- `clinic_id: Optional[str] = None` — filter by clinic_id
- `due_soon: bool = False` — only return patients due within 7 days

**Response** (each item):
```json
{
  "patient_id": "PAT-0001",
  "abo": "B",
  "rh_d": true,
  "known_antibodies": ["anti-K"],
  "clinic_id": "CLN-GNT-01",
  "days_until_due": 5,
  "due_soon": true,
  "units_per_session": 1,
  "status": "pending"
}
```

`status` is looked up from `_DEMO_CACHE["patient_statuses"]`: `"APPROVED"` → `"approved"`, `"REJECTED"` → `"rejected"`, missing → `"pending"`.

Response is sorted by `days_until_due` ascending.

---

## `GET /api/patients/{patient_id}/match`

Response model: `MatchResult`

No body. 404 if `patient_id` not in `patient_repo`.

**Processing**:
1. Calls `engine.forecast_due(patient, today)` → `next_need_date`
2. Creates `Request(request_id=f"REQ-API-{patient_id}", ...)`
3. Calls `engine.choose_lever(req, dataset, today)` → `lever_result`
4. Calls `engine.collect_inventory_candidates(patient, clinic_loc, dataset, today)` → `inv_candidates`
5. Calls `engine.rank_matches(req, nearby_donors, dataset, today)` → `donor_ranking`
6. Serialises top 10 from each

**Response**:
```json
{
  "patient_id": "PAT-0001",
  "abo": "B",
  "rh_d": true,
  "known_antibodies": ["anti-K"],
  "days_until_due": 5,
  "chosen_lever": "inventory",
  "chosen_inventory": {
    "bank_id": "BB-0036",
    "bank_name": "Government General Hospital Guntur",
    "component": "PRBC",
    "abo": "B",
    "rh_d": true,
    "phenotype_tags": {"C": true, "c": true, "E": false, "e": true, "K": false},
    "days_to_expiry": 3,
    "distance_km": 0.7,
    "inventory_options": 1
  },
  "chosen_donor": null,
  "ranked_inventory": [
    {"rank": 1, "bank_id": "BB-0036", "bank_name": "...", "abo": "B", "rh_d": true, "days_to_expiry": 3, "distance_km": 0.7}
  ],
  "ranked_donors": [
    {"rank": 1, "donor_id": "DON-0002", "abo": "B", "rh_d": true, "distance_km": 2.4, "reliability": 0.28, "phenotype_quality": 1.0, "bonded": true, "score": 0.9141}
  ],
  "reasoning": "Redistribute near-expiry unit from Government General Hospital Guntur..."
}
```

**Decision logic**: None in endpoint. `choose_lever()` decides; endpoint serialises.

---

## `POST /api/patients/{patient_id}/propose`

Response model: `ProposalResponse`

**Query parameters**: `simulate_timeout: bool = False`
**Header**: `X-HemoGrid-Chaos: inject-timeout`

**Processing**:
1. Calls `agents.propose_request(patient_id, dataset, today)` → paused graph
2. Stores `{patient_id, bank_id, chosen_lever, clinic_id}` in `_DEMO_CACHE["pending_proposals"][thread_id]`

**Response**:
```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "awaiting_approval",
  "proposal": {
    "patient_id": "PAT-0001",
    "chosen_lever": "inventory",
    "proposed_action": {
      "type": "redistribute",
      "recipient": "PAT-0001",
      "bank_id": "BB-0036",
      "bank_name": "Government General Hospital Guntur",
      "days_to_expiry": 3,
      "distance_km": 0.7
    },
    "reasoning": "Redistribute near-expiry unit..."
  },
  "events_so_far": [
    {"step_index": 0, "agent": "Demand Forecasting", "node": "forecast", "summary": "PAT-0001 due in 5d...", "details": {...}},
    {"step_index": 1, "agent": "Blood Desert Detection", "node": "desert", "summary": "CLN-GNT-01 · score=... · ...", "details": {...}},
    {"step_index": 2, "agent": "Supply Strategy Orchestrator", "node": "orchestrate", "summary": "chosen_lever=inventory", "details": {...}},
    {"step_index": 3, "agent": "HITL Approval Gate", "node": "approval", "summary": "Awaiting coordinator approval...", "details": {...}}
  ],
  "donor_message_draft": null,
  "emergency_reasoning": null
}
```

For donor lever: `donor_message_draft` is populated (LLM or template). For emergency lever: `emergency_reasoning` is populated.

---

## `POST /api/patients/{patient_id}/approve`

Response model: `ApproveResponse`

**Request body**:
```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "decision": "approve"
}
```

`decision`: `"approve"` or `"reject"`

**Processing**:
1. Calls `agents.approve_request(body.thread_id, body.decision)` → resumes paused graph
2. Pops `_DEMO_CACHE["pending_proposals"][thread_id]`
3. If `decision == "approve"`:
   - Sets `_DEMO_CACHE["patient_statuses"][patient_id] = "APPROVED"`
   - If `chosen_lever == "inventory"` and `bank_id` present: increments `_DEMO_CACHE["bank_adjustments"][bank_id]`
   - If `clinic_id` present: increments `_DEMO_CACHE["cell_adjustments"][clinic_id]["met_delta"]` and `["supply_gap_delta"]`
4. If `decision == "reject"`: Sets `_DEMO_CACHE["patient_statuses"][patient_id] = "REJECTED"`

**Response**:
```json
{
  "status": "fulfilled",
  "chosen_lever": "inventory",
  "events": [
    {"step_index": 0, ...},
    {"step_index": 1, ...},
    {"step_index": 2, ...},
    {"step_index": 3, "agent": "HITL Approval Gate", "node": "approval", "summary": "Approved: inventory action for PAT-0001", ...},
    {"step_index": 4, "agent": "Redistribution", "node": "redistribution", "summary": "BB-0036 · 3d · 0.7km", ...}
  ],
  "emergency_reasoning": null
}
```

---

## `GET /api/patients/{patient_id}/activity`

Response model: `ActivityFeedOut`

**Query parameters**: `simulate_timeout: bool = False`
**Header**: `X-HemoGrid-Chaos: inject-timeout`

**Processing**: Calls `agents.run_request(patient_id, dataset, today)` (non-HITL path, runs to completion). Returns the ordered `trace` events.

**Response**:
```json
{
  "patient_id": "PAT-0001",
  "chosen_lever": "inventory",
  "events": [
    {"step_index": 0, "agent": "Demand Forecasting", "node": "forecast", ...},
    {"step_index": 1, "agent": "Blood Desert Detection", "node": "desert", ...},
    {"step_index": 2, "agent": "Supply Strategy Orchestrator", "node": "orchestrate", ...},
    {"step_index": 3, "agent": "Redistribution", "node": "redistribution", ...}
  ]
}
```

The `orchestrate` event's `details` includes: `narration` (LLM or template), `need_clock_days`, `supply_clock_days`, `transport_tier`, `deliverable`, `agent_reasoning`, `agent_validation`, `typewriter_trace`.

---

## Demo State Endpoints

### `GET /api/demo/statuses`

Returns `_DEMO_CACHE["patient_statuses"]` as `dict[str, str]`:
```json
{"PAT-0001": "APPROVED", "PAT-0003": "REJECTED"}
```

### `GET /api/demo/adjustments`

Returns bank and cell adjustments:
```json
{
  "bank_adjustments": {"BB-0036": 1},
  "cell_adjustments": {"CLN-GNT-01": {"met_delta": 1, "supply_gap_delta": 1}}
}
```

### `POST /api/demo/reset`

Clears `_DEMO_CACHE` to pristine baseline. Does **NOT** reload the dataset from disk.

**Response**:
```json
{"status": "reset", "message": "Demo state reset. Active source: LiveHybridSource."}
```

---

## Decision Logic in Endpoints

The spec principle is "no decision logic in endpoints — the engine decides." Verification:

| Endpoint | Contains logic? | Details |
|----------|----------------|---------|
| `GET /api/health` | None | Pure state read |
| `GET /api/banks` | Filter only | `valid_only`, `district` filters — not decisions |
| `GET /api/deserts` | Demo adjustment | `cell_adjustments` applied to `met`/`supply_gap`/`desert_score` — this IS lightweight logic in the endpoint |
| `GET /api/patients` | Status lookup | `_DEMO_CACHE["patient_statuses"]` lookup — not a decision |
| `GET /api/patients/{id}/match` | None | All decisions from `choose_lever()` |
| `POST /api/patients/{id}/propose` | Cache write | Stores proposal in `_DEMO_CACHE` — bookkeeping, not decision |
| `POST /api/patients/{id}/approve` | State mutation | Writes to `_DEMO_CACHE` based on decision — bookkeeping, not decision |
| `GET /api/patients/{id}/activity` | None | Serialises graph trace |

**Note**: The `/api/deserts` demo adjustment logic does modify `met`, `supply_gap`, and `desert_score` inline before returning, which is lightweight display logic rather than matching/routing logic. It could be considered a minor violation of the "no decision logic in endpoints" principle.

---

## `_DEMO_CACHE` Volatile State

```python
_DEMO_CACHE: dict = {
    "patient_statuses":  {},   # patient_id → "APPROVED" | "REJECTED"
    "pending_proposals": {},   # thread_id  → {patient_id, bank_id, chosen_lever, clinic_id}
    "bank_adjustments":  {},   # bank_id    → int (units dispatched)
    "cell_adjustments":  {},   # cell_id    → {"met_delta": int, "supply_gap_delta": int}
}
```

This dict is module-level global, initialised at startup and reset by `POST /api/demo/reset`. It does not persist across server restarts. The underlying `app.state.dataset` is never modified — all adjustments are purely cosmetic overlay on the displayed numbers.
