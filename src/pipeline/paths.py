"""Path helpers for the kit root, data dirs, and DuckDB warehouse file."""

from __future__ import annotations

from pathlib import Path

# src/pipeline/paths.py → package dir → src → kit root
PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
ROOT = SRC_DIR.parent

DATA = ROOT / "data"
RAW = DATA / "raw"
BRONZE = DATA / "bronze"
EXPECTED = DATA / "expected"
FIXTURES = DATA / "fixtures"
SQL_DIR = ROOT / "sql"
GOLD_SQL = SQL_DIR / "gold_daily_metrics.sql"
DB_PATH = DATA / "warehouse.duckdb"


def ensure_data_dirs() -> None:
    """Create data directories if missing (does not create the DuckDB file)."""
    for d in (DATA, RAW, BRONZE, EXPECTED, FIXTURES):
        d.mkdir(parents=True, exist_ok=True)


def warehouse_path(override: str | Path | None = None) -> Path:
    """Return the DuckDB warehouse path (default: data/warehouse.duckdb)."""
    if override is None:
        return DB_PATH
    return Path(override)
