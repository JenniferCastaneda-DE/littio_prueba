# Mess catalog (public)

Measured quirks and **planted** failure rows in the public raw dumps.

**Context first:** read [`docs/SCENARIO.md`](../docs/SCENARIO.md) — you are building a trustworthy daily **GPV** from noisy transaction lifecycle events. This catalog lists how the dumps misbehave.

Candidates must quarantine with the **exact three codes** below and continue on bad rows.

Golden day **D = 2024-06-01** (UTC). Day **D+1 = 2024-06-02**.

---

## Event ordering (silver winner)

Within each `transaction_id`, ascending order key:

```text
(event_time, sequence, event_id)
```

**Last** event after sort is the current-state winner.

| Rule | Behavior |
|------|----------|
| Null `event_time` | **Never wins** — demote / ignore for winner selection (do not quarantine solely for null time unless PK/amount/status rules fire) |
| Same `event_time` | Higher `sequence` wins; if still tied, higher `event_id` (lexicographic) wins |
| Redelivered `event_id` | Same event must not produce double GPV (idempotent apply / dedupe by `event_id` at bronze or silver) |
| Late COMPLETED | `GPV_day` = UTC date of **winning** COMPLETED `event_time`, not file / ingest day |

---

## Quarantine codes (exactly 3)

| Code | Predicate | Planted `event_id` |
|------|-----------|--------------------|
| `NULL_PK` | missing/null `transaction_id` or `event_id` | `evt_plant_null_pk` |
| `BAD_AMOUNT` | unparseable / illegal magnitude (`"not-a-number"`, empty, NaN junk) | `evt_plant_bad_amount` |
| `UNKNOWN_STATUS` | status not in `{PENDING, COMPLETED, FAILED, CANCELLED}` | `evt_plant_unknown_status` (status `FAILD`) |

Continue-on-bad-rows: quarantine the bad event; process remaining good events.

---

## Planted public event_ids

| `event_id` | File | Intent | Expected |
|------------|------|--------|----------|
| `evt_plant_null_pk` | `raw/events_2024-06-01.jsonl` | `transaction_id` is JSON `null` | quarantine `NULL_PK` |
| `evt_plant_bad_amount` | `raw/events_2024-06-01.jsonl` | `amount` = `"not-a-number"` | quarantine `BAD_AMOUNT` |
| `evt_plant_unknown_status` | `raw/events_2024-06-01.jsonl` | `status` = `"FAILD"` (typo) | quarantine `UNKNOWN_STATUS` |
| `evt_pending_tx_A` | `raw/events_2024-06-01.jsonl` | PENDING for `tx_late_A` on day D | silver current may be PENDING until late COMPLETED |
| `evt_late_completed_tx_A` | `raw/events_2024-06-02.jsonl` | COMPLETED for `tx_late_A` with **`event_time` on D** | contributes GPV to **2024-06-01**, not D+1 |

---

## Public mess classes (taxonomy)

These are the only mess classes the public set exercises. Hidden interviewer set uses the **same** classes only.

### 1. Multi-event lifecycle (good)
Several transactions have PENDING then COMPLETED (or single-shot COMPLETED). Winner is last by order key; only winning COMPLETED contributes GPV.

### 2. Late COMPLETED (event day ≠ file day)
- `tx_late_A`: PENDING in D file; COMPLETED (`evt_late_completed_tx_A`) in D+1 file with `event_time` still on D.
- Expected: GPV attributes to **2024-06-01**.

### 3. Redelivered `event_id`
- D+1 file re-emits `evt_completed_tx_topup_cop_1` (identical `event_id` already in D).
- Expected: no double GPV for that transaction.

### 4. Tie-break (`sequence`)
- `tx_tiebreak_1`: two events same `event_time` (`2024-06-01T15:00:00Z`), `sequence` 1 = PENDING, `sequence` 2 = COMPLETED amount `"40.00"`.
- Expected: COMPLETED wins → GPV TOPUP/COP includes `40.00`.

### 5. Null `event_time` never wins
- `tx_null_time_1`:
  - `evt_null_time_completed_tx_null_time_1`: COMPLETED, amount `"999.00"`, **`event_time`: null** — must **not** become current and must **not** contribute GPV.
  - `evt_real_time_pending_tx_null_time_1`: PENDING with real `event_time` — wins current state.
- Expected: current = PENDING; **no GPV** from the 999 row (optional: do not quarantine null time alone).

### 6. Terminal non-money
- `tx_failed_cop_1` ends FAILED; `tx_cancelled_usd_1` ends CANCELLED — may be current; **no GPV**.

### 7. Planted quarantine (see table above)
Three planted rows with exact codes. Good rows in the same files must still publish.

### 8. Late / redelivery delta fixture
`fixtures/late_redelivery_delta/events_delta.jsonl` applied **after** a full run on raw/:
- Redelivery of an already-applied `event_id` (`evt_completed_tx_topup_cop_1`) → **must not** double GPV.
- Late COMPLETED for `tx_pending_only_B` (`evt_delta_completed_tx_pending_only_B`) with `event_time` on D → GPV TOPUP/USD may increase by `60.00` **once**.

### 9. Gate-fail fixture
`fixtures/gate_fail/` forces WAP checks to fail (duplicate `transaction_id` and/or null COMPLETED magnitude). Used only by `make test-gate-fail` / kit gate-fail path — not part of the happy-path golden day.

---

## GPV rows contributing to public golden day D

Winning COMPLETED with `event_time` date = `2024-06-01`:

| `transaction_id` | product_type | currency | amount | Notes |
|------------------|--------------|----------|--------|-------|
| `tx_topup_cop_1` | TOPUP | COP | 200.00 | multi-event on D |
| `tx_late_A` | TOPUP | COP | 100.00 | late COMPLETED in D+1 file |
| `tx_tiebreak_1` | TOPUP | COP | 40.00 | sequence tie-break |
| `tx_topup_usd_1` | TOPUP | USD | 30.00 | single COMPLETED on D |
| `tx_transfer_cop_1` | TRANSFER | COP | 150.00 | single COMPLETED on D |
| `tx_transfer_usd_1` | TRANSFER | USD | 50.00 | single COMPLETED on D |
| `tx_withdrawal_cop_1` | WITHDRAWAL | COP | 75.00 | multi-event on D |

**Aggregates** → `expected/gpv_2024-06-01.csv`:

| product_type | currency | gpv |
|--------------|----------|-----|
| TOPUP | COP | 340.00 |
| TOPUP | USD | 30.00 |
| TRANSFER | COP | 150.00 |
| TRANSFER | USD | 50.00 |
| WITHDRAWAL | COP | 75.00 |

---

## Non-GPV / control transactions (sanity)

| `transaction_id` | Expected current | GPV on D |
|------------------|------------------|----------|
| `tx_null_time_1` | PENDING (null-time COMPLETED demoted) | none |
| `tx_failed_cop_1` | FAILED | none |
| `tx_cancelled_usd_1` | CANCELLED | none |
| `tx_pending_only_B` | PENDING until delta fixture | none on base run |

---

## Source files map

| Path | Role |
|------|------|
| `raw/events_2024-06-01.jsonl` | Day D dump |
| `raw/events_2024-06-02.jsonl` | Day D+1: late COMPLETED + redelivery + noise |
| `expected/gpv_2024-06-01.csv` | Partial public golden for day D |
| `fixtures/late_redelivery_delta/events_delta.jsonl` | Post-run redelivery + late flip |
| `fixtures/gate_fail/broken_silver_seed.sql` | Reference seed: COMPLETED + NULL `amount_magnitude` (WAP magnitude fail-closed) |
| `fixtures/gate_fail/broken_events.jsonl` | Alternate broken-money event dump |
