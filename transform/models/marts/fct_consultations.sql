select
    c.consultation_id,
    {{ member_key('c.member_id') }} as member_key,
    c.doctor_id,
    c.started_at_utc,
    c.duration_minutes,
    c.diagnosis_code,
    c.channel,
    c.prescription_issued
from {{ ref('stg_consultations') }} as c
inner join {{ ref('stg_members') }} as m
    on c.member_id = m.member_id
