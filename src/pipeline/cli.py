"""Thin CLI: land | silver | wap | gold | run | smoke.

Usage (from kit root with PYTHONPATH=src)::

  python -m pipeline.cli land
  python -m pipeline.cli run
  python -m pipeline.cli smoke
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from pipeline.bronze import bronze_row_count, land
from pipeline.db import get_connection
from pipeline.gold import run_gold
from pipeline.logging_utils import get_logger, log_event
from pipeline.paths import DB_PATH, ROOT, ensure_data_dirs
from pipeline.quality import gold_is_published, run_wap
from pipeline.silver import build_silver, ensure_silver_tables

logger = get_logger("pipeline.cli")


def _print_stats(label: str, stats: Any) -> None:
    print(f"{label}: {json.dumps(stats, default=str)}")


def cmd_land(_args: argparse.Namespace) -> int:
    stats = land(db_path=DB_PATH)
    _print_stats("land", stats)
    return 0


def cmd_silver(_args: argparse.Namespace) -> int:
    try:
        conn = get_connection(DB_PATH)
        try:
            ensure_silver_tables(conn)
        finally:
            conn.close()
        stats = build_silver(db_path=DB_PATH)
        _print_stats("silver", stats)
        return 0
    except NotImplementedError as exc:
        print(f"CANDIDATE incomplete: {exc}", file=sys.stderr)
        return 2


def cmd_gold(_args: argparse.Namespace) -> int:
    stats = run_gold(db_path=DB_PATH)
    _print_stats("gold_stage", stats)
    return 0


def cmd_wap(_args: argparse.Namespace) -> int:
    try:
        ok = run_wap(db_path=DB_PATH)
        if not ok:
            print(
                "WAP gate failed closed — gold.daily_metrics left untouched",
                file=sys.stderr,
            )
            raise SystemExit(1)
        _print_stats(
            "wap",
            {"published": True, "gold_published": gold_is_published(db_path=DB_PATH)},
        )
        return 0
    except NotImplementedError as exc:
        print(f"CANDIDATE incomplete: {exc}", file=sys.stderr)
        return 2


def cmd_run(_args: argparse.Namespace) -> int:
    """Full path: land → silver → wap (stage + checks + publish)."""
    land_stats = land(db_path=DB_PATH)
    _print_stats("land", land_stats)
    try:
        silver_stats = build_silver(db_path=DB_PATH)
        _print_stats("silver", silver_stats)
    except NotImplementedError as exc:
        print(f"CANDIDATE incomplete (silver): {exc}", file=sys.stderr)
        return 2
    try:
        ok = run_wap(db_path=DB_PATH)
    except NotImplementedError as exc:
        print(f"CANDIDATE incomplete (wap): {exc}", file=sys.stderr)
        return 2
    if not ok:
        print(
            "WAP gate failed closed — gold.daily_metrics left untouched",
            file=sys.stderr,
        )
        raise SystemExit(1)
    conn = get_connection(DB_PATH)
    try:
        rows = bronze_row_count(conn)
    finally:
        conn.close()
    _print_stats(
        "run",
        {
            "bronze_rows": rows,
            "gold_published": gold_is_published(db_path=DB_PATH),
        },
    )
    return 0


def cmd_smoke(_args: argparse.Namespace) -> int:
    """Minimal path: dirs + land twice + bronze row count (idempotency signal)."""
    ensure_data_dirs()
    if DB_PATH.exists():
        DB_PATH.unlink()
    stats = land(db_path=DB_PATH)
    stats2 = land(db_path=DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        n = bronze_row_count(conn)
    finally:
        conn.close()
    result = {
        "root": str(ROOT),
        "first_land": stats,
        "second_land": stats2,
        "bronze_rows": n,
        "idempotent_row_count": stats["bronze_rows"] == stats2["bronze_rows"],
        "ok": True,
    }
    _print_stats("smoke", result)
    log_event(logger, "smoke_ok", bronze_rows=n)
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "land": cmd_land,
    "silver": cmd_silver,
    "wap": cmd_wap,
    "gold": cmd_gold,
    "run": cmd_run,
    "smoke": cmd_smoke,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="Littio DE take-home pipeline CLI (kit)",
    )
    parser.add_argument(
        "command",
        choices=sorted(COMMANDS.keys()),
        help="land | silver | wap | gold | run | smoke",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
