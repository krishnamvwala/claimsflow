# ClaimsFlow Acceptance-Criteria Matrix

**Document status:** Baseline draft

**Blueprint phase:** Phase 0 - Discovery and Success Contract

**Source requirements:** [ClaimsFlow Requirements](requirements.md)

**Data boundary:** Synthetic portfolio data only

## 1. Purpose

This document translates the ClaimsFlow requirements into observable, testable completion conditions. A feature is not complete merely because its code exists; it is complete only when its criterion passes and the required evidence is retained.

Every requirement in `requirements.md` is linked to exactly one primary acceptance criterion below. A test may satisfy more than one criterion, but every criterion must remain independently traceable.

## 2. How to use this matrix

- **Given / When / Then** defines the expected behavior without prescribing the implementation.
- **Evidence** identifies the artifact needed to prove the behavior.
- **Test level** identifies the lowest appropriate verification boundary.
- **Release gate** defines whether failure blocks the phase or release shown in the final column.
- **Phase** identifies when the criterion must first pass. It must continue passing in later releases.
- Every implementation issue and pull request must cite the applicable requirement and acceptance-criterion identifiers.
- Exact schemas, thresholds, tolerances, schedules, formulas, and scoring weights will be supplied by the source-data contracts, metric dictionary, and architecture decision records.

### Test-level vocabulary

| Test level | Meaning |
| --- | --- |
| Unit | Isolated deterministic function, rule, parser, or calculation test |
| Contract | Schema, interface, configuration, or documentation contract test |
| Integration | Multiple components or a real local/cloud service boundary |
| dbt | dbt model, schema, relationship, freshness, or business-rule test |
| End-to-end | Source delivery through trusted or operational output |
| Security | Secret, identity, access, masking, or threat-control verification |
| Performance | Scale, scan, duration, query-plan, or resource-use verification |
| Visual/UAT | Human-verifiable dashboard, workflow, accessibility, or decision test |
| Documentation | Review of required instructions, decisions, limitations, or evidence |

### Release-gate vocabulary

| Gate | Meaning |
| --- | --- |
| Blocker | The owning phase or version 1 release cannot be accepted while the criterion fails |
| Conditional | Release requires an explicitly approved, documented exception with owner and expiration |

## 3. Ingestion and lineage criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-ING-001 | FR-ING-001 | **Given** valid synthetic files for every supported source family, **when** a scheduled incremental run executes, **then** each file is loaded once into its expected raw destination and its batch is auditable. | End-to-end run manifest, raw row counts, and supported-source fixture inventory | End-to-end | Blocker | 2 |
| AC-ING-002 | FR-ING-002 | **Given** two distinct deliveries, **when** they are registered, **then** each receives a non-null unique batch identifier that remains stable across the run. | Uniqueness test and batch-audit rows | Integration | Blocker | 2 |
| AC-ING-003 | FR-ING-003 | **Given** an ingested file, **when** its batch audit is queried, **then** source system, file name, checksum, batch ID, ingestion time, processing status, and source-to-target lineage are present. | Batch-audit contract test and sample audit record | Contract | Blocker | 2 |
| AC-ING-004 | FR-ING-004 | **Given** the complete raw-record population, **when** lineage integrity is validated, **then** every record has a non-null stable source-file and source-row or source-record key, every key resolves to exactly one registered source delivery, and no orphan or duplicate lineage relationship exists at the documented grain. | Full-population missing-key, orphan, relationship-cardinality, and uniqueness tests plus bidirectional lineage queries | Integration | Blocker | 2 |
| AC-ING-005 | FR-ING-005 | **Given** a successfully processed batch and its accepted-state snapshot, **when** the identical batch is processed again, **then** the business-key set, stable per-record content hashes, business-row counts, and published financial totals are identical and no duplicate record exists. | Replay test with full business-key and stable-hash set comparison, duplicate checks, and before-and-after counts and amounts | End-to-end | Blocker | 2 |
| AC-ING-006 | FR-ING-006 | **Given** a file with a previously accepted checksum and source identity, **when** it is delivered again, **then** the duplicate is detected and the recorded decision explains why it was not republished. | Duplicate-delivery test and audit decision | Integration | Blocker | 2 |
| AC-ING-007 | FR-ING-007 | **Given** a downstream correction or normalization, **when** the original raw record is queried, **then** its source values remain unchanged and available for replay. | Immutability test comparing raw and corrected evidence | Integration | Blocker | 2 |
| AC-ING-008 | FR-ING-008 | **Given** an identified batch or bounded date window, **when** an authorized replay or backfill runs, **then** only the requested scope is processed and the outcome is auditable and idempotent. | Replay/backfill scenario, parameters, audit trail, and reconciliation | End-to-end | Blocker | 2 |

## 4. Data-quality and quarantine criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-DQ-001 | FR-DQ-001 | **Given** a batch containing identity, completeness, code, date, financial, duplicate, freshness, and reconciliation cases, **when** validation runs, **then** every configured rule family executes before trusted publication. | Rule-execution manifest and fixture-to-rule coverage report | Integration | Blocker | 3 |
| AC-DQ-002 | FR-DQ-002 | **Given** one fixture for each enumerated defect, **when** validation runs, **then** every defect produces its expected rule and disposition. | Parameterized validation tests covering every listed defect | Unit | Blocker | 3 |
| AC-DQ-003 | FR-DQ-003 | **Given** any failed or warned validation, **when** its result is inspected, **then** rule ID, severity, disposition, reason, affected field or record, and processing time are populated. | Validation-result schema test and representative records | Contract | Blocker | 3 |
| AC-DQ-004 | FR-DQ-004 | **Given** fixtures for all four dispositions, **when** validation completes, **then** records are classified as accepted, warned, quarantined, or rejected according to the versioned severity map. | Disposition mapping tests and severity configuration | Unit | Blocker | 3 |
| AC-DQ-005 | FR-DQ-005 | **Given** a safely normalizable value, **when** its documented rule runs repeatedly, **then** it produces the same corrected value, records the rule, and passes its post-normalization validation. | Determinism and post-validation tests plus rule documentation | Unit | Blocker | 3 |
| AC-DQ-006 | FR-DQ-006 | **Given** an ambiguous identity, code, financial, or deadline value, **when** validation runs, **then** the record is quarantined with a clear reason and is absent from trusted models. | Negative fixture, quarantine record, and curated anti-join test | Integration | Blocker | 3 |
| AC-DQ-007 | FR-DQ-007 | **Given** a critical rule or reconciliation failure, **when** the pipeline reaches its publication gate, **then** dependent trusted models are not published and an actionable failure is recorded. | Failure-injection run, blocked task state, and alert evidence | End-to-end | Blocker | 3 |
| AC-DQ-008 | FR-DQ-008 | **Given** a quarantined record with a verified correction or disposition, **when** it is reprocessed, **then** both original and revised values, actor or source, time, reason, and outcome remain queryable. | Correction-history contract test and audit query | Integration | Blocker | 3 |
| AC-DQ-009 | FR-DQ-009 | **Given** a completed batch, **when** disposition counts are summed, **then** accepted plus warned plus quarantined plus rejected equals the raw input count with no unexplained records. | Automated batch count reconciliation | dbt | Blocker | 3 |
| AC-DQ-010 | FR-DQ-010 | **Given** processed batches from multiple sources, **when** quality reporting is queried, **then** rates, failed-rule distribution, freshness, quarantine volume, and reconciliation history are available by batch and source. | Quality mart tests and representative reporting query | dbt | Blocker | 3 |

## 5. Warehouse and transformation criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-WH-001 | FR-WH-001 | **Given** a successful run, **when** storage and dbt lineage are inspected, **then** landing, raw, validated, curated, semantic, and operational responsibilities are distinct with no prohibited layer bypass. | Architecture map, dataset inventory, and dependency test | Contract | Blocker | 4 |
| AC-WH-002 | FR-WH-002 | **Given** curated facts, **when** their keys and row behavior are tested, **then** claim, claim-line, payment, denial, and appeal models each conform to their documented grain. | Grain documentation plus uniqueness and duplicate tests | dbt | Blocker | 4 |
| AC-WH-003 | FR-WH-003 | **Given** facts that share patient, provider, payer, facility, diagnosis, procedure, denial reason, or date concepts, **when** joined through conformed keys, **then** the relationships resolve according to documented cardinality. | Relationship tests and conformance query suite | dbt | Blocker | 4 |
| AC-WH-004 | FR-WH-004 | **Given** any published dbt model, **when** generated documentation is inspected, **then** grain, purpose, fields, dependencies, owner, and materialization are present. | dbt documentation coverage check | Documentation | Blocker | 4 |
| AC-WH-005 | FR-WH-005 | **Given** a release candidate, **when** `dbt build` runs, **then** required uniqueness, not-null, relationship, accepted-value, reconciliation, and custom business tests pass. | Successful dbt build artifact and test manifest | dbt | Blocker | 4 |
| AC-WH-006 | FR-WH-006 | **Given** a tracked reference or status value that changes, **when** the new version is processed, **then** prior and current states remain distinguishable at the documented effective times. | Snapshot or history-model scenario test | dbt | Blocker | 4 |
| AC-WH-007 | FR-WH-007 | **Given** accepted source financial totals, **when** curated facts are aggregated under the documented convention, **then** the variance is within the approved tolerance and is reported. | Automated financial reconciliation with tolerance evidence | dbt | Blocker | 4 |
| AC-WH-008 | FR-WH-008 | **Given** BI model connections and queries, **when** their sources are inspected, **then** they reference only approved semantic or operational objects and not raw tables. | Connection inventory and prohibited-source scan | Contract | Blocker | 7 |

## 6. Metric-governance criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-MET-001 | FR-MET-001 | **Given** the metric dictionary, **when** completeness is checked, **then** denial rate, clean-claim rate, first-pass acceptance, days in A/R, outstanding balance, net collection rate, appeal success rate, and recovered revenue are defined and implemented. | Metric-dictionary coverage test and model references | Contract | Blocker | 4 |
| AC-MET-002 | FR-MET-002 | **Given** any governed metric, **when** its definition is inspected, **then** grain, numerator, denominator, inclusions, exclusions, time convention, null behavior, and owner are stated. | Metric-definition schema checklist | Documentation | Blocker | 4 |
| AC-MET-003 | FR-MET-003 | **Given** a denial cohort with valid relationships, **when** users filter by payer, provider, facility, procedure, diagnosis, denial reason, or time, **then** results reconcile to the unfiltered governed total under the documented rules. | Dimensional slice-and-reconcile test suite | dbt | Blocker | 4 |
| AC-MET-004 | FR-MET-004 | **Given** the same filter context, **when** a metric is viewed in leadership and operational outputs, **then** both return the same value and definition version. | Cross-report semantic reconciliation | Integration | Blocker | 7 |
| AC-MET-005 | FR-MET-005 | **Given** any published KPI, **when** its documented warehouse or semantic query is executed for the same filter context, **then** the result matches the published value within the stated display-rounding rule. | KPI-to-query reconciliation pack | Integration | Blocker | 7 |

## 7. Denial-priority criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-PRI-001 | FR-PRI-001 | **Given** eligible denied claims, **when** the active deterministic rules execute, **then** exactly one current priority record is produced per eligible claim. | Eligibility-to-priority count and uniqueness tests | dbt | Blocker | 6 |
| AC-PRI-002 | FR-PRI-002 | **Given** controlled fixtures that vary one factor at a time, **when** scoring runs, **then** recoverable amount, deadline urgency, resolution rate, payer response behavior, documentation readiness, and claim age affect results exactly as specified. | Factor-isolation and boundary test suite | Unit | Blocker | 6 |
| AC-PRI-003 | FR-PRI-003 | **Given** a scoring release, **when** configuration is inspected, **then** inputs, weights, thresholds, exclusions, bands, and a unique immutable rule version are recorded in version control. | Versioned scoring configuration and contract check | Contract | Blocker | 6 |
| AC-PRI-004 | FR-PRI-004 | **Given** identical inputs and rule version across repeated runs, **when** results are compared, **then** score, band, and explanation are identical. | Repeatability test with stable output hash | Unit | Blocker | 6 |
| AC-PRI-005 | FR-PRI-005 | **Given** any priority record, **when** it is inspected, **then** claim ID, score, band, amount, days remaining, reasons, blockers, rule version, calculation time, and lineage are populated. | Priority-output schema and completeness tests | Contract | Blocker | 6 |
| AC-PRI-006 | FR-PRI-006 | **Given** claims failing at least one configured required identity, financial, or deadline check, regardless of the check's severity label, **when** scoring runs, **then** every such claim is absent from ranked output and present in a blocking-evidence output identifying each failed required check. | Required-check fixture matrix, negative eligibility tests, and full anti-join reconciliation between failures and ranked output | dbt | Blocker | 6 |
| AC-PRI-007 | FR-PRI-007 | **Given** any priority output or user interface, **when** its available actions and language are inspected, **then** it recommends human review and exposes no automatic filing, submission, or approval action. | UAT checklist and interface/action inventory | Visual/UAT | Blocker | 7 |

## 8. Dashboard criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-BI-001 | FR-BI-001 | **Given** trusted semantic data, **when** a revenue-cycle manager opens the executive view, **then** denial trends, revenue exposure, A/R, recoveries, collection performance, and data quality are visible and filterable. | Executive-page UAT script and screenshots | Visual/UAT | Blocker | 7 |
| AC-BI-002 | FR-BI-002 | **Given** ranked eligible claims, **when** a billing specialist opens the operational view, **then** priority, deadlines, amounts, payer and reason concentrations, and claim-level evidence are accessible. | Operational-page UAT script and drill-through evidence | Visual/UAT | Blocker | 7 |
| AC-BI-003 | FR-BI-003 | **Given** defined dashboard filter contexts, **when** displayed totals are compared with governed queries, **then** all values match within the display-rounding rule. | Automated or recorded dashboard reconciliation pack | Integration | Blocker | 7 |
| AC-BI-004 | FR-BI-004 | **Given** normal, empty, stale, and failed-refresh states, **when** reports are reviewed, **then** metric definitions, refresh context, active filters, and appropriate empty or error messages are visible. | State-based visual acceptance checklist | Visual/UAT | Blocker | 7 |

## 9. Operational-alert criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-ALT-001 | FR-ALT-001 | **Given** fixtures immediately below, exactly at, and immediately above the configured high-value threshold and immediately outside, exactly at, and inside the active filing or appeal window, **when** alert evaluation runs, **then** each claim satisfying both configured boundary comparators appears exactly once with amount and days remaining and every nonqualifying or expired claim produces no alert. | Amount-and-deadline boundary matrix with qualifying alerts and non-alert assertions | Integration | Blocker | 6 |
| AC-ALT-002 | FR-ALT-002 | **Given** payer and denial-category rates immediately below, exactly at, and immediately above the configured spike threshold, **when** alert evaluation runs, **then** only the above-threshold cohorts alert and each alert identifies the cohort, baseline, observed value, and variance. | Below/at/above threshold test with alert and non-alert assertions | Integration | Blocker | 6 |
| AC-ALT-003 | FR-ALT-003 | **Given** an injected failure in ingestion, transformation, validation, reconciliation, or publication, **when** orchestration handles it, **then** a failure alert identifies the stage and affected batch or run. | Failure-injection matrix and emitted alerts | End-to-end | Blocker | 5 |
| AC-ALT-004 | FR-ALT-004 | **Given** quality rates and source ages on the passing side, exactly at the boundary, and on the breaching side of each rule's versioned threshold and comparator, **when** monitoring evaluates them, **then** only cases satisfying that rule's configured breach expression alert and each alert reports expected, observed, comparator, severity, and affected source or batch. | Comparator-aware quality/freshness boundary matrix covering minimum and maximum rules with alert and non-alert assertions | Integration | Blocker | 5 |
| AC-ALT-005 | FR-ALT-005 | **Given** payment variances inside, exactly at, and immediately outside the documented tolerance in both directions, **when** reconciliation runs, **then** only outside-tolerance cases alert and each alert identifies the claim or batch, compared amounts, tolerance, and variance. | Two-sided financial-variance boundary matrix with alert and non-alert assertions | Integration | Blocker | 6 |
| AC-ALT-006 | FR-ALT-006 | **Given** unresolved claim volumes and ages immediately below, exactly at, and immediately above their configured backlog thresholds, **when** monitoring runs, **then** only above-threshold cases alert and each alert identifies the affected cohort, threshold, and observed backlog. | Volume-and-age below/at/above boundary tests with alert and non-alert assertions | Integration | Blocker | 6 |
| AC-ALT-007 | FR-ALT-007 | **Given** any generated alert, **when** its contract is validated, **then** source, batch or claim context, reason, time, severity, and review evidence are present. | Alert-schema contract test across all alert types | Contract | Blocker | 6 |

## 10. Orchestration and operations criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-OPS-001 | FR-OPS-001 | **Given** an Airflow DAG run, **when** its graph is inspected, **then** ingestion, validation, dbt, reconciliation, and publication execute in the documented dependency order. | DAG-structure test and successful run graph | Integration | Blocker | 5 |
| AC-OPS-002 | FR-OPS-002 | **Given** every production-path task, **when** configuration is inspected, **then** retry, timeout, dependency, backfill, and failure-callback behavior are explicitly defined or inherited from an approved default. | DAG policy test and documented defaults | Contract | Blocker | 5 |
| AC-OPS-003 | FR-OPS-003 | **Given** successful and failed tasks, **when** operational audit data is queried, **then** start, end, status, duration, row counts, quality outcomes, and applicable error context are present. | Operational-audit schema and completeness tests | Integration | Blocker | 5 |
| AC-OPS-004 | FR-OPS-004 | **Given** a required upstream or critical-gate failure, **when** the DAG continues evaluation, **then** downstream publication remains unexecuted or blocked. | Dependency failure-injection test | End-to-end | Blocker | 5 |
| AC-OPS-005 | FR-OPS-005 | **Given** each documented common failure, **when** a reviewer follows the runbook, **then** the failure can be diagnosed and safely retried, replayed, or escalated using the stated steps. | Runbook tabletop test and recovery record | Documentation | Blocker | 5 |
| AC-OPS-006 | FR-OPS-006 | **Given** a failed run with no prior context, **when** a reviewer uses only operational evidence, **then** the batch, task, rule, impact, and recommended recovery action can be identified. | Timed reviewer exercise and evidence checklist | Visual/UAT | Blocker | 5 |

## 11. Privacy and security criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-SEC-001 | NFR-SEC-001 | **Given** every project data path and artifact, including ingress, project-managed storage, processing, logs, exports, dashboards, fixtures, reports, screenshots, and committed files, **when** runtime controls and release provenance checks execute, **then** every accepted record is traceable to an approved synthetic generator or fixture, unverified input is rejected before entering project-managed storage or processing, and no real personal or customer data is retained or displayed. | Complete data-path inventory, synthetic-provenance manifest, ingress rejection test using a safe non-sensitive canary, runtime storage/output scan, and release review | Security | Blocker | 1/8 |
| AC-SEC-002 | NFR-SEC-002 | **Given** any user-facing dataset, report, screenshot, or document, **when** reviewed, **then** its synthetic/non-production status is clear and not reasonably confusable with real patient data. | Labeling checklist and portfolio review | Visual/UAT | Blocker | 8/9 |
| AC-SEC-003 | NFR-SEC-003 | **Given** a commit or release candidate, **when** secret scanning runs, **then** no credential, token, private key, connection string, or prohibited secret is detected. | Passing secret-scan result | Security | Blocker | 1/8 |
| AC-SEC-004 | NFR-SEC-004 | **Given** each cloud identity and environment, **when** IAM configuration is reviewed, **then** permissions are limited to required resources/actions and development/test boundaries are distinct. | Terraform/IAM policy review and least-privilege matrix | Security | Blocker | 1/8 |
| AC-SEC-005 | NFR-SEC-005 | **Given** the version 1 design, **when** the security documentation is reviewed, **then** masking, RBAC, audit, encryption, retention, and threat assumptions show implemented controls and explicit production gaps. | Threat model and security-control matrix | Documentation | Blocker | 1/8 |
| AC-SEC-006 | NFR-SEC-006 | **Given** every pull request and release workflow, **when** CI executes, **then** an approved secret-scanning gate runs and blocks on an unapproved finding. | CI workflow test with safe synthetic canary | Security | Blocker | 1/8 |

## 12. Reliability and data-integrity criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-REL-001 | NFR-REL-001 | **Given** the same accepted input and configuration, **when** the complete batch pipeline is run more than once, **then** trusted state and financial totals are unchanged after the first successful run. | End-to-end idempotency test and state comparison | End-to-end | Blocker | 5 |
| AC-REL-002 | NFR-REL-002 | **Given** retry, replay, and backfill scenarios, **when** each completes, **then** accepted record keys and financial totals show neither duplicates nor unexplained loss. | Scenario matrix with key and amount reconciliations | End-to-end | Blocker | 5 |
| AC-REL-003 | NFR-REL-003 | **Given** a trusted publication, **when** its release evidence is queried, **then** passing validation, dbt tests, source freshness, and reconciliation are linked to that publication. | Publication manifest with gate references | Contract | Blocker | 5 |
| AC-REL-004 | NFR-REL-004 | **Given** an injected partial failure, **when** the run stops, **then** completed and incomplete work is distinguishable, no unsafe publication occurs, and documented recovery succeeds. | Partial-failure injection and recovery transcript | End-to-end | Blocker | 5 |
| AC-REL-005 | NFR-REL-005 | **Given** the automated test inventory, **when** coverage is checked, **then** happy path, late and duplicate delivery, malformed input, partial failure, boundaries, nulls, and replay each have a passing test. | Required-scenario coverage manifest | Contract | Blocker | 8 |

## 13. Performance and scale criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-PERF-001 | NFR-PERF-001 | **Given** a synthetic monthly workload of at least 100,000 claims plus related claim lines, payments, denials, and appeals and a version-controlled pre-run manifest fixing the reference environment, 20-request operational suite, filter and pagination mix, representative query corpus, and test parameters, **when** the full monthly pipeline and that exact suite run, **then** the pipeline finishes within 30 minutes, each operational request returns at most 500 records with a warm-cache p95 server response time of at most 5 seconds, each corpus query scans at most 1 GiB, and browser memory grows by at most 200 MiB during a 30-minute workflow without loading the full dataset. | Pre-run versioned manifest containing workload, environment, request/query identifiers, parameters, filters, and pagination mix plus a scale report recording duration, per-query scanned bytes, page sizes, 20-request latency distribution, and browser-memory measurements | Performance | Conditional | 8 |
| AC-PERF-002 | NFR-PERF-002 | **Given** major BigQuery facts and marts, **when** table design and representative query plans are reviewed, **then** partitioning and clustering match documented filter/join patterns. | Table metadata and representative query-plan review | Performance | Blocker | 4 |
| AC-PERF-003 | NFR-PERF-003 | **Given** a bounded new batch or changed period, **when** incremental processing runs, **then** unaffected history is not rebuilt or rescanned beyond the documented merge/lookback window. | Incremental-run query/job evidence | Performance | Blocker | 4 |
| AC-PERF-004 | NFR-PERF-004 | **Given** representative dashboard queries, **when** query plans and row counts are reviewed, **then** no unexplained full scans, many-to-many explosions, or unused joins remain. | Query-performance checklist and before/after evidence for findings | Performance | Conditional | 7/8 |

## 14. Maintainability and reproducibility criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-MNT-001 | NFR-MNT-001 | **Given** deployed infrastructure and pipeline behavior, **when** repository coverage is reviewed, **then** infrastructure, transformations, orchestration, and validation are represented by version-controlled code or configuration. | Repository-to-runtime component inventory | Documentation | Blocker | 1/8 |
| AC-MNT-002 | NFR-MNT-002 | **Given** a clean environment and a reviewer unfamiliar with the project, **when** documented setup steps are followed, **then** the local core workflow or documented cloud plan can be reproduced without undocumented commands. | Clean-setup rehearsal and issue log | End-to-end | Blocker | 1/9 |
| AC-MNT-003 | NFR-MNT-003 | **Given** a pull request changing each component family, **when** CI runs, **then** applicable formatting, linting, unit, dbt, Terraform, and documentation checks execute and report status. | CI path-coverage matrix and workflow runs | Integration | Blocker | 1/8 |
| AC-MNT-004 | NFR-MNT-004 | **Given** a material architecture, metric, severity, scope, or scoring change, **when** it is proposed, **then** the pull request includes an approved decision or documentation update describing impact. | PR-template gate and representative decision record | Documentation | Blocker | 1/8 |
| AC-MNT-005 | NFR-MNT-005 | **Given** a release candidate, **when** dependencies and release metadata are inspected, **then** material dependencies are constrained and the release version, commit, and known limitations are recorded. | Lock/constraint files and release manifest | Contract | Blocker | 8 |

## 15. Explainability and auditability criteria

| Criterion | Requirement | Given / When / Then | Required evidence | Test level | Gate | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| AC-AUD-001 | NFR-AUD-001 | **Given** the complete trusted-record population, **when** lineage integrity is validated, **then** every trusted record has non-null lineage keys that resolve through exactly one batch to a registered source delivery and original source record, with no orphan, duplicate, or ambiguous path at the documented grain. | Full-population missing-key, orphan, referential-integrity, path-cardinality, and uniqueness tests plus bidirectional lineage queries | Integration | Blocker | 4 |
| AC-AUD-002 | NFR-AUD-002 | **Given** any quarantined or rejected record, **when** its decision is inspected, **then** the rule, severity, evidence, reason, and processing time are available. | Quarantine/rejection audit completeness test | Integration | Blocker | 3 |
| AC-AUD-003 | NFR-AUD-003 | **Given** any priority decision, **when** its audit detail is inspected, **then** inputs, rule version, leading reasons, calculation time, and lineage are available. | Priority audit completeness and reproducibility test | Integration | Blocker | 6 |
| AC-AUD-004 | NFR-AUD-004 | **Given** any material metric shown to a user, **when** its lineage is followed, **then** the definition version and reproducible model/query are identified. | Metric-to-model traceability test | Integration | Blocker | 7 |
| AC-AUD-005 | NFR-AUD-005 | **Given** the public repository and demo, **when** reviewed, **then** synthetic assumptions, non-production boundaries, known limitations, and prohibited interpretations are visible. | Public-documentation and demo checklist | Visual/UAT | Blocker | 9 |

## 16. Cross-phase end-to-end acceptance scenarios

These scenarios combine individual criteria into the customer story that the final portfolio demonstration must prove.

| Scenario | Required behavior | Principal criteria | Release evidence |
| --- | --- | --- | --- |
| E2E-001 - Healthy batch | A valid scheduled batch is registered, loaded once, validated, transformed, reconciled, published, and exposed through governed outputs. | AC-ING-001, AC-ING-002, AC-ING-003, AC-DQ-001, AC-WH-005, AC-WH-007, AC-REL-003 | Run manifest, reconciliation, passing dbt build, and output query |
| E2E-002 - Duplicate delivery | The same delivered file is detected; replay changes neither trusted business keys, stable record hashes, row counts, nor financial totals. | AC-ING-005, AC-ING-006, AC-REL-001, AC-REL-002 | Duplicate audit decision and full before/after key, hash, count, and amount comparison |
| E2E-003 - Unsafe payer batch | Invalid identity, code, date, and financial records are classified correctly; critical failures block publication and preserve evidence. | AC-DQ-002, AC-DQ-004, AC-DQ-006, AC-DQ-007, AC-AUD-002 | Fixture results, quarantine evidence, and blocked publication |
| E2E-004 - Verified correction | A quarantined record is corrected without overwriting raw evidence, revalidated, and published only after all blocking validation, test, freshness, and reconciliation gates pass. | AC-ING-007, AC-DQ-005, AC-DQ-007, AC-DQ-008, AC-DQ-009, AC-REL-003 | Original/revised audit, post-validation result, reconciliation, blocked-publication failure injection, and publication manifest linked to passing gate evidence |
| E2E-005 - Denial investigation | A denial spike is visible by governed dimensions and reconciles between warehouse, executive, and operational views. | AC-MET-003, AC-MET-004, AC-MET-005, AC-BI-001, AC-BI-003, AC-ALT-002 | Slice queries, dashboard reconciliation, and spike alert |
| E2E-006 - Deadline prioritization | An eligible high-value denied claim is ranked reproducibly, explained, and alerted before its deadline; unsafe claims are withheld. | AC-PRI-001 through AC-PRI-007, AC-ALT-001, AC-AUD-003 | Scoring tests, priority evidence, exclusion reconciliation, and alert |
| E2E-007 - Operational failure and recovery | An injected failure blocks publication, records actionable evidence, alerts the engineer, and succeeds on an idempotent retry without duplicate, replaced, or lost accepted records. | AC-ALT-003, AC-OPS-003 through AC-OPS-006, AC-REL-002, AC-REL-004 | Failure and recovery run, alert, audit, and full before/after accepted-business-key, stable-hash, count, and amount reconciliation |
| E2E-008 - Public portfolio release | CI, security, scale, setup, documentation, and synthetic-data gates pass for a tagged release. | AC-SEC-001 through AC-SEC-006, AC-PERF-001, AC-MNT-002, AC-MNT-003, AC-MNT-005, AC-AUD-005 | Release manifest, CI run, security review, scale report, and demo checklist |

## 17. Traceability rules and completeness

- The baseline requirements contain 80 unique requirement identifiers.
- This matrix contains 80 unique primary acceptance-criterion identifiers.
- Every baseline requirement must appear exactly once in the primary matrices in sections 3 through 15.
- Cross-phase scenarios may reference acceptance criteria multiple times and do not replace primary traceability.
- A requirement without a criterion, or a criterion without a valid requirement, is a release-blocking documentation defect.
- When a requirement changes, its criterion and affected end-to-end scenarios must be reviewed in the same pull request.

## 18. Acceptance-matrix definition of done

This artifact is ready for baseline approval when:

- All 80 requirements are mapped exactly once.
- All 80 criterion identifiers are unique.
- Every criterion states observable Given/When/Then behavior.
- Every criterion identifies evidence, a test level, release-gate behavior, and an owning implementation phase.
- Critical data-quality, financial, security, publication, and audit failures are release blockers.
- Conditional performance gates require a documented exception rather than silent acceptance.
- The final customer demo is represented by cross-phase end-to-end scenarios.
- The matrix contains no claim that synthetic results prove real healthcare or financial outcomes.

## 19. Next Phase 0 artifact

Create the initial architecture decision records for BigQuery, dbt, Airflow, Python, Power BI, security, and deployment boundaries. The governed metric dictionary is maintained in [`docs/metric-dictionary`](metric-dictionary/README.md).
