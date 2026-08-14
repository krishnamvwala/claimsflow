---
adr_id: ADR-005
title: Power BI connectivity, refresh, semantic governance, and report states
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Business Intelligence
  - Revenue Cycle Operations
requirements: [FR-BI-001, FR-BI-002, FR-BI-003, FR-BI-004]
acceptance_criteria: [AC-BI-001, AC-BI-002, AC-BI-003, AC-BI-004]
supersedes: []
---

# ADR-005: Power BI connectivity, refresh, semantic governance, and report states

## Context

ClaimsFlow needs an executive view and an actionable billing work queue that agree with governed warehouse metrics. Reports must expose freshness, filter context, definitions, empty/error states, and drill-through evidence without granting BI users access to raw or quarantined records.

## Decision

Use the supported Google BigQuery connector from Power BI to read only BigQuery semantic and operational datasets. Use Import mode with incremental refresh for version 1 executive and operational models. Permit DirectQuery only through a future, measured decision for a genuinely near-real-time use case.

## Decision details

- One centrally governed Power BI semantic model serves executive and operational report pages. It uses a star schema, single-direction relationships by default, conformed dimensions, explicit measures, hidden technical keys, and a dedicated measure table.
- Power Query selects only named versioned semantic/operational views. It does not recreate joins, validation rules, metric filters, signs, time boundaries, or priority weights.
- Import mode is the baseline because the portfolio uses scheduled batches and benefits from predictable report interaction. Incremental refresh partitions eligible fact data by a UTC event/as-of field using `RangeStart` and `RangeEnd`; the lookback covers the documented late-arrival window.
- Every warehouse publication manifest declares the complete affected BI partition ranges, including an explicitly bounded historical replay outside the routine lookback. The refresh targets the union of the routine window and all declared affected ranges. If a code, contract, dictionary, correction, or other change has unbounded historical impact—or its affected ranges cannot be proven complete—the publication requires a full semantic-model refresh.
- Refresh begins only after Airflow advances a successful publication. The refresh is serialized with publication advancement and pins one explicit `publication_id` for every partition/query in the run. The report stores publication ID, warehouse publication time, Power BI refresh time, dictionary version, and active data interval.
- DAX measures consume governed numerator/denominator columns and reproduce only presentation-safe operations such as division and rounding defined by the metric contract. Every KPI exposes its name, definition, time convention, last refresh, and active filters.
- The operational work queue displays claim ID, priority band/score, recoverable amount, deadline, leading reasons, blocking conditions, rule version, and drill-through evidence. It supports pagination/filtering and never loads the entire operational population into a visual.
- Report acceptance includes normal, empty, stale, and failed-refresh states. Stale or failed states remain visible and do not present old values as current.
- Dashboard reconciliation exports the filter context and compares displayed values with versioned warehouse queries under the display-rounding rule.
- Row-level security roles are designed and tested for future clinic or functional separation, but the public synthetic demo uses one read-only demo role and clearly states that this is not a production authorization model.

## Alternatives considered

### DirectQuery for every report page

Rejected because scheduled batch data does not need query-per-interaction freshness, and unmanaged DirectQuery can increase latency, concurrency, and BigQuery scan cost.

### Import raw BigQuery tables and model in Power BI

Rejected because this would bypass validated/semantic boundaries and allow report-specific business logic to diverge from dbt.

### Separate executive and operational semantic models

Rejected for version 1 because shared metrics and dimensions would be duplicated. Separate models may be reconsidered if measured scale, ownership, or security boundaries require them.

## Consequences

### Positive

- Report interactions are responsive and insulated from repeated warehouse scans.
- Executive and operational pages share definitions and conformed dimensions.
- Refresh and publication context make staleness visible.
- BigQuery permissions can be narrowly limited to consumer contracts.

### Trade-offs

- Import mode is not real-time and adds a second refresh operation after warehouse publication.
- Incremental refresh needs stable event fields, partition policy, and late-arrival testing.
- Power BI service authentication and workspace governance still require platform-specific setup outside the public repository.

## Security and privacy

The BI identity has read and job permissions only for approved semantic and operational relations in the dev/demo environment. It cannot list or read landing, raw, validated-internal, quarantine, or audit datasets. Export/download settings and workspace access are restricted for the demo. Synthetic/non-production labeling appears on every page.

## Reliability and recovery

A failed warehouse publication does not trigger refresh. A failed Power BI refresh leaves the previous model available with a visible failed/stale state and emits an operational alert. A normal forward publication may use incremental refresh only when its manifest proves complete affected partition ranges; the refresh must include those ranges even when they fall outside the routine lookback. Unbounded historical impact requires a full refresh. Publication rollback always invalidates all imported partitions and performs a full semantic-model refresh for the selected prior publication. In every path, post-refresh reconciliation must prove that all affected values match the warehouse and every imported row resolves to the one selected publication ID before the report is marked current.

## Validation evidence

- Semantic-model relationship, measure, and hidden-field review.
- Import/incremental-refresh configuration and late-arrival fixture test.
- Historical-backfill test that changes a partition outside the routine lookback and proves that partition is refreshed.
- Unbounded code/dictionary-impact test that requires a full refresh rather than an incremental refresh.
- Rollback test proving a full refresh contains exactly one selected publication ID across every partition.
- Warehouse-to-dashboard reconciliation for representative filter contexts.
- Performance test for the 20-request operational suite and executive interactions.
- Visual/UAT checklist for normal, empty, stale, failed, filtered, and drill-through states.

## Revisit triggers

- A validated decision requires sub-refresh-latency operational data.
- Imported model size or refresh duration exceeds the agreed budget.
- Security requires distinct models or workspaces rather than row-level roles.
- The connector implementation changes materially.
- Report query evidence shows unacceptable model cardinality or relationship behavior.

## References

- [Google BigQuery connector for Power Query](https://learn.microsoft.com/en-us/power-query/connectors/google-bigquery)
- [Power BI incremental refresh overview](https://learn.microsoft.com/en-us/power-bi/connect-data/incremental-refresh-overview)
- [Understand star schema for Power BI](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
