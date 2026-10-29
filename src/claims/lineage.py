"""Lineage from dbt's manifest: a diagram for the docs, and impact analysis for reviews.

    python -m claims.lineage diagram            write docs/lineage.md
    python -m claims.lineage impact stg_claims  everything downstream, dashboards included

The impact command answers the question a reviewer should ask of every
pull request: if this model changes, which tables, reports and models move?
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from claims.config import DBT_DIR, REPO

LAYER_ORDER = ["source", "seed", "staging", "intermediate", "restricted", "analytics", "exposure"]


@dataclass(frozen=True)
class Node:
    uid: str
    name: str
    layer: str


def load_graph(manifest_path: Path) -> tuple[dict[str, Node], dict[str, set[str]]]:
    manifest = json.loads(manifest_path.read_text())
    nodes: dict[str, Node] = {}
    children: dict[str, set[str]] = {}

    for uid, src in manifest["sources"].items():
        nodes[uid] = Node(uid, f"{src['source_name']}.{src['name']}", "source")
    for uid, node in manifest["nodes"].items():
        if node["resource_type"] == "seed":
            nodes[uid] = Node(uid, node["name"], "seed")
        elif node["resource_type"] == "model":
            nodes[uid] = Node(uid, node["name"], node["config"].get("schema") or "model")
    for uid, exp in manifest["exposures"].items():
        nodes[uid] = Node(uid, exp["name"], "exposure")

    for uid in nodes:
        entry = manifest["nodes"].get(uid) or manifest["exposures"].get(uid)
        if not entry:
            continue
        for parent in entry.get("depends_on", {}).get("nodes", []):
            if parent in nodes:
                children.setdefault(parent, set()).add(uid)
    return nodes, children


def downstream(name: str, nodes: dict[str, Node], children: dict[str, set[str]]) -> list[Node]:
    start = [uid for uid, n in nodes.items() if n.name == name]
    if not start:
        raise KeyError(f"no model, seed, source or exposure named {name!r}")
    seen: set[str] = set()
    queue = deque(start)
    while queue:
        for child in children.get(queue.popleft(), ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return sorted((nodes[u] for u in seen), key=lambda n: (_rank(n.layer), n.name))


def _rank(layer: str) -> int:
    return LAYER_ORDER.index(layer) if layer in LAYER_ORDER else len(LAYER_ORDER)


def mermaid(nodes: dict[str, Node], children: dict[str, set[str]]) -> str:
    def nid(uid: str) -> str:
        return uid.replace(".", "_").replace("-", "_")

    lines = ["flowchart LR"]
    for layer in LAYER_ORDER:
        members = sorted((n for n in nodes.values() if n.layer == layer), key=lambda n: n.name)
        if not members:
            continue
        lines.append(f"  subgraph {layer}")
        lines += [f'    {nid(n.uid)}["{n.name}"]' for n in members]
        lines.append("  end")
    for parent, kids in sorted(children.items()):
        lines += [f"  {nid(parent)} --> {nid(k)}" for k in sorted(kids)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=str(DBT_DIR / "target" / "manifest.json"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagram")
    p = sub.add_parser("impact")
    p.add_argument("name")
    args = parser.parse_args(argv)

    nodes, children = load_graph(Path(args.manifest))
    if args.cmd == "diagram":
        out = REPO / "docs" / "lineage.md"
        out.write_text(
            "# Lineage\n\nGenerated from dbt's manifest by `python -m claims.lineage diagram`.\n\n"
            "```mermaid\n" + mermaid(nodes, children) + "\n```\n"
        )
        print(f"wrote {out.relative_to(REPO)}")
        return 0
    for n in downstream(args.name, nodes, children):
        print(f"{n.layer:<13} {n.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
