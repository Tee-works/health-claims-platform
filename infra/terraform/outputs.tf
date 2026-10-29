output "lake_bucket" {
  value = module.data_lake.lake_bucket_id
}

output "role_arns" {
  value = module.access.role_arns
}

output "athena_workgroups" {
  value = {
    analysts    = aws_athena_workgroup.analysts.name
    engineering = aws_athena_workgroup.engineering.name
  }
}
