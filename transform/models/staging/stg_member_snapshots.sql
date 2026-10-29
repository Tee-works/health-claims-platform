-- Every membership snapshot, as delivered. Contains personal data: restricted.
select
    member_id,
    cast(snapshot_date as date) as snapshot_date,
    first_name,
    last_name,
    gender,
    cast(date_of_birth as date) as date_of_birth,
    phone,
    state,
    employer_id,
    plan_id,
    cast(enrolled_on as date) as enrolled_on,
    cast(left_on as date) as left_on
from {{ source('lake', 'members') }}
