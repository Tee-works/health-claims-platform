"""Governance as code: the OPA policies run against the real build, and catch a broken one.

The Rego rules have their own unit tests (`opa test policies`); these tests
check the input document built from dbt's manifest and the warehouse, and that
the policies pass on the platform as built and fail when it is broken.
"""

import copy
import json
import re
import shutil
import subprocess

import pytest

from claims.config import DBT_DIR, REPO
from claims.policy import POLICY_DIR, build_input, evaluate

needs_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa is not installed")


@pytest.fixture(scope="module")
def document(platform):
    return build_input(DBT_DIR / "target" / "manifest.json", platform["paths"].warehouse)


def model(document, name):
    return next(m for m in document["models"] if m["name"] == name)


def test_personal_column_list_matches_the_sql_guard():
    """One classification: the OPA policy and the dbt test must agree on what is personal data."""
    in_policy = set(
        json.loads((POLICY_DIR / "data.json").read_text())["classification"]["personal_columns"]
    )
    sql = (REPO / "transform/tests/singular/assert_no_personal_data_in_analytics.sql").read_text()
    in_sql = set(re.search(r"'\^\((.*?)\)\$'", sql).group(1).split("|"))
    assert in_policy == in_sql


def test_input_uses_the_columns_the_warehouse_really_has(document):
    assert "first_name" in model(document, "member_pii")["columns"]
    assert "member_key" in model(document, "dim_member")["columns"]
    assert "first_name" not in model(document, "dim_member")["columns"]


def test_input_carries_zones_owners_contracts_and_lineage(document):
    fct = model(document, "fct_claims")
    assert fct["zone"] == "analytics" and fct["owner"] and fct["contract_enforced"]
    assert {p["name"] for p in model(document, "member_pii")["parents"]} == {"stg_members"}
    members = next(s for s in document["sources"] if s["name"] == "lake.members")
    assert members["contains_pii"]
    report = next(e for e in document["exposures"] if e["name"] == "employer_loss_ratio_report")
    assert report["maturity"] == "high"
    assert all(p["contract_enforced"] for p in report["parents"])


@needs_opa
def test_rego_unit_tests_pass():
    result = subprocess.run(
        ["opa", "test", str(POLICY_DIR)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@needs_opa
def test_the_platform_as_built_complies(document):
    assert evaluate(document) == []


@needs_opa
def test_a_broken_platform_is_denied(document):
    broken = copy.deepcopy(document)
    pii = model(broken, "member_pii")
    leaky = model(broken, "dim_member")
    leaky["parents"].append(
        {k: pii[k] for k in ("id", "name", "kind", "zone", "contract_enforced")}
    )
    leaky["columns"].append("phone")
    model(broken, "mart_loss_ratio")["owner"] = ""
    violations = evaluate(broken)
    assert any("dim_member (analytics) reads restricted model member_pii" in v for v in violations)
    assert any("analytics.dim_member has personal-data column phone" in v for v in violations)
    assert any("analytics.mart_loss_ratio has no owner" in v for v in violations)
