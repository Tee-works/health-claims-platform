"""Synthetic data for a health insurer that runs a network of partner hospitals and clinics.

Everything is generated from a seed: members, employers, plans, providers,
claims and telemedicine consultations. What is realistic is how the data
arrives, because that is where a data platform earns its keep:

- every hospital sends a monthly claims file, in one of three house formats
  (different column names, date formats, comma or semicolon delimiters,
  amounts as "N12,345.00" strings or as integer kobo, status as words or
  single letters, ICD-10 codes written "b 54" instead of "B54")
- rejected claims come back as resubmissions under the same reference
- a small share of rows is broken (missing member, negative amount, invalid
  diagnosis code, service date in the future) and some reference members
  the insurer has never heard of
- the telemedicine API pages overlap, so the same consultation arrives twice
- membership arrives as monthly snapshots in which members change plan or leave

On top of that, a few claims are deliberately suspicious (upcoding,
duplicate billing, care after cover ended, implausible visit frequency).
Their labels are written to data/truth/ and never loaded into the
warehouse; they exist only to measure the risk model.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from claims.config import SEEDS_DIR, Paths

PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2026, 6, 30)
SNAPSHOT_DATES = [date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)]


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    monthly_premium_ngn: int
    annual_limit_ngn: int
    visits_per_month: float  # expected encounters per member per month


PLANS = [
    Plan("P-BRZ", "Bronze", 7_000, 300_000, 0.22),
    Plan("P-SLV", "Silver", 14_000, 750_000, 0.30),
    Plan("P-GLD", "Gold", 28_000, 2_000_000, 0.38),
    Plan("P-PLT", "Platinum", 52_000, 5_000_000, 0.45),
]

# diagnosis -> (description, service category, billed range in NGN)
DIAGNOSES: dict[str, tuple[str, str, tuple[int, int]]] = {
    "B54": ("Malaria, unspecified", "outpatient", (12_000, 45_000)),
    "J06.9": ("Upper respiratory infection", "outpatient", (8_000, 25_000)),
    "I10": ("Essential hypertension", "outpatient", (10_000, 30_000)),
    "E11.9": ("Type 2 diabetes without complications", "outpatient", (15_000, 40_000)),
    "A09": ("Gastroenteritis", "outpatient", (9_000, 28_000)),
    "N39.0": ("Urinary tract infection", "laboratory", (6_000, 22_000)),
    "M54.5": ("Low back pain", "imaging", (18_000, 85_000)),
    "Z00.0": ("General medical examination", "laboratory", (10_000, 35_000)),
    "A01.0": ("Typhoid fever", "inpatient", (120_000, 450_000)),
    "O80": ("Single spontaneous delivery", "maternity", (250_000, 800_000)),
    "K35.80": ("Acute appendicitis", "surgery", (450_000, 1_500_000)),
    "R50.9": ("Fever, unspecified", "pharmacy", (3_000, 18_000)),
}
DIAGNOSIS_WEIGHTS = [24, 18, 10, 7, 9, 6, 5, 8, 4, 2, 1, 6]

STATES = ["Lagos", "FCT", "Rivers"]
AREAS = {
    "Lagos": ["Ikeja", "Lekki", "Surulere", "Yaba", "Gbagada", "Ajah", "Ikoyi", "Festac"],
    "FCT": ["Wuse", "Garki", "Maitama", "Gwarinpa"],
    "Rivers": ["GRA", "Trans-Amadi", "Rumuola"],
}
PROVIDER_KINDS = [
    ("partner_hospital", "Specialist Hospital"),
    ("partner_hospital", "Medical Centre"),
    ("network_clinic", "Family Clinic"),
    ("pharmacy", "Pharmacy"),
]
FIRST = [
    "Adaeze",
    "Chinedu",
    "Tunde",
    "Fatima",
    "Ibrahim",
    "Ngozi",
    "Emeka",
    "Aisha",
    "Segun",
    "Bisi",
    "Kemi",
    "Yusuf",
    "Zainab",
    "Obinna",
    "Funmi",
    "Musa",
    "Halima",
    "Ifeoma",
    "Tobi",
    "Uche",
    "Amina",
    "Femi",
    "Nneka",
    "Sani",
    "Yetunde",
    "Kunle",
    "Chiamaka",
    "Mariam",
    "Dayo",
]
LAST = [
    "Okafor",
    "Adeyemi",
    "Bello",
    "Okeke",
    "Balogun",
    "Abubakar",
    "Eze",
    "Ogunleye",
    "Mohammed",
    "Nwosu",
    "Lawal",
    "Ibe",
    "Adewale",
    "Usman",
    "Chukwu",
    "Afolabi",
    "Yakubu",
    "Onyeka",
    "Salami",
    "Danjuma",
]
SECTORS = ["banking", "telecoms", "logistics", "manufacturing", "fintech", "oil and gas", "retail"]
EMPLOYER_WORDS = [
    "Harbour",
    "Crest",
    "Meridian",
    "Savanna",
    "Atlantic",
    "Summit",
    "Delta",
    "Pinnacle",
    "Lagoon",
    "Northstar",
    "Baobab",
    "Kestrel",
    "Ember",
    "Riverside",
]


@dataclass(frozen=True)
class Employer:
    employer_id: str
    name: str
    sector: str
    plan_id: str
    headcount: int


@dataclass(frozen=True)
class Member:
    member_id: str
    first_name: str
    last_name: str
    gender: str
    date_of_birth: date
    phone: str
    state: str
    employer_id: str
    plan_id: str
    enrolled_on: date
    left_on: date | None


@dataclass(frozen=True)
class Provider:
    provider_id: str
    code: str
    name: str
    state: str
    provider_type: str
    file_format: str
    tariff_factor: float


@dataclass(frozen=True)
class Claim:
    claim_ref: str
    resubmission_no: int
    member_id: str | None
    provider_id: str
    service_date: date
    diagnosis_code: str
    service_category: str
    billed_amount: float
    approved_amount: float | None
    status: str  # approved | rejected | pending
    submitted_on: date
    anomaly: str | None = None
    defect: str | None = None


@dataclass(frozen=True)
class Consultation:
    consultation_id: str
    member_id: str
    doctor_id: str
    doctor_name: str
    started_at: datetime
    ended_at: datetime
    icd10: str
    prescription_issued: bool
    channel: str


@dataclass
class Insurer:
    seed: int
    plans: list[Plan]
    employers: list[Employer]
    members: list[Member]
    plan_history: dict[str, list[tuple[date, str]]]  # member -> [(snapshot_date, plan_id)]
    providers: list[Provider]
    claims: list[Claim]
    consultations: list[Consultation]


def _months(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _money(x: float) -> float:
    return round(x / 50) * 50.0  # hospitals bill in round-ish naira amounts


def generate(seed: int = 2026, n_employers: int = 22) -> Insurer:
    rng = random.Random(seed)

    employers = []
    for i in range(n_employers):
        name = (
            f"{rng.choice(EMPLOYER_WORDS)} {rng.choice(['Group', 'Holdings', 'Ltd', 'Partners'])}"
        )
        employers.append(
            Employer(
                f"E{i + 1:03d}",
                name,
                rng.choice(SECTORS),
                rng.choices([p.plan_id for p in PLANS], weights=[3, 4, 3, 1])[0],
                rng.randint(15, 160),
            )
        )

    members: list[Member] = []
    for emp in employers:
        state = rng.choice(STATES)
        for _ in range(emp.headcount):
            enrolled = PERIOD_START - timedelta(days=200) + timedelta(days=rng.randint(0, 680))
            left = None
            if rng.random() < 0.12:
                left = enrolled + timedelta(days=rng.randint(60, 400))
                left = left if left < PERIOD_END else None
            members.append(
                Member(
                    member_id=f"RH-{len(members) + 1:06d}",
                    first_name=rng.choice(FIRST),
                    last_name=rng.choice(LAST),
                    gender=rng.choice(["F", "M"]),
                    date_of_birth=date(
                        rng.randint(1962, 2004), rng.randint(1, 12), rng.randint(1, 28)
                    ),
                    phone=f"+234{rng.choice(['803', '806', '813', '816', '703', '810'])}"
                    f"{rng.randint(1_000_000, 9_999_999)}",
                    state=state if rng.random() < 0.85 else rng.choice(STATES),
                    employer_id=emp.employer_id,
                    plan_id=emp.plan_id,
                    enrolled_on=enrolled,
                    left_on=left,
                )
            )

    # Some members move up a plan between snapshots.
    plan_history: dict[str, list[tuple[date, str]]] = {}
    plan_order = [p.plan_id for p in PLANS]
    for i, m in enumerate(members):
        plan = m.plan_id
        history = []
        for snap in SNAPSHOT_DATES:
            if snap != SNAPSHOT_DATES[0] and rng.random() < 0.04 and plan != plan_order[-1]:
                plan = plan_order[plan_order.index(plan) + 1]
            history.append((snap, plan))
        plan_history[m.member_id] = history
        members[i] = replace(m, plan_id=plan)

    providers = []
    for state in STATES:
        for area in AREAS[state]:
            ptype, kind = rng.choice(PROVIDER_KINDS)
            code = f"{state[:2].upper()}{area[:3].upper()}{len(providers) + 1:02d}"
            providers.append(
                Provider(
                    f"PRV{len(providers) + 1:03d}",
                    code,
                    f"{area} {kind}",
                    state,
                    ptype,
                    rng.choice(["A", "B", "C"]),
                    round(rng.uniform(0.9, 1.25), 2),
                )
            )
    by_state = defaultdict(list)
    for p in providers:
        by_state[p.state].append(p)

    claims: list[Claim] = []
    counters: dict[str, int] = defaultdict(int)
    plan_by_id = {p.plan_id: p for p in PLANS}
    codes = list(DIAGNOSES)

    def new_ref(provider: Provider, on: date) -> str:
        counters[provider.code] += 1
        return f"{provider.code}-{on.year}-{counters[provider.code]:06d}"

    def make_claim(m: Member, prov: Provider, on: date, dx: str, anomaly=None) -> Claim:
        _, category, (lo, hi) = DIAGNOSES[dx]
        billed = _money(rng.uniform(lo, hi) * prov.tariff_factor)
        r = rng.random()
        if r < 0.06:
            status, approved = "rejected", 0.0
        elif r < 0.09:
            status, approved = "pending", None
        else:
            status, approved = "approved", _money(billed * rng.uniform(0.85, 1.0))
        return Claim(
            new_ref(prov, on),
            0,
            m.member_id,
            prov.provider_id,
            on,
            dx,
            category,
            billed,
            approved,
            status,
            on + timedelta(days=rng.randint(3, 40)),
            anomaly,
        )

    for m in members:
        lam = plan_by_id[m.plan_id].visits_per_month
        for month in _months(max(PERIOD_START, m.enrolled_on), PERIOD_END):
            for _ in range(_poisson(rng, lam)):
                day = month + timedelta(days=rng.randint(0, 27))
                if day < m.enrolled_on or (m.left_on and day > m.left_on) or day > PERIOD_END:
                    continue
                prov = rng.choice(by_state[m.state] if rng.random() < 0.9 else providers)
                dx = rng.choices(codes, weights=DIAGNOSIS_WEIGHTS)[0]
                claims.append(make_claim(m, prov, day, dx))

    # Rejected claims are often corrected and resubmitted under the same reference.
    for c in [c for c in claims if c.status == "rejected"]:
        if rng.random() < 0.45:
            approved = _money(c.billed_amount * rng.uniform(0.85, 1.0))
            claims.append(
                replace(
                    c,
                    resubmission_no=1,
                    status="approved",
                    approved_amount=approved,
                    submitted_on=c.submitted_on + timedelta(days=rng.randint(20, 50)),
                )
            )

    # ---- suspicious claims (labelled in data/truth, never loaded) --------------------------
    base = [c for c in claims if c.resubmission_no == 0 and c.status == "approved"]
    for c in rng.sample(base, k=len(base) // 120):  # upcoding
        billed = _money(c.billed_amount * rng.uniform(3.0, 6.0))
        claims[claims.index(c)] = replace(
            c, billed_amount=billed, approved_amount=_money(billed * 0.95), anomaly="upcoding"
        )
    prov_by_id = {p.provider_id: p for p in providers}
    for c in rng.sample(base, k=len(base) // 150):  # same visit billed twice
        prov = prov_by_id[c.provider_id]
        claims.append(
            replace(
                c,
                claim_ref=new_ref(prov, c.service_date),
                submitted_on=c.submitted_on + timedelta(days=rng.randint(1, 10)),
                anomaly="duplicate_billing",
            )
        )
    leavers = [m for m in members if m.left_on and m.left_on < PERIOD_END - timedelta(days=45)]
    for m in rng.sample(leavers, k=min(25, len(leavers))):  # care after cover ended
        day = m.left_on + timedelta(days=rng.randint(5, 40))
        prov = rng.choice(by_state[m.state])
        claims.append(make_claim(m, prov, day, rng.choice(codes[:6]), anomaly="outside_coverage"))
    for m in rng.sample(members, k=6):  # one provider, many visits in a month
        prov = rng.choice(by_state[m.state])
        month = rng.choice(_months(max(PERIOD_START, m.enrolled_on), PERIOD_END - timedelta(30)))
        for _ in range(rng.randint(8, 12)):
            day = month + timedelta(days=rng.randint(0, 27))
            if m.left_on and day > m.left_on:
                continue
            claims.append(
                make_claim(
                    m, prov, day, rng.choice(["J06.9", "B54", "R50.9"]), anomaly="frequency_abuse"
                )
            )

    # ---- broken rows (should be quarantined at ingestion) ---------------------------------
    defects = []
    for c in rng.sample(claims, k=len(claims) // 160):
        kind = rng.choice(
            [
                "missing_member",
                "negative_amount",
                "invalid_diagnosis",
                "future_service_date",
                "unknown_member",
            ]
        )
        if kind == "missing_member":
            defects.append(replace(c, member_id=None, defect=kind, anomaly=None))
        elif kind == "negative_amount":
            defects.append(replace(c, billed_amount=-c.billed_amount, defect=kind, anomaly=None))
        elif kind == "invalid_diagnosis":
            defects.append(replace(c, diagnosis_code="XYZ", defect=kind, anomaly=None))
        elif kind == "future_service_date":
            defects.append(replace(c, service_date=date(2027, 1, 15), defect=kind, anomaly=None))
        else:
            defects.append(replace(c, member_id="RH-999999", defect=kind, anomaly=None))
    for d in defects:
        claims[
            claims.index(
                next(
                    c
                    for c in claims
                    if c.claim_ref == d.claim_ref and c.resubmission_no == d.resubmission_no
                )
            )
        ] = d

    consultations = []
    doctors = [(f"DR{i:03d}", f"Dr {rng.choice(FIRST)} {rng.choice(LAST)}") for i in range(1, 19)]
    for m in rng.sample(members, k=len(members) // 2):
        for _ in range(rng.randint(1, 4)):
            start = datetime.combine(
                max(m.enrolled_on, PERIOD_START) + timedelta(days=rng.randint(0, 300)),
                datetime.min.time(),
            ) + timedelta(hours=rng.randint(7, 21), minutes=rng.randint(0, 59))
            if start.date() > PERIOD_END or (m.left_on and start.date() > m.left_on):
                continue
            doc = rng.choice(doctors)
            consultations.append(
                Consultation(
                    f"TC-{len(consultations) + 1:07d}",
                    m.member_id,
                    doc[0],
                    doc[1],
                    start,
                    start + timedelta(minutes=rng.randint(6, 35)),
                    rng.choice(codes[:8] + ["R50.9"]),
                    rng.random() < 0.55,
                    rng.choice(["video", "chat", "phone"]),
                )
            )

    return Insurer(seed, PLANS, employers, members, plan_history, providers, claims, consultations)


# ---- writing the landing zone ---------------------------------------------------------------


def _fmt_date(d: date, fmt: str) -> str:
    return {"A": d.isoformat(), "B": d.strftime("%d/%m/%Y"), "C": d.strftime("%Y%m%d")}[fmt]


def _fmt_amount(x: float | None, fmt: str) -> str:
    if x is None:
        return ""
    if fmt == "B":
        sign = "-" if x < 0 else ""
        return f"{sign}N{abs(x):,.2f}"
    if fmt == "C":
        return str(int(round(x * 100)))  # kobo
    return f"{x:.2f}"


def _fmt_dx(code: str, fmt: str) -> str:
    if fmt == "C":  # lower case, a space after the letter, dots dropped
        return f"{code[0].lower()} {code[1:].replace('.', '')}"
    return code


_HEADERS = {
    "A": [
        "claim_ref",
        "resubmission_no",
        "member_id",
        "service_date",
        "icd10",
        "service_category",
        "billed_amount",
        "approved_amount",
        "status",
        "submitted_on",
    ],
    "B": [
        "Claim Reference",
        "Resubmission",
        "Member ID",
        "Date of Service",
        "Diagnosis",
        "Category",
        "Amount Billed",
        "Amount Approved",
        "Claim Status",
        "Date Submitted",
    ],
    "C": [
        "ref",
        "resub",
        "enrollee_no",
        "svc_dt",
        "dx",
        "cat",
        "billed_kobo",
        "approved_kobo",
        "st",
        "submitted",
    ],
}
_STATUS = {
    "A": {"approved": "approved", "rejected": "rejected", "pending": "pending"},
    "B": {"approved": "Approved", "rejected": "Rejected", "pending": "Pending Review"},
    "C": {"approved": "A", "rejected": "R", "pending": "P"},
}


def write_landing(ins: Insurer, paths: Paths) -> dict[str, int]:
    """Write source files the way each source would deliver them."""
    paths.landing.mkdir(parents=True, exist_ok=True)
    providers = {p.provider_id: p for p in ins.providers}

    files: dict[Path, list[list[str]]] = defaultdict(list)
    for c in ins.claims:
        prov = providers[c.provider_id]
        f = prov.file_format
        month = c.submitted_on.strftime("%Y-%m")
        path = paths.landing / "claims" / prov.code / f"{prov.code}_{month}.csv"
        files[path].append(
            [
                c.claim_ref,
                str(c.resubmission_no),
                c.member_id or "",
                _fmt_date(c.service_date, f),
                _fmt_dx(c.diagnosis_code, f),
                c.service_category,
                _fmt_amount(c.billed_amount, f),
                _fmt_amount(c.approved_amount, f),
                _STATUS[f][c.status],
                _fmt_date(c.submitted_on, f),
            ]
        )
    for path, rows in files.items():
        fmt = providers[next(p for p in providers if providers[p].code == path.parent.name)]
        fmt = fmt.file_format
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";" if fmt == "C" else ",")
            w.writerow(_HEADERS[fmt])
            w.writerows(rows)

    # Telemedicine API: pages of 250 that overlap by 5 records.
    tele = paths.landing / "telemedicine"
    tele.mkdir(parents=True, exist_ok=True)
    records = sorted(ins.consultations, key=lambda c: c.started_at)
    page, i, size, overlap = 1, 0, 250, 5
    while i < len(records):
        chunk = records[max(0, i - overlap) if page > 1 else 0 : i + size]
        body = {
            "page": page,
            "next_page": page + 1 if i + size < len(records) else None,
            "data": [
                {
                    "consultation_id": c.consultation_id,
                    "member": {"id": c.member_id},
                    "doctor": {"id": c.doctor_id, "name": c.doctor_name},
                    "started_at": c.started_at.isoformat() + "+01:00",
                    "ended_at": c.ended_at.isoformat() + "+01:00",
                    "diagnosis": {"icd10": c.icd10},
                    "prescription_issued": c.prescription_issued,
                    "channel": c.channel,
                }
                for c in chunk
            ],
        }
        (tele / f"consultations_page_{page:04d}.json").write_text(json.dumps(body))
        i += size
        page += 1

    # Membership: monthly JSONL snapshots, PII included (the source system holds it).
    member_by_id = {m.member_id: m for m in ins.members}
    for snap_i, snap in enumerate(SNAPSHOT_DATES):
        out = paths.landing / "enrolment" / f"snapshot_date={snap.isoformat()}" / "members.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as fh:
            for mid, history in ins.plan_history.items():
                m = member_by_id[mid]
                if m.enrolled_on > snap:
                    continue
                rec = asdict(m)
                rec["plan_id"] = history[snap_i][1]
                rec["left_on"] = m.left_on.isoformat() if m.left_on and m.left_on <= snap else None
                rec["date_of_birth"] = m.date_of_birth.isoformat()
                rec["enrolled_on"] = m.enrolled_on.isoformat()
                fh.write(json.dumps(rec) + "\n")

    # Hidden labels for the risk model; never ingested.
    paths.truth.mkdir(parents=True, exist_ok=True)
    with (paths.truth / "claim_labels.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["claim_ref", "resubmission_no", "anomaly", "defect"])
        for c in ins.claims:
            if c.anomaly or c.defect:
                w.writerow([c.claim_ref, c.resubmission_no, c.anomaly or "", c.defect or ""])

    return {
        "claim_files": len(files),
        "claim_rows": len(ins.claims),
        "telemedicine_pages": page - 1,
        "members": len(ins.members),
    }


def write_seeds(ins: Insurer, seeds_dir: Path = SEEDS_DIR) -> None:
    """Reference data the warehouse joins to. Committed, so dbt seeds are reviewable."""
    seeds_dir.mkdir(parents=True, exist_ok=True)
    with (seeds_dir / "plans.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plan_id", "plan_name", "monthly_premium_ngn", "annual_limit_ngn"])
        for p in ins.plans:
            w.writerow([p.plan_id, p.name, p.monthly_premium_ngn, p.annual_limit_ngn])
    with (seeds_dir / "providers.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "provider_id",
                "provider_code",
                "provider_name",
                "state",
                "provider_type",
                "file_format",
            ]
        )
        for p in ins.providers:
            w.writerow([p.provider_id, p.code, p.name, p.state, p.provider_type, p.file_format])
    with (seeds_dir / "employers.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["employer_id", "employer_name", "sector"])
        for e in ins.employers:
            w.writerow([e.employer_id, e.name, e.sector])
    with (seeds_dir / "diagnosis_codes.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["diagnosis_code", "description", "service_category"])
        for code, (desc, cat, _) in DIAGNOSES.items():
            w.writerow([code, desc, cat])
