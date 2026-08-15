variable "project_id" {
  description = "Dedicated Google Cloud project for synthetic dev/demo resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid lowercase Google Cloud project ID."
  }
}

variable "region" {
  description = "Google Cloud region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "bigquery_location" {
  description = "BigQuery and landing-bucket location."
  type        = string
  default     = "US"
}

variable "landing_bucket_name" {
  description = "Globally unique name for the immutable synthetic landing bucket."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account ID required to create the dev/demo cost budget."
  type        = string

  validation {
    condition     = can(regex("^[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$", var.billing_account_id))
    error_message = "billing_account_id must use the XXXXXX-XXXXXX-XXXXXX format."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly budget threshold for the bounded portfolio environment."
  type        = number
  default     = 25

  validation {
    condition = (
      var.monthly_budget_usd >= 1 &&
      var.monthly_budget_usd <= 100 &&
      floor(var.monthly_budget_usd) == var.monthly_budget_usd
    )
    error_message = "monthly_budget_usd must be a whole-dollar amount from 1 through 100."
  }
}

variable "github_repository" {
  description = "GitHub owner/repository allowed to federate for dev/demo deployment."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must use the owner/repository format."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID allowed to federate."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must contain digits only."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable numeric GitHub owner ID allowed to federate."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must contain digits only."
  }
}

variable "github_workflow_ref" {
  description = "Exact owner/repository workflow ref allowed to deploy from main."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+/\\.github/workflows/[A-Za-z0-9._-]+\\.ya?ml@refs/heads/main$", var.github_workflow_ref))
    error_message = "github_workflow_ref must identify a workflow on refs/heads/main."
  }

  validation {
    condition = startswith(
      var.github_workflow_ref,
      "${var.github_repository}/.github/workflows/",
    )
    error_message = "github_workflow_ref must belong to github_repository."
  }
}

variable "github_environment" {
  description = "Protected GitHub environment required in the deployment OIDC token."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]*$", var.github_environment))
    error_message = "github_environment may contain only letters, digits, dot, underscore, and hyphen."
  }
}

variable "labels" {
  description = "Additional non-sensitive labels applied to supported resources."
  type        = map(string)
  default     = {}

  validation {
    condition = length(setintersection(
      toset(keys(var.labels)),
      toset(["application", "data_boundary", "environment", "managed_by", "production_use"]),
    )) == 0
    error_message = "labels cannot override ClaimsFlow reserved governance keys."
  }
}
