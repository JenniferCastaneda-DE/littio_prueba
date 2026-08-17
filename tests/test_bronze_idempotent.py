"""Kit sanity (not one of the 5 official scored tests): bronze land is idempotent.

Land public raw twice; bronze.events row count must be stable.
Always runnable once pipeline.bronze.land exists — does not require candidate silver/gold.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import bronze_event_count, call_land, reset_db


def test_bronze_land_idempotent(db_path: Path, raw_dir: Path) -> None:
    assert raw_dir.exists(), f"missing public raw dir: {raw_dir}"

    reset_db(db_path)
    call_land(db_path, raw_dir=raw_dir)
    count_1 = bronze_event_count(db_path)

    call_land(db_path, raw_dir=raw_dir)
    count_2 = bronze_event_count(db_path)

    assert count_1 == count_2, (
        f"bronze.events not idempotent on re-land: {count_1} → {count_2}. "
        "Kit land must upsert / skip already-processed files (no truncate-reload theater)."
    )
    assert count_1 > 0, "bronze.events empty after land — raw dumps not ingested"
