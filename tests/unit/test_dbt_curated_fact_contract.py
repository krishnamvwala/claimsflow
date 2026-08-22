from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
DBT = ROOT / "analytics" / "dbt"
FACTS = DBT / "models" / "curated" / "facts"

FACT_NAMES = {
    "fact_appeal",
    "fact_claim",
    "fact_claim_line",
    "fact_denial",
    "fact_payment",
}
FACT_KEYS = {
    "fact_appeal": "appeal_fact_id",
    "fact_claim": "claim_fact_id",
    "fact_claim_line": "claim_line_fact_id",
    "fact_denial": "denial_fact_id",
    "fact_payment": "payment_fact_id",
}


def _mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _properties() -> dict[str, dict[str, Any]]:
    root = _mapping(yaml.safe_load((FACTS / "_facts.yml").read_text(encoding="utf-8")))
    models = root["models"]
    assert isinstance(models, list)
    return {cast(str, _mapping(model)["name"]): _mapping(model) for model in models}


def test_generated_curated_fact_properties_are_current() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_dbt_curated_fact_properties.py"),
            "--check",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_curated_fact_inventory_contracts_and_storage_metadata_are_exact() -> None:
    properties = _properties()
    assert set(properties) == FACT_NAMES
    assert {path.stem for path in FACTS.glob("*.sql")} == FACT_NAMES

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
        assert isinstance(metadata["partition_by"], str) and metadata["partition_by"]
        assert isinstance(metadata["cluster_by"], list) and metadata["cluster_by"]
        assert isinstance(metadata["source_models"], list) and metadata["source_models"]
        assert isinstance(metadata["financial_fields"], list) and metadata["financial_fields"]

        columns = [_mapping(column) for column in cast(list[object], model["columns"])]
        column_names = [cast(str, column["name"]) for column in columns]
        assert len(column_names) == len(set(column_names))
        assert {
            "candidate_publication_id",
            "candidate_selection_fingerprint",
            FACT_KEYS[name],
            "source_validated_record_id",
            "source_validation_id",
            "source_batch_id",
            "source_disposition",
            "quality_report_sha256",
            "quality_configuration_sha256",
            "validated_record_set_sha256",
            "synthetic_only",
        } <= set(column_names)
        assert all(
            isinstance(column["description"], str)
            and column["description"]
            and isinstance(column["data_type"], str)
            for column in columns
        )
        key_column = next(column for column in columns if column["name"] == FACT_KEYS[name])
        assert key_column["data_tests"] == ["not_null", "unique"]

        sql = (FACTS / f"{name}.sql").read_text(encoding="utf-8").lower()
        assert "source(" not in sql
        assert "raw" not in sql
        assert "quarantine" not in sql
        assert "claimsflow_fact_key" in sql
        assert "partition_by" in sql
        for column_name in column_names:
            assert re.search(rf"\b{re.escape(column_name)}\b", sql), (name, column_name)


def test_curated_fact_relationship_contract_is_complete() -> None:
    properties = _properties()

    required_relationships = {
        "fact_claim": {
            "patient_dimension_id",
            "provider_dimension_id",
            "facility_dimension_id",
            "payer_dimension_id",
            "plan_dimension_id",
            "primary_diagnosis_dimension_id",
        },
        "fact_claim_line": {"claim_fact_id", "procedure_dimension_id"},
        "fact_payment": {"claim_fact_id"},
        "fact_denial": {
            "claim_fact_id",
            "payer_dimension_id",
            "denial_reason_dimension_id",
        },
        "fact_appeal": {"denial_fact_id", "claim_fact_id"},
    }
    for model_name, required_columns in required_relationships.items():
        columns = {
            cast(str, column["name"]): _mapping(column)
            for column in cast(list[dict[str, Any]], properties[model_name]["columns"])
        }
        for column_name in required_columns:
            tests = cast(list[object], columns[column_name]["data_tests"])
            assert "not_null" in tests
            assert any(isinstance(test, dict) and "relationships" in test for test in tests)

    line_columns = {
        cast(str, column["name"]): _mapping(column)
        for column in cast(list[dict[str, Any]], properties["fact_claim_line"]["columns"])
    }
    assert line_columns["diagnosis_dimension_ids"]["data_type"] == "array<string>"
    assert "not_null" in cast(list[object], line_columns["diagnosis_dimension_ids"]["data_tests"])

    payment_config = _mapping(properties["fact_payment"]["config"])
    payment_metadata = _mapping(payment_config["meta"])
    assert set(cast(list[str], payment_metadata["source_models"])) == {
        "stg_payments",
        "stg_remittances",
    }
    payment_columns = {
        cast(str, column["name"]): _mapping(column)
        for column in cast(list[dict[str, Any]], properties["fact_payment"]["columns"])
    }
    remittance_tests = cast(
        list[object], payment_columns["remittance_source_validated_record_id"]["data_tests"]
    )
    assert any(isinstance(test, dict) and "relationships" in test for test in remittance_tests)


def test_curated_fact_models_use_governed_dependencies_and_deterministic_helpers() -> None:
    macro = (DBT / "macros" / "curated_facts.sql").read_text(encoding="utf-8")
    assert "claimsflow_fact_key" in macro
    assert "claimsflow_dimension_key" in macro
    assert "format_date('%Y%m%d'" in macro
    assert "cast(null as int64)" in macro

    model_text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(FACTS.glob("*.sql")))
    assert "date '9999-12-31'" not in model_text
    literal_refs = set(re.findall(r"ref\('([a-z0-9_]+)'\)", model_text))
    assert literal_refs <= {
        *FACT_NAMES,
        "dim_date",
        "dim_denial_reason",
        "dim_diagnosis",
        "dim_facility",
        "dim_patient",
        "dim_payer",
        "dim_plan",
        "dim_procedure",
        "dim_provider",
        "stg_appeals",
        "stg_claim_lines",
        "stg_claims",
        "stg_denials",
        "stg_payments",
        "stg_remittances",
    }
    claim_line_sql = (FACTS / "fact_claim_line.sql").read_text(encoding="utf-8")
    assert "array_agg(" in claim_line_sql
    assert "line_diagnosis_codes" in claim_line_sql
    assert "__unresolved_dimension__" in claim_line_sql
    assert "signed_amount" in (FACTS / "fact_payment.sql").read_text(encoding="utf-8")


def test_curated_fact_singular_tests_cover_all_release_gates() -> None:
    tests = DBT / "tests"
    gate_files = {
        "publication": "curated_fact_publication_scope.sql",
        "reconciliation": "curated_fact_source_reconciliation.sql",
        "parents": "curated_fact_parent_relationships.sql",
        "effective_dimensions": "curated_fact_effective_dimension_relationships.sql",
        "dates": "curated_fact_date_keys.sql",
        "diagnoses": "curated_fact_line_diagnosis_relationships.sql",
        "financials": "curated_fact_financial_integrity.sql",
    }
    contents = {
        name: (tests / filename).read_text(encoding="utf-8")
        for name, filename in gate_files.items()
    }
    for content in contents.values():
        assert "config(tags=['curated_facts', 'phase4b2'])" in content
    for model_name in FACT_NAMES:
        assert f"'{model_name}'" in contents["publication"]
        assert f"'{model_name}'" in contents["reconciliation"]
    assert (
        "source.financial_control is distinct from fact.financial_control"
        in contents["reconciliation"]
    )
    assert "original_claim" in contents["parents"]
    assert "reversed_payment" in contents["parents"]
    assert "remittance_source_validated_record_id" in contents["parents"]
    assert "dimension.valid_to" in contents["effective_dimensions"]
    assert "claimsflow_date_dimension_id" in contents["dates"]
    assert "safe_offset(diagnosis_offset)" in contents["diagnoses"]
    assert "claim_line_rollup" in contents["financials"]
    assert "denial_total_recovery" in contents["financials"]
    assert "remittance_control" in contents["financials"]


def test_curated_fact_and_full_candidate_selectors_include_every_release_gate() -> None:
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
            "tag:validated_staging",
            "tag:curated_dimensions",
            "tag:curated_facts",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    selected_names = set(completed.stdout.splitlines())
    assert selected_names >= FACT_NAMES
    assert {
        "curated_fact_publication_scope",
        "curated_fact_source_reconciliation",
        "curated_fact_parent_relationships",
        "curated_fact_effective_dimension_relationships",
        "curated_fact_date_keys",
        "curated_fact_line_diagnosis_relationships",
        "curated_fact_financial_integrity",
    } <= selected_names

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
            "tag:validated_staging",
            "tag:curated_dimensions",
            "tag:curated_facts",
            "--vars",
            (
                "{claimsflow_publication_id: fact_selector_regression, "
                "claimsflow_validation_ids: [fact_selector_validation], "
                "claimsflow_code_commit: '1111111111111111111111111111111111111111'}"
            ),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert dev_demo.returncode == 0, dev_demo.stdout + dev_demo.stderr
    dev_demo_names = set(dev_demo.stdout.splitlines())
    assert dev_demo_names >= FACT_NAMES | {
        "stg_claims",
        "stg_claim_lines",
        "stg_payments",
        "stg_remittances",
        "dim_date",
        "dim_patient",
        "dim_payer",
    }
    assert {
        "staging_publication_scope",
        "staging_reconciles_to_quality_counts",
        "staging_reconciles_to_typed_models",
        "staging_reconciles_to_validated_record_set",
        "staging_requires_every_validation",
        "curated_date_coverage",
        "curated_date_span_bound",
        "curated_dimension_history_integrity",
        "curated_dimension_publication_scope",
        "curated_dimension_reconciliation",
        "curated_plan_payer_effective_relationship",
        "curated_fact_publication_scope",
        "curated_fact_source_reconciliation",
        "curated_fact_parent_relationships",
        "curated_fact_effective_dimension_relationships",
        "curated_fact_date_keys",
        "curated_fact_line_diagnosis_relationships",
        "curated_fact_financial_integrity",
    } <= dev_demo_names
