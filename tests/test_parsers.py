"""Every hospital format must parse to the same standard rows."""

import csv
from datetime import date

import pytest

from claims.ingest.parsers import normalise_icd10, parse_amount, parse_claims_file
from claims.synth import _HEADERS, _STATUS, _fmt_amount, _fmt_date, _fmt_dx


@pytest.mark.parametrize(
    "raw, code",
    [
        ("b 54", "B54"),
        ("k 3580", "K35.80"),
        ("Z00.0", "Z00.0"),
        ("j069", "J06.9"),
        ("I10", "I10"),
        (None, None),
    ],
)
def test_icd10_normalisation(raw, code):
    assert normalise_icd10(raw) == code


@pytest.mark.parametrize(
    "raw, style, value",
    [
        ("12345.50", "plain", 12345.5),
        ("N1,234,567.00", "naira_text", 1234567.0),
        ("-N2,500.00", "naira_text", -2500.0),
        ("1234500", "kobo", 12345.0),
        ("", "plain", None),
        ("abc", "kobo", None),
    ],
)
def test_amount_parsing(raw, style, value):
    assert parse_amount(raw, style) == value


ROWS = [
    (
        "LAIKE01-2025-000001",
        0,
        "RH-000123",
        date(2025, 3, 4),
        "K35.80",
        "surgery",
        845250.0,
        800000.0,
        "approved",
        date(2025, 3, 20),
    ),
    (
        "LAIKE01-2025-000002",
        1,
        "RH-000456",
        date(2025, 3, 9),
        "B54",
        "outpatient",
        18000.0,
        None,
        "pending",
        date(2025, 4, 2),
    ),
]


@pytest.mark.parametrize("fmt", ["A", "B", "C"])
def test_all_formats_parse_to_identical_rows(tmp_path, fmt):
    path = tmp_path / f"claims_{fmt}.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter=";" if fmt == "C" else ",")
        w.writerow(_HEADERS[fmt])
        for ref, resub, member, svc, dx, cat, billed, approved, status, sub in ROWS:
            w.writerow(
                [
                    ref,
                    resub,
                    member,
                    _fmt_date(svc, fmt),
                    _fmt_dx(dx, fmt),
                    cat,
                    _fmt_amount(billed, fmt),
                    _fmt_amount(approved, fmt),
                    _STATUS[fmt][status],
                    _fmt_date(sub, fmt),
                ]
            )
    df = parse_claims_file(path, fmt, "PRV001")
    got = [
        (
            r.claim_ref,
            r.resubmission_no,
            r.member_id,
            r.service_date,
            r.diagnosis_code,
            r.service_category,
            r.billed_amount_ngn,
            None if r.approved_amount_ngn != r.approved_amount_ngn else r.approved_amount_ngn,
            r.status,
            r.submitted_on,
        )
        for r in df.itertuples()
    ]
    assert got == ROWS
    assert df.served_before_submission.all()


def test_layout_change_is_rejected_not_misread(tmp_path):
    path = tmp_path / "renamed.csv"
    path.write_text("Claim Ref,Member\nX,RH-000001\n")
    with pytest.raises(ValueError, match="expected columns missing"):
        parse_claims_file(path, "B", "PRV001")
