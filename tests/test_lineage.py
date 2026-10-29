from claims.config import DBT_DIR
from claims.lineage import downstream, load_graph, mermaid


def test_impact_of_a_staging_change_reaches_dashboards_and_the_model(platform):
    nodes, children = load_graph(DBT_DIR / "target" / "manifest.json")
    names = {n.name for n in downstream("stg_claims", nodes, children)}
    assert {
        "fct_claims",
        "mart_loss_ratio",
        "employer_loss_ratio_report",
        "claim_risk_model",
    } <= names
    assert "member_pii" not in names


def test_diagram_has_every_layer(platform):
    nodes, children = load_graph(DBT_DIR / "target" / "manifest.json")
    diagram = mermaid(nodes, children)
    for layer in ("source", "staging", "intermediate", "restricted", "analytics", "exposure"):
        assert f"subgraph {layer}" in diagram
