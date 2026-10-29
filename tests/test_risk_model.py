import duckdb
import pytest

from claims.ml import drift
from claims.ml.features import FEATURES, load_features
from claims.ml.model import load_latest, train


def test_rules_plus_model_find_the_suspicious_claims(platform):
    m = platform["model"].metadata["metrics"]["rules_plus_model"]
    assert m["precision_at_k"] > 0.5 and m["lift_at_k"] > 15
    assert m["recall_in_top_2k_by_type"]["outside_coverage"] == 1.0
    assert m["recall_in_top_2k_by_type"]["duplicate_billing"] > 0.9


def test_rules_add_what_the_model_misses(platform):
    metrics = platform["model"].metadata["metrics"]
    assert metrics["rules_plus_model"]["precision_at_k"] > metrics["model_only"]["precision_at_k"]


def test_model_version_is_reproducible(platform):
    paths = platform["paths"]
    again = train(paths.warehouse, paths.registry)
    assert again.version == platform["model"].version


def test_drift_check_passes_on_training_data_and_fails_on_shifted_data(platform):
    paths = platform["paths"]
    reference = load_latest(paths.registry).metadata["drift_reference"]
    frame = load_features(paths.warehouse)
    assert max(drift.check(reference, frame).values()) < drift.WARN

    shifted = frame.copy()
    shifted["log_billed"] += 1.5  # every bill ~4.5x larger: tariffs changed, or the data did
    with pytest.raises(drift.DriftError, match="log_billed"):
        drift.check(reference, shifted)


def test_scores_are_written_without_personal_data(platform):
    with duckdb.connect(str(platform["paths"].warehouse), read_only=True) as con:
        cols = {
            c
            for (c,) in con.execute(
                "select column_name from information_schema.columns "
                "where table_name = 'claim_risk_scores'"
            ).fetchall()
        }
        n, ranks = con.execute(
            "select count(*), count(distinct risk_rank) from analytics.claim_risk_scores"
        ).fetchone()
    assert "member_id" not in cols and {"risk_score", "review_reasons", "model_version"} <= cols
    assert n == ranks == platform["scored"]["scored"]


def test_features_are_the_documented_ones():
    assert FEATURES == [
        "log_billed",
        "billed_vs_typical",
        "same_visit_claims",
        "provider_visits_month",
        "outside_coverage",
        "days_to_submit",
    ]
