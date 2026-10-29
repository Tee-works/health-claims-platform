variable "name_prefix" {
  type = string
}

variable "account_id" {
  type = string
}

variable "region" {
  type = string
}

variable "role_principals" {
  type = map(list(string))
}

variable "lake_bucket_arn" {
  type = string
}

variable "results_bucket_arn" {
  type = string
}

variable "sensitive_key_arn" {
  type = string
}

variable "analytics_key_arn" {
  type = string
}

variable "catalog_prefix" {
  type = string
}

variable "workgroup_arns" {
  type = map(string)
}
