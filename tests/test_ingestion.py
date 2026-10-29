import json

import duckdb
import pandas as pd

from claims.ingest.run import ingest


def test_exactly_the_broken_rows_are_quarantined(platform):
    paths = platform["paths"]
    labels = pd.read_csv(paths.truth / "claim_labels.csv", dtype=str).fillna("")
    expected = labels[
        labels.defect.isin(
            ["missing_member", "negative_amount", "invalid_diagnosis", "future_service_date"]
        )
    ]
    quarantined = pd.read_parquet(paths.quarantine / "claims")
    assert set(quarantined.claim_ref) == set(expected.claim_ref)
    assert quarantined["_trueset_reasons"].str.len().gt(0).all()


def test_every_quarantined_row_has_a_reason_per_file(platform):
    reports = [r for r in platform["reports"] if r.source == "claims" and r.quarantined]
    assert reports and all(sum(r.reasons.values()) >= r.quarantined for r in reports)


def test_rerun_is_idempotent(platform):
    again = ingest(platform["paths"])
    assert {r.status for r in again} == {"skipped"}


def test_redelivered_file_does_not_duplicate_claims(platform):
    paths = platform["paths"]
    con = duckdb.connect(str(paths.warehouse), read_only=True)
    before = con.execute("select count(*) from staging.stg_claims").fetchone()[0]
    con.close()

    target = next((paths.landing / "claims").glob("*/*.csv"))
    target.write_text(target.read_text() + "\n")  # same rows, new bytes: a re-send
    reports = ingest(paths)
    assert [r.status for r in reports if r.file.endswith(target.name)] == ["loaded"]

    con = duckdb.connect(str(paths.warehouse), read_only=True)
    after, dupes = con.execute(
        "select count(*), count(*) - count(distinct (claim_ref, resubmission_no)) "
        "from staging.stg_claims"
    ).fetchone()
    con.close()
    assert (after, dupes) == (before, 0)


def test_unknown_provider_file_is_rejected_whole(platform):
    paths = platform["paths"]
    stray = paths.landing / "claims" / "XXNEW99" / "XXNEW99_2026-06.csv"
    stray.parent.mkdir()
    stray.write_text("claim_ref\nX\n")
    report = next(r for r in ingest(paths) if r.file.endswith(stray.name))
    assert report.status == "rejected" and report.rows == 0
    manifest = json.loads(paths.manifest.read_text())
    assert any("unknown provider" in k for k in manifest[report.file]["reasons"])
