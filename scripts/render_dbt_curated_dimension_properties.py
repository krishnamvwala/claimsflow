#!/usr/bin/env python3
"""Render deterministic dbt contracts for Phase 4B.1 curated dimensions."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "analytics" / "dbt" / "models" / "curated" / "dimensions" / "_dimensions.yml"


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


Column = tuple[str, str, str]

EFFECTIVE_DIMENSIONS: dict[str, dict[str, object]] = {
    "dim_denial_reason": {
        "entity": "denial_reason",
        "grain": (
            "one denial-reason version per source system, denial reason code, and valid-from date"
        ),
        "source": "stg_reference_denial_reasons",
        "keys": [
            ("denial_reason_code", "string", "Source denial-reason code."),
        ],
        "attributes": [
            ("denial_category", "string", "Governed denial category."),
            ("denial_reason_description", "string", "Denial-reason description."),
            ("preventable_default_flag", "bool", "Default preventability classification."),
            (
                "required_document_codes",
                "array<string>",
                "Document codes commonly required to resolve the denial.",
            ),
            (
                "historical_resolution_rate",
                "numeric",
                "Governed historical resolution-rate reference value.",
            ),
        ],
    },
    "dim_diagnosis": {
        "entity": "diagnosis",
        "grain": (
            "one diagnosis version per source system, code system, diagnosis code, and "
            "valid-from date"
        ),
        "source": "stg_reference_diagnoses",
        "keys": [
            ("code_system", "string", "Diagnosis coding system."),
            ("diagnosis_code", "string", "Diagnosis code within its coding system."),
        ],
        "attributes": [
            ("diagnosis_description", "string", "Diagnosis description."),
        ],
    },
    "dim_facility": {
        "entity": "facility",
        "grain": "one facility version per source system, facility ID, and valid-from date",
        "source": "stg_reference_facilities",
        "keys": [("facility_id", "string", "Source facility identifier.")],
        "attributes": [
            ("facility_name", "string", "Synthetic facility display name."),
            ("clinic_number", "int64", "Synthetic clinic number."),
            ("region", "string", "Synthetic facility region."),
        ],
    },
    "dim_payer": {
        "entity": "payer",
        "grain": "one payer version per source system, payer ID, and valid-from date",
        "source": "stg_reference_payers",
        "keys": [("payer_id", "string", "Source payer identifier.")],
        "attributes": [
            ("payer_name", "string", "Synthetic payer display name."),
            ("payer_type", "string", "Payer classification."),
            ("timely_filing_days", "int64", "Timely-filing window in days."),
            ("appeal_window_days", "int64", "Appeal filing window in days."),
            ("expected_response_days", "int64", "Expected payer response window in days."),
            (
                "historical_resolution_rate",
                "numeric",
                "Governed historical resolution-rate reference value.",
            ),
        ],
    },
    "dim_plan": {
        "entity": "plan",
        "grain": "one plan version per source system, plan ID, and valid-from date",
        "source": "stg_reference_plans",
        "keys": [("plan_id", "string", "Source plan identifier.")],
        "attributes": [
            ("payer_id", "string", "Source payer identifier owning the plan."),
            ("plan_name", "string", "Synthetic plan display name."),
            ("coverage_type", "string", "Plan coverage classification."),
        ],
        "parent": (
            "payer_dimension_id",
            "string",
            "Effective payer dimension version covering this plan version.",
        ),
    },
    "dim_procedure": {
        "entity": "procedure",
        "grain": (
            "one procedure version per source system, code system, procedure code, and "
            "valid-from date"
        ),
        "source": "stg_reference_procedures",
        "keys": [
            ("code_system", "string", "Procedure coding system."),
            ("procedure_code", "string", "Procedure code within its coding system."),
        ],
        "attributes": [
            ("procedure_description", "string", "Procedure description."),
        ],
    },
    "dim_provider": {
        "entity": "provider",
        "grain": "one provider version per source system, provider ID, and valid-from date",
        "source": "stg_reference_providers",
        "keys": [("provider_id", "string", "Source provider identifier.")],
        "attributes": [
            ("provider_name", "string", "Synthetic provider display name."),
            ("specialty_code", "string", "Provider specialty code."),
        ],
    },
}


def _column(
    name: str,
    data_type: str,
    description: str,
    tests: list[object] | None = None,
) -> dict[str, object]:
    column: dict[str, object] = {
        "name": name,
        "data_type": data_type,
        "description": description,
    }
    if tests:
        column["data_tests"] = tests
    return column


def _candidate_columns() -> list[dict[str, object]]:
    return [
        _column(
            "candidate_publication_id",
            "string",
            "Candidate publication namespace supplied to the governed dbt invocation.",
            ["not_null"],
        ),
        _column(
            "candidate_selection_fingerprint",
            "string",
            "Fingerprint of the immutable validation-ID selection backing this candidate.",
            ["not_null"],
        ),
    ]


def _effective_columns(spec: dict[str, object]) -> list[dict[str, object]]:
    entity = str(spec["entity"])
    columns = _candidate_columns()
    columns.extend(
        [
            _column(
                f"{entity}_dimension_id",
                "string",
                "Deterministic SHA-256 surrogate key for this effective-dated version.",
                ["not_null", "unique"],
            ),
            _column(
                f"{entity}_business_key",
                "string",
                "Deterministic SHA-256 key shared by all history versions of the entity.",
                ["not_null"],
            ),
        ]
    )
    parent = spec.get("parent")
    if parent is not None:
        parent_column = cast(Column, parent)
        columns.append(
            _column(
                str(parent_column[0]),
                str(parent_column[1]),
                str(parent_column[2]),
                [
                    "not_null",
                    {
                        "relationships": {
                            "arguments": {
                                "to": "ref('dim_payer')",
                                "field": "payer_dimension_id",
                            }
                        }
                    },
                ],
            )
        )
    columns.append(
        _column("source_system", "string", "Synthetic source-system namespace.", ["not_null"])
    )
    for name, data_type, description in cast(list[Column], spec["keys"]):
        columns.append(_column(name, data_type, description, ["not_null"]))
    for name, data_type, description in cast(list[Column], spec["attributes"]):
        columns.append(_column(name, data_type, description))
    columns.extend(
        [
            _column("valid_from", "date", "Inclusive version-effective start date.", ["not_null"]),
            _column(
                "valid_to",
                "date",
                "Exclusive version-effective end date; null is open-ended.",
            ),
            _column(
                "source_active_flag",
                "bool",
                "Active flag supplied by the validated reference record.",
                ["not_null"],
            ),
            _column(
                "is_current",
                "bool",
                "True exactly when the version has no valid-to date.",
                ["not_null"],
            ),
            _column(
                "source_validated_record_id",
                "string",
                "Stable validated-record key providing row-level lineage.",
                ["not_null", "unique"],
            ),
            _column(
                "source_validation_id",
                "string",
                "Immutable Phase 3 validation identifier.",
                ["not_null"],
            ),
            _column(
                "source_batch_id",
                "string",
                "Immutable ingestion batch identifier.",
                ["not_null"],
            ),
            _column(
                "quality_report_sha256",
                "string",
                "Checksum of the approving Phase 3 quality report.",
                ["not_null"],
            ),
            _column(
                "quality_configuration_sha256",
                "string",
                "Checksum binding policy, contracts, and quality implementation.",
                ["not_null"],
            ),
            _column(
                "validated_record_set_sha256",
                "string",
                "Checksum of the complete approved validated-record set.",
                ["not_null"],
            ),
            _column(
                "synthetic_only",
                "bool",
                "Mandatory synthetic-data boundary marker.",
                ["not_null", {"accepted_values": {"arguments": {"values": [True]}}}],
            ),
        ]
    )
    return columns


def _model_config(
    *, grain: str, purpose: str, source_models: list[str], history_strategy: str
) -> dict[str, object]:
    return {
        "access": "protected",
        "contract": {"enforced": True},
        "meta": {
            "owner": "ClaimsFlow Analytics Engineering",
            "grain": grain,
            "purpose": purpose,
            "materialization": "table",
            "publication_scoped": True,
            "history_strategy": history_strategy,
            "source_models": source_models,
        },
    }


def _effective_models() -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for name, spec in sorted(EFFECTIVE_DIMENSIONS.items()):
        source = str(spec["source"])
        source_models = [source]
        if name == "dim_plan":
            source_models.append("dim_payer")
        models.append(
            {
                "name": name,
                "description": (
                    f"Publication-isolated synthetic {spec['entity']} history dimension at grain: "
                    f"{spec['grain']}."
                ),
                "config": _model_config(
                    grain=str(spec["grain"]),
                    purpose=f"Conform validated {spec['entity']} reference history for facts.",
                    source_models=source_models,
                    history_strategy="effective_dated_type_2",
                ),
                "columns": _effective_columns(spec),
            }
        )
    return models


def _patient_model() -> dict[str, object]:
    return {
        "name": "dim_patient",
        "description": (
            "Publication-isolated privacy-minimized synthetic patient dimension derived from "
            "validated eligibility at one row per source system and patient ID."
        ),
        "config": _model_config(
            grain="one patient per eligibility source system and patient ID",
            purpose="Provide a non-PII conformed patient key and eligibility coverage summary.",
            source_models=["stg_eligibility"],
            history_strategy="current_eligibility_rollup",
        ),
        "columns": [
            *_candidate_columns(),
            _column(
                "patient_dimension_id",
                "string",
                "Deterministic SHA-256 surrogate key for the synthetic patient.",
                ["not_null", "unique"],
            ),
            _column(
                "patient_business_key",
                "string",
                "Deterministic SHA-256 business key for the synthetic patient.",
                ["not_null", "unique"],
            ),
            _column(
                "source_system",
                "string",
                "Eligibility source-system namespace.",
                ["not_null"],
            ),
            _column("patient_id", "string", "Synthetic source patient identifier.", ["not_null"]),
            _column(
                "first_verified_at",
                "timestamp",
                "Earliest eligibility verification timestamp.",
            ),
            _column("last_verified_at", "timestamp", "Latest eligibility verification timestamp."),
            _column(
                "first_coverage_start_date",
                "date",
                "Earliest observed eligibility coverage start date.",
            ),
            _column(
                "last_coverage_end_date",
                "date",
                "Latest finite observed eligibility coverage end date.",
            ),
            _column(
                "eligibility_record_count",
                "int64",
                "Count of validated eligibility records contributing to this patient.",
                ["not_null"],
            ),
            _column(
                "source_validation_ids",
                "array<string>",
                "Sorted distinct Phase 3 validation identifiers contributing to the row.",
                ["not_null"],
            ),
            _column(
                "source_batch_ids",
                "array<string>",
                "Sorted distinct ingestion batch identifiers contributing to the row.",
                ["not_null"],
            ),
            _column(
                "validated_record_set_sha256s",
                "array<string>",
                "Sorted distinct validated-record-set checksums contributing to the row.",
                ["not_null"],
            ),
            _column(
                "synthetic_only",
                "bool",
                "Mandatory synthetic-data boundary marker.",
                ["not_null", {"accepted_values": {"arguments": {"values": [True]}}}],
            ),
        ],
    }


def _date_model() -> dict[str, object]:
    calendar_columns: list[Column] = [
        ("calendar_date", "date", "Calendar date."),
        ("calendar_year", "int64", "Gregorian calendar year."),
        ("calendar_quarter", "int64", "Gregorian calendar quarter number."),
        ("calendar_month", "int64", "Gregorian calendar month number."),
        ("month_name", "string", "English calendar month name."),
        ("iso_year", "int64", "ISO week-numbering year."),
        ("iso_week", "int64", "ISO week number."),
        ("day_of_month", "int64", "Day number within the month."),
        ("day_of_week", "int64", "BigQuery day-of-week number, Sunday equals one."),
        ("day_name", "string", "English weekday name."),
        ("week_start_date", "date", "Monday starting the containing week."),
        ("month_start_date", "date", "First date of the containing month."),
        ("quarter_start_date", "date", "First date of the containing quarter."),
        ("year_start_date", "date", "First date of the containing year."),
        ("is_weekend", "bool", "True for Saturday or Sunday."),
    ]
    return {
        "name": "dim_date",
        "description": (
            "Publication-isolated continuous calendar spine spanning every non-null date in "
            "the validated candidate."
        ),
        "config": _model_config(
            grain="one row per calendar date in the candidate source-date range",
            purpose="Provide conformed calendar attributes for all curated facts.",
            source_models=["all fourteen typed staging models"],
            history_strategy="candidate_date_spine",
        ),
        "columns": _candidate_columns()
        + [
            _column(
                "date_dimension_id",
                "int64",
                "Deterministic YYYYMMDD calendar surrogate key.",
                ["not_null", "unique"],
            )
        ]
        + [
            _column(name, data_type, description, ["not_null"])
            for name, data_type, description in calendar_columns
        ]
        + [
            _column(
                "synthetic_only",
                "bool",
                "Mandatory synthetic-data boundary marker.",
                ["not_null", {"accepted_values": {"arguments": {"values": [True]}}}],
            )
        ],
    }


def render() -> str:
    models = [*_effective_models(), _patient_model(), _date_model()]
    rendered = yaml.dump(
        {"version": 2, "models": sorted(models, key=lambda model: str(model["name"]))},
        Dumper=_NoAliasSafeDumper,
        sort_keys=False,
        allow_unicode=False,
        width=100,
    )
    return (
        "# Generated by scripts/render_dbt_curated_dimension_properties.py; "
        "do not edit manually.\n" + rendered
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(
                "dbt curated dimension properties are missing or differ from the governed spec"
            )
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
