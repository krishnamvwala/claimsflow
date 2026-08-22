# ClaimsFlow dbt project

This directory is the exclusive home of warehouse business transformations, governed
metric projections, and the future deterministic priority engine described by ADR-002.

Phase 4A implements the validated staging boundary for all fourteen source identities.
Staging models may read only the immutable validated-record and quality-run interfaces; no
model may bypass that boundary to read landing, raw, quarantine, or rejected data. Every
non-CI invocation must provide a safe `claimsflow_publication_id` and an explicit non-empty
`claimsflow_validation_ids` allowlist.

Each project-protected staging view receives a physical alias bound to both its publication ID
and exact validation-selection fingerprint. The validated boundary hashes the exact canonical
normalized payload consumed by typed projections, then recomputes the Phase 3 per-record and
complete record-set evidence before exposing rows, retains complete source,
contract, validation, and quality-report lineage, and uses enforced model contracts for typed
fields. Failed candidates and reused names with different inputs remain physically isolated.

Phase 4B.1 builds nine publication-isolated conformed dimensions from that boundary. Seven
reference dimensions preserve effective-dated history with deterministic version and business
keys, `dim_plan` resolves the effective payer version, `dim_patient` is a privacy-minimized
eligibility rollup, and `dim_date` is a continuous candidate calendar. Generated enforced
contracts and singular tests cover candidate scope, source reconciliation, history overlap,
plan-to-payer relationships, and date coverage. Curated facts, membership deltas, active-
manifest advancement, semantic metrics, and priority logic remain later milestones.

The intended model flow is:

`staging -> intermediate -> curated -> semantic / operational`

In dev/demo, `generate_schema_name` maps staging and intermediate work into the governed
`claimsflow_curated` dataset and maps consumer models to `claimsflow_semantic` and
`claimsflow_operational`. Those are the exact datasets Terraform creates and grants to the
transformation identity. CI keeps its isolated `claimsflow_ci_*` parse namespace.

Run `make dbt-parse` from the repository root to verify both generated contract artifacts and
parse project configuration without contacting Google Cloud. See the
[validated-staging guide](../../docs/development/dbt-validated-staging.md) for the source
interface and the [curated-dimension guide](../../docs/development/dbt-curated-dimensions.md)
for the Phase 4B.1 model and test contract.
