# build_map.py — Stage B: emit data/build/map/map_data.json + index.html
# Inventory is always a DERIVED QUERY (architecture invariant #4) — never a stored count.
# Privacy: donor_id masked; email/phone never emitted.
# Run AFTER build_jitter.py so display_latitude/display_longitude exist on donors + patients.

import json
import math
import os
import uuid
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
RANDOM_SEED   = 42
BUILD_DIR     = os.path.join(os.path.dirname(__file__), "data", "build")
MAP_DIR       = os.path.join(BUILD_DIR, "map")
TODAY         = date.today().isoformat()
TODAY_PLUS_7  = (date.today() + timedelta(days=7)).isoformat()
DATA_URL      = "./map_data.json"
ANTIGEN_COLS  = ["C","c","E","e","K","k","Jka","Jkb","Fya","Fyb","M","N","S","s"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(name: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(BUILD_DIR, f"{name}.csv"))


def _clean(x):
    """Convert numpy / NaN scalars to JSON-safe Python types."""
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def _mask_id(pid: str) -> str:
    s = str(pid)
    # Friendly remapped IDs (DNR-/PAT-) are safe to show in full
    if s.startswith(("DNR-", "PAT-")):
        return s
    return s[:8] + "…" if len(s) > 8 else s


def _phenotype_summary(row) -> str:
    """Compact 'C+ c- E+ …' string for typed donors; 'untyped' otherwise."""
    if not row["is_typed"]:
        return "untyped"
    parts = []
    for ag in ANTIGEN_COLS:
        v = row.get(f"phenotype_{ag}", "unknown")
        if v == "pos":
            parts.append(f"{ag}+")
        elif v == "neg":
            parts.append(f"{ag}-")
    return " ".join(parts) if parts else "untyped"

# ── Inventory: DERIVED QUERY (never a stored column) ─────────────────────────

def _compute_inventory(bags: pd.DataFrame, location_id: str) -> dict:
    avail = bags[
        (bags["current_location_id"] == location_id)
        & (bags["status"] == "available")
        & (bags["expiry_date"] >= TODAY)
    ]
    abo_rhd = (avail["abo"] + avail["rhd"].map({"pos": "+", "neg": "-"}).fillna("?"))
    by_type = abo_rhd.value_counts().to_dict()
    exp_7d  = int((avail["expiry_date"] <= TODAY_PLUS_7).sum())
    return {
        "available_total":  int(len(avail)),
        "by_abo_rhd":       by_type,
        "expiring_within_7d": exp_7d,
    }

# ── Payload builders ──────────────────────────────────────────────────────────

def _build_banks(banks: pd.DataFrame, bags: pd.DataFrame) -> list:
    out = []
    for _, r in banks.iterrows():
        inv = _compute_inventory(bags, r["bank_id"])
        out.append({
            "bank_id":      r["bank_id"],
            "name":         r["name"],
            "category":     _clean(r.get("category")),
            "lat":          _clean(r["latitude"]),
            "lng":          _clean(r["longitude"]),
            "apheresis":    str(r.get("apheresis", "")).upper() == "YES",
            "service_time": _clean(r.get("service_time")),
            "inventory":    inv,
        })
    return out


def _build_facilities(
    facilities: pd.DataFrame,
    patients: pd.DataFrame,
    antibodies: pd.DataFrame,
) -> list:
    ab_lookup: dict[str, list[str]] = (
        antibodies.groupby("patient_id")["specificity"].apply(list).to_dict()
    )

    out = []
    for _, fr in facilities.iterrows():
        fid   = fr["facility_id"]
        prows = patients[patients["home_facility_id"] == fid]
        pat_list = []
        for _, pr in prows.iterrows():
            pid = pr["patient_id"]
            _specials = []
            if bool(pr.get("special_irradiated", False)):  _specials.append("irradiated")
            if bool(pr.get("special_cmv_neg",    False)):  _specials.append("cmv_neg")
            if bool(pr.get("special_washed",     False)):  _specials.append("washed")
            pat_list.append({
                "patient_id":              _mask_id(pid),
                "abo":                     pr["abo"],
                "rhd":                     pr["rhd"],
                "age_years":               _clean(pr.get("age_years")),
                "diagnosis":               _clean(pr.get("diagnosis")),
                "extended_match_policy":   _clean(pr.get("extended_match_policy")),
                "last_transfusion_date":   _clean(pr.get("last_transfusion_date")),
                "expected_transfusion_date": _clean(pr.get("expected_transfusion_date")),
                "units_per_session":       _clean(pr.get("units_per_session")),
                "required_units":          _clean(pr.get("required_units")),
                "special_requirements":    _specials,
                "antibodies":              ab_lookup.get(pid, []),
                "requires_adsorption_workup": bool(pr.get("requires_adsorption_workup", False)),
            })
        out.append({
            "facility_id":       fid,
            "name":              fr["name"],
            "type":              _clean(fr.get("type")),
            "lat":               _clean(fr["latitude"]),
            "lng":               _clean(fr["longitude"]),
            "has_own_bank":      bool(fr.get("has_own_bank", False)),
            "associated_bank_id": _clean(fr.get("associated_bank_id")),
            "patients":          pat_list,
        })
    return out


def _build_donors(donors: pd.DataFrame) -> list:
    out = []
    for _, r in donors.iterrows():
        out.append({
            "donor_id_masked":   _mask_id(r["donor_id"]),
            "display_lat":       _clean(r["display_latitude"]),
            "display_lng":       _clean(r["display_longitude"]),
            "abo":               r["abo"],
            "rhd":               r["rhd"],
            "eligibility_status": r["eligibility_status"],
            "donation_count":    int(r["donation_count"]),
            "is_typed":          bool(r["is_typed"]),
            "home_bank_id":      r["home_bank_id"],
            "last_donation_date": _clean(r.get("last_donation_date")),
            "next_eligible_date": _clean(r.get("next_eligible_date")),
            "consent_to_recall": bool(r.get("consent_to_recall", False)),
            "phenotype_summary": _phenotype_summary(r),
        })
    return out

# ── HTML template (all CSS + JS inline; PLACEHOLDER_* tokens replaced at write time) ──

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>HemoGrid &mdash; Thalassemia Blood Logistics Map</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;font-family:system-ui,-apple-system,sans-serif}
body{display:flex;flex-direction:column}
#header{background:#1e3a5f;color:#e2eaf5;display:flex;align-items:center;gap:14px;
        padding:8px 14px;flex-shrink:0;border-bottom:2px solid #2d4f7c;z-index:1000}
#header h1{font-size:.92rem;font-weight:700;color:#7dd3fc;white-space:nowrap}
#countbar{flex:1;font-size:.76rem;color:#93b4d4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#countbar span{color:#e2eaf5;font-weight:700}
#reload-btn{background:#1d4ed8;color:#eff6ff;border:none;border-radius:6px;
            padding:5px 12px;font-size:.76rem;cursor:pointer;white-space:nowrap}
#reload-btn:hover{background:#2563eb}
#reload-btn:disabled{opacity:.6;cursor:wait}
#map{flex:1}
.leaflet-popup-content{font-size:.78rem;line-height:1.45;min-width:220px}
.pu-title{font-size:.88rem;font-weight:700;color:#1e3a5f;margin-bottom:5px;
          border-bottom:1px solid #e5e7eb;padding-bottom:3px}
.pu-row{display:flex;gap:6px;margin-bottom:2px;align-items:baseline}
.pu-row span{color:#6b7280;white-space:nowrap}
.pu-row b{color:#111827;margin-left:auto;text-align:right}
.pu-hr{border:0;border-top:1px solid #e5e7eb;margin:5px 0}
.inv-tbl{border-collapse:collapse;width:100%;margin-top:4px;font-size:.72rem}
.inv-tbl th,.inv-tbl td{border:1px solid #d1d5db;padding:2px 6px;text-align:center}
.inv-tbl th{background:#eff6ff;font-weight:600}
.pat-list{max-height:250px;overflow-y:auto;margin-top:5px}
.pat-card{border-left:3px solid #3b82f6;padding:4px 6px;margin-bottom:5px;
          background:#f0f7ff;border-radius:3px}
.pat-id{font-weight:700;color:#1e3a5f;margin-bottom:2px;font-size:.8rem}
.badge{display:inline-block;border-radius:4px;padding:1px 5px;font-size:.65rem;
       font-weight:700;margin-right:2px;margin-top:2px}
.badge-ok{background:#dcfce7;color:#15803d}
.badge-no{background:#fee2e2;color:#991b1b}
.badge-ab{background:#fce7f3;color:#9d174d}
.badge-ads{background:#fef9c3;color:#854d0e}
.legend-box{background:rgba(255,255,255,.93);border:1px solid #d1d5db;border-radius:6px;
            padding:8px 12px;font-size:.72rem;line-height:1.75;
            box-shadow:0 1px 4px rgba(0,0,0,.15)}
.legend-box b{display:block;margin-bottom:2px;font-size:.77rem}
.leg-dot{display:inline-block;width:10px;height:10px;border-radius:50%;
         margin-right:4px;vertical-align:middle}
.leg-sq{display:inline-block;width:10px;height:10px;border-radius:2px;
        margin-right:4px;vertical-align:middle}
.leg-note{color:#9ca3af;font-size:.65rem;margin-top:4px;max-width:160px}
</style>
</head>
<body>
<div id="header">
  <h1>HemoGrid &mdash; Thalassemia Blood Logistics</h1>
  <div id="countbar">
    <span id="cnt-donors">PLACEHOLDER_N_DONORS</span> donors &middot;
    <span id="cnt-banks">PLACEHOLDER_N_BANKS</span> banks &middot;
    <span id="cnt-clinics">PLACEHOLDER_N_CLINICS</span> clinics &middot;
    live available units:&nbsp;<span id="cnt-units">&#8212;</span>
  </div>
  <button id="reload-btn" onclick="reloadData()">&#8635; Reset / Reload</button>
</div>
<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
'use strict';

// ── Data source: ONE swappable seam (simulation layer replaces this URL later) ──
const DATA_URL = 'PLACEHOLDER_DATA_URL';

// ── Map ───────────────────────────────────────────────────────────────────────
const map = L.map('map').setView([17.39, 78.48], 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19
}).addTo(map);

// ── Layer groups ──────────────────────────────────────────────────────────────
const donorCluster = L.markerClusterGroup({
  maxClusterRadius: 50,
  disableClusteringAtZoom: 16,
  chunkedLoading: true,
});
const bankLayer   = L.layerGroup();
const clinicLayer = L.layerGroup();
let controlAdded  = false;

// ── Icon factories ────────────────────────────────────────────────────────────
function bankIcon() {
  return L.divIcon({
    html: '<div style="width:16px;height:16px;background:#2563eb;border:2px solid #1d4ed8;border-radius:3px;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>',
    iconSize: [16,16], iconAnchor: [8,8], className: ''
  });
}
function clinicIcon() {
  return L.divIcon({
    html: '<div style="width:16px;height:16px;background:#f59e0b;border:2px solid #d97706;border-radius:3px;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>',
    iconSize: [16,16], iconAnchor: [8,8], className: ''
  });
}

// ── Popup helpers ─────────────────────────────────────────────────────────────
function rhdSym(v) { return v === 'pos' ? '+' : v === 'neg' ? '−' : v; }

function fmtInventory(inv) {
  if (!inv || inv.available_total === 0)
    return '<em style="color:#888">No units in stock</em>';
  const rows = Object.entries(inv.by_abo_rhd)
    .sort(([,a],[,b]) => b - a)
    .map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  return `
    <div class="pu-row"><span>Available:</span><b>${inv.available_total} units</b></div>
    <div class="pu-row"><span>Expiring ≤7 d:</span><b>${inv.expiring_within_7d}</b></div>
    <table class="inv-tbl"><thead><tr><th>Type</th><th>Units</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function fmtPatients(patients) {
  if (!patients || patients.length === 0)
    return '<em style="color:#888">No patients registered here</em>';
  return patients.map(p => {
    const abs = (p.antibodies || []).map(a =>
      `<span class="badge badge-ab">${a}</span>`).join('');
    const ads = p.requires_adsorption_workup
      ? '<span class="badge badge-ads">⚠ Adsorption workup</span> ' : '';
    const specials = (p.special_requirements || []).map(s =>
      `<span class="badge badge-no">${s}</span>`).join(' ');
    const abLine = abs ? `<div style="margin-top:3px">${abs}</div>` : '';
    const spLine = specials ? `<div style="margin-top:2px">${specials}</div>` : '';
    return `<div class="pat-card">
      <div class="pat-id">${p.patient_id} &mdash; ${p.abo}${rhdSym(p.rhd)}</div>
      <div class="pu-row"><span>Age:</span><b>${p.age_years != null ? p.age_years + ' yr' : '—'}</b></div>
      <div class="pu-row"><span>Diagnosis:</span><b>${p.diagnosis || '—'}</b></div>
      <div class="pu-row"><span>Last transfusion:</span><b>${p.last_transfusion_date || '—'}</b></div>
      <div class="pu-row"><span>Next transfusion:</span><b>${p.expected_transfusion_date || '—'}</b></div>
      <div class="pu-row"><span>Units/session:</span><b>${p.units_per_session ?? '—'}</b></div>
      <div class="pu-row"><span>Policy:</span><b>${p.extended_match_policy || '—'}</b></div>
      ${ads}${spLine}${abLine}
    </div>`;
  }).join('');
}

// ── Layer builder (called on initial load + every reload) ─────────────────────
function buildLayers(data) {
  donorCluster.clearLayers();
  bankLayer.clearLayers();
  clinicLayer.clearLayers();

  // Donors — clustered circles on display coords
  (data.donors || []).forEach(d => {
    if (d.display_lat == null || d.display_lng == null) return;
    const color = d.eligibility_status === 'eligible' ? '#22c55e' : '#94a3b8';
    const m = L.circleMarker([d.display_lat, d.display_lng], {
      radius: 5, fillColor: color, color: '#fff', weight: 1, fillOpacity: 0.85
    });
    const pheno = d.is_typed ? (d.phenotype_summary || 'typed') : '<em>Untyped</em>';
    const eligBadge = d.eligibility_status === 'eligible'
      ? '<span class="badge badge-ok">Eligible</span>'
      : '<span class="badge badge-no">Not eligible</span>';
    m.bindPopup(`
      <div class="pu-title">${d.donor_id_masked}</div>
      <div class="pu-row"><span>Blood type:</span><b>${d.abo}${rhdSym(d.rhd)}</b></div>
      <div class="pu-row"><span>Status:</span><b>${eligBadge}</b></div>
      <div class="pu-row"><span>Donations:</span><b>${d.donation_count}</b></div>
      <div class="pu-row"><span>Typed:</span><b>${d.is_typed ? 'Yes' : 'No'}</b></div>
      <div class="pu-row"><span>Phenotype:</span><b style="max-width:160px;word-break:break-all">${pheno}</b></div>
      <div class="pu-row"><span>Home bank:</span><b>${d.home_bank_id}</b></div>
      <div class="pu-row"><span>Last donation:</span><b>${d.last_donation_date || '—'}</b></div>
      <div class="pu-row"><span>Next eligible:</span><b>${d.next_eligible_date || '—'}</b></div>
      <div class="pu-row"><span>Consent to recall:</span><b>${d.consent_to_recall ? 'Yes' : 'No'}</b></div>
    `, { maxWidth: 290 });
    donorCluster.addLayer(m);
  });

  // Banks — square blue markers
  (data.banks || []).forEach(b => {
    if (!b.lat || !b.lng) return;          // skip 0,0 (invalid coords)
    const m = L.marker([b.lat, b.lng], { icon: bankIcon() });
    m.bindPopup(`
      <div class="pu-title">${b.name}</div>
      <div class="pu-row"><span>ID:</span><b>${b.bank_id}</b></div>
      <div class="pu-row"><span>Category:</span><b>${b.category || '—'}</b></div>
      <div class="pu-row"><span>Apheresis:</span><b>${b.apheresis ? 'Yes' : 'No'}</b></div>
      <div class="pu-row"><span>Hours:</span><b>${b.service_time || '—'}</b></div>
      <hr class="pu-hr"><b style="font-size:.8rem">Live Inventory</b>
      ${fmtInventory(b.inventory)}
    `, { maxWidth: 300 });
    bankLayer.addLayer(m);
  });

  // Clinics — square amber markers
  (data.facilities || []).forEach(f => {
    if (!f.lat || !f.lng) return;
    const m = L.marker([f.lat, f.lng], { icon: clinicIcon() });
    const ownBank = f.has_own_bank
      ? `Yes (${f.associated_bank_id || '?'})` : 'No';
    m.bindPopup(`
      <div class="pu-title">${f.name}</div>
      <div class="pu-row"><span>Type:</span><b>${f.type || '—'}</b></div>
      <div class="pu-row"><span>Own bank:</span><b>${ownBank}</b></div>
      <div class="pu-row"><span>Assoc. bank:</span><b>${f.associated_bank_id || '—'}</b></div>
      <hr class="pu-hr"><b style="font-size:.8rem">Patients (${f.patients.length})</b>
      <div class="pat-list">${fmtPatients(f.patients)}</div>
    `, { maxHeight: 360, maxWidth: 330 });
    clinicLayer.addLayer(m);
  });

  // Wire up layer control + legend (once; layers stay on map across reloads)
  if (!controlAdded) {
    donorCluster.addTo(map);
    bankLayer.addTo(map);
    clinicLayer.addTo(map);

    L.control.layers(null, {
      'Donors':       donorCluster,
      'Blood Banks':  bankLayer,
      'Thal Clinics': clinicLayer,
    }, { collapsed: false, position: 'topright' }).addTo(map);

    // Legend (custom control)
    const legend = L.control({ position: 'bottomright' });
    legend.onAdd = () => {
      const el = L.DomUtil.create('div', 'legend-box');
      el.innerHTML = `
        <b>Legend</b>
        <span class="leg-dot" style="background:#22c55e"></span> Donor — eligible<br>
        <span class="leg-dot" style="background:#94a3b8"></span> Donor — not eligible<br>
        <span class="leg-sq" style="background:#2563eb"></span> Blood bank<br>
        <span class="leg-sq" style="background:#f59e0b"></span> Thal clinic<br>
        <div class="leg-note">Donor coords jittered ≤700 m for display privacy</div>`;
      return el;
    };
    legend.addTo(map);
    controlAdded = true;
  }

  // Live-units count (derived from JSON payload, never a stored number)
  const liveUnits = (data.banks || []).reduce(
    (s, b) => s + ((b.inventory && b.inventory.available_total) || 0), 0);
  document.getElementById('cnt-units').textContent = liveUnits;
}

// ── Data fetch ────────────────────────────────────────────────────────────────
async function loadData() {
  const r = await fetch(DATA_URL + '?_=' + Date.now());
  if (!r.ok) throw new Error('HTTP ' + r.status + ' from ' + DATA_URL);
  return r.json();
}

// ── Reload button — base affordance for simulation's base→reset ───────────────
async function reloadData() {
  const btn = document.getElementById('reload-btn');
  btn.textContent = 'Loading…';
  btn.disabled = true;
  try {
    buildLayers(await loadData());
  } catch (e) {
    alert('Error loading data: ' + e.message);
    console.error(e);
  } finally {
    btn.textContent = '↻ Reset / Reload';
    btn.disabled = false;
  }
}

// ── Initial load ──────────────────────────────────────────────────────────────
(async () => {
  try {
    buildLayers(await loadData());
  } catch (e) {
    document.getElementById('countbar').innerHTML =
      '<span style="color:#f87171">Failed to load map_data.json — ' +
      e.message + '. Run: cd ./data/build/map && python -m http.server 8000</span>';
    console.error(e);
  }
})();
</script>
</body>
</html>
"""

# ── File writers ──────────────────────────────────────────────────────────────

def _write_map_data(banks_pl, fac_pl, donors_pl, run_id: str):
    os.makedirs(MAP_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "run_id":        run_id,
        "banks":         banks_pl,
        "facilities":    fac_pl,
        "donors":        donors_pl,
    }
    path = os.path.join(MAP_DIR, "map_data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))   # compact — saves ~30%
    size_kb = os.path.getsize(path) // 1024
    print(f"  Written: {path}  ({size_kb} KB)")
    return path


def _write_index_html(n_donors: int, n_banks: int, n_clinics: int):
    os.makedirs(MAP_DIR, exist_ok=True)
    html = (
        _HTML
        .replace("PLACEHOLDER_DATA_URL",  DATA_URL)
        .replace("PLACEHOLDER_N_DONORS",  str(n_donors))
        .replace("PLACEHOLDER_N_BANKS",   str(n_banks))
        .replace("PLACEHOLDER_N_CLINICS", str(n_clinics))
    )
    path = os.path.join(MAP_DIR, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  Written: {path}")
    return path

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading CSVs...")
    donors     = _load("donors")
    patients   = _load("patients")
    bags       = _load("bags")
    banks      = _load("banks")
    facilities = _load("facilities")
    antibodies = _load("antibodies")

    assert "display_latitude" in donors.columns, (
        "display_latitude missing — run build_jitter.py first"
    )

    run_id = f"map-{TODAY}-seed{RANDOM_SEED}-{uuid.uuid4().hex[:6]}"

    print("Building banks payload (live inventory query)...")
    banks_pl   = _build_banks(banks, bags)

    print("Building facilities payload...")
    fac_pl     = _build_facilities(facilities, patients, antibodies)

    print("Building donors payload...")
    donors_pl  = _build_donors(donors)

    print("Writing artifacts...")
    _write_map_data(banks_pl, fac_pl, donors_pl, run_id)
    _write_index_html(len(donors), len(banks), len(facilities))

    # ── Summary numbers ───────────────────────────────────────────────────────
    total_live  = sum(b["inventory"]["available_total"] for b in banks_pl)
    banks_w_inv = sum(1 for b in banks_pl if b["inventory"]["available_total"] > 0)
    donor_pts   = donors["display_latitude"].nunique()

    print()
    print("=" * 65)
    print("Stage B complete.")
    print(f"  Distinct donor display points (after jitter): {donor_pts}")
    print(f"  Total live available units:                   {total_live}")
    print(f"  Banks with inventory:                         {banks_w_inv} / {len(banks_pl)}")
    print()
    print("To view the map:")
    print("  cd ./data/build/map && python -m http.server 8000")
    print("  Open: http://localhost:8000")
    print("=" * 65)
