# Scenario — Why this pipeline exists

## Who you are

You joined **Littio** as a **Senior Data Engineer**. Littio is a fintech: customers top up balances, transfer money, and withdraw. Every of those actions is a **transaction** that moves through a lifecycle of status events (`PENDING` → `COMPLETED` / `FAILED` / `CANCELLED`).

Product, finance, and leadership do **not** read raw events. They need a trusted daily number:

> **Gross Payment Volume (GPV)** — total completed money, by product and currency, **for each business day**.

That number must not double-count late updates, redelivered messages, or garbage rows. If it is wrong, dashboards lie and decisions go wrong.

## What just happened

Engineering already dumps lifecycle events from the payment platform into multi-day **JSONL files** under `data/raw/` (a simplified stand-in for our event bus exports). The kit ships **working bronze land code** (`pipeline.bronze.land`): it reads those JSONL files into DuckDB table `bronze.events` when you run `make smoke` / `make run`.  

**`data/bronze/` is only a reserved empty directory** (placeholder). Landed data is **not** pre-written as files there; it appears in `data/warehouse.duckdb` after smoke. You must **not** reimplement land/lineage.

Your team’s previous pipeline was fragile:

- Late `COMPLETED` events were attributed to the **ingest day**, not the day the payment actually completed.
- Re-running the job **double-counted** completed volume.
- One bad row could **kill the whole batch**, or worse, bad rows were **dropped silently**.
- Gold metrics sometimes published even when silver was inconsistent.

You are asked to replace the broken middle and gold with something a senior would ship: **correct current state per transaction**, **quarantine of poison rows**, **fail-closed publish**, and **one honest GPV metric**.

## The data you inherit

| Layer | Meaning | Who owns it here |
|-------|---------|------------------|
| **Raw JSONL** | Noisy event-bus-style dumps (duplicates, late status, typos, nulls) | Kit provides files |
| **Bronze** | Faithful land of those events + lineage | **Kit (already implemented)** |
| **Silver** | One **current** row per `transaction_id` + quarantine of bad events | **You** |
| **Gold** | Daily completed GPV by `product_type` × `currency` | **You** (SQL + checks) |

Events for the **same** transaction can arrive out of order or a day late. Example:

1. Day D file: `tx_late_A` is only `PENDING`.
2. Day D+1 file: `tx_late_A` becomes `COMPLETED` with `event_time` still on day **D**.

Finance wants that volume on **day D**, not on day D+1.

## Business rules (non-negotiable)

1. **Grain of truth:** one current status per `transaction_id` in silver.
2. **Winner rule:** among eligible events for a transaction, the winner is the last by  
   `(event_time, sequence, event_id)`. Null `event_time` never wins.
3. **GPV:** only a **winning** `COMPLETED` contributes.  
   `GPV_day` = UTC calendar date of that winning COMPLETED’s `event_time`.
4. **Poison rows** do not silently disappear and do not abort the whole run:  
   quarantine with fixed codes (`NULL_PK`, `BAD_AMOUNT`, `UNKNOWN_STATUS`) and continue.
5. **Do not publish gold** if quality checks fail (Write–Audit–Publish).
6. **Re-runs** with the same files must not change GPV; redelivery of the same `event_id` must not double-count.

Details and frozen tables: `docs/STATUS_GPV_EFFECT.md`, `docs/MONEY_CONTRACT.md`, `data/MESS_CATALOG.md`.

## What success looks like

When you are done, a teammate can:

```bash
make smoke          # environment + bronze land OK
make run            # silver → quality gate → gold
make test           # 5 proofs of money/order/quarantine/publish
make rerun-proof    # re-run and late/redelivery safe
make test-gate-fail # broken money never publishes gold
```

…and finance’s partial golden for **2024-06-01** matches your gold (including late completes attributed to that day).

You are **not** building a cloud platform, Airflow, or a full warehouse. You are owning the **money-correct path** from landed events to a publishable daily GPV under realistic mess.

## How to start (first 10 minutes)

1. Read this file + the short contracts in `docs/`.
2. Skim `data/MESS_CATALOG.md` (what’s wrong in the dumps).
3. Run `make smoke` (bronze should land).
4. Open `src/pipeline/silver.py` and implement quarantine + winner selection.
5. Then WAP checks + `sql/gold_daily_metrics.sql`.
6. Drive `make test` green; fill `docs/ARCHITECTURE.md`.
