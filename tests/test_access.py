"""Who can reach what, checked against the IAM policies Terraform deploys.

The policies are the JSON templates in infra/terraform/modules/access/policies,
rendered with test ARNs and evaluated with IAM's core rule: an explicit Deny
always wins, otherwise access needs an Allow. Conditions are treated as
satisfied, which can only overstate access, so every "cannot" asserted here
also holds in AWS.
"""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

POLICY_DIR = Path(__file__).resolve().parents[1] / "infra/terraform/modules/access/policies"
LAKE = "arn:aws:s3:::claims-test-lake"
RESULTS = "arn:aws:s3:::claims-test-athena-results"
SENSITIVE_KEY = "arn:aws:kms:af-south-1:111122223333:key/sensitive"
ANALYTICS_KEY = "arn:aws:kms:af-south-1:111122223333:key/analytics"
WG = "arn:aws:athena:af-south-1:111122223333:workgroup/claims-test-"
GLUE = "arn:aws:glue:af-south-1:111122223333:"
VARS = {
    "lake": LAKE,
    "results": RESULTS,
    "sensitive_key": SENSITIVE_KEY,
    "analytics_key": ANALYTICS_KEY,
    "analysts_workgroup": WG + "analysts",
    "engineering_workgroup": WG + "engineering",
    "catalog": GLUE + "catalog",
    "database_prefix": GLUE + "database/claims_test",
    "table_prefix": GLUE + "table/claims_test",
}


def policy(role: str) -> dict:
    text = (POLICY_DIR / f"{role}.json.tftpl").read_text()
    used = set(re.findall(r"\$\{(\w+)\}", text))
    assert used <= set(VARS), f"template uses unknown variables {used - set(VARS)}"
    return json.loads(re.sub(r"\$\{(\w+)\}", lambda m: VARS[m.group(1)], text))


def decide(role: str, action: str, resource: str) -> str:
    allowed = False
    for s in policy(role)["Statement"]:
        actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        resources = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        if any(fnmatchcase(action.lower(), a.lower()) for a in actions) and any(
            fnmatchcase(resource, r) for r in resources
        ):
            if s["Effect"] == "Deny":
                return "deny"
            allowed = True
    return "allow" if allowed else "implicit deny"


def can(role: str, action: str, resource: str) -> bool:
    return decide(role, action, resource) == "allow"


SENSITIVE_ZONES = ["landing", "raw", "quarantine", "staging", "restricted"]


@pytest.mark.parametrize("zone", SENSITIVE_ZONES)
def test_analyst_is_explicitly_denied_sensitive_zones(zone):
    assert decide("analyst", "s3:GetObject", f"{LAKE}/{zone}/claims/part.parquet") == "deny"


def test_analyst_reads_analytics_but_cannot_write_it():
    assert can("analyst", "s3:GetObject", f"{LAKE}/analytics/fct_claims/part.parquet")
    assert not can("analyst", "s3:PutObject", f"{LAKE}/analytics/fct_claims/part.parquet")


def test_analyst_cannot_use_the_sensitive_key_even_if_granted_elsewhere():
    assert decide("analyst", "kms:Decrypt", SENSITIVE_KEY) == "deny"
    assert can("analyst", "kms:Decrypt", ANALYTICS_KEY)


def test_analyst_queries_only_through_the_capped_workgroup():
    assert can("analyst", "athena:StartQueryExecution", WG + "analysts")
    assert not can("analyst", "athena:StartQueryExecution", WG + "engineering")


def test_analyst_catalog_access_is_limited_to_analytics():
    assert can("analyst", "glue:GetTable", GLUE + "table/claims_test_analytics/fct_claims")
    assert (
        decide("analyst", "glue:GetTable", GLUE + "table/claims_test_restricted/member_pii")
        == "deny"
    )


def test_ingest_writes_raw_only():
    assert can("ingest", "s3:PutObject", f"{LAKE}/raw/claims/batch.parquet")
    assert can("ingest", "s3:PutObject", f"{LAKE}/quarantine/claims/batch.parquet")
    assert not can("ingest", "s3:PutObject", f"{LAKE}/analytics/fct_claims/x.parquet")
    assert not can("ingest", "kms:Decrypt", ANALYTICS_KEY)


def test_raw_zone_is_append_only_for_transform():
    # dbt reads raw but can never change what the sources delivered.
    assert can("transform", "s3:GetObject", f"{LAKE}/raw/claims/batch.parquet")
    assert not can("transform", "s3:PutObject", f"{LAKE}/raw/claims/batch.parquet")
    assert not can("transform", "s3:DeleteObject", f"{LAKE}/raw/claims/batch.parquet")
    assert can("transform", "s3:PutObject", f"{LAKE}/restricted/member_pii/x.parquet")


def test_ml_never_sees_personal_data():
    assert can("ml", "s3:GetObject", f"{LAKE}/analytics/fct_claims/x.parquet")
    assert decide("ml", "s3:GetObject", f"{LAKE}/restricted/member_pii/x.parquet") == "deny"
    assert not can("ml", "s3:PutObject", f"{LAKE}/analytics/fct_claims/x.parquet")
    assert can("ml", "s3:PutObject", f"{LAKE}/ml/claim_risk/model.joblib")


@pytest.mark.parametrize("role", ["ingest", "transform", "analyst", "ml"])
def test_no_role_gets_wildcard_actions_or_resources(role):
    for s in policy(role)["Statement"]:
        if s["Effect"] != "Allow":
            continue
        assert not any(a in ("*", "s3:*", "kms:*") for a in s["Action"]), s["Sid"]
        if s["Resource"] == ["*"]:
            # the one action AWS does not scope to a resource
            assert s["Action"] == ["lakeformation:GetDataAccess"], s["Sid"]
