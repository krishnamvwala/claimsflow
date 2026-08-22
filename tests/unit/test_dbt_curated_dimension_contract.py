from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
DBT = ROOT / "analytics" / "dbt"
DIMENSIONS = DBT / "models" / "curated" / "dimensions"

DIMENSION_NAMES = {
    "dim_date",
    "dim_denial_reason",
    "dim_diagnosis",
    "dim_facility",
    "dim_patient",
    "dim_payer",
    "dim_plan",
    "dim_procedure",
    "dim_provider",
}
EFFECTIVE_DIMENSIONS = DIMENSION_NAMES - {"dim_date", "dim_patient"}


def _mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _properties() -> dict[str, dict[str, Any]]:
    root = _mapping(yaml.safe_load((DIMENSIONS / "_dimensions.yml").read_text(encoding="utf-8")))
    models = root["models"]
    assert isinstance(models, list)
    return {cast(str, _mapping(model)["name"]): _mapping(model) for model in models}


def test_generated_curated_dimension_properties_are_current() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_dbt_curated_dimension_properties.py"),
            "--check",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_curated_dimension_inventory_and_contract_metadata_are_exact() -> None:
    properties = _properties()
    sql_names = {path.stem for path in DIMENSIONS.glob("*.sql")}
    assert set(properties) == DIMENSION_NAMES
    assert sql_names == DIMENSION_NAMES

    for name, model in properties.items():
        config = _mapping(model["config"])
        metadata = _mapping(config["meta"])
        assert config["access"] == "protected"
        assert _mapping(config["contract"])["enforced"] is True
        assert metadata["owner"] == "ClaimsFlow Analytics Engineering"
        assert metadata["materialization"] == "table"
        assert metadata["publication_scoped"] is True
        assert isinstance(metadata["grain"], str) and metadata["grain"]
        assert isinstance(metadata["purpose"], str) and metadata["purpose"]
        assert isinstance(metadata["history_strategy"], str) and metadata["history_strategy"]
        assert isinstance(metadata["source_models"], list) and metadata["source_models"]

        columns = [_mapping(column) for column in cast(list[object], model["columns"])]
        column_names = [cast(str, column["name"]) for column in columns]
        assert len(column_names) == len(set(column_names))
        common_names = {
            "candidate_publication_id",
            "candidate_selection_fingerprint",
            "synthetic_only",
        }
        assert common_names <= set(column_names)
        assert all(
            isinstance(column["description"], str)
            and column["description"]
            and isinstance(column["data_type"], str)
            for column in columns
        )

        sql = (DIMENSIONS / f"{name}.sql").read_text(encoding="utf-8").lower()
        assert "source(" not in sql
        assert "raw" not in sql
        assert "quarantine" not in sql


def test_effective_dimensions_declare_history_keys_and_lineage() -> None:
    properties = _properties()
    for name in EFFECTIVE_DIMENSIONS:
        entity = name.removeprefix("dim_")
        columns = {
            cast(str, column["name"]): column
            for column in cast(list[dict[str, Any]], properties[name]["columns"])
        }
        assert {
            f"{entity}_dimension_id",
            f"{entity}_business_key",
            "valid_from",
            "valid_to",
            "source_active_flag",
            "is_current",
            "source_validated_record_id",
            "source_validation_id",
            "source_batch_id",
            "quality_report_sha256",
            "quality_configuration_sha256",
            "validated_record_set_sha256",
        } <= set(columns)
        assert "unique" in cast(list[object], columns[f"{entity}_dimension_id"]["data_tests"])

    plan_columns = {
        cast(str, column["name"]): column
        for column in cast(list[dict[str, Any]], properties["dim_plan"]["columns"])
    }
    payer_tests = cast(list[object], plan_columns["payer_dimension_id"]["data_tests"])
    assert any(
        isinstance(test, dict)
        and _mapping(_mapping(test)["relationships"])["arguments"]
        == {"to": "ref('dim_payer')", "field": "payer_dimension_id"}
        for test in payer_tests
    )


def test_curated_dimension_models_use_deterministic_keys_and_governed_dependencies() -> None:
    macro = (DBT / "macros" / "curated_dimensions.sql").read_text(encoding="utf-8")
    assert "to_hex(" in macro
    assert "sha256(" in macro
    assert "to_json_string(" in macro
    assert "claimsflow_effective_dimension" in macro
    assert "ref(source_model)" in macro
    assert "claimsflow_candidate_dates" in macro

    allowed_dependencies = {
        "dim_payer",
        "stg_appeals",
        "stg_claim_lines",
        "stg_claims",
        "stg_denials",
        "stg_eligibility",
        "stg_payments",
        "stg_remittances",
        "stg_reference_denial_reasons",
        "stg_reference_diagnoses",
        "stg_reference_facilities",
        "stg_reference_payers",
        "stg_reference_plans",
        "stg_reference_procedures",
        "stg_reference_providers",
    }
    dependency_text = (
        macro
        + "\n"
        + "\n".join(path.read_text(encoding="utf-8") for path in sorted(DIMENSIONS.glob("*.sql")))
    )
    literal_refs = set(re.findall(r"ref\('([a-z0-9_]+)'\)", dependency_text))
    assert literal_refs <= allowed_dependencies
    assert set(re.findall(r"'((?:stg_)[a-z0-9_]+)'", macro)) >= (
        allowed_dependencies - {"dim_payer"}
    )


def test_curated_singular_tests_cover_scope_history_reconciliation_and_dates() -> None:
    tests = DBT / "tests"
    publication = (tests / "curated_dimension_publication_scope.sql").read_text(encoding="utf-8")
    reconciliation = (tests / "curated_dimension_reconciliation.sql").read_text(encoding="utf-8")
    history = (tests / "curated_dimension_history_integrity.sql").read_text(encoding="utf-8")
    relationship = (tests / "curated_plan_payer_effective_relationship.sql").read_text(
        encoding="utf-8"
    )
    date_coverage = (tests / "curated_date_coverage.sql").read_text(encoding="utf-8")
    date_span = (tests / "curated_date_span_bound.sql").read_text(encoding="utf-8")

    for name in DIMENSION_NAMES:
        assert f"'{name}'" in publication
    for name in DIMENSION_NAMES - {"dim_date"}:
        assert f"'{name}'" in reconciliation
    for name in EFFECTIVE_DIMENSIONS:
        assert f"'{name}'" in history
    assert "source_active_flag != (valid_to is null)" in history
    assert "overlapping_history_versions" in history
    assert "payer.payer_dimension_id is null" in relationship
    assert "claimsflow_candidate_dates" in date_coverage
    assert "generate_date_array" in date_coverage
    assert "except distinct" in date_coverage
    assert "claimsflow_max_date_spine_days" in date_span
    assert "date_spine_days" in date_span
    assert "config(tags=['curated_dimensions', 'phase4b1'])" in date_span


def test_curated_selector_includes_date_span_release_gate() -> None:
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
            "tag:curated_dimensions",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    selected_names = set(completed.stdout.splitlines())
    assert "curated_date_span_bound" in selected_names

    dev_demo = subprocess.run(
        [
            str(dbt),
            "--quiet",
            "ls",
            "--project-dir",
            str(DBT),
            "--profiles-dir",
            str(ROOT / "config" / "dbt"),
            "--target",
            "dev_demo",
            "--no-partial-parse",
            "--output",
            "name",
            "--select",
            "tag:curated_dimensions",
            "--vars",
            (
                "{claimsflow_publication_id: selector_regression, "
                "claimsflow_validation_ids: [selector_validation], "
                "claimsflow_code_commit: '1111111111111111111111111111111111111111'}"
            ),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert dev_demo.returncode == 0, dev_demo.stdout + dev_demo.stderr
    assert "curated_date_span_bound" in set(dev_demo.stdout.splitlines())
