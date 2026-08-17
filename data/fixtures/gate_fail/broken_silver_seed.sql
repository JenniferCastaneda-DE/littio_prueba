-- Gate-fail seed (reference SQL): forces WAP check_completed_magnitude to fail.
-- Primary harness path: tests.conftest.seed_gate_fail_silver / make_runners.
-- Matches silver.transactions_current DDL in pipeline.silver.ensure_silver_tables.
--
-- Note: transaction_id is PRIMARY KEY, so duplicate-row uniqueness cannot be
-- planted via INSERT. Kit tests plant NULL amount_magnitude on a COMPLETED row.

DELETE FROM silver.transactions_current
WHERE transaction_id = 'tx_gate_null_amount';

INSERT INTO silver.transactions_current (
    transaction_id,
    event_id,
    status,
    product_type,
    currency,
    amount_magnitude,
    event_time,
    sequence,
    gpv_day,
    updated_at
) VALUES (
    'tx_gate_null_amount',
    'evt_gate_null_amount',
    'COMPLETED',
    'TRANSFER',
    'USD',
    NULL,
    '2024-06-01T11:00:00Z',
    1,
    DATE '2024-06-01',
    CURRENT_TIMESTAMP
);
