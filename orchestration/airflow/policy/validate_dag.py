"""Runtime policy test for the ClaimsFlow Airflow DAG."""

from __future__ import annotations

import argparse
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from typing import NoReturn

from airflow.models import DagBag
from airflow.task.trigger_rule import TriggerRule

EXPECTED_TASKS = (
    "register_delivery",
    "verify_landing_object",
    "load_raw",
    "validate_batch",
    "build_candidate",
    "reconcile",
    "evaluate_publication_gates",
    "advance_publication",
    "refresh_bi",
    "evaluate_alerts",
)
EXPECTED_EDGES = set(pairwise(EXPECTED_TASKS))


def fail(message: str) -> NoReturn:
    """Stop the policy check with an actionable error."""

    raise RuntimeError(message)


def validate(dag_folder: Path) -> None:
    """Load the DAG through Airflow and assert its effective policy."""

    dag_bag = DagBag(dag_folder=str(dag_folder), safe_mode=False)
    if dag_bag.import_errors:
        fail(f"DAG import errors: {dag_bag.import_errors}")

    dag = dag_bag.dags.get("claimsflow_synthetic_batch")
    if dag is None:
        fail("claimsflow_synthetic_batch was not loaded")
    if set(dag.task_ids) != set(EXPECTED_TASKS):
        fail(f"unexpected task IDs: {sorted(dag.task_ids)}")

    actual_edges = {
        (task.task_id, downstream_id)
        for task in dag.tasks
        for downstream_id in task.downstream_task_ids
    }
    if actual_edges != EXPECTED_EDGES:
        fail(f"unexpected DAG edges: {sorted(actual_edges)}")

    if dag.catchup:
        fail("catchup must remain disabled")
    if dag.max_active_runs != 1 or dag.max_active_tasks != 4:
        fail("DAG concurrency must remain max_active_runs=1 and max_active_tasks=4")

    for task in dag.tasks:
        expected_retries = 0 if task.task_id == "advance_publication" else 2
        if task.retries != expected_retries:
            fail(f"{task.task_id} retries must be {expected_retries}")
        if task.execution_timeout != timedelta(minutes=30):
            fail(f"{task.task_id} must have a 30-minute execution timeout")
        if not task.retry_exponential_backoff:
            fail(f"{task.task_id} must use exponential retry backoff")
        if task.pool != "default_pool":
            fail(f"{task.task_id} must use the bounded default_pool")
        if task.trigger_rule != TriggerRule.ALL_SUCCESS:
            fail(f"{task.task_id} must fail closed with all_success")
        if task.on_failure_callback is None:
            fail(f"{task.task_id} must retain the identifier-only failure callback")

    print(
        "Airflow DAG policy passed: "
        f"{len(EXPECTED_TASKS)} tasks, {len(EXPECTED_EDGES)} exact fail-closed edges."
    )


def main() -> None:
    """Parse the DAG folder argument and run validation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--dag-folder", type=Path, default=Path("/opt/airflow/dags"))
    arguments = parser.parse_args()
    validate(arguments.dag_folder)


if __name__ == "__main__":
    main()
