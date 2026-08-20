# Runtime component inventory

**Data boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION OR CLINICAL/BILLING USE

This inventory ties each accepted architecture owner to a repository path, runtime, current
implementation state, and release gate. “Scaffolded” means the boundary is executable or
parseable but does not yet perform the future business operation.

| Component | Repository path | Pinned runtime | Current state | Ownership boundary | Validation |
| --- | --- | --- | --- | --- | --- |
| Python package and CLI | `src/claimsflow` | Python 3.12 | Phase 3 local quality boundary implemented | Configuration, generator, provenance gate, local ingestion, cloud publication, quality/quarantine gate, and safe control-plane output; no analytics rules | Ruff, strict mypy, pytest |
| Python local adapter | `src/claimsflow/adapters/local_registry.py` | Python 3.12 SQLite | Phase 2 slice implemented | Idempotency, serialized delivery decisions, durable publication intents, lineage hashes, dispositions, replay integrity, and immutable-version collision evidence | Replay tamper, concurrency, crash recovery, collision retention, reconciliation, and failure-path tests |
| Python cloud adapters | `src/claimsflow/adapters/gcs_landing.py`; `src/claimsflow/adapters/bigquery_raw.py` | BigQuery 3.43.0; Storage 3.1.1 | Phase 2 adapters implemented; live dev/demo exercise deferred | Create-only generation-pinned landing, cloud SHA-256 re-verification, deterministic append-only raw/audit jobs; no dbt-owned business logic | Fake client, collision/replay, tamper, generation, ordering, and reconciliation tests |
| Python quality engine | `src/claimsflow/quality`; `config/data-quality-policy.yml` | Python 3.12; policy 1.0.0 | Phase 3 local slice implemented | Exact policy/contract/implementation binding, all 83 governed source rules across 131 source-identity/rule pairs with explicit not-applicable evidence, hourly freshness windows, final dispositions, immutable corrections, deterministic replay reconstruction, durable report receipts, batch controls, and fail-closed publication gate; no metric or priority logic | Relationship, reversal, freshness, tamper, replay, correction, configuration, symlink, reconciliation, and gate tests |
| dbt Core project | `analytics/dbt` | dbt Core 1.12.2; dbt-bigquery 1.12.0 | Scaffolded, no models | Exclusive owner of transformations, metrics, and priority evidence | Offline `dbt parse` plus exact physical-schema policy |
| Apache Airflow | `orchestration/airflow` | Airflow 3.3.1/Python 3.12 image pinned by digest | Scaffolded with inert DAG | Dependencies, bounded retry/replay, and publication order only | Static policy plus runtime `DagBag` validation |
| Local containers | `compose.yaml` | Docker Compose | Scaffolded | Reproducible Airflow runtime; no credentials | `docker compose config`, image build |
| Terraform module | `infra/terraform/modules/foundation` | Terraform 1.15.8; Google 7.44.0 | Scaffolded, not applied | Landing, datasets, identities/IAM, WIF, retention, and budget | Format, init without backend, validate |
| Terraform local root | `infra/terraform/environments/local` | Terraform 1.15.8 | Scaffolded | Synthetic boundary metadata; no cloud resources | Format and validate |
| Terraform dev/demo root | `infra/terraform/environments/dev-demo` | Terraform 1.15.8 | Scaffolded, not applied | Dedicated synthetic GCP composition with partial remote backend | Format and validate |
| Release evidence | `config/release-manifest*` | JSON Schema 2020-12; jsonschema 4.26.0 | Scaffolded | Version, artifact, approval, limitation, and synthetic-only evidence | Complete schema and governed-version tests |
| GitHub Actions | `.github/workflows/project-foundation.yml` | Actions pinned to commit SHAs | Scaffolded | PR/main validation only; no deploy or cloud authentication | Path policy and GitHub checks |
| Power BI | Future `bi/` path | Not selected | Deferred | Semantic/operational consumption only | Future model/report tests |
| Synthetic source generator | `src/claimsflow/generator` | Python 3.12 | Phase 2 slice implemented | Reserved fictional data and immutable generator manifests | Determinism, contract-header, provenance, reconciliation, and safety tests |
| Local ingestion and structural validation | `src/claimsflow/ingestion`; `claimsflow ingest` | Python 3.12; PyYAML 6.0.3 | Phase 2 slice implemented | Reproduce deterministic provenance, verify contracts, stream landed raw evidence, classify each row, reconcile, hash artifact inventory, and register through an injected port without cloud writes | Forged provenance, landing TOCTOU, financial/type policy, replay tamper, partial duplicate, concurrency, crash recovery, and reconciliation tests |

## Version authority

Application dependencies are exact pins in `pyproject.toml` and complete resolutions in
`uv.lock`. Airflow stays in its pinned official image because Apache Airflow supports pip
installation with its own tested constraints rather than becoming part of the application
lock. Terraform root and module constraints pin the CLI/provider compatibility boundary;
the dev/demo root owns its generated Google provider lock. The local root uses only
Terraform's built-in provider and therefore has no external-provider lock entry.

## Next milestone

Phase 3 now has local contract-driven cross-family relationships, effective references,
temporal/pointer checks, freshness evidence, financial controls, final validated/quarantine/
rejected routing, immutable correction history, and a fail-closed publication gate. The next
feature slice is Phase 4: dbt validated staging, curated dimensional models, reconciliation
tests, and governed metric implementations. A live isolated synthetic GCP exercise remains a
separate explicitly approved integration gate; dashboards and automated deployment remain
later slices.
