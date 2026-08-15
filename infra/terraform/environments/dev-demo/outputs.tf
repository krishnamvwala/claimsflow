output "landing_bucket_name" {
  value       = module.foundation.landing_bucket_name
  description = "Immutable synthetic landing bucket."
}

output "dataset_ids" {
  value       = module.foundation.dataset_ids
  description = "Dataset IDs keyed by governed layer."
}

output "service_account_emails" {
  value       = module.foundation.service_account_emails
  description = "Workload identities keyed by responsibility."
}

output "workload_identity_provider" {
  value       = module.foundation.workload_identity_provider
  description = "GitHub OIDC provider restricted to the approved deployment context."
}
