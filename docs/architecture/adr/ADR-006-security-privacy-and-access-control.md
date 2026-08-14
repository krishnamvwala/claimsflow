---
adr_id: ADR-006
title: Synthetic-only security, IAM, secrets, audit, encryption, and retention
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Security Review
  - ClaimsFlow Data Engineering
requirements: [NFR-SEC-001, NFR-SEC-002, NFR-SEC-003, NFR-SEC-004, NFR-SEC-005, NFR-SEC-006, NFR-AUD-001, NFR-AUD-002, NFR-AUD-003, NFR-AUD-004, NFR-AUD-005]
acceptance_criteria: [AC-SEC-001, AC-SEC-002, AC-SEC-003, AC-SEC-004, AC-SEC-005, AC-SEC-006, AC-AUD-001, AC-AUD-002, AC-AUD-003, AC-AUD-004, AC-AUD-005]
supersedes: []
---

# ADR-006: Synthetic-only security, IAM, secrets, audit, encryption, and retention

## Context

ClaimsFlow is a public portfolio project in a healthcare domain. Even synthetic records can be mistaken for real data, and insecure examples can teach unsafe practices. The design must prove provenance, least privilege, secret hygiene, access/audit boundaries, encryption, retention, and known production gaps without claiming HIPAA compliance.

## Decision

Enforce a synthetic-only trust boundary at ingress and throughout outputs. Separate local and dev/demo resources and identities, grant least privilege by layer, store secrets outside Git, authenticate CI to Google Cloud with GitHub OIDC and Workload Identity Federation, retain complete audit lineage, and document controls and gaps explicitly.

## Decision details

- Every accepted input is traceable to an approved versioned generator or fixture manifest. Unverified input is rejected before entering project-managed storage or processing. A safe synthetic canary tests this control.
- All datasets, reports, screenshots, exports, docs, and demos display `SYNTHETIC DATA — NOT FOR PRODUCTION OR CLINICAL/BILLING USE`. Generated IDs and organizations use reserved fictional patterns and cannot be derived from real people or customers.
- Local and dev/demo use separate configuration and identities; the shared demo uses a dedicated GCP project and Power BI workspace. There is no version 1 production environment.
- Humans use individual identities. Workloads use distinct identities for ingestion, transformation, orchestration, deployment, BI, and audit review. No shared owner credential is used for routine operation.

| Role | Read | Write/admin | Explicit denial |
| --- | --- | --- | --- |
| Ingestion writer | Landing manifests, source contracts | Landing, raw, validation/audit events | Curated/semantic publication, IAM |
| Transformation writer | Validated inputs, contract metadata | Curated, semantic, operational candidate relations, dbt artifacts | Landing/raw mutation, IAM |
| Orchestration runner | Run metadata and gate summaries | Run/task state and approved invocations | Business-table ad hoc writes, IAM |
| BI reader | Approved semantic and operational views | BigQuery query jobs only | Landing, raw, quarantine, transformation internals, IAM |
| Auditor | Audit, lineage, configuration metadata | None | Source/business data mutation, IAM |
| Deployment identity | Terraform state and declared resources | Approved environment infrastructure | Data-row access unless a specific deployment operation requires it |

- Secrets belong in Secret Manager or an approved local credential store and are injected at runtime. Repository, logs, artifacts, Terraform variables/state configuration, Airflow XCom, and Power BI source files must not contain long-lived secret material.
- GitHub Actions exchanges its repository/environment-scoped OIDC token for short-lived Google credentials through Workload Identity Federation. Trust conditions restrict repository, branch/ref, workflow, and environment. Long-lived service-account JSON keys are prohibited.
- Data uses TLS in transit and Google-managed encryption at rest for the portfolio baseline. Cloud audit logs and application audit tables record administrative and data-operation evidence appropriate to each service.
- Lifecycle policy keeps landing, raw, and lineage/audit evidence for at least the longest replay, metric restatement, and retained-publication horizon. The current maximum metric restatement window is 365 days, so the dev/demo baseline is 400 days for landing, raw, and lineage/audit evidence and 30 days for generated exports; repository fixtures remain version-controlled. A referential-retention check blocks deletion while an active or retained publication still depends on the evidence. Dependent publications and user-facing outputs must expire no later than their source evidence. Legal hold is not supported.
- Threat assumptions include malicious/untrusted uploads, credential leakage, excessive IAM, cross-environment writes, unsafe logs/exports, dependency compromise, SQL/query abuse, and accidental deletion. Controls include provenance rejection, restricted identities, secret scanning, dependency review, query limits, audit, soft-delete/version recovery, and publication gates.
- Known production gaps include HIPAA risk analysis and agreements, real-data classification/DLP, patient-access controls, network/service perimeters, customer-managed keys, formal key rotation, incident-response exercises, disaster recovery, penetration testing, legal retention, and compliance evidence. These are prerequisites, not deferred implementation promises.

## Alternatives considered

### Treat synthetic data as eliminating security requirements

Rejected because public code, credentials, cloud spend, access patterns, and misleading outputs still create risk, and the portfolio must demonstrate production-aware boundaries.

### Store a service-account JSON key in GitHub Secrets

Rejected because a long-lived key increases leakage and rotation risk. Federated short-lived credentials are the CI/CD baseline.

### Claim production or HIPAA readiness from the portfolio design

Rejected because synthetic-data controls and documentation do not establish the legal, organizational, operational, and technical controls required for real regulated workloads.

## Consequences

### Positive

- The data boundary is testable from ingestion through public artifacts.
- Narrow identities limit accidental layer bypass and make responsibility visible.
- Keyless CI removes a high-risk long-lived credential.
- Explicit gaps prevent overstating the portfolio's assurance.

### Trade-offs

- More identities, policies, labels, scans, and evidence increase setup effort.
- Google-managed encryption is simpler but does not demonstrate customer-managed-key operations.
- The 400-day evidence floor costs more storage and must increase if any replay, restatement, or retained-publication horizon grows.

## Security and privacy

This entire ADR defines the baseline security/privacy control set. No control in it authorizes real data. A pull request that weakens provenance, labels, IAM, secret handling, audit, encryption, retention, or gap disclosure is a material decision change.

## Reliability and recovery

Cloud Storage recovery features and append-only evidence reduce accidental-loss risk. Audit records must survive a failed business-data run. Identity or secret compromise triggers credential revocation, workflow disablement, audit review, clean redeployment, and regeneration of synthetic state; no real-person notification procedure is implied because real data is prohibited.

## Validation evidence

- End-to-end synthetic provenance inventory and safe-canary rejection test.
- Terraform IAM matrix review and denied-access tests for every workload role.
- Pull-request and release secret scans using safe synthetic detections.
- Workload Identity Federation claim-condition review.
- Public artifact label scan, audit-lineage integrity tests, and retention configuration review.
- Threat-model tabletop and explicit production-gap checklist.

## Revisit triggers

- Any proposal to ingest real, regulated, customer, or third-party data.
- A new public export, integration, user role, or environment is introduced.
- Threat modeling finds that dataset/project IAM cannot provide adequate isolation.
- Regulatory, contractual, or retention obligations are proposed.
- Long-lived credentials or customer-managed encryption become required.

## References

- [Google Cloud Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [Configure Workload Identity Federation with deployment pipelines](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Cloud Storage overview and data-protection controls](https://cloud.google.com/storage/docs/introduction)
- [Cloud Storage object versioning](https://cloud.google.com/storage/docs/object-versioning)
