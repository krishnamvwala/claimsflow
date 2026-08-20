# Macros

Phase 4A macros validate candidate publication and quality-validation identifiers, bind
physical aliases to a deterministic validation-selection fingerprint, reproduce Phase 3
length-prefixed record-evidence hashes, and project governed JSON values into BigQuery types.
The projected fields come from the same canonical JSON string whose SHA-256 is independently
recomputed by the boundary. They fail compilation for unsafe or missing identifiers and for
unsupported contract types.
Macros contain no credentials, row payloads, governed metrics, priority weights, or Airflow-
specific orchestration behavior.
