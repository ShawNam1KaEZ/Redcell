# 04 — Data

## Raw Datasets

### 1. `data/blood-banks.xls` — e-RaktKosh National Blood Bank Directory

| Attribute | Value |
|-----------|-------|
| Path | `data/blood-banks.xls` |
| File size | 904,654 bytes |
| Format | **cp1252-encoded CSV** with `.xls` extension (NOT a real Excel file) |
| Loader | `pd.read_csv(path, encoding='cp1252', low_memory=False)` |
| Raw rows | 3,383 (after header) |
| After dedup | 2,817 (6 rows containing "(Repeated)" or "(REPEATED)" in bank name are dropped) |
| Columns | 27 (see [docs/00](00-file-index.md) for full list) |
| Source | e-RaktKosh national blood bank registry (Government of India portal) |
| License | Government open data — UNVERIFIED; no license file present |
| Provenance | All fields `PROVIDED` (from source) except `bank_id` (`DERIVED`) and `coord_valid` (`DERIVED`) |

**Coordinate quality**: The loader validates each row with `_coord_valid(lat, lon)` which rejects: `lat == 0`, `lon == 0`, `lat == lon`, lat outside `(6.0, 37.0)`, lon outside `(68.0, 98.0)`. The `BloodBank.coord_valid` flag reflects this check. UNVERIFIED: exact count of invalid-coord banks from this file.

**Cleaning steps** (in `SyntheticSource._load_blood_banks()`):
1. Strip whitespace from all column names and string cell values
2. Drop rows matching `(Repeated)` or `(REPEATED)` in `Blood Bank Name`
3. Assign sequential `bank_id = f"BB-{idx:04d}"` starting from 1 (order-dependent — see fragility note in [docs/10](10-data-flow-and-known-issues.md))
4. Parse `Category` into `BankCategory` enum; set `None` on ValueError
5. Parse `Blood Component Available == "YES"` → `does_components`
6. Clean address (replace curly quotes), name (HTML unescape), pincode (strip whitespace/trailing commas)
7. Coalesce `Mobile` and `Contact No` into single `contact` field

### 2. `data/uci_blood_transfusion.csv` — UCI Blood Transfusion Service Center

| Attribute | Value |
|-----------|-------|
| Path | `data/uci_blood_transfusion.csv` |
| Format | UTF-8 CSV |
| Rows | 748 data rows |
| Columns | `Recency` (months since last donation), `Frequency` (total donations), `Monetary` (total blood donated in cc), `Time` (months since first donation), `Donated_Blood` (binary label: donated in March 2007) |
| Source | UCI Machine Learning Repository — Blood Transfusion Service Center Data Set |
| License | UNVERIFIED; likely CC BY 4.0 (UCI standard) |
| Usage | Training data for the donor reliability logistic regression in `SyntheticSource._build_reliability_scorer()`. Also used as RFM distribution for synthetic donor generation. |

**Reliability scorer**: A `LogisticRegression(random_state=42, max_iter=1000)` is fit on `[inv_Recency, Frequency, Time]` features (Monetary is excluded; inv_Recency = max_Recency - Recency to make direction positive). Features are `MinMaxScaler` normalized. Trained AUC on the same data: 0.755. The fitted scaler+classifier are captured in a closure (scorer function) and applied to each synthetic donor's RFM values. Synthetic donors' RFM values are sampled from UCI rows with small random noise.

### 3. `newdata/Hackathon Data_5000.csv` — Live Blood Bridge Registry

| Attribute | Value |
|-----------|-------|
| Path | `newdata/Hackathon Data_5000.csv` |
| Format | UTF-8 CSV |
| Rows | 7,033 data rows |
| Columns | 31 (see [docs/00](00-file-index.md)) |
| Source | Blood Bridge NGO / hackathon organizer |
| Roles | `Bridge Donor` (2061), `Emergency Donor` (2384), `Guest` (2420), `Volunteer` (83), `Patient` (84). `Guest` and `Volunteer` are skipped. |
| Blood groups | 21 distinct values including `Do not Know` (skipped), `Bombay Blood Group` (special handling), long-form like `"O Positive"`, `"A1B Negative"` |
| Key columns used | `user_id`, `role`, `blood_group`, `latitude`, `longitude`, `eligibility_status`, `donations_till_date` |
| Skipped rows | `blood_group == "Do not Know"` OR `blood_group.isna()` OR `latitude.isna()` OR `longitude.isna()` |
| Read by | `LiveHybridSource._parse_hackathon_csv()` |

**Filtering statistics** (approximate; exact numbers UNVERIFIED as they depend on the exact file version):
- Raw: 7033
- Skipped (Do-not-Know): 160
- Skipped (NaN blood group): 1876
- Skipped (null coordinates): ~24 additional
- Retained: ~4973

### 4. `newdata/BW_Sample_Data_Updated_v3.xlsx - user_data.csv` — Supplementary User Registry

| Attribute | Value |
|-----------|-------|
| Path | `newdata/BW_Sample_Data_Updated_v3.xlsx - user_data.csv` |
| Format | UTF-8 CSV |
| Rows | 200 data rows |
| Columns | `user_id`, `name`, `gender`, `mobile`, `date_of_birth`, `blood_group`, `city`, `pincode`, `role`, `insert_time` |
| Roles | `Fighter` (78), `Emergency Donor` (73), `Bridge Donor` (49) |
| No coordinates | Uses `city` field mapped to clinic centres via `_CITY_CLINIC_IDX` with ~2km jitter |
| Read by | `LiveHybridSource._parse_user_csv()` |

### 5. `newdata/cleaned_thalassemia_data.csv` — NOT READ BY ANY CODE

| Attribute | Value |
|-----------|-------|
| Path | `newdata/cleaned_thalassemia_data.csv` |
| Format | UTF-8 CSV |
| Rows | 7,033 data rows |
| Columns | 31 (same columns as `Hackathon Data_5000.csv`) |
| Bytes | 1,635,475 (vs 1,645,828 for Hackathon CSV — different file) |
| Read by | **NOTHING** — no source code reads this file |

This file appears to be a cleaned version of the hackathon data but has not been wired into `LiveHybridSource` or any adapter. It is the most likely candidate for the "new data not reflecting in UI" issue. See [docs/10](10-data-flow-and-known-issues.md).

---

## Synthetic Data Generation

### Controlled by `SyntheticSource` (`hemogrid/sources/synthetic_source.py`)

**RNG**: `np.random.default_rng(seed=42)` — a fresh `numpy.random.Generator` seeded with 42. This is passed through the entire generation pipeline in order.

### Generation order (critical — sequence-dependent)

```
rng = np.random.default_rng(seed=42)
1. _load_blood_banks()          ← no rng calls (CSV loading only)
2. _build_reliability_scorer()  ← no rng calls (scikit-learn fit)
3. _generate_clinics()          ← no rng calls (hardcoded rows)
4. _generate_donors(rng, ...)   ← consumes rng [900 donors, many calls each]
5. _generate_patients(rng, ...) ← consumes rng [199 random patients + PAT-0001 prepended]
6. _make_bonds(rng, ...)        ← consumes rng [random bonds for ~25% of donors]
7. _generate_inventory(rng, ...)← consumes rng [inventory across ~1/3 of component banks]
# ------------ RNG sequence now frozen: all golden objects are determined ------------
8. _generate_stressed_patients(clinics)       ← NO rng; deterministic post-RNG patients
9. _generate_compatibility_stress(clinics, banks) ← NO rng; inventory + patients
10. _generate_emergency_patient(clinics)      ← NO rng; deterministic PAT-EMERG-99
```

Any rng call inserted before step 8 will shift ALL downstream object identities. This is the Seeding Isolation Invariant documented in `CLAUDE.md`.

### Synthetic entity counts (from `uvicorn_out.txt` log, `SyntheticSource` path)

| Entity | Count |
|--------|-------|
| Blood banks (canonical) | 2,817 |
| Clinics | 9 |
| Donors (random) | 900 |
| Patients (random) | 199 + 1 (PAT-0001 prepended) = 200 |
| Bonds (donors linked to patients) | 237 donors |
| Inventory units (total) | 1,295 |
| Banks with inventory | 358 |
| Stressed Lucknow patients (post-RNG) | 4 (PAT-0201..0204) |
| Stressed Hyderabad patients (post-RNG) | 12 (PAT-0301..0312) |
| Emergency patient (post-RNG) | 1 (PAT-EMERG-99) |

**Total patient count after all additions**: 200 (random) + 4 (LKN stressed) + 12 (HYD stressed) + 1 (EMERG) = 217

### Clinic generation (hardcoded in `_generate_clinics()`)

All 9 clinics have `Provenance.SYNTHETIC` for all fields:

| clinic_id | name | lat | lng | region |
|-----------|------|-----|-----|--------|
| CLN-GNT-01 | Guntur Thalassaemia Centre | 16.3019 | 80.4378 | Andhra Pradesh |
| CLN-HYD-01 | Hyderabad Thalassaemia Centre | 17.3850 | 78.4867 | Telangana |
| CLN-CHN-01 | Chennai Thalassaemia Centre | 13.0827 | 80.2707 | Tamil Nadu |
| CLN-BLR-01 | Bengaluru Thalassaemia Centre | 12.9716 | 77.5946 | Karnataka |
| CLN-MUM-01 | Mumbai Thalassaemia Centre | 19.0760 | 72.8777 | Maharashtra |
| CLN-AHM-01 | Ahmedabad Thalassaemia Centre | 23.0225 | 72.5714 | Gujarat |
| CLN-DEL-01 | Delhi Thalassaemia Centre | 28.6139 | 77.2090 | Delhi |
| CLN-KOL-01 | Kolkata Thalassaemia Centre | 22.5726 | 88.3639 | West Bengal |
| CLN-LKN-01 | Lucknow Thalassaemia Centre | 26.8467 | 80.9462 | Uttar Pradesh |

### Donor generation (`_generate_donors()`)

- Count: 900
- Geography: jittered (~0.07 degrees std ≈ 8 km) around a weighted-sampled valid-coord blood bank. Guntur banks get 6× weight (Guntur-biased cluster for demo)
- ABO+Rh: sampled via `enrichment.random_abo_rh(rng)` from Indian population frequencies
- Phenotype: sampled via `enrichment.random_phenotype(rng)` independently per antigen
- RFM: sampled from a random UCI row with noise `[-2,+3)` for Recency, `[-1,+2)` for Frequency, `[-3,+4)` for Time
- Reliability score: computed by the fitted `LogisticRegression` scorer
- Contactable: 85% probability; WhatsApp channel added at 70% conditional probability
- donor_id: `DON-0001` through `DON-0900`

### Patient generation (`_generate_patients()`)

- Count: 200 total (199 random + 1 hardcoded PAT-0001 at index 0)
- PAT-0001 is prepended first (before rng calls for i=1..199)
- Alloimmunization rate: 20%
- Interval: uniform integer `[21, 28]` days
- `last_transfusion_date`: `today - Uniform(0, interval)` days (so ~25–33% are due within 7 days)
- Clinic assignment: Guntur gets 4× weight; others equal weight

### Golden PAT-0001 (hardcoded in `_generate_patients()`)

```python
Patient(
    patient_id="PAT-0001",
    abo_group=ABOGroup.B,
    rh_d=True,
    phenotype=Phenotype(C=True, c=False, E=False, e=True, K=False),
    known_antibodies=["anti-K"],
    transfusion_interval_days=21,
    last_transfusion_date=today - timedelta(days=16),  # due in 5 days
    units_per_session=1,
    clinic_id="CLN-GNT-01",
    preferred_language="te",
)
```

`last_transfusion_date = today - 16 days` means `needed_by_date = today - 16 + 21 = today + 5`. This is a `date.today()` call at load time, so the 5-day window is relative to the startup date, not a fixed date.

### Bond generation (`_make_bonds()`)

The demo bond is set before random bonds:
1. Find the first donor `d` in `donors` where `d.abo_group == B`, `d.rh_d == True`, `d.phenotype.K == False`, and `_donor_eligible(d) == True`.
2. Pin that donor's location to `Location(lat=16.32, lng=80.45)` (near Guntur clinic, ≈2.4 km away).
3. Append `PAT-0001` to `demo_donor.linked_patients`.
4. This donor becomes `DON-0002` (it is the first eligible B+ K-neg donor found in the seed=42 sequence, which turns out to be index 1 in the list, i.e., `DON-0002`).

Random bonds: 25% of donors[1:] get 1–2 patients randomly linked from ABO-compatible patients[1:].

### Inventory generation (`_generate_inventory()`)

**Demo unit** (before random inventory): placed at `guntur_demo_banks[0]` — the first bank in the banks list where `coord_valid=True` AND `district.upper()=="GUNTUR"` AND `does_components==True`:
```python
InventoryUnit(
    component=Component.PRBC,
    abo=ABOGroup.B,
    rh_d=True,
    phenotype_tags=Phenotype(C=True, c=True, E=False, e=True, K=False),
    collection_date=today - timedelta(days=39),
    expiry_date=today + timedelta(days=3),
    storage_status="ok",
)
```
This unit has `K=False` so it passes `phenotype_antibody_safe(PAT-0001, unit)` for the `anti-K` antibody. The CLAUDE.md says this goes to `BB-0036`. UNVERIFIED from code alone — `BB-0036` is the bank_id assigned to the first valid-coord, does_components Guntur bank at index 36 (1-based). This depends on CSV row ordering.

**Random inventory**: 1/3 of all `coord_valid=True AND does_components=True` banks, randomly permuted by `rng`. Each selected bank gets 2–5 units. Component distribution: 70% PRBC (35–42 day shelf), 20% platelets (4–5 day shelf), 10% plasma (270–365 day shelf). 60% of PRBC units get a phenotype assigned; 40% are untyped (`phenotype_tags=None`).

### Post-RNG Deterministic Additions

These are appended AFTER the rng is fully consumed by steps 4–7.

**`_generate_stressed_patients(clinics)` → PAT-0201..0204 at CLN-LKN-01 (Lucknow)**:
- PAT-0201: B+, anti-K+anti-E+anti-c, 2 units/session
- PAT-0202: O+, anti-E+anti-c, 2 units/session
- PAT-0203: A+, anti-K+anti-c, 2 units/session
- PAT-0204: B−, anti-K+anti-E, 2 units/session

**`_generate_compatibility_stress(clinics, banks)` → inventory + PAT-0301..0312 at CLN-HYD-01**:
- Adds 35 B+ PRBC units across BB-2253 (21 units), BB-2257 (11 units), BB-2260 (3 units)
  - Phenotype mix: 28 untyped, 3 E+c+K-neg, 2 E+c+K+, 2 safe (K-neg, E-neg, c-neg)
- Adds 28 PRBC units across BB-0037 (20 units) and BB-0041 (8 units) for Guntur
  - ABO/Rh composition mirrors Guntur demand; expiry `today+14` (so BB-0036 demo unit at `today+3` still wins for PAT-0001)
- Adds 12 B+ patients at CLN-HYD-01 (PAT-0301..0312), all anti-E + anti-c; PAT-0309 and PAT-0310 also anti-K

**`_generate_emergency_patient(clinics)` → PAT-EMERG-99 at CLN-KOL-01 (Kolkata)**:
```python
Patient(
    patient_id="PAT-EMERG-99",
    abo_group=ABOGroup.O,
    rh_d=False,       # O-negative
    phenotype=Phenotype(C=False, c=False, E=False, e=True, K=False),
    known_antibodies=["anti-K", "anti-E", "anti-c", "anti-C"],
    transfusion_interval_days=21,
    last_transfusion_date=today - timedelta(days=19),  # due in 2 days
    units_per_session=1,
    clinic_id="CLN-KOL-01",
    preferred_language="bn",
)
```

---

## Canonical Data Models (field-by-field)

All canonical models inherit from `CanonicalModel(BaseModel)` which adds `provenance: dict[str, Provenance]`.

### Enums (`hemogrid/models/enums.py`)

| Enum | Values |
|------|--------|
| `Provenance` | `PROVIDED = "provided"`, `DERIVED = "derived"`, `SYNTHETIC = "synthetic"` |
| `ABOGroup` | `A = "A"`, `B = "B"`, `AB = "AB"`, `O = "O"` |
| `Component` | `PRBC = "PRBC"`, `PLATELETS = "platelets"`, `PLASMA = "plasma"` |
| `BankCategory` | `GOVERNMENT = "Government"`, `PRIVATE = "Private"`, `CHARITY = "Charity"` |
| `Lever` | `INVENTORY = "inventory"`, `DONOR = "donor"`, `EMERGENCY = "emergency"` |
| `RequestStatus` | `PREDICTED = "predicted"`, `PROPOSED = "proposed"`, `APPROVED = "approved"`, `FULFILLED = "fulfilled"` |

### Sub-models (`hemogrid/models/common.py`)

**`Location`**: `lat: float`, `lng: float`

**`Phenotype`**: `C: Optional[bool]`, `c: Optional[bool]`, `E: Optional[bool]`, `e: Optional[bool]`, `K: Optional[bool]`

**`Consent`**: `contactable: bool`, `channels: list[str]`

### `Patient` (`hemogrid/models/patient.py`)

| Field | Type | Constraints | Provenance guidance |
|-------|------|-------------|---------------------|
| `patient_id` | `str` | — | SYNTHETIC (tokenized) |
| `abo_group` | `ABOGroup` | — | PROVIDED or SYNTHETIC |
| `rh_d` | `bool` | — | PROVIDED or SYNTHETIC |
| `phenotype` | `Optional[Phenotype]` | — | PROVIDED if organizer includes it; SYNTHETIC otherwise |
| `known_antibodies` | `list[str]` | — | PROVIDED or SYNTHETIC |
| `transfusion_interval_days` | `int` | `ge=21, le=28` | SYNTHETIC |
| `last_transfusion_date` | `date` | — | PROVIDED or SYNTHETIC |
| `units_per_session` | `int` | `ge=1, le=2` | SYNTHETIC |
| `clinic_id` | `str` | — | PROVIDED or SYNTHETIC |
| `preferred_language` | `str` | — | SYNTHETIC |
| `provenance` | `dict[str, Provenance]` | — | (inherited from CanonicalModel) |

### `Donor` (`hemogrid/models/donor.py`)

| Field | Type | Constraints | Provenance guidance |
|-------|------|-------------|---------------------|
| `donor_id` | `str` | — | SYNTHETIC (tokenized) |
| `abo_group` | `ABOGroup` | — | PROVIDED or SYNTHETIC |
| `rh_d` | `bool` | — | PROVIDED or SYNTHETIC |
| `phenotype` | `Optional[Phenotype]` | — | PROVIDED or SYNTHETIC |
| `location` | `Location` | — | PROVIDED or SYNTHETIC |
| `last_donation_date` | `Optional[date]` | — | PROVIDED or SYNTHETIC |
| `donation_count` | `int` | `ge=0`, default 0 | PROVIDED or DERIVED |
| `reliability_score` | `float` | `ge=0.0, le=1.0`, default 0.0 | DERIVED |
| `preferred_language` | `str` | — | SYNTHETIC |
| `consent` | `Consent` | — | SYNTHETIC (demo); real system needs explicit opt-in |
| `linked_patients` | `list[str]` | — | DERIVED (Blood Bridge bonds) |
| `engagement_log` | `list[dict[str, Any]]` | — | DERIVED (populated by Engagement Agent at runtime) |

### `BloodBank` (`hemogrid/models/blood_bank.py`)

| Field | Type | Constraints | Provenance guidance |
|-------|------|-------------|---------------------|
| `bank_id` | `str` | — | DERIVED (our stable token) |
| `source_serial` | `int` | — | PROVIDED (original "Sr No") |
| `name` | `str` | — | PROVIDED |
| `location` | `Location` | — | PROVIDED when coord_valid; SYNTHETIC if geocoded |
| `coord_valid` | `bool` | — | DERIVED |
| `address` | `Optional[str]` | — | PROVIDED |
| `state` | `str` | — | PROVIDED |
| `district` | `Optional[str]` | — | PROVIDED |
| `pincode` | `Optional[str]` | — | PROVIDED |
| `contact` | `Optional[str]` | — | PROVIDED (Mobile coalesced with Contact No) |
| `category` | `Optional[BankCategory]` | — | PROVIDED |
| `does_components` | `bool` | — | PROVIDED ("Blood Component Available" == "YES") |
| `service_hours` | `Optional[str]` | — | PROVIDED |
| `units` | `list[InventoryUnit]` | — | SYNTHETIC |

### `InventoryUnit` (`hemogrid/models/blood_bank.py`)

| Field | Type | Constraints | Provenance guidance |
|-------|------|-------------|---------------------|
| `component` | `Component` | — | SYNTHETIC |
| `abo` | `ABOGroup` | — | SYNTHETIC |
| `rh_d` | `bool` | — | SYNTHETIC |
| `phenotype_tags` | `Optional[Phenotype]` | — | SYNTHETIC |
| `collection_date` | `date` | — | SYNTHETIC |
| `expiry_date` | `date` | — | SYNTHETIC |
| `storage_status` | `str` | values: "ok", "degraded", "quarantined" | SYNTHETIC |

### `Clinic` (`hemogrid/models/clinic.py`)

| Field | Type | Provenance |
|-------|------|------------|
| `clinic_id` | `str` | PROVIDED or SYNTHETIC |
| `location` | `Location` | PROVIDED or SYNTHETIC |
| `name` | `str` | PROVIDED or SYNTHETIC |
| `region` | `str` | PROVIDED or SYNTHETIC |

### `Request` (`hemogrid/models/request.py`)

All fields `DERIVED` (created by the engine at runtime, not from any external dataset).

| Field | Type | Constraints |
|-------|------|-------------|
| `request_id` | `str` | — |
| `patient_id` | `str` | — |
| `needed_by_date` | `date` | — |
| `component` | `Component` | — |
| `units` | `int` | `ge=1` |
| `required_phenotype` | `Optional[Phenotype]` | — |
| `candidate_matches` | `list[str]` | default [] |
| `chosen_lever` | `Optional[Lever]` | — |
| `status` | `RequestStatus` | default `PREDICTED` |
| `audit_trail` | `list[dict[str, Any]]` | default [] |

### `CanonicalDataset` (`hemogrid/models/dataset.py`)

Container returned by every `DataSource.load()`:
```python
patients:    list[Patient]    = []
donors:      list[Donor]      = []
blood_banks: list[BloodBank]  = []
clinics:     list[Clinic]     = []
requests:    list[Request]    = []  # always empty from DataSource; created at runtime
```

---

## DataSource Interface and Implementations

### `DataSource` ABC (`hemogrid/sources/base.py`)

```python
class DataSource(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @abstractmethod
    def load(self) -> CanonicalDataset: ...
```

### `OrganizerAdapter` (`hemogrid/sources/organizer_adapter.py`)

Stub. Both `source_name` and `load()` raise `NotImplementedError`. Described as "THE ONLY FILE EDITED ON HACKATHON DAY." Not used in the running system.

### `SyntheticSource` (`hemogrid/sources/synthetic_source.py`)

Constructor: `SyntheticSource(data_dir: Optional[Path] = None, seed: int = 42)`
- `data_dir` defaults to `Path(__file__).parent.parent.parent / "data"` (resolves relative to the source file, not CWD)
- `source_name` returns `"SyntheticSource"`

### `LiveHybridSource` (`hemogrid/sources/live_source.py`)

Constructor: `LiveHybridSource(data_dir: Optional[Path] = None)`
- `data_dir` defaults to `Path(__file__).parent.parent.parent / "data"` (same as SyntheticSource)
- `self._newdata_dir = self._data_dir.parent / "newdata"` (one level up from `data/`, then into `newdata/`)
- `source_name` returns `"LiveHybridSource"`
- `TODAY_SIMULATION: date = date(2026, 6, 5)` — hardcoded module-level constant used for all live-patient date anchoring

**Bank pruning** (`_prune_to_catchment()`): Retains banks within `_CATCHMENT_KM = 80.0` km of `_HYD_LOC = Location(lat=17.3850, lng=78.4867)`. Banks with `coord_valid=False` are excluded. Additionally retains up to 5 nearest banks for each of 3 showcase clinic locs: CLN-GNT-01 (Guntur), CLN-LKN-01 (Lucknow), CLN-MUM-01 (Mumbai).

**Inventory seeding**: Two passes:
1. `_seed_catchment_inventory()`: 1 unit per 3 eligible nearby donors (within 10 km), capped at 8 per bank
2. `_seed_patient_matched_inventory()`: 2–3 ABO/Rh-compatible PRBC units per live patient in the nearest retained bank; Hyderabad patients have a starvation gate (60% high-risk / 35% low-risk probability of being denied) to ensure CLN-HYD-01 remains a blood desert

### Active Source Selection (API startup)

`hemogrid/api/main.py:_build_dataset()`:
```python
flag = os.environ.get("HEMOGRID_USE_LIVE_DATA", "true").strip().lower()
if flag != "false":
    return LiveHybridSource().load()
return SyntheticSource().load()
```

Default is `LiveHybridSource` (the `"true"` default means live data is active unless explicitly disabled).
