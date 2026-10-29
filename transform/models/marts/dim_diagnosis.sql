select
    diagnosis_code,
    description,
    service_category
from {{ ref('diagnosis_codes') }}
