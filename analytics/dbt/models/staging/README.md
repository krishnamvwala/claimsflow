# Staging

Phase 4A staging models read only allowlisted, approved, reconciled synthetic records from
the validated and audit source interfaces. The project-protected `stg_validated_records`
boundary recomputes the canonical normalized-payload, per-record, and complete record-set
evidence before injecting the
candidate publication ID and validation-selection fingerprint. It retains validation, batch,
file, contract, evaluated-payload, normalized-payload, record-evidence, record-set, and report
hashes. Fourteen
source-conformed views cast every governed field and convert pipe-delimited `STRING_LIST`
values to ordered `array<string>` values.

Every physical staging alias ends with the safe candidate publication ID and the deterministic
fingerprint of its exact validation allowlist. These models do
not implement facts, dimensions, governed metrics, active-publication selection, priority
policy, or reporting behavior.
