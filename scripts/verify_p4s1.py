"""
scripts/verify_p4s1.py — P4-S1 verification harness.

Forces the DONOR lever for PAT-0001 by clearing all inventory units in the
in-memory dataset (source/seed untouched).  Calls propose_request, prints
the draft, then approves and confirms the draft is unchanged.

Run from repo root:
    python -m scripts.verify_p4s1
"""
from __future__ import annotations

import sys
from datetime import date

sys.path.insert(0, ".")

from hemogrid.agents.graph import _get_compiled_graph, approve_request, propose_request
from hemogrid.sources.synthetic_source import SyntheticSource


def _clear_inventory(ds):
    for bank in ds.blood_banks:
        bank.units.clear()
    return ds


def main() -> None:
    print("=" * 64)
    print("P4-S1 VERIFICATION — donor lever + message draft")
    print("=" * 64)

    ds    = SyntheticSource().load()
    today = date.today()

    # Confirm normal path first (should be INVENTORY)
    from hemogrid.engine import choose_lever, forecast_due
    from hemogrid.models import Component, Request
    patient = next(p for p in ds.patients if p.patient_id == "PAT-0001")
    next_need, _ = forecast_due(patient, today)
    req = Request(
        request_id="REQ-VERIFY", patient_id="PAT-0001",
        needed_by_date=next_need, component=Component.PRBC,
        units=patient.units_per_session,
    )
    normal_lever = choose_lever(req, ds, today)
    print(f"\n[GOLDEN CHECK] PAT-0001 normal lever  : {normal_lever['lever'].value}")
    print(f"               days_until_due          : {(next_need - today).days}")

    # Clear inventory to force donor path
    ds_cleared = SyntheticSource().load()
    _clear_inventory(ds_cleared)

    cleared_lever = choose_lever(req, ds_cleared, today)
    print(f"[CLEARED INV]  PAT-0001 cleared lever  : {cleared_lever['lever'].value}")
    assert cleared_lever["lever"].value == "donor", "Expected donor lever after clearing inventory"

    # --- PROPOSE ---
    print("\n--- PROPOSE PAT-0001 (cleared inventory) ---")
    prop = propose_request("PAT-0001", ds_cleared, today)

    chosen_lever = prop["proposal"]["chosen_lever"]
    pa           = prop["proposal"]["proposed_action"]
    donor_id     = pa.get("donor_id", "?")
    draft        = prop.get("donor_message_draft")
    thread_id    = prop["thread_id"]

    print(f"  chosen_lever       : {chosen_lever}")
    print(f"  target_donor_id    : {donor_id}")
    print(f"  donor_message_draft: {repr(draft)}")

    path_tag = "FALLBACK TEMPLATE" if draft and draft.startswith("Dear Donor") else "LIVE DRAFT"
    # More robust detection: check if Ollama responded by looking for typical template pattern
    if draft and "please contact us immediately" in draft.lower():
        path_tag = "FALLBACK TEMPLATE"
    elif draft:
        path_tag = "LIVE DRAFT"
    else:
        path_tag = "DRAFT MISSING"

    print(f"  path_tag           : {path_tag}")

    assert chosen_lever == "donor", f"Expected 'donor', got {chosen_lever!r}"
    assert donor_id == "DON-0002",  f"Expected 'DON-0002', got {donor_id!r} (fragility #1)"
    assert draft is not None,       "donor_message_draft must not be None"
    assert len(draft) > 20,         "donor_message_draft too short"

    # --- APPROVE and confirm draft is unchanged ---
    print("\n--- APPROVE thread ---")
    approve_result = approve_request(thread_id, "approve")
    print(f"  status             : {approve_result['status']}")
    print(f"  chosen_lever       : {approve_result['chosen_lever']}")

    # Read final graph state and confirm draft was not mutated
    graph       = _get_compiled_graph()
    final_state = graph.get_state({"configurable": {"thread_id": thread_id}})
    post_draft  = final_state.values.get("donor_message_draft")

    print(f"  pre-approve draft  : {repr(draft[:80])}...")
    print(f"  post-approve draft : {repr((post_draft or '')[:80])}...")
    assert post_draft == draft, "IDEMPOTENCY FAILURE: draft mutated after approval!"
    print("  idempotency check  : PASS — draft unchanged after resume")

    print(f"\n[VERIFICATION COMPLETE] path_tag={path_tag}")
    print("=" * 64)


if __name__ == "__main__":
    main()
