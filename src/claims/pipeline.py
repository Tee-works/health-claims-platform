"""Run the platform end to end, or one stage at a time.

    claims generate    synthetic source files and reference seeds
    claims ingest      landing zone -> lake (contracts, quarantine, manifest)
    claims transform   dbt build: models, contracts, tests, unit tests
    claims policy      governance rules as code (OPA) against the built platform
    claims train       train and register the claim risk model
    claims score       score current claims (refuses on drift unless --force)
    claims lineage     regenerate docs/lineage.md
    claims all         every stage in order

In production the same stages run as Airflow tasks (orchestration/airflow).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from claims.config import DBT_DIR, Paths


def _env(paths: Paths) -> None:
    os.environ.setdefault("CLAIMS_LAKE_DIR", str(paths.lake))
    os.environ.setdefault("CLAIMS_WAREHOUSE", str(paths.warehouse))


def generate(paths: Paths) -> None:
    from claims.synth import generate as make
    from claims.synth import write_landing, write_seeds

    ins = make()
    print(json.dumps(write_landing(ins, paths)))
    write_seeds(ins)


def ingest(paths: Paths) -> None:
    from claims.ingest.run import ingest as run
    from claims.ingest.run import summarise

    print(summarise(run(paths)))


def transform(paths: Paths, full_refresh: bool = False) -> None:
    # A separate process, as in production: dbt holds a write connection to the
    # warehouse while it runs, and later stages need it released.
    _env(paths)
    args = ["build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    if full_refresh:
        args.append("--full-refresh")
    cmd = [sys.executable, "-c", "from dbt.cli.main import cli; cli()", *args]
    if subprocess.run(cmd, check=False).returncode != 0:
        raise SystemExit("dbt build failed")


def policy(required: bool = True) -> None:
    import shutil

    from claims.policy import main as run

    if shutil.which("opa") is None and not required:
        print("opa not installed: skipping the policy check (CI always runs it)", file=sys.stderr)
        return
    if run([]) != 0:
        raise SystemExit("governance policy check failed")


def train(paths: Paths) -> None:
    from claims.ml.model import train as fit

    reg = fit(paths.warehouse, paths.registry, paths.truth / "claim_labels.csv")
    print(json.dumps({"version": reg.version, "metrics": reg.metadata["metrics"]}, indent=2))


def score(paths: Paths, force: bool = False) -> None:
    from claims.ml.model import score as run

    print(json.dumps(run(paths.warehouse, paths.registry, force=force), indent=2))


def lineage(paths: Paths) -> None:
    from claims.lineage import main as run

    run(["diagram"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims", description=__doc__.splitlines()[0])
    parser.add_argument(
        "stage",
        choices=["generate", "ingest", "transform", "policy", "train", "score", "lineage", "all"],
    )
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument("--force", action="store_true", help="score even if drift is detected")
    args = parser.parse_args(argv)
    paths = Paths.default()
    _env(paths)

    stages = {
        "generate": lambda: generate(paths),
        "ingest": lambda: ingest(paths),
        "transform": lambda: transform(paths, args.full_refresh),
        "policy": lambda: policy(required=args.stage == "policy"),
        "train": lambda: train(paths),
        "score": lambda: score(paths, args.force),
        "lineage": lambda: lineage(paths),
    }
    order = list(stages) if args.stage == "all" else [args.stage]
    for name in order:
        print(f"==> {name}", file=sys.stderr)
        stages[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
