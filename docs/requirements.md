# ClaimsFlow Requirements

**Document status:** Baseline draft

**Blueprint phase:** Phase 0 - Discovery and Success Contract

**Product:** ClaimsFlow - Healthcare Claims, Denial Prevention, and Revenue Recovery Platform

**Data boundary:** Synthetic portfolio data only

## 1. Purpose

This document defines the customer problem, users, scope, required system behavior, operating qualities, constraints, and measurable outcomes for ClaimsFlow. It is the first implementation contract for the project.

The requirements describe what the platform must accomplish and why. Detailed source schemas, metric formulas, scoring weights, and architecture decisions will be defined in separate Phase 0 artifacts and linked back to the requirement identifiers in this document.

## 2. Fictional customer

The customer is a fictional regional healthcare provider that operates 20 clinics and processes approximately 100,000 medical claims per month.

Claims and revenue-cycle data arrive from multiple EHR systems, a clearinghouse, payer remittance files, eligibility feeds, reference files, and billing spreadsheets. The sources use inconsistent structures, identifiers, codes, and delivery schedules.

All organizations, people, claims, payments, and outcomes used by this project are fictional or synthetically generated. ClaimsFlow is not a production billing, clinical, or claims-adjudication system.

## 3. Customer business problem

The revenue-cycle team cannot reliably determine which claims require immediate attention or why denials are increasing.

Data arrives in different formats, contains duplicates and missing values, and does not share consistent definitions. Analysts spend days cleaning and reconciling files before producing reports. Billing, Finance, and Operations may report different numbers for the same business question. By the time leadership receives the analysis, high-value claims may be approaching filing or appeal deadlines.

The organization is experiencing:

- High claim-denial rates.
- Slow identification and resolution of rejected claims.
- Inconsistent payer and denial-reason codes.
- Revenue at risk because filing or appeal deadlines may be missed.
- Manual reconciliation across spreadsheets and source systems.
- No dependable, shared view of accounts receivable and denial exposure.
- Conflicting financial and operational metrics across teams.
- Limited evidence explaining which denied claims should be handled first.

## 4. Product objective

ClaimsFlow will convert fragmented synthetic claims and remittance data into a governed revenue-cycle analytics operation.

The platform must help the customer:

1. Consolidate claims, claim lines, remittances, payments, eligibility, denial, appeal, and reference data.
2. Detect and isolate unsafe data before it reaches trusted reporting.
3. Identify the leading causes and concentrations of denials.
4. Prioritize denied claims using transparent, reproducible business rules.
5. Alert teams to approaching deadlines, quality failures, processing failures, payment variances, and unresolved backlogs.
6. Give Billing, Finance, Operations, and leadership consistent revenue-cycle metrics.
7. Trace published records, metrics, and priority decisions to their source and processing evidence.

### North-star outcome

Give revenue-cycle teams a trusted, timely, and explainable way to find the claims most likely to recover revenue before filing or appeal deadlines expire.

## 5. Primary users and decisions

| User | Primary decision | Required experience |
| --- | --- | --- |
| Revenue-cycle manager | Where is revenue at risk, and what should the team address first? | Executive KPIs, denial trends, backlog visibility, and a prioritized work queue |
| Billing specialist | Which claim should I work next, and why? | Claim-level priority, deadline, amount, reason, evidence, and blocking conditions |
| Data analyst | Can I trust and reproduce this metric? | Documented definitions, tested models, lineage, freshness, and reconciled totals |
| Data engineer | Did the pipeline complete correctly, and is the output current? | Batch audit, task status, logs, data-quality results, retries, and alerts |
| Compliance or security reviewer | Is sensitive access limited, synthetic, and auditable? | Synthetic-data evidence, least-privilege design, masking approach, and access/audit records |

## 6. Core user journeys

### Journey A - Process a new source batch

1. A scheduled claim, remittance, eligibility, billing, or reference file arrives.
2. ClaimsFlow records the file, batch identity, checksum, source, arrival time, and processing status.
3. The platform loads source-shaped raw records while preserving file and source-row lineage.
4. Validation classifies records as accepted, accepted with warning, quarantined, or rejected.
5. Critical quality or reconciliation failures stop trusted publication and generate evidence for investigation.
6. A successful batch publishes tested warehouse models and governed metrics.

### Journey B - Investigate a denial increase

1. A revenue-cycle manager sees an increase in denial rate.
2. The manager filters the trend by payer, provider, facility, procedure, and denial reason.
3. The manager reviews the affected claims and the underlying source and quality evidence.
4. The manager assigns operational attention based on financial exposure, urgency, and recurring cause.

### Journey C - Work the priority queue

1. A billing specialist opens the denied-claim work queue.
2. ClaimsFlow ranks eligible claims using the active deterministic rule version.
3. Each item displays the recoverable amount, deadline, priority band, leading reasons, and blocking conditions.
4. Claims with unsafe or incomplete data are withheld from ranking until the blocking condition is resolved.
5. The specialist uses the evidence to decide the next human action. ClaimsFlow does not automatically file or submit an appeal.

### Journey D - Diagnose and recover a failed run

1. A pipeline task, source-freshness check, data-quality threshold, or reconciliation gate fails.
2. ClaimsFlow records the affected batch, task, rule, counts, timestamps, and error context.
3. The data engineer follows the documented runbook and safely retries or replays the affected work.
4. The retry does not duplicate or silently lose records.
5. Publication resumes only after the required gates pass.

## 7. Scope

### 7.1 In scope for version 1

- Synthetic claim, claim-line, remittance, payment, eligibility, payer, provider, facility, diagnosis, procedure, denial, and appeal data.
- Scheduled and incremental batch ingestion.
- Immutable landing files and source-shaped raw warehouse tables.
- File, batch, record, and source-row lineage.
- Explicit validation, quarantine, warning, rejection, and republication contracts.
- Raw, validated, curated, semantic, and operational data layers.
- Dimensional claims analytics models built and tested with dbt.
- Governed revenue-cycle metric definitions.
- Airflow orchestration with retries, dependencies, backfill behavior, and failure callbacks.
- Operational audit tables, structured logs, freshness checks, and alerts.
- A deterministic and explainable denied-claim priority engine.
- Power BI executive dashboards and an operational work queue.
- Infrastructure configuration through Terraform.
- Continuous integration and controlled deployment workflows through GitHub Actions.
- Documentation, automated tests, reproducible demo data, and a portfolio case study.

### 7.2 Explicitly out of scope for version 1

- Real patient, provider, payer, employer, or customer data.
- Production use or representation as a HIPAA-compliant production service.
- Clinical decision support, medical advice, legal advice, or payer-policy interpretation.
- Automated claim submission, adjudication, payment posting, appeal filing, or payer communication.
- Full EDI 837 or 835 certification.
- A black-box machine-learning score represented as a factual prediction of recovery.
- A large custom web application duplicating the customer-facing role of PulseOps.
- Manual spreadsheet preparation as a required step in the trusted reporting workflow.
- Silent correction of ambiguous financial, identity, code, or deadline values.

## 8. Functional requirements

### 8.1 Ingestion and lineage

- **FR-ING-001:** The system shall ingest synthetic claims, claim lines, remittances, payments, eligibility, billing, and reference files on a scheduled and incremental basis.
- **FR-ING-002:** The system shall assign or record a unique batch identifier for every source delivery.
- **FR-ING-003:** The system shall record the source system, file name, checksum, batch identifier, ingestion timestamp, processing status, and source-to-target lineage.
- **FR-ING-004:** Every ingested record shall preserve a stable reference to its source file and original source-row position or source-record identifier.
- **FR-ING-005:** Reprocessing an identical batch shall not create duplicate business records or duplicate published financial amounts.
- **FR-ING-006:** The system shall detect duplicate file delivery and record the resulting decision in the batch audit.
- **FR-ING-007:** Raw source values shall remain available for replay and evidence and shall not be overwritten by downstream corrections.
- **FR-ING-008:** The system shall support controlled replay or backfill of an identified source batch or time window.

### 8.2 Validation and quarantine

- **FR-DQ-001:** The system shall validate identity, required fields, code formats, dates, financial relationships, duplicates, source freshness, and batch reconciliation before trusted publication.
- **FR-DQ-002:** Validation shall include missing claim or patient identifiers, duplicate claims, invalid diagnosis or procedure-code formats, invalid service dates, missing payer mappings, unknown denial codes, negative or inconsistent balances, payments exceeding permitted financial relationships, and missing filing or appeal deadlines.
- **FR-DQ-003:** Each validation result shall contain a stable rule identifier, severity, disposition, plain-language reason, affected field or record, and processing timestamp.
- **FR-DQ-004:** Records shall be classified as accepted, accepted with warning, quarantined, or rejected according to documented rule severity.
- **FR-DQ-005:** Safe formatting problems may be normalized automatically only through documented, deterministic, and tested rules.
- **FR-DQ-006:** Ambiguous values shall be quarantined with a clear failure reason rather than silently corrected or published.
- **FR-DQ-007:** Critical validation or reconciliation failures shall block dependent trusted publication.
- **FR-DQ-008:** The system shall preserve both the original evidence and any verified correction or disposition.
- **FR-DQ-009:** Accepted, warned, quarantined, and rejected counts shall reconcile to the raw batch count.
- **FR-DQ-010:** The system shall report data-quality rates, failed-rule distributions, freshness, quarantine volume, and reconciliation history by batch and source.

### 8.3 Warehouse and transformations

- **FR-WH-001:** The platform shall maintain separate landing, raw, validated, curated, semantic, and operational layers.
- **FR-WH-002:** The curated warehouse shall represent claims, claim lines, payments, denials, and appeals at documented grains.
- **FR-WH-003:** The curated warehouse shall use conformed dimensions for patient, provider, payer, facility, diagnosis, procedure, denial reason, and date concepts.
- **FR-WH-004:** dbt models shall document their grain, purpose, fields, dependencies, owner, and materialization strategy.
- **FR-WH-005:** Published models shall pass required uniqueness, not-null, relationship, accepted-value, reconciliation, and custom business-rule tests.
- **FR-WH-006:** Slowly changing reference or status information shall preserve history where the business decision requires it.
- **FR-WH-007:** Curated financial totals shall reconcile to accepted source totals within a documented tolerance.
- **FR-WH-008:** BI consumers shall query governed semantic or operational models rather than raw source tables.

### 8.4 Metric governance

- **FR-MET-001:** The system shall provide governed definitions for denial rate, clean-claim rate, first-pass acceptance rate, days in accounts receivable, outstanding balance, net collection rate, appeal success rate, and recovered revenue.
- **FR-MET-002:** Each metric definition shall state its grain, numerator, denominator, inclusions, exclusions, time convention, null behavior, and owner.
- **FR-MET-003:** Denial analysis shall support payer, provider, facility, procedure, diagnosis, denial-reason, and time dimensions where the source data supports the relationship.
- **FR-MET-004:** Leadership and operational reports shall use the same governed definitions.
- **FR-MET-005:** Every published KPI shall be reproducible with a documented warehouse query or semantic-layer calculation.

### 8.5 Denial-priority engine

- **FR-PRI-001:** The system shall create a priority record for each eligible denied claim using deterministic business rules.
- **FR-PRI-002:** The initial priority method shall consider recoverable amount, days remaining before the filing or appeal deadline, synthetic historical resolution rate, synthetic payer response behavior, documentation readiness, and claim age.
- **FR-PRI-003:** Scoring inputs, weights, thresholds, exclusions, and priority bands shall be configuration-controlled and versioned.
- **FR-PRI-004:** The same inputs and rule version shall always produce the same score and explanation.
- **FR-PRI-005:** Every priority record shall include the claim identifier, score, priority band, recoverable amount, days remaining, leading reasons, blocking conditions, rule version, calculation timestamp, and lineage.
- **FR-PRI-006:** Claims failing required identity, financial, or deadline checks shall be withheld from ranking.
- **FR-PRI-007:** The priority engine shall recommend human review and shall not automatically file, submit, or approve an appeal.

### 8.6 Dashboards and operational alerts

- **FR-BI-001:** The system shall provide an executive view of denial trends, revenue exposure, accounts receivable, recoveries, collection performance, and data quality.
- **FR-BI-002:** The system shall provide an operational view of ranked claims, deadlines, amounts, payer and denial-reason concentrations, and drill-through evidence.
- **FR-BI-003:** Dashboard totals shall reconcile to governed warehouse queries.
- **FR-BI-004:** Reports shall display metric definitions, refresh context, filters, and appropriate empty or error states.
- **FR-ALT-001:** The system shall identify high-value claims approaching filing or appeal deadlines.
- **FR-ALT-002:** The system shall identify a sudden increase in denials from a payer or denial category.
- **FR-ALT-003:** The system shall identify failed ingestion, transformation, validation, reconciliation, or publication activity.
- **FR-ALT-004:** The system shall identify data-quality threshold and source-freshness breaches.
- **FR-ALT-005:** The system shall identify unusual payment variances requiring reconciliation.
- **FR-ALT-006:** The system shall identify a growing backlog of unresolved claims.
- **FR-ALT-007:** Every alert output shall include the affected source, batch or claim context, reason, timestamp, severity, and evidence needed for human review.

### 8.7 Orchestration and operations

- **FR-OPS-001:** Airflow shall coordinate ingestion, validation, dbt transformation, reconciliation, and publication dependencies.
- **FR-OPS-002:** Pipeline tasks shall define retry policy, timeout, dependency, backfill, and failure-callback behavior.
- **FR-OPS-003:** The system shall record batch and task start time, end time, status, duration, row counts, quality outcomes, and error context.
- **FR-OPS-004:** The system shall stop downstream publication when a required upstream task or critical gate fails.
- **FR-OPS-005:** The project shall provide a runbook for common failures, diagnosis, replay, and recovery.
- **FR-OPS-006:** A reviewer shall be able to identify the failing batch, task, rule, impact, and recommended recovery action from operational evidence.

## 9. Non-functional requirements

### 9.1 Privacy and security

- **NFR-SEC-001:** The project shall use synthetic data only.
- **NFR-SEC-002:** Synthetic records and documentation shall be clearly labeled so they cannot reasonably be mistaken for real patient data.
- **NFR-SEC-003:** Credentials, tokens, connection strings, and other secrets shall not be committed to the repository.
- **NFR-SEC-004:** Cloud identities and service accounts shall follow least-privilege access and environment separation.
- **NFR-SEC-005:** The design shall document masking, role-based access, auditability, encryption, retention, and threat assumptions even when the portfolio environment does not implement every production control.
- **NFR-SEC-006:** CI shall include automated secret scanning or an equivalent release gate.

### 9.2 Reliability and data integrity

- **NFR-REL-001:** Batch processing shall be idempotent.
- **NFR-REL-002:** Retries, replays, and backfills shall not duplicate or silently lose accepted records or financial amounts.
- **NFR-REL-003:** Every trusted publication shall have passing validation, test, freshness, and reconciliation evidence.
- **NFR-REL-004:** Partial failure shall leave the affected batch in an identifiable and recoverable state.
- **NFR-REL-005:** Automated tests shall cover happy paths, late delivery, duplicate delivery, malformed input, partial failure, threshold boundaries, null handling, and replay behavior.

### 9.3 Performance and scale

- **NFR-PERF-001:** The design shall support the fictional baseline of approximately 100,000 claims per month without requiring a browser or analyst workstation to hold the complete operational dataset.
- **NFR-PERF-002:** BigQuery tables shall use documented partitioning and clustering strategies appropriate to the dominant filters and joins.
- **NFR-PERF-003:** Incremental processing shall avoid full-history rebuilds when only a bounded batch or period has changed, except when a controlled full rebuild is required.
- **NFR-PERF-004:** Dashboard queries and models shall be reviewed for unnecessary scans, joins, and cardinality expansion.

### 9.4 Maintainability and reproducibility

- **NFR-MNT-001:** Infrastructure, transformation, orchestration, and validation behavior shall be represented as version-controlled code or configuration.
- **NFR-MNT-002:** A new reviewer shall be able to set up or understand the project using documented commands and sample configuration.
- **NFR-MNT-003:** CI shall run formatting, linting, unit, transformation, infrastructure-validation, and documentation checks appropriate to the changed components.
- **NFR-MNT-004:** Architecture, metric, validation-severity, scope, and scoring changes shall be recorded rather than introduced silently.
- **NFR-MNT-005:** The project shall pin or constrain important dependency versions and record release versions.

### 9.5 Explainability and auditability

- **NFR-AUD-001:** Every trusted record shall be traceable to a source delivery and processing batch.
- **NFR-AUD-002:** Every quarantine or rejection decision shall identify the rule and evidence that caused it.
- **NFR-AUD-003:** Every priority decision shall identify its scoring inputs, rule version, leading reasons, and calculation time.
- **NFR-AUD-004:** Every material metric shall be traceable to a documented definition and reproducible calculation.
- **NFR-AUD-005:** Synthetic assumptions and portfolio limitations shall be visible in the repository and demonstration.

## 10. Business success measures

Because version 1 uses synthetic data, these measures evaluate platform capability rather than claiming real clinical or financial improvement.

| Desired outcome | Version 1 evidence |
| --- | --- |
| Reduce preventable denials | Governed denial trends and preventable-reason analysis are reproducible from trusted data |
| Shorten denial-resolution time | The work queue exposes age, deadline urgency, blocking conditions, and prioritized next-review candidates |
| Recover more outstanding revenue | Recoverable balances are quantified and ranked using transparent rules |
| Reduce manual reconciliation | Source-to-curated counts and financial totals are generated and tested automatically |
| Improve clean-claim and first-pass acceptance visibility | Both metrics use documented definitions and reconcile across warehouse and BI outputs |
| Establish consistent reporting | Billing, Finance, Operations, and leadership views use the same semantic definitions |
| Act before deadlines | High-value claims in defined filing or appeal windows appear in alert outputs with evidence |
| Operate reliably | Injected failures produce actionable evidence and a safe, idempotent recovery run |

## 11. Delivery constraints and assumptions

- The initial cloud design targets Google Cloud Storage and BigQuery.
- dbt Core is the transformation and documentation framework.
- Apache Airflow is the orchestration framework.
- Python and SQL are the primary ingestion, validation, and transformation languages.
- Power BI is the business-intelligence layer.
- Terraform is the infrastructure-as-code tool.
- GitHub Actions provides continuous-integration and controlled deployment workflows.
- Cloud cost will be controlled through bounded synthetic datasets, partitioning, clustering, incremental processing, and documented query-cost review.
- Source schedules, business tolerances, metric conventions, and scoring weights are working assumptions until defined in their dedicated Phase 0 artifacts.

## 12. Requirement governance

- Every implementation issue or pull request shall reference one or more requirement identifiers or a documented defect.
- A requirement may be changed only through a reviewed documentation update that explains the reason and downstream impact.
- New features must identify the user decision, measurable acceptance condition, and blueprint phase they support.
- A proposed feature remains out of scope when those relationships are unclear.
- Detailed acceptance criteria shall be maintained in the Phase 0 acceptance-criteria matrix.
- Detailed input structures shall be maintained in the source-data contracts.
- Detailed formulas shall be maintained in the metric dictionary.
- Material technology and design choices shall be maintained in architecture decision records.

## 13. Requirements document definition of done

This requirements document is ready for baseline approval when:

- The customer problem and north-star outcome are explicit.
- Every planned version 1 capability maps to a user decision, business outcome, or reliability requirement.
- Version 1 scope and non-goals are explicit.
- Functional and non-functional requirements use stable identifiers.
- Synthetic-data, privacy, safety, and non-production boundaries are explicit.
- Open formula, schema, scoring, and architecture details are routed to named Phase 0 artifacts rather than silently assumed.
- The requirements contain no claims of real healthcare, financial, or operational outcomes.

## 14. Phase 0 artifact status

Completed Phase 0 artifacts:

1. [Acceptance-criteria matrix](acceptance-criteria.md).
2. [Source-data contracts](source-data-contracts/README.md).
3. [Governed metric dictionary](metric-dictionary/README.md).
4. [Architecture baseline and decision records](architecture/README.md).

Next: begin Phase 1 implementation scaffolding under the accepted architecture boundaries.
