"""Data contracts applied at ingestion, one TrueSet suite per source.

Rows that break a contract are not dropped. They go to the quarantine area
with the reasons attached, so the provider-relations team can send them back
to the hospital, and the counts are reported per file.
"""

from __future__ import annotations

ICD10 = r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$"
MEMBER_ID = r"^RH-[0-9]{6}$"

CLAIMS = {
    "suite": "claims_contract",
    "checks": [
        {"type": "not_null", "column": "claim_ref"},
        {"type": "not_null", "column": "member_id"},
        {"type": "matches_regex", "column": "member_id", "pattern": MEMBER_ID},
        {"type": "not_null", "column": "service_date"},
        {"type": "not_null", "column": "billed_amount_ngn"},
        {"type": "in_range", "column": "billed_amount_ngn", "min": 0},
        {"type": "in_range", "column": "approved_amount_ngn", "min": 0},
        {"type": "matches_regex", "column": "diagnosis_code", "pattern": ICD10},
        {"type": "in_set", "column": "status", "values": ["approved", "rejected", "pending"]},
        # a service cannot be dated after the claim for it was submitted
        {"type": "in_set", "column": "served_before_submission", "values": [True]},
    ],
}

CONSULTATIONS = {
    "suite": "telemedicine_contract",
    "checks": [
        {"type": "not_null", "column": "consultation_id"},
        {"type": "not_null", "column": "member_id"},
        {"type": "matches_regex", "column": "member_id", "pattern": MEMBER_ID},
        {"type": "not_null", "column": "started_at_utc"},
        {"type": "matches_regex", "column": "diagnosis_code", "pattern": ICD10},
        {"type": "in_set", "column": "channel", "values": ["video", "chat", "phone"]},
        {"type": "in_set", "column": "ends_after_start", "values": [True]},
    ],
}

MEMBERS = {
    "suite": "enrolment_contract",
    "checks": [
        {"type": "unique", "column": "member_id"},
        {"type": "matches_regex", "column": "member_id", "pattern": MEMBER_ID},
        {"type": "not_null", "column": "plan_id"},
        {"type": "not_null", "column": "enrolled_on"},
        {"type": "in_set", "column": "gender", "values": ["F", "M"]},
        {"type": "matches_regex", "column": "phone", "pattern": r"^\+234[0-9]{10}$"},
    ],
}
