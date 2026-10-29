variable "environment" {
  description = "Deployment environment, e.g. dev or prod."
  type        = string
}

variable "region" {
  description = "AWS region. af-south-1 (Cape Town) is the closest region to Lagos."
  type        = string
  default     = "af-south-1"
}

variable "role_principals" {
  description = "IAM principals (SSO roles, CI roles, workload roles) allowed to assume each platform role. Empty means the account root, i.e. delegated to IAM policy in the account."
  type        = map(list(string))
  default     = {}
}

variable "analyst_query_scan_limit_gb" {
  description = "Hard cap on data scanned by a single analyst query in Athena."
  type        = number
  default     = 10
}

variable "engineering_query_scan_limit_gb" {
  description = "Hard cap on data scanned by a single engineering query in Athena."
  type        = number
  default     = 200
}

variable "raw_transition_days" {
  description = "Days before raw-zone objects move to infrequent-access storage."
  type        = number
  default     = 30
}
