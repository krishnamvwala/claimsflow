"""Deterministic row validation and synthetic-provenance checks."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from claimsflow.domain.ingestion import ClassifiedRow, Disposition, ValidationIssue
from claimsflow.ingestion.contracts import FieldContract, SourceFileContract


class ProvenanceViolation(ValueError):
    """Raised before landing when source rows are not reserved synthetic fixtures."""


_DISPOSITION_RANK: dict[Disposition, int] = {
    "accepted": 0,
    "accepted_with_warning": 1,
    "quarantined": 2,
    "rejected": 3,
}
_RESERVED_IDENTIFIER_FIELDS = {
    "member_reference",
    "payment_trace_number",
    "source_control_number",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def payload_sha256(payload: dict[str, str]) -> str:
    """Hash the immutable source-shaped payload with stable JSON encoding."""

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _key_value(field: str, row: dict[str, str], source_system: str) -> str:
    return source_system if field == "source_system" else row.get(field, "")


def stable_key(fields: tuple[str, ...], row: dict[str, str], source_system: str) -> str:
    """Serialize an ordered source key without ambiguous delimiter joining."""

    return _canonical_json([_key_value(field, row, source_system) for field in fields])


def _is_identifier(field: str) -> bool:
    return field.endswith("_id") or field in _RESERVED_IDENTIFIER_FIELDS


def verify_reserved_synthetic_values(
    contract: SourceFileContract,
    row: dict[str, str],
    source_system: str,
    row_number: int,
) -> None:
    """Fail closed when identity values could be mistaken for real records."""

    if not source_system.startswith("synthetic_"):
        raise ProvenanceViolation(
            f"DQ-CMN-001: {contract.source_identity} has an unapproved source system"
        )
    for field in contract.fields:
        value = row.get(field.name, "")
        if value and _is_identifier(field.name) and not value.startswith("SYN-"):
            raise ProvenanceViolation(
                f"DQ-CMN-001: {contract.source_identity} row {row_number} field "
                f"{field.name} is not a reserved synthetic identifier"
            )
    for name, value in row.items():
        if name.endswith("source_system") and value and not value.startswith("synthetic_"):
            raise ProvenanceViolation(
                f"DQ-CMN-001: {contract.source_identity} row {row_number} field {name} "
                "is not an approved synthetic source"
            )


def _issue(
    rule_id: str,
    severity: str,
    disposition: Disposition,
    reason: str,
    field: str | None = None,
    normalized_value: str | None = None,
) -> ValidationIssue:
    if severity not in {"warning", "error", "critical"}:
        raise AssertionError(f"unsupported severity: {severity}")
    return ValidationIssue(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        disposition=disposition,
        reason=reason,
        field=field,
        normalized_value=normalized_value,
    )


def _normalize_text(field: FieldContract, value: str) -> tuple[str, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    normalized = value
    trimmed = value.strip(" \t\r\n")
    if trimmed != value:
        if _is_identifier(field.name):
            issues.append(
                _issue(
                    "DQ-CMN-014",
                    "error",
                    "quarantined",
                    "identifier contains leading or trailing whitespace",
                    field.name,
                )
            )
        else:
            normalized = trimmed
            issues.append(
                _issue(
                    "NORM-CMN-001",
                    "warning",
                    "accepted_with_warning",
                    "trimmed leading or trailing ASCII whitespace",
                    field.name,
                    normalized,
                )
            )
    if field.allowed_values and normalized not in field.allowed_values:
        case_matches = [item for item in field.allowed_values if item.lower() == normalized.lower()]
        if len(case_matches) == 1:
            normalized = case_matches[0]
            issues.append(
                _issue(
                    "NORM-CMN-002",
                    "warning",
                    "accepted_with_warning",
                    "normalized allowed code or enum capitalization",
                    field.name,
                    normalized,
                )
            )
    return normalized, issues


def _parse_decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _numeric_shape(field_type: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"NUMERIC\(([0-9]+),([0-9]+)\)", field_type)
    if match is None:
        return None
    precision, scale = (int(value) for value in match.groups())
    return precision, scale


def _fits_numeric(value: str, precision: int, scale: int) -> bool:
    match = re.fullmatch(r"-?([0-9]+)(?:\.([0-9]+))?", value)
    if match is None or scale > precision:
        return False
    integer, fraction = match.groups()
    integer_digits = len(integer.lstrip("0"))
    fraction_digits = len(fraction or "")
    return integer_digits <= precision - scale and fraction_digits <= scale


def _validate_type(
    field: FieldContract,
    value: str,
) -> tuple[str, Decimal | int | datetime | date | bool | None, list[ValidationIssue]]:
    if field.field_type in {"STRING", "STRING_LIST"}:
        normalized, issues = _normalize_text(field, value)
    else:
        normalized, issues = value, []
    parsed: Decimal | int | datetime | date | bool | None = None
    valid = True

    if field.field_type in {"STRING", "STRING_LIST"}:
        parsed = None
    elif field.field_type == "INTEGER":
        if not re.fullmatch(r"-?[0-9]+", normalized):
            valid = False
        else:
            parsed = int(normalized)
    elif field.field_type.startswith("NUMERIC("):
        parsed = _parse_decimal(normalized)
        shape = _numeric_shape(field.field_type)
        valid = parsed is not None and shape is not None
        if valid and shape is not None:
            precision, scale = shape
            valid = _fits_numeric(normalized, precision, scale)
        if valid and shape is not None:
            _, scale = shape
            fractional_digits = len(normalized.partition(".")[2])
        else:
            fractional_digits = 0
        if valid and shape is not None and fractional_digits < scale:
            normalized = f"{parsed:.{scale}f}"
            issues.append(
                _issue(
                    "NORM-CMN-005",
                    "warning",
                    "accepted_with_warning",
                    "normalized monetary or decimal scale",
                    field.name,
                    normalized,
                )
            )
    elif field.field_type == "DATE":
        try:
            parsed = date.fromisoformat(normalized)
        except ValueError:
            valid = False
    elif field.field_type == "TIMESTAMP":
        try:
            timestamp = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                valid = False
            else:
                parsed = timestamp
                utc_value = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
                if not normalized.endswith("Z"):
                    normalized = utc_value
                    issues.append(
                        _issue(
                            "NORM-CMN-003",
                            "warning",
                            "accepted_with_warning",
                            "normalized timestamp to UTC",
                            field.name,
                            normalized,
                        )
                    )
        except ValueError:
            valid = False
    elif field.field_type == "BOOLEAN":
        lowered = normalized.lower()
        if lowered in {"true", "false"}:
            if normalized != lowered:
                normalized = lowered
                issues.append(
                    _issue(
                        "NORM-CMN-004",
                        "warning",
                        "accepted_with_warning",
                        "normalized boolean representation",
                        field.name,
                        normalized,
                    )
                )
            parsed = lowered == "true"
        elif normalized in {"1", "0"}:
            normalized = "true" if normalized == "1" else "false"
            parsed = normalized == "true"
            issues.append(
                _issue(
                    "NORM-CMN-004",
                    "warning",
                    "accepted_with_warning",
                    "normalized boolean representation",
                    field.name,
                    normalized,
                )
            )
        else:
            valid = False
    else:
        valid = False

    if not valid:
        issues.append(
            _issue(
                "DQ-CMN-013",
                "critical",
                "rejected",
                f"value cannot be parsed as governed type {field.field_type}",
                field.name,
            )
        )
        return normalized, None, issues
    return normalized, parsed, issues


def _constraint_issues(
    field: FieldContract,
    value: str,
    parsed: Decimal | int | datetime | date | bool | None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if field.allowed_values and value not in field.allowed_values:
        issues.append(
            _issue(
                "DQ-CMN-014",
                "error",
                "quarantined",
                "value is outside the governed allowed set",
                field.name,
            )
        )
    if field.pattern is not None and re.fullmatch(field.pattern, value) is None:
        issues.append(
            _issue(
                "DQ-CMN-014",
                "error",
                "quarantined",
                "value does not match the governed pattern",
                field.name,
            )
        )
    if isinstance(parsed, (Decimal, int)) and not isinstance(parsed, bool):
        numeric = Decimal(parsed)
        violations = (
            (
                field.minimum is not None and numeric < Decimal(str(field.minimum)),
                "value is below the minimum",
            ),
            (
                field.maximum is not None and numeric > Decimal(str(field.maximum)),
                "value is above the maximum",
            ),
            (
                field.minimum_exclusive is not None
                and numeric <= Decimal(str(field.minimum_exclusive)),
                "value is not above the exclusive minimum",
            ),
        )
        for violated, reason in violations:
            if violated:
                issues.append(
                    _issue(
                        "DQ-CMN-014",
                        "error",
                        "quarantined",
                        reason,
                        field.name,
                    )
                )
    return issues


def _decimal(row: dict[str, str], field: str) -> Decimal | None:
    return _parse_decimal(row.get(field, ""))


def _domain_issues(contract: SourceFileContract, row: dict[str, str]) -> list[ValidationIssue]:
    family = contract.source_family
    issues: list[ValidationIssue] = []
    currency = row.get("currency_code")
    if currency not in {None, "", "USD"}:
        rule = {
            "appeals": "DQ-APL-007",
            "claim-lines": "DQ-CLN-006",
            "claims": "DQ-CLM-005",
            "denials": "DQ-DEN-006",
            "eligibility": "DQ-ELG-007",
            "payments": "DQ-PAY-004",
            "remittances": "DQ-REM-004",
        }.get(family, "DQ-CMN-014")
        issues.append(
            _issue(rule, "error", "quarantined", "currency_code must be USD", "currency_code")
        )

    if family in {"claims", "claim-lines"}:
        billed = _decimal(row, "billed_amount")
        parts = [
            _decimal(row, field)
            for field in (
                "payer_paid_amount",
                "patient_paid_amount",
                "adjustment_amount",
                "outstanding_balance",
            )
        ]
        if (
            billed is not None
            and all(part is not None for part in parts)
            and billed != sum((part for part in parts if part is not None), Decimal("0"))
        ):
            rule = "DQ-CLM-006" if family == "claims" else "DQ-CLN-007"
            issues.append(
                _issue(
                    rule,
                    "error",
                    "quarantined",
                    "financial components do not equal billed_amount",
                )
            )

        allowed = _decimal(row, "allowed_amount")
        payer_paid = _decimal(row, "payer_paid_amount")
        patient_responsibility = _decimal(row, "patient_responsibility_amount")
        patient_paid = _decimal(row, "patient_paid_amount")
        if (
            allowed is not None
            and payer_paid is not None
            and patient_responsibility is not None
            and payer_paid + patient_responsibility > allowed
        ):
            rule = "DQ-CLM-007" if family == "claims" else "DQ-CLN-009"
            issues.append(
                _issue(
                    rule,
                    "error",
                    "quarantined",
                    "payer payment plus patient responsibility exceeds allowed amount",
                )
            )
        if (
            patient_paid is not None
            and patient_responsibility is not None
            and patient_paid > patient_responsibility
        ):
            rule = "DQ-CLM-012" if family == "claims" else "DQ-CLN-010"
            issues.append(
                _issue(
                    rule,
                    "error",
                    "quarantined",
                    "patient payment exceeds patient responsibility",
                )
            )

    if family == "payments":
        amount = _decimal(row, "amount")
        if amount is not None and amount <= 0:
            issues.append(
                _issue("DQ-PAY-004", "error", "quarantined", "amount must be positive", "amount")
            )
        credit_types = {"payer_payment", "patient_payment", "contractual_adjustment", "write_off"}
        debit_types = {"refund", "reversal"}
        transaction_type = row.get("transaction_type")
        direction = row.get("direction")
        if (transaction_type in credit_types and direction != "credit") or (
            transaction_type in debit_types and direction != "debit"
        ):
            issues.append(
                _issue(
                    "DQ-PAY-011", "error", "quarantined", "transaction direction is inconsistent"
                )
            )
    if family == "remittances":
        amount = _decimal(row, "total_payment_amount")
        if amount is not None and amount < 0:
            issues.append(
                _issue("DQ-REM-004", "error", "quarantined", "total payment cannot be negative")
            )
        status = row.get("remittance_status")
        direction = row.get("direction")
        if (status in {"received", "posted"} and direction != "credit") or (
            status == "reversed" and direction != "debit"
        ):
            issues.append(
                _issue("DQ-REM-007", "error", "quarantined", "remittance direction is inconsistent")
            )
    if family == "eligibility":
        start = row.get("coverage_start_date")
        end = row.get("coverage_end_date")
        if start and end:
            try:
                if date.fromisoformat(end) <= date.fromisoformat(start):
                    issues.append(
                        _issue("DQ-ELG-005", "error", "quarantined", "coverage interval is invalid")
                    )
            except ValueError:
                pass
    if family == "appeals":
        requested = _decimal(row, "requested_amount")
        recovered = _decimal(row, "recovered_amount") if row.get("recovered_amount") else None
        if requested is not None and (
            requested <= 0 or (recovered is not None and (recovered < 0 or recovered > requested))
        ):
            issues.append(
                _issue("DQ-APL-007", "error", "quarantined", "appeal amounts are inconsistent")
            )
    if family == "denials":
        denial_date = row.get("denial_date")
        for deadline_field in ("filing_deadline_date", "appeal_deadline_date"):
            deadline = row.get(deadline_field)
            if denial_date and deadline:
                try:
                    if date.fromisoformat(deadline) < date.fromisoformat(denial_date):
                        issues.append(
                            _issue(
                                "DQ-DEN-007",
                                "error",
                                "quarantined",
                                "deadline precedes denial date",
                                deadline_field,
                            )
                        )
                except ValueError:
                    pass
    if family == "reference-data":
        start = row.get("valid_from")
        end = row.get("valid_to")
        if start and end:
            try:
                if date.fromisoformat(end) <= date.fromisoformat(start):
                    issues.append(
                        _issue(
                            "DQ-REF-003", "error", "quarantined", "effective interval is invalid"
                        )
                    )
            except ValueError:
                pass
    return issues


def classify_row(
    contract: SourceFileContract,
    row: dict[str, str],
    source_system: str,
    duplicate_natural_key: bool,
) -> ClassifiedRow:
    """Validate one row, retain original values, and assign exactly one disposition."""

    normalized = dict(row)
    issues: list[ValidationIssue] = []
    for field in contract.fields:
        value = row.get(field.name, "")
        if value == "":
            if not field.nullable:
                rule_id = (
                    contract.required_rule_id
                    if field.name in contract.required_rule_fields
                    else "DQ-CMN-013"
                )
                issues.append(
                    _issue(
                        rule_id,
                        "critical",
                        "rejected",
                        "required non-null source value is empty",
                        field.name,
                    )
                )
            continue
        normalized_value, parsed, field_issues = _validate_type(field, value)
        normalized[field.name] = normalized_value
        issues.extend(field_issues)
        if not any(issue.rule_id == "DQ-CMN-013" for issue in field_issues):
            issues.extend(_constraint_issues(field, normalized_value, parsed))

    source_record_id = stable_key(contract.source_record_id, normalized, source_system)
    natural_key = stable_key(contract.natural_key, normalized, source_system)
    if any(
        _key_value(field, normalized, source_system) == "" for field in contract.source_record_id
    ):
        issues.append(
            _issue(
                "DQ-CMN-007",
                "critical",
                "rejected",
                "source record identity cannot be generated completely",
            )
        )
    if duplicate_natural_key:
        issues.append(
            _issue(
                contract.duplicate_rule_id,
                "critical",
                "rejected",
                "duplicate natural key exists within the delivery file",
            )
        )
    issues.extend(_domain_issues(contract, normalized))

    unique_issues = tuple(
        {
            (issue.rule_id, issue.field, issue.reason, issue.normalized_value): issue
            for issue in issues
        }.values()
    )
    disposition: Disposition = "accepted"
    for issue in unique_issues:
        if _DISPOSITION_RANK[issue.disposition] > _DISPOSITION_RANK[disposition]:
            disposition = issue.disposition
    return ClassifiedRow(
        source_identity=contract.source_identity,
        source_record_id=source_record_id,
        natural_key=natural_key,
        version_discriminator=normalized.get(contract.version_field, ""),
        payload_sha256=payload_sha256(row),
        disposition=disposition,
        original_payload=row,
        normalized_payload=normalized,
        issues=unique_issues,
    )
