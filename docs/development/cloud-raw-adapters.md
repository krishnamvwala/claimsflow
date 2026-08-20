# Cloud Storage and BigQuery raw adapters

**Boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION, CLINICAL, OR BILLING USE

This Phase 2 slice publishes one already verified local ingestion result into an immutable
Cloud Storage landing boundary and append-only BigQuery raw/audit tables. The implementation
is programmatic rather than a default CLI command so importing ClaimsFlow, running tests, or
using local ingestion cannot accidentally create cloud resources or incur spend.

## Components

- `claimsflow.ports.cloud` defines the landing-object and raw/audit warehouse interfaces.
- `claimsflow.adapters.gcs_landing` implements create-only, generation-pinned Cloud Storage
  uploads and full content re-verification.
- `claimsflow.adapters.bigquery_raw` implements deterministic raw JSON Lines and audit load
  jobs.
- `claimsflow.ingestion.cloud_publication` verifies local artifacts, builds the upload/load
  plan, enforces ordering, and reconciles the completed publication.

Unit tests inject fakes through the ports. The Google clients and Application Default
Credentials are loaded only when `from_default_credentials(...)` is called explicitly.

## Publication sequence

1. Re-hash the local ingestion report and every artifact in its declared inventory.
2. Require synthetic-only provenance, canonical artifact paths, and reconciled file/batch
   counts before any external call.
3. Build deterministic Cloud Storage object names containing source identity, delivery date,
   batch ID, and original file name.
4. Upload the source manifest and each newly processed source file with
   `if_generation_match=0`; an exact existing live object is an idempotent replay, never an
   overwrite.
5. Re-open every exact object generation, validate metadata and size, download the object,
   and recompute its full SHA-256 checksum.
6. Only after every landing object passes the cloud-side gate, append each local raw JSON
   Lines artifact to its source-specific BigQuery raw table.
7. Use a deterministic load-job ID. A task replay reattaches to the prior job and requires the
   same destination and output-row count.
8. After all raw rows reconcile, append one audit event containing the landing object URIs,
   generations, SHA-256 hashes, raw load job IDs, and local reconciliation evidence.

Any failure stops the remaining sequence. Immutable objects or successful append jobs from a
partial attempt remain safe recovery evidence; retry uses the same object names and job IDs.

## Physical layout

Landing object names use this form:

```text
source=<source-identity>/delivery_date=<YYYY-MM-DD>/batch_id=<batch-id>/<original-file-name>
source=manifest/delivery_date=<YYYY-MM-DD>/batch_id=<batch-id>/manifest.json
```

Raw destinations use one table per governed source identity:

```text
<project>.claimsflow_raw.<source_identity>
```

Raw rows keep the local immutable lineage envelope and store issues, original payload, and
normalized payload as BigQuery JSON values. Raw tables are append-only and ingestion-time
partitioned, with stable lineage/status clustering. The publication audit destination is:

```text
<project>.claimsflow_audit.ingestion_publications
```

The audit table is event-time partitioned and clustered by batch, event type, and decision.

## Security, idempotency, and cost boundary

- No service-account key files are accepted or committed. Authorized runtime composition uses
  Application Default Credentials; CI/deployment will use the accepted federation boundary.
- Object metadata and logs contain identifiers, hashes, generations, counts, and contract
  versions—not raw row values.
- Cloud object creation uses a zero-generation precondition. Verification and downloads pin
  the exact returned generation.
- BigQuery load jobs use deterministic IDs and `WRITE_APPEND`; exact replay validates the
  existing job rather than starting a second logical append.
- Fake tests require no credentials and create no cloud resources. A live dev/demo integration
  test or Terraform apply requires separate explicit authorization and budget controls.

## Current limits

- There is no default cloud CLI command or automatic deployment.
- The adapters do not execute dbt transformations, cross-family relationship/freshness rules,
  governed metrics, priority scoring, or dashboard publication.
- A live isolated dev/demo smoke test remains deferred until the target project, bucket,
  datasets, credentials, and cost approval are explicitly provided.
- Real healthcare or customer data remains prohibited.
