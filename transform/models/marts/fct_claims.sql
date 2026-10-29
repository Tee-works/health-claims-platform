-- One row per claim, current state. Incremental: each run reprocesses the last
-- 60 days of submissions, because corrected resubmissions arrive late and must
-- replace the original rather than add to it.
{{
    config(
        materialized='incremental',
        unique_key='claim_ref',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with claims as (

    select * from {{ ref('int_claims_latest') }}
    {% if is_incremental() %}
        where submitted_on >= (
            select max(previous_run.submitted_on) - to_days({{ var('incremental_lookback_days') }})
            from {{ this }} as previous_run
        )
    {% endif %}

),

members as (

    select
        member_id,
        employer_id,
        plan_id,
        enrolled_on,
        left_on
    from {{ ref('stg_members') }}

),

plan_history as (

    select * from {{ ref('int_member_plan_history') }}

)

select
    c.claim_ref,
    c.resubmission_no,
    {{ member_key('c.member_id') }} as member_key,
    c.provider_id,
    coalesce(p.plan_id, m.plan_id) as plan_id,
    m.employer_id,
    c.service_date,
    c.service_month,
    c.submitted_on,
    c.diagnosis_code,
    c.service_category,
    c.status,
    c.billed_amount_ngn,
    c.approved_amount_ngn,
    (
        c.service_date >= m.enrolled_on
        and (m.left_on is null or c.service_date <= m.left_on)
    ) as is_within_coverage,
    -- row-level lineage: the hospital file and ingestion batch this claim came from
    c.source_file,
    c.batch_id
from claims as c
-- orphaned claims (unknown member) are in int_claims_orphaned, not here
inner join members as m
    on c.member_id = m.member_id
left join plan_history as p
    on
        c.member_id = p.member_id
        and c.service_date >= p.valid_from
        and c.service_date < p.valid_to
