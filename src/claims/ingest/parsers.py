"""Turn each source's native format into one standard shape.

Parsing never raises on a bad value. An unparseable date or amount becomes
null, and the contract then quarantines the row with a reason. One bad cell
in a hospital's file should not block the other few hundred claims in it.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from claims.config import MAPPINGS_DIR

STANDARD_CLAIM_COLUMNS = [
    "claim_ref",
    "resubmission_no",
    "member_id",
    "provider_id",
    "service_date",
    "diagnosis_code",
    "service_category",
    "billed_amount_ngn",
    "approved_amount_ngn",
    "status",
    "submitted_on",
    "served_before_submission",
]


def load_mapping(fmt: str) -> dict[str, Any]:
    return yaml.safe_load((MAPPINGS_DIR / f"format_{fmt.lower()}.yaml").read_text())


def normalise_icd10(raw: Any) -> str | None:
    """'b 54' -> 'B54', 'k 3580' -> 'K35.80', 'Z00.0' -> 'Z00.0'."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    code = re.sub(r"[\s.]", "", str(raw)).upper()
    return code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"


def parse_amount(raw: Any, style: str) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    try:
        if style == "kobo":
            return int(text) / 100
        if style == "naira_text":
            negative = text.startswith("-")
            value = float(re.sub(r"[^\d.]", "", text))
            return -value if negative else value
        return float(text)
    except ValueError:
        return None


def parse_date(raw: Any, fmt: str) -> date | None:
    try:
        return datetime.strptime(str(raw).strip(), fmt).date()
    except (TypeError, ValueError):
        return None


def parse_claims_file(path: Path, fmt: str, provider_id: str) -> pd.DataFrame:
    m = load_mapping(fmt)
    df = pd.read_csv(path, sep=m["delimiter"], dtype=str, keep_default_na=False)
    missing = set(m["columns"].values()) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: expected columns missing for format {fmt}: {missing}")
    src = {std: df[col] for std, col in m["columns"].items()}
    out = pd.DataFrame(
        {
            "claim_ref": src["claim_ref"].str.strip().replace("", None),
            "resubmission_no": pd.to_numeric(src["resubmission_no"], errors="coerce")
            .fillna(0)
            .astype(int),
            "member_id": src["member_id"].str.strip().replace("", None),
            "provider_id": provider_id,
            "service_date": [parse_date(v, m["date_format"]) for v in src["service_date"]],
            "diagnosis_code": [normalise_icd10(v) for v in src["diagnosis_code"]],
            "service_category": src["service_category"].str.strip().str.lower(),
            "billed_amount_ngn": [parse_amount(v, m["amount"]) for v in src["billed_amount"]],
            "approved_amount_ngn": [parse_amount(v, m["amount"]) for v in src["approved_amount"]],
            "status": src["status"].map(m["status_map"]),
            "submitted_on": [parse_date(v, m["date_format"]) for v in src["submitted_on"]],
        }
    )
    out["served_before_submission"] = [
        bool(s and sub and s <= sub)
        for s, sub in zip(out.service_date, out.submitted_on, strict=True)
    ]
    return out[STANDARD_CLAIM_COLUMNS]


def _utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        return None


def parse_telemedicine_page(path: Path) -> pd.DataFrame:
    body = json.loads(path.read_text())
    rows = []
    for rec in body.get("data", []):
        started, ended = _utc(rec.get("started_at")), _utc(rec.get("ended_at"))
        rows.append(
            {
                "consultation_id": rec.get("consultation_id"),
                "member_id": (rec.get("member") or {}).get("id"),
                "doctor_id": (rec.get("doctor") or {}).get("id"),
                "started_at_utc": started,
                "ended_at_utc": ended,
                "diagnosis_code": normalise_icd10((rec.get("diagnosis") or {}).get("icd10")),
                "prescription_issued": bool(rec.get("prescription_issued")),
                "channel": rec.get("channel"),
                "ends_after_start": bool(started and ended and ended > started),
                "api_page": body.get("page"),
            }
        )
    # Doctor names are personal data the warehouse does not need; they are not ingested.
    return pd.DataFrame(rows)


def parse_enrolment_snapshot(path: Path) -> pd.DataFrame:
    snapshot = path.parent.name.split("=", 1)[1]
    df = pd.read_json(path, lines=True, dtype={"phone": str})
    df["snapshot_date"] = date.fromisoformat(snapshot)
    for col in ("date_of_birth", "enrolled_on", "left_on"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df
