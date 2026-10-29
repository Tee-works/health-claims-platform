-- A rejected claim can be corrected and resubmitted under the same reference.
-- The latest resubmission is the claim's current state.
select *
from {{ ref('stg_claims') }}
qualify row_number() over (
    partition by claim_ref
    order by resubmission_no desc, submitted_on desc
) = 1
