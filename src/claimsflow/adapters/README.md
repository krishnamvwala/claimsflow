# Adapter boundary

This directory contains the local SQLite ingestion registry, the Cloud Storage landing
adapter, and the BigQuery raw/audit adapter. The local adapter stores control-plane, lineage,
hash, and disposition evidence; immutable source payloads remain in the explicitly selected
local batch artifact directory until an authorized caller composes the cloud publication
service. Every adapter implements an interface in `claimsflow.ports`, preserves the
synthetic-only boundary, and keeps metric or transformation logic in dbt.

The SQLite adapter serializes one workspace's ingestion decisions, records publication intents
for crash recovery, verifies report/artifact hashes on replay through the service, and retains
blocked version-collision evidence under the workspace `collisions/` directory. Managed
directories, database sidecars, and lock files reject symlink escapes; replay and partial-file
deduplication reconcile SQLite summaries and dependencies back to hashed artifact evidence.

`gcs_landing.py` uploads with `if_generation_match=0`, treats an exact existing object as an
idempotent replay, and downloads the exact returned generation to recompute SHA-256 before
raw loading. `bigquery_raw.py` uses deterministic job IDs, append-only JSON load jobs, strict
schemas, ingestion-time partitioning for raw tables, event-time partitioning for audit, and
exact output-row reconciliation. Default clients use Application Default Credentials only
when explicitly constructed; imports, unit tests, and local ingestion perform no cloud write.
