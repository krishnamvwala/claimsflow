# Curated

Phase 4B.1 implements nine publication-isolated conformed dimensions under `dimensions/`.
Seven reference dimensions retain effective-dated history, `dim_plan` resolves the covering
payer version, `dim_patient` provides a privacy-minimized eligibility rollup, and `dim_date`
provides a continuous candidate calendar. Every model is a protected contract-enforced table
with deterministic keys, complete candidate scope, and validated-source lineage.

Phase 4B.2 implements five publication-isolated curated facts under `facts/`. They retain the
claim, claim-line, payment, denial, and appeal grains; resolve parents and effective dimensions;
and enforce exact source and financial reconciliation.

Membership deltas, governed metrics, and active-publication advancement remain future slices.
See the [curated-dimension guide](../../../../docs/development/dbt-curated-dimensions.md) and
[curated-fact guide](../../../../docs/development/dbt-curated-facts.md).
