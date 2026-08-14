module "foundation" {
  source = "../../modules/foundation"

  project_id                 = var.project_id
  region                     = var.region
  bigquery_location          = var.bigquery_location
  landing_bucket_name        = var.landing_bucket_name
  billing_account_id         = var.billing_account_id
  github_repository          = var.github_repository
  github_repository_id       = var.github_repository_id
  github_repository_owner_id = var.github_repository_owner_id
  github_workflow_ref        = var.github_workflow_ref
  github_environment         = var.github_environment
}
