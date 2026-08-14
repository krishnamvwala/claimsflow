---
adr_id: ADR-003
title: Airflow orchestration, publication gates, retry, replay, and alerting
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Platform Engineering
  - Revenue Cycle Operations
requirements: [FR-ALT-001, FR-ALT-002, FR-ALT-003, FR-ALT-004, FR-ALT-005, FR-ALT-006, FR-ALT-007, FR-OPS-001, FR-OPS-002, FR-OPS-003, FR-OPS-004, FR-OPS-005, FR-OPS-006, NFR-REL-001, NFR-REL-002, NFR-REL-003, NFR-REL-004, NFR-REL-005]
acceptance_criteria: [AC-ALT-001, AC-ALT-002, AC-ALT-003, AC-ALT-004, AC-ALT-005, AC-ALT-006, AC-ALT-007, AC-OPS-001, AC-OPS-002, AC-OPS-003, AC-OPS-004, AC-OPS-005, AC-OPS-006, AC-REL-001, AC-REL-002, AC-REL-003, AC-REL-004, AC-REL-005]
supersedes: []
---

# ADR-003: Airflow orchestration, publication gates, retry, replay, and alerting

## Context

ClaimsFlow must schedule dependent batch work, stop unsafe publication, expose failure evidence, and safely replay late, duplicate, malformed, or partially processed deliveries. The orchestrator must coordinate domain tools without becoming a second implementation of validation, transformation, or alert policy.

## Decision

Use Apache Airflow for workflow dependency, scheduling, bounded replay, retry policy, operational callbacks, and publication gating. Run Airflow in Docker for local development. A shared demonstration may use an Airflow-compatible managed deployment such as Cloud Composer, but DAG behavior must remain portable and must not depend on a provider-specific business-rule implementation.

## Decision details

- The source-side CLI verifies provenance before upload. The primary cloud batch DAG then receives that verified registration, rechecks landing generation/checksum, loads immutable raw, validates/classifies, runs a bounded isolated dbt candidate build, reconciles, evaluates publication gates, advances the publication manifest, refreshes every affected BI partition declared by that manifest (or performs a required full refresh), and evaluates operational alerts.
- DAGs express order and pass immutable identifiers. Python and dbt implement work. No metric formula, validation-rule meaning, priority weight, or alert threshold is embedded in Airflow operators.
- Every run has `run_id`, logical UTC interval, selected batch IDs, environment, code commit, and configuration versions. Every task records start/end, status, duration, attempt, row counts, quality summaries, error class, and recovery hint.
- Tasks declare timeout, retry count, exponential backoff where safe, pool/concurrency limit, trigger rule, and failure callback. Registration, append/merge, and reconciliation tasks are idempotent before they are retryable. Publication has no blind retry after an ambiguous external response; it first checks the publication idempotency key.
- Backfill accepts an explicit UTC start/end interval or batch-ID allowlist, a reprocessing behavior, and a maximum number of active runs. It defaults to missing/failed work, performs a dry-run selection, and refuses unbounded input.
- Replaying the same batch uses the same checksum, source-record identity, business keys, and configuration version. A changed correction becomes a new batch linked to its predecessor; it is not disguised as the same delivery.
- Required validation, source freshness, dbt tests, reconciliation, and audit-completeness tasks feed one publication gate. Any blocker prevents publication and report refresh.
- Alert evaluation occurs after trusted models for business alerts and on failure callbacks for pipeline alerts. Every alert uses a versioned rule and includes source, batch or claim context, observed value, threshold/comparator, severity, timestamp, evidence link, deduplication key, and human owner.
- Common failures have a runbook entry. Recovery records who initiated it, scope, reason, prior run, selected configuration, outcome, and before/after reconciliation.

## Alternatives considered

### GitHub Actions as the batch scheduler

Rejected because Actions is retained for CI/CD; it does not provide the desired data-interval, task-dependency, retry, backfill, and operator evidence model for recurring pipelines.

### Put all pipeline logic in one Python process

Rejected because partial failure boundaries, targeted retries, dependency visibility, and operational evidence would be harder to inspect and test.

### Automatically retry every failed task

Rejected because ambiguous publication and non-idempotent external actions can duplicate effects. Retryability must be a declared task property backed by an idempotency strategy.

## Consequences

### Positive

- DAG structure makes dependencies and blocked publication visible.
- Bounded backfills and task-level evidence provide a safe recovery story.
- Business logic remains testable in its owning Python or dbt layer.
- Local Docker keeps the portfolio reproducible while preserving a path to a managed demo.

### Trade-offs

- Airflow adds services, metadata, dependency management, and operational overhead.
- A local deployment does not prove managed-environment capacity or disaster recovery.
- Cross-system idempotency still depends on careful keys and publication checks outside Airflow.

## Security and privacy

Airflow connections reference a secret manager or short-lived identity; credentials are never stored in DAG code, variables, XCom payloads, or logs. XCom contains identifiers and small control results only, never claim rows. Environment-specific runner identities receive only the permissions required to invoke the owning component.

## Reliability and recovery

The publication gate is fail-closed. Partial failure leaves durable run/task evidence and never marks a batch published. Retry and replay use stable idempotency keys and reconcile accepted business keys, hashes, counts, and financial totals. Operators can restore the prior publication pointer while a failed candidate remains available for diagnosis.

## Validation evidence

- DAG-structure and policy tests for order, timeout, retry, callback, and gate configuration.
- Happy, late, duplicate, malformed, partial-failure, boundary, null, and replay scenarios.
- Backfill dry-run and bounded-concurrency evidence.
- Failure/recovery transcript with before/after key, hash, count, and amount reconciliation.
- Alert contract and threshold-boundary tests across every alert type.

## Revisit triggers

- Event-driven or continuous processing becomes a validated requirement.
- Managed Airflow constraints require non-portable DAG behavior.
- The platform needs multi-region recovery or an availability objective beyond the portfolio baseline.
- An external action such as claim submission is proposed.
- Pipeline volume makes the current scheduler/executor topology miss the performance contract.

## References

- [Apache Airflow DAG concepts](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html)
- [Apache Airflow backfill controls](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/backfill.html)
- [Apache Airflow architecture overview](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html)
