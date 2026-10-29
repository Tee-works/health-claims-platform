-- Members without personal data. Analysts join on member_key; names, phone
-- numbers and dates of birth stay in restricted.member_pii.
with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('stg_member_snapshots') }}

),

members as (

    select
        m.*,
        date_diff('year', m.date_of_birth, a.as_of_date) as age
    from {{ ref('stg_members') }} as m
    cross join as_of as a

)

select
    {{ member_key('member_id') }} as member_key,
    gender,
    case
        when age < 25 then '18-24'
        when age < 35 then '25-34'
        when age < 45 then '35-44'
        when age < 55 then '45-54'
        else '55+'
    end as age_band,
    state,
    employer_id,
    plan_id,
    enrolled_on,
    left_on,
    left_on is null as is_active
from members
