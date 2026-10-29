data "aws_caller_identity" "current" {}

locals {
  account_root = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"

  # Key administration stays with the account; use is granted through IAM role
  # policies (modules/access), so who can decrypt what is reviewable in one place.
  key_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AccountAdministersKey"
      Effect    = "Allow"
      Principal = { AWS = local.account_root }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })
}

# ---- keys ------------------------------------------------------------------------------

resource "aws_kms_key" "sensitive" {
  description             = "${var.name_prefix}: member PII and raw source data"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = local.key_policy
}

resource "aws_kms_alias" "sensitive" {
  name          = "alias/${var.name_prefix}-sensitive"
  target_key_id = aws_kms_key.sensitive.key_id
}

resource "aws_kms_key" "analytics" {
  description             = "${var.name_prefix}: pseudonymised analytics and ML data"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = local.key_policy
}

resource "aws_kms_alias" "analytics" {
  name          = "alias/${var.name_prefix}-analytics"
  target_key_id = aws_kms_key.analytics.key_id
}

# ---- buckets -----------------------------------------------------------------------------

resource "aws_s3_bucket" "logs" {
  #checkov:skip=CKV_AWS_18:This is the access-log target; logging it to itself would loop.
  #checkov:skip=CKV_AWS_144:Cross-region replication is a DR decision, not set for this demo.
  #checkov:skip=CKV2_AWS_62:No consumers need event notifications on access logs.
  bucket = "${var.name_prefix}-access-logs"
}

resource "aws_s3_bucket" "lake" {
  #checkov:skip=CKV_AWS_144:Cross-region replication is a DR decision, not set for this demo.
  #checkov:skip=CKV2_AWS_62:Ingestion is scheduled, not event-driven.
  bucket = "${var.name_prefix}-lake"
}

resource "aws_s3_bucket" "results" {
  #checkov:skip=CKV_AWS_144:Query results are disposable; no replication.
  #checkov:skip=CKV2_AWS_62:No consumers need event notifications on query results.
  bucket = "${var.name_prefix}-athena-results"
}

locals {
  buckets = {
    logs    = aws_s3_bucket.logs.id
    lake    = aws_s3_bucket.lake.id
    results = aws_s3_bucket.results.id
  }
  bucket_keys = {
    logs    = aws_kms_key.analytics.arn
    lake    = aws_kms_key.sensitive.arn # default to the stricter key
    results = aws_kms_key.analytics.arn
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = local.buckets
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = local.buckets
  bucket   = each.value

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.buckets
  bucket   = each.value

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.buckets
  bucket   = each.value

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = local.bucket_keys[each.key]
    }
    bucket_key_enabled = true # far fewer KMS calls, so far lower KMS cost
  }
}

resource "aws_s3_bucket_logging" "this" {
  for_each      = { lake = aws_s3_bucket.lake.id, results = aws_s3_bucket.results.id }
  bucket        = each.value
  target_bucket = aws_s3_bucket.logs.id
  target_prefix = "${each.key}/"
}

# ---- cost: lifecycle ---------------------------------------------------------------------

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id

  rule {
    id     = "raw-to-cheaper-storage"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    transition {
      days          = var.raw_transition_days
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 180
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "landing-files-expire"
    status = "Enabled"
    filter {
      prefix = "landing/"
    }
    expiration {
      days = 400 # source files kept a year past delivery for audit, then deleted
    }
  }

  rule {
    id     = "old-versions-and-uploads"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    id     = "query-results-expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "logs-retention"
    status = "Enabled"
    filter {}
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---- bucket policy: TLS only, and analytics data must use the analytics key ------------

resource "aws_s3_bucket_policy" "lake" {
  bucket = aws_s3_bucket.lake.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.lake.arn, "${aws_s3_bucket.lake.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "AnalyticsZoneUsesAnalyticsKey"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = ["${aws_s3_bucket.lake.arn}/analytics/*", "${aws_s3_bucket.lake.arn}/ml/*"]
        Condition = {
          StringNotEquals = {
            "s3:x-amz-server-side-encryption-aws-kms-key-id" = aws_kms_key.analytics.arn
          }
        }
      },
    ]
  })
}
