# Adapter boundary

This directory contains the local SQLite ingestion registry and will later hold Cloud Storage
and BigQuery landing/raw adapters. The local adapter stores control-plane, lineage, hash, and
disposition evidence; immutable source payloads remain in the explicitly selected local batch
artifact directory. No cloud writes are implemented yet. Every adapter must implement the
interfaces in `claimsflow.ports`, preserve the synthetic-only boundary, and keep metric or
transformation logic in dbt.

The SQLite adapter serializes one workspace's ingestion decisions, records publication intents
for crash recovery, verifies report/artifact hashes on replay through the service, and retains
blocked version-collision evidence under the workspace `collisions/` directory. Managed
directories, database sidecars, and lock files reject symlink escapes; replay and partial-file
deduplication reconcile SQLite summaries and dependencies back to hashed artifact evidence.

No external writes are implemented in Phase 1. The Phase 2 local adapter writes only to the
operator-selected local workspace; cloud writes remain deferred.
