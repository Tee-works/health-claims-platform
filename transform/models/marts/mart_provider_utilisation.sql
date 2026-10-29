select
    provider_id,
    service_month as month,
    count(*) as claims,
    count(distinct member_key) as members_served,
    sum(billed_amount_ngn) as billed_ngn,
    sum(approved_amount_ngn) as approved_ngn,
    round(avg(case when status = 'rejected' then 1.0 else 0.0 end), 4) as rejection_rate,
    sum(case when not is_within_coverage then 1 else 0 end) as claims_outside_coverage
from {{ ref('fct_claims') }}
group by provider_id, service_month
