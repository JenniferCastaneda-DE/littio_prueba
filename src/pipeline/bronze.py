"""WORKING bronze land: JSONL → bronze.events (upsert by event_id + processed_files).

Kit-owned. Candidates must not reimplement land/lineage for MUST.

Public API (harness / Makefile)::

    land(db_path=..., raw_dir=...)
    bronze_row_count(conn) / count_new_rows_on_reland(...)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import duckdb

from pipeline.db import get_connection, init_all
from pipeline.logging_utils import get_logger, log_event
from pipeline.paths import RAW

logger = get_logger("pipeline.bronze")

PathLike = Union[str, Path]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _row_hash(payload: dict[str, Any]) -> str:
    """Stable content hash of the raw event object (sorted JSON)."""
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_row(obj: dict[str, Any], source_file: str, ingested_at: datetime) -> dict[str, Any]:
    """Map a JSON object to bronze.events columns + lineage."""
    seq = obj.get("sequence")
    if seq is not None and not isinstance(seq, int):
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            seq = None

    amount = obj.get("amount")
    if amount is not None and not isinstance(amount, str):
        amount = str(amount)

    return {
        "event_id": obj.get("event_id"),
        "transaction_id": obj.get("transaction_id"),
        "status": obj.get("status"),
        "product_type": obj.get("product_type"),
        "currency": obj.get("currency"),
        "amount": amount,
        "event_time": obj.get("event_time"),
        "sequence": seq,
        "source_file_hint": obj.get("source_file_hint"),
        "_ingested_at": ingested_at,
        "_source_file": source_file,
        "_row_hash": _row_hash(obj),
    }


def _list_jsonl(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        return []
    files: list[Path] = []
    # Top-level *.jsonl and one-level subdirs (fixtures/late_redelivery_delta style)
    for p in sorted(raw_dir.rglob("*.jsonl")):
        if p.is_file():
            files.append(p)
    return files


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                log_event(
                    logger,
                    "skip_malformed_jsonl_line",
                    source_file=str(path),
                    line_no=line_no,
                    error=str(exc),
                )
                continue
            if not isinstance(obj, dict):
                continue
            rows.append(obj)
    return rows


def _upsert_event(conn: duckdb.DuckDBPyConnection, row: dict[str, Any]) -> None:
    """Idempotent upsert on event_id (DELETE + INSERT)."""
    event_id = row.get("event_id")
    if event_id is None:
        log_event(logger, "skip_null_event_id", source_file=row.get("_source_file"))
        return

    conn.execute("DELETE FROM bronze.events WHERE event_id = ?", [event_id])
    conn.execute(
        """
        INSERT INTO bronze.events (
            event_id, transaction_id, status, product_type, currency, amount,
            event_time, sequence, source_file_hint,
            _ingested_at, _source_file, _row_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            row["event_id"],
            row["transaction_id"],
            row["status"],
            row["product_type"],
            row["currency"],
            row["amount"],
            row["event_time"],
            row["sequence"],
            row["source_file_hint"],
            row["_ingested_at"],
            row["_source_file"],
            row["_row_hash"],
        ],
    )


def _record_processed(
    conn: duckdb.DuckDBPyConnection,
    source_file: str,
    row_count: int,
    landed_at: datetime,
) -> None:
    conn.execute("DELETE FROM meta.processed_files WHERE source_file = ?", [source_file])
    conn.execute(
        """
        INSERT INTO meta.processed_files (source_file, row_count, landed_at)
        VALUES (?, ?, ?)
        """,
        [source_file, row_count, landed_at],
    )


def _resolve_conn(
    conn: Optional[duckdb.DuckDBPyConnection],
    db_path: Optional[PathLike],
) -> tuple[duckdb.DuckDBPyConnection, bool]:
    """Return (connection, owns_connection)."""
    if conn is not None:
        return conn, False
    return get_connection(db_path), True


def bronze_row_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Return number of rows in bronze.events."""
    return int(conn.execute("SELECT COUNT(*) FROM bronze.events").fetchone()[0])


def count_new_rows_on_reland(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    raw_dir: Optional[PathLike] = None,
    db_path: Optional[PathLike] = None,
) -> int:
    """Land once more and return bronze row delta (must be 0 for idempotent kit land)."""
    conn, own = _resolve_conn(conn, db_path)
    try:
        init_all(conn)
        before = bronze_row_count(conn)
        land(conn=conn, raw_dir=raw_dir, db_path=db_path)
        after = bronze_row_count(conn)
        return after - before
    finally:
        if own:
            conn.close()


def land(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    raw_dir: Optional[PathLike] = None,
    db_path: Optional[PathLike] = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Land all ``*.jsonl`` under raw_dir into bronze.events (upsert by event_id).

    Accepts either an open ``conn`` or ``db_path`` (harness/Makefile style).

    - Adds lineage: _ingested_at, _source_file, _row_hash
    - Tracks each file in meta.processed_files
    - Re-landing the same files must not duplicate event_id

    Returns stats dict: files, rows_read, rows_upserted, bronze_rows, processed_files.
    """
    conn, own = _resolve_conn(conn, db_path)
    try:
        init_all(conn)

        root = Path(raw_dir) if raw_dir is not None else RAW
        files = _list_jsonl(root)
        rows_read = 0
        rows_upserted = 0
        files_landed = 0
        ingested_at = _utc_now()

        for path in files:
            try:
                source_name = str(path.relative_to(root))
            except ValueError:
                source_name = path.name

            objects = _read_jsonl(path)
            file_rows = 0
            for obj in objects:
                rows_read += 1
                if obj.get("event_id") is None:
                    log_event(logger, "skip_null_event_id", source_file=source_name)
                    continue
                row = _normalize_row(obj, source_file=source_name, ingested_at=ingested_at)
                _upsert_event(conn, row)
                rows_upserted += 1
                file_rows += 1

            _record_processed(conn, source_name, file_rows, ingested_at)
            files_landed += 1
            log_event(
                logger,
                "landed_file",
                source_file=source_name,
                row_count=file_rows,
            )

        stats = {
            "files": files_landed,
            "rows_read": rows_read,
            "rows_upserted": rows_upserted,
            "bronze_rows": bronze_row_count(conn),
            "processed_files": int(
                conn.execute("SELECT COUNT(*) FROM meta.processed_files").fetchone()[0]
            ),
            "raw_dir": str(root),
        }
        log_event(logger, "land_complete", **stats)
        return stats
    finally:
        if own:
            conn.close()
