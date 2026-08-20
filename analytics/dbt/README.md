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
fields. Failed candidates and reused names with different inputs remain physically isolated. Curated append-only result versions,
membership deltas, active-manifest advancement, semantic metrics, and priority logic remain
later milestones; no curated SQL model or destructive curated default is allowed yet.

The intended model flow is:

`staging -> intermediate -> curated -> semantic / operational`

In dev/demo, `generate_schema_name` maps staging and intermediate work into the governed
`claimsflow_curated` dataset and maps consumer models to `claimsflow_semantic` and
`claimsflow_operational`. Those are the exact datasets Terraform creates and grants to the
transformation identity. CI keeps its isolated `claimsflow_ci_*` parse namespace.

Run `make dbt-parse` from the repository root to verify the generated contract properties and
parse project configuration without contacting Google Cloud. See the
[validated-staging guide](../../docs/development/dbt-validated-staging.md) for the governed
dev/demo invocation and source interface.
