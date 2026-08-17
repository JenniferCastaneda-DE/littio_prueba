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
    """Create silver.transactions_current, silver.quarantine, and the
    silver.processed_events watermark table if missing.

    processed_events tracks (event_id -> _row_hash) already folded into
    transactions_current / quarantine, so build_silver can skip bronze rows
    it has already merged (see build_silver for the incremental strategy).
    """
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.processed_events (
            event_id        VARCHAR PRIMARY KEY,
            row_hash        VARCHAR NOT NULL,
            transaction_id  VARCHAR
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


def _fetch_processed_hashes(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = conn.execute("SELECT event_id, row_hash FROM silver.processed_events").fetchall()
    return {event_id: row_hash for event_id, row_hash in rows}


def _fetch_current_rows(
    conn: duckdb.DuckDBPyConnection, transaction_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Existing transactions_current rows for the given ids, as pick_winner-shaped dicts.

    amount_magnitude (already non-negative) is fed back in as "amount" so the
    stored winner can re-compete fairly against new bronze rows without
    needing to keep the raw amount string around.
    """
    if not transaction_ids:
        return {}
    placeholders = ",".join("?" for _ in transaction_ids)
    rows = conn.execute(
        f"""
        SELECT transaction_id, event_id, status, product_type, currency,
               amount_magnitude, event_time, sequence, gpv_day
        FROM silver.transactions_current
        WHERE transaction_id IN ({placeholders})
        """,
        list(transaction_ids),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for tid, event_id, status, product_type, currency, magnitude, event_time, sequence, gpv_day in rows:
        out[tid] = {
            "transaction_id": tid,
            "event_id": event_id,
            "status": status,
            "product_type": product_type,
            "currency": currency,
            "amount": magnitude,
            "event_time": event_time,
            "sequence": sequence,
            "gpv_day": gpv_day,
        }
    return out


def build_silver(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    db_path: Optional[PathLike] = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Merge bronze.events into silver.transactions_current incrementally.

    Accepts either an open ``conn`` or ``db_path`` (harness/Makefile style).

    Orchestration:
      1. ensure_silver_tables
      2. read bronze.events, diff against silver.processed_events by
         (event_id, _row_hash) — unseen or content-changed rows are the
         "delta"; already-merged/byte-identical redeliveries are skipped
      3. classify_quarantine on the delta → kit insert_quarantine for bad rows
      4. group delta's good rows by transaction_id, re-competing each affected
         transaction_id against its *existing* transactions_current row (if
         any) → pick_winner over the union → upsert (MERGE), not
         truncate-and-reload
      5. record the delta's (event_id, row_hash) as processed

    Candidate implements classify_quarantine and pick_winner (and any
    magnitude / gpv_day derivation they choose before insert). See
    docs/ARCHITECTURE.md decision table for why this is a merge and not a
    full rebuild.
    """
    own = conn is None
    if own:
        conn = get_connection(db_path)
    assert conn is not None

    try:
        ensure_silver_tables(conn)

        records = _fetch_bronze_records(conn)
        if not records:
            return {"bronze_rows": 0, "delta_rows": 0, "quarantined": 0, "current_rows": 0}

        processed = _fetch_processed_hashes(conn)
        delta = [
            rec for rec in records if processed.get(rec.get("event_id")) != rec.get("_row_hash")
        ]

        current_rows = int(
            conn.execute("SELECT COUNT(*) FROM silver.transactions_current").fetchone()[0]
        )
        if not delta:
            return {
                "bronze_rows": len(records),
                "delta_rows": 0,
                "quarantined": 0,
                "current_rows": current_rows,
            }

        good: list[dict[str, Any]] = []
        quarantine_batch: list[dict[str, Any]] = []

        for rec in delta:
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

        existing_by_tx = _fetch_current_rows(conn, list(by_tx.keys()))
        for tid, existing in existing_by_tx.items():
            by_tx[tid].append(existing)

        for _tid, events in by_tx.items():
            winner = pick_winner(events)  # CANDIDATE
            conn.execute(
                """
                INSERT INTO silver.transactions_current (
                    transaction_id, event_id, status, product_type, currency,
                    amount_magnitude, event_time, sequence, gpv_day, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, now())
                ON CONFLICT (transaction_id) DO UPDATE SET
                    event_id = EXCLUDED.event_id,
                    status = EXCLUDED.status,
                    product_type = EXCLUDED.product_type,
                    currency = EXCLUDED.currency,
                    amount_magnitude = EXCLUDED.amount_magnitude,
                    event_time = EXCLUDED.event_time,
                    sequence = EXCLUDED.sequence,
                    gpv_day = EXCLUDED.gpv_day,
                    updated_at = now()
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

        conn.executemany(
            """
            INSERT INTO silver.processed_events (event_id, row_hash, transaction_id)
            VALUES (?, ?, ?)
            ON CONFLICT (event_id) DO UPDATE SET
                row_hash = EXCLUDED.row_hash,
                transaction_id = EXCLUDED.transaction_id
            """,
            [[rec.get("event_id"), rec.get("_row_hash"), rec.get("transaction_id")] for rec in delta],
        )

        current_rows = int(
            conn.execute("SELECT COUNT(*) FROM silver.transactions_current").fetchone()[0]
        )

        return {
            "bronze_rows": len(records),
            "delta_rows": len(delta),
            "quarantined": len(quarantine_batch),
            "current_rows": current_rows,
        }
    finally:
        if own:
            conn.close()
