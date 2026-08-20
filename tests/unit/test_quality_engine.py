from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from claimsflow.domain.ingestion import ValidationIssue
from claimsflow.quality.catalog import QualityCatalog
from claimsflow.quality.engine import QualityEvaluation, QualityRecord, evaluate_quality

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/source-data"
POLICY = ROOT / "config/data-quality-policy.yml"


def _record(
    source_identity: str,
    payload: dict[str, str],
    *,
    source_system: str = "synthetic_test",
    disposition: str = "accepted",
    issues: tuple[ValidationIssue, ...] = (),
) -> QualityRecord:
    return QualityRecord(
        source_identity=source_identity,
        source_system=source_system,
        source_record_id=f'["{source_identity}-record"]',
        natural_key=f'["{source_identity}-key"]',
        payload_sha256="a" * 64,
        original_payload=payload,
        normalized_payload=payload,
        preliminary_disposition=disposition,  # type: ignore[arg-type]
        preliminary_issues=issues,
        lineage={"source_row_number": 1},
    )


def _evaluate(*records: QualityRecord, hours_after_generation: int = 1) -> QualityEvaluation:
    catalog = QualityCatalog.load(CONTRACTS, POLICY)
    generated = datetime(2026, 8, 16, tzinfo=UTC)
    return evaluate_quality(
        records,
        catalog,
        present_identities=set(catalog.identities()),
        evaluation_time=generated + timedelta(hours=hours_after_generation),
        batch_generated_at=generated,
    )


def test_orphan_claim_line_is_quarantined_with_stable_relationship_rule() -> None:
    line = _record(
        "claim-lines",
        {
            "claim_id": "SYN-CLM-MISSING",
            "submission_sequence": "1",
            "procedure_code": "SYN-PROC-MISSING",
            "procedure_code_system": "SYNTHETIC",
            "diagnosis_codes": "SYN-DX-MISSING",
            "diagnosis_code_system": "SYNTHETIC",
            "denial_reason_code": "",
            "service_from_date": "2026-07-10",
            "service_to_date": "2026-07-10",
            "source_updated_at": "2026-08-16T00:00:00Z",
        },
        source_system="synthetic_ehr",
    )

    evaluation = _evaluate(line)

    outcome = evaluation.records[0]
    assert outcome.disposition == "quarantined"
    assert "DQ-CLN-003" in {issue.rule_id for issue in outcome.issues}
    assert evaluation.reconciled is True


def test_effective_reference_must_resolve_at_source_event_date() -> None:
    eligibility = _record(
        "eligibility",
        {
            "eligibility_id": "SYN-ELG-1",
            "payer_id": "SYN-PAYER-MISSING",
            "plan_id": "SYN-PLAN-MISSING",
            "verification_at": "2026-07-10T12:00:00Z",
            "coverage_status": "active",
            "coverage_start_date": "2026-01-01",
            "coverage_end_date": "2027-01-01",
        },
        source_system="synthetic_patient_access",
    )

    evaluation = _evaluate(eligibility)

    outcome = evaluation.records[0]
    assert outcome.disposition == "quarantined"
    assert "DQ-ELG-003" in {issue.rule_id for issue in outcome.issues}


def test_withdrawn_appeal_requires_filing_evidence() -> None:
    appeal = _record(
        "appeals",
        {
            "appeal_status": "withdrawn",
            "created_at": "2026-08-10T12:00:00Z",
            "filed_at": "",
            "appeal_deadline_date": "2026-08-30",
            "decision_date": "2026-08-15",
            "outcome": "withdrawn",
            "documentation_ready_flag": "true",
            "source_updated_at": "2026-08-15T12:00:00Z",
        },
        source_system="synthetic_practice_management",
    )

    evaluation = _evaluate(appeal)

    assert "DQ-APL-005" in {issue.rule_id for issue in evaluation.records[0].issues}


def test_non_decided_appeal_rejects_either_decision_field() -> None:
    appeal = _record(
        "appeals",
        {
            "appeal_status": "draft",
            "created_at": "2026-08-10T12:00:00Z",
            "filed_at": "",
            "appeal_deadline_date": "2026-08-30",
            "decision_date": "2026-08-15",
            "outcome": "",
            "documentation_ready_flag": "false",
            "source_updated_at": "2026-08-15T12:00:00Z",
        },
        source_system="synthetic_practice_management",
    )

    evaluation = _evaluate(appeal)

    assert "DQ-APL-006" in {issue.rule_id for issue in evaluation.records[0].issues}


def test_denial_reason_rate_uses_shared_reference_range_rule() -> None:
    denial_reason = _record(
        "reference-data.denial-reasons",
        {
            "denial_reason_code": "SYN-DEN-01",
            "historical_resolution_rate": "1.5000",
            "valid_from": "2025-01-01",
            "valid_to": "",
            "active_flag": "true",
        },
        source_system="synthetic_reference",
    )

    evaluation = _evaluate(denial_reason)

    outcome = evaluation.records[0]
    assert outcome.disposition == "quarantined"
    assert "DQ-REF-007" in {issue.rule_id for issue in outcome.issues}


def test_critical_row_outcome_blocks_dependent_publication() -> None:
    rejected_issue = ValidationIssue(
        rule_id="DQ-CLM-001",
        severity="critical",
        disposition="rejected",
        reason="claim identity is missing",
        field="claim_id",
    )
    claim = _record(
        "claims",
        {"claim_id": "", "source_updated_at": "2026-08-16T00:00:00Z"},
        disposition="rejected",
        issues=(rejected_issue,),
    )

    evaluation = _evaluate(claim)

    assert evaluation.records[0].disposition == "rejected"
    assert "DQ-CMN-016" in {issue.rule_id for issue in evaluation.batch_findings}


def test_freshness_breach_is_a_nonblocking_source_warning() -> None:
    payer = _record(
        "reference-data.payers",
        {
            "payer_id": "SYN-PAYER-01",
            "valid_from": "2025-01-01",
            "valid_to": "",
        },
        source_system="synthetic_reference",
    )

    evaluation = _evaluate(payer, hours_after_generation=31)

    freshness = [issue for issue in evaluation.source_findings if issue.rule_id == "DQ-CMN-015"]
    assert freshness
    assert all(
        issue.severity == "warning" and issue.disposition == "accepted_with_warning"
        for issue in freshness
    )
    assert "DQ-CMN-015" not in {issue.rule_id for issue in evaluation.batch_findings}


def test_missing_governed_source_blocks_publication() -> None:
    catalog = QualityCatalog.load(CONTRACTS, POLICY)
    generated = datetime(2026, 8, 16, tzinfo=UTC)

    evaluation = evaluate_quality(
        (),
        catalog,
        present_identities=set(catalog.identities()) - {"appeals"},
        evaluation_time=generated + timedelta(hours=1),
        batch_generated_at=generated,
    )

    missing = [issue for issue in evaluation.batch_findings if issue.rule_id == "DQ-REF-008"]
    assert len(missing) == 1
    assert missing[0].source_identity == "appeals"
    assert missing[0].severity == "critical"


def test_remittance_payment_control_mismatch_blocks_publication() -> None:
    payer = _record(
        "reference-data.payers",
        {
            "payer_id": "SYN-PAYER-01",
            "valid_from": "2025-01-01",
            "valid_to": "",
        },
        source_system="synthetic_reference",
    )
    remittance = _record(
        "remittances",
        {
            "remittance_id": "SYN-REM-01",
            "reverses_remittance_source_system": "",
            "reverses_remittance_id": "",
            "payer_id": "SYN-PAYER-01",
            "direction": "credit",
            "remittance_date": "2026-08-15",
            "received_at": "2026-08-15T12:00:00Z",
            "total_payment_amount": "125.00",
            "claim_transaction_count": "1",
            "currency_code": "USD",
            "remittance_status": "received",
            "source_updated_at": "2026-08-15T12:00:00Z",
        },
        source_system="synthetic_clearinghouse",
    )

    evaluation = _evaluate(payer, remittance)

    controls = [issue for issue in evaluation.batch_findings if issue.rule_id == "DQ-REM-006"]
    assert len(controls) == 1
    assert controls[0].severity == "critical"
    assert evaluation.reconciled is True


def test_claim_cannot_point_to_itself_as_an_original_submission() -> None:
    claim = _record(
        "claims",
        {
            "claim_id": "SYN-CLM-SELF",
            "submission_sequence": "1",
            "submission_type": "replacement",
            "original_claim_source_system": "synthetic_ehr",
            "original_claim_id": "SYN-CLM-SELF",
            "original_submission_sequence": "1",
            "claim_status": "submitted",
            "filing_deadline_date": "2026-08-30",
            "first_response_at": "",
            "first_response_disposition": "",
            "first_pass_accepted_flag": "false",
            "submitted_at": "2026-08-15T12:00:00Z",
            "adjudicated_at": "",
            "source_updated_at": "2026-08-15T12:00:00Z",
        },
        source_system="synthetic_ehr",
    )

    evaluation = _evaluate(claim)

    assert evaluation.records[0].disposition == "quarantined"
    assert "DQ-CLM-010" in {issue.rule_id for issue in evaluation.records[0].issues}
