# ClaimsFlow dbt project

This directory is the exclusive home of warehouse business transformations, governed
metric projections, and the future deterministic priority engine described by ADR-002.

Phase 4A implements the validated staging boundary for all fourteen source identities.
Staging models may read only the immutable validated-record and quality-run interfaces; no
model may bypass that boundary to read landing, raw, quarantine, or rejected data. Every
non-CI invocation must provide a safe `claimsflow_publication_id`, an explicit non-empty
`claimsflow_validation_ids` allowlist, and the exact `claimsflow_code_commit`.

Each project-protected staging view receives a physical alias bound to its publication ID,
exact validation-selection fingerprint, and code-bound candidate-build fingerprint. The
validated boundary hashes the exact canonical
normalized payload consumed by typed projections, then recomputes the Phase 3 per-record and
complete record-set evidence before exposing rows, retains complete source,
contract, validation, and quality-report lineage, and uses enforced model contracts for typed
fields. Failed candidates and reused names with different inputs remain physically isolated.

Phase 4B.1 builds nine publication-isolated conformed dimensions from that boundary. Seven
reference dimensions preserve effective-dated history with deterministic version and business
keys, `dim_plan` resolves the effective payer version, `dim_patient` is a privacy-minimized
eligibility rollup, and `dim_date` is a continuous candidate calendar. Generated enforced
contracts and singular tests cover candidate scope, source reconciliation, history overlap,
plan-to-payer relationships, and date coverage.

Phase 4B.2 adds five publication-isolated curated facts for claims, claim lines, payments,
denials, and appeals. They preserve exact source grains and lineage, resolve parent facts and
effective dimension versions, map every calendar role, and enforce ordered line-diagnosis
conformance. Exact source totals, claim-line rollups, payment signs, denial exposure, appeal
recovery, relationship, and candidate-scope gates fail closed.

Phase 4B.3 adds the stable protected `active_publication_membership` view over the governed
synthetic-only audit control tables. It begins at the single revision-guarded active pointer,
reduces that manifest's bounded delta chain to the latest mapping per relation and business
key, removes tombstones, and joins immutable result-version evidence. Its singular release
gate rejects pointer, manifest-chain, gate, delta, version, inventory, and resolved-key
integrity failures.
Semantic metrics and priority logic remain later milestones.

The intended model flow is:

`staging -> intermediate -> curated dimensions / facts -> semantic / operational`

In dev/demo, `generate_schema_name` maps staging and intermediate work into the governed
`claimsflow_curated` dataset and maps consumer models to `claimsflow_semantic` and
`claimsflow_operational`. Those are the exact datasets Terraform creates and grants to the
transformation identity. CI keeps its isolated `claimsflow_ci_*` parse namespace.

Run `make dbt-parse` from the repository root to verify both generated contract artifacts and
parse project configuration without contacting Google Cloud. See the
[validated-staging guide](../../docs/development/dbt-validated-staging.md) for the source
interface and the [curated-dimension guide](../../docs/development/dbt-curated-dimensions.md)
for the Phase 4B.1 model and test contract.
See the [curated-fact guide](../../docs/development/dbt-curated-facts.md) for the Phase 4B.2
fact, relationship, and financial-reconciliation contract.
See the [safe-publication guide](../../docs/development/safe-publication.md) for Phase 4B.3
manifest, membership, activation, compaction, and rollback behavior.
