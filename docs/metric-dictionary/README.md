# ClaimsFlow Governed Metric Dictionary

**Document status:** Baseline draft

**Dictionary version:** 1.0.0

**Blueprint phase:** Phase 0 - Discovery and Success Contract

**Data boundary:** Synthetic portfolio data only

## 1. Purpose

This dictionary turns ClaimsFlow's metric-governance requirements into exact, versioned calculation contracts. It defines the business meaning, grain, formula, cohort, source dependencies, dimensions, null behavior, reversal behavior, precision, validation evidence, and required test scenarios for every version 1 KPI.

The YAML definitions in [`contracts/metrics`](../../contracts/metrics) are authoritative. This document explains their shared conventions. The definitions do not claim real operational or financial performance; all examples and future implementation data remain synthetic.

See the [worked metric examples](examples.md) for arithmetic, time-boundary, correction, and dimensional-reconciliation scenarios.

## 2. Metric registry

| Metric ID | Governed metric | Type | Governing time | Definition |
| --- | --- | --- | --- | --- |
| MET-DEN-001 | Denial rate | Percent | Claim adjudication cohort | [`denial-rate.yml`](../../contracts/metrics/denial-rate.yml) |
| MET-CLN-001 | Clean-claim rate | Percent | Original claim submission cohort | [`clean-claim-rate.yml`](../../contracts/metrics/clean-claim-rate.yml) |
| MET-FPA-001 | First-pass acceptance rate | Percent | Original claim submission cohort | [`first-pass-acceptance-rate.yml`](../../contracts/metrics/first-pass-acceptance-rate.yml) |
| MET-DAR-001 | Days in accounts receivable | Days | Daily as-of snapshot with 90-day charge lookback | [`days-in-ar.yml`](../../contracts/metrics/days-in-ar.yml) |
| MET-ARB-001 | Outstanding balance | USD | Daily as-of snapshot | [`outstanding-balance.yml`](../../contracts/metrics/outstanding-balance.yml) |
| MET-NCR-001 | Net collection rate | Percent | Claim service-date cohort at a calculation cutoff | [`net-collection-rate.yml`](../../contracts/metrics/net-collection-rate.yml) |
| MET-APS-001 | Appeal success rate | Percent | Appeal decision cohort | [`appeal-success-rate.yml`](../../contracts/metrics/appeal-success-rate.yml) |
| MET-REV-001 | Recovered revenue | USD | Appeal decision cohort | [`recovered-revenue.yml`](../../contracts/metrics/recovered-revenue.yml) |

## 3. Formula summary

| Metric | Exact summary formula |
| --- | --- |
| Denial rate | `100 × distinct adjudicated claim submissions with a trusted denial ÷ distinct adjudicated claim submissions` |
| Clean-claim rate | `100 × clean original claims ÷ adjudicated original claims` |
| First-pass acceptance rate | `100 × first-pass accepted original claims ÷ original claims with a first response` |
| Days in A/R | `ending eligible outstanding balance ÷ (eligible gross charges from the prior 90 UTC dates ÷ 90)` |
| Outstanding balance | `sum current eligible claim-identity outstanding balance` |
| Net collection rate | `100 × net payer and patient payments ÷ (gross billed charges − net contractual adjustments)` |
| Appeal success rate | `100 × favorable decided appeals ÷ decided appeals` |
| Recovered revenue | `sum incremental recovered amount from favorable decided appeal events` |

The summary is not a substitute for each YAML contract. Inclusion, exclusion, version selection, cutoff, reversal, and null rules are part of the formula.

## 4. Shared record and version rules

- Only records eligible for trusted publication participate. Quarantined, rejected, blocked, and duplicate-no-op deliveries never contribute.
- A complete source natural key is required. Missing or unresolved required relationships are never inferred.
- Every contributing dependency first filters `trusted_published_at <= calculation_cutoff_at`, then selects the latest eligible business version. A late-arriving row with an older `source_updated_at` cannot leak into a calculation whose cutoff predates its trusted publication.
- Each dependency declares its complete natural key, business-version discriminator (`source_updated_at`, or `valid_from` for reference data), immutable `trusted_published_at`, and `processing_status` so the knowledge cutoff and version ranking are reproducible.
- A current claim identity is unique by `(source_system, claim_id)`. Select the highest non-rejected `submission_sequence` known at cutoff, then the latest source version for that natural key. A rejected replacement does not suppress the preceding valid submission; a current void removes the identity when the metric contract says so.
- Claim-header and claim-line financial amounts are never added together. Header metrics use claim headers; lines provide slicing or reconciliation through semi-joins.
- One-to-many procedure, diagnosis, denial, payment, or appeal relationships must be collapsed to the metric's stated grain before aggregation. A dimension may not change the unfiltered fact population through fanout.
- Every material output stores `metric_id`, `dictionary_version`, filter context, cohort or as-of date, `calculation_cutoff_at`, calculation timestamp, numerator, denominator where applicable, unrounded value, display value, and source lineage.

## 5. Time, cohort, and restatement conventions

- All timestamps normalize to UTC before cohort assignment.
- Period metrics use half-open intervals: `period_start <= event_time < period_end`. For a DATE event, `period_end` remains exclusive.
- As-of metrics use all source evidence known through `23:59:59.999999Z` on `as_of_date`.
- Event date chooses the business cohort; `calculation_cutoff_at` limits evidence using immutable `trusted_published_at`. Business-effective `source_updated_at`, ingestion time, and trusted-publication time must not be conflated.
- Late-arriving or corrected evidence restates only the open window declared by the metric. After that window, changes require an audited backfill and create a new calculation version rather than overwriting evidence silently.
- Days in A/R uses exactly 90 UTC calendar dates: `as_of_date - 89` through `as_of_date`, inclusive.

## 6. Null, empty, and zero-denominator behavior

- Required source values that are null fail validation; they are never silently converted to zero, false, an empty identifier, or a default date.
- Ratio and duration metrics return a null value with `not_applicable` status when the denominator is zero. They do not report `0%` or `0 days` for an empty denominator.
- Additive currency metrics return `0.00 USD` for a valid empty cohort.
- A null amount on a record that is otherwise required for a complete metric blocks publication of that metric result.
- Numerators must be subsets of their denominators for count-based rates.

## 7. Money, adjustments, reversals, and rounding

- Version 1 currency is USD only. Source components retain exact `NUMERIC(18,2)` precision through aggregation.
- Percent and duration results calculate at `NUMERIC(18,6)` precision before display rounding.
- Display rounding uses half away from zero only after the full aggregate is calculated. Rounded rows are never summed to create a total.
- Claims already separate payer-paid, patient-paid, patient-responsibility, adjustment, and outstanding amounts. Patient responsibility is an allocation, not a payment.
- Net collection rate includes payer and patient payments. Only `contractual_adjustment` reduces collectible charges; `write_off` does not.
- Payment refunds and reversals are signed debits and must resolve through the complete original-payment key. Their metric bucket comes from the original transaction type.
- A corrected claim or appeal source version replaces its earlier metric contribution inside the declared restatement window; it is not added as another event.
- `recovered_amount` is incremental for one appeal event, not cumulative across appeal levels. Recovery cannot exceed the appeal request, and total recovery for one denial cannot exceed its denied amount.

## 8. Similar metrics that must remain distinct

First-pass acceptance measures whether an original claim entered payer processing without a front-door rejection. A claim may therefore be first-pass accepted and later denied.

Clean-claim rate is stricter. Its numerator requires a successful first pass, a clean source flag, no linked denial, and no later replacement or void known by cutoff. Later correction evidence can remove a claim from the clean numerator during the open restatement window but cannot rewrite its historical first-pass response.

Denial rate counts whether a claim submission experienced a denial. A later overturn does not erase that operational event. Appeal success and recovered revenue separately describe the outcome and financial recovery.

## 9. Dimensional behavior

Denial analysis collectively supports payer, provider, facility, procedure, diagnosis, denial reason, and time as required by `FR-MET-003`. The metric contracts list only dimensions supported by their source relationships.

- Header dimensions use conformed claim or denial keys.
- Procedure and diagnosis filters use claim-line semi-joins against the complete claim key.
- Multi-valued diagnosis membership filters a claim once even when several matching values exist.
- Slices with mutually exclusive members reconcile exactly to their unfiltered numerator and denominator components before rate division. Multi-membership procedure and diagnosis filter views are explicitly non-additive unless a future governed allocation rule is introduced.
- Ratios are recomputed from sliced components; percentages are never added or averaged without their weights.

Denial rate does not expose `denial_reason` as a denominator dimension because non-denied claims have no denial reason and a reason-filtered denominator would be undefined. Denial-reason analysis is governed by appeal success and recovered revenue, where both numerator and denominator arise from denial-linked events. Procedure and diagnosis attribution uses a denial's exact line pointer when it exists; a claim-level denial is eligible for each distinct claim-line filter member but is counted once within a slice.

## 10. Governance and implementation boundary

- Business owners approve meaning and decision use. ClaimsFlow Analytics Engineering stewards calculation contracts and model parity.
- A semantic or dbt implementation must reference the immutable `metric_id` and `dictionary_version` and pass the contract's required scenarios.
- Leadership and operational outputs must consume the same governed semantic result for identical filter context.
- Any change to formula, grain, inclusion, exclusion, time boundary, sign, or null behavior is a major dictionary version change. Backward-compatible dimension additions are minor; clarifications without behavior change are patch changes.
- The automated validator checks structural completeness, exact requirement traceability, declared source fields, allowed dimensions, test-category coverage, unique validation rules, documentation links, time boundaries, precision, and denominator behavior.

## 11. Requirement and acceptance traceability

| Concern | Requirement | Acceptance evidence enabled |
| --- | --- | --- |
| Complete eight-metric registry | `FR-MET-001` | `AC-MET-001` coverage validation |
| Grain, components, inclusions, exclusions, time, nulls, and owner | `FR-MET-002` | `AC-MET-002` definition-schema validation |
| Denial analysis dimensions | `FR-MET-003` | `AC-MET-003` declared dimension and future slice reconciliation tests |
| Shared definitions across outputs | `FR-MET-004` | Immutable IDs, versions, and semantic-consumer rules for `AC-MET-004` |
| Reproducible calculations | `FR-MET-005` | Source dependencies, formulas, precision, and future query parity for `AC-MET-005` |

## 12. Definition of done

The dictionary is ready for baseline approval when:

- Exactly eight unique YAML metric contracts parse successfully.
- Every contract states business ownership, output grain, numerator, denominator, inclusions, exclusions, time rules, dimensions, nulls, reversals, adjustments, precision, dependencies, validations, and scenarios.
- Every source dependency and dimension field exists in the merged source-data contracts.
- Count-based numerators are constrained to their denominators; additive metrics state that a denominator is not applicable.
- Each metric covers boundary, null, reversal, dimensional, and empty- or zero-denominator behavior.
- All rule, scenario, metric, requirement, and acceptance identifiers are valid and unique where required.
- The metric validator, its negative regression suite, link checks, and repository whitespace checks pass.
- Devin reviews the complete local diff before it is pushed.

## 13. Next Phase 0 artifact

Create the initial architecture decision records for the BigQuery data layers, dbt modeling and semantic strategy, Airflow orchestration boundary, Python service responsibilities, Power BI connectivity, security boundary, and deployment approach.
