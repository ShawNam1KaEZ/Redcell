# build_jitter.py — Stage A: add display_latitude/display_longitude jitter columns
# Adds visual-only display coords to donors.csv and patients.csv.
# Real latitude/longitude columns are NEVER modified (matcher needs raw GPS).
# RANDOM_SEED=42 => same run always produces identical output.

import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
RANDOM_SEED       = 42
BUILD_DIR         = os.path.join(os.path.dirname(__file__), "data", "build")
RAYLEIGH_SCALE_M  = 300     # Rayleigh sigma; mode (peak) is exactly this value (metres)
MAX_RADIUS_M      = 700     # hard cap → no display point can exceed 700 m from true point
ASSERT_MIN_DISTINCT_DONORS = 4000
ASSERT_MAX_KM_DISPLACEMENT = 1.0
M_PER_DEG_LAT     = 111320  # metres per degree latitude (constant)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _jitter(lats: np.ndarray, lngs: np.ndarray, rng_seed: int):
    """Return (display_lats, display_lngs) with seeded Rayleigh radial jitter."""
    rng    = np.random.default_rng(rng_seed)
    n      = len(lats)
    radii  = rng.rayleigh(scale=RAYLEIGH_SCALE_M, size=n).clip(0, MAX_RADIUS_M)
    angles = rng.uniform(0, 2 * math.pi, size=n)
    cos_lat = np.cos(np.radians(lats))
    dlat    = radii * np.cos(angles) / M_PER_DEG_LAT
    dlng    = radii * np.sin(angles) / (M_PER_DEG_LAT * np.where(cos_lat == 0, 1e-9, cos_lat))
    return lats + dlat, lngs + dlng


def _haversine_m(lat1, lng1, lat2, lng2) -> np.ndarray:
    """Vectorized haversine distance in metres."""
    R    = 6_371_000
    phi1 = np.radians(lat1);  phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lng2 - lng1)
    a    = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))

# ── Per-entity processing ─────────────────────────────────────────────────────

def _process(entity: str, rng_seed: int, assert_min_distinct: int | None = None):
    path = os.path.join(BUILD_DIR, f"{entity}.csv")
    df   = pd.read_csv(path)

    before = df.groupby(["latitude", "longitude"]).ngroups
    print(f"{entity.upper()} — distinct (lat,lng) BEFORE: {before}")

    dlat, dlng = _jitter(df["latitude"].values.astype(float),
                         df["longitude"].values.astype(float),
                         rng_seed)
    df["display_latitude"]  = dlat
    df["display_longitude"] = dlng

    after = df.groupby(["display_latitude", "display_longitude"]).ngroups
    print(f"{entity.upper()} — distinct (display_lat,display_lng) AFTER:  {after}")

    if assert_min_distinct is not None:
        assert after > assert_min_distinct, (
            f"FAIL: only {after} distinct display points (need >{assert_min_distinct})"
        )
        print(f"  ASSERT distinct PASS: {after} > {assert_min_distinct}")

    dists_m = _haversine_m(
        df["latitude"].values.astype(float),  df["longitude"].values.astype(float),
        df["display_latitude"].values,         df["display_longitude"].values,
    )
    max_km = float(dists_m.max()) / 1000
    assert max_km <= ASSERT_MAX_KM_DISPLACEMENT, (
        f"FAIL: max displacement {max_km:.3f} km exceeds {ASSERT_MAX_KM_DISPLACEMENT} km"
    )
    print(f"  ASSERT displacement PASS: max {max_km:.3f} km (<= {ASSERT_MAX_KM_DISPLACEMENT} km)")

    df.to_csv(path, index=False)
    print(f"  Written: {path}")
    return before, after

# ── Metadata updates ──────────────────────────────────────────────────────────

def _update_field_sources(entity: str, n: int):
    path = os.path.join(BUILD_DIR, f"{entity}_field_sources.json")
    with open(path) as fh:
        data = json.load(fh)
    data["display_latitude"]  = {"real": 0, "synth": n}
    data["display_longitude"] = {"real": 0, "synth": n}
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    print(f"  Updated field sources: {path}")


def _update_data_dictionary():
    path = os.path.join(BUILD_DIR, "data_dictionary.md")
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()

    new_rows = (
        "| display_latitude  | float | synth | Jitter-offset lat for map display; real GPS preserved in `latitude` |\n"
        "| display_longitude | float | synth | Jitter-offset lng for map display; real GPS preserved in `longitude` |\n"
    )

    def _inject_after_section(content, section_header, next_header):
        if section_header not in content:
            return content
        i = content.index(section_header)
        j = content.index(next_header, i)
        block = content[i:j]
        if "display_latitude" in block:
            return content          # already present
        return content[:j] + new_rows + content[j:]

    txt = _inject_after_section(txt, "## donors.csv",   "## bags.csv")
    txt = _inject_after_section(txt, "## patients.csv", "## antibodies.csv")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(f"  Updated data_dictionary.md")


def _stamp_report(donor_before, donor_after, patient_before, patient_after):
    path = os.path.join(BUILD_DIR, "REPORT.md")
    stamp = (
        f"\n## L. Stage-A Jitter — Display Coordinates\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  RANDOM_SEED: {RANDOM_SEED}\n\n"
        f"| Entity   | Distinct (lat,lng) BEFORE | Distinct (display_lat,lng) AFTER |\n"
        f"|---|---|---|\n"
        f"| donors   | {donor_before} | {donor_after} |\n"
        f"| patients | {patient_before} | {patient_after} |\n\n"
        f"- Rayleigh sigma = {RAYLEIGH_SCALE_M} m (mode = {RAYLEIGH_SCALE_M} m), hard cap = {MAX_RADIUS_M} m\n"
        f"- Assert donors distinct > {ASSERT_MIN_DISTINCT_DONORS}: PASS\n"
        f"- Assert max displacement <= {ASSERT_MAX_KM_DISPLACEMENT} km: PASS (donors + patients)\n"
        f"- New columns added: `display_latitude`, `display_longitude` in donors.csv and patients.csv\n"
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(stamp)
    print(f"  Stamped REPORT.md")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"RANDOM_SEED={RANDOM_SEED}  Rayleigh scale={RAYLEIGH_SCALE_M}m  cap={MAX_RADIUS_M}m\n")

    # Donors: seed = RANDOM_SEED
    d_before, d_after = _process(
        "donors", rng_seed=RANDOM_SEED, assert_min_distinct=ASSERT_MIN_DISTINCT_DONORS
    )
    print()
    # Patients: seed = RANDOM_SEED + 1 (independent stream, still derived from base seed)
    p_before, p_after = _process("patients", rng_seed=RANDOM_SEED + 1)
    print()

    donors  = pd.read_csv(os.path.join(BUILD_DIR, "donors.csv"))
    patients = pd.read_csv(os.path.join(BUILD_DIR, "patients.csv"))

    _update_field_sources("donors",  len(donors))
    _update_field_sources("patients", len(patients))
    _update_data_dictionary()
    _stamp_report(d_before, d_after, p_before, p_after)

    print()
    print("=" * 60)
    print(f"Stage A complete.")
    print(f"  Donors  — distinct display points:  {d_before} -> {d_after}")
    print(f"  Patients — distinct display points: {p_before} -> {p_after}")
