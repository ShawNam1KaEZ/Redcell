"""
SyntheticSource — working DataSource for development and demo.

Phase 1 (current):
  · Loads real BloodBank objects from the e-RaktKosh directory.
  · Generates synthetic Clinic, Donor, Patient, and InventoryUnit objects
    seeded from real Indian population frequencies (see hemogrid/enrichment.py).
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .. import enrichment as enr
from ..models import (
    ABOGroup,
    BankCategory,
    BloodBank,
    CanonicalDataset,
    Clinic,
    Component,
    Consent,
    Donor,
    InventoryUnit,
    Location,
    Patient,
    Phenotype,
    Provenance,
    Request,
)
from .base import DataSource

_P = Provenance
_INDIA_LAT: tuple[float, float] = (6.0, 37.0)
_INDIA_LON: tuple[float, float] = (68.0, 98.0)

# ABO compatibility: donor group → set of patient groups it can supply (PRBC)
_ABO_COMPAT: dict[ABOGroup, set[ABOGroup]] = {
    ABOGroup.O:  {ABOGroup.O, ABOGroup.A, ABOGroup.B, ABOGroup.AB},
    ABOGroup.A:  {ABOGroup.A, ABOGroup.AB},
    ABOGroup.B:  {ABOGroup.B, ABOGroup.AB},
    ABOGroup.AB: {ABOGroup.AB},
}

# State → ISO 639-1 language code (best approximation for dominant language)
_STATE_LANG: dict[str, str] = {
    "Andhra Pradesh":        "te",
    "Telangana":             "te",
    "Tamil Nadu":            "ta",
    "Karnataka":             "kn",
    "Kerala":                "ml",
    "West Bengal":           "bn",
    "Odisha":                "or",
    "Maharashtra":           "mr",
    "Goa":                   "mr",
    "Gujarat":               "gu",
    "Punjab":                "pa",
    "Assam":                 "as",
    "Manipur":               "mni",
    "Mizoram":               "lus",
    "Meghalaya":             "kha",
    "Arunachal Pradesh":     "hi",
    "Nagaland":              "en",
    "Tripura":               "bn",
    "Sikkim":                "ne",
}
_DEFAULT_LANG = "hi"


# ---------------------------------------------------------------------------
# Cell-level cleaning helpers (blood-bank loader reuses these)
# ---------------------------------------------------------------------------

def _str(val) -> Optional[str]:
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def _clean_address(val) -> Optional[str]:
    s = _str(val)
    if s is None:
        return None
    return s.replace(chr(0x2018), "'").replace(chr(0x2019), "'")


def _clean_name(val) -> Optional[str]:
    s = _str(val)
    return html.unescape(s) if s else None


def _clean_pincode(val) -> Optional[str]:
    s = _str(val)
    if s is None:
        return None
    s = re.sub(r"\s+", "", s).rstrip(",")
    return s or None


def _coalesce_contact(mobile, contact_no) -> Optional[str]:
    return _str(mobile) or _str(contact_no)


def _coord_valid(lat: float, lon: float) -> bool:
    if lat == 0 or lon == 0:
        return False
    if lat == lon:
        return False
    if not (_INDIA_LAT[0] <= lat <= _INDIA_LAT[1]):
        return False
    if not (_INDIA_LON[0] <= lon <= _INDIA_LON[1]):
        return False
    return True


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def _lang_for_state(state: str) -> str:
    return _STATE_LANG.get(state, _DEFAULT_LANG)


def _donor_eligible(donor: Donor) -> bool:
    """≥ 90-day interval since last donation (NBTC rule)."""
    if donor.last_donation_date is None:
        return True
    return (date.today() - donor.last_donation_date).days >= 90


# ---------------------------------------------------------------------------
# SyntheticSource
# ---------------------------------------------------------------------------

class SyntheticSource(DataSource):
    """
    Working DataSource implementation used until OrganizerAdapter is filled in
    on hackathon day.

    `seed` controls all synthetic generation; set it for reproducible demos.
    Defaults to the `data/` directory at the project root, resolved relative
    to this file so it works regardless of the caller's CWD.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        seed: int = 42,
    ) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
        self._data_dir = Path(data_dir)
        self._seed = seed

    @property
    def source_name(self) -> str:
        return "SyntheticSource"

    def load(self) -> CanonicalDataset:
        rng = np.random.default_rng(self._seed)

        banks   = self._load_blood_banks()
        scorer  = self._build_reliability_scorer()
        clinics = self._generate_clinics()
        donors  = self._generate_donors(rng, banks, scorer)
        patients = self._generate_patients(rng, clinics)
        self._make_bonds(rng, donors, patients)
        self._generate_inventory(rng, banks)

        # Post-seeded deterministic additions — NO rng calls below this line.
        # The seed=42 RNG sequence is frozen; all golden objects are unaffected.

        # SUPPLY_LIMITED stressed cohort (Lucknow, PAT-0201..0204)
        stressed = self._generate_stressed_patients(clinics)
        patients.extend(stressed)

        # COMPATIBILITY_LIMITED stressed cohort (Hyderabad, PAT-0301..0307).
        # Also adds B+ inventory to BB-2253 in-place — full shelves, but
        # almost none of it passes the antibody-safe gate for these patients.
        compat_stressed = self._generate_compatibility_stress(clinics, banks)
        patients.extend(compat_stressed)

        return CanonicalDataset(
            blood_banks=banks,
            donors=donors,
            patients=patients,
            clinics=clinics,
            requests=[],   # Requests are created by the engine at runtime
        )

    # ------------------------------------------------------------------
    # 1. Real blood-bank loader (e-RaktKosh directory)
    # ------------------------------------------------------------------

    def _load_blood_banks(self) -> list[BloodBank]:
        path = self._data_dir / "blood-banks.xls"
        df   = pd.read_csv(path, encoding="cp1252", low_memory=False)

        df.columns = [c.strip() for c in df.columns]
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].apply(
                lambda x: x.strip() if isinstance(x, str) else x
            )

        repeated_mask = df["Blood Bank Name"].str.contains(
            r"\(Repeated\)|\(REPEATED\)", regex=True, na=False
        )
        n_dropped = int(repeated_mask.sum())
        df = df[~repeated_mask].reset_index(drop=True)

        banks: list[BloodBank] = []
        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            lat = float(row["Latitude"])
            lon = float(row["Longitude"])

            raw_cat = _str(row.get("Category"))
            try:
                category: Optional[BankCategory] = (
                    BankCategory(raw_cat) if raw_cat else None
                )
            except ValueError:
                category = None

            does_components = (
                (_str(row.get("Blood Component Available")) or "").upper() == "YES"
            )

            banks.append(
                BloodBank(
                    bank_id=f"BB-{idx:04d}",
                    source_serial=int(row["Sr No"]),
                    name=_clean_name(row["Blood Bank Name"]) or "",
                    location=Location(lat=lat, lng=lon),
                    coord_valid=_coord_valid(lat, lon),
                    address=_clean_address(row.get("Address")),
                    state=_str(row["State"]) or "",
                    district=_str(row.get("District")),
                    pincode=_clean_pincode(row.get("Pincode")),
                    contact=_coalesce_contact(
                        row.get("Mobile"), row.get("Contact No")
                    ),
                    category=category,
                    does_components=does_components,
                    service_hours=_str(row.get("Service Time")),
                    units=[],
                    provenance={
                        "bank_id":         _P.DERIVED,
                        "source_serial":   _P.PROVIDED,
                        "name":            _P.PROVIDED,
                        "location":        _P.PROVIDED,
                        "coord_valid":     _P.DERIVED,
                        "address":         _P.PROVIDED,
                        "state":           _P.PROVIDED,
                        "district":        _P.PROVIDED,
                        "pincode":         _P.PROVIDED,
                        "contact":         _P.PROVIDED,
                        "category":        _P.PROVIDED,
                        "does_components": _P.PROVIDED,
                        "service_hours":   _P.PROVIDED,
                        "units":           _P.SYNTHETIC,
                    },
                )
            )

        print(
            f"[SyntheticSource] blood banks: {len(banks)} loaded "
            f"({n_dropped} (Repeated) dropped)"
        )
        return banks

    # ------------------------------------------------------------------
    # 2. Reliability scorer (trained once from UCI data)
    # ------------------------------------------------------------------

    def _build_reliability_scorer(self):
        """
        Fit a logistic regression on UCI RFM features → Donated_Blood label.
        Returns a deterministic scorer: (recency_months, frequency, time_months)
        → float[0, 1].

        One-sentence explainer: donors with lower recency (donated recently),
        higher frequency, and longer history score higher, via a logistic
        regression on three min-max-normalised RFM features.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.preprocessing import MinMaxScaler

        df = pd.read_csv(self._data_dir / "uci_blood_transfusion.csv")

        # Invert Recency so the monotone direction is positive for all features.
        df["inv_Recency"] = df["Recency"].max() - df["Recency"]
        feats = ["inv_Recency", "Frequency", "Time"]

        X = df[feats].values.astype(float)
        y = df["Donated_Blood"].values

        scaler = MinMaxScaler()
        X_sc   = scaler.fit_transform(X)

        clf = LogisticRegression(random_state=42, max_iter=1000)
        clf.fit(X_sc, y)

        proba    = clf.predict_proba(X_sc)[:, 1]
        auc      = float(roc_auc_score(y, proba))
        mean_pos = float(proba[y == 1].mean())
        mean_neg = float(proba[y == 0].mean())
        recency_max = float(df["Recency"].max())

        print(
            f"[SyntheticSource] reliability scorer  "
            f"AUC={auc:.3f}  "
            f"mean(donors)={mean_pos:.3f}  "
            f"mean(non-donors)={mean_neg:.3f}"
        )

        def scorer(recency: float, frequency: float, time: float) -> float:
            inv_r = recency_max - recency
            x     = scaler.transform([[inv_r, frequency, time]])
            return float(clf.predict_proba(x)[0, 1])

        return scorer

    # ------------------------------------------------------------------
    # 3. Synthetic clinics
    # ------------------------------------------------------------------

    def _generate_clinics(self) -> list[Clinic]:
        """Nine thalassemia centres spread across India; Guntur is the demo clinic."""
        rows = [
            ("CLN-GNT-01", "Guntur Thalassaemia Centre",      Location(lat=16.3019,  lng=80.4378),  "Andhra Pradesh"),
            ("CLN-HYD-01", "Hyderabad Thalassaemia Centre",   Location(lat=17.3850,  lng=78.4867),  "Telangana"),
            ("CLN-CHN-01", "Chennai Thalassaemia Centre",      Location(lat=13.0827,  lng=80.2707),  "Tamil Nadu"),
            ("CLN-BLR-01", "Bengaluru Thalassaemia Centre",    Location(lat=12.9716,  lng=77.5946),  "Karnataka"),
            ("CLN-MUM-01", "Mumbai Thalassaemia Centre",       Location(lat=19.0760,  lng=72.8777),  "Maharashtra"),
            ("CLN-AHM-01", "Ahmedabad Thalassaemia Centre",    Location(lat=23.0225,  lng=72.5714),  "Gujarat"),
            ("CLN-DEL-01", "Delhi Thalassaemia Centre",        Location(lat=28.6139,  lng=77.2090),  "Delhi"),
            ("CLN-KOL-01", "Kolkata Thalassaemia Centre",      Location(lat=22.5726,  lng=88.3639),  "West Bengal"),
            ("CLN-LKN-01", "Lucknow Thalassaemia Centre",      Location(lat=26.8467,  lng=80.9462),  "Uttar Pradesh"),
        ]
        clinics = []
        for cid, name, loc, region in rows:
            clinics.append(
                Clinic(
                    clinic_id=cid,
                    location=loc,
                    name=name,
                    region=region,
                    provenance={k: _P.SYNTHETIC for k in
                                ["clinic_id", "location", "name", "region"]},
                )
            )
        print(f"[SyntheticSource] clinics: {len(clinics)} generated")
        return clinics

    # ------------------------------------------------------------------
    # 4. Synthetic donor roster
    # ------------------------------------------------------------------

    def _generate_donors(
        self,
        rng: np.random.Generator,
        banks: list[BloodBank],
        scorer,
    ) -> list[Donor]:
        today      = date.today()
        uci_df     = pd.read_csv(self._data_dir / "uci_blood_transfusion.csv")
        n_uci      = len(uci_df)
        valid_banks = [b for b in banks if b.coord_valid]

        # Build sampling weights: Guntur banks get 6× weight to ensure a
        # healthy local cluster for the demo.
        weights = np.ones(len(valid_banks))
        for i, b in enumerate(valid_banks):
            if (b.district or "").upper() == "GUNTUR":
                weights[i] = 6.0
        weights /= weights.sum()

        n_donors = 900
        donors: list[Donor] = []

        for i in range(n_donors):
            abo, rh_d = enr.random_abo_rh(rng)
            phenotype = enr.random_phenotype(rng)

            # Geography: jitter around a weighted-sampled bank (~8 km std)
            bank_idx = int(rng.choice(len(valid_banks), p=weights))
            anchor   = valid_banks[bank_idx]
            lat      = float(anchor.location.lat + rng.normal(0, 0.07))
            lng      = float(anchor.location.lng + rng.normal(0, 0.07))
            language = _lang_for_state(anchor.state)

            # RFM profile sampled from UCI distribution + small noise
            row        = uci_df.iloc[int(rng.integers(0, n_uci))]
            recency_mo = max(0, int(row["Recency"])   + int(rng.integers(-2, 3)))
            frequency  = max(1, int(row["Frequency"]) + int(rng.integers(-1, 2)))
            time_mo    = max(2, int(row["Time"])      + int(rng.integers(-3, 4)))

            reliability     = scorer(recency_mo, frequency, time_mo)
            last_donation   = today - timedelta(days=int(recency_mo * 30.44))
            contactable     = bool(rng.random() < 0.85)
            channels: list[str] = []
            if contactable:
                channels.append("SMS")
                if rng.random() < 0.70:
                    channels.append("WhatsApp")

            donors.append(
                Donor(
                    donor_id=f"DON-{i + 1:04d}",
                    abo_group=abo,
                    rh_d=rh_d,
                    phenotype=phenotype,
                    location=Location(lat=lat, lng=lng),
                    last_donation_date=last_donation,
                    donation_count=frequency,
                    reliability_score=reliability,
                    preferred_language=language,
                    consent=Consent(contactable=contactable, channels=channels),
                    linked_patients=[],
                    engagement_log=[],
                    provenance={
                        "donor_id":         _P.SYNTHETIC,
                        "abo_group":        _P.SYNTHETIC,
                        "rh_d":             _P.SYNTHETIC,
                        "phenotype":        _P.SYNTHETIC,
                        "location":         _P.SYNTHETIC,
                        "last_donation_date": _P.SYNTHETIC,
                        "donation_count":   _P.SYNTHETIC,
                        "reliability_score": _P.DERIVED,
                        "preferred_language": _P.SYNTHETIC,
                        "consent":          _P.SYNTHETIC,
                        "linked_patients":  _P.DERIVED,
                        "engagement_log":   _P.DERIVED,
                    },
                )
            )

        print(f"[SyntheticSource] donors: {len(donors)} generated")
        return donors

    # ------------------------------------------------------------------
    # 5. Synthetic patient cohort
    # ------------------------------------------------------------------

    def _generate_patients(
        self,
        rng: np.random.Generator,
        clinics: list[Clinic],
    ) -> list[Patient]:
        today       = date.today()
        allo_rate   = 0.20   # ~20 % of thalassaemia patients are alloimmunised
        n_patients  = 200

        # Clinic weights: Guntur gets extra patients for demo density
        clinic_weights = np.array(
            [4.0 if c.clinic_id == "CLN-GNT-01" else 1.0 for c in clinics]
        )
        clinic_weights /= clinic_weights.sum()

        patients: list[Patient] = []

        # ── Demo patient (golden scenario) ──────────────────────────────
        # Aarav: B+, phenotype K-negative, alloimmunised (anti-K),
        # due in 5 days at the Guntur clinic.
        guntur_clinic = next(c for c in clinics if c.clinic_id == "CLN-GNT-01")
        patients.append(
            Patient(
                patient_id="PAT-0001",
                abo_group=ABOGroup.B,
                rh_d=True,
                phenotype=Phenotype(C=True, c=False, E=False, e=True, K=False),
                known_antibodies=["anti-K"],
                transfusion_interval_days=21,
                last_transfusion_date=today - timedelta(days=16),
                units_per_session=1,
                clinic_id=guntur_clinic.clinic_id,
                preferred_language="te",
                provenance={k: _P.SYNTHETIC for k in [
                    "patient_id", "abo_group", "rh_d", "phenotype",
                    "known_antibodies", "transfusion_interval_days",
                    "last_transfusion_date", "units_per_session",
                    "clinic_id", "preferred_language",
                ]},
            )
        )

        # ── Remaining patients ──────────────────────────────────────────
        for i in range(1, n_patients):
            abo, rh_d = enr.random_abo_rh(rng)
            phenotype  = enr.random_phenotype(rng)

            antibodies = (
                enr.generate_antibodies(phenotype, rng)
                if rng.random() < allo_rate
                else []
            )

            interval = int(rng.integers(21, 29))
            # last_transfusion_date uniform in [today-interval, today]
            # → ~25-33 % of patients are due within 7 days
            days_since         = int(rng.integers(0, interval + 1))
            last_transfusion   = today - timedelta(days=days_since)

            clinic_idx = int(rng.choice(len(clinics), p=clinic_weights))
            clinic     = clinics[clinic_idx]
            language   = _lang_for_state(clinic.region)

            patients.append(
                Patient(
                    patient_id=f"PAT-{i + 1:04d}",
                    abo_group=abo,
                    rh_d=rh_d,
                    phenotype=phenotype,
                    known_antibodies=antibodies,
                    transfusion_interval_days=interval,
                    last_transfusion_date=last_transfusion,
                    units_per_session=1 if rng.random() < 0.60 else 2,
                    clinic_id=clinic.clinic_id,
                    preferred_language=language,
                    provenance={k: _P.SYNTHETIC for k in [
                        "patient_id", "abo_group", "rh_d", "phenotype",
                        "known_antibodies", "transfusion_interval_days",
                        "last_transfusion_date", "units_per_session",
                        "clinic_id", "preferred_language",
                    ]},
                )
            )

        print(f"[SyntheticSource] patients: {len(patients)} generated")
        return patients

    # ------------------------------------------------------------------
    # 6. Bonds (Blood Bridge made computable)
    # ------------------------------------------------------------------

    def _make_bonds(
        self,
        rng: np.random.Generator,
        donors: list[Donor],
        patients: list[Patient],
    ) -> None:
        today        = date.today()
        demo_patient = patients[0]   # PAT-0001

        # ── Demo bond ───────────────────────────────────────────────────
        # Guarantee a B+, K-negative, currently-eligible donor bonded to
        # the demo patient.
        eligible_for_demo = [
            d for d in donors
            if d.abo_group == ABOGroup.B
            and d.rh_d
            and d.phenotype is not None
            and not d.phenotype.K
            and _donor_eligible(d)
        ]

        if eligible_for_demo:
            raw_donor = eligible_for_demo[0]
            # Pin the demo bond donor inside the Guntur cluster so the bond
            # path demo is clinically plausible (local donor, not 800+ km away).
            demo_donor = raw_donor.model_copy(
                update={"location": Location(lat=16.32, lng=80.45)}
            )
            idx = next(i for i, d in enumerate(donors) if d.donor_id == raw_donor.donor_id)
            donors[idx] = demo_donor
        else:
            # Failsafe (should not fire at seed=42 with 900 donors)
            demo_donor = donors[0].model_copy(update={
                "abo_group":          ABOGroup.B,
                "rh_d":               True,
                "phenotype":          Phenotype(C=True, c=True, E=False, e=True, K=False),
                "last_donation_date": today - timedelta(days=120),
                "location":           Location(lat=16.32, lng=80.45),
                "linked_patients":    [],
            })
            donors[0] = demo_donor

        demo_donor.linked_patients.append(demo_patient.patient_id)

        # ── Random bonds for ~25 % of remaining donors ──────────────────
        bond_rate = 0.25
        for donor in donors[1:]:
            if rng.random() > bond_rate:
                continue
            compatible = [
                p for p in patients[1:]
                if p.abo_group in _ABO_COMPAT.get(donor.abo_group, set())
            ]
            if not compatible:
                continue
            n_bonds = 1 if rng.random() < 0.80 else 2
            idxs    = rng.choice(
                len(compatible), size=min(n_bonds, len(compatible)), replace=False
            )
            for idx in idxs:
                donor.linked_patients.append(compatible[int(idx)].patient_id)

        bonded_donors = sum(1 for d in donors if d.linked_patients)
        print(f"[SyntheticSource] bonds: {bonded_donors} donors bonded to patients")

    # ------------------------------------------------------------------
    # 7. Synthetic inventory units
    # ------------------------------------------------------------------

    def _generate_inventory(
        self,
        rng: np.random.Generator,
        banks: list[BloodBank],
    ) -> None:
        today = date.today()

        # ── Demo unit ───────────────────────────────────────────────────
        # A B+, K-negative PRBC unit expiring in 4 days at the first
        # valid-coord, does_components Guntur bank (the demo trigger).
        guntur_demo_banks = [
            b for b in banks
            if b.coord_valid
            and (b.district or "").upper() == "GUNTUR"
            and b.does_components
        ]
        if guntur_demo_banks:
            demo_bank = guntur_demo_banks[0]
            demo_bank.units.append(
                InventoryUnit(
                    component=Component.PRBC,
                    abo=ABOGroup.B,
                    rh_d=True,
                    phenotype_tags=Phenotype(C=True, c=True, E=False, e=True, K=False),
                    collection_date=today - timedelta(days=39),
                    expiry_date=today + timedelta(days=3),
                    storage_status="ok",
                    provenance={k: _P.SYNTHETIC for k in [
                        "component", "abo", "rh_d", "phenotype_tags",
                        "collection_date", "expiry_date", "storage_status",
                    ]},
                )
            )

        # ── Regular inventory across all valid-coord, does_components banks ─
        # Use 1 in 3 banks to keep the dataset fast to generate and verify.
        component_banks = [b for b in banks if b.coord_valid and b.does_components]
        perm            = rng.permutation(len(component_banks))
        selected        = [component_banks[i] for i in perm[: len(component_banks) // 3]]

        for bank in selected:
            n_units = int(rng.integers(2, 6))
            for _ in range(n_units):
                roll = rng.random()
                if roll < 0.70:
                    component = Component.PRBC
                    shelf_days = int(rng.integers(35, 43))
                elif roll < 0.90:
                    component = Component.PLATELETS
                    shelf_days = int(rng.integers(4, 6))
                else:
                    component = Component.PLASMA
                    shelf_days = int(rng.integers(270, 366))

                days_since_collection = int(rng.integers(1, shelf_days))
                collection_date = today - timedelta(days=days_since_collection)
                expiry_date     = collection_date + timedelta(days=shelf_days)

                abo, rh_d     = enr.random_abo_rh(rng)
                phenotype_tags = (
                    enr.random_phenotype(rng) if rng.random() < 0.60 else None
                )

                bank.units.append(
                    InventoryUnit(
                        component=component,
                        abo=abo,
                        rh_d=rh_d,
                        phenotype_tags=phenotype_tags,
                        collection_date=collection_date,
                        expiry_date=expiry_date,
                        storage_status="ok",
                        provenance={k: _P.SYNTHETIC for k in [
                            "component", "abo", "rh_d", "phenotype_tags",
                            "collection_date", "expiry_date", "storage_status",
                        ]},
                    )
                )

        total_units = sum(len(b.units) for b in banks)
        print(f"[SyntheticSource] inventory: {total_units} units across "
              f"{sum(1 for b in banks if b.units)} banks")

    # ------------------------------------------------------------------
    # 8. Principled stressed cohort (post-RNG, deterministic)
    # ------------------------------------------------------------------

    def _generate_stressed_patients(self, clinics: list[Clinic]) -> list[Patient]:
        """
        Four explicitly-constructed alloimmunized patients at CLN-LKN-01 (Lucknow).

        CLINICAL STORY — why Lucknow is a genuine immunological desert:
          · Raw PRBC inventory near Lucknow exists (the city has multiple hospitals).
          · BUT 60 % of synthetic units lack phenotype_tags → fail the safety gate
            the moment a patient has ANY known antibody (phenotype_antibody_safe
            returns False when src_ph is None and patient has antibodies).
          · Of the 40 % with phenotype tags, only P(K-neg)×P(E-neg)×P(c-neg)
            ≈ 0.97 × 0.82 × 0.45 ≈ 36 % of units are triple-compatible.
          · Combined hit-rate per random PRBC unit: 0.40 × 0.36 ≈ 14 %.
          · PAT-0204 (B−) adds Rh-negative restriction: only ~6 % of the Indian
            population is Rh-negative, so compatible Rh-neg B/O units are rare.

        NOT created by deleting supply.  The scarcity is purely from demand that
        outstrips the *immunologically safe* fraction of the existing supply.

        Added post-RNG-sequence: no rng parameter, no rng calls.  The seed=42
        RNG state (bonds, inventory, DON-0002 identity) is entirely preserved.
        PAT-IDs 0201–0204 are above the n_patients=200 loop ceiling, no collision.
        """
        today = date.today()
        lucknow_clinic = next((c for c in clinics if c.clinic_id == "CLN-LKN-01"), None)
        if lucknow_clinic is None:
            return []

        base_prov = {k: _P.SYNTHETIC for k in [
            "patient_id", "abo_group", "rh_d", "phenotype",
            "known_antibodies", "transfusion_interval_days",
            "last_transfusion_date", "units_per_session",
            "clinic_id", "preferred_language",
        ]}

        return [
            # Triple alloimmunized: anti-K + anti-E + anti-c.
            # Compatible unit needs K=False, E=False, c=False AND typed phenotype.
            # Expected hit-rate per random unit: ~14 %.
            Patient(
                patient_id="PAT-0201",
                abo_group=ABOGroup.B, rh_d=True,
                phenotype=Phenotype(C=True, c=False, E=False, e=True, K=False),
                known_antibodies=["anti-K", "anti-E", "anti-c"],
                transfusion_interval_days=21,
                last_transfusion_date=today - timedelta(days=18),
                units_per_session=2,
                clinic_id="CLN-LKN-01",
                preferred_language="hi",
                provenance=base_prov,
            ),
            # O+ with anti-E + anti-c: confined to O-type supply only (~37 % of
            # random inventory), further narrowed by E-neg + c-neg requirement.
            Patient(
                patient_id="PAT-0202",
                abo_group=ABOGroup.O, rh_d=True,
                phenotype=Phenotype(C=True, c=False, E=False, e=True, K=False),
                known_antibodies=["anti-E", "anti-c"],
                transfusion_interval_days=21,
                last_transfusion_date=today - timedelta(days=17),
                units_per_session=2,
                clinic_id="CLN-LKN-01",
                preferred_language="hi",
                provenance=base_prov,
            ),
            # A+ with anti-K + anti-c.
            Patient(
                patient_id="PAT-0203",
                abo_group=ABOGroup.A, rh_d=True,
                phenotype=Phenotype(C=True, c=False, E=False, e=True, K=False),
                known_antibodies=["anti-K", "anti-c"],
                transfusion_interval_days=21,
                last_transfusion_date=today - timedelta(days=19),
                units_per_session=2,
                clinic_id="CLN-LKN-01",
                preferred_language="hi",
                provenance=base_prov,
            ),
            # B− with anti-K + anti-E: Rh-neg restricts supply to Rh-neg units only
            # (B− is ~1.9 % of the Indian population → very few eligible donors or
            # inventory units), PLUS K-neg AND E-neg constraints stack on top.
            Patient(
                patient_id="PAT-0204",
                abo_group=ABOGroup.B, rh_d=False,
                phenotype=Phenotype(C=False, c=True, E=False, e=True, K=False),
                known_antibodies=["anti-K", "anti-E"],
                transfusion_interval_days=21,
                last_transfusion_date=today - timedelta(days=18),
                units_per_session=2,
                clinic_id="CLN-LKN-01",
                preferred_language="hi",
                provenance=base_prov,
            ),
        ]

    # ------------------------------------------------------------------
    # 9. Principled COMPATIBILITY_LIMITED cohort + Guntur composed shelf
    #    (both post-RNG, deterministic, no rng calls)
    # ------------------------------------------------------------------

    def _generate_compatibility_stress(
        self,
        clinics: list[Clinic],
        banks: list[BloodBank],
    ) -> list[Patient]:
        """
        Two deterministic inventory additions and one patient cohort.

        ── 1. CLN-HYD-01 (Hyderabad) — COMPATIBILITY_LIMITED desert ──────────

        All 5 existing due patients at CLN-HYD-01 are A+ or O+ type; ABO rules
        mean they CANNOT receive B-type PRBC units.  Adding 12 alloimmunized B+
        patients and 35 B+ units creates:

          S_raw >> D   — full shelf (35 new B+ units + ~18 existing for other pts)
          S_safe << D  — only 2 of 35 pass the antibody gate (33 fail because:
                          28 have no extended phenotype → fail-safe reject,
                           5 carry E+ and/or c+ antigens the patients react to)

        Why the rescue effect is eliminated: no existing patient is B-compatible,
        so the 33 "bad" B+ units are tested ONLY against the alloimmunized stressed
        patients — every one of whom has anti-E and anti-c.  Zero non-alloimmunized
        rescue.

        35 B+ units spread across 3 nearby banks for realism (one bank holding 35
        units for a single disease state is implausible):
          BB-2253 (0.0km): 21 units — thalassemia specialist bank
          BB-2257 (0.8km): 11 units — Aditya Hospital Blood Bank
          BB-2260 (1.9km):  3 units — Thalassemia and Sickle Cell Society
        Phenotype mix unchanged: 28 untyped, 3 E+c+ K-neg, 2 E+c+ K+, 2 safe.

        12 stressed B+ patients (PAT-0301..0312), all with anti-E + anti-c.
        D_stressed = 24 units; D_total = 6 (existing) + 24 = 30 units.

        ── 2. CLN-GNT-01 (Guntur) — composed realistic shelf ─────────────────

        Demand profile of 27 due Guntur patients (D=39, 5.57 units/day):
          O+: 18u  B+: 11u  A+: 6u  AB+: 2u  B-: 1u  O-: 1u

        5-day buffer (5.57 × 5 = 27.9 → 28 units) chosen as a conservative
        mid-range stocking norm (4–6 day rule of thumb for RBC).  ABO/Rh
        composition mirrors demand proportions.  ~39% typed (11/28), 61%
        untyped (17/28) — consistent with Indian bank practice.  K-neg typed
        units (10 of 11 typed) serve the 5 anti-K alloimmunized patients; 1 K-pos
        typed represents the 3% Indian K+ prevalence.

        Distributed across two nearby component-capable banks:
          BB-0037 (0.5km): 20 units — Indian Red Cross Society (main district)
          BB-0041 (1.2km):  8 units — M/s. Needs Blood Bank (secondary)

        Expiry today+14 on all new Guntur units (> BB-0036's today+3) so the
        ascending-expiry sort in choose_lever still picks BB-0036's B+ K-neg demo
        unit first for PAT-0001.  BB-0036 and its demo unit are untouched.

        No RNG calls anywhere.  Seed=42 sequence and all golden objects intact.
        """
        today = date.today()

        unit_prov = {k: _P.SYNTHETIC for k in [
            "component", "abo", "rh_d", "phenotype_tags",
            "collection_date", "expiry_date", "storage_status",
        ]}
        base_prov = {k: _P.SYNTHETIC for k in [
            "patient_id", "abo_group", "rh_d", "phenotype",
            "known_antibodies", "transfusion_interval_days",
            "last_transfusion_date", "units_per_session",
            "clinic_id", "preferred_language",
        ]}

        collection = today - timedelta(days=7)
        expiry     = today + timedelta(days=14)

        def _unit(abo, rh_d, ph=None):
            return InventoryUnit(
                component=Component.PRBC, abo=abo, rh_d=rh_d,
                phenotype_tags=ph,
                collection_date=collection, expiry_date=expiry,
                storage_status="ok", provenance=unit_prov,
            )

        # Phenotype shorthand
        _ph_safe  = Phenotype(C=True, c=False, E=False, e=True, K=False)  # safe for HYD stressed
        _ph_ec_k0 = Phenotype(C=True, c=True, E=True, e=False, K=False)   # E+c+ K-neg (fails anti-E,c)
        _ph_ec_k1 = Phenotype(C=True, c=True, E=True, e=False, K=True)    # E+c+ K+ (fails all three)
        _ph_k0    = Phenotype(C=True, c=True, E=False, e=True, K=False)   # K-neg for GNT anti-K pts
        _ph_k1    = Phenotype(C=True, c=True, E=False, e=True, K=True)    # K-pos (3% Indian prevalence)

        # ── Hyderabad: 35 B+ PRBC units across 3 banks ─────────────────────
        # Phenotype totals: 28 untyped, 3 E+c+ K-neg, 2 E+c+ K+, 2 safe
        hyd_plan: list[tuple[str, list[tuple[Optional[Phenotype], int]]]] = [
            ("BB-2253", [(None, 17), (_ph_ec_k0, 2), (_ph_ec_k1, 1), (_ph_safe, 1)]),  # 21
            ("BB-2257", [(None,  8), (_ph_ec_k0, 1), (_ph_ec_k1, 1), (_ph_safe, 1)]),  # 11
            ("BB-2260", [(None,  3)]),                                                   #  3
        ]
        for bank_id, spec in hyd_plan:
            bank = next((b for b in banks if b.bank_id == bank_id), None)
            if bank is None:
                return []
            for ph, count in spec:
                for _ in range(count):
                    bank.units.append(_unit(ABOGroup.B, True, ph))

        # ── Guntur: 28 PRBC units, demand-proportional composed shelf ───────
        # ABO/Rh: O+(13), B+(8), A+(4), O-(1), B-(1), AB+(1)
        # Typed (11): 4 O+ K-neg, 1 O+ K-pos, 1 O- K-neg, 3 B+ K-neg, 2 A+ K-neg
        # Untyped (17): O+(8), B+(5), A+(2), B-(1), AB+(1)
        gnt_plan: list[tuple[str, list[tuple[ABOGroup, bool, Optional[Phenotype], int]]]] = [
            ("BB-0037", [
                (ABOGroup.O,  True,  None,   5),   # O+ untyped ×5
                (ABOGroup.O,  True,  _ph_k0, 3),   # O+ K-neg   ×3
                (ABOGroup.O,  True,  _ph_k1, 1),   # O+ K-pos   ×1  (3% freq)
                (ABOGroup.O,  False, _ph_k0, 1),   # O- K-neg   ×1
                (ABOGroup.B,  True,  None,   3),   # B+ untyped ×3
                (ABOGroup.B,  True,  _ph_k0, 2),   # B+ K-neg   ×2
                (ABOGroup.A,  True,  None,   1),   # A+ untyped ×1
                (ABOGroup.A,  True,  _ph_k0, 2),   # A+ K-neg   ×2
                (ABOGroup.B,  False, None,   1),   # B- untyped ×1
                (ABOGroup.AB, True,  None,   1),   # AB+ untyped×1
            ]),  # 5+3+1+1+3+2+1+2+1+1 = 20
            ("BB-0041", [
                (ABOGroup.O, True,  None,   3),    # O+ untyped ×3
                (ABOGroup.O, True,  _ph_k0, 1),    # O+ K-neg   ×1
                (ABOGroup.B, True,  None,   2),    # B+ untyped ×2
                (ABOGroup.B, True,  _ph_k0, 1),    # B+ K-neg   ×1
                (ABOGroup.A, True,  None,   1),    # A+ untyped ×1
            ]),  # 3+1+2+1+1 = 8
        ]
        for bank_id, spec in gnt_plan:
            bank = next((b for b in banks if b.bank_id == bank_id), None)
            if bank is None:
                return []
            for abo, rh_d, ph, count in spec:
                for _ in range(count):
                    bank.units.append(_unit(abo, rh_d, ph))

        # ── Hyderabad: 12 stressed B+ patients, all anti-E + anti-c ────────
        def _pat(pid, last_days, extra_ab=None):
            ab = ["anti-E", "anti-c"] + (extra_ab or [])
            return Patient(
                patient_id=pid,
                abo_group=ABOGroup.B, rh_d=True,
                phenotype=Phenotype(C=True, c=False, E=False, e=True, K=False),
                known_antibodies=ab,
                transfusion_interval_days=21,
                last_transfusion_date=today - timedelta(days=last_days),
                units_per_session=2,
                clinic_id="CLN-HYD-01",
                preferred_language="te", provenance=base_prov,
            )

        return [
            _pat("PAT-0301", 18),
            _pat("PAT-0302", 17),
            _pat("PAT-0303", 19),
            _pat("PAT-0304", 20),
            _pat("PAT-0305", 18),
            _pat("PAT-0306", 16),
            _pat("PAT-0307", 17),
            _pat("PAT-0308", 19),
            _pat("PAT-0309", 18, ["anti-K"]),  # triple: anti-E + anti-c + anti-K
            _pat("PAT-0310", 17, ["anti-K"]),  # triple
            _pat("PAT-0311", 20),
            _pat("PAT-0312", 16),
        ]
