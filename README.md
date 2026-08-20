# ClaimsFlow

Healthcare claims analytics, denial prevention, and revenue recovery platform built with BigQuery, dbt, Airflow, Python, and Power BI.

## Project status

ClaimsFlow has completed the Phase 0 discovery/success-contract baseline and the Phase 1 implementation foundation. Phase 2 includes the deterministic synthetic source generator, an idempotent local ingestion boundary, and fake-tested Cloud Storage landing plus BigQuery raw/audit adapters. Phase 3 now adds contract-driven cross-source/effective-date validation, freshness evidence, final quarantine/rejection routing, immutable correction history, reconciliation, and a fail-closed publication gate. Requirements, acceptance criteria, machine-readable source-data contracts, the governed metric dictionary, and seven accepted architecture decisions are documented and automatically validated.

Phase 1 adds pinned Python tooling, the typed package and CLI boundary, an empty parseable dbt project, an inert fail-closed Airflow DAG in Docker, guarded Terraform local and dev/demo roots, release-manifest configuration, component-aware CI, and offline policy tests. It creates no cloud resources and implements no claims business logic.

The Phase 2 generator creates bounded fictional source deliveries for all eight governed source families, with delivery-namespaced identifiers, contract metadata, row counts, SHA-256 hashes, and generated-to-written row-count reconciliation. The local ingestion slice independently reproduces approved generator evidence before landing, streams immutable raw evidence, records row lineage, classifies structural outcomes, verifies stored artifacts on replay, handles duplicate deliveries as audited no-ops, preserves immutable-version collision evidence, recovers interrupted publication through durable intents, and proves disposition reconciliation. The cloud slice adds create-only generation-pinned landing uploads, full SHA-256 cloud re-verification, deterministic append-only BigQuery raw load jobs, and one reconciled audit event. Unit tests use fakes and create no cloud resources; live dev/demo execution remains an explicit approved integration step. No real healthcare or customer data is permitted at any phase.

The Phase 3 quality slice verifies the complete ingestion artifact inventory, binds each run to exact policy, contract, and implementation hashes, applies all 83 governed source rules across 131 source-identity/rule pairs with explicit not-applicable evidence, writes separate validated/quarantine/rejected evidence, preserves synthetic corrections without overwriting raw values, and blocks dependent publication for critical or unreconciled outcomes. Same-window replay reconstructs the expected evidence and verifies a durable report-hash receipt; later hourly windows refresh freshness evidence. dbt transformation and business metric logic remain deliberately deferred to Phase 4.

## Quick start

```bash
cp .env.example .env
make bootstrap
uv run --locked claimsflow doctor
make check
```

Generate a small repeatable delivery into a new, ignored directory:

```bash
uv run --locked claimsflow generate \
  --service-month 2026-07 \
  --claims 1000 \
  --seed 20260815 \
  --output data/generated/demo-2026-07
```

Verify and register that delivery in an ignored local workspace:

```bash
uv run --locked claimsflow ingest \
  --manifest data/generated/demo-2026-07/manifest.json \
  --workspace data/local-ingestion
```

Run final Phase 3 quality and publication gates:

```bash
uv run --locked claimsflow validate \
  --batch-id <batch-id-from-ingest> \
  --workspace data/local-ingestion
```

See the [local development guide](docs/development/README.md) for prerequisites, component
commands, boundaries, and troubleshooting.

## Project documentation

- [Requirements](docs/requirements.md)
- [Acceptance criteria](docs/acceptance-criteria.md)
- [Source-data contracts](docs/source-data-contracts/README.md)
- [Governed metric dictionary](docs/metric-dictionary/README.md)
- [Architecture baseline and decision records](docs/architecture/README.md)
- [Local development guide](docs/development/README.md)
- [Runtime component inventory](docs/development/component-inventory.md)
- [Synthetic generator guide](docs/development/synthetic-generator.md)
- [Local ingestion guide](docs/development/local-ingestion.md)
- [Cloud raw adapters guide](docs/development/cloud-raw-adapters.md)
- [Data-quality and quarantine guide](docs/development/data-quality-quarantine.md)
