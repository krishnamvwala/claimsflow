#!/usr/bin/env python3
"""Render deterministic dbt contracts for Phase 4B.2 curated facts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
DBT = ROOT / "analytics" / "dbt"
OUTPUT = DBT / "models" / "curated" / "facts" / "_facts.yml"
STAGING_PROPERTIES = DBT / "models" / "staging" / "_staging.yml"
CONTRACTS = ROOT / "contracts" / "source-data"


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


def _relationship(model: str, field: str) -> dict[str, object]:
    return {
        "relationships": {
            "arguments": {"to": f"ref('{model}')", "field": field},
        }
    }


def _accepted(values: list[object]) -> dict[str, object]:
    return {"accepted_values": {"arguments": {"values": values}}}


DerivedColumn = tuple[str, str, str, list[object]]

FACT_SPECS: dict[str, dict[str, object]] = {
    "fact_claim": {
        "source": "stg_claims",
        "contract": "claims.yml",
        "grain": "one claim submission version per source system",
        "purpose": "Conform claim submissions and their financial state to governed dimensions.",
        "partition_by": "service_from_date month",
        "cluster_by": ["payer_dimension_id", "facility_dimension_id", "claim_status"],
        "financial_fields": [
            "billed_amount",
            "allowed_amount",
            "payer_paid_amount",
            "patient_paid_amount",
            "patient_responsibility_amount",
            "adjustment_amount",
            "outstanding_balance",
        ],
        "derived": [
            (
                "claim_fact_id",
                "string",
                "Deterministic claim-submission fact key.",
                ["not_null", "unique"],
            ),
            (
                "original_claim_fact_id",
                "string",
                "Prior claim-submission fact key for a replacement or void.",
                [_relationship("fact_claim", "claim_fact_id")],
            ),
            (
                "patient_dimension_id",
                "string",
                "Conformed synthetic patient key.",
                ["not_null", _relationship("dim_patient", "patient_dimension_id")],
            ),
            (
                "provider_dimension_id",
                "string",
                "Provider version effective on the first service date.",
                ["not_null", _relationship("dim_provider", "provider_dimension_id")],
            ),
            (
                "facility_dimension_id",
                "string",
                "Facility version effective on the first service date.",
                ["not_null", _relationship("dim_facility", "facility_dimension_id")],
            ),
            (
                "payer_dimension_id",
                "string",
                "Payer version effective on the first service date.",
                ["not_null", _relationship("dim_payer", "payer_dimension_id")],
            ),
            (
                "plan_dimension_id",
                "string",
                "Plan version effective on the first service date.",
                ["not_null", _relationship("dim_plan", "plan_dimension_id")],
            ),
            (
                "primary_diagnosis_dimension_id",
                "string",
                "Primary diagnosis version effective on the first service date.",
                ["not_null", _relationship("dim_diagnosis", "diagnosis_dimension_id")],
            ),
            (
                "service_from_date_dimension_id",
                "int64",
                "First-service calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "service_to_date_dimension_id",
                "int64",
                "Last-service calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "submitted_date_dimension_id",
                "int64",
                "Submission calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "first_response_date_dimension_id",
                "int64",
                "Optional first-response calendar key.",
                [_relationship("dim_date", "date_dimension_id")],
            ),
            (
                "adjudicated_date_dimension_id",
                "int64",
                "Optional adjudication calendar key.",
                [_relationship("dim_date", "date_dimension_id")],
            ),
            (
                "filing_deadline_date_dimension_id",
                "int64",
                "Optional filing-deadline calendar key.",
                [_relationship("dim_date", "date_dimension_id")],
            ),
        ],
    },
    "fact_claim_line": {
        "source": "stg_claim_lines",
        "contract": "claim-lines.yml",
        "grain": "one service line on one claim submission version",
        "purpose": "Conform claim-line clinical coding and financial state to governed dimensions.",
        "partition_by": "service_from_date month",
        "cluster_by": ["claim_fact_id", "procedure_dimension_id", "line_status"],
        "financial_fields": [
            "billed_amount",
            "allowed_amount",
            "payer_paid_amount",
            "patient_paid_amount",
            "patient_responsibility_amount",
            "adjustment_amount",
            "outstanding_balance",
        ],
        "derived": [
            (
                "claim_line_fact_id",
                "string",
                "Deterministic claim-line fact key.",
                ["not_null", "unique"],
            ),
            (
                "claim_fact_id",
                "string",
                "Parent claim-submission fact key.",
                ["not_null", _relationship("fact_claim", "claim_fact_id")],
            ),
            (
                "procedure_dimension_id",
                "string",
                "Procedure version effective on the first line-service date.",
                ["not_null", _relationship("dim_procedure", "procedure_dimension_id")],
            ),
            (
                "diagnosis_dimension_ids",
                "array<string>",
                "Ordered conformed diagnosis keys matching the source diagnosis-code list.",
                ["not_null"],
            ),
            (
                "denial_reason_dimension_id",
                "string",
                "Optional denial-reason version effective on the first line-service date.",
                [_relationship("dim_denial_reason", "denial_reason_dimension_id")],
            ),
            (
                "service_from_date_dimension_id",
                "int64",
                "First line-service calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "service_to_date_dimension_id",
                "int64",
                "Last line-service calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
        ],
    },
    "fact_payment": {
        "source": "stg_payments",
        "source_models": ["stg_payments", "stg_remittances"],
        "contract": "payments.yml",
        "grain": "one posted payment, adjustment, refund, or write-off transaction",
        "purpose": (
            "Conform signed financial transactions to their claim, line, payer, and "
            "calendar context."
        ),
        "partition_by": "payment_date month",
        "cluster_by": ["claim_fact_id", "payer_dimension_id", "transaction_type"],
        "financial_fields": ["amount", "signed_amount"],
        "derived": [
            (
                "payment_fact_id",
                "string",
                "Deterministic financial-transaction fact key.",
                ["not_null", "unique"],
            ),
            (
                "claim_fact_id",
                "string",
                "Required parent claim-submission fact key.",
                ["not_null", _relationship("fact_claim", "claim_fact_id")],
            ),
            (
                "claim_line_fact_id",
                "string",
                "Optional allocated claim-line fact key.",
                [_relationship("fact_claim_line", "claim_line_fact_id")],
            ),
            (
                "reverses_payment_fact_id",
                "string",
                "Optional original transaction reversed by this event.",
                [_relationship("fact_payment", "payment_fact_id")],
            ),
            (
                "payer_dimension_id",
                "string",
                "Optional payer version effective on the transaction date.",
                [_relationship("dim_payer", "payer_dimension_id")],
            ),
            (
                "remittance_source_validated_record_id",
                "string",
                "Optional resolved parent-remittance staging record.",
                [_relationship("stg_remittances", "validated_record_id")],
            ),
            (
                "payment_date_dimension_id",
                "int64",
                "Business-effective payment calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "posted_date_dimension_id",
                "int64",
                "Ledger-posting calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "signed_amount",
                "numeric",
                "Governed signed amount: credits positive and debits negative.",
                ["not_null"],
            ),
        ],
    },
    "fact_denial": {
        "source": "stg_denials",
        "contract": "denials.yml",
        "grain": "one denial event for a claim or claim line",
        "purpose": "Conform denial exposure, reason, deadlines, and readiness evidence.",
        "partition_by": "denial_date month",
        "cluster_by": ["payer_dimension_id", "denial_reason_dimension_id", "denial_status"],
        "financial_fields": ["denied_amount"],
        "derived": [
            (
                "denial_fact_id",
                "string",
                "Deterministic denial-event fact key.",
                ["not_null", "unique"],
            ),
            (
                "claim_fact_id",
                "string",
                "Required denied claim-submission fact key.",
                ["not_null", _relationship("fact_claim", "claim_fact_id")],
            ),
            (
                "claim_line_fact_id",
                "string",
                "Optional denied claim-line fact key.",
                [_relationship("fact_claim_line", "claim_line_fact_id")],
            ),
            (
                "payer_dimension_id",
                "string",
                "Payer version effective on the denial date.",
                ["not_null", _relationship("dim_payer", "payer_dimension_id")],
            ),
            (
                "denial_reason_dimension_id",
                "string",
                "Denial-reason version effective on the denial date.",
                ["not_null", _relationship("dim_denial_reason", "denial_reason_dimension_id")],
            ),
            (
                "denial_date_dimension_id",
                "int64",
                "Denial-effective calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "received_date_dimension_id",
                "int64",
                "Denial-receipt calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "filing_deadline_date_dimension_id",
                "int64",
                "Corrected-claim filing-deadline calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "appeal_deadline_date_dimension_id",
                "int64",
                "Appeal-deadline calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
        ],
    },
    "fact_appeal": {
        "source": "stg_appeals",
        "contract": "appeals.yml",
        "grain": "one appeal level or event for one denial",
        "purpose": "Conform human-reviewed appeal workflow, outcome, and recovery evidence.",
        "partition_by": "created_at month",
        "cluster_by": ["denial_fact_id", "claim_fact_id", "appeal_status"],
        "financial_fields": ["requested_amount", "recovered_amount"],
        "derived": [
            (
                "appeal_fact_id",
                "string",
                "Deterministic appeal-event fact key.",
                ["not_null", "unique"],
            ),
            (
                "denial_fact_id",
                "string",
                "Required parent denial-event fact key.",
                ["not_null", _relationship("fact_denial", "denial_fact_id")],
            ),
            (
                "claim_fact_id",
                "string",
                "Required parent claim-submission fact key.",
                ["not_null", _relationship("fact_claim", "claim_fact_id")],
            ),
            (
                "created_date_dimension_id",
                "int64",
                "Appeal creation calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "filed_date_dimension_id",
                "int64",
                "Optional human filing calendar key.",
                [_relationship("dim_date", "date_dimension_id")],
            ),
            (
                "appeal_deadline_date_dimension_id",
                "int64",
                "Appeal-deadline calendar key.",
                ["not_null", _relationship("dim_date", "date_dimension_id")],
            ),
            (
                "decision_date_dimension_id",
                "int64",
                "Optional payer-decision calendar key.",
                [_relationship("dim_date", "date_dimension_id")],
            ),
        ],
    },
}

LINEAGE_RENAMES = {
    "validated_record_id": "source_validated_record_id",
    "validation_id": "source_validation_id",
    "batch_id": "source_batch_id",
    "disposition": "source_disposition",
}
LINEAGE_FIELDS = [
    "validated_record_id",
    "validation_id",
    "batch_id",
    "disposition",
    "quality_report_sha256",
    "quality_configuration_sha256",
    "validated_record_set_sha256",
    "synthetic_only",
]


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _staging_columns() -> dict[str, dict[str, dict[str, object]]]:
    root = _mapping(yaml.safe_load(STAGING_PROPERTIES.read_text(encoding="utf-8")), "staging")
    result: dict[str, dict[str, dict[str, object]]] = {}
    for raw_model in cast(list[object], root["models"]):
        model = _mapping(raw_model, "staging model")
        result[str(model["name"])] = {
            str(column["name"]): cast(dict[str, object], column)
            for column in cast(list[dict[str, object]], model["columns"])
        }
    return result


def _contract_fields(path: str) -> list[dict[str, Any]]:
    contract = _mapping(
        yaml.safe_load((CONTRACTS / path).read_text(encoding="utf-8")),
        path,
    )
    return [_mapping(field, f"{path}.schema") for field in cast(list[object], contract["schema"])]


def _copy_column(column: dict[str, object], name: str | None = None) -> dict[str, object]:
    result = {
        "name": name or column["name"],
        "data_type": column["data_type"],
        "description": column["description"],
    }
    tests = column.get("data_tests")
    if isinstance(tests, list) and tests:
        result["data_tests"] = list(tests)
    return result


def _candidate_columns() -> list[dict[str, object]]:
    return [
        {
            "name": "candidate_publication_id",
            "data_type": "string",
            "description": (
                "Candidate publication namespace supplied to the governed dbt invocation."
            ),
            "data_tests": ["not_null"],
        },
        {
            "name": "candidate_selection_fingerprint",
            "data_type": "string",
            "description": (
                "Fingerprint of the immutable validation-ID selection backing this candidate."
            ),
            "data_tests": ["not_null"],
        },
    ]


def _derived_columns(spec: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, data_type, description, tests in cast(list[DerivedColumn], spec["derived"]):
        column: dict[str, object] = {
            "name": name,
            "data_type": data_type,
            "description": description,
        }
        if tests:
            column["data_tests"] = tests
        result.append(column)
    return result


def _source_columns(
    spec: dict[str, object], staging: dict[str, dict[str, dict[str, object]]]
) -> list[dict[str, object]]:
    model_name = str(spec["source"])
    available = staging[model_name]
    fields = _contract_fields(str(spec["contract"]))
    result = [_copy_column(available["source_system"])]
    for field in fields:
        name = str(field["name"])
        column = _copy_column(available[name])
        allowed_values = field.get("allowed_values")
        if isinstance(allowed_values, list):
            tests = cast(list[object], column.setdefault("data_tests", []))
            tests.append(_accepted(cast(list[object], allowed_values)))
        result.append(column)
    return result


def _lineage_columns(
    spec: dict[str, object], staging: dict[str, dict[str, dict[str, object]]]
) -> list[dict[str, object]]:
    available = staging[str(spec["source"])]
    result: list[dict[str, object]] = []
    for source_name in LINEAGE_FIELDS:
        output_name = LINEAGE_RENAMES.get(source_name, source_name)
        column = _copy_column(available[source_name], output_name)
        if source_name == "validated_record_id":
            column["data_tests"] = ["not_null", "unique"]
        result.append(column)
    return result


def render() -> str:
    staging = _staging_columns()
    models: list[dict[str, object]] = []
    for name, raw_spec in sorted(FACT_SPECS.items()):
        spec = cast(dict[str, object], raw_spec)
        columns = (
            _candidate_columns()
            + _derived_columns(spec)
            + _source_columns(spec, staging)
            + _lineage_columns(spec, staging)
        )
        column_names = [str(column["name"]) for column in columns]
        if len(column_names) != len(set(column_names)):
            raise ValueError(f"duplicate {name} contract column")
        models.append(
            {
                "name": name,
                "description": (
                    f"Publication-isolated synthetic curated fact at grain: {spec['grain']}."
                ),
                "config": {
                    "access": "protected",
                    "contract": {"enforced": True},
                    "meta": {
                        "owner": "ClaimsFlow Analytics Engineering",
                        "grain": spec["grain"],
                        "purpose": spec["purpose"],
                        "materialization": "table",
                        "publication_scoped": True,
                        "source_models": spec.get("source_models", [spec["source"]]),
                        "partition_by": spec["partition_by"],
                        "cluster_by": spec["cluster_by"],
                        "financial_fields": spec["financial_fields"],
                    },
                },
                "columns": columns,
            }
        )
    document = {"version": 2, "models": models}
    rendered = yaml.dump(
        document,
        Dumper=_NoAliasSafeDumper,
        sort_keys=False,
        allow_unicode=False,
        width=100,
    )
    return (
        "# Generated by scripts/render_dbt_curated_fact_properties.py; do not edit manually.\n"
        + rendered
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"generated dbt fact properties are stale: {OUTPUT}")
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
