-- Current state of each member: their row in the latest snapshot they appear in.
select *
from {{ ref('stg_member_snapshots') }}
qualify row_number() over (partition by member_id order by snapshot_date desc) = 1
