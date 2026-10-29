"""Claim features for the risk model, computed from the analytics schema only.

The model never sees personal data: it reads pseudonymous member keys from
fct_claims, the same access an analyst has.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

FEATURES = [
    "log_billed",  # size of the bill
    "billed_vs_typical",  # bill relative to the median for the same diagnosis
    "same_visit_claims",  # claims for the same member, provider, day and diagnosis
    "provider_visits_month",  # member's claims at this provider in the same month
    "outside_coverage",  # service date outside the member's cover
    "days_to_submit",  # delay between service and claim
]

FEATURE_SQL = """
with claims as (
    select * from analytics.fct_claims where status <> 'rejected'
),
typical as (
    select diagnosis_code, median(billed_amount_ngn) as median_billed
    from claims group by diagnosis_code
)
select
    c.claim_ref,
    ln(greatest(c.billed_amount_ngn, 1)) as log_billed,
    c.billed_amount_ngn / nullif(t.median_billed, 0) as billed_vs_typical,
    count(*) over (
        partition by c.member_key, c.provider_id, c.service_date, c.diagnosis_code
    ) as same_visit_claims,
    count(*) over (
        partition by c.member_key, c.provider_id, c.service_month
    ) as provider_visits_month,
    case when c.is_within_coverage then 0 else 1 end as outside_coverage,
    date_diff('day', c.service_date, c.submitted_on) as days_to_submit
from claims as c
join typical as t using (diagnosis_code)
order by c.claim_ref
"""


def load_features(warehouse: Path) -> pd.DataFrame:
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        df = con.execute(FEATURE_SQL).df()
    finally:
        con.close()
    df[FEATURES] = df[FEATURES].astype(float).fillna(0.0)
    return df
