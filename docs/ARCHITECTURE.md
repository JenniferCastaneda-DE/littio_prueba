# Architecture handoff (candidate fill-in)

Complete this form before submission. **≤5 decision lines** + **1 runbook line**. No essays.

## Decision table (≤5 lines)

| # | Decision | Your answer |
|---|----------|-------------|
| 1 | Grain | _e.g. silver.transactions_current @ transaction_id_ |
| 2 | Order key (winner) | _e.g. (event_time, sequence, event_id); null event_time never wins_ |
| 3 | Quarantine codes (exactly 3) | _NULL_PK / BAD_AMOUNT / UNKNOWN_STATUS — when each fires_ |
| 4 | Hard-fail publish condition | _when WAP refuses gold publish_ |
| 5 | GPV day rule | _UTC date of winning COMPLETED event_time_ |

## Runbook (1 line)

**Reprocess / quarantine rule:** _______________________________________________

_(Example shape: “Re-run same files is no-op on bronze and zero GPV delta; quarantine continue-on-bad-rows; never silent-drop.”)_

## Known gap (optional, one line)

What you deliberately did not solve in 3h: _________________________________
