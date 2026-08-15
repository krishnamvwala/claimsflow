# Dev/demo foundation module

This module declares the synthetic-only Google Cloud boundary: immutable landing storage,
seven layer-specific BigQuery datasets, distinct workload identities, least-privilege data
access, mandatory GitHub OIDC federation, and a mandatory billing budget.

Safety defaults include public-access prevention, uniform bucket access, versioning, a
400-day retention floor, seven-day soft deletion, no automatic evidence deletion,
`force_destroy = false`, and `delete_contents_on_destroy = false`. Storage-class lifecycle
rules reduce cost without removing evidence. Terraform never uploads or reads claim rows.

The deployment account intentionally receives no broad project role here. A reviewed
environment-specific deployment design must grant only the permissions needed by an
approved plan.

Federation is fail closed on the repository name, immutable repository and owner numeric
IDs, `refs/heads/main`, an exact workflow reference, and a protected GitHub environment.
The budget depends on the enabled Cloud Billing Budget API. The ingestion identity alone
can read landing objects; orchestration writes identifier-only audit evidence and cannot
read the landing bucket. Every identity that runs queries has `bigquery.jobUser`, while
dataset access remains layer-specific.
