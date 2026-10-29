"""Train, version and run the claim risk model.

An isolation forest ranks claims by how unusual they are, so the claims team
reviews the strangest first. It is unsupervised: real fraud labels are rare
and late. The synthetic data carries hidden labels, which are used only to
measure how well the ranking works, never to train.

Every trained model is registered under a version derived from its training
data and parameters, with the feature list, metrics and a drift reference.
Scoring refuses to run if today's claims have drifted too far from that
reference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from claims.ml import drift
from claims.ml.features import FEATURES, load_features

PARAMS = {"n_estimators": 300, "contamination": 0.025, "random_state": 7}
MODEL_NAME = "claim_risk"


@dataclass
class Registered:
    version: str
    path: Path
    metadata: dict


def _fingerprint(frame: pd.DataFrame) -> str:
    h = hashlib.sha256(
        pd.util.hash_pandas_object(frame[["claim_ref", *FEATURES]], index=False).values.tobytes()
    )
    h.update(json.dumps(PARAMS, sort_keys=True).encode())
    return h.hexdigest()[:12]


# Known patterns are rules, not something to hope a model learns. Each hit
# lifts a claim above every unflagged claim; the model orders within groups.
RULES = {
    "outside_coverage": lambda f: f.outside_coverage > 0,
    "possible_duplicate": lambda f: f.same_visit_claims > 1,
}
RULE_WEIGHT = 10.0


def rank(frame: pd.DataFrame, model) -> pd.DataFrame:
    out = frame[["claim_ref"]].copy()
    out["model_score"] = np.round(-model.score_samples(frame[FEATURES]), 6)
    hits = pd.DataFrame({name: rule(frame) for name, rule in RULES.items()})
    out["review_reasons"] = hits.apply(lambda r: ",".join(n for n in RULES if r[n]), axis=1)
    out["risk_score"] = out.model_score + RULE_WEIGHT * hits.sum(axis=1)
    return out


def evaluate(scores: pd.DataFrame, labels_csv: Path) -> dict:
    """Precision of the top-k ranked claims against the hidden labels."""
    if not labels_csv.exists():
        return {}
    labels = pd.read_csv(labels_csv, dtype=str).fillna("")
    labels = labels[labels.anomaly != ""].drop_duplicates("claim_ref")
    ranked = scores.sort_values("risk_score", ascending=False).reset_index(drop=True)
    positives = set(labels.claim_ref) & set(ranked.claim_ref)
    if not positives:
        return {}
    k = len(positives)
    top = set(ranked.claim_ref.head(k))
    by_type = {}
    for kind, group in labels[labels.claim_ref.isin(positives)].groupby("anomaly"):
        refs = set(group.claim_ref)
        by_type[kind] = round(len(refs & set(ranked.claim_ref.head(2 * k))) / len(refs), 3)
    base_rate = k / len(ranked)
    precision = len(top & positives) / k
    return {
        "labelled_anomalies": k,
        "scored_claims": len(ranked),
        "precision_at_k": round(precision, 3),
        "base_rate": round(base_rate, 4),
        "lift_at_k": round(precision / base_rate, 1),
        "recall_in_top_2k_by_type": by_type,
    }


def train(warehouse: Path, registry: Path, labels_csv: Path | None = None) -> Registered:
    frame = load_features(warehouse)
    model = make_pipeline(StandardScaler(), IsolationForest(**PARAMS))
    model.fit(frame[FEATURES])

    version = _fingerprint(frame)
    out = registry / MODEL_NAME / version
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib")

    scores = rank(frame, model)
    model_only = scores.assign(risk_score=scores.model_score)
    metadata = {
        "model": MODEL_NAME,
        "version": version,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "training_rows": len(frame),
        "features": FEATURES,
        "params": PARAMS,
        "rules": list(RULES),
        "metrics": {
            "rules_plus_model": evaluate(scores, labels_csv),
            "model_only": evaluate(model_only, labels_csv),
        }
        if labels_csv
        else {},
        "drift_reference": drift.reference_profile(frame, FEATURES),
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (registry / MODEL_NAME / "LATEST").write_text(version)
    return Registered(version, out, metadata)


def load_latest(registry: Path) -> Registered:
    version = (registry / MODEL_NAME / "LATEST").read_text().strip()
    path = registry / MODEL_NAME / version
    return Registered(version, path, json.loads((path / "metadata.json").read_text()))


def score(warehouse: Path, registry: Path, force: bool = False) -> dict:
    """Score current claims with the latest model and write analytics.claim_risk_scores."""
    reg = load_latest(registry)
    frame = load_features(warehouse)
    psi = {} if force else drift.check(reg.metadata["drift_reference"], frame)
    model = joblib.load(reg.path / "model.joblib")
    out = rank(frame, model)
    out["risk_rank"] = out.risk_score.rank(ascending=False, method="first").astype(int)
    out["model_version"] = reg.version
    out["scored_at"] = datetime.now(UTC).replace(tzinfo=None)

    con = duckdb.connect(str(warehouse))
    try:
        con.register("scores", out)
        con.execute("create or replace table analytics.claim_risk_scores as select * from scores")
    finally:
        con.close()
    return {"model_version": reg.version, "scored": len(out), "psi": psi}
