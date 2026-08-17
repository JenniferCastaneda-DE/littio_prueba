"""Makefile-facing runners (smoke / rerun-proof / test-gate-fail / run).

Invoked as:  PYTHONPATH=src python -m tests.make_runners <cmd>
Keeps Makefile free of nested-quote Python one-liners.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is importable when launched as python -m tests.make_runners
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def cmd_smoke() -> int:
    from pipeline.bronze import bronze_row_count, land
    from pipeline.db import get_connection
    from pipeline.paths import DB_PATH, RAW

    if DB_PATH.exists():
        DB_PATH.unlink()
    s1 = land(db_path=DB_PATH, raw_dir=RAW)
    s2 = land(db_path=DB_PATH, raw_dir=RAW)
    con = get_connection(DB_PATH)
    try:
        n = bronze_row_count(con)
    finally:
        con.close()
    print(f"land#1={s1}")
    print(f"land#2={s2}")
    print(f"bronze.events rows: {n}")
    if n <= 0:
        print("FAIL bronze empty")
        return 1
    if s1.get("bronze_rows") is not None and s2.get("bronze_rows") is not None:
        if s1["bronze_rows"] != s2["bronze_rows"]:
            print("FAIL bronze row count changed on re-land")
            return 1
    print("smoke OK")
    return 0


def cmd_run() -> int:
    from pipeline.bronze import land
    from pipeline.paths import DB_PATH, RAW

    print("landing bronze…")
    print(land(db_path=DB_PATH, raw_dir=RAW))
    try:
        from pipeline.silver import build_silver

        print("silver…", build_silver(db_path=DB_PATH))
    except NotImplementedError as e:
        print(f"SKIP silver: NotImplemented (candidate TODO) — {e}")
        return 0
    try:
        from pipeline.quality import gold_is_published, run_wap

        ok = run_wap(db_path=DB_PATH)
        print(f"wap published={ok} gold_has_rows={gold_is_published(db_path=DB_PATH)}")
        if not ok:
            print("WAP gate failed closed")
            return 1
    except NotImplementedError as e:
        print(f"SKIP wap: NotImplemented (candidate TODO) — {e}")
        return 0
    print("run finished")
    return 0


# Public totals and delta increment (see tests/conftest.py / MESS_CATALOG)
# Day D golden CSV sum + D+1 completed-only (tx_dplus1_only USD 12)
_EXPECTED_PUBLIC_GPV_BASELINE_TOTAL = 657.0
_DELTA_LATE_GPV_INCREMENT = 60.0


def _gpv_sum(db_path) -> float:
    from pipeline.db import get_connection

    con = get_connection(db_path)
    try:
        cols = [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'gold' AND table_name = 'daily_metrics'"
            ).fetchall()
        ]
        amount_col = next(
            (c for c in ("gpv_amount", "gpv", "completed_gpv") if c in cols),
            None,
        )
        if amount_col is None:
            raise RuntimeError(f"gold.daily_metrics has no gpv column; cols={cols}")
        return float(
            con.execute(
                f"SELECT COALESCE(SUM({amount_col}), 0) FROM gold.daily_metrics"
            ).fetchone()[0]
        )
    finally:
        con.close()


def cmd_rerun_proof() -> int:
    from pipeline.bronze import bronze_row_count, land
    from pipeline.db import get_connection
    from pipeline.paths import DB_PATH, FIXTURES, RAW

    delta = FIXTURES / "late_redelivery_delta"
    if DB_PATH.exists():
        DB_PATH.unlink()

    def bcount() -> int:
        con = get_connection(DB_PATH)
        try:
            return bronze_row_count(con)
        finally:
            con.close()

    print("land #1…")
    land(db_path=DB_PATH, raw_dir=RAW)
    c1 = bcount()
    print(f"bronze count after land #1: {c1}")
    print("land #2 (idempotent)…")
    land(db_path=DB_PATH, raw_dir=RAW)
    c2 = bcount()
    print(f"bronze count after land #2: {c2}")
    if c1 != c2:
        print(f"FAIL bronze not idempotent: {c1} → {c2}")
        return 1
    if c1 <= 0:
        print("FAIL bronze.events empty after land")
        return 1
    print("PASS bronze event count stable")

    def try_money(extra_raw=None) -> None:
        from pipeline.quality import run_wap
        from pipeline.silver import build_silver

        if extra_raw is not None:
            land(db_path=DB_PATH, raw_dir=extra_raw)
        build_silver(db_path=DB_PATH)
        ok = run_wap(db_path=DB_PATH)
        if ok is False:
            raise RuntimeError("run_wap gate closed during rerun-proof money path")

    try:
        print("full pipeline run #1…")
        try_money()
        g1 = _gpv_sum(DB_PATH)
        print(f"GPV sum #1: {g1}")
        if g1 <= 0:
            print("FAIL GPV sum is 0 after pipeline — empty gold cannot hollow-pass")
            return 1
        if abs(g1 - _EXPECTED_PUBLIC_GPV_BASELINE_TOTAL) > 1e-6:
            print(
                f"FAIL baseline GPV {g1} != expected public all-days total "
                f"{_EXPECTED_PUBLIC_GPV_BASELINE_TOTAL} "
                f"(day D golden 645 + D+1 WITHDRAWAL/USD 12)"
            )
            return 1
        print("full pipeline run #2…")
        try_money()
        g2 = _gpv_sum(DB_PATH)
        print(f"GPV sum #2: {g2}")
        if abs(g2 - g1) > 1e-9:
            print(f"FAIL GPV delta on double run: {g2 - g1}")
            return 1
        print("PASS GPV double-run delta 0")
        if not delta.exists():
            print(f"WARN missing {delta}; skip late/redelivery money proof")
        else:
            print(f"apply late/redelivery delta from {delta}…")
            try_money(extra_raw=delta)
            g_after = _gpv_sum(DB_PATH)
            late_delta = g_after - g1
            if abs(late_delta - _DELTA_LATE_GPV_INCREMENT) > 1e-6:
                print(
                    f"FAIL first delta apply GPV change {late_delta} "
                    f"!= {_DELTA_LATE_GPV_INCREMENT} (tx_pending_only_B)"
                )
                return 1
            try_money(extra_raw=delta)
            g_after2 = _gpv_sum(DB_PATH)
            print(f"GPV after delta x1: {g_after}; after x2: {g_after2}")
            if abs(g_after2 - g_after) > 1e-9:
                print("FAIL double application of late_redelivery_delta changed GPV")
                return 1
            print("PASS late/redelivery no double GPV")
        print("rerun-proof OK (bronze + money)")
        return 0
    except NotImplementedError as e:
        print(f"kit bronze check OK; full money proof needs candidate code: {e}")
        return 0
    except ImportError as e:
        print(f"kit bronze check OK; full money proof needs candidate code: {e}")
        return 0


def cmd_test_gate_fail() -> int:
    from pipeline.bronze import land
    from pipeline.db import get_connection
    from pipeline.paths import DB_PATH, FIXTURES, RAW

    gate = FIXTURES / "gate_fail"
    if DB_PATH.exists():
        DB_PATH.unlink()

    try:
        from pipeline.quality import gold_is_published, run_wap
        from pipeline.silver import build_silver
    except ImportError as e:
        print(f"SKIP test-gate-fail: import — {e}")
        return 0

    try:
        raw = gate if gate.exists() else RAW
        land(db_path=DB_PATH, raw_dir=raw)
        build_silver(db_path=DB_PATH)

        con = get_connection(DB_PATH)
        try:
            n = int(
                con.execute(
                    "SELECT COUNT(*) FROM silver.transactions_current "
                    "WHERE status = 'COMPLETED'"
                ).fetchone()[0]
            )
            if n > 0:
                con.execute(
                    """
                    UPDATE silver.transactions_current
                    SET amount_magnitude = NULL
                    WHERE transaction_id = (
                        SELECT transaction_id FROM silver.transactions_current
                        WHERE status = 'COMPLETED' LIMIT 1
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
                        'tx_gate_null_amount', 'evt_gate_null_amount', 'COMPLETED',
                        'TRANSFER', 'USD', NULL, '2024-06-01T11:00:00Z', 1,
                        DATE '2024-06-01', CURRENT_TIMESTAMP
                    )
                    """
                )
        finally:
            con.close()

        try:
            ok = run_wap(db_path=DB_PATH)
        except NotImplementedError as e:
            print(f"SKIP test-gate-fail: WAP checks NotImplemented — {e}")
            return 0

        if ok is False and not gold_is_published(db_path=DB_PATH):
            print("PASS gate-fail closed (run_wap returned False, gold unpublished)")
            return 0
        if ok is True or gold_is_published(db_path=DB_PATH):
            print("FAIL gate-fail: pipeline published despite broken silver money")
            return 1
        print("PASS gate-fail closed")
        return 0
    except NotImplementedError as e:
        print(f"SKIP test-gate-fail: NotImplemented — {e}")
        return 0


COMMANDS = {
    "smoke": cmd_smoke,
    "run": cmd_run,
    "rerun-proof": cmd_rerun_proof,
    "test-gate-fail": cmd_test_gate_fail,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: python -m tests.make_runners {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
