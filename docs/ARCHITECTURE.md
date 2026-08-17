# Architecture handoff (candidate fill-in)

Complete this form before submission. **≤5 decision lines** + **1 runbook line**. No essays.

## Decision table (≤5 lines)

| # | Decision | Your answer |
|---|----------|-------------|
| 1 | Grain | `silver.transactions_current` @ `transaction_id`; full DELETE+rebuild from `bronze.events` on every `build_silver` call (idempotent by construction, not incremental) |
| 2 | Order key (winner) | ascending `(event_time, sequence, event_id)`, last wins; null `event_time` ranked below any real timestamp so it can never win; null `sequence` sorts lowest |
| 3 | Quarantine codes (exactly 3) | `NULL_PK` if `transaction_id` or `event_id` missing/empty; `BAD_AMOUNT` if `amount` doesn't parse to a finite float; `UNKNOWN_STATUS` if `status` ∉ {PENDING, COMPLETED, FAILED, CANCELLED} — checked in that order, row still processed (continue-on-bad-rows) |
| 4 | Hard-fail publish condition | any of the 3 WAP checks raises (dup `transaction_id`, NULL/negative `amount_magnitude` on a COMPLETED winner, or stage gold ≠ silver COMPLETED set) → `run_wap` returns `False`, `gold.daily_metrics` left untouched |
| 5 | GPV day rule | UTC calendar date of the **winning** COMPLETED row's `event_time`, set on the winner during `pick_winner` and carried straight into the gold SQL — never the ingest/file day |

## Runbook (1 line)

**Reprocess / quarantine rule:** Re-landing the same files is a bronze no-op (upsert by `event_id`) and silver is fully rebuilt from bronze on every run, so re-runs and redelivery produce zero GPV delta; bad rows are quarantined with a fixed code and the batch continues — never silently dropped, never aborted.

## Known gap (optional, one line)

Silver rebuild is full-table (not incremental/partitioned), fine at this data volume but would need a windowed/merge strategy at production scale; no FX or cross-currency GPV blending was attempted (out of scope per contract).
