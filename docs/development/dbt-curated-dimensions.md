# dbt curated dimensions

**Data boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION OR CLINICAL/BILLING USE

Phase 4B.1 adds nine conformed dimensions on top of the Phase 4A validated staging boundary.
Every dimension is a protected, contract-enforced BigQuery table whose physical alias contains
the candidate publication ID and exact validation-selection fingerprint. A failed or rebuilt
candidate therefore cannot overwrite another candidate's dimension tables.

## Model inventory

| Model | Grain | Validated dependency | History behavior |
| --- | --- | --- | --- |
| `dim_patient` | One patient per eligibility source system and patient ID | `stg_eligibility` | Current eligibility rollup with no member reference or other direct PII |
| `dim_payer` | One payer version per source system, payer ID, and valid-from date | `stg_reference_payers` | Effective-dated |
| `dim_plan` | One plan version per source system, plan ID, and valid-from date | `stg_reference_plans`, `dim_payer` | Effective-dated and bound to the covering payer version |
| `dim_provider` | One provider version per source system, provider ID, and valid-from date | `stg_reference_providers` | Effective-dated |
| `dim_facility` | One facility version per source system, facility ID, and valid-from date | `stg_reference_facilities` | Effective-dated |
| `dim_diagnosis` | One diagnosis version per source system, code system, code, and valid-from date | `stg_reference_diagnoses` | Effective-dated |
| `dim_procedure` | One procedure version per source system, code system, code, and valid-from date | `stg_reference_procedures` | Effective-dated |
| `dim_denial_reason` | One denial-reason version per source system, code, and valid-from date | `stg_reference_denial_reasons` | Effective-dated |
| `dim_date` | One row per calendar date in the candidate's complete source-date range | All fourteen typed staging models | Rebuilt as a continuous candidate date spine |

The seven reference dimensions preserve all validated effective-dated versions instead of
flattening to a current record. Each version has a deterministic SHA-256 surrogate key; a
separate business key remains constant across history versions. `is_current` is derived only
from an open-ended `valid_to`, while `source_active_flag` remains available for integrity
reconciliation. Intervals follow the source contract: `valid_from` is inclusive and
`valid_to` is exclusive, so one version may start exactly when its predecessor ends.

`dim_plan` resolves `payer_dimension_id` only when the plan's entire effective interval is
covered by the matching payer version in the same source system and candidate. The model uses
a left join so a missing parent remains visible and fails both the not-null relationship gate
and the effective relationship test instead of silently dropping the plan.

`dim_patient` deliberately excludes `member_reference` and financial eligibility attributes.
It exposes a stable synthetic patient key, eligibility observation bounds, row count, and
sorted validation/batch/checksum lineage only.

## Candidate build and validation

Use a new safe publication ID for every candidate and pass the immutable approved Phase 3
validation IDs that make up the candidate:

```bash
uv run --locked --group dbt dbt build \
  --project-dir analytics/dbt \
  --profiles-dir config/dbt \
  --target dev_demo \
  --select tag:curated_dimensions \
  --vars '{claimsflow_publication_id: demo_20260821_01, claimsflow_validation_ids: [validation_id_here]}'
```

The candidate must pass all of these gates before later publication logic can reference it:

- generated model-contract drift and offline `dbt parse`;
- non-null and unique surrogate keys plus the `dim_plan` relationship contract;
- exact source-to-dimension row-count reconciliation;
- effective interval, current-flag, and overlap checks across every history dimension;
- publication ID, selection fingerprint, and synthetic-only scope checks across all nine
  conformed dimensions;
- complete `dim_date` coverage from the minimum through maximum non-null candidate date.

The calendar spine is fail-closed at 36,600 days (about 100 years). An outlier date cannot
expand the table without bound: the model emits no spine for that candidate and the dedicated
span test fails publication.

Run the offline repository gate with:

```bash
make dbt-parse
```

That command checks both generated YAML artifacts and parses models/tests without contacting
Google Cloud. A real `dbt build` is a separate explicitly authorized synthetic dev/demo action.

## Deferred boundary

Phase 4B.1 creates no claim, claim-line, payment, denial, or appeal facts; no financial metric
logic; no priority score; and no active-publication pointer. Phase 4B.2 will add publication-
isolated curated facts and fact-to-dimension effective-date relationships. Candidate
membership deltas and active-manifest advancement remain the following slice.
