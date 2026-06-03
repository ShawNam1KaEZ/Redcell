"""
verify_step3.py — verification for Phase 2 Step 3.
Uses ASCII only (Windows cp1252 safe).
"""
from datetime import date, timedelta

from hemogrid.sources.synthetic_source import SyntheticSource
from hemogrid.engine import compute_desert_cells, choose_lever, forecast_due
from hemogrid.models import ABOGroup, Component, Request

today = date.today()

print("=" * 70)
print("LOAD 1")
print("=" * 70)
ds1 = SyntheticSource().load()
print(f"\nPatient count: {len(ds1.patients)}")
print(f"Donor count:   {len(ds1.donors)}")

# ------------------------------------------------------------------
# A) Desert cells
# ------------------------------------------------------------------
cells = compute_desert_cells(ds1, today)
print(f"\n[A] /api/deserts => {len(cells)} cells, sorted by desert_score desc")
hdr = f"{'cell_id':<18} {'pts_due':>7} {'demand':>6} {'raw_prbc':>8} " \
      f"{'compat_safe':>11} {'inv_sup':>7} {'don_sup':>7} {'activ':>6} {'score':>6}"
print(hdr)
print("-" * len(hdr))
for c in cells:
    print(f"{c['cell_id']:<18} {c['patients_due']:>7} {c['demand_units']:>6} "
          f"{c['raw_prbc_nearby']:>8} {c['compatible_safe_units']:>11} "
          f"{c['inventory_supply']:>7} {c['donor_supply']:>7} "
          f"{c['activatable_supply']:>6} {c['desert_score']:>6}")

print("\n[A] Top 3 cells -- full breakdown:")
for rank, c in enumerate(cells[:3], 1):
    print(f"\n  #{rank}: {c['cell_id']} -- {c['name']}")
    print(f"       lat={c['lat']:.4f}, lng={c['lng']:.4f}")
    print(f"       patients_due={c['patients_due']}, demand_units={c['demand_units']}")
    print(f"       banks_nearby={c['banks_nearby']}, donors_nearby={c['donors_nearby']}, "
          f"eligible_donors={c['eligible_donors_nearby']}")
    print(f"       raw_prbc_nearby={c['raw_prbc_nearby']}")
    print(f"       compatible_safe_units={c['compatible_safe_units']}")
    print(f"       inventory_supply={c['inventory_supply']}, donor_supply={c['donor_supply']}")
    print(f"       activatable_supply={c['activatable_supply']}, "
          f"desert_score={c['desert_score']}")

# ------------------------------------------------------------------
# B) Guntur vs Lucknow contrast
# ------------------------------------------------------------------
guntur_cell  = next((c for c in cells if c["cell_id"] == "CLN-GNT-01"), None)
lucknow_cell = next((c for c in cells if c["cell_id"] == "CLN-LKN-01"), None)

print("\n[B] Guntur vs Lucknow contrast:")
if guntur_cell:
    print(f"     Guntur  -- desert_score={guntur_cell['desert_score']}, "
          f"raw_prbc={guntur_cell['raw_prbc_nearby']}, "
          f"compat_safe={guntur_cell['compatible_safe_units']}, "
          f"activatable={guntur_cell['activatable_supply']}")
if lucknow_cell:
    gap = lucknow_cell['raw_prbc_nearby'] - lucknow_cell['compatible_safe_units']
    print(f"     Lucknow -- desert_score={lucknow_cell['desert_score']}, "
          f"raw_prbc={lucknow_cell['raw_prbc_nearby']}, "
          f"compat_safe={lucknow_cell['compatible_safe_units']}, "
          f"activatable={lucknow_cell['activatable_supply']}")
    print(f"     Immunological gap (raw - compat_safe): {gap} units")

most_stressed = cells[0]["cell_id"]
print(f"\n     Most stressed: {most_stressed} "
      f"{'[PASS: LKN is #1]' if most_stressed == 'CLN-LKN-01' else '[FAIL: NOT LKN]'}")
g_score = guntur_cell["desert_score"] if guntur_cell else -1
print(f"     Guntur score=0: {'[PASS]' if g_score == 0 else '[FAIL score=' + str(g_score) + ']'}")

# ------------------------------------------------------------------
# C) Golden scenario
# ------------------------------------------------------------------
print("\n[C] Golden scenario re-run")
pat = next(p for p in ds1.patients if p.patient_id == "PAT-0001")
next_need, due = forecast_due(pat, today)
days_away = (next_need - today).days
print(f"     PAT-0001 -- abo={pat.abo_group.value}, rh_d={pat.rh_d}, "
      f"antibodies={pat.known_antibodies}")
print(f"     next_need={next_need}, due_soon={due}, days_until={days_away}")

req = Request(
    request_id="REQ-VERIFY-01",
    patient_id="PAT-0001",
    needed_by_date=next_need,
    component=Component.PRBC,
    units=1,
)
result = choose_lever(req, ds1, today)
lever_val = result.get("lever")
print(f"     choose_lever => lever={lever_val}")
if lever_val and lever_val.value == "inventory":
    bank_id = result.get("bank_id")
    print(f"       bank_id={bank_id}, dist={result.get('distance_km')} km, "
          f"expiry_days={result.get('days_to_expiry')}")
    print(f"       BB-0036: {'[PASS]' if bank_id == 'BB-0036' else '[FAIL: ' + str(bank_id) + ']'}")
elif lever_val:
    print(f"       [FAIL: expected inventory lever, got {lever_val}]")

# Clear ALL compatible inventory (within search radius) to force donor fallback.
# There may be other compatible B+/K-neg units at other nearby banks beyond BB-0036;
# we need to drain the full inventory pool to isolate the donor path.
from hemogrid.engine import abo_rh_compatible, phenotype_antibody_safe
from hemogrid.models import Location
from hemogrid.engine import haversine_km as _hav
guntur_loc = Location(lat=16.3019, lng=80.4378)
saved_units = {}
cleared_banks = 0
for bank in ds1.blood_banks:
    if not bank.coord_valid:
        continue
    if _hav(guntur_loc, bank.location) > 100.0:
        continue
    compat = [
        u for u in bank.units
        if abo_rh_compatible(pat, u) and phenotype_antibody_safe(pat, u)
    ]
    if compat:
        saved_units[bank.bank_id] = bank.units[:]
        bank.units = [u for u in bank.units if u not in compat]
        cleared_banks += 1
print(f"\n     Cleared compatible inventory from {cleared_banks} bank(s) within 100 km")
r2 = choose_lever(req, ds1, today)
l2 = r2.get("lever")
print(f"     choose_lever => lever={l2}")
if l2 and l2.value == "donor":
    d_id = r2.get("donor_id")
    bd   = r2["breakdown"]
    print(f"       donor_id={d_id}, score={r2.get('donor_score')}, "
          f"dist={bd['proximity_km']} km, bonded={bd['bonded']}")
    print(f"       DON-0002: {'[PASS]' if d_id == 'DON-0002' else '[FAIL: ' + str(d_id) + ']'}")
elif l2 and l2.value == "emergency":
    print("       [NOTE: no compatible donor found — expected donor fallback]")
else:
    print(f"       [FAIL: unexpected lever {l2}]")
# restore
for bank in ds1.blood_banks:
    if bank.bank_id in saved_units:
        bank.units = saved_units[bank.bank_id]

# ------------------------------------------------------------------
# D) DON-0002 identity
# ------------------------------------------------------------------
print("\n[D] DON-0002 identity")
don2 = next((d for d in ds1.donors if d.donor_id == "DON-0002"), None)
if don2:
    print(f"     abo={don2.abo_group.value}, rh_d={don2.rh_d}, "
          f"K={don2.phenotype.K if don2.phenotype else 'N/A'}")
    print(f"     linked_patients={don2.linked_patients}")
    ok_abo  = don2.abo_group == ABOGroup.B and don2.rh_d
    ok_k    = don2.phenotype is not None and not don2.phenotype.K
    ok_bond = "PAT-0001" in don2.linked_patients
    print(f"     B+: {'[PASS]' if ok_abo else '[FAIL]'}  "
          f"K-neg: {'[PASS]' if ok_k else '[FAIL]'}  "
          f"bonded PAT-0001: {'[PASS]' if ok_bond else '[FAIL]'}")
else:
    print("     DON-0002 NOT FOUND [FAIL]")

# ------------------------------------------------------------------
# E) Stressed patients present
# ------------------------------------------------------------------
stressed_ids = {"PAT-0201", "PAT-0202", "PAT-0203", "PAT-0204"}
found = {p.patient_id for p in ds1.patients} & stressed_ids
print(f"\n[E] Stressed patients present: {sorted(found)} "
      f"{'[PASS]' if found == stressed_ids else '[FAIL missing: ' + str(stressed_ids - found) + ']'}")
for pid in sorted(stressed_ids):
    p = next((x for x in ds1.patients if x.patient_id == pid), None)
    if p:
        print(f"     {pid} abo={p.abo_group.value} rh_d={p.rh_d} "
              f"antibodies={p.known_antibodies} clinic={p.clinic_id}")

# ------------------------------------------------------------------
# F) Determinism
# ------------------------------------------------------------------
print("\n[F] Determinism (two fresh loads)")
ds2 = SyntheticSource().load()
cells2 = compute_desert_cells(ds2, today)
a, b_ = cells[0], cells2[0]
match = (a["cell_id"] == b_["cell_id"]
         and a["desert_score"] == b_["desert_score"]
         and a["raw_prbc_nearby"] == b_["raw_prbc_nearby"]
         and a["compatible_safe_units"] == b_["compatible_safe_units"])
print(f"     Load-1: {a['cell_id']} score={a['desert_score']} "
      f"raw={a['raw_prbc_nearby']} compat={a['compatible_safe_units']}")
print(f"     Load-2: {b_['cell_id']} score={b_['desert_score']} "
      f"raw={b_['raw_prbc_nearby']} compat={b_['compatible_safe_units']}")
print(f"     Identical: {'[PASS]' if match else '[FAIL]'}")

print("\n" + "=" * 70)
print("DONE")
