output "role_arns" {
  value = { for k, r in aws_iam_role.this : k => r.arn }
}

output "policy_json" {
  description = "Rendered policy per role, for tests and reviews."
  value       = local.policies
}
