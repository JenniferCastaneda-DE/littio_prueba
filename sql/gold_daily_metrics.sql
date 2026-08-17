-- Gold: daily completed GPV by product_type × currency
-- Grain: (gpv_day, product_type, currency)
-- Source: silver.transactions_current (winning row per transaction_id)
--
-- CANDIDATE TODO:
--   1. Filter to COMPLETED winners only (status = 'COMPLETED')
--   2. GPV_day = UTC date of winning COMPLETED event_time
--      (prefer silver.gpv_day if you set it in build_silver; else CAST/DATE from event_time)
--   3. gpv_amount = SUM(amount_magnitude)  -- magnitude ≥ 0 after silver
--   4. GROUP BY gpv_day, product_type, currency
--
-- Kit executes this as a SELECT inserted into stage.gold_daily_metrics.
-- Skeleton returns zero rows until TODOs are filled (WHERE 1 = 0).

SELECT
    gpv_day,
    product_type,
    currency,
    SUM(amount_magnitude) AS gpv_amount
FROM silver.transactions_current
WHERE status = 'COMPLETED'
  AND gpv_day IS NOT NULL
GROUP BY 1, 2, 3
;
