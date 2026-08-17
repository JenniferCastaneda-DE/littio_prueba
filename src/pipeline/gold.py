"""Gold layer: run gold_daily_metrics.sql into stage.gold_daily_metrics.

Public API (harness)::

    run_gold(db_path=...)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import duckdb

from pipeline.db import get_connection, init_stage_gold_tables
from pipeline.logging_utils import get_logger, log_event
from pipeline.paths import GOLD_SQL
from pipeline.silver import ensure_silver_tables

logger = get_logger("pipeline.gold")

PathLike = Union[str, Path]


def load_gold_sql(sql_path: Optional[PathLike] = None) -> str:
    """Load the gold daily metrics SQL file."""
    path = Path(sql_path) if sql_path is not None else GOLD_SQL
    if not path.exists():
        raise FileNotFoundError(f"Gold SQL not found: {path}")
    return path.read_text(encoding="utf-8")


def build_stage(
    conn: duckdb.DuckDBPyConnection,
    sql_path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Execute gold SQL and materialize into stage.gold_daily_metrics.

    Replaces stage contents. Does not touch gold.daily_metrics (WAP publish does).
    """
    init_stage_gold_tables(conn)
    ensure_silver_tables(conn)  # gold SQL reads silver.transactions_current
    sql = load_gold_sql(sql_path)

    conn.execute("DELETE FROM stage.gold_daily_metrics")

    # Prefer INSERT…SELECT of candidate SQL; wrap if they only provide a SELECT.
    stripped = sql.strip().rstrip(";")
    # Drop full-line SQL comments when detecting statement type / wrapping SELECT
    body_lines = [
        ln
        for ln in stripped.splitlines()
        if ln.strip() and not ln.strip().startswith("--")
    ]
    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError(f"Gold SQL has no executable body: {sql_path or GOLD_SQL}")

    if body.upper().startswith("INSERT"):
        conn.execute(body)
    else:
        conn.execute(
            "INSERT INTO stage.gold_daily_metrics "
            "(gpv_day, product_type, currency, gpv_amount)\n"
            f"{body}"
        )

    n = int(conn.execute("SELECT COUNT(*) FROM stage.gold_daily_metrics").fetchone()[0])
    stats = {"stage_rows": n, "sql_path": str(sql_path or GOLD_SQL)}
    log_event(logger, "gold_stage_built", **stats)
    return stats


def run_gold(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    db_path: Optional[PathLike] = None,
    sql_path: Optional[PathLike] = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Build stage gold from sql/gold_daily_metrics.sql.

    Accepts either an open ``conn`` or ``db_path`` (harness/Makefile style).
    """
    own = conn is None
    if own:
        conn = get_connection(db_path)
    assert conn is not None
    try:
        return build_stage(conn, sql_path=sql_path)
    finally:
        if own:
            conn.close()
