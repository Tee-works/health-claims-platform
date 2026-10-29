-- Approved claims as a share of premium, per employer per month. The number a
-- corporate plan is renewed and priced on.
with premium as (

    select
        employer_id,
        month,
        count(*) as member_months,
        sum(premium_ngn) as premium_ngn
    from {{ ref('mart_member_months') }}
    group by employer_id, month

),

claims as (

    select
        employer_id,
        service_month as month,
        count(*) as approved_claims,
        sum(approved_amount_ngn) as approved_claims_ngn
    from {{ ref('fct_claims') }}
    where status = 'approved' and is_within_coverage
    group by employer_id, service_month

)

select
    p.employer_id,
    p.month,
    p.member_months,
    cast(p.premium_ngn as decimal(16, 2)) as premium_ngn,
    coalesce(c.approved_claims, 0) as approved_claims,
    cast(coalesce(c.approved_claims_ngn, 0) as decimal(16, 2)) as approved_claims_ngn,
    cast(round(coalesce(c.approved_claims_ngn, 0) / nullif(p.premium_ngn, 0), 4) as decimal(8, 4))
        as loss_ratio
from premium as p
left join claims as c
    on p.employer_id = c.employer_id and p.month = c.month
