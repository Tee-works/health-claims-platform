"""Governance as code: check the built platform against the OPA policies in policies/.

    python -m claims.policy            build the input and evaluate it (fails on any violation)
    python -m claims.policy --dump     print the input document instead

The input comes from what was actually built, not from what the YAML claims:
dbt's manifest gives every model's zone, owner, contract and lineage, and the
warehouse catalogue gives the columns each table really has. The rules
themselves live in policies/dataflow.rego, with their tests beside them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from claims.config import DBT_DIR, REPO

POLICY_DIR = REPO / "policies"
QUERY = "data.dataflow.deny"


def _meta(node: dict) -> dict:
    return {**node.get("meta", {}), **node.get("config", {}).get("meta", {})}


def _columns(warehouse: Path) -> dict[tuple[str, str], list[str]]:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        rows = con.execute(
            "select table_schema, table_name, column_name from information_schema.columns "
            "order by table_schema, table_name, ordinal_position"
        ).fetchall()
    out: dict[tuple[str, str], list[str]] = {}
    for schema, table, column in rows:
        out.setdefault((schema, table), []).append(column)
    return out


def build_input(manifest_path: Path, warehouse: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    columns = _columns(warehouse)
    refs: dict[str, dict] = {}

    for uid, src in manifest["sources"].items():
        name = f"{src['source_name']}.{src['name']}"
        refs[uid] = {
            "id": f"source:{name}",
            "name": name,
            "kind": "source",
            "zone": "source",
            "contains_pii": bool(_meta(src).get("contains_pii", False)),
        }
    for uid, node in manifest["nodes"].items():
        if node["resource_type"] == "seed":
            refs[uid] = {
                "id": f"seed:{node['name']}",
                "name": node["name"],
                "kind": "seed",
                "zone": "reference",
            }
        elif node["resource_type"] == "model":
            zone = node["config"].get("schema") or node["schema"]
            refs[uid] = {
                "id": f"model:{node['name']}",
                "name": node["name"],
                "kind": "model",
                "zone": zone,
                "owner": str(_meta(node).get("owner") or ""),
                "description": (node.get("description") or "").strip(),
                "contract_enforced": bool(node["config"].get("contract", {}).get("enforced")),
                "contains_pii": bool(_meta(node).get("contains_pii", False)),
                "columns": columns.get((zone, node.get("alias") or node["name"]), []),
            }

    def parents(entry: dict) -> list[dict]:
        out = []
        for p in entry.get("depends_on", {}).get("nodes", []):
            if p in refs:
                ref = refs[p]
                out.append(
                    {
                        k: ref[k]
                        for k in ("id", "name", "kind", "zone", "contract_enforced")
                        if k in ref
                    }
                )
        return out

    models = []
    for uid, node in manifest["nodes"].items():
        if node["resource_type"] == "model":
            models.append({**refs[uid], "parents": parents(node)})
    exposures = [
        {
            "id": f"exposure:{exp['name']}",
            "name": exp["name"],
            "kind": "exposure",
            "type": exp.get("type", ""),
            "maturity": exp.get("maturity") or "",
            "owner_email": (exp.get("owner") or {}).get("email") or "",
            "parents": parents(exp),
        }
        for exp in manifest["exposures"].values()
    ]
    sources = [r for r in refs.values() if r["kind"] == "source"]
    key = lambda d: d["id"]  # noqa: E731
    return {
        "models": sorted(models, key=key),
        "sources": sorted(sources, key=key),
        "exposures": sorted(exposures, key=key),
    }


def evaluate(document: dict, policy_dir: Path = POLICY_DIR) -> list[str]:
    """Violations, sorted. Raises if OPA is not installed."""
    opa = shutil.which("opa")
    if not opa:
        raise FileNotFoundError(
            "opa is not installed: https://www.openpolicyagent.org/docs/latest/#1-download-opa"
        )
    result = subprocess.run(
        [opa, "eval", "--format=json", "--stdin-input", "--data", str(policy_dir), QUERY],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=True,
    )
    values = json.loads(result.stdout)["result"][0]["expressions"][0]["value"]
    return sorted(values)


def main(argv: list[str] | None = None) -> int:
    from claims.config import Paths

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=str(DBT_DIR / "target" / "manifest.json"))
    parser.add_argument("--dump", action="store_true", help="print the input document and exit")
    args = parser.parse_args(argv)

    document = build_input(Path(args.manifest), Paths.default().warehouse)
    if args.dump:
        print(json.dumps(document, indent=2))
        return 0
    violations = evaluate(document)
    for v in violations:
        print(f"DENY  {v}")
    n = len(document["models"]) + len(document["sources"]) + len(document["exposures"])
    print(f"{len(violations)} violation(s) across {n} models, sources and exposures")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
