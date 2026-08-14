# ClaimsFlow dbt project

This directory is the exclusive home of warehouse business transformations, governed
metric projections, and the future deterministic priority engine described by ADR-002.

Phase 1 establishes an empty, parseable project. Business models start in a later
milestone after synthetic generators, validated inputs, and executable source contracts
exist. Staging models may read only validated relations; no model may bypass that boundary
to read landing, raw, or quarantine data.

No SQL model is allowed in Phase 1. In particular, curated models have no ordinary table
default: the next warehouse milestone must first implement and test publication-scoped,
append-only result versions and membership deltas. The scaffold validator rejects an early
model or a destructive curated default.

The intended model flow is:

`staging -> intermediate -> curated -> semantic / operational`

In dev/demo, `generate_schema_name` maps staging and intermediate work into the governed
`claimsflow_curated` dataset and maps consumer models to `claimsflow_semantic` and
`claimsflow_operational`. Those are the exact datasets Terraform creates and grants to the
transformation identity. CI keeps its isolated `claimsflow_ci_*` parse namespace.

Run `make dbt-parse` from the repository root to validate project configuration without
contacting Google Cloud.
