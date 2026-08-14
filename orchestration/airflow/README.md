# Local Airflow

Airflow 3.3.1 runs from an image pinned by release tag and immutable digest, so its large,
pip-and-constraints-managed dependency graph stays outside the locked application
environment. The inert Phase 1 DAG does not import the ClaimsFlow application package, so the
image performs no networked package installation. A later executable DAG milestone must
install a wheel produced from `uv.lock` rather than resolving application dependencies during
the image build. No cloud credentials are copied into the image or Compose configuration.

The Phase 1 DAG is intentionally inert: it proves fail-closed task order, retry policy,
bounded concurrency, timeout declarations, and identifier-only failure logging. Its empty
operators do not move data or publish anything. Later milestones replace tasks with thin
calls into tested Python and dbt components; business rules never move into the DAG.

Start the local service with `make airflow-up`, record the one-time standalone credentials
shown by Airflow, and open `http://127.0.0.1:8080`. The host port binds only to loopback. Stop
it with `make airflow-down`.

Everything under `logs/`, `db/`, and the generated password file is ignored by Git.
