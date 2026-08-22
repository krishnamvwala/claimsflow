from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
DBT = ROOT / "analytics" / "dbt"
PUBLICATION = DBT / "models" / "publication"


def _mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_publication_sources_and_active_membership_contract_are_complete() -> None:
    properties = _mapping(
        yaml.safe_load((PUBLICATION / "_publication.yml").read_text(encoding="utf-8"))
    )
    sources = cast(list[dict[str, Any]], properties["sources"])
    assert len(sources) == 1
    source = _mapping(sources[0])
    assert source["name"] == "publication_control"
    assert source["schema"] == "claimsflow_audit"
    assert {table["name"] for table in cast(list[dict[str, Any]], source["tables"])} == {
        "active_publications",
        "publication_activations",
        "publication_manifests",
        "publication_membership_deltas",
        "publication_result_versions",
        "publication_candidate_inventory",
        "publication_reservation_locks",
    }

    models = cast(list[dict[str, Any]], properties["models"])
    assert len(models) == 1
    model = _mapping(models[0])
    assert model["name"] == "active_publication_membership"
    config = _mapping(model["config"])
    metadata = _mapping(config["meta"])
    assert config["access"] == "protected"
    assert _mapping(config["contract"])["enforced"] is True
    assert metadata["owner"] == "ClaimsFlow Analytics Engineering"
    assert metadata["materialization"] == "view"
    assert metadata["publication_scoped"] is False
    assert metadata["grain"]
    assert metadata["purpose"]
    assert set(metadata["source_models"]) == {
        "source:publication_control.active_publications",
        "source:publication_control.publication_manifests",
        "source:publication_control.publication_membership_deltas",
        "source:publication_control.publication_result_versions",
    }
    columns = cast(list[dict[str, Any]], model["columns"])
    assert {column["name"] for column in columns} == {
        "environment",
        "active_publication_id",
        "active_revision",
        "mapping_publication_id",
        "logical_relation",
        "business_key",
        "result_version_id",
        "result_source_publication_id",
        "result_sha256",
        "physical_relation",
    }
    assert all(column["description"] and column["data_type"] for column in columns)
    assert all("not_null" in column["data_tests"] for column in columns)


def test_active_membership_view_uses_pointer_chain_precedence_and_tombstones() -> None:
    sql = (PUBLICATION / "active_publication_membership.sql").read_text(encoding="utf-8")
    assert "source('publication_control', 'active_publications')" in sql
    assert "source('publication_control', 'publication_manifests')" in sql
    assert "cross join unnest(membership_delta_chain)" in sql
    assert "order by chain.chain_position desc, delta.sequence desc" in sql
    assert "membership_precedence = 1" in sql
    assert "and not tombstone" in sql
    assert "source('publication_control', 'publication_result_versions')" in sql
    assert "source(" not in sql.replace("source('publication_control'", "")
    assert "raw" not in sql.lower()
    assert "quarantine" not in sql.lower()


def test_publication_integrity_gate_covers_pointer_manifest_delta_and_version_failures() -> None:
    sql = (DBT / "tests" / "publication_active_membership_integrity.sql").read_text(
        encoding="utf-8"
    )
    for failure in (
        "duplicate_active_pointer",
        "duplicate_manifest_id",
        "invalid_active_manifest",
        "broken_active_chain",
        "failed_active_gate",
        "missing_active_gate",
        "duplicate_delta_key",
        "duplicate_result_version",
        "duplicate_inventory_key",
        "duplicate_inventory_sequence",
        "orphan_membership",
        "duplicate_resolved_key",
        "untrusted_result_source",
        "active_inventory_mismatch",
    ):
        assert f"'{failure}'" in sql
    assert "is distinct from 'passed'" in sql
    assert "array_length(membership_delta_chain) > 8" in sql
    assert "membership_mode = 'base'" in sql
    assert "membership_mode = 'delta'" in sql
    assert "config(tags=['publication_control', 'phase4b3'])" in sql


def test_publication_control_selector_parses_offline(tmp_path: Path) -> None:
    dbt = Path(sys.executable).with_name("dbt")
    assert dbt.is_file()
    completed = subprocess.run(
        [
            str(dbt),
            "--quiet",
            "ls",
            "--project-dir",
            str(DBT),
            "--profiles-dir",
            str(ROOT / "config" / "dbt"),
            "--target",
            "ci",
            "--no-partial-parse",
            "--output",
            "name",
            "--select",
            "tag:publication_control",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DBT_TARGET_PATH": str(tmp_path / "dbt-target"),
            "DBT_LOG_PATH": str(tmp_path / "dbt-logs"),
        },
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert {
        "active_publication_membership",
        "publication_active_membership_integrity",
    } <= set(completed.stdout.splitlines())
