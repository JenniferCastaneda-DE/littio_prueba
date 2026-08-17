"""Test 2 — Late COMPLETED / redelivery must not double-count GPV.

Applies data/fixtures/late_redelivery_delta after a baseline public pipeline.
- First apply: COMPLETED for tx_pending_only_B adds +60 TOPUP/USD once.
- Re-apply same delta (incl. redelivered event_id): GPV must not change again.
Fails clearly while silver/WAP remain NotImplemented.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import (
    DELTA_LATE_GPV_INCREMENT,
    EXPECTED_PUBLIC_GPV_BASELINE_TOTAL,
    EXPECTED_PUBLIC_GPV_DAY_TOTAL,
    GOLDEN_DAY,
    call_build_silver,
    call_land,
    call_run_wap,
    gpv_day_total,
    gpv_total,
    reset_db,
    run_full_pipeline,
)


def _rebuild_money(db_path: Path) -> None:
    """Silver rebuild + WAP publish (WAP stages gold internally)."""
    call_build_silver(db_path)
    result = call_run_wap(db_path)
    if result is False:
        raise AssertionError("run_wap closed gate unexpectedly during late-flip proof")


def test_late_flip_no_double_gpv(
    db_path: Path,
    raw_dir: Path,
    late_redelivery_delta: Path,
) -> None:
    assert raw_dir.exists(), f"missing public raw dir: {raw_dir}"
    assert late_redelivery_delta.exists(), (
        f"missing late/redelivery fixture: {late_redelivery_delta} "
        "(file or directory under data/fixtures/)"
    )

    reset_db(db_path)
    run_full_pipeline(db_path, raw_dir=raw_dir)
    gpv_baseline = gpv_total(db_path)
    day_baseline = gpv_day_total(db_path, GOLDEN_DAY)

    assert gpv_baseline > 0, (
        "baseline GPV is 0 — pipeline must publish public money before delta proof"
    )
    assert abs(day_baseline - EXPECTED_PUBLIC_GPV_DAY_TOTAL) <= 1e-6, (
        f"day {GOLDEN_DAY} baseline GPV expected {EXPECTED_PUBLIC_GPV_DAY_TOTAL}, "
        f"got {day_baseline}"
    )
    assert abs(gpv_baseline - EXPECTED_PUBLIC_GPV_BASELINE_TOTAL) <= 1e-6, (
        f"all-days baseline GPV expected {EXPECTED_PUBLIC_GPV_BASELINE_TOTAL}, "
        f"got {gpv_baseline}"
    )

    # Apply late/redelivery delta once and rebuild silver → wap
    call_land(db_path, raw_dir=late_redelivery_delta)
    _rebuild_money(db_path)
    gpv_after_late = gpv_total(db_path)
    day_after_late = gpv_day_total(db_path, GOLDEN_DAY)

    late_delta = gpv_after_late - gpv_baseline
    day_delta = day_after_late - day_baseline
    assert abs(late_delta - DELTA_LATE_GPV_INCREMENT) <= 1e-6, (
        f"first late_redelivery_delta apply must add GPV by "
        f"{DELTA_LATE_GPV_INCREMENT} (tx_pending_only_B TOPUP/USD COMPLETED); "
        f"got baseline={gpv_baseline}, after={gpv_after_late}, delta={late_delta}. "
        "Redelivery of evt_completed_tx_topup_cop_1 alone must not move GPV."
    )
    assert abs(day_delta - DELTA_LATE_GPV_INCREMENT) <= 1e-6, (
        f"late COMPLETED for tx_pending_only_B must attribute to day {GOLDEN_DAY}; "
        f"day delta={day_delta}, expected {DELTA_LATE_GPV_INCREMENT}"
    )

    # Apply the same delta again (redelivery) — GPV must not change
    call_land(db_path, raw_dir=late_redelivery_delta)
    _rebuild_money(db_path)
    gpv_after_redelivery = gpv_total(db_path)

    assert abs(gpv_after_redelivery - gpv_after_late) <= 1e-9, (
        f"redelivery doubled or changed GPV: after_late={gpv_after_late}, "
        f"after_redelivery={gpv_after_redelivery}, baseline={gpv_baseline}. "
        "Same event_id / late COMPLETED must not double-count money."
    )
