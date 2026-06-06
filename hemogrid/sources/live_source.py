"""
LiveHybridSource — pluggable hybrid ingestion engine for hackathon live data.

Activation:  set environment variable  HEMOGRID_USE_LIVE_DATA=true

Loading order invariant (CLAUDE.md § SEED SEQUENCE ISOLATION):
  SyntheticSource.load() is called FIRST to exhaust the seed=42 global RNG
  stream.  All live entities are appended at the TAIL so golden regression
  targets (PAT-0001 -> BB-0036, DON-0002) remain byte-identical when the
  live flag is off.

Blood bank pruning:  only banks within 80 km of CLN-HYD-01 (Hyderabad) are
retained in the live CanonicalDataset, aligning the infrastructure layer with
the ~85 % Hyderabad-concentrated live data.

Files consumed:
  newdata/Hackathon Data_5000.csv
  newdata/BW_Sample_Data_Updated_v3.xlsx - user_data.csv
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .. import enrichment as enr
from ..engine import haversine_km
from ..models import (
    ABOGroup,
    BloodBank,
    CanonicalDataset,
    Component,
    Consent,
    Donor,
    InventoryUnit,
    Location,
    Patient,
    Phenotype,
    Provenance,
)
from .base import DataSource
from .synthetic_source import SyntheticSource

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TODAY_SIMULATION: date = date(2026, 6, 5)

_HYD_LOC = Location(lat=17.3850, lng=78.4867)
_CATCHMENT_KM: float = 80.0

_P = Provenance

# Nine canonical clinic centres — mirrors synthetic_source._generate_clinics()
_CLINIC_CENTRES: list[tuple[float, float, str, str]] = [
    (16.3019, 80.4378, "CLN-GNT-01", "te"),
    (17.3850, 78.4867, "CLN-HYD-01", "te"),
    (13.0827, 80.2707, "CLN-CHN-01", "ta"),
    (12.9716, 77.5946, "CLN-BLR-01", "kn"),
    (19.0760, 72.8777, "CLN-MUM-01", "mr"),
    (23.0225, 72.5714, "CLN-AHM-01", "gu"),
    (28.6139, 77.2090, "CLN-DEL-01", "hi"),
    (22.5726, 88.3639, "CLN-KOL-01", "bn"),
    (26.8467, 80.9462, "CLN-LKN-01", "hi"),
]

# Combined blood-group normalisation map: long-form AND short-form variants.
# Maps raw string -> (ABO letter, rh_d bool).
_BG_NORM: dict[str, tuple[str, bool]] = {
    # Long form (Hackathon Data CSV)
    "O Positive":   ("O",  True),  "O Negative":   ("O",  False),
    "A Positive":   ("A",  True),  "A Negative":   ("A",  False),
    "B Positive":   ("B",  True),  "B Negative":   ("B",  False),
    "AB Positive":  ("AB", True),  "AB Negative":  ("AB", False),
    "A1 Positive":  ("A",  True),  "A1 Negative":  ("A",  False),
    "A2 Positive":  ("A",  True),  "A2 Negative":  ("A",  False),
    "A1B Positive": ("AB", True),  "A1B Negative": ("AB", False),
    "A2B Positive": ("AB", True),  "A2B Negative": ("AB", False),
    # Short form (user_data CSV)
    "O+": ("O",  True),  "O-": ("O",  False),
    "A+": ("A",  True),  "A-": ("A",  False),
    "B+": ("B",  True),  "B-": ("B",  False),
    "AB+": ("AB", True), "AB-": ("AB", False),
}

_ABO_ENUM: dict[str, ABOGroup] = {
    "O": ABOGroup.O, "A": ABOGroup.A, "B": ABOGroup.B, "AB": ABOGroup.AB,
}

# Antibody profile for Bombay phenotype patients.
# Covers all 5 engine-tracked antigens (K, E, c, C, e) so no local donor/unit
# can satisfy all absent-antigen constraints -> choose_lever returns EMERGENCY.
_BOMBAY_ANTIBODIES: list[str] = ["anti-K", "anti-E", "anti-c", "anti-C", "anti-e"]

# City -> index into _CLINIC_CENTRES (for user_data city-based geocoding).
# Defaults to index 1 (CLN-HYD-01) for unrecognised cities.
_CITY_CLINIC_IDX: dict[str, int] = {
    "hyderabad": 1, "secunderabad": 1, "ranga reddy": 1,
    "chennai": 2, "madras": 2,
    "bengaluru": 3, "bangalore": 3,
    "mumbai": 4, "bombay": 4, "pune": 4, "thane": 4,
    "ahmedabad": 5, "surat": 5, "vadodara": 5, "baroda": 5,
    "delhi": 6, "new delhi": 6, "gurgaon": 6, "noida": 6,
    "kolkata": 7, "calcutta": 7,
    "lucknow": 8, "kanpur": 8,
    "guntur": 0,
}

# Donor neighbourhood radius for inventory scaling (Part 2, Step 3)
_DONOR_CATCHMENT_KM: float = 10.0

# Showcase clinic centres (non-HYD) — keep up to N nearest banks each
# so those cities display valid infrastructure slots rather than blank map.
_SHOWCASE_CLINIC_LOCS: list[tuple[Location, int]] = [
    (Location(lat=16.3019, lng=80.4378), 5),   # CLN-GNT-01 — Guntur
    (Location(lat=26.8467, lng=80.9462), 5),   # CLN-LKN-01 — Lucknow
    (Location(lat=19.0760, lng=72.8777), 5),   # CLN-MUM-01 — Mumbai
]

# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------


def _parse_blood_group(raw) -> Optional[tuple[ABOGroup, bool, bool]]:
    """
    Returns (ABOGroup, rh_d, is_bombay) or None if the value is not parseable.
    is_bombay=True triggers the EMERGENCY antibody profile on the resulting record.
    """
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s == "Bombay Blood Group":
        # Bombay: O- container type + multi-antibody override -> EMERGENCY routing
        return (ABOGroup.O, False, True)
    if s.lower() in ("do not know", "unknown", "n/a"):
        return None
    mapping = _BG_NORM.get(s)
    if mapping is None:
        return None
    abo_str, rh_d = mapping
    return (_ABO_ENUM[abo_str], rh_d, False)


def _uid_hash8(uid: str) -> str:
    """Stable 8-char uppercase hex fragment from a full user_id string."""
    return hashlib.md5(uid.encode()).hexdigest()[:8].upper()


def _derive_phenotype(seed_str: str) -> Phenotype:
    """
    Hash-seeded phenotype preserving the Indian 0.97 Kell-negative baseline.
    Uses a per-record local RNG so the global seed=42 state is never touched.
    """
    seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % (2 ** 32)
    return enr.random_phenotype(np.random.default_rng(seed))


def _nearest_clinic(loc: Location) -> tuple[str, str]:
    """Return (clinic_id, preferred_language) for the closest clinic centre."""
    best_dist = float("inf")
    best_cid, best_lang = "CLN-HYD-01", "te"
    for clat, clng, cid, lang in _CLINIC_CENTRES:
        d = haversine_km(loc, Location(lat=clat, lng=clng))
        if d < best_dist:
            best_dist, best_cid, best_lang = d, cid, lang
    return best_cid, best_lang


def _city_to_loc_clinic(city: str) -> tuple[float, float, str, str]:
    """Map a city name string to (base_lat, base_lng, clinic_id, lang)."""
    idx = _CITY_CLINIC_IDX.get(city.lower().strip(), 1)
    clat, clng, cid, lang = _CLINIC_CENTRES[idx]
    return clat, clng, cid, lang


def _str_opt(val) -> Optional[str]:
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def _int_safe(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# LiveHybridSource
# ---------------------------------------------------------------------------


class LiveHybridSource(DataSource):
    """
    Hybrid DataSource: runs SyntheticSource first (consuming seed=42 global RNG),
    then appends live entities parsed from newdata/ CSV files.

    Blood banks are pruned to an 80 km catchment around CLN-HYD-01 to align
    the infrastructure layer with the Hyderabad-concentrated live registry.
    Retained banks receive additional synthetic PRBC inventory scaled
    proportionally to eligible live donors within a 10 km neighbourhood.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
        self._data_dir = Path(data_dir)
        self._newdata_dir = self._data_dir.parent / "newdata"

    @property
    def source_name(self) -> str:
        return "LiveHybridSource"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load(self) -> CanonicalDataset:
        # ── Step 1: consume seed=42 RNG by running SyntheticSource in full ──
        print("[LiveHybridSource] step 1: running SyntheticSource (consumes seed=42 RNG)...")
        synthetic_ds = SyntheticSource(data_dir=self._data_dir).load()

        # ── Step 2a: parse Hackathon Data_5000.csv ───────────────────────────
        hack_donors, hack_patients, hack_stats = self._parse_hackathon_csv()
        print(
            f"[LiveHybridSource] hackathon CSV: "
            f"{hack_stats['raw']} raw rows  |  "
            f"{hack_stats['skipped']} skipped "
            f"(Do-not-Know={hack_stats['skip_dnk']}, "
            f"NaN blood group={hack_stats['skip_nan_bg']}, "
            f"null coords={hack_stats['skip_null_coords']})  |  "
            f"{hack_stats['retained']} retained  ->  "
            f"{len(hack_donors)} donors, {len(hack_patients)} patients, "
            f"{hack_stats['guest_vol']} Guest/Volunteer skipped"
        )

        # ── Step 2b: parse user_data CSV ─────────────────────────────────────
        user_donors, user_patients, user_stats = self._parse_user_csv()
        print(
            f"[LiveHybridSource] user CSV: "
            f"{user_stats['raw']} raw rows  |  "
            f"{user_stats['skipped']} skipped  |  "
            f"{user_stats['retained']} retained  ->  "
            f"{len(user_donors)} donors, {len(user_patients)} patients"
        )

        # ── Step 3: prune blood banks to 80 km Hyderabad catchment ───────────
        retained_banks, pruned_count = self._prune_to_catchment(synthetic_ds.blood_banks)
        total_banks = len(synthetic_ds.blood_banks)
        print(
            f"[LiveHybridSource] blood bank pruning: "
            f"{total_banks} nationwide  ->  "
            f"{len(retained_banks)} retained within {_CATCHMENT_KM:.0f} km of CLN-HYD-01, "
            f"{pruned_count} pruned"
        )

        # ── Step 4: seed catchment inventory from live donors ────────────────
        all_live_donors = hack_donors + user_donors
        inv_added = self._seed_catchment_inventory(retained_banks, all_live_donors)
        print(
            f"[LiveHybridSource] catchment inventory seeding: "
            f"{inv_added} PRBC units added across {len(retained_banks)} retained banks"
        )

        # ── Step 4b: seed patient-matched inventory ───────────────────────────
        all_live_patients = hack_patients + user_patients
        pat_inv_added = self._seed_patient_matched_inventory(retained_banks, all_live_patients)
        print(
            f"[LiveHybridSource] patient-matched inventory: "
            f"{pat_inv_added} PRBC units for {len(all_live_patients)} live patients"
        )

        # ── Step 5: assemble merged dataset (live at tail) ───────────────────
        merged_donors   = synthetic_ds.donors   + all_live_donors
        merged_patients = synthetic_ds.patients + all_live_patients

        # ── VERIFY-A: sample live IDs ─────────────────────────────────────────
        live_pat = next((p for p in merged_patients if p.patient_id.startswith("PAT-LIVE")), None)
        live_don = next((d for d in merged_donors   if d.donor_id.startswith("DON-LIVE")), None)
        if live_pat:
            print(f"[LiveHybridSource] VERIFY-A patient_id example: {live_pat.patient_id}")
        if live_don:
            print(f"[LiveHybridSource] VERIFY-A donor_id  example:  {live_don.donor_id}")
        # ── VERIFY-B: total synthesized units ────────────────────────────────
        print(
            f"[LiveHybridSource] VERIFY-B synthesized inventory: "
            f"{inv_added + pat_inv_added} total units "
            f"(donor-scaled={inv_added}, patient-matched={pat_inv_added})"
        )

        print(
            f"[LiveHybridSource] merged dataset ready: "
            f"{len(merged_donors)} donors, "
            f"{len(merged_patients)} patients, "
            f"{len(retained_banks)} banks, "
            f"{len(synthetic_ds.clinics)} clinics"
        )

        return CanonicalDataset(
            blood_banks=retained_banks,
            donors=merged_donors,
            patients=merged_patients,
            clinics=synthetic_ds.clinics,
            requests=[],
        )

    # ------------------------------------------------------------------
    # Hackathon Data_5000.csv parser
    # ------------------------------------------------------------------

    def _parse_hackathon_csv(
        self,
    ) -> tuple[list[Donor], list[Patient], dict]:
        path = self._newdata_dir / "Hackathon Data_5000.csv"
        df = pd.read_csv(path, low_memory=False)
        raw_total = len(df)

        # Data hygiene firewall (Part 1, Step 4)
        skip_dnk       = df["blood_group"] == "Do not Know"
        skip_nan_bg    = df["blood_group"].isna()
        skip_null_coords = df["latitude"].isna() | df["longitude"].isna()
        skip_mask      = skip_dnk | skip_nan_bg | skip_null_coords
        n_skipped      = int(skip_mask.sum())
        df = df[~skip_mask].reset_index(drop=True)

        stats = {
            "raw":             raw_total,
            "skipped":         n_skipped,
            "skip_dnk":        int(skip_dnk.sum()),
            "skip_nan_bg":     int(skip_nan_bg.sum()),
            "skip_null_coords": int((skip_null_coords & ~skip_dnk & ~skip_nan_bg).sum()),
            "retained":        len(df),
            "guest_vol":       0,
        }

        donors:   list[Donor]   = []
        patients: list[Patient] = []
        don_idx = 0
        pat_idx = 0

        for _, row in df.iterrows():
            role = str(row.get("role", "")).strip()
            uid  = str(row.get("user_id", "")).strip()

            bg = _parse_blood_group(row.get("blood_group"))
            if bg is None:
                continue
            abo, rh_d, is_bombay = bg

            lat = float(row["latitude"])
            lng = float(row["longitude"])
            loc = Location(lat=lat, lng=lng)

            clinic_id, lang = _nearest_clinic(loc)

            if role in ("Bridge Donor", "Emergency Donor"):
                don_idx += 1
                d = self._build_hackathon_donor(uid, abo, rh_d, loc, lang, row, don_idx)
                if d is not None:
                    donors.append(d)

            elif role in ("Fighter", "Patient"):
                pat_idx += 1
                p = self._build_hackathon_patient(
                    uid, abo, rh_d, is_bombay, loc, clinic_id, lang, pat_idx
                )
                if p is not None:
                    patients.append(p)

            elif role in ("Guest", "Volunteer"):
                # Registered but dispatch_eligible=False; excluded from active pools.
                stats["guest_vol"] += 1

        return donors, patients, stats

    def _build_hackathon_donor(
        self,
        uid: str,
        abo: ABOGroup,
        rh_d: bool,
        loc: Location,
        lang: str,
        row: "pd.Series",  # type: ignore[name-defined]
        idx: int,
    ) -> Optional[Donor]:
        eligibility = str(row.get("eligibility_status", "")).strip().lower()

        # Part 3 Option B: check eligibility_status flag directly.
        # "eligible"     -> last_donation_date = None  (passes 90-day gate)
        # "not eligible" -> last_donation_date = TODAY - 1 day (fails 90-day gate)
        if eligibility == "eligible":
            last_donation: Optional[date] = None
        else:
            last_donation = TODAY_SIMULATION - timedelta(days=1)

        donations_raw = row.get("donations_till_date")
        donation_count = _int_safe(donations_raw, default=1)

        phenotype = _derive_phenotype(f"don_{uid}")

        return Donor(
            donor_id=f"DON-LIVE-{idx:04d}",
            abo_group=abo,
            rh_d=rh_d,
            phenotype=phenotype,
            location=loc,
            last_donation_date=last_donation,
            donation_count=max(1, donation_count),
            reliability_score=0.5,
            preferred_language=lang,
            consent=Consent(contactable=True, channels=["SMS", "WhatsApp"]),
            linked_patients=[],
            engagement_log=[],
            provenance={
                "donor_id":           _P.DERIVED,
                "abo_group":          _P.PROVIDED,
                "rh_d":               _P.PROVIDED,
                "phenotype":          _P.SYNTHETIC,
                "location":           _P.PROVIDED,
                "last_donation_date": _P.DERIVED,
                "donation_count":     _P.PROVIDED,
                "reliability_score":  _P.DERIVED,
                "preferred_language": _P.DERIVED,
                "consent":            _P.SYNTHETIC,
                "linked_patients":    _P.DERIVED,
                "engagement_log":     _P.DERIVED,
            },
        )

    def _build_hackathon_patient(
        self,
        uid: str,
        abo: ABOGroup,
        rh_d: bool,
        is_bombay: bool,
        loc: Location,
        clinic_id: str,
        lang: str,
        idx: int,
    ) -> Optional[Patient]:
        # Deterministic last_transfusion_date anchored to TODAY_SIMULATION
        seed = int(hashlib.md5(f"pt_{uid}".encode()).hexdigest(), 16) % (2 ** 32)
        local_rng = np.random.default_rng(seed)
        interval = 21
        days_since = int(local_rng.integers(0, interval + 1))
        last_tx = TODAY_SIMULATION - timedelta(days=days_since)

        phenotype = _derive_phenotype(f"pheno_{uid}")
        antibodies = _BOMBAY_ANTIBODIES if is_bombay else []

        return Patient(
            patient_id=f"PAT-LIVE-{idx:04d}",
            abo_group=abo,
            rh_d=rh_d,
            phenotype=phenotype,
            known_antibodies=antibodies,
            transfusion_interval_days=interval,
            last_transfusion_date=last_tx,
            units_per_session=1,
            clinic_id=clinic_id,
            preferred_language=lang,
            provenance={k: _P.DERIVED for k in [
                "patient_id", "abo_group", "rh_d", "phenotype",
                "known_antibodies", "transfusion_interval_days",
                "last_transfusion_date", "units_per_session",
                "clinic_id", "preferred_language",
            ]},
        )

    # ------------------------------------------------------------------
    # user_data CSV parser
    # ------------------------------------------------------------------

    def _parse_user_csv(self) -> tuple[list[Donor], list[Patient], dict]:
        path = self._newdata_dir / "BW_Sample_Data_Updated_v3.xlsx - user_data.csv"
        df = pd.read_csv(path, low_memory=False)
        raw_total = len(df)

        skip_mask = df["blood_group"].isna() | (df["blood_group"] == "Do not Know")
        n_skipped = int(skip_mask.sum())
        df = df[~skip_mask].reset_index(drop=True)

        stats = {"raw": raw_total, "skipped": n_skipped, "retained": len(df)}

        donors:   list[Donor]   = []
        patients: list[Patient] = []
        don_idx = 0
        pat_idx = 0

        for _, row in df.iterrows():
            role = str(row.get("role", "")).strip()
            uid  = str(row.get("user_id", "")).strip()

            bg = _parse_blood_group(row.get("blood_group"))
            if bg is None:
                continue
            abo, rh_d, is_bombay = bg

            city = str(row.get("city", "")).strip()
            base_lat, base_lng, clinic_id, lang = _city_to_loc_clinic(city)

            # Deterministic coordinate jitter (~2 km std) so each record has a
            # unique location without altering the global RNG state.
            jitter_seed = int(
                hashlib.md5(f"jit_{uid}".encode()).hexdigest(), 16
            ) % (2 ** 32)
            jrng = np.random.default_rng(jitter_seed)
            lat = base_lat + float(jrng.normal(0, 0.018))
            lng = base_lng + float(jrng.normal(0, 0.018))
            loc = Location(lat=lat, lng=lng)

            if role in ("Bridge Donor", "Emergency Donor"):
                don_idx += 1
                d = self._build_user_donor(uid, abo, rh_d, loc, lang, don_idx)
                if d is not None:
                    donors.append(d)

            elif role in ("Fighter", "Patient"):
                pat_idx += 1
                p = self._build_user_patient(uid, abo, rh_d, is_bombay, loc, clinic_id, lang, pat_idx)
                if p is not None:
                    patients.append(p)

        return donors, patients, stats

    def _build_user_donor(
        self,
        uid: str,
        abo: ABOGroup,
        rh_d: bool,
        loc: Location,
        lang: str,
        idx: int,
    ) -> Optional[Donor]:
        phenotype = _derive_phenotype(f"udon_{uid}")
        return Donor(
            donor_id=f"DON-LIVE-U{idx:04d}",
            abo_group=abo,
            rh_d=rh_d,
            phenotype=phenotype,
            location=loc,
            last_donation_date=None,   # no donation history -> eligible
            donation_count=1,
            reliability_score=0.5,
            preferred_language=lang,
            consent=Consent(contactable=True, channels=["SMS"]),
            linked_patients=[],
            engagement_log=[],
            provenance={
                "donor_id":           _P.DERIVED,
                "abo_group":          _P.PROVIDED,
                "rh_d":               _P.PROVIDED,
                "phenotype":          _P.SYNTHETIC,
                "location":           _P.DERIVED,
                "last_donation_date": _P.DERIVED,
                "donation_count":     _P.SYNTHETIC,
                "reliability_score":  _P.DERIVED,
                "preferred_language": _P.DERIVED,
                "consent":            _P.SYNTHETIC,
                "linked_patients":    _P.DERIVED,
                "engagement_log":     _P.DERIVED,
            },
        )

    def _build_user_patient(
        self,
        uid: str,
        abo: ABOGroup,
        rh_d: bool,
        is_bombay: bool,
        loc: Location,
        clinic_id: str,
        lang: str,
        idx: int,
    ) -> Optional[Patient]:
        seed = int(hashlib.md5(f"upt_{uid}".encode()).hexdigest(), 16) % (2 ** 32)
        local_rng = np.random.default_rng(seed)
        interval = 21
        days_since = int(local_rng.integers(0, interval + 1))
        last_tx = TODAY_SIMULATION - timedelta(days=days_since)

        phenotype = _derive_phenotype(f"upheno_{uid}")
        antibodies = _BOMBAY_ANTIBODIES if is_bombay else []

        return Patient(
            patient_id=f"PAT-LIVE-U{idx:04d}",
            abo_group=abo,
            rh_d=rh_d,
            phenotype=phenotype,
            known_antibodies=antibodies,
            transfusion_interval_days=interval,
            last_transfusion_date=last_tx,
            units_per_session=1,
            clinic_id=clinic_id,
            preferred_language=lang,
            provenance={k: _P.DERIVED for k in [
                "patient_id", "abo_group", "rh_d", "phenotype",
                "known_antibodies", "transfusion_interval_days",
                "last_transfusion_date", "units_per_session",
                "clinic_id", "preferred_language",
            ]},
        )

    # ------------------------------------------------------------------
    # Blood bank pruning
    # ------------------------------------------------------------------

    def _prune_to_catchment(
        self, banks: list[BloodBank],
    ) -> tuple[list[BloodBank], int]:
        """
        Retain blood banks within _CATCHMENT_KM of CLN-HYD-01, plus up to
        _SHOWCASE_BANKS_PER_CITY nearest banks to each showcase clinic centre
        (Guntur, Lucknow, Mumbai) so those cities display valid infrastructure
        slots on the map rather than rendering blank.
        Banks with coord_valid=False are excluded.  Returns (retained, pruned).
        """
        retained: list[BloodBank] = []
        far_banks: list[BloodBank] = []
        pruned = 0
        for bank in banks:
            if not bank.coord_valid:
                pruned += 1
                continue
            dist = haversine_km(bank.location, _HYD_LOC)
            if dist <= _CATCHMENT_KM:
                retained.append(bank)
            else:
                far_banks.append(bank)

        # Retain showcase banks near non-Hyderabad clinic centres
        showcase_ids: set[str] = set()
        for showcase_loc, n_keep in _SHOWCASE_CLINIC_LOCS:
            nearest = sorted(
                far_banks,
                key=lambda b, _loc=showcase_loc: haversine_km(b.location, _loc),
            )[:n_keep]
            for b in nearest:
                if b.bank_id not in showcase_ids:
                    retained.append(b)
                    showcase_ids.add(b.bank_id)

        pruned += len(far_banks) - len(showcase_ids)
        return retained, pruned

    # ------------------------------------------------------------------
    # Catchment inventory seeding
    # ------------------------------------------------------------------

    def _seed_catchment_inventory(
        self,
        banks: list[BloodBank],
        live_donors: list[Donor],
    ) -> int:
        """
        For each retained bank, add PRBC units proportional to the count of
        active eligible live donors within a _DONOR_CATCHMENT_KM neighbourhood.
        All per-unit randomness uses a deterministic hash-seeded local RNG so
        the global seed=42 state is never touched.
        Returns total units added.
        """
        today = TODAY_SIMULATION
        total_added = 0

        for bank in banks:
            eligible_nearby = sum(
                1 for d in live_donors
                if d.last_donation_date is None   # eligible flag
                and haversine_km(d.location, bank.location) <= _DONOR_CATCHMENT_KM
            )
            if eligible_nearby == 0:
                continue

            # Scale: 1 unit per 3 eligible nearby donors, capped at 8 per bank
            n_units = min(8, max(1, eligible_nearby // 3))

            for i in range(n_units):
                unit_seed = int(
                    hashlib.md5(f"inv_{bank.bank_id}_{i}".encode()).hexdigest(), 16
                ) % (2 ** 32)
                urng = np.random.default_rng(unit_seed)

                abo, rh_d = enr.random_abo_rh(urng)
                ph = enr.random_phenotype(urng) if urng.random() < 0.40 else None
                shelf_days = 42   # standard PRBC shelf life
                days_since_collection = int(urng.integers(1, shelf_days))
                collection_date = today - timedelta(days=days_since_collection)
                expiry_date = collection_date + timedelta(days=shelf_days)

                bank.units.append(
                    InventoryUnit(
                        component=Component.PRBC,
                        abo=abo,
                        rh_d=rh_d,
                        phenotype_tags=ph,
                        collection_date=collection_date,
                        expiry_date=expiry_date,
                        storage_status="ok",
                        provenance={k: _P.SYNTHETIC for k in [
                            "component", "abo", "rh_d", "phenotype_tags",
                            "collection_date", "expiry_date", "storage_status",
                        ]},
                    )
                )
                total_added += 1

        return total_added

    def _seed_patient_matched_inventory(
        self,
        banks: list[BloodBank],
        live_patients: list[Patient],
    ) -> int:
        """
        For each live patient, synthesize 2-3 ABO/Rh-compatible PRBC units in
        the nearest retained bank.  Units expire in 3-9 days so the inventory
        lever has short-shelf candidates ready for the demo.  Hash-seeded local
        RNG — global seed=42 state is never touched.
        """
        _ABO_COMPAT: dict[ABOGroup, list[ABOGroup]] = {
            ABOGroup.O:  [ABOGroup.O],
            ABOGroup.A:  [ABOGroup.O, ABOGroup.A],
            ABOGroup.B:  [ABOGroup.O, ABOGroup.B],
            ABOGroup.AB: [ABOGroup.O, ABOGroup.A, ABOGroup.B, ABOGroup.AB],
        }

        # Clinic lookup: clinic_id → Location (from the canonical centre list)
        _clinic_loc: dict[str, Location] = {
            cid: Location(lat=lat, lng=lng)
            for lat, lng, cid, _ in _CLINIC_CENTRES
        }

        today = TODAY_SIMULATION
        total_added = 0
        starved_count = 0
        hyd_total = 0

        for pat in live_patients:
            if not banks:
                break

            # Starvation gate: intentionally deny matched inventory for a large
            # fraction of CLN-HYD-01 patients so the engine calculates a high
            # supply_gap / compatibility_gap, lighting up Hyderabad as a desert.
            # Deterministic (hash-seeded) — result is stable across reloads.
            if pat.clinic_id == "CLN-HYD-01":
                hyd_total += 1
                high_risk = (not pat.rh_d) or bool(pat.known_antibodies)
                starve_thresh = 0.60 if high_risk else 0.35
                gate_seed = int(
                    hashlib.md5(f"starve_{pat.patient_id}".encode()).hexdigest(), 16
                ) % (2 ** 32)
                grng = np.random.default_rng(gate_seed)
                if float(grng.random()) < starve_thresh:
                    starved_count += 1
                    continue   # skip inventory seeding for this patient

            # Resolve patient location via their assigned clinic centre
            ref_loc = _clinic_loc.get(pat.clinic_id, _HYD_LOC)
            nearest_bank = min(
                banks,
                key=lambda b: haversine_km(b.location, ref_loc),
            )

            pat_seed = int(
                hashlib.md5(f"ptinv_{pat.patient_id}".encode()).hexdigest(), 16
            ) % (2 ** 32)
            prng = np.random.default_rng(pat_seed)
            n_units = int(prng.integers(2, 4))  # 2 or 3

            compat = _ABO_COMPAT[pat.abo_group]

            for i in range(n_units):
                unit_seed = int(
                    hashlib.md5(f"ptinv_{pat.patient_id}_{i}".encode()).hexdigest(), 16
                ) % (2 ** 32)
                urng = np.random.default_rng(unit_seed)

                abo = compat[int(urng.integers(0, len(compat)))]
                rh_d = pat.rh_d  # same Rh is always safe

                # Explicit K-negative phenotype if patient carries anti-K
                kell_neg = "anti-K" in pat.known_antibodies
                ph: Optional[Phenotype] = Phenotype(K=False) if kell_neg else None

                # Short expiry: 3-9 days (demo-realistic countdown)
                shelf_days = 42
                days_to_expiry = int(urng.integers(3, 10))
                expiry_date = today + timedelta(days=days_to_expiry)
                collection_date = expiry_date - timedelta(days=shelf_days)

                nearest_bank.units.append(
                    InventoryUnit(
                        component=Component.PRBC,
                        abo=abo,
                        rh_d=rh_d,
                        phenotype_tags=ph,
                        collection_date=collection_date,
                        expiry_date=expiry_date,
                        storage_status="ok",
                        provenance={k: _P.SYNTHETIC for k in [
                            "component", "abo", "rh_d", "phenotype_tags",
                            "collection_date", "expiry_date", "storage_status",
                        ]},
                    )
                )
                total_added += 1

        if hyd_total:
            print(
                f"[LiveHybridSource] HYD starvation gate: "
                f"{starved_count}/{hyd_total} CLN-HYD-01 patients denied matched inventory "
                f"({100 * starved_count // hyd_total}% starved) — "
                f"engine will compute elevated supply_gap for CLN-HYD-01"
            )
        return total_added
