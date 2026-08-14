output "landing_bucket_name" {
  description = "Immutable synthetic landing bucket."
  value       = google_storage_bucket.landing.name
}

output "dataset_ids" {
  description = "BigQuery dataset IDs keyed by governed layer."
  value       = { for layer, dataset in google_bigquery_dataset.layer : layer => dataset.dataset_id }
}

output "service_account_emails" {
  description = "Workload identities keyed by responsibility."
  value       = { for name, account in google_service_account.workload : name => account.email }
}

output "workload_identity_provider" {
  description = "GitHub OIDC provider restricted to the approved deployment context."
  value       = google_iam_workload_identity_pool_provider.github.name
}
