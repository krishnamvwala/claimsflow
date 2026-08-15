# ClaimsFlow

Healthcare claims analytics, denial prevention, and revenue recovery platform built with BigQuery, dbt, Airflow, Python, and Power BI.

## Project status

ClaimsFlow has completed the Phase 0 discovery/success-contract baseline and the Phase 1 implementation foundation. Requirements, acceptance criteria, machine-readable source-data contracts, the governed metric dictionary, and seven accepted architecture decisions are documented and automatically validated.

Phase 1 adds pinned Python tooling, the typed package and CLI boundary, an empty parseable dbt project, an inert fail-closed Airflow DAG in Docker, guarded Terraform local and dev/demo roots, release-manifest configuration, component-aware CI, and offline policy tests. It creates no cloud resources and implements no claims business logic.

The next blueprint milestone is Phase 2: a deterministic synthetic source generator and the first provenance/ingestion vertical slice. No real healthcare or customer data is permitted at any phase.

## Quick start

```bash
cp .env.example .env
make bootstrap
uv run --locked claimsflow doctor
make check
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
