"""Pure, deterministic record factories for each governed source family."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import overload

from claimsflow.generator.catalog import (
    APPEALS,
    CLAIM_LINES,
    CLAIMS,
    DENIALS,
    ELIGIBILITY,
    PAYMENTS,
    REFERENCE_COLUMNS,
    REMITTANCES,
    SourceDefinition,
    reference_definition,
)
from claimsflow.generator.models import GenerationConfig

Row = dict[str, str]
PAYERS = 5
PROVIDERS = 25
FACILITIES = 20
DIAGNOSES = 8
PROCEDURES = 8
REMITTANCE_GROUP_SIZE = 25

DENIAL_REASONS = (
    ("SYN-DEN-AUTH", "authorization", "Synthetic authorization evidence missing"),
    ("SYN-DEN-CODE", "coding", "Synthetic coding mismatch"),
    ("SYN-DEN-ELIG", "eligibility", "Synthetic eligibility mismatch"),
    ("SYN-DEN-TIME", "timely_filing", "Synthetic timely-filing issue"),
    ("SYN-DEN-DOC", "documentation", "Synthetic documentation incomplete"),
)


@dataclass(frozen=True, slots=True)
class SourceRows:
    """One source file definition paired with its single-pass row stream."""

    definition: SourceDefinition
    rows: Iterable[Row]


@dataclass(frozen=True, slots=True)
class ClaimAmounts:
    billed: int
    allowed: int | None
    payer_paid: int
    patient_paid: int
    patient_responsibility: int
    adjustment: int
    outstanding: int


@dataclass(frozen=True, slots=True)
class PaymentFact:
    index: int
    claim_id: str
    payer_id: str
    amount: int
    payment_date: date
    remittance_id: str


def _stable_int(config: GenerationConfig, namespace: str, index: int, low: int, high: int) -> int:
    payload = f"{config.seed}:{namespace}:{index}".encode()
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return low + value % (high - low + 1)


def _timestamp(value: date, hour: int = 12) -> str:
    return (
        datetime(value.year, value.month, value.day, hour, tzinfo=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _money(cents: int | None) -> str:
    if cents is None:
        return ""
    return f"{cents / 100:.2f}"


def _bool(value: bool) -> str:
    return str(value).lower()


def _claim_id(config: GenerationConfig, index: int) -> str:
    return f"SYN-CLM-{config.delivery_namespace}-{index:08d}"


def _patient_id(config: GenerationConfig, index: int) -> str:
    return f"SYN-PAT-{config.delivery_namespace}-{index:08d}"


def _eligibility_id(config: GenerationConfig, index: int) -> str:
    return f"SYN-ELG-{config.delivery_namespace}-{index:08d}"


def _denial_id(config: GenerationConfig, index: int) -> str:
    return f"SYN-DEN-{config.delivery_namespace}-{index:08d}"


def _payer_number(config: GenerationConfig, index: int) -> int:
    return _stable_int(config, "payer", index, 1, PAYERS)


def _payer_id(config: GenerationConfig, index: int) -> str:
    return f"SYN-PAYER-{_payer_number(config, index):02d}"


def _plan_id(config: GenerationConfig, index: int) -> str:
    return f"SYN-PLAN-{_payer_number(config, index):02d}"


def _service_date(config: GenerationConfig, index: int) -> date:
    return config.service_month + timedelta(days=_stable_int(config, "service-day", index, 0, 27))


def _is_denied(config: GenerationConfig, index: int) -> bool:
    return _stable_int(config, "denial", index, 1, 8) == 1


def _claim_amounts(config: GenerationConfig, index: int) -> ClaimAmounts:
    billed = _stable_int(config, "billed-cents", index, 10_000, 250_000)
    if _is_denied(config, index):
        return ClaimAmounts(
            billed=billed,
            allowed=None,
            payer_paid=0,
            patient_paid=0,
            patient_responsibility=0,
            adjustment=0,
            outstanding=billed,
        )
    payer_paid = billed * 70 // 100
    patient_paid = billed * 10 // 100
    adjustment = billed - payer_paid - patient_paid
    return ClaimAmounts(
        billed=billed,
        allowed=payer_paid + patient_paid,
        payer_paid=payer_paid,
        patient_paid=patient_paid,
        patient_responsibility=patient_paid,
        adjustment=adjustment,
        outstanding=0,
    )


@overload
def _split_cents(total: int, parts: int) -> tuple[int, ...]: ...


@overload
def _split_cents(total: None, parts: int) -> tuple[None, ...]: ...


def _split_cents(total: int | None, parts: int) -> tuple[int | None, ...]:
    if total is None:
        return (None,) * parts
    quotient, remainder = divmod(total, parts)
    return tuple(quotient + (1 if position < remainder else 0) for position in range(parts))


def _line_count(config: GenerationConfig, index: int) -> int:
    return _stable_int(config, "line-count", index, 1, 3)


def _denial_reason(config: GenerationConfig, index: int) -> tuple[str, str, str]:
    position = _stable_int(config, "denial-reason", index, 0, len(DENIAL_REASONS) - 1)
    return DENIAL_REASONS[position]


def iter_reference_rows(dataset: str, config: GenerationConfig) -> Iterator[Row]:
    """Yield one complete effective-dated synthetic reference dataset."""

    valid_from = date(config.service_month.year - 1, 1, 1).isoformat()
    common = {"valid_from": valid_from, "valid_to": "", "active_flag": "true"}
    if dataset == "payers":
        payer_types = ("commercial", "commercial", "medicare", "medicaid", "other")
        for index in range(1, PAYERS + 1):
            yield {
                "payer_id": f"SYN-PAYER-{index:02d}",
                "payer_name": f"Synthetic Payer {index:02d}",
                "payer_type": payer_types[index - 1],
                "timely_filing_days": str(90 + index * 15),
                "appeal_window_days": str(45 + index * 5),
                "expected_response_days": str(10 + index),
                "historical_resolution_rate": f"{0.45 + index * 0.05:.4f}",
                **common,
            }
    elif dataset == "plans":
        coverage_types = ("commercial", "commercial", "medicare", "medicaid", "other")
        for index in range(1, PAYERS + 1):
            yield {
                "plan_id": f"SYN-PLAN-{index:02d}",
                "payer_id": f"SYN-PAYER-{index:02d}",
                "plan_name": f"Synthetic Plan {index:02d}",
                "coverage_type": coverage_types[index - 1],
                **common,
            }
    elif dataset == "providers":
        for index in range(1, PROVIDERS + 1):
            yield {
                "provider_id": f"SYN-PRV-{index:03d}",
                "provider_name": f"Synthetic Provider {index:03d}",
                "specialty_code": f"SYN-SPC-{(index - 1) % 6 + 1:02d}",
                **common,
            }
    elif dataset == "facilities":
        for index in range(1, FACILITIES + 1):
            yield {
                "facility_id": f"SYN-FAC-{index:02d}",
                "facility_name": f"Synthetic Clinic {index:02d}",
                "clinic_number": str(index),
                "region": f"Synthetic Region {(index - 1) % 4 + 1}",
                **common,
            }
    elif dataset == "diagnoses":
        for index in range(1, DIAGNOSES + 1):
            yield {
                "diagnosis_code": f"SYN-DX-{index:03d}",
                "code_system": "SYNTHETIC",
                "diagnosis_description": f"Non-clinical synthetic diagnosis group {index:02d}",
                **common,
            }
    elif dataset == "procedures":
        for index in range(1, PROCEDURES + 1):
            yield {
                "procedure_code": f"SYN-PROC-{index:03d}",
                "code_system": "SYNTHETIC",
                "procedure_description": f"Non-clinical synthetic service group {index:02d}",
                **common,
            }
    elif dataset == "denial-reasons":
        for index, (code, category, description) in enumerate(DENIAL_REASONS, start=1):
            yield {
                "denial_reason_code": code,
                "denial_category": category,
                "denial_reason_description": description,
                "preventable_default_flag": _bool(index != 4),
                "required_document_codes": "SYN-DOC-A|SYN-DOC-B" if index in {1, 5} else "",
                "historical_resolution_rate": f"{0.40 + index * 0.08:.4f}",
                **common,
            }
    else:
        raise ValueError(f"unsupported reference dataset: {dataset}")


def iter_eligibility_rows(config: GenerationConfig) -> Iterator[Row]:
    coverage_start = date(config.service_month.year, 1, 1)
    coverage_end = date(config.service_month.year + 1, 1, 1)
    for index in range(1, config.claim_count + 1):
        service_date = _service_date(config, index)
        verification = _timestamp(service_date, 6)
        yield {
            "eligibility_id": _eligibility_id(config, index),
            "patient_id": _patient_id(config, index),
            "payer_id": _payer_id(config, index),
            "plan_id": _plan_id(config, index),
            "member_reference": f"SYN-MBR-{config.delivery_namespace}-{index:08d}",
            "verification_at": verification,
            "response_status": "confirmed",
            "coverage_status": "active",
            "coverage_type": "commercial",
            "coverage_start_date": coverage_start.isoformat(),
            "coverage_end_date": coverage_end.isoformat(),
            "primary_coverage_flag": "true",
            "deductible_remaining": _money(
                _stable_int(config, "deductible-cents", index, 0, 300_000)
            ),
            "out_of_pocket_remaining": _money(_stable_int(config, "oop-cents", index, 0, 600_000)),
            "copay_amount": _money(_stable_int(config, "copay-cents", index, 0, 7_500)),
            "currency_code": "USD",
            "source_updated_at": verification,
        }


def iter_claim_rows(config: GenerationConfig) -> Iterator[Row]:
    for index in range(1, config.claim_count + 1):
        service_date = _service_date(config, index)
        submitted_date = service_date + timedelta(days=1)
        response_date = service_date + timedelta(days=2)
        adjudicated_date = service_date + timedelta(days=7)
        denied = _is_denied(config, index)
        amounts = _claim_amounts(config, index)
        yield {
            "claim_id": _claim_id(config, index),
            "submission_sequence": "1",
            "original_claim_source_system": "",
            "original_claim_id": "",
            "original_submission_sequence": "",
            "patient_id": _patient_id(config, index),
            "eligibility_source_system": ELIGIBILITY.source_system,
            "eligibility_id": _eligibility_id(config, index),
            "provider_id": f"SYN-PRV-{_stable_int(config, 'provider', index, 1, PROVIDERS):03d}",
            "facility_id": f"SYN-FAC-{_stable_int(config, 'facility', index, 1, FACILITIES):02d}",
            "payer_id": _payer_id(config, index),
            "plan_id": _plan_id(config, index),
            "claim_type": "professional" if index % 4 else "institutional",
            "claim_status": "denied" if denied else "paid",
            "submission_type": "original",
            "service_from_date": service_date.isoformat(),
            "service_to_date": service_date.isoformat(),
            "submitted_at": _timestamp(submitted_date, 9),
            "first_response_at": _timestamp(response_date, 10),
            "first_response_disposition": "accepted",
            "adjudicated_at": _timestamp(adjudicated_date, 11),
            "primary_diagnosis_code": (
                f"SYN-DX-{_stable_int(config, 'diagnosis', index, 1, DIAGNOSES):03d}"
            ),
            "primary_diagnosis_code_system": "SYNTHETIC",
            "billed_amount": _money(amounts.billed),
            "allowed_amount": _money(amounts.allowed),
            "payer_paid_amount": _money(amounts.payer_paid),
            "patient_paid_amount": _money(amounts.patient_paid),
            "patient_responsibility_amount": _money(amounts.patient_responsibility),
            "adjustment_amount": _money(amounts.adjustment),
            "outstanding_balance": _money(amounts.outstanding),
            "currency_code": "USD",
            "clean_claim_flag": "true",
            "first_pass_accepted_flag": "true",
            "filing_deadline_date": (service_date + timedelta(days=90)).isoformat(),
            "source_updated_at": _timestamp(adjudicated_date, 12),
        }


def iter_claim_line_rows(config: GenerationConfig) -> Iterator[Row]:
    for index in range(1, config.claim_count + 1):
        line_count = _line_count(config, index)
        amounts = _claim_amounts(config, index)
        denied = _is_denied(config, index)
        reason_code, _, _ = _denial_reason(config, index)
        service_date = _service_date(config, index)
        billed = _split_cents(amounts.billed, line_count)
        payer_paid = _split_cents(amounts.payer_paid, line_count)
        patient_paid = _split_cents(amounts.patient_paid, line_count)
        patient_responsibility = _split_cents(amounts.patient_responsibility, line_count)
        allowed = (
            (None,) * line_count
            if amounts.allowed is None
            else tuple(
                payer_paid[position] + patient_responsibility[position]
                for position in range(line_count)
            )
        )
        outstanding = _split_cents(amounts.outstanding, line_count)
        adjustment = tuple(
            billed[position] - payer_paid[position] - patient_paid[position] - outstanding[position]
            for position in range(line_count)
        )
        if any(value < 0 for value in adjustment) or sum(adjustment) != amounts.adjustment:
            raise AssertionError("claim-line financial allocation must reconcile exactly")
        for offset in range(line_count):
            line_number = offset + 1
            procedure_number = _stable_int(config, "procedure", index + offset, 1, PROCEDURES)
            yield {
                "claim_id": _claim_id(config, index),
                "submission_sequence": "1",
                "line_number": str(line_number),
                "claim_line_id": (
                    f"SYN-CLN-{config.delivery_namespace}-{index:08d}-{line_number:02d}"
                ),
                "service_from_date": service_date.isoformat(),
                "service_to_date": service_date.isoformat(),
                "procedure_code": f"SYN-PROC-{procedure_number:03d}",
                "procedure_code_system": "SYNTHETIC",
                "procedure_modifiers": "",
                "diagnosis_codes": (
                    f"SYN-DX-{_stable_int(config, 'diagnosis', index, 1, DIAGNOSES):03d}"
                ),
                "diagnosis_code_system": "SYNTHETIC",
                "place_of_service_code": "11",
                "revenue_code": "",
                "units": "1.0000",
                "line_status": "denied" if denied else "paid",
                "denial_reason_code": reason_code if denied else "",
                "billed_amount": _money(billed[offset]),
                "allowed_amount": _money(allowed[offset]),
                "payer_paid_amount": _money(payer_paid[offset]),
                "patient_paid_amount": _money(patient_paid[offset]),
                "patient_responsibility_amount": _money(patient_responsibility[offset]),
                "adjustment_amount": _money(adjustment[offset]),
                "outstanding_balance": _money(outstanding[offset]),
                "currency_code": "USD",
                "source_updated_at": _timestamp(service_date + timedelta(days=7), 12),
            }


def iter_payment_facts(config: GenerationConfig) -> Iterator[PaymentFact]:
    positions_by_payer: dict[str, int] = {}
    for index in range(1, config.claim_count + 1):
        amounts = _claim_amounts(config, index)
        if amounts.payer_paid == 0:
            continue
        payer_id = _payer_id(config, index)
        position = positions_by_payer.get(payer_id, 0) + 1
        positions_by_payer[payer_id] = position
        group = (position - 1) // REMITTANCE_GROUP_SIZE + 1
        yield PaymentFact(
            index=index,
            claim_id=_claim_id(config, index),
            payer_id=payer_id,
            amount=amounts.payer_paid,
            payment_date=_service_date(config, index) + timedelta(days=9),
            remittance_id=(
                f"SYN-REM-{config.delivery_namespace}-"
                f"{payer_id.removeprefix('SYN-PAYER-')}-{group:06d}"
            ),
        )


def iter_remittance_rows(config: GenerationConfig) -> Iterator[Row]:
    totals: dict[str, tuple[str, int, int]] = {}
    for fact in iter_payment_facts(config):
        payer_id, amount, count = totals.get(fact.remittance_id, (fact.payer_id, 0, 0))
        totals[fact.remittance_id] = (payer_id, amount + fact.amount, count + 1)
    remittance_date = config.generated_at.date() - timedelta(days=1)
    received_at = _timestamp(remittance_date, 10)
    for remittance_id in sorted(totals):
        payer_id, amount, count = totals[remittance_id]
        yield {
            "remittance_id": remittance_id,
            "reverses_remittance_source_system": "",
            "reverses_remittance_id": "",
            "payer_id": payer_id,
            "source_control_number": remittance_id.replace("SYN-REM", "SYN-CTL"),
            "payment_trace_number": remittance_id.replace("SYN-REM", "SYN-TRACE"),
            "payment_method": "eft",
            "direction": "credit",
            "remittance_date": remittance_date.isoformat(),
            "received_at": received_at,
            "total_payment_amount": _money(amount),
            "claim_transaction_count": str(count),
            "currency_code": "USD",
            "remittance_status": "posted",
            "source_updated_at": received_at,
        }


def iter_payment_rows(config: GenerationConfig) -> Iterator[Row]:
    for fact in iter_payment_facts(config):
        posted_at = _timestamp(fact.payment_date, 15)
        common = {
            "claim_source_system": CLAIMS.source_system,
            "claim_id": fact.claim_id,
            "claim_submission_sequence": "1",
            "claim_line_number": "",
            "claim_line_id": "",
            "currency_code": "USD",
            "payment_date": fact.payment_date.isoformat(),
            "posted_at": posted_at,
            "reverses_payment_source_system": "",
            "reverses_payment_id": "",
            "posting_status": "posted",
            "source_updated_at": posted_at,
        }
        yield {
            "payment_id": f"SYN-PAY-{config.delivery_namespace}-{fact.index:08d}-PAY",
            "remittance_source_system": REMITTANCES.source_system,
            "remittance_id": fact.remittance_id,
            "payer_id": fact.payer_id,
            "transaction_type": "payer_payment",
            "direction": "credit",
            "amount": _money(fact.amount),
            "adjustment_reason_code": "",
            **common,
        }
        amounts = _claim_amounts(config, fact.index)
        yield {
            "payment_id": f"SYN-PAY-{config.delivery_namespace}-{fact.index:08d}-PAT",
            "remittance_source_system": "",
            "remittance_id": "",
            "payer_id": "",
            "transaction_type": "patient_payment",
            "direction": "credit",
            "amount": _money(amounts.patient_paid),
            "adjustment_reason_code": "",
            **common,
        }
        yield {
            "payment_id": f"SYN-PAY-{config.delivery_namespace}-{fact.index:08d}-ADJ",
            "remittance_source_system": "",
            "remittance_id": "",
            "payer_id": fact.payer_id,
            "transaction_type": "contractual_adjustment",
            "direction": "credit",
            "amount": _money(amounts.adjustment),
            "adjustment_reason_code": "SYN-CONTRACTUAL",
            **common,
        }


def iter_denial_rows(config: GenerationConfig) -> Iterator[Row]:
    for index in range(1, config.claim_count + 1):
        if not _is_denied(config, index):
            continue
        service_date = _service_date(config, index)
        denial_date = service_date + timedelta(days=7)
        reason_code, category, _ = _denial_reason(config, index)
        amounts = _claim_amounts(config, index)
        yield {
            "denial_id": _denial_id(config, index),
            "claim_source_system": CLAIMS.source_system,
            "claim_id": _claim_id(config, index),
            "claim_submission_sequence": "1",
            "claim_line_number": "",
            "claim_line_id": "",
            "payer_id": _payer_id(config, index),
            "denial_reason_code": reason_code,
            "denial_category": category,
            "denial_date": denial_date.isoformat(),
            "received_at": _timestamp(denial_date, 13),
            "denied_amount": _money(amounts.outstanding),
            "currency_code": "USD",
            "filing_deadline_date": (service_date + timedelta(days=90)).isoformat(),
            "appeal_deadline_date": (denial_date + timedelta(days=60)).isoformat(),
            "denial_status": "open",
            "preventable_flag": _bool(category != "timely_filing"),
            "documentation_ready_flag": "true",
            "missing_document_codes": "",
            "source_updated_at": _timestamp(denial_date, 13),
        }


def iter_appeal_rows(config: GenerationConfig) -> Iterator[Row]:
    denial_position = 0
    for index in range(1, config.claim_count + 1):
        if not _is_denied(config, index):
            continue
        denial_position += 1
        if denial_position % 2 == 0:
            continue
        service_date = _service_date(config, index)
        denial_date = service_date + timedelta(days=7)
        created_date = denial_date + timedelta(days=1)
        amounts = _claim_amounts(config, index)
        yield {
            "appeal_id": f"SYN-APL-{config.delivery_namespace}-{index:08d}",
            "denial_source_system": DENIALS.source_system,
            "denial_id": _denial_id(config, index),
            "claim_source_system": CLAIMS.source_system,
            "claim_id": _claim_id(config, index),
            "claim_submission_sequence": "1",
            "appeal_level": "1",
            "appeal_status": "ready_for_human_review",
            "created_at": _timestamp(created_date, 9),
            "filed_at": "",
            "appeal_deadline_date": (denial_date + timedelta(days=60)).isoformat(),
            "decision_date": "",
            "outcome": "",
            "requested_amount": _money(amounts.outstanding),
            "recovered_amount": "",
            "currency_code": "USD",
            "documentation_ready_flag": "true",
            "owner_queue": "synthetic_human_appeal_review",
            "source_updated_at": _timestamp(created_date, 9),
        }


def source_rows(config: GenerationConfig) -> tuple[SourceRows, ...]:
    """Return all governed source streams in dependency order."""

    references = tuple(
        SourceRows(reference_definition(dataset), iter_reference_rows(dataset, config))
        for dataset in REFERENCE_COLUMNS
    )
    operational = (
        SourceRows(ELIGIBILITY, iter_eligibility_rows(config)),
        SourceRows(CLAIMS, iter_claim_rows(config)),
        SourceRows(CLAIM_LINES, iter_claim_line_rows(config)),
        SourceRows(REMITTANCES, iter_remittance_rows(config)),
        SourceRows(PAYMENTS, iter_payment_rows(config)),
        SourceRows(DENIALS, iter_denial_rows(config)),
        SourceRows(APPEALS, iter_appeal_rows(config)),
    )
    return references + operational
