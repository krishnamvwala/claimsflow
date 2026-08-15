"""Source contract catalog used by the Phase 2 generator."""

from __future__ import annotations

from dataclasses import dataclass

from claimsflow.generator.models import GenerationConfig


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """The contract envelope and exact CSV header for one generated file."""

    source_family: str
    source_system: str
    contract_id: str
    contract_version: str
    file_pattern: str
    columns: tuple[str, ...]
    dataset: str | None = None


CLAIMS = SourceDefinition(
    source_family="claims",
    source_system="synthetic_ehr",
    contract_id="SRC-CLM-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_claims_{extract_at_utc}_{sequence}.csv",
    columns=(
        "claim_id",
        "submission_sequence",
        "original_claim_source_system",
        "original_claim_id",
        "original_submission_sequence",
        "patient_id",
        "eligibility_source_system",
        "eligibility_id",
        "provider_id",
        "facility_id",
        "payer_id",
        "plan_id",
        "claim_type",
        "claim_status",
        "submission_type",
        "service_from_date",
        "service_to_date",
        "submitted_at",
        "first_response_at",
        "first_response_disposition",
        "adjudicated_at",
        "primary_diagnosis_code",
        "primary_diagnosis_code_system",
        "billed_amount",
        "allowed_amount",
        "payer_paid_amount",
        "patient_paid_amount",
        "patient_responsibility_amount",
        "adjustment_amount",
        "outstanding_balance",
        "currency_code",
        "clean_claim_flag",
        "first_pass_accepted_flag",
        "filing_deadline_date",
        "source_updated_at",
    ),
)

CLAIM_LINES = SourceDefinition(
    source_family="claim-lines",
    source_system="synthetic_ehr",
    contract_id="SRC-CLN-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_claim_lines_{extract_at_utc}_{sequence}.csv",
    columns=(
        "claim_id",
        "submission_sequence",
        "line_number",
        "claim_line_id",
        "service_from_date",
        "service_to_date",
        "procedure_code",
        "procedure_code_system",
        "procedure_modifiers",
        "diagnosis_codes",
        "diagnosis_code_system",
        "place_of_service_code",
        "revenue_code",
        "units",
        "line_status",
        "denial_reason_code",
        "billed_amount",
        "allowed_amount",
        "payer_paid_amount",
        "patient_paid_amount",
        "patient_responsibility_amount",
        "adjustment_amount",
        "outstanding_balance",
        "currency_code",
        "source_updated_at",
    ),
)

ELIGIBILITY = SourceDefinition(
    source_family="eligibility",
    source_system="synthetic_patient_access",
    contract_id="SRC-ELG-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_eligibility_{extract_date}_{sequence}.csv",
    columns=(
        "eligibility_id",
        "patient_id",
        "payer_id",
        "plan_id",
        "member_reference",
        "verification_at",
        "response_status",
        "coverage_status",
        "coverage_type",
        "coverage_start_date",
        "coverage_end_date",
        "primary_coverage_flag",
        "deductible_remaining",
        "out_of_pocket_remaining",
        "copay_amount",
        "currency_code",
        "source_updated_at",
    ),
)

REMITTANCES = SourceDefinition(
    source_family="remittances",
    source_system="synthetic_payer_gateway",
    contract_id="SRC-REM-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_remittances_{extract_date}_{sequence}.csv",
    columns=(
        "remittance_id",
        "reverses_remittance_source_system",
        "reverses_remittance_id",
        "payer_id",
        "source_control_number",
        "payment_trace_number",
        "payment_method",
        "direction",
        "remittance_date",
        "received_at",
        "total_payment_amount",
        "claim_transaction_count",
        "currency_code",
        "remittance_status",
        "source_updated_at",
    ),
)

PAYMENTS = SourceDefinition(
    source_family="payments",
    source_system="synthetic_billing",
    contract_id="SRC-PAY-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_payments_adjustments_{extract_at_utc}_{sequence}.csv",
    columns=(
        "payment_id",
        "remittance_source_system",
        "remittance_id",
        "claim_source_system",
        "claim_id",
        "claim_submission_sequence",
        "claim_line_number",
        "claim_line_id",
        "payer_id",
        "transaction_type",
        "direction",
        "amount",
        "currency_code",
        "payment_date",
        "posted_at",
        "adjustment_reason_code",
        "reverses_payment_source_system",
        "reverses_payment_id",
        "posting_status",
        "source_updated_at",
    ),
)

DENIALS = SourceDefinition(
    source_family="denials",
    source_system="synthetic_payer_gateway",
    contract_id="SRC-DEN-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_denials_{extract_at_utc}_{sequence}.csv",
    columns=(
        "denial_id",
        "claim_source_system",
        "claim_id",
        "claim_submission_sequence",
        "claim_line_number",
        "claim_line_id",
        "payer_id",
        "denial_reason_code",
        "denial_category",
        "denial_date",
        "received_at",
        "denied_amount",
        "currency_code",
        "filing_deadline_date",
        "appeal_deadline_date",
        "denial_status",
        "preventable_flag",
        "documentation_ready_flag",
        "missing_document_codes",
        "source_updated_at",
    ),
)

APPEALS = SourceDefinition(
    source_family="appeals",
    source_system="synthetic_denial_management",
    contract_id="SRC-APL-001",
    contract_version="1.0.0",
    file_pattern="{source_system}_appeals_{extract_at_utc}_{sequence}.csv",
    columns=(
        "appeal_id",
        "denial_source_system",
        "denial_id",
        "claim_source_system",
        "claim_id",
        "claim_submission_sequence",
        "appeal_level",
        "appeal_status",
        "created_at",
        "filed_at",
        "appeal_deadline_date",
        "decision_date",
        "outcome",
        "requested_amount",
        "recovered_amount",
        "currency_code",
        "documentation_ready_flag",
        "owner_queue",
        "source_updated_at",
    ),
)

REFERENCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "payers": (
        "payer_id",
        "payer_name",
        "payer_type",
        "timely_filing_days",
        "appeal_window_days",
        "expected_response_days",
        "historical_resolution_rate",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
    "plans": (
        "plan_id",
        "payer_id",
        "plan_name",
        "coverage_type",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
    "providers": (
        "provider_id",
        "provider_name",
        "specialty_code",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
    "facilities": (
        "facility_id",
        "facility_name",
        "clinic_number",
        "region",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
    "diagnoses": (
        "diagnosis_code",
        "code_system",
        "diagnosis_description",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
    "procedures": (
        "procedure_code",
        "code_system",
        "procedure_description",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
    "denial-reasons": (
        "denial_reason_code",
        "denial_category",
        "denial_reason_description",
        "preventable_default_flag",
        "required_document_codes",
        "historical_resolution_rate",
        "valid_from",
        "valid_to",
        "active_flag",
    ),
}


def reference_definition(dataset: str) -> SourceDefinition:
    return SourceDefinition(
        source_family="reference-data",
        source_system="synthetic_reference",
        contract_id="SRC-REF-001",
        contract_version="1.0.0",
        file_pattern="{source_system}_{dataset_name}_{effective_date}_{sequence}.csv",
        columns=REFERENCE_COLUMNS[dataset],
        dataset=dataset,
    )


def source_definitions() -> tuple[SourceDefinition, ...]:
    """Return the exact 14-file delivery inventory in dependency order."""

    references = tuple(reference_definition(dataset) for dataset in REFERENCE_COLUMNS)
    return (
        *references,
        ELIGIBILITY,
        CLAIMS,
        CLAIM_LINES,
        REMITTANCES,
        PAYMENTS,
        DENIALS,
        APPEALS,
    )


def render_file_name(definition: SourceDefinition, config: GenerationConfig) -> str:
    """Render the governed delivery pattern with stable logical extract values."""

    extract_date = config.generated_at.strftime("%Y%m%d")
    extract_timestamp = config.generated_at.strftime("%Y%m%dT%H%M%SZ")
    return definition.file_pattern.format(
        source_system=definition.source_system,
        dataset_name=(definition.dataset or "").replace("-", "_"),
        effective_date=extract_date,
        extract_date=extract_date,
        extract_at_utc=extract_timestamp,
        sequence="001",
    )
