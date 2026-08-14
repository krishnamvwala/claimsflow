---
adr_id: ADR-007
title: Environments, Terraform, CI/CD, observability, rollback, and cost governance
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Platform Engineering
  - ClaimsFlow Data Engineering
requirements: [NFR-MNT-001, NFR-MNT-002, NFR-MNT-003, NFR-MNT-004, NFR-MNT-005]
acceptance_criteria: [AC-MNT-001, AC-MNT-002, AC-MNT-003, AC-MNT-004, AC-MNT-005]
supersedes: []
---

# ADR-007: Environments, Terraform, CI/CD, observability, rollback, and cost governance

## Context

ClaimsFlow must be reproducible by a reviewer, deploy infrastructure predictably, surface pipeline and data failures, constrain cloud spend, and record material changes. A portfolio project also needs a credible path from a laptop to a shared demo without pretending that the demo is production.

## Decision

Use local and dev/demo environments, Terraform for Google Cloud infrastructure, GitHub Actions for validation and controlled deployment, versioned release manifests for artifacts, structured operational evidence for observability, and explicit budgets/query limits. Deployment changes advance only after review, passing gates, short-lived authentication, and environment approval.

## Decision details

- `local` runs Python, dbt, Airflow, and tests through pinned tooling and containers where appropriate, using small synthetic fixtures. `dev/demo` is a dedicated GCP project with separate state, resources, identities, budgets, datasets, buckets, and approved Power BI workspace.
- Terraform modules declare buckets/lifecycle, BigQuery datasets, service accounts/IAM, Workload Identity Federation, secrets references, logging/monitoring, and budget controls. Environment root modules provide explicit non-secret values. State uses an access-controlled remote backend and is never committed.
- Pull-request CI selects relevant checks and includes whitespace/link validation, Python formatting/lint/type/unit tests, source-contract checks, metric checks, architecture checks, dbt parse/build tests against fixtures, Airflow DAG-policy tests, Terraform format/validate, secret scan, and dependency review as components appear.
- Changes to `main` create immutable build metadata. Dev/demo deployment requires the protected GitHub environment, an approved Terraform plan, short-lived federated credentials, and a manual approval. Direct workstation deployment to the shared environment is for documented break-glass recovery only.
- A release manifest records semantic version, Git commit, dependency locks, Terraform module/provider versions, Python/dbt/Airflow versions, contract and dictionary versions, dbt artifacts, deployed environment, included batch/generator version, known limitations, approver, and UTC time.
- Components emit structured JSON logs keyed by environment, run, task, batch, publication, rule, and code version. BigQuery audit tables preserve batch/task states, validation summaries, reconciliation, publication, alerts, and recovery. Logs avoid claim payloads.
- Alerts cover failed stages, freshness/quality breaches, deadline/revenue thresholds, payment variance, and backlog. Each points to evidence and an owner. The portfolio defines response/runbook behavior but makes no 24/7 support claim.
- Cost controls include a small bounded generator default, dataset/table expiration where safe, partition filters, clustering review, incremental processing, BigQuery dry runs and maximum bytes billed, custom query quotas, Cloud Billing budgets/alerts, limited Airflow concurrency, and teardown instructions for ephemeral resources.
- Rollback redeploys a prior versioned code/infrastructure artifact and selects the prior successful data publication. It never overwrites landing/raw evidence. Forward recovery processes a corrected batch or approved bounded backfill.
- Material dependencies are constrained and lockfiles are committed. Automated update pull requests must pass the same gates. Architecture, metric, severity, scope, and scoring changes require a matching ADR or governed-document update.

## Alternatives considered

### Manual cloud setup documented in screenshots

Rejected because it is difficult to reproduce, review, diff, and safely tear down, and it cannot prove repository-to-runtime coverage.

### One shared environment for local development and demo

Rejected because experiments could affect demonstrations, IAM would be broad, and costs and failure evidence would be hard to attribute.

### Automatically deploy every merge without approval

Rejected because infrastructure and data-publication changes can incur cost or break the shared demo. The environment approval is an intentional release boundary.

## Consequences

### Positive

- A new reviewer can trace infrastructure and behavior to versioned code.
- CI catches contract and configuration drift before deployment.
- Release, run, and publication evidence link code to observable outcomes.
- Budgets and query controls bound the financial risk of a public demo.

### Trade-offs

- Terraform, containers, CI matrices, and release metadata add work before visible dashboard features.
- Dev/demo is not a production-equivalent resilience environment.
- Manual deployment approval reduces speed but makes cost and change authority explicit.

## Security and privacy

Deployment uses Workload Identity Federation and environment-scoped least privilege. Terraform variables, backend settings, plans, logs, and release artifacts must not contain secrets or claim payloads. Public workflow logs and build artifacts are reviewed for synthetic/non-production labeling and safe retention.

## Reliability and recovery

Deployments retain version and plan evidence. A failed infrastructure apply stops before application publication and is reconciled against state before retry. A failed data release leaves the prior successful publication active. Recovery follows versioned runbooks and records operator, reason, selected version, scope, and outcome.

## Validation evidence

- Clean-machine setup rehearsal using only documented commands and sample configuration.
- Terraform format/validate and repository-to-runtime component inventory.
- CI path-coverage tests showing the appropriate checks run for each component family.
- Dev/demo plan, approval, deployment, rollback, and release-manifest exercise.
- Dashboard/log/audit review for injected failures plus BigQuery dry-run, quota, and budget evidence.

## Revisit triggers

- A production or regulated environment is proposed.
- Recovery, availability, or deployment-frequency objectives exceed the manual-approved demo model.
- Monthly cloud cost or representative query scans exceed the documented budget.
- The project gains multiple independent teams or services needing separate release trains.
- A managed platform replaces a version-controlled component boundary.

## References

- [Terraform configuration language](https://developer.hashicorp.com/terraform/language)
- [Terraform files and configuration structure](https://developer.hashicorp.com/terraform/language/files)
- [Configure Workload Identity Federation with deployment pipelines](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Estimate and control BigQuery costs](https://cloud.google.com/bigquery/docs/best-practices-costs)
