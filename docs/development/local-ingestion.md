# Local ingestion boundary

**Boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION, CLINICAL, OR BILLING USE

The second Phase 2 vertical slice turns one approved generator delivery into auditable local
landing, immutable raw, validation, quarantine, rejection, and batch-registry evidence. It
does not contact Google Cloud or publish trusted analytical data.

## Run it

From the repository root, first generate a new delivery and then ingest its manifest:

```bash
uv run --locked claimsflow generate \
  --service-month 2026-07 \
  --claims 1000 \
  --seed 20260815 \
  --output data/generated/demo-2026-07

uv run --locked claimsflow ingest \
  --manifest data/generated/demo-2026-07/manifest.json \
  --workspace data/local-ingestion
```

Both directories are ignored by Git. The workspace must not be inside the delivery directory,
and neither existing evidence nor source files are overwritten.

## Trust-boundary sequence

1. Parse the manifest and require its exact approved shape.
2. Recompute file hashes, headers, file names, contract metadata, and row counts.
3. Load the eight YAML contracts and bind all fourteen file/dataset interfaces.
4. Scan source identities for reserved `SYN-` and `synthetic_` provenance before landing.
5. Deterministically regenerate hash-only evidence and require an exact match to the approved
   current generator output; caller-recomputed checksums cannot forge provenance.
6. Detect a previously registered batch or identical source file.
7. Stream each non-duplicate CSV into immutable JSON Lines raw evidence.
8. Add batch, file, row-number, contract, ingestion-time, and payload-hash lineage.
9. Apply contract type, allowed-value, pattern, range, and bounded financial checks.
10. Assign exactly one `accepted`, `accepted_with_warning`, `quarantined`, or `rejected`
    disposition and prove the counts reconcile.
11. Hash every staged artifact, validate report semantics, record a durable publication intent,
    atomically rename the artifact directory, and commit the SQLite registration.

An exact batch replay records `duplicate_no_op` and processes no rows. An identical file in a
new batch is linked to its original batch and is not copied or republished. Reusing a batch ID
with different evidence or reusing a natural key and version with a different accepted payload
hash blocks the run. Every exact replay verifies the stored report hash and complete artifact
inventory before returning a no-op. Workspace-scoped locking serializes duplicate decisions;
an interrupted rename/registration is recovered from its durable intent on retry. A partial
duplicate also re-verifies the original batch's registry summary, hashed report, full inventory,
and exact processed file when the pointer is created, recovered, or replayed.

Reserved workspace children (`batches`, `collisions`, the SQLite database and sidecars, and
lock files) must be regular in-workspace paths. Symlink or type-confusion attempts fail closed
before managed payload publication, and lock files are opened with no-follow protection.

## Local evidence layout

```text
data/local-ingestion/
├── ingestion-registry.sqlite3
├── batches/<batch-id>/
    ├── landing/
    │   ├── manifest.json
    │   └── files/*.csv
    ├── raw/*.jsonl
    ├── quality/*.jsonl
    ├── quarantine/*.jsonl
    ├── rejected/*.jsonl
│   └── audit/ingestion-report.json
└── collisions/<batch-id>-<manifest-hash>-<report-hash>/
    ├── landing/, raw/, quality/, quarantine/, rejected/
    └── audit/collision.json
```

Raw JSON Lines retain the original source payload and add a separate normalized payload. Safe
normalizations never overwrite raw values. The registry stores no claim payload values; it
contains batch and delivery controls, lineage keys, stable hashes, dispositions, immutable
source-version evidence, and ingestion events.

If `DQ-CMN-011` detects the same natural key and version with a different accepted payload
hash, the incoming directory moves to the non-published `collisions/` area. Both payload hashes,
the original batch, the incoming evidence location, and the blocking event remain auditable.

## Current limits

- Generator version `1.0.1` fixes exact cent allocation across claim lines. Older generator
  output retains a distinct identity but is not accepted by this current-version local boundary.
- This slice executes provenance, schema/type, normalization, duplicate, row-reconciliation,
  and bounded family financial/date controls.
- Full cross-family relationship resolution, contract freshness rules, invalid-scenario
  fixture coverage, and trusted publication remain later validation milestones.
- Cloud Storage, BigQuery, Airflow execution, dbt transformations, and Power BI are not used.
- The system never files, approves, or submits an appeal.
