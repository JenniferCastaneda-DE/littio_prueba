"""Test 5 — Public partial GPV day matches expected CSV.

Compares gold.daily_metrics for D=2024-06-01 against data/expected/gpv_2024-06-01.csv.
Includes ≥1 late COMPLETED attributed to event day D (not ingest day D+1).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from tests.conftest import (
    GOLDEN_DAY,
    gpv_for_day,
    reset_db,
    run_full_pipeline,
)


def _norm_key(product_type: str, currency: str) -> tuple[str, str]:
    return (str(product_type).strip().upper(), str(currency).strip().upper())


def _load_expected(path: Path) -> dict[tuple[str, str], float]:
    """Load expected GPV keyed by (product_type, currency)."""
    out: dict[tuple[str, str], float] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames, f"empty or headerless expected CSV: {path}"
        fields = {h.strip().lower(): h for h in reader.fieldnames}

        def col(*names: str) -> str:
            for n in names:
                if n in fields:
                    return fields[n]
            raise AssertionError(
                f"expected CSV {path} missing columns {names}; has {reader.fieldnames}"
            )

        pt_c = col("product_type", "product")
        cur_c = col("currency", "ccy")
        gpv_c = col("gpv", "gpv_amount", "completed_gpv", "amount")

        for row in reader:
            # Optional day filter if present (kit CSV: gpv_day)
            day_key = None
            for cand in ("gpv_day", "metric_date", "day", "date"):
                if cand in fields:
                    day_key = fields[cand]
                    break
            if day_key is not None:
                day_val = str(row[day_key]).strip()[:10]
                if day_val and day_val != GOLDEN_DAY:
                    continue
            key = _norm_key(row[pt_c], row[cur_c])
            out[key] = out.get(key, 0.0) + float(row[gpv_c])
    return out


def _load_actual(db_path: Path) -> dict[tuple[str, str], float]:
    rows = gpv_for_day(db_path, GOLDEN_DAY)
    out: dict[tuple[str, str], float] = defaultdict(float)
    if not rows:
        return {}
    # Infer product_type / currency / gpv column names from first row keys
    sample = {str(k).lower(): k for k in rows[0].keys()}
    pt_k = sample.get("product_type") or sample.get("product")
    cur_k = sample.get("currency") or sample.get("ccy")
    # Prefer kit DDL column gpv_amount; accept aliases for candidate variance.
    gpv_k = (
        sample.get("gpv_amount")
        or sample.get("gpv")
        or sample.get("completed_gpv")
        or sample.get("amount")
    )
    assert pt_k and cur_k and gpv_k, (
        f"gold.daily_metrics row keys unexpected: {list(rows[0].keys())}"
    )
    for r in rows:
        key = _norm_key(r[pt_k], r[cur_k])
        out[key] += float(r[gpv_k] or 0)
    return dict(out)


def test_public_gpv_day_matches_expected(
    db_path: Path,
    raw_dir: Path,
    expected_gpv_csv: Path,
) -> None:
    assert raw_dir.exists(), f"missing public raw dir: {raw_dir}"
    assert expected_gpv_csv.exists(), (
        f"missing expected golden CSV: {expected_gpv_csv}"
    )

    reset_db(db_path)
    run_full_pipeline(db_path, raw_dir=raw_dir)

    expected = _load_expected(expected_gpv_csv)
    actual = _load_actual(db_path)

    assert expected, f"expected CSV parsed empty: {expected_gpv_csv}"

    # Compare multiset of (product_type, currency) → gpv
    exp_keys = set(expected)
    act_keys = set(actual)
    missing = exp_keys - act_keys
    extra = act_keys - exp_keys
    mismatches: list[str] = []

    for k in sorted(exp_keys & act_keys):
        if abs(expected[k] - actual[k]) > 1e-6:
            mismatches.append(
                f"{k}: expected={expected[k]}, actual={actual[k]}"
            )

    assert not missing and not extra and not mismatches, (
        f"public GPV day {GOLDEN_DAY} mismatch vs {expected_gpv_csv.name}.\n"
        f"  missing keys: {sorted(missing)}\n"
        f"  extra keys: {sorted(extra)}\n"
        f"  value mismatches: {mismatches}\n"
        "Late COMPLETED must attribute to event-time UTC day D, not ingest day D+1."
    )
