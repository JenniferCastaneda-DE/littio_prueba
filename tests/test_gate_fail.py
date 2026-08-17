"""Test 3 — Fail-closed publish on broken money fixture.

Land gate_fail events (or public raw fallback), build silver when implemented,
then plant a COMPLETED row with NULL amount_magnitude so
check_completed_magnitude must close the gate. Gold must not publish.
NotImplementedError from candidate stubs fails clearly (does not skip).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    CandidateNotImplemented,
    call_build_silver,
    call_land,
    call_run_wap,
    gold_is_published,
    reset_db,
    seed_gate_fail_silver,
)


def test_gate_fail_closed(
    db_path: Path,
    gate_fail_fixture: Path,
    raw_dir: Path,
) -> None:
    # Prefer dedicated gate_fail dump; fall back to public raw if missing.
    land_src = gate_fail_fixture if gate_fail_fixture.exists() else raw_dir
    assert land_src.exists(), f"missing land source for gate-fail: {land_src}"

    reset_db(db_path)
    call_land(db_path, raw_dir=land_src)
    # Requires candidate classify_quarantine / pick_winner (clear NI failure).
    call_build_silver(db_path)
    seed_gate_fail_silver(db_path)

    # Intentional fail-closed: run_wap returns False on AssertionError/ValueError
    # from checks. Do NOT treat arbitrary exceptions as gate-closed (would false-pass).
    try:
        result = call_run_wap(db_path)
    except CandidateNotImplemented:
        raise

    if result is not False:
        pytest.fail(
            "gate_fail did not fail-closed: run_wap returned "
            f"{result!r} despite COMPLETED row with NULL amount_magnitude. "
            "Candidate WAP checks must block bad money before gold is visible.",
            pytrace=False,
        )

    assert not gold_is_published(db_path), (
        "gate closed but gold.daily_metrics still has rows — fail-closed violated"
    )
