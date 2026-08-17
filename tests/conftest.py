"""Shared fixtures for the Littio DE take-home kit harness.

Intended pipeline API (PYTHONPATH=src):
  pipeline.bronze.land(db_path=..., raw_dir=...)
  pipeline.silver.build_silver(db_path=...)
  pipeline.quality.run_wap(db_path=...)   # fail-closed; False or raise on gate fail
  pipeline.gold.run_gold(db_path=...)

Tables (KIT_CONTRACT):
  bronze.events
  silver.transactions_current
  silver.quarantine
  stage.gold_daily_metrics
  gold.daily_metrics
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FIXTURES_DIR = DATA_DIR / "fixtures"
EXPECTED_DIR = DATA_DIR / "expected"
DEFAULT_DB_PATH = DATA_DIR / "warehouse.duckdb"

# Public golden day (UTC)
GOLDEN_DAY = "2024-06-01"

# Sum of data/expected/gpv_2024-06-01.csv for golden day D only
# TOPUP COP 340 + TOPUP USD 30 + TRANSFER COP 150 + TRANSFER USD 50 + WITHDRAWAL COP 75
EXPECTED_PUBLIC_GPV_DAY_TOTAL = 645.0

# Full warehouse GPV after public raw land (D + D+1):
# day D 645 + day D+1 tx_dplus1_only WITHDRAWAL/USD 12.00
EXPECTED_PUBLIC_GPV_BASELINE_TOTAL = 657.0

# late_redelivery_delta: COMPLETED for tx_pending_only_B (TOPUP/USD 60) once
DELTA_LATE_GPV_INCREMENT = 60.0

# Backward-compatible alias (day-D golden sum)
EXPECTED_PUBLIC_GPV_TOTAL = EXPECTED_PUBLIC_GPV_DAY_TOTAL

# Planted public event_ids (KIT_CONTRACT)
PLANTED = {
    "evt_plant_null_pk": "NULL_PK",
    "evt_plant_bad_amount": "BAD_AMOUNT",
    "evt_plant_unknown_status": "UNKNOWN_STATUS",
}
LATE_COMPLETED_EVENT_ID = "evt_late_completed_tx_A"
LATE_TX_ID = "tx_late_A"
PENDING_TX_A_EVENT_ID = "evt_pending_tx_A"

# Kit gold DDL column (prefer this; accept aliases for candidate variance)
_GPV_AMOUNT_COLS = ("gpv_amount", "gpv", "completed_gpv")
_GPV_DATE_COLS = ("gpv_day", "metric_date", "day", "date")


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture
def raw_dir() -> Path:
    return RAW_DIR


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def expected_dir() -> Path:
    return EXPECTED_DIR


@pytest.fixture
def late_redelivery_delta() -> Path:
    """Delta dump for late COMPLETED / redelivery proofs."""
    return FIXTURES_DIR / "late_redelivery_delta"


@pytest.fixture
def gate_fail_fixture() -> Path:
    """Broken money fixture for fail-closed WAP."""
    return FIXTURES_DIR / "gate_fail"


@pytest.fixture
def expected_gpv_csv() -> Path:
    return EXPECTED_DIR / "gpv_2024-06-01.csv"


@pytest.fixture
def db_path(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Isolated DuckDB path under pytest tmp (default).

    Opt into the project warehouse with: @pytest.mark.project_db
    """
    if request.node.get_closest_marker("project_db"):
        path = DEFAULT_DB_PATH
        if path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    path = tmp_path / "warehouse.duckdb"
    return path


@pytest.fixture
def project_db_path() -> Path:
    """Shared project DB at data/warehouse.duckdb (reset each use)."""
    path = DEFAULT_DB_PATH
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def reset_db(path: Path) -> None:
    """Remove warehouse file if present."""
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)


def connect(path: Path, *, read_only: bool = False):
    import duckdb

    return duckdb.connect(str(path), read_only=read_only)


def bronze_event_count(path: Path) -> int:
    con = connect(path, read_only=True)
    try:
        return int(con.execute("SELECT COUNT(*) FROM bronze.events").fetchone()[0])
    finally:
        con.close()


def _gold_column_map(path: Path) -> tuple[list[str], str, str]:
    """Return (all_cols, date_col, amount_col) for gold.daily_metrics."""
    con = connect(path, read_only=True)
    try:
        cols = [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'gold' AND table_name = 'daily_metrics'"
            ).fetchall()
        ]
    finally:
        con.close()
    if not cols:
        raise RuntimeError("gold.daily_metrics missing or has no columns")
    date_col = next((c for c in _GPV_DATE_COLS if c in cols), None)
    amount_col = next((c for c in _GPV_AMOUNT_COLS if c in cols), None)
    if amount_col is None:
        raise RuntimeError(f"no gpv column on gold.daily_metrics; cols={cols}")
    if date_col is None:
        raise RuntimeError(f"no date column on gold.daily_metrics; cols={cols}")
    return cols, date_col, amount_col


def gpv_total(path: Path) -> float:
    """Sum GPV from gold.daily_metrics across all days (kit column: gpv_amount)."""
    _cols, _date_col, amount_col = _gold_column_map(path)
    con = connect(path, read_only=True)
    try:
        return float(
            con.execute(
                f"SELECT COALESCE(SUM({amount_col}), 0) FROM gold.daily_metrics"
            ).fetchone()[0]
        )
    finally:
        con.close()


def gpv_day_total(path: Path, day: str = GOLDEN_DAY) -> float:
    """Sum GPV from gold.daily_metrics for a single UTC calendar day."""
    _cols, date_col, amount_col = _gold_column_map(path)
    con = connect(path, read_only=True)
    try:
        return float(
            con.execute(
                f"""
                SELECT COALESCE(SUM({amount_col}), 0) FROM gold.daily_metrics
                WHERE CAST({date_col} AS DATE) = CAST(? AS DATE)
                """,
                [day],
            ).fetchone()[0]
        )
    finally:
        con.close()


def gpv_for_day(path: Path, day: str = GOLDEN_DAY) -> list[dict]:
    """Return gold daily metric rows for a UTC day as list of dicts."""
    _cols, date_col, _amount_col = _gold_column_map(path)
    con = connect(path, read_only=True)
    try:
        result = con.execute(
            f"""
            SELECT * FROM gold.daily_metrics
            WHERE CAST({date_col} AS DATE) = CAST(? AS DATE)
            ORDER BY 1, 2, 3
            """,
            [day],
        )
        col_names = [d[0] for d in result.description]
        return [dict(zip(col_names, row)) for row in result.fetchall()]
    finally:
        con.close()


def quarantine_codes_for_event(path: Path, event_id: str) -> list[str]:
    con = connect(path, read_only=True)
    try:
        cols = [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'silver' AND table_name = 'quarantine'"
            ).fetchall()
        ]
        # Kit DDL uses reason_code (see pipeline.silver.ensure_silver_tables)
        code_col = next(
            (c for c in ("reason_code", "quarantine_code", "code") if c in cols),
            None,
        )
        if code_col is None:
            raise RuntimeError(f"no code column on silver.quarantine; cols={cols}")
        rows = con.execute(
            f"SELECT {code_col} FROM silver.quarantine WHERE event_id = ?",
            [event_id],
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        con.close()


def gold_is_published(path: Path) -> bool:
    """True if gold.daily_metrics exists and has ≥1 row."""
    try:
        from pipeline.quality import gold_is_published as _kit_gold_published

        return bool(_kit_gold_published(db_path=path))
    except Exception:
        pass
    con = connect(path, read_only=True)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'gold' AND table_name = 'daily_metrics'"
        ).fetchone()[0]
        if not n:
            return False
        return int(con.execute("SELECT COUNT(*) FROM gold.daily_metrics").fetchone()[0]) > 0
    except Exception:
        return False
    finally:
        con.close()


def ensure_silver_ddl(path: Path) -> None:
    """Create silver tables (kit DDL) without running candidate winner logic."""
    from pipeline.db import get_connection
    from pipeline.silver import ensure_silver_tables

    con = get_connection(path)
    try:
        ensure_silver_tables(con)
    finally:
        con.close()


def seed_gate_fail_silver(path: Path) -> None:
    """Plant money-integrity failure into silver.transactions_current.

    Uses live kit DDL (amount_magnitude, gpv_day). PRIMARY KEY on
    transaction_id prevents true duplicate rows — force NULL magnitude on a
    COMPLETED row so check_completed_magnitude must fail-closed when implemented.
    """
    ensure_silver_ddl(path)
    con = connect(path, read_only=False)
    try:
        n = int(
            con.execute(
                "SELECT COUNT(*) FROM silver.transactions_current WHERE status = 'COMPLETED'"
            ).fetchone()[0]
        )
        if n > 0:
            con.execute(
                """
                UPDATE silver.transactions_current
                SET amount_magnitude = NULL
                WHERE transaction_id = (
                    SELECT transaction_id FROM silver.transactions_current
                    WHERE status = 'COMPLETED'
                    LIMIT 1
                )
                """
            )
        else:
            con.execute(
                """
                INSERT INTO silver.transactions_current (
                    transaction_id, event_id, status, product_type, currency,
                    amount_magnitude, event_time, sequence, gpv_day, updated_at
                ) VALUES (
                    'tx_gate_null_amount',
                    'evt_gate_null_amount',
                    'COMPLETED',
                    'TRANSFER',
                    'USD',
                    NULL,
                    '2024-06-01T11:00:00Z',
                    1,
                    DATE '2024-06-01',
                    CURRENT_TIMESTAMP
                )
                """
            )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Pipeline call wrappers — fail clearly on NotImplemented / missing modules
# ---------------------------------------------------------------------------
class CandidateNotImplemented(AssertionError):
    """Raised when a candidate TODO (NotImplementedError) is still stubbed.

    Subclasses AssertionError so pytest reports FAILED (not ERROR/skip).
    """


def _fail_ni(layer: str, exc: BaseException) -> None:
    raise CandidateNotImplemented(
        f"Candidate must implement {layer} "
        f"(got {type(exc).__name__}: {exc}). "
        f"Replace NotImplementedError stubs per KIT_CONTRACT."
    ) from exc


def call_land(db_path: Path, raw_dir: Path = RAW_DIR):
    try:
        from pipeline.bronze import land
    except ImportError as e:
        raise CandidateNotImplemented(
            f"pipeline.bronze.land missing — kit incomplete: {e}"
        ) from e
    try:
        return land(db_path=db_path, raw_dir=raw_dir)
    except NotImplementedError as e:
        _fail_ni("pipeline.bronze.land", e)


def call_build_silver(db_path: Path):
    try:
        from pipeline.silver import build_silver
    except ImportError as e:
        raise CandidateNotImplemented(
            f"pipeline.silver.build_silver missing — candidate must implement silver: {e}"
        ) from e
    try:
        return build_silver(db_path=db_path)
    except NotImplementedError as e:
        _fail_ni("pipeline.silver.build_silver", e)


def call_run_wap(db_path: Path):
    try:
        from pipeline.quality import run_wap
    except ImportError as e:
        raise CandidateNotImplemented(
            f"pipeline.quality.run_wap missing — candidate must fill WAP checks: {e}"
        ) from e
    try:
        return run_wap(db_path=db_path)
    except NotImplementedError as e:
        _fail_ni("pipeline.quality.run_wap", e)


def call_run_gold(db_path: Path):
    try:
        from pipeline.gold import run_gold
    except ImportError as e:
        raise CandidateNotImplemented(
            f"pipeline.gold.run_gold missing — candidate must fill gold SQL: {e}"
        ) from e
    try:
        return run_gold(db_path=db_path)
    except NotImplementedError as e:
        _fail_ni("pipeline.gold.run_gold", e)


def run_full_pipeline(db_path: Path, raw_dir: Path = RAW_DIR) -> None:
    """Land → silver → WAP (stage + checks + publish).

    Matches pipeline.cli run: ``run_wap`` builds stage gold and publishes.
    Optional ``run_gold`` is not required after a successful WAP.
    Fails (does not skip) on NotImplemented.
    """
    call_land(db_path, raw_dir=raw_dir)
    call_build_silver(db_path)
    result = call_run_wap(db_path)
    if result is False:
        raise AssertionError(
            "run_wap returned False (gate closed) during full pipeline on public data"
        )


@pytest.fixture
def land_public(db_path: Path, raw_dir: Path):
    """Land public raw dumps into an isolated DB; yield db_path."""
    reset_db(db_path)
    call_land(db_path, raw_dir=raw_dir)
    return db_path
