# terraform test, against a mocked AWS provider: no account, no credentials.

# The mock fills computed attributes with random strings; the AWS provider rejects
# those where it expects an ARN, so the resources that other resources reference
# by ARN get realistic ones.
mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock-role"
    }
  }
  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/mock-policy"
    }
  }
}

override_resource {
  target = module.data_lake.aws_kms_key.sensitive
  values = {
    arn = "arn:aws:kms:eu-west-1:123456789012:key/sensitive-0000-0000-0000-000000000000"
  }
}

override_resource {
  target = module.data_lake.aws_kms_key.analytics
  values = {
    arn = "arn:aws:kms:eu-west-1:123456789012:key/analytics-0000-0000-0000-000000000000"
  }
}


variables {
  environment = "test"
}

run "analyst_is_denied_every_sensitive_zone" {
  command = apply

  assert {
    condition = length([
      for s in jsondecode(module.access.policy_json["analyst"]).Statement :
      s if s.Effect == "Deny" && contains(s.Action, "s3:*")
    ]) == 1
    error_message = "The analyst policy must explicitly deny S3 access to the sensitive zones."
  }

  assert {
    condition = alltrue([
      for zone in ["landing", "raw", "quarantine", "staging", "restricted"] :
      anytrue([
        for s in jsondecode(module.access.policy_json["analyst"]).Statement :
        s.Effect == "Deny" && anytrue([for r in s.Resource : endswith(r, "/${zone}/*")])
      ])
    ])
    error_message = "Every sensitive zone must be covered by an analyst deny."
  }
}

run "analyst_cannot_write_to_the_lake" {
  command = apply

  assert {
    condition = !anytrue([
      for s in jsondecode(module.access.policy_json["analyst"]).Statement :
      s.Effect == "Allow" && contains(s.Action, "s3:PutObject") && anytrue([
        for r in s.Resource : startswith(r, module.data_lake.lake_bucket_arn)
      ])
    ])
    error_message = "Analysts may only write query results, never into the lake."
  }
}

run "sensitive_data_uses_its_own_key" {
  command = apply

  assert {
    condition     = module.data_lake.default_encryption["lake"] == module.data_lake.sensitive_key_arn
    error_message = "The lake bucket must default to the sensitive KMS key."
  }

  assert {
    condition     = module.data_lake.sensitive_key_arn != module.data_lake.analytics_key_arn
    error_message = "Sensitive and analytics data must use different keys."
  }
}

run "analyst_queries_are_capped" {
  command = apply

  assert {
    condition     = aws_athena_workgroup.analysts.configuration[0].bytes_scanned_cutoff_per_query <= 10 * 1073741824
    error_message = "Analyst queries must be capped at 10 GB scanned."
  }

  assert {
    condition     = aws_athena_workgroup.analysts.configuration[0].enforce_workgroup_configuration
    error_message = "Analysts must not be able to override the workgroup settings."
  }
}
