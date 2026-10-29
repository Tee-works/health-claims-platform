select
    employer_id,
    employer_name,
    sector
from {{ ref('employers') }}
