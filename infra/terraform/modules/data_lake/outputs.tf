output "lake_bucket_id" {
  value = aws_s3_bucket.lake.id
}

output "lake_bucket_arn" {
  value = aws_s3_bucket.lake.arn
}

output "results_bucket_id" {
  value = aws_s3_bucket.results.id
}

output "results_bucket_arn" {
  value = aws_s3_bucket.results.arn
}

output "sensitive_key_arn" {
  value = aws_kms_key.sensitive.arn
}

output "analytics_key_arn" {
  value = aws_kms_key.analytics.arn
}

output "default_encryption" {
  description = "Default KMS key per bucket, for tests and reviews."
  value = {
    for k, v in aws_s3_bucket_server_side_encryption_configuration.this :
    k => one(one(v.rule).apply_server_side_encryption_by_default).kms_master_key_id
  }
}
