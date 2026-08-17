"""Silver current-state grain (CANDIDATE fills winner + quarantine predicates).

Order key (ascending; last wins): ``(event_time, sequence, event_id)``
per KIT_CONTRACT.md.

- Null ``event_time`` never wins.
- GPV_day = UTC date of winning COMPLETED ``event_time``.
- Quarantine codes: NULL_PK | BAD_AMOUNT | UNKNOWN_STATUS (continue-on-bad-rows).

Public API (harness)::

    build_silver(db_path=...)
"""

from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import duckdb

from pipeline.db import get_connection, init_schemas
from pipeline.logging_utils import get_logger
from pipeline.quarantine import insert_quarantine

logger = get_logger("pipeline.silver")

PathLike = Union[str, Path]

KNOWN_STATUSES = {"PENDING", "COMPLETED", "FAILED", "CANCELLED"}


def _parse_amount(amount: Any) -> Optional[float]:
    """Parse a bronze amount (string/number/None) into a finite float, else None."""
    if amount is None:
        return None
    text = str(amount).strip()
    if not text:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _gpv_day(event_time: Optional[str]) -> Optional[date]:
    """UTC calendar date of an ISO-8601 event_time string, else None."""
    if not event_time:
        return None
    try:
        return datetime.fromisoformat(event_time.replace("Z", "+00:00")).date()
    except ValueError:
        return None

BRONZE_SELECT = """
    SELECT event_id, transaction_id, status, product_type, currency,
           amount, event_time, sequence, source_file_hint,
           _ingested_at, _source_file, _row_hash
    FROM bronze.events
"""


def ensure_silver_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create silver.transactions_current and silver.quarantine if missing."""
    init_schemas(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.transactions_current (
            transaction_id     VARCHAR PRIMARY KEY,
            event_id           VARCHAR,
            status             VARCHAR,
            product_type       VARCHAR,
            currency           VARCHAR,
            amount_magnitude   DOUBLE,
            event_time         VARCHAR,
            sequence           BIGINT,
            gpv_day            DATE,
            updated_at         TIMESTAMP
        )
        """
    )
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


def classify_quarantine(row: Mapping[str, Any]) -> Optional[str]:
    """Return a quarantine reason_code or None if the row is eligible for silver.

    CANDIDATE: implement exactly these codes (KIT_CONTRACT):
      - NULL_PK         — missing/null transaction_id or event_id
      - BAD_AMOUNT      — unparseable / illegal magnitude (NaN, empty, non-numeric)
      - UNKNOWN_STATUS  — status not in {PENDING, COMPLETED, FAILED, CANCELLED}

    Return None when the event may compete for transactions_current.
    """
    if not row.get("transaction_id") or not row.get("event_id"):
        return "NULL_PK"
    if _parse_amount(row.get("amount")) is None:
        return "BAD_AMOUNT"
    if row.get("status") not in KNOWN_STATUSES:
        return "UNKNOWN_STATUS"
    return None


def pick_winner(events_for_tx: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Select the winning event for one transaction_id.

    CANDIDATE: order key ascending, last wins: (event_time, sequence, event_id).
    Null event_time never wins. Null sequence sorts lowest.
    On the returned winner dict also set:
      amount_magnitude = abs(parse(amount)) when parseable/finite
      gpv_day = UTC date of event_time when status is COMPLETED, else null
    Null event_time never wins. Documented in KIT_CONTRACT / docs/STATUS_GPV_EFFECT.

    When producing the winner row, set:
      - amount_magnitude = abs(parse(amount))  # finite magnitude
      - gpv_day = UTC date of winning COMPLETED event_time (else null)
    build_silver inserts those keys; bronze only has amount / event_time.
    """
    if not events_for_tx:
        raise ValueError("pick_winner requires at least one event")

    def _sort_key(rec: Mapping[str, Any]) -> tuple[int, str, int, int, str]:
        event_time = rec.get("event_time")
        sequence = rec.get("sequence")
        return (
            1 if event_time else 0,
            event_time or "",
            1 if sequence is not None else 0,
            sequence or 0,
            rec.get("event_id") or "",
        )

    winner = dict(max(events_for_tx, key=_sort_key))

    magnitude = _parse_amount(winner.get("amount"))
    winner["amount_magnitude"] = abs(magnitude) if magnitude is not None else None
    winner["gpv_day"] = (
        _gpv_day(winner.get("event_time")) if winner.get("status") == "COMPLETED" else None
    )
    return winner


def _fetch_bronze_records(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    result = conn.execute(BRONZE_SELECT)
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, row)) for row in result.fetchall()]


def build_silver(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    db_path: Optional[PathLike] = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Build silver.transactions_current from bronze.events.

    Accepts either an open ``conn`` or ``db_path`` (harness/Makefile style).

    Orchestration (kit skeleton):
      1. ensure_silver_tables
      2. read bronze.events
      3. classify_quarantine → kit insert_quarantine for bad rows
      4. group remaining by transaction_id → pick_winner → upsert current

    Candidate implements classify_quarantine and pick_winner (and any
    magnitude / gpv_day derivation they choose before insert).
    """
    own = conn is None
    if own:
        conn = get_connection(db_path)
    assert conn is not None

    try:
        ensure_silver_tables(conn)

        # Clear prior silver build for deterministic rebuild from bronze
        conn.execute("DELETE FROM silver.transactions_current")
        conn.execute("DELETE FROM silver.quarantine")

        records = _fetch_bronze_records(conn)
        if not records:
            return {
                "bronze_rows": 0,
                "quarantined": 0,
                "current_rows": 0,
            }

        good: list[dict[str, Any]] = []
        quarantine_batch: list[dict[str, Any]] = []

        for rec in records:
            reason = classify_quarantine(rec)  # CANDIDATE
            if reason is not None:
                quarantine_batch.append(
                    {
                        "event_id": rec.get("event_id"),
                        "reason_code": reason,
                        "detail": f"quarantine:{reason}",
                        "raw_json": str(rec),
                    }
                )
            else:
                good.append(rec)

        if quarantine_batch:
            insert_quarantine(conn, quarantine_batch)

        by_tx: dict[Any, list[dict[str, Any]]] = {}
        for rec in good:
            tid = rec.get("transaction_id")
            by_tx.setdefault(tid, []).append(rec)

        current_rows = 0
        for _tid, events in by_tx.items():
            winner = pick_winner(events)  # CANDIDATE
            conn.execute(
                """
                INSERT INTO silver.transactions_current (
                    transaction_id, event_id, status, product_type, currency,
                    amount_magnitude, event_time, sequence, gpv_day, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    winner.get("transaction_id"),
                    winner.get("event_id"),
                    winner.get("status"),
                    winner.get("product_type"),
                    winner.get("currency"),
                    winner.get("amount_magnitude"),
                    winner.get("event_time"),
                    winner.get("sequence"),
                    winner.get("gpv_day"),
                ],
            )
            current_rows += 1

        return {
            "bronze_rows": len(records),
            "quarantined": len(quarantine_batch),
            "current_rows": current_rows,
        }
    finally:
        if own:
            conn.close()
