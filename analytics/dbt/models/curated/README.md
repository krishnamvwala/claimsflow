# Curated

Phase 4B.1 implements nine publication-isolated conformed dimensions under `dimensions/`.
Seven reference dimensions retain effective-dated history, `dim_plan` resolves the covering
payer version, `dim_patient` provides a privacy-minimized eligibility rollup, and `dim_date`
provides a continuous candidate calendar. Every model is a protected contract-enforced table
with deterministic keys, complete candidate scope, and validated-source lineage.

Facts, bridges, membership deltas, governed metrics, and active-publication advancement remain
future slices. See the [curated-dimension guide](../../../../docs/development/dbt-curated-dimensions.md).
