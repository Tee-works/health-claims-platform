-- Claims that reference a member the insurer has no record of. They pass the
-- ingestion contract (the ID is well formed) and can only be caught here.
-- Kept for provider relations to query, never silently dropped.
select
    c.claim_ref,
    c.resubmission_no,
    c.member_id,
    c.provider_id,
    c.service_date,
    c.billed_amount_ngn,
    c.source_file
from {{ ref('int_claims_latest') }} as c
left join {{ ref('stg_members') }} as m
    on c.member_id = m.member_id
where m.member_id is null
