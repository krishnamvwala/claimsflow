from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
DBT = ROOT / "analytics" / "dbt"
CONTRACTS = ROOT / "contracts" / "source-data"
STAGING = DBT / "models" / "staging"


def _mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _models() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(CONTRACTS.glob("*.yml")):
        contract = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
        family = cast(str, contract["source_family"])
        datasets = contract.get("datasets")
        if datasets is None:
            result[family] = {
                "contract_id": contract["contract_id"],
                "grain": contract["grain"],
                "fields": contract["schema"],
            }
            continue
        assert isinstance(datasets, list)
        for value in datasets:
            dataset = _mapping(value)
            result[f"{family}.{dataset['name']}"] = {
                "contract_id": contract["contract_id"],
                "grain": dataset["grain"],
                "fields": dataset["schema"],
            }
    return result


def _model_name(identity: str) -> str:
    if identity.startswith("reference-data."):
        return f"stg_reference_{identity.removeprefix('reference-data.').replace('-', '_')}"
    return f"stg_{identity.replace('-', '_')}"


def _dbt_type(source_type: str) -> str:
    if source_type.startswith("NUMERIC("):
        return "numeric"
    return {
        "STRING": "string",
        "STRING_LIST": "array<string>",
        "INTEGER": "int64",
        "DATE": "date",
        "TIMESTAMP": "timestamp",
        "BOOLEAN": "bool",
    }[source_type]


def test_generated_staging_properties_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "render_dbt_staging_properties.py"), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_every_contract_identity_has_one_exact_typed_staging_model() -> None:
    expected = _models()
    properties = _mapping(yaml.safe_load((STAGING / "_staging.yml").read_text(encoding="utf-8")))
    raw_models = properties["models"]
    assert isinstance(raw_models, list)
    documented = {_mapping(value)["name"]: _mapping(value) for value in raw_models}
    expected_names = {_model_name(identity) for identity in expected}
    sql_names = {
        path.stem for path in STAGING.glob("*.sql") if path.name != "stg_validated_records.sql"
    }
    assert set(documented) == expected_names
    assert sql_names == expected_names
    assert len(expected_names) == 14

    for identity, definition in expected.items():
        model_name = _model_name(identity)
        model = documented[model_name]
        config = _mapping(model["config"])
        metadata = _mapping(config["meta"])
        assert config["access"] == "protected"
        assert _mapping(config["contract"])["enforced"] is True
        assert metadata == {
            "source_identity": identity,
            "contract_id": definition["contract_id"],
            "grain": definition["grain"],
            "owner": "ClaimsFlow Data Engineering",
            "publication_scoped": True,
        }

        columns = [_mapping(value) for value in cast(list[object], model["columns"])]
        business_columns = {
            cast(str, _mapping(_mapping(column["config"])["meta"])["source_field"]): column
            for column in columns
            if "config" in column
            and "meta" in _mapping(column["config"])
            and "source_field" in _mapping(_mapping(column["config"])["meta"])
        }
        fields = [_mapping(value) for value in cast(list[object], definition["fields"])]
        assert set(business_columns) == {field["name"] for field in fields}
        for field in fields:
            column = business_columns[cast(str, field["name"])]
            assert column["data_type"] == _dbt_type(cast(str, field["type"]))
            assert column["description"] == field["description"]
            assert _mapping(_mapping(column["config"])["meta"])["source_type"] == field["type"]
            tests = cast(list[object], column.get("data_tests", []))
            assert ("not_null" in tests) is (field["nullable"] is False)

        sql = (STAGING / f"{model_name}.sql").read_text(encoding="utf-8")
        identity_match = re.search(r"source_identity='([^']+)'", sql)
        assert identity_match is not None and identity_match.group(1) == identity
        sql_fields = re.findall(
            r"\('([a-z][a-z0-9_]*)', '([A-Z_]+(?:\([0-9]+,[0-9]+\))?)'\)",
            sql,
        )
        assert sql_fields == [
            (cast(str, field["name"]), cast(str, field["type"])) for field in fields
        ]
        assert "source(" not in sql.lower()


def test_staging_sources_cannot_bypass_validated_boundary() -> None:
    source_text = (STAGING / "_sources.yml").read_text(encoding="utf-8")
    sources = _mapping(yaml.safe_load(source_text))["sources"]
    assert isinstance(sources, list)
    source_tables = {
        _mapping(source)["name"]: {
            _mapping(table)["name"] for table in cast(list[object], _mapping(source)["tables"])
        }
        for source in sources
    }
    assert source_tables == {
        "claimsflow_validated": {"records"},
        "claimsflow_audit": {"quality_runs"},
    }
    source_definitions = {_mapping(source)["name"]: _mapping(source) for source in sources}
    validated_table = _mapping(
        cast(list[object], source_definitions["claimsflow_validated"]["tables"])[0]
    )
    audit_table = _mapping(cast(list[object], source_definitions["claimsflow_audit"]["tables"])[0])
    validated_columns = {
        _mapping(column)["name"] for column in cast(list[object], validated_table["columns"])
    }
    audit_columns = {
        _mapping(column)["name"] for column in cast(list[object], audit_table["columns"])
    }
    assert {
        "record_evidence_sha256",
        "normalized_payload_canonical_json",
        "normalized_payload_sha256",
    } <= validated_columns
    assert {
        "validated_record_evidence_algorithm",
        "validated_record_set_algorithm",
        "validated_record_count",
        "validated_record_set_sha256",
    } <= audit_columns
    base = (STAGING / "stg_validated_records.sql").read_text(encoding="utf-8")
    assert "source('claimsflow_validated', 'records')" in base
    assert "source('claimsflow_audit', 'quality_runs')" in base
    for condition in (
        "synthetic_only is true",
        "publication_allowed is true",
        "reconciled is true",
        "decision = 'approved'",
        "claimsflow_validation_filter",
        "computed_record_evidence_sha256",
        "computed_normalized_payload_sha256",
        "quality.validated_record_set_sha256 = record_set.computed_record_set_sha256",
        "record_set.mismatched_record_evidence_count = 0",
    ):
        assert condition in base


def test_candidate_alias_and_validation_allowlist_fail_closed() -> None:
    project = (DBT / "dbt_project.yml").read_text(encoding="utf-8")
    scope = (DBT / "macros" / "publication_scope.sql").read_text(encoding="utf-8")
    alias = (DBT / "macros" / "generate_alias_name.sql").read_text(encoding="utf-8")
    assert "claimsflow_publication_id: ci_phase4a" in project
    assert "claimsflow_validation_ids: [ci_validation_phase4a]" in project
    assert "target.name != 'ci'" in scope
    assert "unique claimsflow_publication_id" in scope
    assert "non-empty list of immutable quality validation IDs" in scope
    assert "local_md5(canonical_selection)" in scope
    assert "publication_scoped" in alias
    assert "base_alias }}__{{ claimsflow_publication_id()" in alias
    assert "claimsflow_publication_selection_fingerprint()" in alias
    staging_macro = (DBT / "macros" / "stage_validated.sql").read_text(encoding="utf-8")
    assert (
        "sha256(cast({{ record_alias }}.normalized_payload_canonical_json as string))"
        in staging_macro
    )
    assert "claimsflow_json_value('normalized_payload_canonical_json'" in staging_macro
    assert "claimsflow_json_value('normalized_payload'," not in staging_macro


def test_reconciliation_tests_cover_every_typed_staging_model() -> None:
    reconciliation = (DBT / "tests" / "staging_reconciles_to_typed_models.sql").read_text(
        encoding="utf-8"
    )
    expected_names = {_model_name(identity) for identity in _models()}
    referenced_names = set(re.findall(r"'((?:stg_)[a-z_]+)'", reconciliation))
    referenced_names.discard("stg_validated_records")
    assert referenced_names == expected_names
    counts = (DBT / "tests" / "staging_reconciles_to_quality_counts.sql").read_text(
        encoding="utf-8"
    )
    assert "accepted + warned as expected_validated_rows" in counts
    assert "full outer join staged_counts" in counts
    record_set = (DBT / "tests" / "staging_reconciles_to_validated_record_set.sql").read_text(
        encoding="utf-8"
    )
    assert "claimsflow_validated_record_evidence_sha256" in record_set
    assert "claimsflow_normalized_payload_sha256" in record_set
    assert (
        "normalized_payload_sha256 is distinct from computed_normalized_payload_sha256"
        in record_set
    )
    assert "record_evidence_sha256 is distinct from computed_record_evidence_sha256" in record_set
    assert (
        "validated_record_set_sha256\n    is distinct from record_set.computed_record_set_sha256"
        in record_set
    )
    required = (DBT / "tests" / "staging_requires_every_validation.sql").read_text(encoding="utf-8")
    assert "audit_row_count" in required
    assert "approved_row_count" in required
    assert "!= 1" in required
