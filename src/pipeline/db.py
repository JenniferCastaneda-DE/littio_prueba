"""DuckDB connection and schema initialization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

from pipeline.paths import ensure_data_dirs, warehouse_path

SCHEMAS = ("bronze", "silver", "stage", "gold", "meta")


def connect(db_path: str | Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open (or create) the kit warehouse DuckDB file."""
    ensure_data_dirs()
    path = warehouse_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_schemas(conn: duckdb.DuckDBPyConnection) -> None:
    """Create bronze/silver/stage/gold/meta schemas if missing."""
    for schema in SCHEMAS:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def init_meta_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create meta tables used by kit land / lineage."""
    init_schemas(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta.processed_files (
            source_file   VARCHAR PRIMARY KEY,
            row_count     BIGINT NOT NULL,
            landed_at     TIMESTAMP NOT NULL
        )
        """
    )


def init_bronze_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create bronze.events (kit land target)."""
    init_schemas(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bronze.events (
            event_id          VARCHAR PRIMARY KEY,
            transaction_id    VARCHAR,
            status            VARCHAR,
            product_type      VARCHAR,
            currency          VARCHAR,
            amount            VARCHAR,
            event_time        VARCHAR,
            sequence          BIGINT,
            source_file_hint  VARCHAR,
            _ingested_at      TIMESTAMP NOT NULL,
            _source_file      VARCHAR NOT NULL,
            _row_hash         VARCHAR NOT NULL
        )
        """
    )


def init_stage_gold_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create empty stage/gold daily metrics shells (filled by gold + WAP publish)."""
    init_schemas(conn)
    ddl = """
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            gpv_day        DATE,
            product_type   VARCHAR,
            currency       VARCHAR,
            gpv_amount     DOUBLE
        )
    """
    conn.execute(ddl.format(schema="stage", table="gold_daily_metrics"))
    conn.execute(ddl.format(schema="gold", table="daily_metrics"))


def init_all(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize all kit schemas and base tables (bronze + meta + stage/gold shells)."""
    init_schemas(conn)
    init_meta_tables(conn)
    init_bronze_tables(conn)
    init_stage_gold_tables(conn)


def get_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Connect and run full kit DDL init."""
    conn = connect(db_path)
    init_all(conn)
    return conn
