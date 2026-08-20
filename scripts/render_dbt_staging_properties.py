#!/usr/bin/env python3
"""Render deterministic dbt staging documentation and contracts from source YAML."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "source-data"
OUTPUT = ROOT / "analytics" / "dbt" / "models" / "staging" / "_staging.yml"


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


MODEL_NAMES = {
    "appeals": "stg_appeals",
    "claim-lines": "stg_claim_lines",
    "claims": "stg_claims",
    "denials": "stg_denials",
    "eligibility": "stg_eligibility",
    "payments": "stg_payments",
    "reference-data.denial-reasons": "stg_reference_denial_reasons",
    "reference-data.diagnoses": "stg_reference_diagnoses",
    "reference-data.facilities": "stg_reference_facilities",
    "reference-data.payers": "stg_reference_payers",
    "reference-data.plans": "stg_reference_plans",
    "reference-data.procedures": "stg_reference_procedures",
    "reference-data.providers": "stg_reference_providers",
    "remittances": "stg_remittances",
}

TYPE_MAP = {
    "STRING": "string",
    "STRING_LIST": "array<string>",
    "INTEGER": "int64",
    "DATE": "date",
    "TIMESTAMP": "timestamp",
    "BOOLEAN": "bool",
}

COMMON_COLUMNS: tuple[tuple[str, str, str, list[object]], ...] = (
    (
        "candidate_publication_id",
        "string",
        "Candidate publication namespace injected by the governed dbt invocation.",
        ["not_null"],
    ),
    (
        "candidate_selection_fingerprint",
        "string",
        "Deterministic fingerprint binding the candidate alias to its validation allowlist.",
        ["not_null"],
    ),
    (
        "validated_record_id",
        "string",
        "Stable SHA-256 key for one source identity, source system, and natural key.",
        ["not_null", "unique"],
    ),
    (
        "validation_id",
        "string",
        "Immutable Phase 3 validation selected by the invocation allowlist.",
        ["not_null"],
    ),
    ("batch_id", "string", "Immutable ingestion batch identifier.", ["not_null"]),
    (
        "source_identity",
        "string",
        "Governed contract source identity represented by this model.",
        ["not_null"],
    ),
    ("source_family", "string", "Governed source contract family.", ["not_null"]),
    ("source_dataset", "string", "Optional reference-data dataset name.", []),
    ("source_system", "string", "Synthetic source-system lineage value.", ["not_null"]),
    ("source_file", "string", "Immutable landed source filename.", ["not_null"]),
    (
        "source_checksum_sha256",
        "string",
        "SHA-256 of the immutable source file.",
        ["not_null"],
    ),
    ("source_row_number", "int64", "One-based row number in the source file.", ["not_null"]),
    ("contract_id", "string", "Governed source contract identifier.", ["not_null"]),
    ("contract_version", "string", "Governed source contract version.", ["not_null"]),
    ("ingested_at_utc", "timestamp", "UTC ingestion timestamp.", ["not_null"]),
    ("source_record_id", "string", "Canonical source record identifier.", ["not_null"]),
    ("natural_key", "string", "Canonical natural-key serialization.", ["not_null"]),
    (
        "evaluated_payload_sha256",
        "string",
        "SHA-256 of the payload evaluated by Phase 3.",
        ["not_null"],
    ),
    (
        "normalized_payload_sha256",
        "string",
        "Recomputed SHA-256 of the canonical normalized payload consumed by this model.",
        ["not_null"],
    ),
    (
        "validated_record_evidence_sha256",
        "string",
        "Recomputed Phase 3 record identity and payload-hash evidence checksum.",
        ["not_null"],
    ),
    ("correction_id", "string", "Optional immutable synthetic correction identifier.", []),
    (
        "disposition",
        "string",
        "Final publishable Phase 3 disposition.",
        [
            "not_null",
            {"accepted_values": {"arguments": {"values": ["accepted", "accepted_with_warning"]}}},
        ],
    ),
    ("validated_at_utc", "timestamp", "Governed Phase 3 evaluation-window start.", ["not_null"]),
    (
        "quality_report_sha256",
        "string",
        "Checksum of the immutable Phase 3 quality report.",
        ["not_null"],
    ),
    (
        "quality_configuration_sha256",
        "string",
        "Checksum binding policy, contracts, and quality implementation.",
        ["not_null"],
    ),
    (
        "validated_record_set_sha256",
        "string",
        "Quality-report checksum of the complete ordered validated record-evidence multiset.",
        ["not_null"],
    ),
    ("synthetic_only", "bool", "Mandatory synthetic-data boundary marker.", ["not_null"]),
)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _source_models() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(CONTRACTS.glob("*.yml")):
        contract = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
        family = str(contract["source_family"])
        datasets = contract.get("datasets")
        if datasets is None:
            result[family] = {
                "grain": contract["grain"],
                "contract_id": contract["contract_id"],
                "fields": contract["schema"],
            }
            continue
        if not isinstance(datasets, list):
            raise ValueError(f"{path} datasets must be an array")
        for dataset in datasets:
            definition = _mapping(dataset, f"{path}.datasets")
            identity = f"{family}.{definition['name']}"
            result[identity] = {
                "grain": definition["grain"],
                "contract_id": contract["contract_id"],
                "fields": definition["schema"],
            }
    if set(result) != set(MODEL_NAMES):
        raise ValueError(
            "dbt staging identity map differs from source contracts: "
            f"missing={sorted(set(result) - set(MODEL_NAMES))} "
            f"unknown={sorted(set(MODEL_NAMES) - set(result))}"
        )
    return result


def _dbt_type(source_type: str) -> str:
    if source_type.startswith("NUMERIC("):
        return "numeric"
    try:
        return TYPE_MAP[source_type]
    except KeyError as error:
        raise ValueError(f"unsupported dbt staging source type: {source_type}") from error


def _common_columns(identity: str) -> list[dict[str, object]]:
    columns: list[dict[str, object]] = []
    for name, data_type, description, tests in COMMON_COLUMNS:
        column: dict[str, object] = {
            "name": name,
            "data_type": data_type,
            "description": description,
        }
        column_tests = list(tests)
        if name == "source_identity":
            column_tests.append({"accepted_values": {"arguments": {"values": [identity]}}})
        if column_tests:
            column["data_tests"] = column_tests
        columns.append(column)
    return columns


def _business_columns(fields: object) -> list[dict[str, object]]:
    if not isinstance(fields, list):
        raise ValueError("source contract schema must be an array")
    columns: list[dict[str, object]] = []
    for raw_field in fields:
        field = _mapping(raw_field, "source contract field")
        column: dict[str, object] = {
            "name": field["name"],
            "data_type": _dbt_type(str(field["type"])),
            "description": field["description"],
            "config": {"meta": {"source_field": field["name"], "source_type": field["type"]}},
        }
        if field.get("nullable") is False:
            column["data_tests"] = ["not_null"]
        columns.append(column)
    return columns


def render() -> str:
    models: list[dict[str, object]] = []
    for identity, definition in sorted(
        _source_models().items(), key=lambda item: MODEL_NAMES[item[0]]
    ):
        grain = str(definition["grain"])
        models.append(
            {
                "name": MODEL_NAMES[identity],
                "description": (
                    f"Publication-scoped typed synthetic staging model at grain: {grain}. "
                    "Reads only allowlisted Phase 3 validated records."
                ),
                "config": {
                    "access": "protected",
                    "contract": {"enforced": True},
                    "meta": {
                        "source_identity": identity,
                        "contract_id": definition["contract_id"],
                        "grain": grain,
                        "owner": "ClaimsFlow Data Engineering",
                        "publication_scoped": True,
                    },
                },
                "columns": _common_columns(identity) + _business_columns(definition["fields"]),
            }
        )
    rendered = yaml.dump(
        {"version": 2, "models": models},
        Dumper=_NoAliasSafeDumper,
        sort_keys=False,
        allow_unicode=False,
        width=100,
    )
    return (
        "# Generated by scripts/render_dbt_staging_properties.py; do not edit manually.\n"
        + rendered
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("dbt staging properties are missing or differ from source contracts")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
