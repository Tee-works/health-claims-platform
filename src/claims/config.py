"""Paths shared by every stage. Override the root with CLAIMS_DATA_DIR."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls) -> Paths:
        return cls(Path(os.environ.get("CLAIMS_DATA_DIR", REPO / "data")).resolve())

    @property
    def landing(self) -> Path:  # where sources drop files
        return self.root / "landing"

    @property
    def lake(self) -> Path:  # standardised parquet, written by ingestion
        return self.root / "lake"

    @property
    def raw(self) -> Path:
        return self.lake / "raw"

    @property
    def quarantine(self) -> Path:
        return self.lake / "quarantine"

    @property
    def manifest(self) -> Path:
        return self.lake / "_manifest.json"

    @property
    def warehouse(self) -> Path:
        return self.root / "warehouse.duckdb"

    @property
    def truth(self) -> Path:  # hidden labels, used only to evaluate the risk model
        return self.root / "truth"

    @property
    def registry(self) -> Path:
        return self.root / "registry"


MAPPINGS_DIR = REPO / "sources" / "mappings"
SEEDS_DIR = REPO / "transform" / "seeds"
DBT_DIR = REPO / "transform"
