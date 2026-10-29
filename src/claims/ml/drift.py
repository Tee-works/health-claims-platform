"""Population stability index: has the data the model scores moved away from
the data it was trained on?

PSI below 0.1 is stable, 0.1 to 0.25 is worth a look, above 0.25 means the
model's view of "normal" no longer fits and scores should not be trusted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WARN = 0.10
FAIL = 0.25


class DriftError(RuntimeError):
    pass


def reference_bins(values: pd.Series, n_bins: int = 10) -> list[float]:
    """Interior bin edges at the training data's deciles."""
    qs = np.quantile(values.to_numpy(dtype=float), np.linspace(0, 1, n_bins + 1)[1:-1])
    return sorted(set(float(q) for q in qs))


def _shares(values: np.ndarray, edges: list[float]) -> np.ndarray:
    idx = np.searchsorted(edges, values, side="right")
    counts = np.bincount(idx, minlength=len(edges) + 1).astype(float)
    return np.clip(counts / max(len(values), 1), 1e-4, None)


def psi(reference: dict, current: pd.Series, edges: list[float]) -> float:
    expected = np.array(reference["shares"])
    actual = _shares(current.to_numpy(dtype=float), edges)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def reference_profile(frame: pd.DataFrame, features: list[str]) -> dict:
    profile = {}
    for f in features:
        edges = reference_bins(frame[f])
        profile[f] = {
            "edges": edges,
            "shares": _shares(frame[f].to_numpy(dtype=float), edges).tolist(),
        }
    return profile


def check(profile: dict, frame: pd.DataFrame) -> dict[str, float]:
    """PSI per feature. Raises DriftError if any feature crosses the fail threshold."""
    scores = {f: round(psi(p, frame[f], p["edges"]), 4) for f, p in profile.items()}
    failed = {f: s for f, s in scores.items() if s > FAIL}
    if failed:
        raise DriftError(f"feature drift above {FAIL}: {failed}")
    return scores
