"""Test 4 — Planted quarantine codes on public raw data.

KIT_CONTRACT planted event_ids must land in silver.quarantine with exact codes:
  evt_plant_null_pk        → NULL_PK
  evt_plant_bad_amount     → BAD_AMOUNT
  evt_plant_unknown_status → UNKNOWN_STATUS (status FAILD)

Fails clearly with CandidateNotImplemented until classify_quarantine is filled.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import (
    PLANTED,
    bronze_event_count,
    call_build_silver,
    call_land,
    connect,
    quarantine_codes_for_event,
    reset_db,
)


def test_quarantine_planted_codes(db_path: Path, raw_dir: Path) -> None:
    assert raw_dir.exists(), f"missing public raw dir: {raw_dir}"

    reset_db(db_path)
    call_land(db_path, raw_dir=raw_dir)
    assert bronze_event_count(db_path) > 0, "bronze empty after land"

    # Planted rows must be present in bronze before silver (except null event_id,
    # which bronze skips — our plants all have event_id set).
    con = connect(db_path, read_only=True)
    try:
        for event_id in PLANTED:
            n = int(
                con.execute(
                    "SELECT COUNT(*) FROM bronze.events WHERE event_id = ?",
                    [event_id],
                ).fetchone()[0]
            )
            assert n == 1, (
                f"planted event_id {event_id!r} missing from bronze.events after land "
                f"(count={n}); check data/raw dumps vs KIT_CONTRACT"
            )
    finally:
        con.close()

    call_build_silver(db_path)

    missing: list[str] = []
    wrong: list[str] = []

    for event_id, expected_code in PLANTED.items():
        codes = quarantine_codes_for_event(db_path, event_id)
        if not codes:
            missing.append(f"{event_id} (expected {expected_code})")
            continue
        if expected_code not in codes:
            wrong.append(
                f"{event_id}: got {codes!r}, expected code {expected_code!r}"
            )

    assert not missing and not wrong, (
        "planted quarantine rows incorrect.\n"
        + (f"  missing event_ids: {missing}\n" if missing else "")
        + (f"  wrong codes: {wrong}\n" if wrong else "")
        + "Codes must be exactly NULL_PK | BAD_AMOUNT | UNKNOWN_STATUS per KIT_CONTRACT."
    )
