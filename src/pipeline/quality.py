"""WAP shell: stage → run checks → publish or abort (fail-closed).

Check bodies are CANDIDATE work (NotImplementedError until filled).
Publish plumbing is kit-owned and working.

Public API (harness)::

    run_wap(db_path=...)  # True if published; False if gate failed closed
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import duckdb

from pipeline import gold as gold_mod
from pipeline.db import get_connection, init_stage_gold_tables
from pipeline.logging_utils import get_logger, log_event

logger = get_logger("pipeline.quality")

PathLike = Union[str, Path]


def check_unique_transaction_id(conn: duckdb.DuckDBPyConnection) -> None:
    """Assert silver.transactions_current has unique transaction_id (PK grain).

    CANDIDATE: raise AssertionError/ValueError if duplicates exist.
    """
    dupes = conn.execute(
        """
        SELECT transaction_id, COUNT(*) AS n
        FROM silver.transactions_current
        GROUP BY transaction_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    if dupes:
        raise AssertionError(
            f"duplicate transaction_id in silver.transactions_current: {dupes}"
        )


def check_completed_magnitude(conn: duckdb.DuckDBPyConnection) -> None:
    """Assert COMPLETED rows have amount_magnitude ≥ 0 and NOT NULL.

    CANDIDATE: raise AssertionError/ValueError on violation (GPV money integrity).
    """
    bad = conn.execute(
        """
        SELECT transaction_id, amount_magnitude
        FROM silver.transactions_current
        WHERE status = 'COMPLETED'
          AND (amount_magnitude IS NULL OR amount_magnitude < 0)
        """
    ).fetchall()
    if bad:
        raise AssertionError(
            f"COMPLETED rows with NULL/negative amount_magnitude: {bad}"
        )


def check_gpv_reconciles_to_silver(conn: duckdb.DuckDBPyConnection) -> None:
    """Assert stage gold GPV reconciles to silver COMPLETED set for each day.

    CANDIDATE: compare stage.gold_daily_metrics to silver.transactions_current
    COMPLETED winners (gpv_day / product_type / currency). Raise on mismatch.
    """
    stage_rows = conn.execute(
        "SELECT gpv_day, product_type, currency, gpv_amount FROM stage.gold_daily_metrics"
    ).fetchall()
    silver_rows = conn.execute(
        """
        SELECT gpv_day, product_type, currency, SUM(amount_magnitude)
        FROM silver.transactions_current
        WHERE status = 'COMPLETED'
          AND gpv_day IS NOT NULL
        GROUP BY 1, 2, 3
        """
    ).fetchall()

    stage_map = {(r[0], r[1], r[2]): r[3] for r in stage_rows}
    silver_map = {(r[0], r[1], r[2]): r[3] for r in silver_rows}

    if set(stage_map) != set(silver_map):
        raise AssertionError(
            "gold/silver GPV key mismatch: "
            f"stage_only={set(stage_map) - set(silver_map)}, "
            f"silver_only={set(silver_map) - set(stage_map)}"
        )
    mismatches = {
        k: (stage_map[k], silver_map[k])
        for k in stage_map
        if abs((stage_map[k] or 0) - (silver_map[k] or 0)) > 1e-6
    }
    if mismatches:
        raise AssertionError(f"gold/silver GPV amount mismatch: {mismatches}")


def gold_is_published(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    db_path: Optional[PathLike] = None,
) -> bool:
    """True if gold.daily_metrics exists and has at least one row."""
    own = conn is None
    if own:
        conn = get_connection(db_path)
    assert conn is not None
    try:
        init_stage_gold_tables(conn)
        n = int(conn.execute("SELECT COUNT(*) FROM gold.daily_metrics").fetchone()[0])
        return n > 0
    finally:
        if own:
            conn.close()


def publish_gold(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Copy stage.gold_daily_metrics → gold.daily_metrics (replace)."""
    init_stage_gold_tables(conn)
    conn.execute("DELETE FROM gold.daily_metrics")
    conn.execute(
        """
        INSERT INTO gold.daily_metrics (gpv_day, product_type, currency, gpv_amount)
        SELECT gpv_day, product_type, currency, gpv_amount
        FROM stage.gold_daily_metrics
        """
    )
    n = int(conn.execute("SELECT COUNT(*) FROM gold.daily_metrics").fetchone()[0])
    stats = {"published_rows": n}
    log_event(logger, "gold_published", **stats)
    return stats


def run_wap(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    db_path: Optional[PathLike] = None,
    **_kwargs: Any,
) -> bool:
    """Write-Audit-Publish: stage gold, run 3 checks, publish only if all pass.

    Accepts either an open ``conn`` or ``db_path`` (harness/Makefile style).

    On check failure (AssertionError/ValueError): leave gold.daily_metrics
    untouched and return False (fail-closed).

    On NotImplementedError: re-raise so candidates know checks are unfinished.

    Returns True if published, False if gate failed closed.
    """
    own = conn is None
    if own:
        conn = get_connection(db_path)
    assert conn is not None

    try:
        gold_mod.build_stage(conn)

        try:
            check_unique_transaction_id(conn)
            check_completed_magnitude(conn)
            check_gpv_reconciles_to_silver(conn)
        except NotImplementedError:
            log_event(logger, "wap_checks_not_implemented")
            raise
        except (AssertionError, ValueError) as exc:
            log_event(logger, "wap_gate_failed", error=str(exc))
            return False

        publish_gold(conn)
        log_event(logger, "wap_success")
        return True
    finally:
        if own:
            conn.close()
