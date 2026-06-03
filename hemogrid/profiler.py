"""
hemogrid/profiler.py — Day-of dataset profiler.

Run on any tabular input (DataFrame or file path) to assess in seconds:
  1. Shape: rows, columns, dtypes, non-null coverage
  2. Coordinate quality: invalid-coord counts for lat/lon columns — same rules
     the canonical loader uses (zero, out-of-India-bounds, lat == lon)
  3. Canonical readiness: which fields of a target canonical model map directly
     to a source column (PROVIDED) vs must be computed (DERIVED) vs generated
     (SYNTHETIC) vs need a human decision (NEEDS MAPPING)

First diagnostic to run on an organiser's unknown dataset on hackathon day —
before writing any adapter code. Source-agnostic: no assumptions about specific
column names; matching is purely algorithmic (token-overlap Jaccard score).
"""
from __future__ import annotations

import inspect
import re
import types as _types
from collections import Counter
from pathlib import Path
from typing import Any, Optional, Union, get_args, get_origin

import pandas as pd
from pydantic import BaseModel

from .models import BloodBank, Clinic, Donor, Patient

# ---------------------------------------------------------------------------
# Coordinate bounds — identical to the canonical loader
# ---------------------------------------------------------------------------

_INDIA_LAT = (6.0, 37.0)
_INDIA_LON = (68.0, 98.0)

_RE_LAT = re.compile(r"\blat", re.IGNORECASE)
_RE_LON = re.compile(r"\blon|\blng", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Per-model field classification overrides
# ---------------------------------------------------------------------------

# Assigned / computed by the loader — never present in a raw source file.
_DERIVED: dict[str, set[str]] = {
    "BloodBank": {"bank_id", "coord_valid"},
    "Patient":   {"patient_id"},
    "Donor":     {"donor_id", "reliability_score", "linked_patients", "engagement_log"},
    "Clinic":    {"clinic_id"},
}

# Always generated synthetically — no source column is expected or meaningful.
_SYNTHETIC: dict[str, set[str]] = {
    "BloodBank": {"units"},
}

# Inherited from CanonicalModel base — not a data field; skip in all reports.
_META_FIELDS = frozenset({"provenance"})

# Stop-words for token matching: too short or too generic to carry signal.
_STOP = frozenset({
    "id", "is", "as", "has", "do", "does", "a", "an", "the",
    "of", "in", "at", "by", "to", "no", "or", "on", "up", "it",
    "from", "with", "and", "for", "sr", "num", "val",
})

_KNOWN_TYPES: dict[str, type[BaseModel]] = {
    "BloodBank": BloodBank,
    "Patient":   Patient,
    "Donor":     Donor,
    "Clinic":    Clinic,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trunc(s: str, n: int) -> str:
    return s[: n - 1] + "~" if len(s) > n else s


def _load_df(source: Union[pd.DataFrame, str, Path]) -> tuple[pd.DataFrame, str]:
    if isinstance(source, pd.DataFrame):
        return source, "<DataFrame>"
    path = Path(source)
    label = path.name
    if path.suffix.lower() in {".csv", ".tsv", ".txt"}:
        try:
            return pd.read_csv(path, encoding="utf-8"), label
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="cp1252"), label
    # .xls / .xlsx / unknown: try CSV-with-cp1252 first (handles misnamed CSVs
    # like the e-RaktKosh blood-banks.xls), fall back to real Excel reader.
    try:
        return pd.read_csv(path, encoding="cp1252"), label
    except Exception:
        return pd.read_excel(path), label


def _tokenize(s: str) -> frozenset[str]:
    """Normalize to meaningful tokens; strip stop-words and single-char parts."""
    parts = re.split(r"[^a-z0-9]+", s.lower())
    result: set[str] = set()
    for p in parts:
        if len(p) >= 2 and p not in _STOP:
            result.add(p)
            if p.endswith("s") and len(p) > 4:
                result.add(p[:-1])  # simple plural stem: "hours" -> "hour"
    return frozenset(result)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _best_column_match(
    field_name: str,
    col_tokens: dict[str, frozenset[str]],
    threshold: float = 0.20,
) -> Optional[tuple[str, float]]:
    ft = _tokenize(field_name)
    if not ft:
        return None
    best_col, best_sc = None, 0.0
    for col, ct in col_tokens.items():
        sc = _jaccard(ft, ct)
        if sc > best_sc:
            best_col, best_sc = col, sc
    return (best_col, best_sc) if best_sc >= threshold else None


def _unwrap_optional(annotation: Any) -> Any:
    """Unwrap Optional[X] (= Union[X, None]) to the primary type X."""
    origin = get_origin(annotation)
    if origin is Union:
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        return non_none[0] if len(non_none) == 1 else annotation
    # Python 3.10+ X | None syntax
    if hasattr(_types, "UnionType") and isinstance(annotation, _types.UnionType):
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        return non_none[0] if len(non_none) == 1 else annotation
    return annotation


def _is_pydantic_model(typ: Any) -> bool:
    return inspect.isclass(typ) and issubclass(typ, BaseModel)


def _is_list_type(annotation: Any) -> bool:
    return get_origin(annotation) is list


# ---------------------------------------------------------------------------
# Coordinate quality
# ---------------------------------------------------------------------------

def _coord_quality(
    df: pd.DataFrame,
    lat_cols: list[str],
    lon_cols: list[str],
) -> dict[str, Any]:
    """Report per-column invalid counts using the same rules as _coord_valid."""
    n = len(df)
    per_col: dict[str, Any] = {}

    for col in lat_cols + lon_cols:
        kind = "lat" if col in lat_cols else "lon"
        bounds = _INDIA_LAT if kind == "lat" else _INDIA_LON
        s = pd.to_numeric(df[col], errors="coerce")
        is_null = s.isna()
        is_zero = ~is_null & (s == 0)
        is_oob  = ~is_null & ~is_zero & ((s < bounds[0]) | (s > bounds[1]))
        fail    = is_null | is_zero | is_oob
        total   = int(fail.sum())
        per_col[col] = {
            "null":          int(is_null.sum()),
            "zero":          int(is_zero.sum()),
            "out_of_bounds": int(is_oob.sum()),
            "total_invalid": total,
            "valid_pct":     round(100.0 * (n - total) / n, 1) if n else 0.0,
        }

    lat_eq_lon: Optional[int] = None
    if len(lat_cols) == 1 and len(lon_cols) == 1:
        lat_s = pd.to_numeric(df[lat_cols[0]], errors="coerce")
        lon_s = pd.to_numeric(df[lon_cols[0]], errors="coerce")
        both_ok = ~lat_s.isna() & ~lon_s.isna() & (lat_s != 0) & (lon_s != 0)
        lat_eq_lon = int((lat_s[both_ok] == lon_s[both_ok]).sum())

    return {
        "lat_columns": lat_cols,
        "lon_columns": lon_cols,
        "per_column":  per_col,
        "lat_eq_lon":  lat_eq_lon,
    }


# ---------------------------------------------------------------------------
# Canonical readiness
# ---------------------------------------------------------------------------

def _canonical_readiness(
    df: pd.DataFrame,
    model_class: type[BaseModel],
    lat_cols: list[str],
    lon_cols: list[str],
) -> dict[str, Any]:
    model_name = model_class.__name__
    derived    = _DERIVED.get(model_name, set())
    synthetic  = _SYNTHETIC.get(model_name, set())
    col_tokens = {c: _tokenize(c) for c in df.columns}

    fields: list[dict[str, Any]] = []

    for fname, finfo in model_class.model_fields.items():
        if fname in _META_FIELDS:
            continue

        if fname in derived:
            fields.append({
                "field": fname, "status": "DERIVED",
                "source_col": None, "note": "computed by loader",
            })
            continue

        if fname in synthetic:
            fields.append({
                "field": fname, "status": "SYNTHETIC",
                "source_col": None, "note": "no source; generated",
            })
            continue

        ann      = finfo.annotation
        base_ann = _unwrap_optional(ann)
        is_list  = _is_list_type(ann)

        # Location sub-model — needs lat + lon columns, not a single "location" col
        if _is_pydantic_model(base_ann) and base_ann.__name__ == "Location":
            if lat_cols and lon_cols:
                fields.append({
                    "field":      fname,
                    "status":     "PROVIDED",
                    "source_col": f"{lat_cols[0]} + {lon_cols[0]}",
                    "note":       "via lat/lon columns",
                })
            else:
                fields.append({
                    "field":      fname,
                    "status":     "NEEDS MAPPING",
                    "source_col": None,
                    "note":       "no lat/lon columns detected",
                })
            continue

        # Other Pydantic sub-models (Phenotype, Consent) — try name match
        if _is_pydantic_model(base_ann):
            m = _best_column_match(fname, col_tokens)
            if m:
                fields.append({"field": fname, "status": "PROVIDED",
                               "source_col": m[0], "score": round(m[1], 2)})
            else:
                fields.append({"field": fname, "status": "NEEDS MAPPING",
                               "source_col": None})
            continue

        # List fields not already in the synthetic set
        if is_list:
            m = _best_column_match(fname, col_tokens)
            if m:
                fields.append({"field": fname, "status": "PROVIDED",
                               "source_col": m[0], "score": round(m[1], 2),
                               "note": "list field: verify shape"})
            else:
                fields.append({"field": fname, "status": "NEEDS MAPPING",
                               "source_col": None,
                               "note": "list field: likely needs manual construction"})
            continue

        # Scalar field — try token-overlap match
        m = _best_column_match(fname, col_tokens)
        if m:
            fields.append({"field": fname, "status": "PROVIDED",
                           "source_col": m[0], "score": round(m[1], 2)})
        else:
            fields.append({"field": fname, "status": "NEEDS MAPPING",
                           "source_col": None})

    counts = Counter(f["status"] for f in fields)
    return {"model": model_name, "fields": fields, "summary": dict(counts)}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def profile_dataset(
    source: Union[pd.DataFrame, str, Path],
    target_type: Optional[Union[str, type[BaseModel]]] = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Profile a tabular dataset for HemoGrid canonical-readiness.

    Parameters
    ----------
    source      : DataFrame, file path (CSV / XLS), or path string
    target_type : canonical model to check readiness against (default: BloodBank)
                  accepts the class itself or a string ("BloodBank", "Donor", …)
    verbose     : print a human-readable report to stdout

    Returns
    -------
    dict with keys: source_label, rows, columns, coverage, coord_quality,
                    canonical_readiness
    """
    df, source_label = _load_df(source)

    if target_type is None:
        model_class: type[BaseModel] = BloodBank
    elif isinstance(target_type, str):
        model_class = _KNOWN_TYPES.get(target_type, BloodBank)
    else:
        model_class = target_type

    n = len(df)

    # Coverage
    coverage: dict[str, Any] = {}
    for col in df.columns:
        nn = int(df[col].notna().sum())
        coverage[col] = {
            "dtype":    str(df[col].dtype),
            "non_null": nn,
            "pct":      round(100.0 * nn / n, 1) if n else 0.0,
        }

    # Coordinate quality
    lat_cols = [c for c in df.columns if _RE_LAT.search(c)]
    lon_cols = [c for c in df.columns if _RE_LON.search(c)]
    coord_q  = _coord_quality(df, lat_cols, lon_cols) if (lat_cols or lon_cols) else None

    # Canonical readiness
    readiness = _canonical_readiness(df, model_class, lat_cols, lon_cols)

    result: dict[str, Any] = {
        "source_label":        source_label,
        "rows":                n,
        "columns":             list(df.columns),
        "coverage":            coverage,
        "coord_quality":       coord_q,
        "canonical_readiness": readiness,
    }

    if verbose:
        _print_report(result)

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _print_report(r: dict[str, Any]) -> None:
    W = 64
    sep = "=" * W
    print(sep)
    print(f"HEMOGRID PROFILER  --  {r['source_label']}")
    print(sep)

    print(f"\nSHAPE:  {r['rows']:,} rows  x  {len(r['columns'])} columns")

    # Coverage table
    print("\nCOLUMN COVERAGE")
    print(f"  {'Column':<36} {'dtype':<12} {'non-null %':>10}")
    print(f"  {'-'*36} {'-'*12} {'-'*10}")
    for col, info in r["coverage"].items():
        print(
            f"  {_trunc(col, 36):<36} {info['dtype']:<12} "
            f"{info['pct']:>9.1f}%"
        )

    # Coordinate quality
    cq = r["coord_quality"]
    if cq:
        lat_str = ", ".join(cq["lat_columns"]) or "none"
        lon_str = ", ".join(cq["lon_columns"]) or "none"
        print(f"\nCOORDINATE QUALITY  (lat: {lat_str}  |  lon: {lon_str})")
        print(
            f"  {'Column':<30} {'null':>5} {'zero':>5} "
            f"{'OOB':>5} {'invalid':>8} {'valid%':>7}"
        )
        print(f"  {'-'*30} {'-'*5} {'-'*5} {'-'*5} {'-'*8} {'-'*7}")
        for col, ci in cq["per_column"].items():
            print(
                f"  {_trunc(col, 30):<30} {ci['null']:>5} {ci['zero']:>5} "
                f"{ci['out_of_bounds']:>5} {ci['total_invalid']:>8} "
                f"{ci['valid_pct']:>6.1f}%"
            )
        if cq["lat_eq_lon"] is not None:
            print(f"  lat == lon (same-value pairs): {cq['lat_eq_lon']}")
    else:
        print("\nCOORDINATE QUALITY  -- no lat/lon columns detected")

    # Canonical readiness
    rd = r["canonical_readiness"]
    sm = rd["summary"]
    print(f"\nCANONICAL READINESS  (target: {rd['model']})")
    print(f"  {'Field':<28} {'Status':<15} Source column / note")
    print(f"  {'-'*28} {'-'*15} {'-'*28}")
    for f in rd["fields"]:
        src = _trunc(f.get("source_col") or "--", 30)
        extra = ""
        if "score" in f:
            extra += f"  score={f['score']:.2f}"
        if f.get("note"):
            extra += f"  [{f['note']}]"
        print(f"  {f['field']:<28} {f['status']:<15} {src}{extra}")

    provided = sm.get("PROVIDED", 0)
    derived  = sm.get("DERIVED", 0)
    synth    = sm.get("SYNTHETIC", 0)
    needs    = sm.get("NEEDS MAPPING", 0)
    print(
        f"\n  Summary: {provided} PROVIDED  |  {derived} DERIVED  "
        f"|  {synth} SYNTHETIC  |  {needs} NEEDS MAPPING"
    )
    print()
