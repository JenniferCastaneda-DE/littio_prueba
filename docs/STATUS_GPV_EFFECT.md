# Status → GPV effect (frozen)

Do not invent additional statuses for scoring. Unknown values quarantine.

## Status table

| status | may_be_current | contributes_to_gpv | notes |
|--------|----------------|--------------------|-------|
| PENDING | yes | no | intermediate |
| COMPLETED | yes | yes (if winning) | terminal for GPV unless a later COMPLETED wins by order key |
| FAILED | yes | no | terminal non-money |
| CANCELLED | yes | no | terminal non-money |
| FAILD | quarantine `UNKNOWN_STATUS` | no | planted typo |
| other unknown | quarantine `UNKNOWN_STATUS` | no | |

## Order key

**Ascending winner = last (most recent wins):**

```text
(event_time, sequence, event_id)
```

- Apply within `transaction_id`.
- Null `event_time` **never** wins status (does not become current).
- Use `sequence` as tie-break for equal `event_time`; `event_id` as final tie-break.

## COMPLETED and GPV

- **GPV_day** = UTC date of the **winning** COMPLETED row’s `event_time` (event day, not file/ingest day).
- Only the winning COMPLETED row contributes GPV for that transaction.
- A later COMPLETED (higher order key) replaces the prior COMPLETED for current state and GPV attribution.
- Late COMPLETED that lands in a D+1 file still attributes GPV to day D when its `event_time` is on D.
- PENDING / FAILED / CANCELLED never contribute GPV even if they are current.

## Quarantine codes (exactly three)

| code | when |
|------|------|
| `NULL_PK` | missing/null `transaction_id` or `event_id` |
| `BAD_AMOUNT` | unparseable or illegal magnitude |
| `UNKNOWN_STATUS` | status not in {PENDING, COMPLETED, FAILED, CANCELLED} |

Continue-on-bad-rows: quarantine the row; process the rest.
