"""Test 1 — Double-run GPV zero delta.

Identical reload of public raw data must produce zero net GPV change.
Fails clearly (CandidateNotImplemented) while silver/WAP remain stubbed.
Requires non-zero baseline GPV so empty gold cannot hollow-pass.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import (
    EXPECTED_PUBLIC_GPV_BASELINE_TOTAL,
    EXPECTED_PUBLIC_GPV_DAY_TOTAL,
    GOLDEN_DAY,
    gpv_day_total,
    gpv_total,
    reset_db,
    run_full_pipeline,
)


def test_double_run_gpv_zero_delta(db_path: Path, raw_dir: Path) -> None:
    """Full pipeline twice on the same files → GPV sum delta == 0."""
    assert raw_dir.exists(), f"missing public raw dir: {raw_dir}"

    reset_db(db_path)
    run_full_pipeline(db_path, raw_dir=raw_dir)
    gpv_first = gpv_total(db_path)
    gpv_day_first = gpv_day_total(db_path, GOLDEN_DAY)

    assert gpv_first > 0, (
        "GPV total is 0 after full pipeline — silver winner / gold SQL / WAP publish "
        "are not producing money. Empty gold must not hollow-pass double-run."
    )
    assert abs(gpv_day_first - EXPECTED_PUBLIC_GPV_DAY_TOTAL) <= 1e-6, (
        f"day {GOLDEN_DAY} GPV expected {EXPECTED_PUBLIC_GPV_DAY_TOTAL}, "
        f"got {gpv_day_first} (expected CSV total; incl. late COMPLETED on D)."
    )
    assert abs(gpv_first - EXPECTED_PUBLIC_GPV_BASELINE_TOTAL) <= 1e-6, (
        f"all-days baseline GPV expected {EXPECTED_PUBLIC_GPV_BASELINE_TOTAL}, "
        f"got {gpv_first} (day D golden + D+1 completed only)."
    )

    # Second run without wiping DB — land must upsert; silver/gold rebuild must not double-count.
    run_full_pipeline(db_path, raw_dir=raw_dir)
    gpv_second = gpv_total(db_path)

    delta = gpv_second - gpv_first
    assert abs(delta) <= 1e-9, (
        f"double-run GPV delta must be 0; got first={gpv_first}, second={gpv_second}, "
        f"delta={delta}. Re-runs must not double-count completed GPV."
    )
