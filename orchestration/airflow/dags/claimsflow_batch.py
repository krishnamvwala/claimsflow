"""Synthetic-only ClaimsFlow batch orchestration skeleton.

The DAG owns dependency and recovery policy only. Empty tasks intentionally defer ingestion,
validation, transformation, reconciliation, publication, BI refresh, and alert logic to their
owning components in later milestones.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk import DAG

LOGGER = logging.getLogger(__name__)


def log_failure_identifiers(context: dict[str, Any]) -> None:
    """Log only orchestration identifiers; never serialize XCom values or row payloads."""

    task_instance = context.get("task_instance")
    dag_run = context.get("dag_run")
    LOGGER.error(
        "claimsflow_task_failed",
        extra={
            "environment_id": "local",
            "run_id": getattr(dag_run, "run_id", "unknown"),
            "task_id": getattr(task_instance, "task_id", "unknown"),
        },
    )


DEFAULT_TASK_ARGS = {
    "depends_on_past": False,
    "execution_timeout": timedelta(minutes=30),
    "on_failure_callback": log_failure_identifiers,
    "pool": "default_pool",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "trigger_rule": "all_success",
}


with DAG(
    dag_id="claimsflow_synthetic_batch",
    description="SYNTHETIC DATA ONLY — fail-closed ClaimsFlow batch skeleton",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=4,
    default_args=DEFAULT_TASK_ARGS,
    tags=["claimsflow", "synthetic-only", "portfolio"],
) as dag:
    register_delivery = EmptyOperator(task_id="register_delivery")
    verify_landing_object = EmptyOperator(task_id="verify_landing_object")
    load_raw = EmptyOperator(task_id="load_raw")
    validate_batch = EmptyOperator(task_id="validate_batch")
    build_candidate = EmptyOperator(task_id="build_candidate")
    reconcile = EmptyOperator(task_id="reconcile")
    evaluate_publication_gates = EmptyOperator(task_id="evaluate_publication_gates")
    advance_publication = EmptyOperator(
        task_id="advance_publication",
        retries=0,
    )
    refresh_bi = EmptyOperator(task_id="refresh_bi")
    evaluate_alerts = EmptyOperator(task_id="evaluate_alerts")

    (
        register_delivery
        >> verify_landing_object
        >> load_raw
        >> validate_batch
        >> build_candidate
        >> reconcile
        >> evaluate_publication_gates
        >> advance_publication
        >> refresh_bi
        >> evaluate_alerts
    )
