import duckdb
import pytest

PII = {"member_id", "first_name", "last_name", "phone", "date_of_birth"}


@pytest.fixture(scope="module")
def con(platform):
    c = duckdb.connect(str(platform["paths"].warehouse), read_only=True)
    yield c
    c.close()


def columns(con, schema):
    return {
        (t, c)
        for t, c in con.execute(
            "select table_name, column_name from information_schema.columns where table_schema = ?",
            [schema],
        ).fetchall()
    }


def test_no_personal_data_in_the_analytics_schema(con):
    leaks = {(t, c) for t, c in columns(con, "analytics") if c in PII}
    assert not leaks


def test_personal_data_lives_only_in_restricted(con):
    assert {c for t, c in columns(con, "restricted")} >= PII


def test_orphaned_claims_are_kept_and_reported(con):
    rows = con.execute("select distinct member_id from intermediate.int_claims_orphaned").fetchall()
    assert rows == [("RH-999999",)]


def test_corrected_resubmissions_replace_originals(con):
    n, dupes = con.execute(
        "select count(*), count(*) - count(distinct claim_ref) from analytics.fct_claims"
    ).fetchone()
    resubmitted = con.execute(
        "select count(*) from analytics.fct_claims where resubmission_no > 0"
    ).fetchone()[0]
    assert dupes == 0 and resubmitted > 100


def test_loss_ratio_is_plausible_for_an_insurer(con):
    overall = con.execute(
        "select sum(approved_claims_ngn) / sum(premium_ngn) from analytics.mart_loss_ratio"
    ).fetchone()[0]
    assert 0.5 < overall < 1.0


def test_every_claim_traces_to_its_source_file(con):
    missing = con.execute(
        "select count(*) from analytics.fct_claims where source_file is null or batch_id is null"
    ).fetchone()[0]
    assert missing == 0
