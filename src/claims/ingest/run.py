"""Ingest everything new in the landing zone into the lake.

Idempotent by content: each file's SHA-256 goes into a manifest, and a file
already ingested with the same content is skipped. A hospital that re-sends a
corrected file under the same name gets a new batch, and the warehouse keeps
the latest version of each claim.

Output per source:
    lake/raw/<source>/<batch_id>.parquet          rows that passed the contract
    lake/quarantine/<source>/<batch_id>.parquet   rows that did not, with reasons

Run with:  python -m claims.ingest.run
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from trueset import split

from claims.config import SEEDS_DIR, Paths
from claims.ingest import contracts
from claims.ingest.parsers import (
    parse_claims_file,
    parse_enrolment_snapshot,
    parse_telemedicine_page,
)


@dataclass
class BatchReport:
    source: str
    file: str
    batch_id: str
    rows: int
    quarantined: int
    status: str  # loaded | skipped | rejected
    reasons: dict[str, int]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _providers() -> dict[str, tuple[str, str]]:
    """provider_code -> (provider_id, file_format), from the reference seed."""
    with (SEEDS_DIR / "providers.csv").open() as fh:
        return {
            r["provider_code"]: (r["provider_id"], r["file_format"]) for r in csv.DictReader(fh)
        }


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}

    def seen(self, rel: str, sha: str) -> bool:
        return self.entries.get(rel, {}).get("sha256") == sha

    def record(self, rel: str, sha: str, report: BatchReport) -> None:
        self.entries[rel] = {"sha256": sha, **asdict(report)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=1, sort_keys=True, default=str))


def _write(df: pd.DataFrame, folder: Path, batch_id: str) -> None:
    if df.empty:
        return
    folder.mkdir(parents=True, exist_ok=True)
    df.to_parquet(folder / f"{batch_id}.parquet", index=False)


def _ingest_file(
    paths: Paths,
    manifest: Manifest,
    source: str,
    path: Path,
    parse: Callable[[Path], pd.DataFrame],
    contract: dict,
) -> BatchReport:
    rel = str(path.relative_to(paths.landing))
    sha = _sha256(path)
    batch_id = f"{source}-{path.stem}-{sha[:10]}"
    if manifest.seen(rel, sha):
        return BatchReport(source, rel, batch_id, 0, 0, "skipped", {})

    try:
        df = parse(path)
    except (ValueError, KeyError) as exc:
        # The whole file is unusable (wrong layout, unknown sender): keep a record, load nothing.
        report = BatchReport(source, rel, batch_id, 0, 0, "rejected", {str(exc): 1})
        manifest.record(rel, sha, report)
        return report

    result = split(df, contract)
    reasons: dict[str, int] = {}
    for labels in result.reasons.values():
        for label in labels:
            reasons[label] = reasons.get(label, 0) + 1

    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    good = result.good.assign(_batch_id=batch_id, _source_file=rel, _ingested_at=loaded_at)
    bad = result.bad_annotated().assign(
        _batch_id=batch_id, _source_file=rel, _ingested_at=loaded_at
    )
    _write(good, paths.raw / source, batch_id)
    _write(bad, paths.quarantine / source, batch_id)

    report = BatchReport(source, rel, batch_id, len(df), len(bad), "loaded", reasons)
    manifest.record(rel, sha, report)
    return report


def ingest(paths: Paths | None = None) -> list[BatchReport]:
    paths = paths or Paths.default()
    manifest = Manifest(paths.manifest)
    providers = _providers()
    reports: list[BatchReport] = []

    for path in sorted((paths.landing / "claims").glob("*/*.csv")):
        code = path.parent.name
        if code not in providers:
            parse = _unknown_provider(code)
        else:
            pid, fmt = providers[code]
            parse = lambda p, pid=pid, fmt=fmt: parse_claims_file(p, fmt, pid)  # noqa: E731
        reports.append(_ingest_file(paths, manifest, "claims", path, parse, contracts.CLAIMS))

    for path in sorted((paths.landing / "telemedicine").glob("*.json")):
        reports.append(
            _ingest_file(
                paths,
                manifest,
                "consultations",
                path,
                parse_telemedicine_page,
                contracts.CONSULTATIONS,
            )
        )

    for path in sorted((paths.landing / "enrolment").glob("snapshot_date=*/members.jsonl")):
        reports.append(
            _ingest_file(
                paths, manifest, "members", path, parse_enrolment_snapshot, contracts.MEMBERS
            )
        )

    manifest.save()
    return reports


def _unknown_provider(code: str) -> Callable[[Path], pd.DataFrame]:
    def parse(_: Path) -> pd.DataFrame:
        raise ValueError(f"unknown provider folder {code!r}; not in providers seed")

    return parse


def summarise(reports: list[BatchReport]) -> str:
    by_source: dict[str, dict[str, int]] = {}
    reasons: dict[str, int] = {}
    for r in reports:
        s = by_source.setdefault(
            r.source, {"files": 0, "skipped": 0, "rejected": 0, "rows": 0, "quarantined": 0}
        )
        s["files"] += 1
        s["skipped"] += r.status == "skipped"
        s["rejected"] += r.status == "rejected"
        s["rows"] += r.rows
        s["quarantined"] += r.quarantined
        for k, v in r.reasons.items():
            reasons[f"{r.source}: {k}"] = reasons.get(f"{r.source}: {k}", 0) + v
    lines = [
        f"{src:<14} " + "  ".join(f"{k}={v}" for k, v in s.items()) for src, s in by_source.items()
    ]
    if reasons:
        lines.append("quarantine reasons:")
        lines += [f"  {k}: {v}" for k, v in sorted(reasons.items())]
    return "\n".join(lines)


def main() -> int:
    print(summarise(ingest()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
