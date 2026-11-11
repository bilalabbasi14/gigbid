-- mart_churn_features.sql
-- Final feature table for churn prediction
-- One row per user with 30-day behavioral features

with

user_base as (
    select
        u.user_id,
        u.created_at,
        u.plan_tier,
        u.subscription_start_date,
        coalesce(u.last_login_at, u.created_at) as last_login_at
    from
        {{ ref('stg_users') }} u
),

login_activity as (
    select
        user_id,
        count(*) as login_count_30d,
        count(distinct date(login_at)) as active_days_30d,
        max(datediff(current_date, login_at, day)) as days_since_last_login
    from
        {{ ref('stg_user_events') }}
    where
        event_type = 'login'
        and login_at >= current_date - interval 30 day
    group by 1
),

support_tickets as (
    select
        user_id,
        count(*) as ticket_count_30d,
        count(case when status = 'unresolved' then 1 end) as unresolved_tickets
    from
        {{ ref('stg_support_tickets') }}
    where
        created_at >= current_date - interval 30 day
    group by 1
),

feature_adoption as (
    select
        user_id,
        count(distinct feature_name) as features_used_30d,
        count(case when feature_name = 'export' then 1 end) as used_export,
        count(case when feature_name = 'api_integration' then 1 end) as used_api
    from
        {{ ref('stg_feature_usage') }}
    where
        used_at >= current_date - interval 30 day
    group by 1
)

select
    ub.user_id,
    ub.plan_tier,
    ub.subscription_start_date,
    datediff(current_date, ub.subscription_start_date, day) as account_age_days,
    ub.last_login_at,
    coalesce(la.login_count_30d, 0) as login_count_30d,
    coalesce(la.active_days_30d, 0) as active_days_30d,
    coalesce(la.days_since_last_login, 999) as days_since_last_login,
    coalesce(st.ticket_count_30d, 0) as ticket_count_30d,
    coalesce(st.unresolved_tickets, 0) as unresolved_tickets,
    coalesce(fa.features_used_30d, 0) as features_used_30d,
    coalesce(fa.used_export, 0) as used_export,
    coalesce(fa.used_api, 0) as used_api
from
    user_base ub
left join login_activity la on ub.user_id = la.user_id
left join support_tickets st on ub.user_id = st.user_id
left join feature_adoption fa on ub.user_id = fa.user_id
