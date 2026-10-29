-- Every naira of approved, in-cover claims must land in the loss-ratio mart.
with mart as (

    select sum(approved_claims_ngn) as total from {{ ref('mart_loss_ratio') }}

),

source as (

    select sum(approved_amount_ngn) as total
    from {{ ref('fct_claims') }}
    where
        status = 'approved'
        and is_within_coverage
        and service_month >= date '{{ var("coverage_start") }}'

)

select
    mart.total as mart_total,
    source.total as claims_total
from mart cross join source
where abs(coalesce(mart.total, 0) - coalesce(source.total, 0)) > 0.01
