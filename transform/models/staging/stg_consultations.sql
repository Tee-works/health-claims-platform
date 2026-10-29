-- The API returns overlapping pages; keep the first copy of each consultation.
with source as (

    select * from {{ source('lake', 'consultations') }}

)

select
    consultation_id,
    member_id,
    doctor_id,
    started_at_utc,
    ended_at_utc,
    date_diff('minute', started_at_utc, ended_at_utc) as duration_minutes,
    diagnosis_code,
    channel,
    prescription_issued
from source
qualify row_number() over (partition by consultation_id order by api_page) = 1
