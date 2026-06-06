"""
hemogrid/agents/graph.py — LangGraph orchestration with HITL gate + LLM narration.

Phase 3: Engine decides everything.  LLM narrates the orchestrate step only.

Graph flow
----------
START → forecast → desert → orchestrate → approval_gate
                                                ├─ inventory → redistribution  → END
                                                ├─ donor     → donor_matching  → END
                                                ├─ emergency → emergency       → END
                                                └─ declined  → declined        → END

require_approval=False  (/activity)  : approval_gate is a pass-through; trace is
                                       byte-identical to the Step-2 non-HITL result.
require_approval=True   (/propose)   : approval_gate calls interrupt(proposal) and
                                       pauses the graph.  Resume via Command(resume=).
"""
from __future__ import annotations

import operator
import uuid
from datetime import date
from typing import Annotated, Any, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt  # noqa: F401 (Command re-exported for callers)
from typing_extensions import TypedDict

from ..engine import (
    certified_inventory_candidates,
    choose_lever,
    collect_inventory_candidates,
    compute_desert_cells,
    forecast_due,
    haversine_km,
    rank_matches,
)
from ..models import CanonicalDataset, Component, Request

_SEARCH_RADIUS_KM = 100.0   # mirrors engine._SEARCH_RADIUS_KM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lever_value(lever: Any) -> str:
    """Return string lever value — handles both Lever enum and plain str after checkpoint."""
    return lever.value if hasattr(lever, "value") else str(lever)


# ---------------------------------------------------------------------------
# Structured trace event
# ---------------------------------------------------------------------------

class ActivityEvent(TypedDict):
    step_index: int          # dynamic: len(state["trace"]) when the node runs
    agent: str               # human-readable agent label
    node: str                # graph node id
    summary: str             # one-line description of what this node decided
    details: dict[str, Any]  # key fields; all values are JSON-primitives


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class GraphState(TypedDict):
    # ── Inputs (caller supplies once) ────────────────────────────────────────
    patient_id: str
    dataset: CanonicalDataset
    today: date
    require_approval: bool   # False → /activity pass-through; True → /propose HITL

    # ── Forecast node ─────────────────────────────────────────────────────────
    request: Optional[Request]
    forecast_result: Optional[dict[str, Any]]

    # ── Desert node ───────────────────────────────────────────────────────────
    desert_cell: Optional[dict[str, Any]]

    # ── Orchestrate node ──────────────────────────────────────────────────────
    lever_result: Optional[dict[str, Any]]
    narration: Optional[str]             # LLM-generated (or template) narration

    # ── HITL status (predicted → proposed → approved/declined → fulfilled) ────
    status: str

    # ── Terminal nodes (one branch only per run) ──────────────────────────────
    ranked_inventory: list[tuple]          # redistribution branch
    ranked_donors: list[dict[str, Any]]    # donor_matching branch

    # ── LLM-drafted donor activation message (set once in orchestrate_node) ──
    donor_message_draft: Optional[str]

    # ── LLM-generated emergency escalation reasoning (set once in emergency_node) ──
    emergency_reasoning: Optional[str]

    # ── Ordered event trace (accumulated; reducer = list append) ─────────────
    trace: Annotated[list[ActivityEvent], operator.add]


# ---------------------------------------------------------------------------
# Agent selection (bounded manual loop — no ReAct; langchain-ollama not installed)
# ---------------------------------------------------------------------------
#
# create_react_agent (langgraph.prebuilt) confirmed available + signature verified,
# but requires a LangChain chat model.  langchain-ollama / langchain-community are
# not installed in this environment, so we use a bounded prompt-then-validate loop
# instead of the full ReAct framework.  Either path feeds the same validator.
#
# Guardrail lock #1: agent receives ONLY engine-certified safe+deliverable candidates.
# Any selection outside that set is REJECTED; fallback = choose_lever result.

def _agent_select(
    certified: list[dict[str, Any]],
    patient_id: str,
    engine_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Bounded manual agent: ask LLM to select from certified candidates.
    Validates selection; falls back to engine result on any failure.

    Implementation: langgraph.prebuilt.create_react_agent API is compatible
    (verified), but langchain-ollama is not installed, so we use a single
    structured prompt + JSON parse instead.  The validator is the same either way.
    """
    import json as _json
    import re as _re
    from ..llm import LLMUnavailable, generate

    lever    = _lever_value(engine_result["lever"])
    engine_id = engine_result.get("bank_id") or engine_result.get("donor_id")

    if not certified:
        return {
            "lever":             lever,
            "target_id":         engine_id,
            "agent_reasoning":   "no certified inventory candidates — engine fallback",
            "validation_result": "fallback_empty",
        }

    lines = [
        f"  {i + 1}. bank_id={c['bank_id']} tier={c['transport_tier']} "
        f"expiry={c['expiry_days']}d dist={c['dist_km']}km "
        f"supply_clock={c['supply_clock_days']:.4f}d"
        for i, c in enumerate(certified)
    ]
    prompt = (
        f"Select the best blood unit for patient {patient_id}.\n"
        "Pre-certified safe+deliverable inventory (engine-sorted best-first):\n"
        + "\n".join(lines)
        + "\n\nRanking guidance: "
        "(1) tier 0 (local) preferred over tier 1 (far); "
        "(2) within same tier, sooner expiry prevents wastage; "
        "(3) shorter distance preferred at equal expiry.\n"
        "Respond with ONLY this JSON on one line — no markdown, no extra text:\n"
        '{"lever": "inventory", "target_id": "<bank_id>", "reasoning": "<1-2 sentences>"}'
    )

    try:
        raw = generate(prompt, temperature=0.0)
        if not raw.strip():
            raise LLMUnavailable("empty response")
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if not m:
            raise ValueError(f"no JSON found in: {raw[:120]!r}")
        sel = _json.loads(m.group())

        sel_lever     = sel.get("lever", "").lower().strip()
        sel_id        = sel.get("target_id", "").strip()
        sel_reasoning = sel.get("reasoning", "")

        valid_ids = {c["bank_id"] for c in certified}
        if sel_lever == "inventory" and sel_id in valid_ids:
            return {
                "lever":             "inventory",
                "target_id":         sel_id,
                "agent_reasoning":   sel_reasoning,
                "validation_result": "accepted",
            }
        # Selection not in certified set → REJECT
        return {
            "lever":             lever,
            "target_id":         engine_id,
            "agent_reasoning":   (
                f"agent selected {sel_id!r} (lever={sel_lever!r}) — "
                f"not in certified set {sorted(valid_ids)[:4]} — REJECTED, engine fallback"
            ),
            "validation_result": "rejected_fallback",
        }

    except Exception as exc:
        return {
            "lever":             lever,
            "target_id":         engine_id,
            "agent_reasoning":   (
                f"LLM unavailable ({type(exc).__name__}: {exc}) — engine fallback"
            ),
            "validation_result": "fallback",
        }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def forecast_node(state: GraphState) -> dict:
    """Wraps engine.forecast_due; builds the Request for this run."""
    patient = next(
        p for p in state["dataset"].patients
        if p.patient_id == state["patient_id"]
    )
    next_need, is_due = forecast_due(patient, state["today"])
    days = (next_need - state["today"]).days
    req = Request(
        request_id=f"REQ-GRAPH-{state['patient_id']}",
        patient_id=state["patient_id"],
        needed_by_date=next_need,
        component=Component.PRBC,
        units=patient.units_per_session,
    )
    event: ActivityEvent = {
        "step_index": 0,
        "agent": "Demand Forecasting",
        "node": "forecast",
        "summary": (
            f"{state['patient_id']} due in {days}d "
            f"({next_need.isoformat()}) — is_due_soon={is_due}"
        ),
        "details": {
            "patient_id":     state["patient_id"],
            "days_until_due": days,
            "next_need_date": next_need.isoformat(),
            "is_due_soon":    is_due,
        },
    }
    return {
        "request": req,
        "forecast_result": {
            "next_need_date": next_need,
            "is_due_soon":    is_due,
            "days_until_due": days,
        },
        "trace": [event],
    }


def desert_node(state: GraphState) -> dict:
    """Wraps engine.compute_desert_cells; extracts the cell for this patient's clinic."""
    patient = next(
        p for p in state["dataset"].patients
        if p.patient_id == state["patient_id"]
    )
    cells = compute_desert_cells(state["dataset"], state["today"])
    cell = next((c for c in cells if c["cell_id"] == patient.clinic_id), None)

    if cell:
        event: ActivityEvent = {
            "step_index": 1,
            "agent": "Blood Desert Detection",
            "node": "desert",
            "summary": (
                f"{cell['cell_id']} · score={cell['desert_score']} · "
                f"{cell['desert_type']}"
            ),
            "details": {
                "cell_id":      cell["cell_id"],
                "desert_score": cell["desert_score"],
                "desert_type":  cell["desert_type"],
                "demand_units": cell["demand_units"],
                "safe_units":   cell["safe_units"],
            },
        }
    else:
        event = {
            "step_index": 1,
            "agent": "Blood Desert Detection",
            "node": "desert",
            "summary": f"clinic {patient.clinic_id} not found in cells",
            "details": {"cell_id": patient.clinic_id},
        }
    return {"desert_cell": cell, "trace": [event]}


def orchestrate_node(state: GraphState) -> dict:
    """Engine decides lever; agent selects from certified set; narrate once."""
    from ..llm import draft_donor_message, narrate_decision  # leaf import — avoids circular at module level

    result = choose_lever(state["request"], state["dataset"], state["today"])
    lever = _lever_value(result["lever"])

    patient = next(
        p for p in state["dataset"].patients if p.patient_id == state["patient_id"]
    )
    abo_rh = f"{patient.abo_group.value}{'+' if patient.rh_d else '-'}"

    # ── Agent layer ────────────────────────────────────────────────────────────
    # Build engine-certified safe+deliverable set; agent selects within it.
    if lever == "inventory":
        clinic = next(
            (c for c in state["dataset"].clinics if c.clinic_id == patient.clinic_id),
            None,
        )
        clinic_loc = clinic.location if clinic else None
        certified = certified_inventory_candidates(
            patient, clinic_loc, state["dataset"], state["today"]
        )
        agent_out = _agent_select(certified, state["patient_id"], result)
    else:
        certified = []
        agent_out = {
            "lever":             lever,
            "target_id":         result.get("donor_id"),
            "agent_reasoning":   f"{lever} lever — engine selection retained",
            "validation_result": "engine_lever",
        }

    # ── Decision dict (engine fields + new clock/tier/agent fields) ────────────
    decision: dict[str, Any] = {
        "lever":                lever,
        "patient_id":           state["patient_id"],
        "patient_abo_rh":       abo_rh,
        "patient_antibodies":   patient.known_antibodies,
        "need_clock_days":      result.get("need_clock_days"),
        "supply_clock_days":    result.get("supply_clock_days"),
        "transport_tier":       result.get("transport_tier"),
        "deliverable":          result.get("deliverable"),
        "agent_reasoning":      agent_out.get("agent_reasoning"),
        "agent_validation":     agent_out.get("validation_result"),
    }
    if lever == "inventory":
        decision.update({
            "bank_id":           result["bank_id"],
            "bank_name":         result["bank_name"],
            "expiry_days":       result["days_to_expiry"],
            "dist_km":           result["distance_km"],
            "component":         state["request"].component.value,
            "inventory_options": result["inventory_options"],
        })
    elif lever == "donor":
        bd = result["breakdown"]
        donor = next(
            (d for d in state["dataset"].donors if d.donor_id == result["donor_id"]),
            None,
        )
        donor_abo_rh = (
            f"{donor.abo_group.value}{'+' if donor.rh_d else '-'}" if donor else "?"
        )
        decision.update({
            "donor_id":     result["donor_id"],
            "donor_abo_rh": donor_abo_rh,
            "match_score":  round(result["donor_score"], 4),
            "dist_km":      bd["proximity_km"],
            "bonded":       bd["bonded"],
        })

    narration_result = narrate_decision(decision)  # called exactly once
    narration = narration_result.text

    # Draft donor activation message — ONCE per cycle.
    # Idempotency guard: if the field is already set on incoming state (re-execution
    # safety), skip the LLM call entirely and preserve the existing draft.
    donor_message_draft: Optional[str] = state.get("donor_message_draft")
    if lever == "donor" and not donor_message_draft:
        days_until_due = (state.get("forecast_result") or {}).get("days_until_due", 1)
        donor_message_draft = draft_donor_message(
            patient={"patient_id": state["patient_id"], "abo_rh": abo_rh,
                     "clinic_id": patient.clinic_id},
            donor={
                "donor_id":    decision["donor_id"],
                "dist_km":     decision["dist_km"],
                "bonded":      decision["bonded"],
                "match_score": decision.get("match_score"),
            },
            need_clock=float(days_until_due),
        )

    # Generate emergency escalation reasoning — ONCE per cycle (before approval gate
    # so the UI can display it to the coordinator during the HITL decision phase).
    # Idempotency guard: preserve existing value on interrupt-resume re-execution.
    emergency_reasoning: Optional[str] = state.get("emergency_reasoning")
    if lever == "emergency" and not emergency_reasoning:
        from ..llm import generate_emergency_escalation
        clinic_loc_for_emerg = None
        clinic_for_emerg = next(
            (c for c in state["dataset"].clinics if c.clinic_id == patient.clinic_id), None
        )
        if clinic_for_emerg:
            clinic_loc_for_emerg = clinic_for_emerg.location
        nearby_donors_emerg = (
            [d for d in state["dataset"].donors
             if haversine_km(clinic_loc_for_emerg, d.location) <= _SEARCH_RADIUS_KM]
            if clinic_loc_for_emerg else []
        )
        donor_summaries_emerg = [
            {"donor_id": d.donor_id,
             "dist_km": round(haversine_km(clinic_loc_for_emerg, d.location), 1)}
            for d in nearby_donors_emerg[:10]
        ] if clinic_loc_for_emerg else []
        emergency_reasoning = generate_emergency_escalation(
            patient={"patient_id": state["patient_id"], "abo_rh": abo_rh,
                     "known_antibodies": patient.known_antibodies},
            close_but_undeliverable_donors=donor_summaries_emerg,
        )

    # Typewriter trace — agent execution cycle messages surfaced to the UI
    _typewriter_trace = [
        "Scanning local proximity tiers...",
        "Evaluating antibody safety gates...",
        f"Locking lever selection: {lever}",
        "Finalizing Edge LLM narration strings...",
    ]

    event: ActivityEvent = {
        "step_index": 2,
        "agent": "Supply Strategy Orchestrator",
        "node": "orchestrate",
        "summary": f"chosen_lever={lever}",
        "details": {
            "chosen_lever":      lever,
            "narration":         narration,
            "need_clock_days":   result.get("need_clock_days"),
            "supply_clock_days": result.get("supply_clock_days"),
            "transport_tier":    result.get("transport_tier"),
            "deliverable":       result.get("deliverable"),
            "agent_reasoning":   agent_out.get("agent_reasoning"),
            "agent_validation":  agent_out.get("validation_result"),
            "typewriter_trace":  _typewriter_trace,
        },
    }
    return {
        "lever_result":         result,
        "narration":            narration,
        "donor_message_draft":  donor_message_draft,
        "emergency_reasoning":  emergency_reasoning,
        "trace":                [event],
    }


def approval_gate_node(state: GraphState) -> dict:
    """
    HITL approval gate between orchestrate and the terminal nodes.

    require_approval=False → pass-through (no event, trace unchanged vs Step 2).
    require_approval=True  → calls interrupt(proposal) on first entry;
                             on resume, reads decision and emits approval event.

    Re-execution safety: nothing non-idempotent appears before interrupt().
    Events are only emitted in the return dict (after interrupt() returns on resume).
    """
    if not state["require_approval"]:
        return {}   # /activity path: no gate, no event, no status change

    lr = state["lever_result"]
    lever = _lever_value(lr["lever"])

    # Build proposal payload (fully deterministic — same on any re-execution)
    if lever == "inventory":
        proposed_action: dict[str, Any] = {
            "type":           "redistribute",
            "bank_id":        lr["bank_id"],
            "bank_name":      lr["bank_name"],
            "days_to_expiry": lr["days_to_expiry"],
            "distance_km":    lr["distance_km"],
            "recipient":      state["patient_id"],
        }
    elif lever == "donor":
        proposed_action = {
            "type":        "activate_donor",
            "donor_id":    lr["donor_id"],
            "score":       lr["donor_score"],
            "distance_km": lr["breakdown"]["proximity_km"],
            "bonded":      lr["breakdown"]["bonded"],
            "recipient":   state["patient_id"],
        }
    else:
        proposed_action = {
            "type":      "emergency_escalation",
            "recipient": state["patient_id"],
        }

    proposal = {
        "patient_id":      state["patient_id"],
        "chosen_lever":    lever,
        "proposed_action": proposed_action,
        "reasoning":       lr.get("reasoning", ""),
    }

    # ── INTERRUPT — graph suspends here on first call ──────────────────────────
    # On resume, interrupt() returns the value passed to Command(resume=...).
    decision = interrupt(proposal)
    # ── Everything below runs only after the coordinator responds ──────────────

    approved = decision.get("decision") == "approve"
    step = len(state["trace"])   # dynamic: 3 after forecast/desert/orchestrate

    if approved:
        event: ActivityEvent = {
            "step_index": step,
            "agent":      "HITL Approval Gate",
            "node":       "approval",
            "summary":    f"Approved: {lever} action for {state['patient_id']}",
            "details":    {"decision": "approve", "lever": lever},
        }
        return {"status": "approved", "trace": [event]}
    else:
        event = {
            "step_index": step,
            "agent":      "HITL Approval Gate",
            "node":       "approval",
            "summary":    f"Rejected: {lever} action for {state['patient_id']}",
            "details":    {"decision": "reject", "lever": lever},
        }
        return {"status": "declined", "trace": [event]}


def redistribution_node(state: GraphState) -> dict:
    """Terminal node for the INVENTORY branch."""
    patient = next(
        p for p in state["dataset"].patients
        if p.patient_id == state["patient_id"]
    )
    clinic = next(
        (c for c in state["dataset"].clinics if c.clinic_id == patient.clinic_id),
        None,
    )
    clinic_loc = clinic.location if clinic else None
    candidates = collect_inventory_candidates(
        patient, clinic_loc, state["dataset"], state["today"]
    )
    lr = state["lever_result"]
    event: ActivityEvent = {
        "step_index": len(state["trace"]),   # 3 (non-HITL) or 4 (HITL)
        "agent":      "Redistribution",
        "node":       "redistribution",
        "summary": (
            f"{lr['bank_id']} · {lr['days_to_expiry']}d · "
            f"{lr['distance_km']}km"
        ),
        "details": {
            "bank_id":           lr["bank_id"],
            "bank_name":         lr["bank_name"],
            "days_to_expiry":    lr["days_to_expiry"],
            "distance_km":       lr["distance_km"],
            "inventory_options": lr["inventory_options"],
        },
    }
    return {"ranked_inventory": candidates, "status": "fulfilled", "trace": [event]}


def donor_matching_node(state: GraphState) -> dict:
    """Terminal node for the DONOR branch."""
    patient = next(
        p for p in state["dataset"].patients
        if p.patient_id == state["patient_id"]
    )
    clinic = next(
        (c for c in state["dataset"].clinics if c.clinic_id == patient.clinic_id),
        None,
    )
    clinic_loc = clinic.location if clinic else None
    nearby_donors = (
        [d for d in state["dataset"].donors
         if haversine_km(clinic_loc, d.location) <= _SEARCH_RADIUS_KM]
        if clinic_loc else state["dataset"].donors
    )
    ranked = rank_matches(
        state["request"], nearby_donors, state["dataset"], state["today"]
    )

    if ranked:
        top = ranked[0]
        bd  = top["breakdown"]
        bonded_str = " · bonded" if bd["bonded"] else ""
        event: ActivityEvent = {
            "step_index": len(state["trace"]),
            "agent":      "Donor Matching",
            "node":       "donor_matching",
            "summary": (
                f"{top['donor'].donor_id} · score={top['score']} · "
                f"{bd['proximity_km']}km{bonded_str}"
            ),
            "details": {
                "donor_id":        top["donor"].donor_id,
                "score":           top["score"],
                "proximity_km":    bd["proximity_km"],
                "bonded":          bd["bonded"],
                "candidates_ranked": len(ranked),
            },
        }
    else:
        event = {
            "step_index": len(state["trace"]),
            "agent":      "Donor Matching",
            "node":       "donor_matching",
            "summary":    "no eligible donors found",
            "details":    {"candidates_ranked": 0},
        }
    return {"ranked_donors": ranked, "status": "fulfilled", "trace": [event]}


def emergency_node(state: GraphState) -> dict:
    """Terminal node for the EMERGENCY branch.

    emergency_reasoning was generated in orchestrate_node (before the approval gate)
    so the coordinator could review it during the HITL phase.  Here we simply carry
    it into the terminal event's details.
    """
    emergency_reasoning: Optional[str] = state.get("emergency_reasoning")
    event: ActivityEvent = {
        "step_index": len(state["trace"]),
        "agent":      "Emergency Escalation",
        "node":       "emergency",
        "summary":    "No compatible source found — escalate to regional network",
        "details":    {"emergency_reasoning": emergency_reasoning or ""},
    }
    return {"status": "fulfilled", "trace": [event]}


def declined_node(state: GraphState) -> dict:
    """Terminal node for the DECLINED (rejected) branch."""
    lever = _lever_value(state["lever_result"]["lever"])
    event: ActivityEvent = {
        "step_index": len(state["trace"]),
        "agent":      "Action Declined",
        "node":       "declined",
        "summary":    f"Coordinator declined the {lever} proposal for {state['patient_id']}",
        "details":    {"decision": "reject", "lever": lever},
    }
    return {"status": "declined", "trace": [event]}


# ---------------------------------------------------------------------------
# Edge routers
# ---------------------------------------------------------------------------

def _approval_router(state: GraphState) -> str:
    """Route after approval_gate: 'declined' if rejected, else lever value."""
    if state.get("status") == "declined":
        return "declined"
    return _lever_value(state["lever_result"]["lever"])


# ---------------------------------------------------------------------------
# Shared checkpointer + compiled graph (lazy singleton)
# ---------------------------------------------------------------------------

_saver: InMemorySaver = InMemorySaver()
_compiled_graph = None


def _get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


def _build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("forecast",       forecast_node)
    builder.add_node("desert",         desert_node)
    builder.add_node("orchestrate",    orchestrate_node)
    builder.add_node("approval_gate",  approval_gate_node)
    builder.add_node("redistribution", redistribution_node)
    builder.add_node("donor_matching", donor_matching_node)
    builder.add_node("emergency",      emergency_node)
    builder.add_node("declined",       declined_node)

    builder.add_edge(START,          "forecast")
    builder.add_edge("forecast",     "desert")
    builder.add_edge("desert",       "orchestrate")
    builder.add_edge("orchestrate",  "approval_gate")
    builder.add_conditional_edges(
        "approval_gate",
        _approval_router,
        {
            "inventory": "redistribution",
            "donor":     "donor_matching",
            "emergency": "emergency",
            "declined":  "declined",
        },
    )
    builder.add_edge("redistribution", END)
    builder.add_edge("donor_matching", END)
    builder.add_edge("emergency",      END)
    builder.add_edge("declined",       END)

    return builder.compile(checkpointer=_saver)


# Keep build_graph() for external callers / tests that compile their own graph.
def build_graph():
    """Return a freshly compiled graph (uses the shared InMemorySaver)."""
    return _build_graph()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def _initial_state(
    patient_id: str,
    dataset: CanonicalDataset,
    today: date,
    require_approval: bool,
) -> dict:
    return {
        "patient_id":       patient_id,
        "dataset":          dataset,
        "today":            today,
        "require_approval": require_approval,
        "status":           "predicted",
        "request":          None,
        "forecast_result":  None,
        "desert_cell":      None,
        "lever_result":     None,
        "narration":              None,
        "donor_message_draft":    None,
        "emergency_reasoning":    None,
        "ranked_donors":          [],
        "ranked_inventory":       [],
        "trace":                  [],
    }


def run_request(
    patient_id: str,
    dataset: CanonicalDataset,
    today: date,
) -> GraphState:
    """
    Run to completion with require_approval=False (/activity path).
    Uses a fresh thread_id per call — no HITL interference.
    """
    graph   = _get_compiled_graph()
    thread_id = f"activity-{uuid.uuid4().hex}"
    return graph.invoke(
        _initial_state(patient_id, dataset, today, require_approval=False),
        config={"configurable": {"thread_id": thread_id}},
    )


def propose_request(
    patient_id: str,
    dataset: CanonicalDataset,
    today: date,
) -> dict:
    """
    Invoke graph with require_approval=True; pauses at approval_gate.

    Returns a dict with:
      thread_id       — caller stores this for the subsequent approve call
      status          — "awaiting_approval"
      proposal        — the interrupt payload surfaced to the coordinator
      events_so_far   — trace-so-far + synthesised "awaiting-approval" event
    """
    graph     = _get_compiled_graph()
    thread_id = str(uuid.uuid4())
    cfg       = {"configurable": {"thread_id": thread_id}}

    graph.invoke(_initial_state(patient_id, dataset, today, require_approval=True), config=cfg)

    # Graph is now paused; read checkpoint state for the interrupt payload.
    g_state = graph.get_state(cfg)
    proposal: dict = {}
    for task in g_state.tasks:
        for intr in task.interrupts:
            proposal = intr.value
            break
        if proposal:
            break

    trace_so_far          = list(g_state.values.get("trace", []))
    donor_message_draft   = g_state.values.get("donor_message_draft")
    emergency_reasoning   = g_state.values.get("emergency_reasoning")

    # Synthesise "awaiting-approval" event so the UI feed shows 4 steps.
    lever = proposal.get("chosen_lever", "?")
    awaiting_event: ActivityEvent = {
        "step_index": len(trace_so_far),
        "agent":      "HITL Approval Gate",
        "node":       "approval",
        "summary":    f"Awaiting coordinator approval — {lever} for {patient_id}",
        "details": {
            "status":          "awaiting_approval",
            "proposed_action": proposal.get("proposed_action", {}),
        },
    }

    return {
        "thread_id":           thread_id,
        "status":              "awaiting_approval",
        "proposal":            proposal,
        "events_so_far":       trace_so_far + [awaiting_event],
        "donor_message_draft": donor_message_draft,
        "emergency_reasoning": emergency_reasoning,
    }


def approve_request(thread_id: str, decision: str) -> dict:
    """
    Resume the paused graph with the coordinator's decision.

    decision: "approve" | "reject"

    Returns: status, chosen_lever, full event trace.
    """
    graph  = _get_compiled_graph()
    cfg    = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(Command(resume={"decision": decision}), config=cfg)

    lr    = result.get("lever_result") or {}
    lever = _lever_value(lr.get("lever", "unknown"))

    return {
        "status":              result.get("status", "unknown"),
        "chosen_lever":        lever,
        "trace":               list(result.get("trace", [])),
        "emergency_reasoning": result.get("emergency_reasoning"),
    }
