-- One row per member per month of cover, with the premium for the plan held at
-- month end. The denominator of every per-member and loss-ratio metric.
with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('stg_member_snapshots') }}

),

months as (

    select
        m.member_id,
        m.employer_id,
        m.plan_id as current_plan_id,
        cast(unnest(generate_series(
            cast(date_trunc('month', greatest(m.enrolled_on, date '{{ var("coverage_start") }}')) as date),
            cast(date_trunc('month', coalesce(m.left_on, a.as_of_date)) as date),
            interval 1 month
        )) as date) as month
    from {{ ref('stg_members') }} as m
    cross join as_of as a
    where coalesce(m.left_on, a.as_of_date) >= date '{{ var("coverage_start") }}'

)

select
    {{ member_key('mo.member_id') }} as member_key,
    mo.month,
    mo.employer_id,
    coalesce(h.plan_id, mo.current_plan_id) as plan_id,
    pl.monthly_premium_ngn as premium_ngn
from months as mo
left join {{ ref('int_member_plan_history') }} as h
    on
        mo.member_id = h.member_id
        and last_day(mo.month) >= h.valid_from
        and last_day(mo.month) < h.valid_to
left join {{ ref('plans') }} as pl
    on coalesce(h.plan_id, mo.current_plan_id) = pl.plan_id
