data "google_project" "current" {
  project_id = var.project_id
}

locals {
  required_services = toset([
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "monitoring.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ])

  dataset_layers = toset([
    "raw",
    "validated",
    "quarantine",
    "curated",
    "semantic",
    "operational",
    "audit",
  ])

  workload_accounts = {
    ingestion      = "Writes verified landing, raw, validation, and audit evidence"
    transformation = "Builds isolated curated, semantic, and operational candidates"
    orchestration  = "Coordinates bounded pipeline work with identifier-only messages"
    bi             = "Reads published semantic and operational models"
    auditor        = "Reads audit evidence without business-data mutation"
    deployment     = "Applies approved infrastructure through keyless federation"
  }

  common_labels = merge(
    var.labels,
    {
      application    = "claimsflow"
      data_boundary  = "synthetic-only"
      environment    = "dev-demo"
      managed_by     = "terraform"
      production_use = "prohibited"
    },
  )

  dataset_access = {
    ingestion_raw = {
      dataset = "raw"
      role    = "roles/bigquery.dataEditor"
      account = "ingestion"
    }
    ingestion_validated = {
      dataset = "validated"
      role    = "roles/bigquery.dataEditor"
      account = "ingestion"
    }
    ingestion_quarantine = {
      dataset = "quarantine"
      role    = "roles/bigquery.dataEditor"
      account = "ingestion"
    }
    ingestion_audit = {
      dataset = "audit"
      role    = "roles/bigquery.dataEditor"
      account = "ingestion"
    }
    transformation_validated = {
      dataset = "validated"
      role    = "roles/bigquery.dataViewer"
      account = "transformation"
    }
    transformation_curated = {
      dataset = "curated"
      role    = "roles/bigquery.dataEditor"
      account = "transformation"
    }
    transformation_semantic = {
      dataset = "semantic"
      role    = "roles/bigquery.dataEditor"
      account = "transformation"
    }
    transformation_operational = {
      dataset = "operational"
      role    = "roles/bigquery.dataEditor"
      account = "transformation"
    }
    transformation_audit = {
      dataset = "audit"
      role    = "roles/bigquery.dataEditor"
      account = "transformation"
    }
    orchestration_audit = {
      dataset = "audit"
      role    = "roles/bigquery.dataEditor"
      account = "orchestration"
    }
    bi_semantic = {
      dataset = "semantic"
      role    = "roles/bigquery.dataViewer"
      account = "bi"
    }
    bi_operational = {
      dataset = "operational"
      role    = "roles/bigquery.dataViewer"
      account = "bi"
    }
    auditor_audit = {
      dataset = "audit"
      role    = "roles/bigquery.dataViewer"
      account = "auditor"
    }
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "landing" {
  name                        = var.landing_bucket_name
  project                     = var.project_id
  location                    = var.bigquery_location
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = 34560000
    is_locked        = false
  }

  soft_delete_policy {
    retention_duration_seconds = 604800
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 30
    }
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
    condition {
      age = 90
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "layer" {
  for_each = local.dataset_layers

  project                    = var.project_id
  dataset_id                 = "claimsflow_${replace(each.value, "-", "_")}"
  friendly_name              = "ClaimsFlow ${title(each.value)} (synthetic only)"
  description                = "SYNTHETIC DATA ONLY — ClaimsFlow ${each.value} layer."
  location                   = var.bigquery_location
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_service_account" "workload" {
  for_each = local.workload_accounts

  project      = var.project_id
  account_id   = "claimsflow-${each.key}"
  display_name = "ClaimsFlow ${title(each.key)} (synthetic dev/demo)"
  description  = each.value

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "ingestion_object_creator" {
  bucket = google_storage_bucket.landing.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.workload["ingestion"].email}"
}

resource "google_storage_bucket_iam_member" "ingestion_object_viewer" {
  bucket = google_storage_bucket.landing.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.workload["ingestion"].email}"
}

resource "google_bigquery_dataset_iam_member" "workload" {
  for_each = local.dataset_access

  project    = var.project_id
  dataset_id = google_bigquery_dataset.layer[each.value.dataset].dataset_id
  role       = each.value.role
  member     = "serviceAccount:${google_service_account.workload[each.value.account].email}"
}

resource "google_project_iam_member" "bigquery_job_user" {
  for_each = toset(["ingestion", "transformation", "orchestration", "bi", "auditor"])

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.workload[each.value].email}"
}

resource "google_billing_budget" "dev_demo" {
  billing_account = var.billing_account_id
  display_name    = "ClaimsFlow synthetic dev/demo monthly budget"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }

  threshold_rules {
    threshold_percent = 0.9
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "claimsflow-github"
  display_name              = "ClaimsFlow GitHub Actions"
  description               = "Keyless CI/CD identity for the approved ClaimsFlow repository"
  disabled                  = false

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "claimsflow-github"
  display_name                       = "ClaimsFlow GitHub OIDC"
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.environment"         = "assertion.environment"
    "attribute.job_workflow_ref"    = "assertion.job_workflow_ref"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_repository_owner_id}' && assertion.ref == 'refs/heads/main' && assertion.job_workflow_ref == '${var.github_workflow_ref}' && assertion.environment == '${var.github_environment}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_deployment" {
  service_account_id = google_service_account.workload["deployment"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}
