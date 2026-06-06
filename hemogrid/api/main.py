"""
hemogrid/api/main.py — FastAPI application.

Run with:
    uvicorn hemogrid.api.main:app --reload --port 8000

Architecture note
-----------------
All endpoints read canonical objects through the Repository interface held on
app.state.  Day-of cloud swap: replace InMemoryRepository with a subclass that
reads from S3/GCS/managed-DB; nothing in this file changes.

app.state.dataset is kept for engine batch calls (e.g. compute_desert_cells)
that need the full CanonicalDataset — no source calls happen inside endpoints.

Scope: read-only endpoints only.  No writes, no auth, no agents, no LLM.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..agents import approve_request, propose_request, run_request
from ..engine import (
    choose_lever,
    collect_inventory_candidates,
    compute_desert_cells,
    forecast_due,
    haversine_km,
    rank_matches,
)
from ..llm import narrate_structural_recommendation, set_chaos_mode
from ..models import (
    BloodBank,
    Clinic,
    Component,
    Donor,
    Lever,
    Patient,
    Request,
)
from ..sources.live_source import LiveHybridSource
from ..sources.synthetic_source import SyntheticSource
from ..storage import InMemoryRepository

# ---------------------------------------------------------------------------
# Response DTOs — separate from canonical models to keep models/ pure
# ---------------------------------------------------------------------------


class BankSummary(BaseModel):
    bank_id: str
    name: str
    lat: float
    lng: float
    category: Optional[str]
    does_components: bool
    district: Optional[str]
    state: str
    coord_valid: bool


class DatasetStats(BaseModel):
    donors: int
    patients: int
    banks: int
    valid_coord_banks: int
    inventory_units: int


class HealthResponse(BaseModel):
    status: str
    dataset: DatasetStats
    live_mode: bool = False


class CellDesertScore(BaseModel):
    cell_id: str
    lat: float
    lng: float
    name: str
    patients_due: int
    demand_units: int           # D: total units needed by due patients
    raw_units: int              # S_raw: in-date PRBC units ABO/Rh-compat for >=1 patient
    safe_units: int             # S_safe: subset also passing antibody-safe gate
    met: int                    # min(D, S_safe) — demand actually covered
    compatibility_gap: int      # demand failing only because of antibody mismatch
    supply_gap: int             # demand failing because shelf is too thin
    desert_score: int           # compatibility_gap + supply_gap
    desert_type: str            # OK / COMPATIBILITY_LIMITED / SUPPLY_LIMITED / MIXED
    nearest_safe_inventory_km: Optional[float]  # clock ingredient, no logic here
    eligible_matched_donors_nearby: int         # clock ingredient, no logic here
    classification: str         # CHRONIC / ACUTE / OK
    structural_recommendation: str  # LLM narrative or deterministic template fallback


# ── Matching DTOs ────────────────────────────────────────────────────────────


class PatientSummary(BaseModel):
    """Lightweight patient view for the due-patients list."""
    patient_id: str
    abo: str
    rh_d: bool
    known_antibodies: list[str]
    clinic_id: str
    days_until_due: int
    due_soon: bool
    units_per_session: int
    status: str = "pending"   # "pending" | "approved" | "rejected"


class PhenotypeOut(BaseModel):
    """Serializable form of Phenotype — optional per-antigen flags."""
    C: Optional[bool] = None
    c: Optional[bool] = None
    E: Optional[bool] = None
    e: Optional[bool] = None
    K: Optional[bool] = None


class ChosenInventoryOut(BaseModel):
    """The single inventory unit the engine selected."""
    bank_id: str
    bank_name: str
    component: str
    abo: str
    rh_d: bool
    phenotype_tags: Optional[PhenotypeOut]
    days_to_expiry: int
    distance_km: Optional[float]
    inventory_options: int   # total compatible units found in radius


class DonorBreakdownOut(BaseModel):
    """Per-component score breakdown from rank_matches — mirrors engine output exactly."""
    proximity_km: float
    proximity_score: float
    reliability: float
    phenotype_quality: float
    bonded: bool
    bond_bonus: float


class ChosenDonorOut(BaseModel):
    """The single donor the engine selected."""
    donor_id: str
    abo: str
    rh_d: bool
    distance_km: float
    reliability_score: float
    bonded: bool
    score: float
    breakdown: DonorBreakdownOut
    candidates_ranked: int   # total eligible donors ranked


class RankedInventoryItem(BaseModel):
    """One entry in the ranked inventory candidate list (for 'Show details')."""
    rank: int
    bank_id: str
    bank_name: str
    abo: str
    rh_d: bool
    days_to_expiry: int
    distance_km: Optional[float]


class RankedDonorItem(BaseModel):
    """One entry in the ranked donor candidate list (for 'Show details')."""
    rank: int
    donor_id: str
    abo: str
    rh_d: bool
    distance_km: float
    reliability: float
    phenotype_quality: float
    bonded: bool
    score: float


class MatchResult(BaseModel):
    """Full engine recommendation for one patient — serialised choose_lever output."""
    patient_id: str
    abo: str
    rh_d: bool
    known_antibodies: list[str]
    days_until_due: int
    chosen_lever: str                              # "inventory" | "donor" | "emergency"
    chosen_inventory: Optional[ChosenInventoryOut] = None
    chosen_donor: Optional[ChosenDonorOut] = None
    ranked_inventory: list[RankedInventoryItem]    # top 10, sorted (expiry, dist, bank_id)
    ranked_donors: list[RankedDonorItem]           # top 10, sorted by rank_matches score
    reasoning: str


# ── Activity feed DTOs ────────────────────────────────────────────────────────


class ActivityEventOut(BaseModel):
    """One agent hand-off step in the LangGraph trace."""
    step_index: int
    agent: str               # human-readable label, e.g. "Demand Forecasting"
    node: str                # graph node id, e.g. "forecast"
    summary: str             # one-line description of what this node decided
    details: dict[str, Any]  # key fields; all values are JSON-primitives


class ActivityFeedOut(BaseModel):
    """Ordered agent activity trace for one patient run."""
    patient_id: str
    chosen_lever: str                  # final lever chosen; must equal /match chosen_lever
    events: list[ActivityEventOut]


# ── HITL proposal + approval DTOs ─────────────────────────────────────────────


class ProposedActionOut(BaseModel):
    """The specific action the engine proposes to the coordinator."""
    type: str                        # "redistribute"|"activate_donor"|"emergency_escalation"
    recipient: str                   # patient_id
    # inventory fields (present when type=="redistribute")
    bank_id: Optional[str] = None
    bank_name: Optional[str] = None
    days_to_expiry: Optional[int] = None
    distance_km: Optional[float] = None
    # donor fields (present when type=="activate_donor")
    donor_id: Optional[str] = None
    score: Optional[float] = None
    bonded: Optional[bool] = None


class ProposalOut(BaseModel):
    """Full proposal surfaced to the coordinator at the HITL gate."""
    patient_id: str
    chosen_lever: str
    proposed_action: ProposedActionOut
    reasoning: str


class ProposalResponse(BaseModel):
    """Response from POST /propose — graph is paused awaiting approval."""
    thread_id: str
    status: str                        # "awaiting_approval"
    proposal: ProposalOut
    events_so_far: list[ActivityEventOut]   # forecast → desert → orchestrate → awaiting
    donor_message_draft: Optional[str] = None    # set when chosen_lever == "donor"
    emergency_reasoning: Optional[str] = None    # set when chosen_lever == "emergency"


class ApproveRequest(BaseModel):
    """Body for POST /approve."""
    thread_id: str
    decision: str                      # "approve" | "reject"


class ApproveResponse(BaseModel):
    """Response from POST /approve — graph has run to completion."""
    status: str                        # "fulfilled" | "declined"
    chosen_lever: str
    events: list[ActivityEventOut]     # full trace incl. approval + terminal step
    emergency_reasoning: Optional[str] = None    # set when chosen_lever == "emergency"


# ---------------------------------------------------------------------------
# In-memory demo state — volatile, resets on POST /api/demo/reset
# ---------------------------------------------------------------------------

_DEMO_CACHE: dict = {}


def _reset_demo_cache() -> None:
    """Purge and reinitialise to pristine seed=42 baseline."""
    _DEMO_CACHE.clear()
    _DEMO_CACHE.update({
        "patient_statuses":  {},   # patient_id → "APPROVED" | "REJECTED"
        "pending_proposals": {},   # thread_id  → {patient_id, bank_id, chosen_lever, clinic_id}
        "bank_adjustments":  {},   # bank_id    → int (units removed)
        "cell_adjustments":  {},   # cell_id    → {"met_delta": int, "supply_gap_delta": int}
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MATCH_RADIUS_KM = 100.0   # same as engine._SEARCH_RADIUS_KM


def _to_summary(bank: BloodBank) -> BankSummary:
    return BankSummary(
        bank_id=bank.bank_id,
        name=bank.name,
        lat=float(bank.location.lat),
        lng=float(bank.location.lng),
        category=bank.category.value if bank.category else None,
        does_components=bank.does_components,
        district=bank.district,
        state=bank.state,
        coord_valid=bank.coord_valid,
    )


def _to_patient_summary(
    patient: Patient, today: date, status: str = "pending"
) -> PatientSummary:
    next_need, is_due = forecast_due(patient, today)
    return PatientSummary(
        patient_id=patient.patient_id,
        abo=patient.abo_group.value,
        rh_d=patient.rh_d,
        known_antibodies=patient.known_antibodies,
        clinic_id=patient.clinic_id,
        days_until_due=(next_need - today).days,
        due_soon=is_due,
        units_per_session=patient.units_per_session,
        status=status,
    )


# ---------------------------------------------------------------------------
# Lifespan: load once, hold in app.state
# ---------------------------------------------------------------------------


def _build_dataset():
    """Defaults to LiveHybridSource; set HEMOGRID_USE_LIVE_DATA=false to fall back to synthetic."""
    flag = os.environ.get("HEMOGRID_USE_LIVE_DATA", "true").strip().lower()
    if flag != "false":
        print("[main] LiveHybridSource active (set HEMOGRID_USE_LIVE_DATA=false to override)")
        return LiveHybridSource().load()
    print("[main] HEMOGRID_USE_LIVE_DATA=false → loading SyntheticSource (seed=42)")
    return SyntheticSource().load()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ds = _build_dataset()

    # Each canonical type gets its own Repository — the invariant that makes
    # cloud-swap seamless and keeps endpoints from touching the source directly.
    bank_repo: InMemoryRepository[BloodBank] = InMemoryRepository(BloodBank)
    for bank in ds.blood_banks:
        bank_repo.save(bank.bank_id, bank)

    patient_repo: InMemoryRepository[Patient] = InMemoryRepository(Patient)
    for patient in ds.patients:
        patient_repo.save(patient.patient_id, patient)

    donor_repo: InMemoryRepository[Donor] = InMemoryRepository(Donor)
    for donor in ds.donors:
        donor_repo.save(donor.donor_id, donor)

    clinic_repo: InMemoryRepository[Clinic] = InMemoryRepository(Clinic)
    for clinic in ds.clinics:
        clinic_repo.save(clinic.clinic_id, clinic)

    app.state.bank_repo    = bank_repo
    app.state.patient_repo = patient_repo
    app.state.donor_repo   = donor_repo
    app.state.clinic_repo  = clinic_repo
    app.state.live_mode    = os.environ.get("HEMOGRID_USE_LIVE_DATA", "true").strip().lower() != "false"
    # ds held for engine batch calls (compute_desert_cells, choose_lever, etc.)
    # that need the full CanonicalDataset.  No source re-loading inside endpoints.
    app.state.dataset = ds
    app.state.stats = DatasetStats(
        donors=len(ds.donors),
        patients=len(ds.patients),
        banks=len(ds.blood_banks),
        valid_coord_banks=sum(1 for b in ds.blood_banks if b.coord_valid),
        inventory_units=sum(len(b.units) for b in ds.blood_banks),
    )

    # Initialise the volatile demo cache to its clean baseline
    _reset_demo_cache()

    yield  # app serves requests here


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="HemoGrid API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", dataset=app.state.stats, live_mode=app.state.live_mode)


@app.get("/api/banks", response_model=list[BankSummary])
def list_banks(
    valid_only: bool = Query(default=True, description="Return only coord_valid=True banks"),
    district: Optional[str] = Query(default=None, description="Filter by district (case-insensitive)"),
) -> list[BankSummary]:
    # All reads go through the Repository — proving repo→DTO, not source→DTO.
    banks: list[BloodBank] = app.state.bank_repo.list_all()

    if valid_only:
        banks = [b for b in banks if b.coord_valid]
    if district:
        dl = district.strip().lower()
        banks = [b for b in banks if (b.district or "").lower() == dl]

    return [_to_summary(b) for b in banks]


@app.get("/api/deserts", response_model=list[CellDesertScore])
def list_deserts(
    radius_km: float = Query(default=50.0, ge=10.0, le=200.0,
                             description="Supply search radius around each clinic (km)"),
    lead_days: int = Query(default=7, ge=1, le=30,
                           description="Patients due within this many days count as demand"),
    simulate_timeout: bool = Query(default=False, description="Stage demo: force LLM fallback"),
    x_hemogrid_chaos: Optional[str] = Header(default=None),
) -> list[CellDesertScore]:
    # Chaos intercept: header X-HemoGrid-Chaos: inject-timeout OR query ?simulate_timeout=true
    chaos = simulate_timeout or (x_hemogrid_chaos == "inject-timeout")
    if chaos:
        set_chaos_mode(True)
    try:
        # Engine does all math; endpoint enriches with LLM narration and serialises.
        cells = compute_desert_cells(app.state.dataset, date.today(), radius_km, lead_days)
        # Apply any live demo adjustments (approved inventory dispatches)
        cell_adj = _DEMO_CACHE.get("cell_adjustments", {})
        for c in cells:
            cid = c.get("cell_id", "")
            if cid in cell_adj:
                adj = cell_adj[cid]
                c["met"] = min(c["demand_units"], c["met"] + adj["met_delta"])
                c["supply_gap"] = max(0, c["supply_gap"] - adj["supply_gap_delta"])
                c["desert_score"] = abs(c.get("compatibility_gap", 0)) + c["supply_gap"]
        result = []
        for c in cells:
            rec = narrate_structural_recommendation(
                c["cell_id"], c["classification"], c["desert_score"], c["desert_type"]
            )
            result.append(CellDesertScore(**c, structural_recommendation=rec))

        hyd = next((r for r in result if r.cell_id == "CLN-HYD-01"), None)
        if hyd:
            print(
                f"[deserts] CLN-HYD-01 desert_score={hyd.desert_score} "
                f"classification={hyd.classification} "
                f"type={hyd.desert_type} "
                f"supply_gap={hyd.supply_gap} "
                f"compat_gap={hyd.compatibility_gap}"
            )
        return result
    finally:
        if chaos:
            set_chaos_mode(False)


@app.get("/api/patients", response_model=list[PatientSummary])
def list_patients(
    clinic_id: Optional[str] = Query(default=None, description="Filter by clinic_id"),
    due_soon: bool = Query(default=False, description="Only return patients due within 7 days"),
) -> list[PatientSummary]:
    today = date.today()
    patients: list[Patient] = app.state.patient_repo.list_all()

    if clinic_id:
        patients = [p for p in patients if p.clinic_id == clinic_id]

    raw_statuses = _DEMO_CACHE.get("patient_statuses", {})

    def _patient_status(pid: str) -> str:
        raw = raw_statuses.get(pid, "")
        if raw == "APPROVED":
            return "approved"
        if raw == "REJECTED":
            return "rejected"
        return "pending"

    summaries = [_to_patient_summary(p, today, _patient_status(p.patient_id)) for p in patients]

    if due_soon:
        summaries = [s for s in summaries if s.due_soon]

    summaries.sort(key=lambda s: s.days_until_due)
    return summaries


@app.get("/api/patients/{patient_id}/match", response_model=MatchResult)
def get_match(patient_id: str) -> MatchResult:
    """
    Run choose_lever + rank_matches for a single patient and serialise the
    engine's output.  No decision logic here — the engine decides; this
    endpoint only translates the result into JSON-serialisable DTOs.
    """
    # 404 guard via repo
    if app.state.patient_repo.get(patient_id) is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id!r} not found")

    today = date.today()
    dataset = app.state.dataset

    # Use the canonical object from dataset.patients — the same object the
    # engine functions use, avoiding any double-deserialisation mismatch.
    patient = next(p for p in dataset.patients if p.patient_id == patient_id)

    next_need, _ = forecast_due(patient, today)
    days_until_due = (next_need - today).days

    req = Request(
        request_id=f"REQ-API-{patient_id}",
        patient_id=patient_id,
        needed_by_date=next_need,
        component=Component.PRBC,
        units=patient.units_per_session,
    )

    # ── Engine call: deterministic lever selection ──────────────────────────
    lever_result = choose_lever(req, dataset, today)
    lever_str: str = lever_result["lever"].value   # "inventory" | "donor" | "emergency"

    clinic = next((c for c in dataset.clinics if c.clinic_id == patient.clinic_id), None)
    clinic_loc = clinic.location if clinic else None

    # ── Ranked inventory candidates — engine is the single source of truth ──
    inv_candidates = collect_inventory_candidates(patient, clinic_loc, dataset, today)

    ranked_inventory = [
        RankedInventoryItem(
            rank=i + 1,
            bank_id=b.bank_id,
            bank_name=b.name,
            abo=u.abo.value,
            rh_d=u.rh_d,
            days_to_expiry=exp_d,
            distance_km=round(dist_km, 1),
        )
        for i, (b, u, dist_km, exp_d) in enumerate(inv_candidates[:10])
    ]

    # ── Ranked donor candidates (for "Show details" + chosen donor lookup) ───
    nearby_donors = (
        [d for d in dataset.donors
         if haversine_km(clinic_loc, d.location) <= _MATCH_RADIUS_KM]
        if clinic_loc else dataset.donors
    )
    donor_ranking = rank_matches(req, nearby_donors, dataset, today)

    ranked_donors = [
        RankedDonorItem(
            rank=i + 1,
            donor_id=r["donor"].donor_id,
            abo=r["donor"].abo_group.value,
            rh_d=r["donor"].rh_d,
            distance_km=r["breakdown"]["proximity_km"],
            reliability=r["breakdown"]["reliability"],
            phenotype_quality=r["breakdown"]["phenotype_quality"],
            bonded=r["breakdown"]["bonded"],
            score=r["score"],
        )
        for i, r in enumerate(donor_ranking[:10])
    ]

    # ── Serialise the chosen lever ──────────────────────────────────────────
    chosen_inventory: Optional[ChosenInventoryOut] = None
    chosen_donor: Optional[ChosenDonorOut] = None

    if lever_str == Lever.INVENTORY.value and inv_candidates:
        best_bank, best_unit, best_dist, best_exp = inv_candidates[0]
        ph = best_unit.phenotype_tags
        chosen_inventory = ChosenInventoryOut(
            bank_id=best_bank.bank_id,
            bank_name=best_bank.name,
            component=best_unit.component.value,
            abo=best_unit.abo.value,
            rh_d=best_unit.rh_d,
            phenotype_tags=PhenotypeOut(
                C=ph.C, c=ph.c, E=ph.E, e=ph.e, K=ph.K
            ) if ph else None,
            days_to_expiry=best_exp,
            distance_km=round(best_dist, 1),
            inventory_options=len(inv_candidates),
        )

    elif lever_str == Lever.DONOR.value and donor_ranking:
        top = donor_ranking[0]
        don = top["donor"]
        bd = top["breakdown"]
        chosen_donor = ChosenDonorOut(
            donor_id=don.donor_id,
            abo=don.abo_group.value,
            rh_d=don.rh_d,
            distance_km=bd["proximity_km"],
            reliability_score=bd["reliability"],
            bonded=bd["bonded"],
            score=top["score"],
            breakdown=DonorBreakdownOut(
                proximity_km=bd["proximity_km"],
                proximity_score=bd["proximity_score"],
                reliability=bd["reliability"],
                phenotype_quality=bd["phenotype_quality"],
                bonded=bd["bonded"],
                bond_bonus=bd["bond_bonus"],
            ),
            candidates_ranked=len(donor_ranking),
        )

    return MatchResult(
        patient_id=patient_id,
        abo=patient.abo_group.value,
        rh_d=patient.rh_d,
        known_antibodies=patient.known_antibodies,
        days_until_due=days_until_due,
        chosen_lever=lever_str,
        chosen_inventory=chosen_inventory,
        chosen_donor=chosen_donor,
        ranked_inventory=ranked_inventory,
        ranked_donors=ranked_donors,
        reasoning=lever_result["reasoning"],
    )


@app.post("/api/patients/{patient_id}/propose", response_model=ProposalResponse)
def propose(
    patient_id: str,
    simulate_timeout: bool = Query(default=False, description="Stage demo: force LLM fallback"),
    x_hemogrid_chaos: Optional[str] = Header(default=None),
) -> ProposalResponse:
    """
    Run the LangGraph HITL path: invoke graph with require_approval=True.
    The graph pauses at the approval gate and returns the proposal + events-so-far.
    Store the returned thread_id and pass it to POST /approve to complete the run.
    """
    if app.state.patient_repo.get(patient_id) is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id!r} not found")

    chaos = simulate_timeout or (x_hemogrid_chaos == "inject-timeout")
    if chaos:
        set_chaos_mode(True)
    try:
        today  = date.today()
        result = propose_request(patient_id, app.state.dataset, today)
    finally:
        if chaos:
            set_chaos_mode(False)

    pa_raw = result["proposal"].get("proposed_action", {})
    thread_id      = result["thread_id"]
    chosen_lever   = result["proposal"]["chosen_lever"]
    bank_id        = pa_raw.get("bank_id")
    patient_obj    = app.state.patient_repo.get(patient_id)
    clinic_id      = patient_obj.clinic_id if patient_obj else None

    # Store pending proposal so the approve endpoint can apply live adjustments
    _DEMO_CACHE["pending_proposals"][thread_id] = {
        "patient_id":    patient_id,
        "bank_id":       bank_id,
        "chosen_lever":  chosen_lever,
        "clinic_id":     clinic_id,
    }

    return ProposalResponse(
        thread_id=thread_id,
        status=result["status"],
        proposal=ProposalOut(
            patient_id=result["proposal"]["patient_id"],
            chosen_lever=chosen_lever,
            proposed_action=ProposedActionOut(**pa_raw),
            reasoning=result["proposal"].get("reasoning", ""),
        ),
        events_so_far=[ActivityEventOut(**e) for e in result["events_so_far"]],
        donor_message_draft=result.get("donor_message_draft"),
        emergency_reasoning=result.get("emergency_reasoning"),
    )


@app.post("/api/patients/{patient_id}/approve", response_model=ApproveResponse)
def approve(patient_id: str, body: ApproveRequest) -> ApproveResponse:
    """
    Resume the paused graph with the coordinator's decision (approve or reject).
    Returns the final status and full event trace.
    """
    if app.state.patient_repo.get(patient_id) is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id!r} not found")

    result = approve_request(body.thread_id, body.decision)

    # ── Persist decision in volatile demo cache ───────────────────────────
    pending      = _DEMO_CACHE["pending_proposals"].pop(body.thread_id, {})
    chosen_lever = result.get("chosen_lever") or pending.get("chosen_lever", "")
    bank_id      = pending.get("bank_id")
    clinic_id    = pending.get("clinic_id")

    if body.decision == "approve":
        _DEMO_CACHE["patient_statuses"][patient_id] = "APPROVED"
        if chosen_lever == "inventory" and bank_id:
            _DEMO_CACHE["bank_adjustments"][bank_id] = (
                _DEMO_CACHE["bank_adjustments"].get(bank_id, 0) + 1
            )
            print(
                f"[approve] bank_adjustments loop — "
                f"patient={patient_id} bank_id={bank_id} "
                f"dispatched={_DEMO_CACHE['bank_adjustments'][bank_id]} unit(s)  "
                f"→ _DEMO_CACHE['bank_adjustments']={dict(_DEMO_CACHE['bank_adjustments'])}"
            )
            if clinic_id:
                adj = _DEMO_CACHE["cell_adjustments"].setdefault(
                    clinic_id, {"met_delta": 0, "supply_gap_delta": 0}
                )
                adj["met_delta"]         += 1
                adj["supply_gap_delta"]  += 1
    else:
        _DEMO_CACHE["patient_statuses"][patient_id] = "REJECTED"

    return ApproveResponse(
        status=result["status"],
        chosen_lever=chosen_lever,
        events=[ActivityEventOut(**e) for e in result["trace"]],
        emergency_reasoning=result.get("emergency_reasoning"),
    )


@app.get("/api/patients/{patient_id}/activity", response_model=ActivityFeedOut)
def get_activity(
    patient_id: str,
    simulate_timeout: bool = Query(default=False, description="Stage demo: force LLM fallback"),
    x_hemogrid_chaos: Optional[str] = Header(default=None),
) -> ActivityFeedOut:
    """
    Run the LangGraph orchestration for one patient and return the ordered
    agent hand-off trace.

    The final chosen lever MUST equal /match's chosen lever — both read the
    same engine with the same dataset.  No decision logic here: this endpoint
    serialises the graph trace only.
    """
    if app.state.patient_repo.get(patient_id) is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id!r} not found")

    chaos = simulate_timeout or (x_hemogrid_chaos == "inject-timeout")
    if chaos:
        set_chaos_mode(True)
    try:
        today = date.today()
        result = run_request(patient_id, app.state.dataset, today)
    finally:
        if chaos:
            set_chaos_mode(False)

    lever = result["lever_result"]["lever"].value
    events = [ActivityEventOut(**evt) for evt in result["trace"]]

    return ActivityFeedOut(
        patient_id=patient_id,
        chosen_lever=lever,
        events=events,
    )


# ---------------------------------------------------------------------------
# Demo state management
# ---------------------------------------------------------------------------


@app.get("/api/demo/statuses", response_model=dict[str, str])
def get_demo_statuses() -> dict[str, str]:
    """Return all patient triage decisions made in this session."""
    return dict(_DEMO_CACHE.get("patient_statuses", {}))


@app.get("/api/demo/adjustments")
def get_demo_adjustments() -> dict:
    """Return bank-unit and cell-metric adjustments accumulated this session."""
    return {
        "bank_adjustments": dict(_DEMO_CACHE.get("bank_adjustments", {})),
        "cell_adjustments": dict(_DEMO_CACHE.get("cell_adjustments", {})),
    }


@app.post("/api/demo/reset")
def reset_demo_state() -> dict[str, str]:
    """
    Purge all volatile demo state (patient statuses, bank adjustments, cell
    adjustments).  The in-memory dataset is NOT reloaded — only the volatile
    _DEMO_CACHE counters are cleared to their pristine baseline.

    When HEMOGRID_USE_LIVE_DATA=true the live-parsed dataset was loaded at
    startup; this reset merely zeros the frontend counters without re-parsing
    the CSV files.
    """
    _reset_demo_cache()
    flag = os.environ.get("HEMOGRID_USE_LIVE_DATA", "true").strip().lower()
    source_tag = "SyntheticSource (seed=42)" if flag == "false" else "LiveHybridSource"
    print(f"[main] demo cache reset  |  active source: {source_tag}  |  cache: {_DEMO_CACHE}")
    return {"status": "reset", "message": f"Demo state reset. Active source: {source_tag}."}
