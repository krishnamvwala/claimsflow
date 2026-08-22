# Local development

ClaimsFlow has a reproducible, synthetic-only project foundation, deterministic Phase 2
generator, idempotent local ingestion boundary, fake-tested Cloud Storage plus BigQuery
raw/audit adapters, a local Phase 3 quality/quarantine gate, Phase 4A publication-scoped
dbt validated staging, Phase 4B.1 publication-scoped dbt curated dimensions, and Phase 4B.2
publication-scoped dbt curated facts, plus the Phase 4B.3 safe-publication control plane and
active-membership view. The default validation path does not contact Google Cloud or create
infrastructure. Generated, ingested, and quality-run claim rows stay in explicit user-selected
local directories unless an authorized caller explicitly composes the cloud publication
service.

## Prerequisites

- Git
- Python 3.12
- uv 0.12.4
- Ruby 2.6 or newer for the repository policy validators
- Docker with Compose for Airflow
- Terraform 1.15.8 for infrastructure validation

Use the official installation instructions for
[uv](https://docs.astral.sh/uv/getting-started/installation/),
[Docker](https://docs.docker.com/engine/install/), and
[Terraform](https://developer.hashicorp.com/terraform/install). Keep the versions above
aligned with `pyproject.toml`, the Docker image, Terraform constraints, and the release
manifest.

## Clean setup

From the repository root:

```bash
cp .env.example .env
make bootstrap
uv run --locked claimsflow doctor
make check
```

`make bootstrap` creates `.venv` from the committed `uv.lock`. `make check` runs the Phase 0
contract, metric, and architecture gates plus the Phase 1 scaffold policy, Python checks, and
an offline dbt parse. No Google credentials are required.

Keep `CLAIMSFLOW_SYNTHETIC_ONLY=true`. The application fails closed if that value changes.
Never put patient, customer, payer, credential, or service-account material into `.env`,
fixtures, logs, screenshots, Terraform variables, or issue/PR text.

## Component commands

- `make check` runs every offline repository gate.
- `make check-python` runs Ruff lint/format checks, strict mypy, and pytest.
- `make dbt-parse` verifies generated Phase 4A staging, Phase 4B.1 dimension, and Phase 4B.2
  fact contracts and parses those models plus the Phase 4B.3 active-publication resolver and
  integrity gate with a non-secret CI profile.
- `uv run --locked claimsflow generate --service-month 2026-07 --claims 1000 --seed 20260815 --output data/generated/demo-2026-07`
  creates a bounded, repeatable fictional delivery without overwriting existing paths.
- `uv run --locked claimsflow ingest --manifest data/generated/demo-2026-07/manifest.json --workspace data/local-ingestion`
  independently verifies, classifies, reconciles, lands, and registers the delivery. An
  identical replay is an audited `duplicate_no_op` and never republishes rows.
- `uv run --locked claimsflow validate --batch-id <batch-id> --workspace data/local-ingestion`
  executes the versioned Phase 3 relationship, effective-reference, freshness, correction,
  financial-reconciliation, quarantine, configuration-binding, deterministic replay, and
  publication-gate boundary without cloud writes. Same-hour replay is a verified no-op;
  later governed hourly windows publish updated freshness evidence.
- [Cloud raw adapters](cloud-raw-adapters.md) documents the programmatic, generation-pinned
  publication boundary. There is intentionally no default cloud-write CLI command.
- [Data quality and quarantine](data-quality-quarantine.md) documents final dispositions,
  immutable correction evidence, exact configuration hashes, durable replay receipts, and
  fail-closed publication behavior.
- [dbt validated staging](dbt-validated-staging.md) documents the candidate publication ID,
  immutable validation allowlist, fourteen typed staging models, source interface, and
  reconciliation tests.
- [dbt curated dimensions](dbt-curated-dimensions.md) documents the nine dimensions,
  deterministic keys, effective-dated history, candidate isolation, and fail-closed tests.
- [dbt curated facts](dbt-curated-facts.md) documents the five facts, parent and effective
  relationships, date roles, exact source reconciliation, and financial-integrity gates.
- [Safe publication and rollback](safe-publication.md) documents immutable manifests, complete
  key/hash inventories, exact changed-key deltas, trusted result-version evidence, serialized
  reservations, gate evaluation, compare-and-swap activation, compaction,
  active-membership resolution, and pointer-only rollback.
- `make airflow-up` builds and starts digest-pinned Airflow 3.3.1 at
  `http://127.0.0.1:8080`; the standalone process prints temporary local credentials.
- `make airflow-down` stops the local Airflow service.
- `make terraform-validate` formats-checks and validates both Terraform roots.

The Airflow DAG uses empty operators in this milestone. It proves orchestration order and
failure policy but does not yet call the implemented cloud adapters, transform, publish,
refresh, or alert. dbt contains validated staging, curated dimensions, curated facts, and the
active-membership resolver; semantic metrics and priority logic remain disabled. Terraform validation reads provider schemas but does not
create resources.

CI loads the DAG through Airflow's `DagBag` and verifies the exact effective task graph,
timeouts, retry behavior, trigger rules, pool, and failure callback. The local web port is
bound to loopback only.

## Dev/demo infrastructure safety

Terraform defines the future Google Cloud resources and the Python adapters can target them,
but nothing deploys or writes by default. Do not run `terraform apply` or compose live adapter
clients until all of the following exist:

1. A dedicated synthetic-only GCP project and access-controlled remote-state bucket.
2. Reviewed non-secret environment values, the mandatory bounded billing budget, and the
   enabled Cloud Billing Budget API.
3. A saved plan reviewed through a protected GitHub environment.
4. Keyless GitHub Workload Identity Federation restricted by immutable repository/owner
   IDs, exact workflow, `main`, protected environment, and a manual approval.

The committed example creates no secret. Local operators should use Application Default
Credentials only for an explicitly approved plan; long-lived service-account JSON keys are
prohibited.

## Generated local state

The following are intentionally untracked:

- `.env`, `.venv`, Python caches, and test reports
- dbt `target`, logs, and downloaded packages
- Airflow logs, SQLite metadata, configuration, and generated passwords
- Terraform state, plans, override files, and `.terraform` plugin directories
- synthetic delivery outputs under `data/generated/`
- local ingestion registries and batch evidence under `data/local-ingestion/`

Never delete landing, registry, or raw evidence to recover a pipeline. ClaimsFlow has no data
cleanup command; use a new isolated workspace for disposable local demonstrations.

## Troubleshooting

- If `uv sync --locked` reports lock drift, do not bypass `--locked`; reconcile
  `pyproject.toml` and regenerate `uv.lock` in a reviewed change.
- If dbt asks for credentials during `dbt parse`, confirm `--target ci` and the committed
  profile path are being used.
- If port 8080 is occupied, stop the conflicting service or temporarily override the host
  port locally without committing the change.
- If Terraform initialization fails, confirm Terraform 1.15.8 and network access to the
  HashiCorp registry. Validation must always use `-backend=false`.
- Run `ruby scripts/validate_project_scaffolding.rb` first when a component path or pinned
  version changes; its error explains the required invariant.
