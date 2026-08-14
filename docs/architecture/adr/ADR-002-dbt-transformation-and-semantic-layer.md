---
adr_id: ADR-002
title: dbt transformation, metric, history, and priority-engine ownership
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Analytics Engineering
  - Revenue Cycle Operations
requirements: [FR-WH-004, FR-WH-005, FR-WH-006, FR-WH-007, FR-MET-001, FR-MET-002, FR-MET-003, FR-MET-004, FR-MET-005, FR-PRI-001, FR-PRI-002, FR-PRI-003, FR-PRI-004, FR-PRI-005, FR-PRI-006, FR-PRI-007]
acceptance_criteria: [AC-WH-004, AC-WH-005, AC-WH-006, AC-WH-007, AC-MET-001, AC-MET-002, AC-MET-003, AC-MET-004, AC-MET-005, AC-PRI-001, AC-PRI-002, AC-PRI-003, AC-PRI-004, AC-PRI-005, AC-PRI-006, AC-PRI-007]
supersedes: []
---

# ADR-002: dbt transformation, metric, history, and priority-engine ownership

## Context

ClaimsFlow needs one reproducible implementation of business transformations, eight governed metrics, dimensional attribution, historical state, and an explainable denied-claim priority calculation. Splitting SQL business logic across Python, Airflow, Power BI, and warehouse scripts would create conflicting results and weak lineage.

## Decision

Use dbt Core with the BigQuery adapter as the exclusive owner of warehouse business transformation. dbt will build curated facts and dimensions, history snapshots, governed semantic projections, operational marts, and the deterministic priority engine. Python, Airflow, and Power BI may invoke or consume these results but may not redefine them.

## Decision details

- The project model path progresses through `staging`, `intermediate`, `curated`, `semantic`, and `operational`. Staging reads validated records only and performs type-safe renaming; curated models define business grains; semantic and operational models are stable consumer contracts.
- Each model declares description, owner, grain, materialization, key, dependencies, columns, and tests in version control. Required tests include uniqueness, not-null, relationships, accepted values, reconciliation, and custom business assertions.
- Large facts and marts use BigQuery incremental materializations with a non-null `unique_key`, merge strategy, explicit event-time lookback, and `on_schema_change: fail` unless a reviewed migration says otherwise. The physical merge key includes the candidate `publication_id`, so dbt cannot update active-publication rows. A candidate membership delta maps only changed keys or tombstones and inherits unchanged mappings from the prior bounded manifest chain. Full refreshes and membership compaction require explicit approval and build an isolated candidate.
- Business history uses dbt snapshots or effective-dated models only when a decision must reproduce the state known at a past time. Snapshot strategy, unique key, updated timestamp, and invalidation behavior are declared per model.
- Each governed metric implementation references its immutable `metric_id` and `dictionary_version`. Semantic models expose numerator, denominator, value, time grain, allowed dimensions, definition version, and publication lineage so a reviewer can reproduce the result.
- Leadership and operational outputs read the same metric relation for an identical filter context. Power BI measures may format, select, or safely divide governed components; they cannot introduce a second business formula.
- The priority engine is a versioned dbt operational model. Configuration controls eligible records, feature normalization, weights, thresholds, bands, and exclusions. The output preserves inputs, component contributions, leading reasons, blocking conditions, rule version, calculation time, and lineage. It recommends human review only.
- Claims that fail required identity, financial, deadline, or publication checks are written to exclusion evidence and never ranked. Eligible plus excluded counts reconcile to the candidate population.
- `dbt build` artifacts, test results, manifest, run results, and catalog are attached to the publication record.

## Alternatives considered

### Put transformations in Python dataframes

Rejected because it would duplicate SQL warehouse behavior, make lineage harder to inspect, and require data movement outside BigQuery for work that is naturally set-based.

### Define metrics and priority logic in Power BI

Rejected because multiple reports could diverge, operational consumers outside Power BI would lack the same definitions, and source-to-result lineage would be weaker.

### Start with a machine-learning recovery score

Rejected because synthetic historical outcomes do not justify a predictive claim. Versioned deterministic rules are testable, explainable, and aligned with the project's human-review boundary.

## Consequences

### Positive

- Business logic has one reviewable owner and lineage graph.
- Metric parity and priority reproducibility become automated tests.
- Incremental models bound work while snapshots preserve decision-relevant history.
- dbt artifacts provide implementation and publication evidence.

### Trade-offs

- Complex validation that needs original file bytes remains in Python, creating an explicit handoff to dbt.
- dbt Core does not supply a hosted scheduler or governance UI; Airflow and repository workflows provide those controls.
- Snapshot and incremental strategies require careful keys, late-arrival windows, and migration planning.

## Security and privacy

dbt runs under an environment-specific transformation identity that can read validated data and write curated, semantic, and operational datasets, but cannot mutate landing or raw evidence. Generated artifacts must not contain row samples or secret values. All models retain the synthetic/non-production label and exclude unnecessary quasi-identifying attributes from BI contracts.

## Reliability and recovery

Every build selects explicit batch IDs or bounded event intervals and one candidate publication namespace. Unique-key and relationship tests protect merges; reconciliation tests protect counts and amounts. Failed builds cannot change the active membership map or advance publication. Recovery reruns the same selection and configuration, while an approved full refresh builds an isolated candidate before publication.

## Validation evidence

- `dbt parse`/compile evidence and a documented DAG.
- Model contract, data-test, snapshot-history, and incremental-idempotency tests.
- Mid-build failure test proving active facts, metrics, and work queues remain byte-for-byte unchanged.
- Metric contract scenario suite and warehouse-to-report parity queries.
- Priority boundary, determinism, exclusion, and explanation tests.
- Published dbt manifest and run results linked from the publication record.

## Revisit triggers

- A governed metric cannot be represented safely in BigQuery SQL.
- The number of teams or projects requires cross-project semantic governance beyond the current relations.
- Priority policy needs an approved statistical model backed by representative governed outcomes.
- dbt Core operations become the dominant reliability constraint.
- A material dbt or BigQuery adapter capability change affects the chosen strategies.

## References

- [Configure dbt incremental models](https://docs.getdbt.com/docs/build/incremental-models)
- [Add dbt data tests to a DAG](https://docs.getdbt.com/docs/build/data-tests)
- [Add dbt snapshots to a DAG](https://docs.getdbt.com/docs/build/snapshots)
