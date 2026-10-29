-- The only table that links a pseudonymous member_key back to a person.
-- Lives in the restricted schema; analysts have no grant on it. Claims and
-- customer-care tooling use it through the transform role when they must.
select
    member_id,
    {{ member_key('member_id') }} as member_key,
    first_name,
    last_name,
    phone,
    date_of_birth
from {{ ref('stg_members') }}
