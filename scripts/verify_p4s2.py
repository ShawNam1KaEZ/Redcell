"""
scripts/verify_p4s2.py — P4-S2 Emergency Response Agent verification harness.

Drives two patients:
  1. PAT-0001 (golden regression)   → chosen_lever == "inventory", target == "BB-0036"
  2. PAT-EMERG-99 (emergency path)  → chosen_lever == "emergency", emergency_reasoning set

Run from repo root:
    python -m scripts.verify_p4s2
"""
from __future__ import annotations

import sys
from datetime import date

sys.path.insert(0, ".")

from hemogrid.agents.graph import approve_request, propose_request, run_request
from hemogrid.engine import choose_lever, forecast_due
from hemogrid.models import Component, Request
from hemogrid.sources.synthetic_source import SyntheticSource


def _injection_proof(ds) -> None:
    """Print the exact injection lines confirming PAT-EMERG-99 is last."""
    ids = [p.patient_id for p in ds.patients]
    last_idx = len(ids) - 1
    # find all post-RNG injected patient IDs
    post_rng = [pid for pid in ids if pid in ("PAT-EMERG-99",)]
    print("\n[INJECTION PROOF] Patient list tail (last 5):")
    for pid in ids[-5:]:
        print(f"  [{ids.index(pid):>4}] {pid}")
    print(f"  PAT-EMERG-99 index = {ids.index('PAT-EMERG-99')} (total = {len(ids)})")
    assert ids[-1] == "PAT-EMERG-99", \
        f"PAT-EMERG-99 must be last in patients list; got {ids[-1]!r}"
    print("  Post-RNG position check: PASS")


def _golden_check(ds, today: date) -> None:
    """PAT-0001 must still choose inventory → BB-0036."""
    print("\n" + "=" * 64)
    print("[GOLDEN REGRESSION] PAT-0001")
    print("=" * 64)

    patient = next(p for p in ds.patients if p.patient_id == "PAT-0001")
    next_need, _ = forecast_due(patient, today)
    need_clock = (next_need - today).days
    req = Request(
        request_id="REQ-VERIFY-PAT0001",
        patient_id="PAT-0001",
        needed_by_date=next_need,
        component=Component.PRBC,
        units=patient.units_per_session,
    )
    result = choose_lever(req, ds, today)
    lever   = result["lever"].value
    bank_id = result.get("bank_id", "?")

    print(f"  chosen_lever     : {lever}")
    print(f"  bank_id          : {bank_id}")
    print(f"  need_clock       : {need_clock}d")
    print(f"  days_to_expiry   : {result.get('days_to_expiry', '?')}d")
    print(f"  distance_km      : {result.get('distance_km', '?')} km")

    assert lever   == "inventory", f"GOLDEN FAIL: expected 'inventory', got {lever!r}"
    assert bank_id == "BB-0036",   f"GOLDEN FAIL: expected 'BB-0036', got {bank_id!r}"
    print("  Golden regression: PASS")


def _emergency_engine_check(ds, today: date) -> None:
    """PAT-EMERG-99 must choose lever == 'emergency' from the engine."""
    print("\n" + "=" * 64)
    print("[ENGINE CHECK] PAT-EMERG-99 -> choose_lever")
    print("=" * 64)

    patient = next(p for p in ds.patients if p.patient_id == "PAT-EMERG-99")
    next_need, _ = forecast_due(patient, today)
    need_clock = (next_need - today).days
    req = Request(
        request_id="REQ-VERIFY-EMERG99",
        patient_id="PAT-EMERG-99",
        needed_by_date=next_need,
        component=Component.PRBC,
        units=patient.units_per_session,
    )
    result = choose_lever(req, ds, today)
    lever  = result["lever"].value

    print(f"  patient_id       : PAT-EMERG-99")
    print(f"  abo_rh           : O{'-' if not patient.rh_d else '+'}")
    print(f"  antibodies       : {patient.known_antibodies}")
    print(f"  need_clock       : {need_clock}d")
    print(f"  chosen_lever     : {lever}")

    assert lever == "emergency", f"Expected 'emergency', got {lever!r}"
    print("  Engine emergency lever: PASS")


def _emergency_graph_propose(ds, today: date) -> str:
    """
    Run HITL propose for PAT-EMERG-99.  Returns thread_id.
    Validates: chosen_lever == 'emergency', emergency_reasoning present.
    """
    print("\n" + "=" * 64)
    print("[GRAPH PROPOSE] PAT-EMERG-99 -> propose_request")
    print("=" * 64)

    prop = propose_request("PAT-EMERG-99", ds, today)
    chosen_lever      = prop["proposal"]["chosen_lever"]
    emergency_reasoning = prop.get("emergency_reasoning")
    thread_id         = prop["thread_id"]

    print(f"  thread_id        : {thread_id}")
    print(f"  chosen_lever     : {chosen_lever}")
    print(f"  emergency_reasoning present: {emergency_reasoning is not None}")
    if emergency_reasoning:
        # Determine path tag
        fallback_markers = [
            "CRISIS ALERT",
            "please contact us immediately",
            "Immediate actions required: broadcast",
        ]
        is_fallback = any(m.lower() in emergency_reasoning.lower() for m in fallback_markers)
        path_tag = "FALLBACK CRISIS TEMPLATE" if is_fallback else "LIVE REASONING"
        print(f"  path_tag         : {path_tag}")
        print(f"  emergency_reasoning:\n    {emergency_reasoning[:300]}")
    else:
        path_tag = "REASONING MISSING"
        print("  WARNING: emergency_reasoning is None")

    assert chosen_lever == "emergency", \
        f"Expected 'emergency', got {chosen_lever!r}"
    assert emergency_reasoning is not None, \
        "emergency_reasoning must not be None for emergency lever"
    assert len(emergency_reasoning) > 20, \
        "emergency_reasoning too short — fallback or LLM returned empty"

    print(f"\n  Propose check: PASS  (path_tag={path_tag})")
    return thread_id, path_tag


def _emergency_graph_approve(thread_id: str) -> None:
    """
    Resume the paused graph with 'approve' and confirm fulfilled + reasoning carried.
    """
    print("\n" + "=" * 64)
    print("[GRAPH APPROVE] PAT-EMERG-99 -> approve_request(approve)")
    print("=" * 64)

    result = approve_request(thread_id, "approve")
    status           = result["status"]
    chosen_lever     = result["chosen_lever"]
    emergency_reasoning = result.get("emergency_reasoning")

    print(f"  status           : {status}")
    print(f"  chosen_lever     : {chosen_lever}")
    print(f"  emergency_reasoning present: {emergency_reasoning is not None}")

    assert status       == "fulfilled",  f"Expected 'fulfilled', got {status!r}"
    assert chosen_lever == "emergency",  f"Expected 'emergency', got {chosen_lever!r}"
    assert emergency_reasoning is not None, \
        "emergency_reasoning must be present in approve response"

    print("  Approve check: PASS")


def _emergency_graph_reject(ds, today: date) -> None:
    """
    Run a second HITL cycle and reject — confirm declined + reasoning still present.
    """
    print("\n" + "=" * 64)
    print("[GRAPH REJECT] PAT-EMERG-99 -> approve_request(reject)")
    print("=" * 64)

    prop = propose_request("PAT-EMERG-99", ds, today)
    thread_id = prop["thread_id"]
    result    = approve_request(thread_id, "reject")

    status   = result["status"]
    er       = result.get("emergency_reasoning")

    print(f"  status           : {status}")
    print(f"  emergency_reasoning present: {er is not None}")

    assert status == "declined", f"Expected 'declined', got {status!r}"
    print("  Reject check: PASS")


def _activity_check(ds, today: date) -> None:
    """
    /activity path (require_approval=False) for PAT-EMERG-99.
    Confirms emergency_reasoning appears in the emergency node's details.
    """
    print("\n" + "=" * 64)
    print("[ACTIVITY] PAT-EMERG-99 -> run_request (no HITL)")
    print("=" * 64)

    result = run_request("PAT-EMERG-99", ds, today)
    lever  = result["lever_result"]["lever"].value
    er     = result.get("emergency_reasoning")
    trace  = result.get("trace", [])

    print(f"  chosen_lever     : {lever}")
    print(f"  emergency_reasoning: {repr((er or '')[:120])}")
    print(f"  trace steps      : {len(trace)}")

    assert lever == "emergency", f"Expected 'emergency', got {lever!r}"
    assert er is not None,       "emergency_reasoning missing from run_request result"

    # Confirm it's also in the emergency node's event details
    emerg_events = [e for e in trace if e["node"] == "emergency"]
    assert emerg_events, "No 'emergency' event in trace"
    assert "emergency_reasoning" in emerg_events[0]["details"], \
        "emergency_reasoning not in emergency event details"

    print("  Activity check: PASS")


def main() -> None:
    print("=" * 64)
    print("P4-S2 VERIFICATION - Emergency Response Agent")
    print("=" * 64)

    ds    = SyntheticSource().load()
    today = date.today()

    # ── 1. Injection proof ──────────────────────────────────────────────────
    _injection_proof(ds)

    # ── 2. Golden regression: PAT-0001 must still be inventory/BB-0036 ──────
    _golden_check(ds, today)

    # ── 3. Engine: PAT-EMERG-99 → emergency lever ───────────────────────────
    _emergency_engine_check(ds, today)

    # ── 4. Graph HITL propose ───────────────────────────────────────────────
    thread_id, path_tag = _emergency_graph_propose(ds, today)

    # ── 5. Graph HITL approve → fulfilled ───────────────────────────────────
    _emergency_graph_approve(thread_id)

    # ── 6. Graph HITL reject → declined ─────────────────────────────────────
    _emergency_graph_reject(ds, today)

    # ── 7. Activity path (no HITL) ──────────────────────────────────────────
    _activity_check(ds, today)

    print("\n" + "=" * 64)
    print(f"[P4-S2 VERIFICATION COMPLETE]  path_tag={path_tag}")
    print("All checks PASS.")
    print("=" * 64)


if __name__ == "__main__":
    main()
