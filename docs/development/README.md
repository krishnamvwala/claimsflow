# Local development

ClaimsFlow Phase 1 is a reproducible, synthetic-only project foundation. The default
validation path does not contact Google Cloud, create infrastructure, or process claim rows.

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
- `make dbt-parse` parses the empty Phase 1 dbt project with a non-secret CI profile.
- `make airflow-up` builds and starts digest-pinned Airflow 3.3.1 at
  `http://127.0.0.1:8080`; the standalone process prints temporary local credentials.
- `make airflow-down` stops the local Airflow service.
- `make terraform-validate` formats-checks and validates both Terraform roots.

The Airflow DAG uses empty operators in this milestone. It proves orchestration order and
failure policy but cannot load, transform, publish, refresh, or alert. dbt contains no
business models yet. Terraform validation reads provider schemas but does not create
resources.

CI loads the DAG through Airflow's `DagBag` and verifies the exact effective task graph,
timeouts, retry behavior, trigger rules, pool, and failure callback. The local web port is
bound to loopback only.

## Dev/demo infrastructure safety

Phase 1 defines the future Google Cloud resources; it does not deploy them. Do not run
`terraform apply` until all of the following exist:

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

Never delete landing or raw evidence to recover a pipeline. This Phase 1 repository has no
data cleanup command.

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
