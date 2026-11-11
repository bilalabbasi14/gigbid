-- Staging model for raw shipment events
{{ config(materialized='view') }}

WITH source AS (
    SELECT
        shipment_id,
        event_timestamp,
        event_type,
        location,
        JSON_EXTRACT_SCALAR(event_payload, '$.status') AS status
    FROM `{{ var('bq_project') }}.{{ var('bq_dataset') }}.shipment_events_raw`
)
SELECT
    shipment_id,
    MIN(event_timestamp) FILTER (WHERE event_type = 'pickup') AS pickup_time,
    MAX(event_timestamp) FILTER (WHERE event_type = 'delivery') AS delivery_time,
    status
FROM source
GROUP BY shipment_id, status
