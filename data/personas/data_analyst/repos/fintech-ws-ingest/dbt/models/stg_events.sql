{{
  config(
    materialized='incremental',
    partition_by={'field': 'event_date', 'data_type': 'date'},
    cluster_by=['product_id']
  )
}}

WITH source AS (
  SELECT
    CAST(_PARTITIONTIME AS DATE) AS event_date,
    CAST(JSON_EXTRACT_SCALAR(data, '$.event_id') AS STRING) AS event_id,
    CAST(JSON_EXTRACT_SCALAR(data, '$.product_id') AS STRING) AS product_id,
    CAST(JSON_EXTRACT_SCALAR(data, '$.amount') AS FLOAT64) AS amount,
    CAST(JSON_EXTRACT_SCALAR(data, '$.currency') AS STRING) AS currency,
    CAST(JSON_EXTRACT_SCALAR(data, '$.event_timestamp') AS TIMESTAMP) AS event_timestamp
  FROM {{ source('raw', 'events') }}
  {% if is_incremental() %}
    WHERE event_timestamp > (SELECT MAX(event_timestamp) FROM {{ this }})
  {% endif %}
)

SELECT * FROM source
