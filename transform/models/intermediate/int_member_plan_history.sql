-- Which plan each member was on, and from when, rebuilt from monthly snapshots
-- (SCD Type 2). The first known plan is assumed to apply from enrolment.
with changes as (

    select
        member_id,
        plan_id,
        snapshot_date,
        enrolled_on,
        lag(plan_id) over (partition by member_id order by snapshot_date) as previous_plan_id
    from {{ ref('stg_member_snapshots') }}

),

starts as (

    select
        member_id,
        plan_id,
        case when previous_plan_id is null then enrolled_on else snapshot_date end as valid_from
    from changes
    where previous_plan_id is null or previous_plan_id <> plan_id

)

select
    member_id,
    plan_id,
    valid_from,
    coalesce(
        lead(valid_from) over (partition by member_id order by valid_from),
        date '9999-12-31'
    ) as valid_to
from starts
