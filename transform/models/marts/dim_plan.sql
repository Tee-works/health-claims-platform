select
    plan_id,
    plan_name,
    monthly_premium_ngn,
    annual_limit_ngn
from {{ ref('plans') }}
