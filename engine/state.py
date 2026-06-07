"""
engine/state.py — HemoGrid simulation state manager.

SQLite-backed, CSV-initialized, mutation-safe state layer.
Run:  python -m engine.state --test-flow
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = Path("./data/build")
DB_PATH   = Path("./data/working_sim.db")
TODAY     = date(2026, 6, 6)

# ── Module-level connection singleton ─────────────────────────────────────────
_conn: Optional[sqlite3.Connection] = None

_CSV_TABLES = [
    "donors",
    "patients",
    "bags",
    "facilities",
    "banks",
    "antibodies",
    "reservations_log",
    "potential_donors",
]


def _sanitize_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Rename columns that would create SQLite duplicate-name errors.
    SQLite column names are case-insensitive, so phenotype_C and phenotype_c
    conflict.  The second occurrence in each clashing pair gets an '_alt' suffix
    (e.g. phenotype_c_alt, phenotype_e_alt, phenotype_k_alt, phenotype_s_alt).
    """
    seen: set = set()
    mapping: dict = {}
    for col in df.columns:
        cl = col.lower()
        if cl in seen:
            mapping[col] = col + "_alt"
        else:
            seen.add(cl)
            mapping[col] = col
    return df.rename(columns=mapping)


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH))
        _conn.row_factory = sqlite3.Row
    return _conn


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log(action_type: str, actor: str, description: str, affected_ids: list[str]) -> None:
    get_conn().execute(
        "INSERT INTO activity_log (timestamp, action_type, actor, description, affected_ids) "
        "VALUES (?,?,?,?,?)",
        (str(TODAY), action_type, actor, description, json.dumps(affected_ids)),
    )
    get_conn().commit()


def _log_count() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]


def _assert_log_grew(count_before: int, context: str) -> None:
    count_after = _log_count()
    if count_after != count_before + 1:
        msg = (
            f"[FAIL] {context}: activity_log did not grow "
            f"(before={count_before}, after={count_after})"
        )
        print(msg)
        raise AssertionError(msg)
    print(f"  [PASS] {context}: activity_log entry recorded (row {count_after}).")


def _total_available() -> int:
    return get_conn().execute(
        "SELECT COUNT(*) FROM bags WHERE status='available' AND expiry_date >= ?",
        (str(TODAY),),
    ).fetchone()[0]


def _total_bag_rows() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM bags").fetchone()[0]


def _available_at_bank(bank_id: str) -> int:
    return get_conn().execute(
        "SELECT COUNT(*) FROM bags "
        "WHERE current_location_id=? AND status='available' AND expiry_date>=?",
        (bank_id, str(TODAY)),
    ).fetchone()[0]


# ── Public inventory query (invariant query, verbatim from spec) ──────────────

def get_derived_inventory(bank_id: str, blood_type: str) -> int:
    """
    Count available bags at bank_id matching abo||rhd == blood_type.
    blood_type examples: 'Opos', 'Aneg', 'ABpos'.
    Uses the invariant query verbatim — date is TODAY pinned to '2026-06-06'.
    """
    return get_conn().execute(
        """
        SELECT COUNT(*) FROM bags
        WHERE current_location_id = ?
          AND status = 'available'
          AND expiry_date >= '2026-06-06'
          AND abo || rhd = ?
        """,
        (bank_id, blood_type),
    ).fetchone()[0]


# ── Reset / init ──────────────────────────────────────────────────────────────

def reset_simulation_state() -> None:
    """Drop all tables and re-clone fresh from base CSVs. Asserts 536 available bags."""
    import pandas as pd

    global _conn
    if _conn is not None:
        try:
            _conn.rollback()
        except Exception:
            pass
        _conn.close()
        _conn = None

    conn = get_conn()
    cur = conn.cursor()

    for table in _CSV_TABLES + ["activity_log", "match_pool"]:
        cur.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.commit()

    for table in _CSV_TABLES:
        csv_path = DATA_DIR / f"{table}.csv"
        if not csv_path.exists():
            print(f"  [WARN] {csv_path} not found — skipped.")
            continue
        df = _sanitize_columns(pd.read_csv(csv_path, dtype=str))
        df.to_sql(table, conn, if_exists="replace", index=False)
        print(f"  Loaded {table}: {len(df)} rows")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT NOT NULL,
            action_type  TEXT NOT NULL,
            actor        TEXT NOT NULL,
            description  TEXT NOT NULL,
            affected_ids TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_pool (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id    TEXT NOT NULL,
            donor_id      TEXT NOT NULL,
            tier          TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            status        TEXT NOT NULL
        )
    """)
    conn.commit()

    # Loud assert
    n = _total_available()
    if n != 536:
        msg = f"[FAIL] reset_simulation_state: expected 536 available bags, got {n}"
        print(msg)
        raise AssertionError(msg)
    print(f"  [PASS] reset_simulation_state: {n} available bags confirmed.")


# ── Mutations ─────────────────────────────────────────────────────────────────

def issue_bag_to_patient(bag_id: str, patient_id: str) -> None:
    """
    Flip bag status 'available'->'issued', set reserved_for_patient_id, update
    patient last_transfusion_date=TODAY.  

    If bag's current_location_id differs from patient's home_facility_id (inter-facility):
    - Updates bag's current_location_id to patient's facility
    - Logs two activity entries: TRANSIT then CONSUMED
    
    If same facility:
    - Logs single activity entry: CONSUMED
    
    Appends to activity_log.

    Asserts:
    - Bank's derived available count drops by exactly 1.
    - Total bag row count is unchanged.
    - activity_log grew by 1 or 2 depending on transfer.
    """
    conn = get_conn()

    bag_row = conn.execute(
        "SELECT status, current_location_id, abo, rhd FROM bags WHERE bag_id=?", (bag_id,)
    ).fetchone()
    if bag_row is None:
        raise ValueError(f"issue_bag_to_patient: bag {bag_id!r} not found")
    if bag_row["status"] != "available":
        raise ValueError(
            f"issue_bag_to_patient: bag {bag_id!r} not available (status={bag_row['status']!r})"
        )

    patient_row = conn.execute(
        "SELECT home_facility_id FROM patients WHERE patient_id=?", (patient_id,)
    ).fetchone()
    if patient_row is None:
        raise ValueError(f"issue_bag_to_patient: patient {patient_id!r} not found")

    bank_id            = bag_row["current_location_id"]
    patient_facility   = patient_row["home_facility_id"]
    is_inter_facility  = bank_id != patient_facility
    
    before_bank = _available_at_bank(bank_id)
    before_rows = _total_bag_rows()
    before_log  = _log_count()

    # If inter-facility, update location to patient's facility and log TRANSIT
    if is_inter_facility:
        conn.execute(
            "UPDATE bags SET current_location_id=? WHERE bag_id=?",
            (patient_facility, bag_id),
        )
        conn.commit()
        _log(
            "transit",
            "system",
            f"TRANSIT: Bag {bag_id} dispatched from {bank_id} to {patient_facility}",
            [bag_id, bank_id, patient_facility],
        )

    # Mark as issued
    conn.execute(
        "UPDATE bags SET status='issued', reserved_for_patient_id=? WHERE bag_id=?",
        (patient_id, bag_id),
    )
    conn.execute(
        "UPDATE patients SET last_transfusion_date=? WHERE patient_id=?",
        (str(TODAY), patient_id),
    )
    conn.commit()

    _log(
        "consume",
        "system",
        f"CONSUMED: Unit {bag_id} successfully issued to {patient_id}",
        [bag_id, patient_id],
    )

    # Loud asserts
    after_bank = _available_at_bank(bank_id)
    after_rows = _total_bag_rows()

    if after_bank != before_bank - 1:
        msg = (
            f"[FAIL] issue_bag_to_patient: bank {bank_id} available should drop by 1 "
            f"(before={before_bank}, after={after_bank})"
        )
        print(msg)
        raise AssertionError(msg)
    print(f"  [PASS] issue_bag_to_patient: bank {bank_id} available {before_bank}->{after_bank}.")

    if after_rows != before_rows:
        msg = (
            f"[FAIL] issue_bag_to_patient: total bag row count changed "
            f"(before={before_rows}, after={after_rows})"
        )
        print(msg)
        raise AssertionError(msg)
    print(f"  [PASS] issue_bag_to_patient: total bag rows stable at {after_rows}.")

    expected_log_grow = 2 if is_inter_facility else 1
    after_log = _log_count()
    if after_log != before_log + expected_log_grow:
        msg = (
            f"[FAIL] issue_bag_to_patient: activity_log should grow by {expected_log_grow} "
            f"(before={before_log}, after={after_log})"
        )
        print(msg)
        raise AssertionError(msg)
    print(f"  [PASS] issue_bag_to_patient: activity_log grew by {expected_log_grow}.")


def register_donation(donor_id: str, bank_id: str, abo: str, rhd: str) -> str:
    """
    Insert a new available bag with serialized BAG####### ID.
    collection_date=TODAY, expiry_date=TODAY+42.  Appends to activity_log.
    Returns the new bag_id.

    Asserts:
    - Global available bag count increases by exactly 1.
    - activity_log grew by 1.
    """
    conn = get_conn()

    before_total = _total_available()
    before_log   = _log_count()

    max_id   = conn.execute("SELECT MAX(bag_id) FROM bags").fetchone()[0]
    next_num = int(max_id[3:]) + 1 if max_id else 1
    new_bag_id = f"BAG{next_num:07d}"

    conn.execute(
        """
        INSERT INTO bags (
            bag_id, donor_id, abo, rhd, collection_date, expiry_date,
            status, current_location_id, component,
            leukoreduced, irradiated, washed, cmv_negative,
            tti_screen_status, reserved_for_patient_id, source
        ) VALUES (?,?,?,?,?,?,'available',?,'packed_rbc',
                  'False','False','False','False','pass',NULL,'sim')
        """,
        (
            new_bag_id, donor_id, abo, rhd,
            str(TODAY), str(TODAY + timedelta(days=42)),
            bank_id,
        ),
    )
    conn.commit()

    _log(
        "register_donation",
        "system",
        f"New bag {new_bag_id} from donor {donor_id} at bank {bank_id}",
        [new_bag_id, donor_id, bank_id],
    )

    after_total = _total_available()
    if after_total != before_total + 1:
        msg = (
            f"[FAIL] register_donation: global available count should increase by 1 "
            f"(before={before_total}, after={after_total})"
        )
        print(msg)
        raise AssertionError(msg)
    print(
        f"  [PASS] register_donation: global available {before_total}->{after_total}, "
        f"new bag {new_bag_id}."
    )

    _assert_log_grew(before_log, "register_donation")

    return new_bag_id


def transfer_bag(bag_id: str, destination_bank_id: str) -> None:
    """
    Move bag to a different bank by updating current_location_id.
    Appends to activity_log.

    Asserts:
    - activity_log grew by 1.
    """
    conn = get_conn()

    row = conn.execute(
        "SELECT current_location_id FROM bags WHERE bag_id=?", (bag_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"transfer_bag: bag {bag_id!r} not found")

    from_bank  = row["current_location_id"]
    before_log = _log_count()

    conn.execute(
        "UPDATE bags SET current_location_id=? WHERE bag_id=?",
        (destination_bank_id, bag_id),
    )
    conn.commit()

    _log(
        "transfer_bag",
        "system",
        f"Transferred {bag_id} from {from_bank} to {destination_bank_id}",
        [bag_id, from_bank, destination_bank_id],
    )

    _assert_log_grew(before_log, "transfer_bag")
    print(f"  [PASS] transfer_bag: {bag_id} moved {from_bank}->{destination_bank_id}.")


# ── Test CLI ──────────────────────────────────────────────────────────────────

def _run_test_flow() -> None:
    print("=" * 62)
    print("HemoGrid State Engine — Test Flow")
    print("=" * 62)

    # 1. Reset
    print("\n[1] reset_simulation_state()")
    reset_simulation_state()

    conn = get_conn()

    # 2. Baseline
    total_0 = _total_available()
    print(f"\n[2] Baseline available bags: {total_0}")

    # Pick an available bag and its bank
    bag_row = conn.execute(
        "SELECT bag_id, current_location_id, abo, rhd FROM bags "
        "WHERE status='available' AND expiry_date >= ? LIMIT 1",
        (str(TODAY),),
    ).fetchone()
    bag_id  = bag_row["bag_id"]
    bank_id = bag_row["current_location_id"]
    bag_abo = bag_row["abo"]
    bag_rhd = bag_row["rhd"]

    bank_before = _available_at_bank(bank_id)
    derived_before = get_derived_inventory(bank_id, bag_abo + bag_rhd)
    print(
        f"    Bag : {bag_id}  ({bag_abo}{bag_rhd})"
        f"  Bank: {bank_id}  ({bank_before} available, "
        f"{derived_before} of type {bag_abo}{bag_rhd})"
    )

    # Pick any patient
    patient_row = conn.execute("SELECT patient_id FROM patients LIMIT 1").fetchone()
    patient_id  = patient_row["patient_id"]
    print(f"    Patient: {patient_id}")

    # 3. Issue bag
    print(f"\n[3] issue_bag_to_patient({bag_id!r}, {patient_id!r})")
    issue_bag_to_patient(bag_id, patient_id)
    total_1         = _total_available()
    derived_after   = get_derived_inventory(bank_id, bag_abo + bag_rhd)
    print(
        f"    get_derived_inventory({bank_id!r}, {bag_abo + bag_rhd!r}) "
        f"= {derived_before} -> {derived_after}"
    )

    # 4. Register a donation
    donor_row = conn.execute(
        "SELECT donor_id, abo, rhd, home_bank_id FROM donors "
        "WHERE home_bank_id IS NOT NULL AND home_bank_id != '' LIMIT 1"
    ).fetchone()
    d_donor = donor_row["donor_id"]
    d_bank  = donor_row["home_bank_id"]
    d_abo   = donor_row["abo"]
    d_rhd   = donor_row["rhd"]

    print(f"\n[4] register_donation({d_donor!r}, {d_bank!r}, {d_abo!r}, {d_rhd!r})")
    new_bag_id = register_donation(d_donor, d_bank, d_abo, d_rhd)
    total_2 = _total_available()

    # 5. Summary
    print("\n" + "=" * 62)
    print("Available bag count flow:")
    print(f"  After reset          : {total_0}")
    print(f"  After issue          : {total_1}  (d {total_1 - total_0:+d})")
    print(f"  After donation       : {total_2}  (d {total_2 - total_1:+d})")
    print(f"\nActivity log entries : {_log_count()}")
    print(f"New bag registered   : {new_bag_id}")
    print("=" * 62)
    print("ALL ASSERTS PASSED")


if __name__ == "__main__":
    if "--test-flow" in sys.argv:
        _run_test_flow()
    else:
        print("Usage: python -m engine.state --test-flow")
        sys.exit(1)
