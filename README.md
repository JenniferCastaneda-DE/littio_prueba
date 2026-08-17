# Littio Senior DE Take-Home — Transaction Pipeline

**Time box: 3 hours wall-clock (hard).** Stop when the clock ends.

---

## The situation (read this first)

**Littio** is a fintech. Customers **top up**, **transfer**, and **withdraw**. Each action is a **transaction** that emits **status events** over its life (`PENDING` → `COMPLETED` / `FAILED` / `CANCELLED`).

Finance and product need one trusted daily metric:

> **GPV (Gross Payment Volume)** = total **completed** money, by `product_type` and `currency`, for each **business day**.

Events do not arrive cleanly. They come as multi-day **JSONL dumps** (stand-in for event-bus exports): duplicates, **late** status updates, redelivered messages, null keys, bad amounts, and status typos.

**Bronze land code is already implemented for you** (kit-owned `src/pipeline/bronze.py`).  
`data/bronze/` is an empty placeholder folder — **not** pre-filled files. Raw events live in `data/raw/*.jsonl`. When you run `make smoke`, the kit **loads raw → DuckDB** table `bronze.events` (file `data/warehouse.duckdb`). You do **not** reimplement that step.

Your job is the path that makes money **correct and safe to publish**:

```text
data/raw/*.jsonl  →  bronze.events in DuckDB (kit; make smoke)
                  →  Silver: one true current state per transaction + quarantine bad rows
                  →  Quality gate: refuse to publish if money checks fail
                  →  Gold: daily completed GPV (the number leadership will trust)
```

### Why this exists

The previous pipeline lied under real conditions:

| Failure | Business impact |
|---------|-----------------|
| Late `COMPLETED` counted on **ingest day** | Volume jumps to the wrong day |
| Re-run / redelivery **double-counted** GPV | Inflated revenue-looking metrics |
| Bad rows **dropped** or **killed the batch** | Silent data loss or no data at all |
| Gold published without checks | Dashboards shipped wrong money |

You are the engineer who fixes that—without rebuilding cloud infra.

### What “done” means

A teammate can run the pipeline offline and:

1. See **one current row per `transaction_id`** in silver (deterministic winner under late/out-of-order events).
2. See planted poison rows in **quarantine** (not silent drop, not full abort).
3. Publish **gold GPV for 2024-06-01** matching the partial golden—including a **late COMPLETED** attributed to that day, not D+1.
4. **Re-run safely** (same files → same GPV; redelivery does not double-count).
5. **Fail closed** if quality checks fail (`make test-gate-fail`: gold stays unpublished).

Full narrative: [`docs/SCENARIO.md`](docs/SCENARIO.md).

---

## Your job (scope)

| You own | Kit already provides |
|---------|----------------------|
| Silver current-state + ordering | Bronze land + lineage |
| Quarantine predicates (3 codes) | Frozen status/GPV & money rules |
| Winner row fields for money (`amount_magnitude`, `gpv_day`) | WAP stage/publish shell |
| 3 WAP check bodies | Raw dumps, planted mess, partial golden |
| Gold GPV SQL fill-in | **5 scored tests** + 1 bronze sanity (you author **0**) |
| 5-line decision table | |

**Editable surface:** implement the `CANDIDATE` / `NotImplementedError` functions in `silver.py` and `quality.py`, and fill `sql/gold_daily_metrics.sql`. You may enrich the winner dict inside `pick_winner` (or immediately before insert if you carefully extend the stub path). **Do not reimplement bronze.** Do not require files outside this kit.

### Business rules (summary)

1. **Grain:** `transaction_id` → one current status in silver.  
2. **Winner:** last by `(event_time, sequence, event_id)`; null `event_time` never wins; null `sequence` sorts as lowest; `event_id` ascending, last wins.  
3. **Money columns on winner:** `amount_magnitude = abs(parse(amount))` (finite); for winning `COMPLETED`, `gpv_day = UTC date(event_time)`; else `gpv_day` null.  
4. **GPV:** only winning `COMPLETED`; day = that `gpv_day` (not ingest/file day).  
5. **Quarantine** `NULL_PK` (null/missing/empty `event_id` or `transaction_id`) \| `BAD_AMOUNT` (unparseable / non-finite magnitude on the event) \| `UNKNOWN_STATUS` and **continue**.  
6. **No gold publish** if checks fail.  
7. **Idempotent** re-runs; no double GPV on redelivery.

Details: `docs/STATUS_GPV_EFFECT.md`, `docs/MONEY_CONTRACT.md`, `data/MESS_CATALOG.md`.

---

## How to start (first ~10 minutes)

1. Read [`docs/SCENARIO.md`](docs/SCENARIO.md) (context) + skim contracts below.  
2. Run `make smoke` — bronze should land.  
3. Open `src/pipeline/silver.py` — implement `classify_quarantine` + `pick_winner` (including `amount_magnitude` / `gpv_day` on the winner).  
4. Fill WAP checks in `src/pipeline/quality.py` and `sql/gold_daily_metrics.sql`.  
5. Drive `make test` / `make rerun-proof` / `make test-gate-fail` green.  
6. Fill `docs/ARCHITECTURE.md` (≤5 lines).

---

## AI policy

AI tools are allowed. We score **judgment + proof**, not novel code volume or architecture blog posts.

## Scope

**There is no NICE list in this kit.** Only MUST items below are scored. Do not invent extra features, metrics, or infrastructure. If MUST is red, ship MUST—not side quests.

Money acceptance oracle: `data/expected/gpv_2024-06-01.csv` + GPV table in `data/MESS_CATALOG.md`.

## MUST (only)

1. **Silver current-state** at grain `transaction_id` (`silver.transactions_current`)
2. **Ordering** `(event_time, sequence, event_id)` within `transaction_id`; COMPLETED terminal for GPV per `docs/STATUS_GPV_EFFECT.md`
3. **Set `amount_magnitude` and `gpv_day` on the winner** (see business rules)
4. **Quarantine** exactly three codes: `NULL_PK` | `BAD_AMOUNT` | `UNKNOWN_STATUS`; continue on bad rows
5. **WAP:** fill exactly three checks in the kit shell (unique `transaction_id`, completed magnitude ≥ 0 and NOT NULL, gold GPV reconciles to silver completed set for the day)
6. **One gold metric (SQL):** daily completed GPV by `product_type` × `currency` (no FX)
7. **Decision table** ≤5 lines in `docs/ARCHITECTURE.md` + one-line reprocess/quarantine runbook rule
8. Drive the kit harness green (`make test`, `make rerun-proof`, `make test-gate-fail`)

## Contracts (read these)

| Doc | Purpose |
|-----|---------|
| [`docs/SCENARIO.md`](docs/SCENARIO.md) | **Business context & problem** |
| `docs/STATUS_GPV_EFFECT.md` | Status → GPV effect, order key |
| `docs/MONEY_CONTRACT.md` | Magnitude, GPV_day, amounts |
| `docs/ARCHITECTURE.md` | Your decision table (handoff) |
| `docs/ACCEPTANCE.md` | Contract checkboxes |
| `data/MESS_CATALOG.md` | What’s wrong in the dumps |
| `schemas/event.v1.json` | Event shape |

## Phase budget (180 minutes)

| Phase | Minutes | Work |
|-------|---------|------|
| P0 Setup & scenario | 10 | Read scenario, `make smoke`, skim contracts |
| P1 Bronze | 0 | Pre-baked — do not rebuild ingest |
| P2 Silver + quarantine | **80** | Current-state grain, ordering, 3 codes — **core** |
| P3 WAP + gold SQL | 35 | 3 checks + thin GPV SQL |
| P4 Proofs + handoff | 30 | Green harness + decision table |
| Buffer | 25 | Golden mismatches, debug, re-runs |

Live debrief is **after** submission (20 minutes); not inside the 180.

## Make targets

```bash
make smoke          # venv/deps + bronze land
make test           # 5 scored tests + 1 bronze sanity (scored tests fail until you implement)
make rerun-proof    # bronze no-op + zero GPV delta; late/redelivery no double GPV
make test-gate-fail # broken fixture → no gold publish
make run            # silver → WAP → gold on public data
```

Stack: Python 3.11+, DuckDB, pytest. Local only — no VPN, AWS, or Airflow.

## End-to-end path

```
raw JSONL → bronze (kit) → silver (you) → quarantine (you)
  → WAP stage/checks/publish (kit shell + your 3 checks) → gold SQL (you)
  → make test / rerun-proof / test-gate-fail
```

## Submission

Ship a runnable offline tree: green MUST targets, filled decision table, your silver/quarantine/WAP/gold changes. Incomplete NICE is fine. Red MUST is not.
