---
adr_id: ADR-001
title: BigQuery data layers, physical design, publication, and cost controls
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Data Engineering
  - ClaimsFlow Analytics Engineering
requirements: [FR-WH-001, FR-WH-002, FR-WH-003, FR-WH-008, NFR-PERF-001, NFR-PERF-002, NFR-PERF-003, NFR-PERF-004]
acceptance_criteria: [AC-WH-001, AC-WH-002, AC-WH-003, AC-WH-008, AC-PERF-001, AC-PERF-002, AC-PERF-003, AC-PERF-004]
supersedes: []
---

# ADR-001: BigQuery data layers, physical design, publication, and cost controls

## Context

ClaimsFlow must consolidate heterogeneous claims data without erasing source evidence, provide governed analytical outputs, support roughly 100,000 synthetic claims per month, and make query cost and performance explainable. Mixing raw, trusted, reporting, and operational data in one dataset would make access control, replay, lineage, and publication safety difficult to prove.

## Decision

Use Cloud Storage as the immutable landing boundary and BigQuery as the analytical warehouse. Create environment-specific physical datasets for raw, validated, quarantine, curated, semantic, operational, and audit data. Enforce forward-only data access and publish trusted outputs through a versioned manifest after all gates pass.

## Decision details

- Cloud Storage object names include the source, delivery date, batch ID, and original file name. The manifest records the object generation, SHA-256 checksum, contract version, synthetic provenance, size, row count when available, and arrival time.
- Raw BigQuery tables remain source-shaped and append-only. Every row carries the shared lineage envelope from the source contracts. Corrections create new evidence and disposition records; they never update the original raw value.
- Validated tables contain accepted and warned records. Quarantine and rejection evidence is stored separately with rule ID, severity, disposition, field, original evidence, reason, and processing time.
- Curated datasets contain documented facts, dimensions, bridges, and history. Semantic datasets contain governed KPI components and reporting views. Operational datasets contain priority, alert, and work-queue projections. BI identities receive access only to semantic and operational datasets.
- Major event tables are partitioned by the dominant bounded time filter: ingestion date for raw/audit evidence and business event or as-of date for curated and reporting facts. Tables are clustered by stable high-use join/filter keys such as payer, facility, claim key, status, or denial reason, with the final choice documented in each model.
- Partition filters are required on large reporting tables. Representative queries are dry-run before release, and automated or interactive jobs set a maximum bytes billed limit appropriate to the environment.
- Incremental models use unique business or surrogate keys plus a documented late-arriving-data lookback, but every candidate write is also scoped by `publication_id`. A candidate merge cannot update any row reachable through the active publication. A controlled full rebuild is exceptional and cannot delete landing or raw evidence.
- Curated, semantic, and operational result versions are append-only by publication. Each candidate adds an immutable membership delta containing changed business-key-to-result-version mappings and deletion tombstones; its manifest inherits the prior successful chain. Unchanged keys therefore retain prior immutable result versions without full-history rebuild or rescan.
- A publication record contains `publication_id`, parent publication, ordered bounded membership-delta chain, environment, code commit, dbt artifact version, included batch IDs, contract and dictionary versions, affected warehouse and BI partition ranges, impact-boundedness, gate results, published relations, row/financial reconciliations, and UTC publication time. Consumer views first resolve one active manifest, select the latest non-tombstoned mapping per business key, and join those result versions. The manifest pointer is the sole consumer-visible mutation.
- Membership-chain depth is capped by configuration and query-plan evidence. Reaching the cap triggers an approved isolated compaction candidate that materializes a new base membership map; the active snapshot remains unchanged until compaction gates pass.
- Failed candidates are never reachable from consumer views. They remain for diagnosis and are deleted only by lifecycle cleanup after the failure evidence and retention rules permit it.

## Alternatives considered

### One BigQuery dataset for every layer

Rejected because naming conventions alone do not create a reliable authorization boundary and make accidental raw-data consumption easier.

### Query files directly as external tables

Rejected as the primary design because source-format variability, mutation risk, weaker load evidence, and repeated parsing make dependable validation and reporting harder. External tables may be used only for bounded diagnostics.

### PostgreSQL as the analytical warehouse

Rejected for version 1 because the blueprint targets BigQuery, the workload is analytical, and BigQuery provides managed partitioning, clustering, job metadata, and scan-based controls that support the portfolio's governance story.

## Consequences

### Positive

- Layer ownership, permissions, and publication state are explicit.
- Raw evidence supports replay and bidirectional lineage.
- Partition pruning, clustering, incremental processing, and query caps make the scale target testable without overengineering.
- Semantic and operational models provide a narrow, governed BI contract.

### Trade-offs

- More datasets and manifests increase infrastructure and documentation work.
- Duplicate storage across layers is intentional and must be controlled with retention and cost budgets.
- Clustering effectiveness and late-arrival windows require measurement and may need a replacement ADR as usage patterns emerge.

## Security and privacy

All objects and rows must pass the synthetic-provenance gate before storage. Dataset-level IAM separates writers and readers by layer and environment. Landing, raw, quarantine, and audit data are not exposed to Power BI. Encryption uses Google-managed keys for the portfolio baseline; a future regulated design must decide whether customer-managed keys and additional perimeters are required.

## Reliability and recovery

Object generation plus checksum makes duplicate delivery decisions deterministic. Append-only raw tables preserve recovery evidence. Publication is a manifest/pointer transition only after validation, dbt tests, freshness, and reconciliation succeed. Because candidate keys and membership are isolated from the active publication, a partial build cannot alter the current consumer snapshot. Rollback selects the prior complete membership manifest rather than rewriting source evidence or published result versions.

## Validation evidence

- Terraform plan and dataset/IAM inventory.
- BigQuery table metadata showing partition and clustering choices.
- Query dry-run and maximum-bytes-billed evidence for the representative corpus.
- Raw-to-validated-to-curated count and amount reconciliations.
- Failure injection proving that an invalid batch cannot advance the publication manifest.
- Mid-build dbt failure proving that partially written candidate rows cannot change any active consumer view.

## Revisit triggers

- Representative queries exceed the scan or latency budgets after measured tuning.
- Streaming or sub-minute decisions become a validated customer requirement.
- Real regulated data is proposed.
- Dataset-level permissions cannot express the required isolation.
- Monthly volume or concurrency changes by an order of magnitude.

## References

- [Introduction to partitioned tables](https://cloud.google.com/bigquery/docs/partitioned-tables)
- [Introduction to clustered tables](https://cloud.google.com/bigquery/docs/clustered-tables)
- [Estimate and control BigQuery costs](https://cloud.google.com/bigquery/docs/best-practices-costs)
- [Cloud Storage object versioning](https://cloud.google.com/storage/docs/object-versioning)
