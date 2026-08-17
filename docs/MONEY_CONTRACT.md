# Money contract (frozen)

## Magnitude

- `amount` on events is a **magnitude** (non-negative after successful parse).
- Parse from string or number. Finite, ≥ 0 after parse for legitimate COMPLETED GPV rows.
- Illegal / unparseable → quarantine `BAD_AMOUNT` (NaN, empty, non-numeric junk, non-finite).
- Kit fixtures may ship amounts as **positive magnitude** plus `product_type` (no requirement to invert signs by product).

## Signed-amount convention

- Do **not** quarantine solely because a parseable amount has a leading minus if the design treats signed withdraws via magnitude: take **abs(parsed value)** as magnitude when the value is otherwise finite and numeric.
- Prefer kit convention: positive magnitude + `product_type` ∈ {TOPUP, TRANSFER, WITHDRAWAL}.
- GPV contribution uses magnitude of the winning COMPLETED row: `abs(parse(amount))`.

## GPV_day

- **GPV_day** = UTC calendar date of the winning COMPLETED event’s `event_time`.
- Attribute late COMPLETED events to that event day, **not** the source-file / ingest day.
- Public golden day **D = 2024-06-01** (UTC).

## No FX

- One gold metric: daily completed GPV by `product_type` × `currency`.
- **No FX conversion.** Do not blend COP and USD into a single volume number.
- Currencies stay separate dimensions: COP and USD report independently.

## What counts as GPV

- Only rows that are **current silver** with status COMPLETED and a valid magnitude.
- Gold must reconcile to the silver completed set for the day (WAP check 3).
