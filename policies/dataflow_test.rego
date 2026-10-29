# Each rule is tested both ways: a minimal platform that complies, and the same
# platform with exactly one thing broken. Run with `opa test policies -v`.
package dataflow_test

import data.dataflow

src_members := {"id": "source:lake.members", "name": "lake.members", "kind": "source", "zone": "source", "contains_pii": true}

stg_members := {
	"id": "model:stg_members", "name": "stg_members", "kind": "model", "zone": "staging",
	"owner": "", "description": "", "contract_enforced": false, "columns": ["member_id", "first_name"],
	"parents": [src_members],
}

member_pii := {
	"id": "model:member_pii", "name": "member_pii", "kind": "model", "zone": "restricted",
	"owner": "data-engineering", "description": "Identifiable member data.", "contract_enforced": false,
	"columns": ["member_id", "member_key", "first_name"], "parents": [stg_members],
}

dim_member := {
	"id": "model:dim_member", "name": "dim_member", "kind": "model", "zone": "analytics",
	"owner": "data-engineering", "description": "Members, pseudonymous.", "contract_enforced": true,
	"columns": ["member_key", "age_band"], "parents": [stg_members],
}

report := {
	"id": "exposure:member_report", "name": "member_report", "kind": "exposure", "type": "dashboard",
	"maturity": "high", "owner_email": "analytics@example.com", "parents": [dim_member],
}

compliant := {
	"models": [stg_members, member_pii, dim_member],
	"sources": [src_members],
	"exposures": [report],
}

with_models(models) := object.union(compliant, {"models": models})

test_compliant_platform_passes if {
	count(dataflow.deny) == 0 with input as compliant
}

test_analytics_reading_restricted_is_denied if {
	leaky := object.union(dim_member, {"parents": [member_pii]})
	some msg in dataflow.deny with input as with_models([stg_members, member_pii, leaky])
	contains(msg, "reads restricted model member_pii")
}

test_exposure_on_restricted_is_denied if {
	bad := object.union(report, {"parents": [member_pii]})
	some msg in dataflow.deny with input as object.union(compliant, {"exposures": [bad]})
	contains(msg, "built on restricted model member_pii")
}

test_personal_column_in_analytics_is_denied if {
	leaky := object.union(dim_member, {"columns": ["member_key", "Phone"]})
	some msg in dataflow.deny with input as with_models([stg_members, member_pii, leaky])
	contains(msg, "personal-data column Phone")
}

test_personal_columns_are_allowed_in_restricted if {
	count(dataflow.deny) == 0 with input as compliant
	"first_name" in member_pii.columns
}

test_missing_owner_is_denied if {
	ownerless := object.union(dim_member, {"owner": ""})
	some msg in dataflow.deny with input as with_models([stg_members, member_pii, ownerless])
	contains(msg, "analytics.dim_member has no owner")
}

test_staging_needs_no_owner if {
	# stg_members has no owner or description, and that is fine: staging is not governed.
	count(dataflow.deny) == 0 with input as compliant
}

test_missing_description_is_denied if {
	vague := object.union(member_pii, {"description": ""})
	some msg in dataflow.deny with input as with_models([stg_members, vague, dim_member])
	contains(msg, "restricted.member_pii has no description")
}

test_exposure_without_owner_is_denied if {
	orphan := object.union(report, {"owner_email": ""})
	some msg in dataflow.deny with input as object.union(compliant, {"exposures": [orphan]})
	contains(msg, "exposure member_report has no owner email")
}

test_high_maturity_exposure_on_uncontracted_model_is_denied if {
	loose := object.union(dim_member, {"contract_enforced": false})
	bad := object.union(report, {"parents": [loose]})
	some msg in dataflow.deny with input as object.union(compliant, {"exposures": [bad]})
	contains(msg, "whose contract is not enforced")
}

test_medium_maturity_exposure_may_use_uncontracted_model if {
	loose := object.union(dim_member, {"contract_enforced": false})
	ok := object.union(report, {"maturity": "medium", "parents": [loose]})
	count(dataflow.deny) == 0 with input as object.union(compliant, {"exposures": [ok]})
}

test_undeclared_personal_source_is_denied if {
	undeclared := object.union(src_members, {"contains_pii": false})
	stg := object.union(stg_members, {"parents": [undeclared]})
	pii := object.union(member_pii, {"parents": [stg]})
	some msg in dataflow.deny with input as {
		"models": [stg, pii, dim_member],
		"sources": [undeclared],
		"exposures": [report],
	}
	contains(msg, "source lake.members feeds restricted model member_pii")
}
