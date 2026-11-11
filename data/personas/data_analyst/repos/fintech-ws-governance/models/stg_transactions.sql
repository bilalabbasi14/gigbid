/*
  Staging model for raw transaction data.
  Includes basic cleaning and type casting.
*/

with source as (
    select
        cast(transaction_id as string) as transaction_id,
        cast(amount as numeric) as amount,
        cast(timestamp as timestamp) as ts,
        user_id
    from {{ source('raw', 'transactions') }}
)

select
    transaction_id,
    amount,
    ts,
    user_id,
    case when amount < 0 then 'refund' else 'sale' end as transaction_type
from source
where amount is not null
