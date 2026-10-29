"""One end-to-end build shared by the tests: generate, ingest, dbt build, train, score."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from claims.config import DBT_DIR, Paths


def dbt(*args: str) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-c",
        "from dbt.cli.main import cli; cli()",
        *args,
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


@pytest.fixture(scope="session")
def platform(tmp_path_factory):
    paths = Paths(tmp_path_factory.mktemp("platform"))
    os.environ["CLAIMS_LAKE_DIR"] = str(paths.lake)
    os.environ["CLAIMS_WAREHOUSE"] = str(paths.warehouse)

    from claims.ingest.run import ingest
    from claims.ml.model import score, train
    from claims.synth import generate, write_landing, write_seeds

    insurer = generate()
    write_landing(insurer, paths)
    write_seeds(insurer)
    reports = ingest(paths)
    build = dbt("build")
    assert build.returncode == 0, build.stdout[-3000:]
    registered = train(paths.warehouse, paths.registry, paths.truth / "claim_labels.csv")
    scored = score(paths.warehouse, paths.registry)
    return {
        "paths": paths,
        "insurer": insurer,
        "reports": reports,
        "model": registered,
        "scored": scored,
    }
