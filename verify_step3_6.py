"""
verify_step3_6.py -- Phase 2 Step 3.6 verification.
ASCII only (Windows cp1252 safe).

Checks:
  (a) Guntur demand profile
  (b) Guntur new shelf composition + days-of-supply justification
  (c) Golden scenario with ranked-unit proof that BB-0036 still wins
  (d) Hyderabad redistribution (banks + counts) before/after confirmation
  (e) Full 9-cell table + partition check
  (f) DON-0002 identity + determinism
  (g) Any surprises noted
"""
from datetime import date, timedelta
from collections import Counter

from hemogrid.sources.synthetic_source import SyntheticSource
from hemogrid.engine import (
    compute_desert_cells, choose_lever, forecast_due,
    abo_rh_compatible, phenotype_antibody_safe, haversine_km,
)
from hemogrid.models import ABOGroup, Component, Request, Location, Phenotype

today = date.today()

print("=" * 72)
print("LOAD")
print("=" * 72)
ds = SyntheticSource().load()
print(f"Patients: {len(ds.patients)}  Donors: {len(ds.donors)}  Banks: {len(ds.blood_banks)}")

guntur_loc  = Location(lat=16.3019, lng=80.4378)
hyd_loc     = Location(lat=17.3850, lng=78.4867)

# ──────────────────────────────────────────────────────────────────────────────
# (a) Guntur demand profile
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(a) GUNTUR DEMAND PROFILE")
print("=" * 72)

due_gnt = [
    p for p in ds.patients
    if p.clinic_id == "CLN-GNT-01" and forecast_due(p, today, 7)[1]
]
unit_demand  = Counter()
pt_demand    = Counter()
for p in due_gnt:
    rh  = "+" if p.rh_d else "-"
    key = f"{p.abo_group.value}{rh}"
    unit_demand[key]  += p.units_per_session
    pt_demand[key]    += 1

print(f"Due patients: {len(due_gnt)}   Total D: {sum(unit_demand.values())}")
print(f"Daily rate: {sum(unit_demand.values())/7:.2f} units/day")
print(f"4d buffer: {sum(unit_demand.values())/7*4:.1f}  "
      f"5d: {sum(unit_demand.values())/7*5:.1f}  "
      f"6d: {sum(unit_demand.values())/7*6:.1f}")
print()
print(f"{'ABO/Rh':<8} {'patients':>8} {'units':>6} {'% units':>8}")
print("-" * 36)
total_u = sum(unit_demand.values())
for k in sorted(unit_demand.keys()):
    print(f"{k:<8} {pt_demand[k]:>8} {unit_demand[k]:>6} {unit_demand[k]/total_u*100:>7.1f}%")

print("\nAlloimmunized:")
allo = [(p.patient_id, p.abo_group.value, "+" if p.rh_d else "-",
         p.known_antibodies, p.units_per_session)
        for p in due_gnt if p.known_antibodies]
for pid, abo, rh, ab, ups in allo:
    print(f"  {pid}: {abo}{rh} {ups}u/sess  ab={ab}")

# ──────────────────────────────────────────────────────────────────────────────
# (b) Guntur new shelf composition
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(b) GUNTUR NEW SHELF COMPOSITION")
print("=" * 72)

demo_bank_id = "BB-0036"
gnt_banks = [
    b for b in ds.blood_banks
    if b.coord_valid and haversine_km(guntur_loc, b.location) <= 50.0
]

print(f"\nAll in-date PRBC units at Guntur banks (within 50km), by bank:")
print(f"{'bank_id':<10} {'dist_km':>7} {'B+ K-neg':>9} {'typed':>6} {'untyped':>8} "
      f"{'total':>6}  bank_name")
print("-" * 80)
total_prbc = 0
by_type = Counter()
by_typed_flag = Counter()
for b in sorted(gnt_banks, key=lambda x: haversine_km(guntur_loc, x.location)):
    dist = haversine_km(guntur_loc, b.location)
    in_date_prbc = [
        u for u in b.units
        if u.component == Component.PRBC and u.storage_status == "ok"
        and u.expiry_date >= today
    ]
    if not in_date_prbc and b.bank_id not in ("BB-0037", "BB-0041"):
        continue
    typed_ct   = sum(1 for u in in_date_prbc if u.phenotype_tags is not None)
    untyped_ct = sum(1 for u in in_date_prbc if u.phenotype_tags is None)
    b_kneg     = sum(1 for u in in_date_prbc
                     if u.abo == ABOGroup.B and u.rh_d
                     and u.phenotype_tags is not None and not u.phenotype_tags.K)
    tag = " <-- demo" if b.bank_id == demo_bank_id else ""
    print(f"{b.bank_id:<10} {dist:>7.1f} {b_kneg:>9} {typed_ct:>6} {untyped_ct:>8} "
          f"{len(in_date_prbc):>6}  {b.name[:30]}{tag}")
    total_prbc += len(in_date_prbc)
    for u in in_date_prbc:
        rh  = "+" if u.rh_d else "-"
        key = f"{u.abo.value}{rh}"
        by_type[key] += 1
        by_typed_flag["typed" if u.phenotype_tags else "untyped"] += 1
print(f"\n  Total in-date PRBC across Guntur 50km radius: {total_prbc}")

print("\n  ABO/Rh breakdown (all Guntur banks):")
for k in sorted(by_type.keys()):
    print(f"    {k}: {by_type[k]}")
print(f"  Typed: {by_typed_flag['typed']}  Untyped: {by_typed_flag['untyped']}")

# Days-of-supply
added_units  = 28
existing_units = total_prbc - added_units
D_guntur     = sum(unit_demand.values())
dos = added_units / (D_guntur / 7)
print(f"\n  Days-of-supply justification:")
print(f"    D={D_guntur} units over 7-day window -> {D_guntur/7:.2f} units/day")
print(f"    New shelf = {added_units} units -> {dos:.1f}-day buffer")
print(f"    Target range: 4-6 days.  Chosen: 5 days (28 = round(5 x 5.57) = 27.9 -> 28)")
print(f"    Existing PRBC at Guntur banks (from random gen): {existing_units}")
print(f"    Total S_raw candidate: {total_prbc}")

# ──────────────────────────────────────────────────────────────────────────────
# (c) Golden scenario re-run with ranked-unit proof
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(c) GOLDEN SCENARIO — choose_lever(PAT-0001)")
print("=" * 72)

pat = next(p for p in ds.patients if p.patient_id == "PAT-0001")
next_need, due = forecast_due(pat, today)
days_away = (next_need - today).days
print(f"\nPAT-0001: {pat.abo_group.value}{'+'if pat.rh_d else'-'} "
      f"ab={pat.known_antibodies}  "
      f"next_need={next_need}  due_soon={due}  days_away={days_away}")

# Collect ALL compatible+safe inventory candidates and show top 4 sorted
inventory_candidates = []
for bank in ds.blood_banks:
    if not bank.coord_valid:
        continue
    dist = haversine_km(guntur_loc, bank.location)
    if dist > 100.0:
        continue
    for unit in bank.units:
        if (unit.component == Component.PRBC and unit.storage_status == "ok"
                and unit.expiry_date >= today
                and abo_rh_compatible(pat, unit)
                and phenotype_antibody_safe(pat, unit)):
            inventory_candidates.append((bank, unit, dist))

inventory_candidates.sort(key=lambda t: (
    (t[1].expiry_date - today).days,
    t[2],
    t[0].bank_id,
))
print(f"\nAll compatible+safe PRBC candidates for PAT-0001 ({len(inventory_candidates)} total):")
print(f"  (sort: expiry_days ASC, dist_km ASC, bank_id ASC)")
print(f"{'rank':<5} {'bank_id':<10} {'dist_km':>8} {'exp_days':>9} {'abo':>4} {'K_neg':>6}  bank_name")
print("-" * 70)
for i, (b, u, dist) in enumerate(inventory_candidates[:6], 1):
    exp_days = (u.expiry_date - today).days
    k_neg    = "yes" if (u.phenotype_tags and not u.phenotype_tags.K) else "n/a"
    marker   = " <-- WINNER" if i == 1 else ""
    print(f"  #{i:<3} {b.bank_id:<10} {dist:>8.1f} {exp_days:>9} {u.abo.value:>4} {k_neg:>6}  "
          f"{b.name[:30]}{marker}")
if len(inventory_candidates) > 6:
    print(f"  ... ({len(inventory_candidates)-6} more)")

req = Request(
    request_id="REQ-VERIFY-01",
    patient_id="PAT-0001",
    needed_by_date=next_need,
    component=Component.PRBC,
    units=1,
)
result = choose_lever(req, ds, today)
lever_val = result.get("lever")
print(f"\nchoose_lever => lever={lever_val}")
if lever_val and lever_val.value == "inventory":
    bank_id = result.get("bank_id")
    print(f"  bank_id={bank_id}, dist={result.get('distance_km')} km, "
          f"expiry_days={result.get('days_to_expiry')}")
    ok = bank_id == "BB-0036"
    print(f"  BB-0036: {'[PASS]' if ok else '[FAIL: ' + str(bank_id) + ']'}")
else:
    print(f"  [FAIL: expected inventory lever, got {lever_val}]")

# Confirm BB-0036 demo unit details
bb36 = next((b for b in ds.blood_banks if b.bank_id == "BB-0036"), None)
if bb36:
    demo_units = [
        u for u in bb36.units
        if u.component == Component.PRBC and u.storage_status == "ok"
        and u.expiry_date >= today
        and u.abo == ABOGroup.B and u.rh_d
        and u.phenotype_tags and not u.phenotype_tags.K
    ]
    print(f"\n  BB-0036 demo unit preserved: {len(demo_units)} B+ K-neg PRBC unit(s)")
    if demo_units:
        u0 = demo_units[0]
        exp_days = (u0.expiry_date - today).days
        print(f"    abo={u0.abo.value}  rh_d={u0.rh_d}  K={u0.phenotype_tags.K}  "
              f"expiry_days={exp_days}  ['[PASS]' if exp_days == 3 else '[FAIL exp='+str(exp_days)+']']")
        status = "[PASS]" if exp_days == 3 else f"[FAIL exp={exp_days}]"
        print(f"    expiry_days==3: {status}")

# Donor fallback
print("\n  --- Forcing donor fallback (clearing compatible inventory) ---")
saved_units = {}
cleared = 0
for bank in ds.blood_banks:
    if not bank.coord_valid:
        continue
    if haversine_km(guntur_loc, bank.location) > 100.0:
        continue
    compat = [u for u in bank.units if abo_rh_compatible(pat, u) and phenotype_antibody_safe(pat, u)]
    if compat:
        saved_units[bank.bank_id] = bank.units[:]
        bank.units = [u for u in bank.units if u not in compat]
        cleared += 1
print(f"  Cleared from {cleared} bank(s)")
r2 = choose_lever(req, ds, today)
l2 = r2.get("lever")
print(f"  choose_lever => lever={l2}")
if l2 and l2.value == "donor":
    d_id = r2.get("donor_id")
    bd   = r2["breakdown"]
    print(f"    donor_id={d_id}  score={r2.get('donor_score')}  "
          f"dist={bd['proximity_km']} km  bonded={bd['bonded']}")
    ok_d = d_id == "DON-0002"
    print(f"    DON-0002: {'[PASS]' if ok_d else '[FAIL: ' + str(d_id) + ']'}")
else:
    print(f"    [FAIL: unexpected lever {l2}]")
for bank in ds.blood_banks:
    if bank.bank_id in saved_units:
        bank.units = saved_units[bank.bank_id]

# ──────────────────────────────────────────────────────────────────────────────
# (d) Hyderabad redistribution
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(d) HYDERABAD REDISTRIBUTION")
print("=" * 72)

hyd_banks_check = [
    ("BB-2253", 0.0), ("BB-2257", 0.8), ("BB-2260", 1.9)
]
print(f"\nB+ PRBC in-date units per bank (expected: 21 + 11 + 3 = 35 new + existing):")
total_b_new = 0
for bid, expected_dist in hyd_banks_check:
    bank = next((b for b in ds.blood_banks if b.bank_id == bid), None)
    if bank is None:
        print(f"  {bid}: NOT FOUND [FAIL]")
        continue
    dist = haversine_km(hyd_loc, bank.location)
    b_units = [
        u for u in bank.units
        if u.component == Component.PRBC and u.abo == ABOGroup.B
        and u.rh_d and u.storage_status == "ok" and u.expiry_date >= today
    ]
    untyped = sum(1 for u in b_units if u.phenotype_tags is None)
    typed   = sum(1 for u in b_units if u.phenotype_tags is not None)
    safe    = sum(1 for u in b_units
                  if u.phenotype_tags
                  and not u.phenotype_tags.E and not u.phenotype_tags.c)
    ec_pos  = sum(1 for u in b_units
                  if u.phenotype_tags
                  and u.phenotype_tags.E and u.phenotype_tags.c)
    print(f"  {bid} ({dist:.1f}km): total={len(b_units)}  "
          f"untyped={untyped}  typed={typed}  "
          f"E+c+={ec_pos}  safe(E-c-)={safe}  {bank.name[:35]}")

# Phenotype totals across all 3 banks
all_b_units = []
for bid, _ in hyd_banks_check:
    bank = next((b for b in ds.blood_banks if b.bank_id == bid), None)
    if bank:
        all_b_units.extend([
            u for u in bank.units
            if u.component == Component.PRBC and u.abo == ABOGroup.B
            and u.rh_d and u.storage_status == "ok" and u.expiry_date >= today
            and (u.expiry_date - today).days == 14  # only newly added units
        ])
total_new = len(all_b_units)
total_untyped = sum(1 for u in all_b_units if u.phenotype_tags is None)
total_eckneg  = sum(1 for u in all_b_units
                    if u.phenotype_tags and u.phenotype_tags.E
                    and u.phenotype_tags.c and not u.phenotype_tags.K)
total_eckpos  = sum(1 for u in all_b_units
                    if u.phenotype_tags and u.phenotype_tags.E
                    and u.phenotype_tags.c and u.phenotype_tags.K)
total_safe    = sum(1 for u in all_b_units
                    if u.phenotype_tags
                    and not u.phenotype_tags.E and not u.phenotype_tags.c)
print(f"\n  New B+ units total (expiry=today+14): {total_new}")
print(f"    untyped: {total_untyped}  E+c+ K-neg: {total_eckneg}  "
      f"E+c+ K+: {total_eckpos}  safe(E-c-): {total_safe}")
ok_mix = (total_untyped == 28 and total_eckneg == 3
          and total_eckpos == 2 and total_safe == 2)
print(f"  Phenotype mix unchanged (28/3/2/2): {'[PASS]' if ok_mix else '[FAIL]'}")

# ──────────────────────────────────────────────────────────────────────────────
# (e) Full 9-cell table + partition check
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(e) FULL 9-CELL TABLE")
print("=" * 72)
cells = compute_desert_cells(ds, today)
print(f"\n{len(cells)} cells, sorted by desert_score desc\n")

hdr = (f"{'cell_id':<18} {'pts':>4} {'D':>4} {'S_raw':>6} {'S_safe':>6} "
       f"{'met':>4} {'cg':>4} {'sg':>4} {'score':>5}  {'type':<22} "
       f"{'safe_km':>8} {'donors':>7}")
print(hdr)
print("-" * len(hdr))
for c in cells:
    sk = f"{c['nearest_safe_inventory_km']:.1f}" if c['nearest_safe_inventory_km'] is not None else "None"
    print(f"{c['cell_id']:<18} {c['patients_due']:>4} {c['demand_units']:>4} "
          f"{c['raw_units']:>6} {c['safe_units']:>6} "
          f"{c['met']:>4} {c['compatibility_gap']:>4} {c['supply_gap']:>4} "
          f"{c['desert_score']:>5}  {c['desert_type']:<22} "
          f"{sk:>8} {c['eligible_matched_donors_nearby']:>7}")

print("\n[PARTITION CHECK] met + compatibility_gap + supply_gap == demand_units")
all_ok = True
for c in cells:
    s = c["met"] + c["compatibility_gap"] + c["supply_gap"]
    if s != c["demand_units"]:
        all_ok = False
        print(f"  [FAIL] {c['cell_id']}: {s} != {c['demand_units']}")
print(f"  All {len(cells)} cells: {'[PASS]' if all_ok else '[FAIL - see above]'}")

# Specific cell checks
gnt = next((c for c in cells if c["cell_id"] == "CLN-GNT-01"), None)
hyd = next((c for c in cells if c["cell_id"] == "CLN-HYD-01"), None)
lkn = next((c for c in cells if c["cell_id"] == "CLN-LKN-01"), None)

print(f"\n  CLN-GNT-01 score not tuned (honest result): "
      f"score={gnt['desert_score']}  type={gnt['desert_type']}")
print(f"  CLN-HYD-01 COMPATIBILITY_LIMITED: "
      f"{'[PASS]' if hyd and hyd['desert_type']=='COMPATIBILITY_LIMITED' else '[FAIL]'}")
print(f"  CLN-LKN-01 SUPPLY_LIMITED: "
      f"{'[PASS]' if lkn and lkn['desert_type']=='SUPPLY_LIMITED' else '[FAIL]'}")

# ──────────────────────────────────────────────────────────────────────────────
# (f) DON-0002 identity + determinism
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(f) DON-0002 IDENTITY + DETERMINISM")
print("=" * 72)

don2 = next((d for d in ds.donors if d.donor_id == "DON-0002"), None)
if don2:
    ok_abo  = don2.abo_group == ABOGroup.B and don2.rh_d
    ok_k    = don2.phenotype is not None and not don2.phenotype.K
    ok_bond = "PAT-0001" in don2.linked_patients
    print(f"\n  DON-0002: {don2.abo_group.value}{'+'if don2.rh_d else'-'}  "
          f"K={don2.phenotype.K if don2.phenotype else 'N/A'}  "
          f"linked={don2.linked_patients}")
    print(f"    B+: {'[PASS]' if ok_abo else '[FAIL]'}  "
          f"K-neg: {'[PASS]' if ok_k else '[FAIL]'}  "
          f"bonded PAT-0001: {'[PASS]' if ok_bond else '[FAIL]'}")
else:
    print("  DON-0002 NOT FOUND [FAIL]")

print("\n[DETERMINISM] Two fresh loads:")
ds2    = SyntheticSource().load()
cells2 = compute_desert_cells(ds2, today)
gnt2   = next((c for c in cells2 if c["cell_id"] == "CLN-GNT-01"), None)
hyd2   = next((c for c in cells2 if c["cell_id"] == "CLN-HYD-01"), None)
lkn2   = next((c for c in cells2 if c["cell_id"] == "CLN-LKN-01"), None)

def _match(a, b):
    return (a["desert_score"] == b["desert_score"]
            and a["raw_units"] == b["raw_units"]
            and a["safe_units"] == b["safe_units"]
            and a["desert_type"] == b["desert_type"])

gnt_ok = gnt and gnt2 and _match(gnt, gnt2)
hyd_ok = hyd and hyd2 and _match(hyd, hyd2)
lkn_ok = lkn and lkn2 and _match(lkn, lkn2)

print(f"  GNT load-1: score={gnt['desert_score']} raw={gnt['raw_units']} "
      f"safe={gnt['safe_units']} type={gnt['desert_type']}")
print(f"  GNT load-2: score={gnt2['desert_score']} raw={gnt2['raw_units']} "
      f"safe={gnt2['safe_units']} type={gnt2['desert_type']}")
print(f"  GNT identical: {'[PASS]' if gnt_ok else '[FAIL]'}")
print(f"  HYD load-1: score={hyd['desert_score']} raw={hyd['raw_units']} "
      f"safe={hyd['safe_units']} type={hyd['desert_type']}")
print(f"  HYD load-2: score={hyd2['desert_score']} raw={hyd2['raw_units']} "
      f"safe={hyd2['safe_units']} type={hyd2['desert_type']}")
print(f"  HYD identical: {'[PASS]' if hyd_ok else '[FAIL]'}")
print(f"  LKN load-1: score={lkn['desert_score']} raw={lkn['raw_units']} "
      f"safe={lkn['safe_units']} type={lkn['desert_type']}")
print(f"  LKN load-2: score={lkn2['desert_score']} raw={lkn2['raw_units']} "
      f"safe={lkn2['safe_units']} type={lkn2['desert_type']}")
print(f"  LKN identical: {'[PASS]' if lkn_ok else '[FAIL]'}")

print("\n" + "=" * 72)
print("DONE")
print("=" * 72)
