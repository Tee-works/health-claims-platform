"""
### Claims platform orchestration

Four DAGs, chained by data rather than by clock (Airflow Datasets):

1. `claims_ingest` every two hours: new files in the landing zone -> raw zone.
2. `claims_transform` whenever raw changes: `dbt build` (models, contracts, tests).
3. `claims_risk_scoring` whenever the marts change: score claims. Refuses to
   score if the inputs have drifted from the training data, and the failure
   alerts the on-call engineer instead of shipping untrustworthy scores.
4. `claims_risk_retrain` weekly: retrain and register a new model version.

Imports of project code happen inside the callables, so the scheduler can
parse this file without the platform's dependencies installed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

LAKE = os.environ.get("CLAIMS_LAKE_URI", "s3://claims-prod-lake")
RAW = Dataset(f"{LAKE}/raw/")
ANALYTICS = Dataset(f"{LAKE}/analytics/")
DBT_DIR = os.environ.get("CLAIMS_DBT_DIR", "/opt/claims/transform")

DEFAULTS = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def _ingest() -> None:
    from claims.ingest.run import ingest, summarise

    reports = ingest()
    print(summarise(reports))
    rejected = [r.file for r in reports if r.status == "rejected"]
    if rejected:
        # Loaded files are kept; a rejected file needs a human to talk to the hospital.
        raise RuntimeError(f"files rejected at ingestion: {rejected}")


def _score() -> None:
    from claims.config import Paths
    from claims.ml.model import score

    paths = Paths.default()
    print(score(paths.warehouse, paths.registry))


def _train() -> None:
    from claims.config import Paths
    from claims.ml.model import train

    paths = Paths.default()
    print(train(paths.warehouse, paths.registry).version)


with DAG(
    dag_id="claims_ingest",
    schedule="0 */2 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULTS,
    tags=["claims", "ingestion"],
    doc_md=__doc__,
):
    PythonOperator(task_id="ingest_landing_zone", python_callable=_ingest, outlets=[RAW])

with DAG(
    dag_id="claims_transform",
    schedule=[RAW],
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULTS,
    tags=["claims", "dbt"],
):
    build = BashOperator(
        task_id="dbt_build",
        bash_command=f"dbt build --project-dir {DBT_DIR} --profiles-dir {DBT_DIR} --target prod",
        outlets=[ANALYTICS],
    )
    lineage = BashOperator(
        task_id="publish_lineage",
        bash_command="python -m claims.lineage diagram",
    )
    build >> lineage

with DAG(
    dag_id="claims_risk_scoring",
    schedule=[ANALYTICS],
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={**DEFAULTS, "retries": 0},  # drift is not transient; do not retry it
    tags=["claims", "ml"],
):
    PythonOperator(task_id="score_claims", python_callable=_score)

with DAG(
    dag_id="claims_risk_retrain",
    schedule="0 3 * * 1",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULTS,
    tags=["claims", "ml"],
):
    PythonOperator(task_id="train_and_register", python_callable=_train)
