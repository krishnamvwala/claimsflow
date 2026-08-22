# Safe warehouse publication and rollback

**Data boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION OR CLINICAL/BILLING USE

Phase 4B.3 turns isolated dbt candidates into governed logical snapshots without allowing a
failed, partial, stale, or concurrent build to replace the data consumers already trust. The
control plane persists every candidate manifest, complete business-key/content-hash inventory,
changed-key membership delta, and new result-version reference before it attempts the sole
consumer-visible mutation: a compare-and-swap update of the environment's active-publication
pointer.

## Control-plane records

| Record | Mutation policy | Purpose |
| --- | --- | --- |
| `publication_manifests` | Create-only | Complete candidate evidence, parent, bounded membership chain, gates, reconciliations, partitions, code, artifacts, contracts, dictionary, and batches |
| `publication_membership_deltas` | Create-only | Only changed business-key mappings plus explicit deletion tombstones |
| `publication_result_versions` | Create-only | Result-version identity, source candidate relation, business key, and SHA-256 content evidence |
| `publication_candidate_inventory` | Create-only | Complete final business-key/content-hash set used to prove no update, addition, or deletion was omitted |
| `publication_activations` | Append-only | Every successful publication or rollback pointer transition |
| `active_publications` | Compare-and-swap only | One preseeded environment row, nullable initial manifest ID, and monotonic revision |
| `publication_reservation_locks` | Revision update only | Preseeded hash buckets that serialize publication-ID create-only reservations |

`GoogleBigQueryPublicationRepository.ensure_schema()` creates these tables with `CREATE TABLE
IF NOT EXISTS`; it never replaces a table. Atomic create-as-select statements preseed the two
supported environment pointer rows and 64 reservation-lock buckets, and post-create assertions
reject missing, duplicate, or unexpected bootstrap rows. Candidate creation is one BigQuery
transaction that first updates the publication ID's lock bucket, so concurrent read-then-insert
attempts cannot both commit. Reusing a publication ID is an idempotent no-op only when the full
candidate fingerprint is identical. Reusing either a publication ID or result-version ID with
different evidence fails.

Every publication-scoped dbt relation also receives a code-bound build fingerprint in its
physical alias. Reusing a publication ID and validation selection with a different exact Git
commit therefore writes a different table instead of replacing an active or rollback relation.

## Mandatory publication gates

The service requires immutable SHA-256 evidence for these named gates:

- `validation`
- `dbt_build`
- `freshness`
- `row_reconciliation`
- `financial_reconciliation`

Every published relation must have exactly one row reconciliation, and every financial
reconciliation must be within its declared tolerance. Bounded changes require both warehouse
and BI partition ranges. Unbounded changes cannot claim incremental BI ranges and therefore
require a later full semantic-model refresh.

The candidate is stored even when a gate fails, but its manifest is never selected. This
preserves diagnosis evidence while keeping the active snapshot unchanged.

## Membership behavior

A normal candidate inherits its active parent's ordered chain and appends one immutable delta.
It must also supply the complete final key/hash inventory committed by the manifest. The
service derives the exact additions, content updates, and deletions against the active parent;
the supplied delta must match that derived set exactly. This detects omitted same-count updates
and omitted delete/add pairs that row totals alone cannot reveal.

A normal-delta upsert must use a new result version owned by the current candidate. Persisting a
failed candidate never makes its versions publishable. A compacted base may reuse only the exact
result version already resolved for that key from the active parent, while changed base rows
must use current-candidate versions. All upserts must match the inventory content hash and the
declared isolated physical relation.

The dbt `active_publication_membership` view starts from `active_publications`, reads only that
manifest's chain, and applies the most recent mapping for each relation/business-key pair.
Latest tombstones disappear from the result. Failed candidates have no path into the view.
The `publication_active_membership_integrity` release test fails on duplicate pointers or
manifests, missing or broken intermediate manifest links, malformed/failed/missing active gates,
duplicate delta, version, or inventory keys, orphan mappings, duplicate resolved business keys,
or any mismatch between resolved membership and the active candidate's complete inventory.

## Chain cap and compaction

`PublicationService` defaults to a maximum chain depth of eight. A normal delta that would
exceed the configured limit fails with `CompactionRequiredError`. An explicitly approved base
candidate starts a new one-entry chain, supplies a complete non-tombstoned membership map, and
remains isolated until every gate passes. The old active snapshot is unaffected while that
compaction builds.

## Activation, concurrency, and replay

Publication reads the current pointer and validates that it is the manifest's declared parent.
Activation always updates the preseeded environment control row and asserts that exactly one row
changed. BigQuery transaction conflicts serialize concurrent writers; the expected publication
ID and revision provide the compare-and-swap guard. A concurrent loser fails closed and remains
unreachable. An identical retry after activation returns `already_active` without another
pointer event.

The service intentionally has no default live-write CLI. An authorized orchestration caller
must construct `GoogleBigQueryPublicationRepository` with Application Default Credentials,
initialize the schema, build a strict `PublicationCandidate`, and call
`PublicationService.publish()`. Unit tests use the thread-safe in-memory reference repository;
the default offline validation path creates no cloud resource and performs no cloud write.

## Rollback

Rollback never rewrites source evidence, result versions, deltas, or manifests. It requires:

1. the caller's expected active publication to match the current pointer;
2. the target manifest to belong to the same environment; and
3. activation history proving the target was previously active.

The service then performs the same revision-guarded pointer transition and appends a rollback
event. Resolving active membership immediately returns the target's exact prior logical
snapshot. Power BI rollback refresh remains a later orchestration/BI milestone and must be a
full refresh under ADR-005.

## Offline validation

Run the complete repository gate:

```bash
make check
```

The Phase 4B.3 tests prove passing activation, failed-candidate and cross-environment version
isolation, complete-inventory detection of omitted changes, changed mappings, tombstones,
idempotent replay, identity collision rejection, stale-parent conflicts, code-bound dbt aliases,
exact rollback, chain-cap failure, base compaction, manifest schema validation, serialized and
parameterized BigQuery transaction structure, and dbt active-membership parsing. A live
synthetic GCP concurrency exercise remains a separately authorized integration gate.

After authorizing a disposable synthetic-only BigQuery dataset, run that live gate explicitly:

```bash
CLAIMSFLOW_RUN_BIGQUERY_CONCURRENCY=1 \
CLAIMSFLOW_BIGQUERY_TEST_PROJECT=<synthetic-test-project> \
uv run --locked --group cloud pytest tests/integration/test_bigquery_publication_concurrency.py
```

The test creates a uniquely named `claimsflow_pub_it_*` dataset, runs two concurrent schema
bootstraps, proves that colliding publication reservations leave one manifest and that two
genesis activations leave one revision-1 pointer/event, then deletes that disposable dataset.
