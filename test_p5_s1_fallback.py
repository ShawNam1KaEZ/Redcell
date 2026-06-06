"""
test_p5_s1_fallback.py — P5-S1 Verification: Golden Profile Fallback Insurance.

Forces LLM to unavailable state (HEMOGRID_LLM_PROVIDER=off) then simulates
each golden profile and asserts exact metric markers are present in output.
"""
import os
import sys

# Force LLM disabled BEFORE importing llm module so generate() raises immediately.
os.environ["HEMOGRID_LLM_PROVIDER"] = "off"

sys.path.insert(0, os.path.dirname(__file__))

from hemogrid.llm import (
    draft_donor_message,
    generate_emergency_escalation,
    narrate_decision,
    narrate_structural_recommendation,
)

PASS = "PASS"
FAIL = "FAIL"

def check(label: str, text: str, required_fragments: list[str]) -> bool:
    print(f"\n{'='*70}")
    print(f"SCENARIO: {label}")
    print(f"{'-'*70}")
    print(text)
    print(f"{'-'*70}")
    all_ok = True
    for fragment in required_fragments:
        ok = fragment in text
        status = PASS if ok else FAIL
        print(f"  [{status}] assertion: {fragment!r}")
        if not ok:
            all_ok = False
    return all_ok


results = []

# ── PAT-0001 DEFAULT: INVENTORY lever → BB-0036 ─────────────────────────────
decision_inv = {
    "lever": "inventory",
    "patient_id": "PAT-0001",
    "patient_abo_rh": "B+",
    "patient_antibodies": ["anti-K"],
    "bank_id": "BB-0036",
    "bank_name": "Government General Hospital",
    "dist_km": 0.7,
    "expiry_days": 3,
    "inventory_options": 1,
}
result_inv = narrate_decision(decision_inv)
assert result_inv.path == "fallback", f"Expected path='fallback', got {result_inv.path!r}"
results.append(check(
    "PAT-0001 DEFAULT -- INVENTORY lever -> BB-0036",
    result_inv.text,
    [
        "PAT-0001",
        "Aarav",
        "anti-K",
        "BB-0036",
        "Government General Hospital, Guntur",
        "0.7 km",
        "Transport Tier 0",
        "3 days",
        "5-day transfusion window",
    ],
))

# ── PAT-0001 BYPASSED: DONOR lever → DON-0002 ───────────────────────────────
decision_don = {
    "lever": "donor",
    "patient_id": "PAT-0001",
    "patient_abo_rh": "B+",
    "patient_antibodies": ["anti-K"],
    "donor_id": "DON-0002",
    "donor_abo_rh": "B+",
    "dist_km": 2.4,
    "match_score": 0.9141,
    "bonded": True,
}
result_don = narrate_decision(decision_don)
assert result_don.path == "fallback", f"Expected path='fallback', got {result_don.path!r}"
results.append(check(
    "PAT-0001 BYPASSED -- DONOR lever -> DON-0002",
    result_don.text,
    [
        "PAT-0001",
        "Aarav",
        "anti-K",
        "DON-0002",
        "B+, K-negative, bonded",
        "2.4 km",
        "0.9141",
        "supply clock of 4 days",
    ],
))

# ── PAT-0001 BYPASSED: draft_donor_message for DON-0002 ─────────────────────
msg = draft_donor_message(
    patient={"patient_id": "PAT-0001", "abo_rh": "B+"},
    donor={"donor_id": "DON-0002", "dist_km": 2.4, "bonded": True},
    need_clock=5,
)
results.append(check(
    "PAT-0001 BYPASSED -- draft_donor_message -> DON-0002",
    msg,
    [
        "DON-0002",
        "PAT-0001",
        "Aarav",
        "B+, K-negative",
        "2.4 km",
        "bonded",
        "Reference: DON-0002 / PAT-0001",
    ],
))

# ── PAT-EMERG-99: EMERGENCY lever ────────────────────────────────────────────
decision_emg = {
    "lever": "emergency",
    "patient_id": "PAT-EMERG-99",
    "patient_abo_rh": "O-",
    "patient_antibodies": ["anti-K", "anti-E", "anti-c", "anti-C"],
}
result_emg = narrate_decision(decision_emg)
assert result_emg.path == "fallback", f"Expected path='fallback', got {result_emg.path!r}"
results.append(check(
    "PAT-EMERG-99 -- EMERGENCY lever (narrate_decision)",
    result_emg.text,
    [
        "PAT-EMERG-99",
        "O-negative",
        "anti-K, anti-E, anti-c, anti-C",
        "2-day transfusion window",
        "100 km search radius",
        "Priority 1",
    ],
))

emg_reasoning = generate_emergency_escalation(
    patient={
        "patient_id": "PAT-EMERG-99",
        "abo_rh": "O-",
        "known_antibodies": ["anti-K", "anti-E", "anti-c", "anti-C"],
    },
    close_but_undeliverable_donors=[{"donor_id": "DON-X"}],
)
results.append(check(
    "PAT-EMERG-99 -- generate_emergency_escalation",
    emg_reasoning,
    [
        "PAT-EMERG-99",
        "O-negative",
        "anti-K, anti-E, anti-c, anti-C",
        "2-day transfusion window",
        "Priority 1",
        "Reference: PAT-EMERG-99",
    ],
))

# ── CLN-HYD-01: CHRONIC desert score 16 ────────────────────────────────────
hyd_rec = narrate_structural_recommendation(
    cell_id="CLN-HYD-01",
    classification="CHRONIC",
    score=16,
    desert_type="COMPATIBILITY_LIMITED",
)
results.append(check(
    "CLN-HYD-01 -- CHRONIC desert structural recommendation",
    hyd_rec,
    [
        "CLN-HYD-01",
        "Hyderabad",
        "score of 16",
        "alloimmunized",
        "anti-K, anti-E, anti-c, anti-C",
        "antibody-safety gate",
        "matched-donor registry",
        "neighboring regions",
    ],
))

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
total = len(results)

passed = sum(results)
print(f"RESULT: {passed}/{total} scenarios fully passed")
if passed == total:
    print("ALL GOLDEN PROFILE FALLBACKS VERIFIED")
else:
    print("SOME ASSERTIONS FAILED — see above")
    sys.exit(1)
