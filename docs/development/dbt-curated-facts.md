# dbt curated facts

**Data boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION OR CLINICAL/BILLING USE

Phase 4B.2 adds five curated facts on top of the Phase 4A validated staging boundary and the
Phase 4B.1 conformed dimensions. Every fact is a protected, contract-enforced BigQuery table
whose physical alias contains the candidate publication ID and exact validation-selection
fingerprint. Failed candidates cannot replace another candidate's fact tables.

## Model inventory

| Model | Grain | Partition | Primary relationships |
| --- | --- | --- | --- |
| `fact_claim` | One claim submission version per source system | Service-from month | Patient, provider, facility, payer, plan, primary diagnosis, dates, optional prior submission |
| `fact_claim_line` | One service line on one claim submission version | Service-from month | Claim, procedure, ordered diagnoses, optional denial reason, dates |
| `fact_payment` | One posted payment, adjustment, refund, or write-off transaction | Payment month | Claim, optional line, optional remittance, optional payer, optional reversed payment, dates |
| `fact_denial` | One denial event for a claim or claim line | Denial month | Claim, optional line, payer, denial reason, dates |
| `fact_appeal` | One appeal level or event for one denial | Creation month | Denial, claim, dates |

Every fact key is a deterministic SHA-256 hash over a namespaced structured natural key.
Parent fact relationships reuse the same key convention and are also resolved against the
candidate facts. Reference dimensions are selected at the contract-defined business date
using inclusive `valid_from` and exclusive `valid_to` intervals.

`fact_claim_line` preserves the ordered source diagnosis list and an equally sized ordered
array of effective diagnosis-dimension keys. The release gate fails for an empty list, a
length mismatch, an unresolved code, a changed order, or a dimension version outside the
line's first service date.

## Financial conventions and gates

Source magnitudes remain unchanged. `fact_payment.signed_amount` is positive for credits and
negative for debits; the original positive `amount` is retained. All financial controls use
exact reconciliation at zero USD tolerance for this synthetic baseline.

Payments with a remittance key resolve to the exact accepted `stg_remittances` record in the
same candidate. Their grouped count and signed amount must equal the remittance transaction
count and direction-adjusted control total.

The Phase 4B.2 selector fails when any of these conditions occurs:

- fact row counts or configured financial-field totals differ from typed staging;
- claim-line billed, paid, adjustment, or outstanding totals do not roll up to the claim;
- claim or line financial equations do not balance;
- a payment sign disagrees with its direction;
- a remittance-linked payment does not resolve, or its grouped count or signed amount differs
  from the accepted remittance control;
- a denial exceeds the linked claim or line outstanding exposure;
- an appeal request exceeds the denial, a recovery exceeds its request, or aggregate recovery
  exceeds the denial;
- any required parent, conformed dimension, date key, publication scope, or synthetic-only
  marker fails to resolve exactly.

## Candidate build and validation

Use a new safe publication ID and the immutable Phase 3 validation IDs composing the
candidate:

```bash
uv run --locked --group dbt dbt build \
  --project-dir analytics/dbt \
  --profiles-dir config/dbt \
  --target dev_demo \
  --select tag:validated_staging tag:curated_dimensions tag:curated_facts \
  --vars "{claimsflow_publication_id: demo_20260822_01, claimsflow_validation_ids: [validation_id_here], claimsflow_code_commit: '$(git rev-parse HEAD)'}"
```

The three tags must be built together for a new publication ID so that its staging views,
dimensions, facts, generic contract tests, and every Phase 4A/4B release gate use the same
candidate namespace and validation allowlist. The fact slice contributes seven singular
release gates: candidate scope, source reconciliation, parent relationships,
effective-dimension relationships, date-key correctness, ordered diagnosis conformance, and
financial integrity.

Run the offline repository gate with:

```bash
make dbt-parse
```

That command verifies the generated Phase 4A, Phase 4B.1, and Phase 4B.2 property files and
parses the entire model/test graph without contacting Google Cloud. A real `dbt build` remains
a separate explicitly authorized synthetic dev/demo integration action.

## Deferred boundary

Phase 4B.2 does not create candidate membership deltas, advance an active-publication
manifest, calculate governed KPIs, score denial priority, or expose BI models. Phase 4B.3
adds immutable result-version membership deltas and safe active-manifest advancement.
