# Data quality and quarantine

**Boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION, CLINICAL, OR BILLING USE

Phase 3 converts one complete, verified local ingestion batch into final validated,
quarantined, or rejected evidence and a fail-closed publication decision. It never changes
landing or raw artifacts. Python owns source-contract, byte/row, relationship, effective-date,
freshness, disposition, and reconciliation decisions; dbt remains the exclusive owner of
warehouse transformations, governed metrics, and priority logic.

## Run locally

Generate and ingest a complete fictional delivery first, then run:

```bash
uv run --locked claimsflow validate \
  --batch-id CF-YYYYMM-EXAMPLE \
  --workspace data/local-ingestion \
  --contracts contracts/source-data \
  --policy config/data-quality-policy.yml
```

The command creates an immutable `quality-runs/<validation-id>/` directory outside the
ingestion batch. An approved run exits zero. A completed but blocked publication gate exits
three and still preserves its report and investigation evidence. Configuration, missing
batch, unsafe path, provenance, or integrity failures exit two without publishing a partial
run.

## Rule sequence

1. Re-hash the registered ingestion report and every declared batch artifact, then bind the
   run to the exact policy, fourteen contract identities, and quality implementation hashes.
2. Require a complete processed inventory for all fourteen governed source identities.
3. Optionally apply complete synthetic corrections after checking the expected raw payload
   hash; the raw row remains unchanged and original plus revised evidence is recorded.
4. Reuse the structural, type, normalization, duplicate, and bounded financial results from
   ingestion.
5. Execute temporal/pointer rules, exact-key relationships, effective-dated reference
   relationships, list-member code relationships, and cross-record semantic checks.
6. Calculate source freshness against each contract's ISO-8601 maximum age. Freshness is a
   visible non-blocking warning in this portfolio baseline.
7. Reconcile claim-line financial rollups and remittance payment controls.
8. Assign exactly one final disposition: `accepted`, `accepted_with_warning`, `quarantined`,
   or `rejected`.
9. Reconcile every final disposition to the immutable raw-row count, assign each output row
   a canonical normalized-payload JSON string and SHA-256, include that checksum in the
   length-prefixed validation, identity, correction, and disposition evidence, and bind the
   complete sorted validated-record multiset into a report-level SHA-256.
10. Block publication for missing sources, critical rejected rows, or failed batch controls.
11. Atomically publish the run only after its artifact inventory and report are complete,
    then register the report SHA-256 in the durable SQLite control plane.

## Artifacts

- `validated/records.jsonl` contains accepted and warned normalized synthetic records, their
  immutable validation ID, canonical normalized-payload JSON and checksum, and independently
  reproducible record-evidence SHA-256.
- `quarantine/records.jsonl` contains ambiguous records and their rule evidence.
- `rejected/records.jsonl` contains structurally unusable records and critical evidence.
- `quality/issues.jsonl` contains row, source-freshness, and batch findings with stable rule
  IDs, severity, reason, affected identity/field, and processing time.
- `corrections/history.jsonl` preserves original and revised synthetic payloads, hashes,
  actor source, reason, and time without overwriting raw evidence.
- `audit/quality-report.json` contains the rule version, exact configuration and implementation
  hashes, the explicit 83-rule inventory across 131 source-identity/rule pairs (including
  not-applicable evidence), hourly evaluation window, source counts, freshness, failed-rule
  distribution, reconciliation, the validated-record count and record-set SHA-256, artifact
  hashes, and publication gate.

An exact replay in the same governed hourly evaluation window reconstructs every expected
artifact and report field, verifies the external SQLite report-hash receipt, and returns
`duplicate_no_op`. A later hourly window creates new freshness evidence. Policy, contract,
implementation, correction, report, artifact, receipt, or target contradictions fail closed.
Every existing output-path component is checked and symlinks are rejected before any quality
artifact is created.

## Current limits

- The service validates one complete local batch; a future candidate-publication service will
  compose accepted records across bounded batches and BigQuery datasets.
- Freshness warnings are reported but do not block this synthetic historical demonstration;
  their as-of time advances through governed hourly validation windows.
- Correction submission is exposed programmatically so a future authenticated human workflow
  can own actor authorization; the CLI currently runs uncorrected validation only.
- No dbt model, dashboard, cloud write, claim submission, appeal filing, or clinical/billing
  action occurs.
