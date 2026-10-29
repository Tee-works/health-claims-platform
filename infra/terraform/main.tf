# Data platform for a health insurer on AWS: an S3 data lake split into zones,
# separate KMS keys for sensitive and pseudonymised data, a Glue catalog per
# zone, Athena workgroups with scan limits, and one IAM role per job function.
#
#   landing/ raw/ staging/ restricted/   member PII, encrypted with the sensitive key
#   analytics/ ml/                       pseudonymised, encrypted with the analytics key

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project             = "health-claims-platform"
      environment         = var.environment
      data_classification = "confidential"
      managed_by          = "terraform"
    }
  }
}

locals {
  name_prefix = "claims-${var.environment}"
  catalog     = replace(local.name_prefix, "-", "_")
  zones       = ["raw", "staging", "restricted", "analytics"]
}

data "aws_caller_identity" "current" {}

module "data_lake" {
  source              = "./modules/data_lake"
  name_prefix         = local.name_prefix
  raw_transition_days = var.raw_transition_days
}

resource "aws_glue_catalog_database" "zone" {
  for_each    = toset(local.zones)
  name        = "${local.catalog}_${each.key}"
  description = "Tables for the ${each.key} zone of the claims data lake."
}

resource "aws_athena_workgroup" "analysts" {
  name          = "${local.name_prefix}-analysts"
  force_destroy = false

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.analyst_query_scan_limit_gb * 1073741824

    result_configuration {
      output_location = "s3://${module.data_lake.results_bucket_id}/analysts/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = module.data_lake.analytics_key_arn
      }
    }
  }
}

resource "aws_athena_workgroup" "engineering" {
  name          = "${local.name_prefix}-engineering"
  force_destroy = false

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.engineering_query_scan_limit_gb * 1073741824

    result_configuration {
      output_location = "s3://${module.data_lake.results_bucket_id}/engineering/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = module.data_lake.analytics_key_arn
      }
    }
  }
}

module "access" {
  source = "./modules/access"

  name_prefix        = local.name_prefix
  account_id         = data.aws_caller_identity.current.account_id
  region             = var.region
  role_principals    = var.role_principals
  lake_bucket_arn    = module.data_lake.lake_bucket_arn
  results_bucket_arn = module.data_lake.results_bucket_arn
  sensitive_key_arn  = module.data_lake.sensitive_key_arn
  analytics_key_arn  = module.data_lake.analytics_key_arn
  catalog_prefix     = local.catalog
  workgroup_arns = {
    analysts    = aws_athena_workgroup.analysts.arn
    engineering = aws_athena_workgroup.engineering.arn
  }
}

# Table-level grants in Lake Formation, on top of the IAM policies: analysts and
# the ML job can read the analytics zone and nothing else; the transform job
# owns every zone.
resource "aws_lakeformation_permissions" "analytics_readers" {
  for_each    = toset(["analyst", "ml"])
  principal   = module.access.role_arns[each.key]
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = aws_glue_catalog_database.zone["analytics"].name
    wildcard      = true
  }
}

resource "aws_lakeformation_permissions" "transform_tables" {
  for_each    = toset(local.zones)
  principal   = module.access.role_arns["transform"]
  permissions = ["ALL"]

  table {
    database_name = aws_glue_catalog_database.zone[each.key].name
    wildcard      = true
  }
}
