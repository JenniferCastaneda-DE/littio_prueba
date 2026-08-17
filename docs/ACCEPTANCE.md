# Acceptance — kit contracts

Candidate and reviewer checklists. MUST gates only.

## Candidate (before submit)

- [ ] Read `docs/SCENARIO.md` (business problem / GPV context)
- [ ] Read `docs/STATUS_GPV_EFFECT.md` and `docs/MONEY_CONTRACT.md`
- [ ] Silver grain = `transaction_id` on `silver.transactions_current`
- [ ] Order key `(event_time, sequence, event_id)`; null `event_time` never wins
- [ ] Exactly 3 quarantine codes: `NULL_PK`, `BAD_AMOUNT`, `UNKNOWN_STATUS`
- [ ] Continue-on-bad-rows (no batch die on one bad row)
- [ ] WAP: 3 checks filled (unique tx, completed magnitude, gold↔silver GPV)
- [ ] Gold: daily completed GPV by `product_type` × `currency`, no FX
- [ ] GPV_day = UTC date of winning COMPLETED `event_time`
- [ ] `docs/ARCHITECTURE.md` decision table ≤5 lines + 1-line runbook
- [ ] `make smoke` green
- [ ] `make test` green (exactly 5 kit tests)
- [ ] `make rerun-proof` green
- [ ] `make test-gate-fail` fails closed (no bad gold publish)
- [ ] No NICE work while any MUST is red

## Kit contracts (frozen — do not change)

- [ ] Status/GPV table matches kit (PENDING / COMPLETED / FAILED / CANCELLED + UNKNOWN)
- [ ] Quarantine taxonomy only the three codes above
- [ ] Planted public event_ids expected when fixtures land:
  - `evt_plant_null_pk` → `NULL_PK`
  - `evt_plant_bad_amount` → `BAD_AMOUNT`
  - `evt_plant_unknown_status` → `UNKNOWN_STATUS` (status `FAILD`)
  - `evt_late_completed_tx_A` / `evt_pending_tx_A` for late COMPLETED story
- [ ] Public partial golden day **D = 2024-06-01** (UTC)
- [ ] Event schema per `schemas/event.v1.json`
