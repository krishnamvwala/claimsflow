# Dev/demo environment

This root composes the shared, synthetic-only Google Cloud foundation. It does not contain
backend coordinates or credentials. Initialize the remote state backend with reviewed
`-backend-config` values and authenticate through Application Default Credentials locally or
GitHub Workload Identity Federation in CI.

Phase 1 validates configuration only. Do not run `terraform apply` until a dedicated project,
remote state bucket, budget, plan review, protected GitHub environment, and manual approval
exist. Copy `terraform.tfvars.example` outside version control or pass non-secret values at
runtime; never place credentials in a `.tfvars` file.

All deployment-boundary inputs are required: billing account ID, repository name,
immutable repository and owner numeric IDs, exact workflow reference, and protected
environment name. The committed example includes the public ClaimsFlow repository IDs but
uses non-deployable project, bucket, and billing sentinels. Replace and review those values;
never weaken the identity condition to make a plan pass.
