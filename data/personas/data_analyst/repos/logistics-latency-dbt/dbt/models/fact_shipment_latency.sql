-- Fact model calculating delivery latency
{{ config(materialized='table') }}

WITH staged AS (
    SELECT * FROM {{ ref('stg_shipment_events') }}
    WHERE pickup_time IS NOT NULL AND delivery_time IS NOT NULL
)
SELECT
    shipment_id,
    pickup_time,
    delivery_time,
    TIMESTAMP_DIFF(delivery_time, pickup_time, MINUTE) AS delivery_delay_minutes,
    CASE WHEN TIMESTAMP_DIFF(delivery_time, pickup_time, MINUTE) > 60 THEN TRUE ELSE FALSE END AS is_late,
    CURRENT_DATE() AS report_date
FROM staged
