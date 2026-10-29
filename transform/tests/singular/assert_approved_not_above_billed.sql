-- An insurer never approves more than the hospital billed.
select
    claim_ref,
    billed_amount_ngn,
    approved_amount_ngn
from {{ ref('fct_claims') }}
where approved_amount_ngn > billed_amount_ngn
