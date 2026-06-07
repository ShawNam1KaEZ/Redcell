"""
Geospatial routing: Haversine distances and ETA estimates between blood banks
and clinical facilities. No external network dependencies.
"""

from __future__ import annotations

import math
import argparse
import sys
from pathlib import Path

import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR      = "./data/build"
LONG_HAUL_KM  = 50       # km flag threshold
AVG_SPEED_KMH = 25       # urban transit speed (Hyderabad)
_EARTH_R      = 6371.0   # km

# ── Core math ─────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS-84 coordinate pairs."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def get_route_metrics(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> dict:
    """
    Returns {"distance_km": float, "eta_minutes": int, "is_long_haul": bool}.
    Uses real coordinates only — never pass display_latitude/display_longitude.
    """
    distance_km = haversine(origin_lat, origin_lng, dest_lat, dest_lng)
    eta_minutes = int((distance_km / AVG_SPEED_KMH) * 60)
    return {
        "distance_km": round(distance_km, 4),
        "eta_minutes": eta_minutes,
        "is_long_haul": distance_km > LONG_HAUL_KM,
    }

# ── Location index ────────────────────────────────────────────────────────────

def _load_location_index(data_dir: str = DATA_DIR) -> dict[str, tuple[float, float, str]]:
    """
    Returns {location_id: (lat, lon, name)} for banks and facilities.
    Skips bank rows where lat == 0.0 and lon == 0.0 (missing geocode).
    """
    d = Path(data_dir)
    banks = pd.read_csv(d / "banks.csv", dtype=str)
    facs  = pd.read_csv(d / "facilities.csv", dtype=str)

    idx: dict[str, tuple[float, float, str]] = {}

    for _, r in banks.iterrows():
        lat, lon = float(r["latitude"]), float(r["longitude"])
        if lat == 0.0 and lon == 0.0:
            continue
        idx[r["bank_id"]] = (lat, lon, r["name"])

    for _, r in facs.iterrows():
        lat, lon = float(r["latitude"]), float(r["longitude"])
        idx[r["facility_id"]] = (lat, lon, r["name"])

    return idx


def route_by_id(origin_id: str, dest_id: str, data_dir: str = DATA_DIR) -> dict:
    """Compute route metrics between two location IDs (BNK#### or FAC####)."""
    idx = _load_location_index(data_dir)

    if origin_id not in idx:
        raise ValueError(
            f"Unknown or coordinate-less location ID: {origin_id!r}. "
            "Check that it exists in banks.csv / facilities.csv with non-zero coords."
        )
    if dest_id not in idx:
        raise ValueError(
            f"Unknown or coordinate-less location ID: {dest_id!r}. "
            "Check that it exists in banks.csv / facilities.csv with non-zero coords."
        )

    olat, olon, oname = idx[origin_id]
    dlat, dlon, dname = idx[dest_id]
    metrics = get_route_metrics(olat, olon, dlat, dlon)
    return {
        "origin_id":   origin_id,
        "origin_name": oname,
        "dest_id":     dest_id,
        "dest_name":   dname,
        **metrics,
    }

# ── Asserts ───────────────────────────────────────────────────────────────────

def run_asserts(data_dir: str = DATA_DIR) -> list[tuple[str, bool, str]]:
    """
    Run loud asserts against the routing implementation.
    Raises AssertionError on first failure (printed before raising).
    Returns list of (label, passed, detail) for all passing checks.
    """
    results: list[tuple[str, bool, str]] = []

    # A1: identical coordinates must yield exactly 0.0 km
    d_zero = haversine(17.0, 78.0, 17.0, 78.0)
    if d_zero != 0.0:
        msg = f"A1 FAIL: identical coords returned {d_zero} km (expected 0.0)"
        print(msg)
        raise AssertionError(msg)
    results.append(("A1  Identical coords -> exactly 0.0 km", True, f"got {d_zero} km"))

    # A2: Charminar (17.3616°N, 78.4747°E) → Secunderabad Junction (17.4399°N, 78.4983°E)
    # Spherical haversine with R=6371 yields 9.079 km; assert within 1%.
    CHARMINAR    = (17.3616, 78.4747)
    SECUNDERABAD = (17.4399, 78.4983)
    REF_KM       = 9.079
    d_cs = haversine(*CHARMINAR, *SECUNDERABAD)
    margin = abs(d_cs - REF_KM) / REF_KM
    if margin >= 0.01:
        msg = (f"A2 FAIL: Charminar->Secunderabad = {d_cs:.4f} km, "
               f"margin {margin:.2%} exceeds 1% limit (ref {REF_KM} km)")
        print(msg)
        raise AssertionError(msg)
    results.append((
        "A2  Charminar->Secunderabad within 1% of 9.079 km", True,
        f"got {d_cs:.4f} km, margin {margin:.4%}"
    ))

    # A3: no negative or null transit values across sampled real coordinate pairs
    idx = _load_location_index(data_dir)
    ids = list(idx.keys())
    checked = 0
    for oid in ids[:10]:
        for did in ids[10:20]:
            if oid == did:
                continue
            olat, olon, _ = idx[oid]
            dlat, dlon, _ = idx[did]
            m = get_route_metrics(olat, olon, dlat, dlon)
            if m["distance_km"] < 0 or m["eta_minutes"] < 0:
                msg = f"A3 FAIL: negative value for {oid}->{did}: {m}"
                print(msg)
                raise AssertionError(msg)
            if m["distance_km"] is None or m["eta_minutes"] is None:
                msg = f"A3 FAIL: null value for {oid}->{did}: {m}"
                print(msg)
                raise AssertionError(msg)
            checked += 1
    results.append(("A3  No negative/null ETAs in sampled pairs", True,
                    f"{checked} pairs checked, all valid"))

    # A4: is_long_haul is strictly True iff distance_km > 50
    # 0 km → False
    m_zero = get_route_metrics(17.0, 78.0, 17.0, 78.0)
    assert not m_zero["is_long_haul"], "A4a FAIL: 0 km marked is_long_haul"
    # ~11 km (0.1° lat) → False
    m_short = get_route_metrics(17.0, 78.0, 17.1, 78.0)
    assert not m_short["is_long_haul"], \
        f"A4b FAIL: {m_short['distance_km']:.2f} km marked is_long_haul"
    # ~48.9 km (0.44°) → False  (boundary: strictly less than 50)
    m_under = get_route_metrics(17.0, 78.0, 17.44, 78.0)
    assert not m_under["is_long_haul"], \
        f"A4c FAIL: {m_under['distance_km']:.2f} km marked is_long_haul"
    # ~50.04 km (0.45°) → True  (strictly greater than 50)
    m_long = get_route_metrics(17.0, 78.0, 17.45, 78.0)
    assert m_long["is_long_haul"], \
        f"A4d FAIL: {m_long['distance_km']:.2f} km NOT marked is_long_haul"
    results.append(("A4  is_long_haul strictly True iff > 50 km", True,
                    f"short={m_short['distance_km']:.2f} km (F), "
                    f"under={m_under['distance_km']:.2f} km (F), "
                    f"long={m_long['distance_km']:.2f} km (T)"))

    return results

# ── Summary grid ──────────────────────────────────────────────────────────────

def print_summary_grid(data_dir: str = DATA_DIR) -> None:
    d = Path(data_dir)
    banks = pd.read_csv(d / "banks.csv", dtype=str)
    facs  = pd.read_csv(d / "facilities.csv", dtype=str)

    banks["latitude"]  = banks["latitude"].astype(float)
    banks["longitude"] = banks["longitude"].astype(float)
    facs["latitude"]   = facs["latitude"].astype(float)
    facs["longitude"]  = facs["longitude"].astype(float)

    valid_banks = banks[(banks["latitude"] != 0.0) | (banks["longitude"] != 0.0)].copy()

    rows = []
    for _, frow in facs.iterrows():
        dists = [
            haversine(frow["latitude"], frow["longitude"],
                      brow["latitude"], brow["longitude"])
            for _, brow in valid_banks.iterrows()
        ]
        avg = sum(dists) / len(dists) if dists else 0.0
        rows.append({
            "facility_id":   frow["facility_id"],
            "name":          frow["name"][:28],
            "avg_km":        avg,
            "min_km":        min(dists) if dists else 0.0,
            "max_km":        max(dists) if dists else 0.0,
            "eta_avg_min":   int((avg / AVG_SPEED_KMH) * 60),
        })

    rows.sort(key=lambda r: r["avg_km"])
    overall = sum(r["avg_km"] for r in rows) / len(rows) if rows else 0.0

    W = 80
    print("\n" + "=" * W)
    print("DISTANCE SUMMARY -- All Facilities x Blood Banks (valid coords)")
    print(f"  Banks (valid coords): {len(valid_banks)} / {len(banks)}   "
          f"Facilities: {len(facs)}")
    print("=" * W)
    print(f"  {'Facility':<10}  {'Name':<28}  {'Avg km':>8}  "
          f"{'Min km':>8}  {'Max km':>8}  {'ETA avg':>8}")
    print("  " + "-" * (W - 2))
    for r in rows:
        print(f"  {r['facility_id']:<10}  {r['name']:<28}  "
              f"{r['avg_km']:>8.1f}  {r['min_km']:>8.1f}  "
              f"{r['max_km']:>8.1f}  {r['eta_avg_min']:>7}m")
    print("  " + "-" * (W - 2))
    print(f"  {'OVERALL AVERAGE':<40}  {overall:>8.1f}")
    print("=" * W)

# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_route(metrics: dict) -> None:
    lh = "YES  <-- LONG HAUL ALERT" if metrics["is_long_haul"] else "no"
    print()
    print("  Route Metrics")
    print("  " + "-" * 50)
    print(f"  From     : {metrics.get('origin_id', '?')}  "
          f"{metrics.get('origin_name', '')}")
    print(f"  To       : {metrics.get('dest_id', '?')}  "
          f"{metrics.get('dest_name', '')}")
    print(f"  Distance : {metrics['distance_km']:.2f} km")
    print(f"  ETA      : {metrics['eta_minutes']} min  "
          f"({metrics['eta_minutes'] / 60:.1f} h)")
    print(f"  LongHaul : {lh}")
    print("  " + "-" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m engine.routing",
        description="HemoGrid geospatial routing CLI",
    )
    parser.add_argument("--from", dest="origin", metavar="ID",
                        help="Origin location ID (BNK#### or FAC####)")
    parser.add_argument("--to",   dest="dest",   metavar="ID",
                        help="Destination location ID (BNK#### or FAC####)")
    parser.add_argument("--data-dir", default=DATA_DIR,
                        help=f"Path to data/build directory (default: {DATA_DIR})")
    args = parser.parse_args()

    if args.origin and args.dest:
        try:
            metrics = route_by_id(args.origin, args.dest, args.data_dir)
            _print_route(metrics)
        except ValueError as exc:
            print(f"\n  ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.origin or args.dest:
        parser.error("Provide both --from and --to, or neither.")

    print("\nRunning routing asserts...")
    try:
        results = run_asserts(args.data_dir)
        for label, passed, detail in results:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {label}  --  {detail}")
    except AssertionError as exc:
        print(f"  [FAIL] {exc}")
        print_summary_grid(args.data_dir)
        sys.exit(1)

    print_summary_grid(args.data_dir)


if __name__ == "__main__":
    main()
