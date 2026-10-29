-- One row per (claim_ref, resubmission_no). If a hospital re-sends a corrected
-- file, the most recently ingested version of each row wins.
with source as (

    select * from {{ source('lake', 'claims') }}

),

latest_delivery as (

    select
        *,
        row_number() over (
            partition by claim_ref, resubmission_no
            order by _ingested_at desc, _batch_id desc
        ) as delivery_rank
    from source

)

select
    claim_ref,
    cast(resubmission_no as integer) as resubmission_no,
    member_id,
    provider_id,
    cast(service_date as date) as service_date,
    cast(date_trunc('month', cast(service_date as date)) as date) as service_month,
    diagnosis_code,
    service_category,
    cast(billed_amount_ngn as decimal(14, 2)) as billed_amount_ngn,
    cast(approved_amount_ngn as decimal(14, 2)) as approved_amount_ngn,
    status,
    cast(submitted_on as date) as submitted_on,
    _batch_id as batch_id,
    _source_file as source_file
from latest_delivery
where delivery_rank = 1
