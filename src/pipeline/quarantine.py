"""Kit quarantine sink helpers (insert into silver.quarantine)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import duckdb

from pipeline.db import init_schemas


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def insert_quarantine(
    conn: duckdb.DuckDBPyConnection,
    rows: Iterable[Mapping[str, Any] | Sequence[Any]],
) -> int:
    """Insert quarantine rows into silver.quarantine.

    Each row may be a mapping with keys:
      event_id, reason_code, detail, raw_json [, quarantined_at]
    or a sequence (event_id, reason_code, detail, raw_json [, quarantined_at]).

    Returns the number of rows inserted.
    """
    # Table must exist (silver.ensure_silver_tables); create if missing for kit safety.
    init_schemas(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.quarantine (
            event_id        VARCHAR,
            reason_code     VARCHAR,
            detail          VARCHAR,
            raw_json        VARCHAR,
            quarantined_at  TIMESTAMP
        )
        """
    )

    count = 0
    now = _utc_now()
    for row in rows:
        if isinstance(row, Mapping):
            event_id = row.get("event_id")
            reason_code = row.get("reason_code")
            detail = row.get("detail")
            raw_json = row.get("raw_json")
            quarantined_at = row.get("quarantined_at", now)
        else:
            seq = list(row)
            event_id = seq[0] if len(seq) > 0 else None
            reason_code = seq[1] if len(seq) > 1 else None
            detail = seq[2] if len(seq) > 2 else None
            raw_json = seq[3] if len(seq) > 3 else None
            quarantined_at = seq[4] if len(seq) > 4 else now

        conn.execute(
            """
            INSERT INTO silver.quarantine
                (event_id, reason_code, detail, raw_json, quarantined_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [event_id, reason_code, detail, raw_json, quarantined_at],
        )
        count += 1
    return count
