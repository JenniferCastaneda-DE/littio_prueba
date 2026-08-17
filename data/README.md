# Data layout

Kit fixtures for the Littio Senior DE take-home (offline medallion slice).

| Path | Purpose |
|------|---------|
| `MESS_CATALOG.md` | Public mess classes, planted `event_id`s, quarantine codes, GPV notes |
| `raw/events_2024-06-01.jsonl` | Day **D** event dump (good multi-event chains + planted quarantine) |
| `raw/events_2024-06-02.jsonl` | Day **D+1**: late COMPLETED for `tx_late_A`, redelivered `event_id`, noise |
| `expected/gpv_2024-06-01.csv` | Partial public golden: `product_type,currency,gpv_day,gpv` for D |
| `fixtures/late_redelivery_delta/events_delta.jsonl` | After full run: redelivery + one late status flip (no double GPV) |
| `fixtures/gate_fail/broken_silver_seed.sql` | Reference SQL: COMPLETED + NULL amount_magnitude (WAP magnitude fail) |
| `fixtures/gate_fail/broken_events.jsonl` | Alternate broken-money events for gate-fail path |
| `bronze/.gitkeep` | Empty bronze landing dir (pipeline creates tables at runtime) |
| `warehouse.duckdb` | **Not shipped** — created at runtime (`data/warehouse.duckdb`) |

## Contracts

- Schema and status/GPV rules: repo root `KIT_CONTRACT.md`
- Golden day **D = 2024-06-01** (UTC)
- Amounts for COMPLETED GPV rows are simple integer strings (`"100.00"`, `"50.00"`, …)
- Product types: `TOPUP` \| `TRANSFER` \| `WITHDRAWAL`
- Currencies: `COP` \| `USD`

## Expected GPV day D (embedded)

| product_type | currency | gpv |
|--------------|----------|-----|
| TOPUP | COP | 340.00 |
| TOPUP | USD | 30.00 |
| TRANSFER | COP | 150.00 |
| TRANSFER | USD | 50.00 |
| WITHDRAWAL | COP | 75.00 |

See `MESS_CATALOG.md` for per-transaction breakdown (includes late COMPLETED `tx_late_A` = 100.00 TOPUP COP attributed to D).
