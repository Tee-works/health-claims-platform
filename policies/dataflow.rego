# Governance rules for the data flows, evaluated by OPA against the built platform.
#
# The input is generated from dbt's manifest and the warehouse catalogue by
# `claims policy` (src/claims/policy.py): every model with its zone, owner,
# contract and real columns, every source and exposure, and every edge between
# them. A rule here is a requirement someone would otherwise write in a policy
# document; here it fails the build instead.
package dataflow

governed_zones := {"analytics", "restricted"}

# Every node's direct parents, by id, for walking lineage upstream.
parents_of[n.id] := {p.id | some p in n.parents} if some n in input.models

parents_of[e.id] := {p.id | some p in e.parents} if some e in input.exposures

# graph.reachable only returns nodes that are keys of the graph, so sources
# (which have no parents) need an entry too.
parents_of[s.id] := set() if some s in input.sources

upstream(id) := graph.reachable(parents_of, {id}) - {id}

# 1. Restricted data stays restricted. Identifiable data lives in the
#    restricted zone; nothing outside it may read from it directly, and no
#    dashboard or model may be built on it.
deny contains msg if {
	some m in input.models
	m.zone != "restricted"
	some p in m.parents
	p.zone == "restricted"
	msg := sprintf("%s (%s) reads restricted model %s: restricted data may only feed restricted models", [m.name, m.zone, p.name])
}

deny contains msg if {
	some e in input.exposures
	some p in e.parents
	p.zone == "restricted"
	msg := sprintf("exposure %s is built on restricted model %s", [e.name, p.name])
}

# 2. No personal data in analytics. Checked against the columns the warehouse
#    really has, not the ones the YAML documents.
deny contains msg if {
	some m in input.models
	m.zone == "analytics"
	some c in m.columns
	lower(c) in data.classification.personal_columns
	msg := sprintf("analytics.%s has personal-data column %s", [m.name, c])
}

# 3. Accountability. Every governed table has a named owner and says what it
#    is; every dashboard and model has someone to contact.
deny contains msg if {
	some m in input.models
	m.zone in governed_zones
	m.owner == ""
	msg := sprintf("%s.%s has no owner (config.meta.owner)", [m.zone, m.name])
}

deny contains msg if {
	some m in input.models
	m.zone in governed_zones
	m.description == ""
	msg := sprintf("%s.%s has no description", [m.zone, m.name])
}

deny contains msg if {
	some e in input.exposures
	e.owner_email == ""
	msg := sprintf("exposure %s has no owner email", [e.name])
}

# 4. What a critical report reads cannot change shape silently. A high-maturity
#    exposure may only depend on models whose contract (column names and types)
#    is enforced.
deny contains msg if {
	some e in input.exposures
	e.maturity == "high"
	some p in e.parents
	p.kind == "model"
	not p.contract_enforced
	msg := sprintf("exposure %s (maturity high) depends on %s, whose contract is not enforced", [e.name, p.name])
}

# 5. Personal data is declared where it enters. Any source that feeds a
#    restricted model must be marked contains_pii, so the classification starts
#    at the source rather than being discovered downstream.
deny contains msg if {
	some m in input.models
	m.zone == "restricted"
	some s in input.sources
	s.id in upstream(m.id)
	not s.contains_pii
	msg := sprintf("source %s feeds restricted model %s but is not declared contains_pii", [s.name, m.name])
}
