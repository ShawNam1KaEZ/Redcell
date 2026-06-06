#!/usr/bin/env python3
"""
scripts/verify_live_agent.py — Validate the live agent path for PAT-0001.

Drives the REAL pipeline (run_request + certified_inventory_candidates).
Does NOT reimplement agent or engine logic.

Outputs:
  - LLM provider / model / host / reachability
  - Orchestrate event: lever, target_id, agent_validation, agent_reasoning
  - Certified candidate set (bank_id, expiry_days, dist_km, transport_tier, deliverable)
  - PATH: LIVE (model produced output) or FALLBACK (model off/unreachable)
  - Assertion: target_id == "BB-0036"
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# Repo root on sys.path so hemogrid is importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

PATIENT_ID = "PAT-0001"


def _ollama_reachable(host: str) -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(host, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    # ── LLM config ─────────────────────────────────────────────────────────────
    provider    = os.environ.get("HEMOGRID_LLM_PROVIDER", "ollama").lower().strip()
    model       = os.environ.get("HEMOGRID_LLM_MODEL",     "qwen2.5:7b")
    ollama_host = os.environ.get("OLLAMA_HOST",             "http://localhost:11434")
    timeout_s   = float(os.environ.get("HEMOGRID_LLM_TIMEOUT", "20.0"))

    print("=" * 64)
    print("LLM CONFIG")
    print(f"  provider : {provider}")
    print(f"  model    : {model}")
    print(f"  host     : {ollama_host}")
    print(f"  timeout  : {timeout_s}s")

    reachable = provider == "ollama" and _ollama_reachable(ollama_host)
    print(f"  OLLAMA   : {'REACHABLE' if reachable else 'NOT REACHABLE'}")

    # ── Load dataset (canonical seed=42) ───────────────────────────────────────
    from hemogrid.sources.synthetic_source import SyntheticSource
    ds      = SyntheticSource(seed=42).load()
    patient = next(p for p in ds.patients if p.patient_id == PATIENT_ID)

    today = date.today()

    # ── Run real pipeline to completion ────────────────────────────────────────
    from hemogrid.agents import run_request
    state = run_request(PATIENT_ID, ds, today)

    # ── Extract orchestrate event ───────────────────────────────────────────────
    orch_event = next((e for e in state["trace"] if e["node"] == "orchestrate"), None)

    lever            = None
    agent_validation = None
    agent_reasoning  = None
    used_direct_call = False

    if orch_event:
        d                = orch_event["details"]
        lever            = d.get("chosen_lever")
        agent_validation = d.get("agent_validation")
        agent_reasoning  = d.get("agent_reasoning")

    # target_id: effective downstream target from lever_result (always present in state)
    lr        = state.get("lever_result") or {}
    target_id = lr.get("bank_id") or lr.get("donor_id")

    # ── Certified candidate set (recomputed from engine — single source of truth) ─
    from hemogrid.engine import certified_inventory_candidates
    clinic     = next((c for c in ds.clinics if c.clinic_id == patient.clinic_id), None)
    clinic_loc = clinic.location if clinic else None
    certified  = certified_inventory_candidates(patient, clinic_loc, ds, today)

    # ── Fallback: if agent_validation absent from trace, call _agent_select directly ──
    if agent_validation is None and lever == "inventory":
        from hemogrid.agents.graph import _agent_select
        from hemogrid.engine import choose_lever, forecast_due
        from hemogrid.models import Component, Request

        next_need, _ = forecast_due(patient, today)
        req = Request(
            request_id=f"REQ-VERIFY-{PATIENT_ID}",
            patient_id=PATIENT_ID,
            needed_by_date=next_need,
            component=Component.PRBC,
            units=patient.units_per_session,
        )
        engine_result = choose_lever(req, ds, today)
        agent_out     = _agent_select(certified, PATIENT_ID, engine_result)

        lever            = agent_out["lever"]
        target_id        = agent_out["target_id"]
        agent_validation = agent_out["validation_result"]
        agent_reasoning  = agent_out["agent_reasoning"]
        used_direct_call = True

    # ── Print results ───────────────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("ORCHESTRATE RESULT")
    print(f"  lever            : {lever}")
    print(f"  target_id        : {target_id}")
    print(f"  agent_validation : {agent_validation}")
    print(f"  agent_reasoning  : {agent_reasoning}")
    if used_direct_call:
        print("  (source: direct _agent_select call — agent_validation absent from trace)")
    else:
        print("  (source: orchestrate event in trace)")

    print()
    print("CERTIFIED CANDIDATES (engine-sorted best-first)")
    print(f"  {'bank_id':<12} {'expiry_days':>11}  {'dist_km':>9}  {'transport_tier':>14}  deliverable")
    for c in certified:
        print(
            f"  {c['bank_id']:<12} {c['expiry_days']:>11}d  "
            f"{c['dist_km']:>8.2f}km  {c['transport_tier']:>14}  {c['deliverable']}"
        )

    # ── PATH ────────────────────────────────────────────────────────────────────
    live_validations = {"accepted", "rejected_fallback"}
    path = "LIVE" if agent_validation in live_validations else "FALLBACK"
    print()
    print(f"PATH: {path}")
    print(f"  (agent_validation={agent_validation!r})")

    # ── Assertion ───────────────────────────────────────────────────────────────
    print()
    print("=" * 64)
    if target_id == "BB-0036":
        print(f"ASSERTION: target_id == 'BB-0036'  PASS  (got {target_id!r})")
    else:
        print(f"ASSERTION: target_id == 'BB-0036'  FAIL  (got {target_id!r})")
        sys.exit(1)


if __name__ == "__main__":
    main()
