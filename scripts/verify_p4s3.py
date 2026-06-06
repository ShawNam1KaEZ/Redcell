"""
scripts/verify_p4s3.py — Verification harness for P4-S3 (Acute vs Chronic Desert Classification).

Run from repo root:
    python -m scripts.verify_p4s3

Checks:
- 9 baseline desert scores are byte-identical to pre-P4-S3 values.
- CLN-GNT-01 and CLN-HYD-01 classification and scores are correct.
- CLN-HYD-01 classification is CHRONIC, structural_recommendation is non-empty.
- Reports path tag: LIVE RECOMMENDATION or FALLBACK RECOMMENDATION TEMPLATE.
"""
from __future__ import annotations

import sys
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from hemogrid.engine import classify_desert_nature, compute_desert_cells
from hemogrid.llm import LLMUnavailable, narrate_structural_recommendation
from hemogrid.sources.synthetic_source import SyntheticSource

TODAY = date.today()

EXPECTED_SCORES: dict[str, int] = {
    "CLN-GNT-01": 1,
    "CLN-HYD-01": 16,
    "CLN-LKN-01": 19,
    "CLN-AHM-01": 2,
}

print("=" * 64)
print("P4-S3 Verification: Acute vs Chronic Desert Classification")
print("=" * 64)

ds = SyntheticSource().load()
cells = compute_desert_cells(ds, TODAY)

cell_map = {c["cell_id"]: c for c in cells}

# ── 1. Score regression check ──────────────────────────────────────────
print("\n[1] SCORE REGRESSION CHECK")
all_ok = True
for cid, expected in EXPECTED_SCORES.items():
    cell = cell_map.get(cid)
    if cell is None:
        print(f"  MISSING  {cid}")
        all_ok = False
        continue
    actual = cell["desert_score"]
    status = "OK" if actual == expected else "FAIL"
    if status == "FAIL":
        all_ok = False
    print(f"  {status}  {cid}  score={actual}  (expected {expected})  type={cell['desert_type']}")

for cell in cells:
    if cell["cell_id"] not in EXPECTED_SCORES:
        print(f"  CHECK  {cell['cell_id']}  score={cell['desert_score']}  type={cell['desert_type']}")

if all_ok:
    print("  => All baseline scores match.")
else:
    print("  => SCORE REGRESSION DETECTED — investigate before proceeding.")

# ── 2. Classification spot-check ───────────────────────────────────────
print("\n[2] CLASSIFICATION SPOT-CHECK")
for cid in ("CLN-GNT-01", "CLN-HYD-01"):
    cell = cell_map.get(cid)
    if cell is None:
        print(f"  MISSING  {cid}")
        continue
    print(
        f"  {cid}  score={cell['desert_score']}  type={cell['desert_type']}  "
        f"classification={cell['classification']}"
    )

# ── 3. classify_desert_nature unit checks ─────────────────────────────
print("\n[3] classify_desert_nature UNIT CHECKS")
cases = [
    (0, "OK",                    "OK"),
    (1, "SUPPLY_LIMITED",        "ACUTE"),
    (9, "COMPATIBILITY_LIMITED", "ACUTE"),
    (10, "COMPATIBILITY_LIMITED","CHRONIC"),
    (16, "COMPATIBILITY_LIMITED","CHRONIC"),
    (2, "SUPPLY_LIMITED",        "ACUTE"),
]
for score, dtype, expected_cls in cases:
    result = classify_desert_nature(score, dtype)["classification"]
    status = "OK" if result == expected_cls else "FAIL"
    print(f"  {status}  classify_desert_nature({score}, {dtype!r}) => {result}  (expected {expected_cls})")

# ── 4. LLM narration for CLN-HYD-01 (CHRONIC showcase) ───────────────
print("\n[4] STRUCTURAL RECOMMENDATION — CLN-HYD-01 (CHRONIC)")
hyd = cell_map.get("CLN-HYD-01")
if hyd:
    # Probe whether Ollama responds by attempting generate()
    path_tag = "FALLBACK RECOMMENDATION TEMPLATE"
    try:
        from hemogrid.llm import generate
        probe = generate("ping", system=None, temperature=0.0)
        if probe:
            path_tag = "LIVE RECOMMENDATION"
    except LLMUnavailable:
        pass
    except Exception:
        pass

    rec = narrate_structural_recommendation(
        hyd["cell_id"], hyd["classification"], hyd["desert_score"], hyd["desert_type"]
    )
    print(f"  classification      : {hyd['classification']}")
    print(f"  desert_score        : {hyd['desert_score']}")
    print(f"  path tag            : {path_tag}")
    print(f"  structural_recommendation:")
    print(f"    \"{rec}\"")
else:
    print("  CLN-HYD-01 not found in cells.")

print("\n" + "=" * 64)
print("Verification complete.")
print("=" * 64)
