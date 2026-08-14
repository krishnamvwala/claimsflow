variable "project_id" {
  description = "Dedicated Google Cloud project for ClaimsFlow synthetic dev/demo."
  type        = string
}

variable "region" {
  description = "Google Cloud region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "bigquery_location" {
  description = "Multi-region or region shared by BigQuery and landing storage."
  type        = string
  default     = "US"
}

variable "landing_bucket_name" {
  description = "Globally unique synthetic landing bucket name."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account ID required to create the dev/demo cost budget."
  type        = string
}

variable "github_repository" {
  description = "GitHub owner/repository allowed to federate for deployment."
  type        = string
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID allowed to federate."
  type        = string
}

variable "github_repository_owner_id" {
  description = "Immutable numeric GitHub owner ID allowed to federate."
  type        = string
}

variable "github_workflow_ref" {
  description = "Exact deployment workflow ref allowed to federate from main."
  type        = string
}

variable "github_environment" {
  description = "Protected GitHub environment required by the deployment token."
  type        = string
}
