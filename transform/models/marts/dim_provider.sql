select
    provider_id,
    provider_code,
    provider_name,
    state,
    provider_type
from {{ ref('providers') }}
