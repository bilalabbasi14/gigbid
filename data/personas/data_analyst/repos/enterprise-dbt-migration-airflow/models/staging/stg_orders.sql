-- Source: raw_orders table in BigQuery
-- Description: Standardized staging model for order data.
-- Performance: Partitioned by order_date to reduce scan costs.

with source as (

    select * from `project.dataset.raw_orders`
    where _PARTITIONTIME >= current_date() - interval 90 day

),

renamed as (

    select
        -- ids
        id as order_id,
        customer_id,
        
        -- amounts
        total_amount as order_total,
        currency_code,
        
        -- timestamps
        created_at as order_timestamp,
        updated_at as last_updated,
        
        -- status
        status as order_status

    from source

)

select * from renamed
