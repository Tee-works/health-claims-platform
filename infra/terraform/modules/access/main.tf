# One role per job function. Policies live in policies/*.json.tftpl so they
# can be reviewed as plain JSON and tested without AWS (tests/test_access.py).

locals {
  roles = {
    ingest    = "Loads hospital files, telemedicine pages and membership snapshots into the raw zone."
    transform = "Runs dbt: reads every zone, writes staging, restricted and analytics."
    analyst   = "Reads the pseudonymised analytics zone through the analysts Athena workgroup."
    ml        = "Trains and scores the claim risk model from the analytics zone."
  }

  template_vars = {
    lake                  = var.lake_bucket_arn
    results               = var.results_bucket_arn
    sensitive_key         = var.sensitive_key_arn
    analytics_key         = var.analytics_key_arn
    analysts_workgroup    = var.workgroup_arns["analysts"]
    engineering_workgroup = var.workgroup_arns["engineering"]
    catalog               = "arn:aws:glue:${var.region}:${var.account_id}:catalog"
    database_prefix       = "arn:aws:glue:${var.region}:${var.account_id}:database/${var.catalog_prefix}"
    table_prefix          = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.catalog_prefix}"
  }

  policies = {
    for role in keys(local.roles) :
    role => templatefile("${path.module}/policies/${role}.json.tftpl", local.template_vars)
  }

  principals = {
    for role in keys(local.roles) :
    role => length(lookup(var.role_principals, role, [])) > 0 ? var.role_principals[role] : ["arn:aws:iam::${var.account_id}:root"]
  }
}

resource "aws_iam_role" "this" {
  for_each             = local.roles
  name                 = "${var.name_prefix}-${each.key}"
  description          = each.value
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = local.principals[each.key] }
    }]
  })
}

resource "aws_iam_policy" "this" {
  for_each    = local.roles
  name        = "${var.name_prefix}-${each.key}"
  description = "Data access for the ${each.key} role."
  policy      = local.policies[each.key]
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each   = local.roles
  role       = aws_iam_role.this[each.key].name
  policy_arn = aws_iam_policy.this[each.key].arn
}
