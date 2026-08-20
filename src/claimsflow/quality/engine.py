"""Deterministic Phase 3 relationship, freshness, reconciliation, and gate engine."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from claimsflow.domain.ingestion import Disposition, ValidationIssue
from claimsflow.domain.quality import QualityIssue, SourceQualitySummary
from claimsflow.quality.catalog import PolicyRule, QualityCatalog, RelationshipSpec

_DISPOSITION_RANK: dict[Disposition, int] = {
    "accepted": 0,
    "accepted_with_warning": 1,
    "quarantined": 2,
    "rejected": 3,
}
FreshnessStatus = Literal["current", "late", "not_evaluable"]

PHASE3_SEMANTIC_RULE_IDS = frozenset(
    {
        "DQ-APL-003",
        "DQ-APL-004",
        "DQ-APL-005",
        "DQ-APL-006",
        "DQ-APL-007",
        "DQ-APL-008",
        "DQ-APL-009",
        "DQ-APL-011",
        "DQ-APL-012",
        "DQ-CLM-003",
        "DQ-CLM-009",
        "DQ-CLM-010",
        "DQ-CLM-011",
        "DQ-CLM-013",
        "DQ-CLM-014",
        "DQ-CLN-004",
        "DQ-CLN-005",
        "DQ-CLN-008",
        "DQ-DEN-003",
        "DQ-DEN-004",
        "DQ-DEN-005",
        "DQ-DEN-006",
        "DQ-DEN-007",
        "DQ-DEN-008",
        "DQ-DEN-009",
        "DQ-DEN-010",
        "DQ-ELG-004",
        "DQ-ELG-006",
        "DQ-ELG-008",
        "DQ-PAY-003",
        "DQ-PAY-005",
        "DQ-PAY-006",
        "DQ-PAY-007",
        "DQ-PAY-008",
        "DQ-PAY-009",
        "DQ-PAY-010",
        "DQ-PAY-012",
        "DQ-REF-004",
        "DQ-REF-005",
        "DQ-REF-006",
        "DQ-REF-007",
        "DQ-REM-005",
        "DQ-REM-006",
        "DQ-REM-008",
        "DQ-REM-009",
    }
)


@dataclass(frozen=True, slots=True)
class QualityRecord:
    """One immutable raw envelope projected into the Phase 3 rule engine."""

    source_identity: str
    source_system: str
    source_record_id: str
    natural_key: str
    payload_sha256: str
    original_payload: dict[str, str]
    normalized_payload: dict[str, str]
    preliminary_disposition: Disposition
    preliminary_issues: tuple[ValidationIssue, ...]
    lineage: dict[str, object]
    correction_id: str | None = None


@dataclass(slots=True)
class EvaluatedRecord:
    """A record with final rule evidence and exactly one disposition."""

    record: QualityRecord
    disposition: Disposition
    issues: list[QualityIssue]


@dataclass(frozen=True, slots=True)
class QualityEvaluation:
    """Pure evaluation result consumed by the immutable artifact writer."""

    records: tuple[EvaluatedRecord, ...]
    source_summaries: tuple[SourceQualitySummary, ...]
    source_findings: tuple[QualityIssue, ...]
    batch_findings: tuple[QualityIssue, ...]
    reconciled: bool


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        timestamp = _parse_timestamp(value)
        return None if timestamp is None else timestamp.date()


def _decimal(value: str | None) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _duration(value: str) -> timedelta:
    body = value.removeprefix("PT")
    hours = 0
    minutes = 0
    if "H" in body:
        hour_value, body = body.split("H", 1)
        hours = int(hour_value)
    if body.endswith("M"):
        minutes = int(body[:-1])
    return timedelta(hours=hours, minutes=minutes)


def _value(record: QualityRecord, field: str) -> str:
    return (
        record.source_system
        if field == "source_system"
        else record.normalized_payload.get(field, "")
    )


def _issue(
    rule: PolicyRule,
    *,
    processed_at_utc: str,
    reason: str,
    record: QualityRecord | None = None,
    source_identity: str | None = None,
    field: str | None = None,
) -> QualityIssue:
    disposition: Disposition | None = (
        None if rule.disposition == "block_batch" else rule.disposition
    )
    return QualityIssue(
        rule_id=rule.rule_id,
        severity=rule.severity,
        disposition=disposition,
        reason=reason,
        processed_at_utc=processed_at_utc,
        source_identity=record.source_identity if record is not None else source_identity,
        source_record_id=record.source_record_id if record is not None else None,
        natural_key=record.natural_key if record is not None else None,
        field=field,
    )


def _add_issue(evaluated: EvaluatedRecord, issue: QualityIssue) -> bool:
    key = (issue.rule_id, issue.field, issue.reason)
    if any((item.rule_id, item.field, item.reason) == key for item in evaluated.issues):
        return False
    evaluated.issues.append(issue)
    if issue.disposition is not None and (
        _DISPOSITION_RANK[issue.disposition] > _DISPOSITION_RANK[evaluated.disposition]
    ):
        evaluated.disposition = issue.disposition
        return True
    return False


def _initial(record: QualityRecord, processed_at_utc: str) -> EvaluatedRecord:
    issues = [
        QualityIssue(
            rule_id=item.rule_id,
            severity=item.severity,
            disposition=item.disposition,
            reason=item.reason,
            processed_at_utc=processed_at_utc,
            source_identity=record.source_identity,
            source_record_id=record.source_record_id,
            natural_key=record.natural_key,
            field=item.field,
        )
        for item in record.preliminary_issues
    ]
    return EvaluatedRecord(
        record=record,
        disposition=record.preliminary_disposition,
        issues=issues,
    )


def _active(records: list[EvaluatedRecord], identity: str) -> list[EvaluatedRecord]:
    return [
        item
        for item in records
        if item.record.source_identity == identity
        and item.disposition in {"accepted", "accepted_with_warning"}
    ]


def _target_key(record: QualityRecord, fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_value(record, field) for field in fields)


def _source_keys(record: QualityRecord, relationship: RelationshipSpec) -> list[tuple[str, ...]]:
    values = tuple(_value(record, field) for field in relationship.fields)
    if not relationship.every_list_member:
        return [values]
    members = tuple(item for item in values[0].split("|") if item)
    return [(member, *values[1:]) for member in members]


def _effective_matches(
    candidates: list[EvaluatedRecord],
    relationship: RelationshipSpec,
    source: QualityRecord,
) -> list[EvaluatedRecord]:
    if relationship.as_of_field is None:
        return []
    as_of = _parse_date(_value(source, relationship.as_of_field))
    if as_of is None:
        return []
    matches: list[EvaluatedRecord] = []
    for candidate in candidates:
        start = _parse_date(candidate.record.normalized_payload.get("valid_from", ""))
        end_value = candidate.record.normalized_payload.get("valid_to", "")
        end = None if not end_value else _parse_date(end_value)
        if start is not None and start <= as_of and (end is None or as_of < end):
            matches.append(candidate)
    return matches


def _relationship_matches(
    source: QualityRecord,
    relationship: RelationshipSpec,
    records: list[EvaluatedRecord],
    source_key: tuple[str, ...],
) -> list[EvaluatedRecord]:
    candidates = [
        candidate
        for candidate in _active(records, relationship.target_identity)
        if _target_key(candidate.record, relationship.target_fields) == source_key
    ]
    if relationship.match == "effective_at":
        return _effective_matches(candidates, relationship, source)
    return candidates


def _apply_relationships(
    evaluated: list[EvaluatedRecord],
    catalog: QualityCatalog,
    processed_at_utc: str,
) -> None:
    for _ in range(len(catalog.identities()) + 1):
        changed = False
        for item in evaluated:
            if item.disposition not in {"accepted", "accepted_with_warning"}:
                continue
            contract = catalog.for_identity(item.record.source_identity)
            for relationship in contract.relationships:
                keys = _source_keys(item.record, relationship)
                if not relationship.required and (
                    not keys or any(any(value == "" for value in key) for key in keys)
                ):
                    continue
                failed = False
                for key in keys:
                    if any(value == "" for value in key):
                        failed = True
                        break
                    matches = _relationship_matches(item.record, relationship, evaluated, key)
                    if len(matches) != 1:
                        failed = True
                        break
                if failed:
                    changed = (
                        _add_issue(
                            item,
                            _issue(
                                relationship.rule,
                                processed_at_utc=processed_at_utc,
                                record=item.record,
                                field="+".join(relationship.fields),
                                reason=(
                                    "relationship did not resolve to exactly one eligible "
                                    f"{relationship.target_identity} record"
                                ),
                            ),
                        )
                        or changed
                    )
        if not changed:
            return
    raise AssertionError("relationship disposition propagation did not converge")


def _parent(
    records: list[EvaluatedRecord],
    identity: str,
    fields: tuple[str, ...],
    values: tuple[str, ...],
) -> EvaluatedRecord | None:
    matches = [
        item for item in _active(records, identity) if _target_key(item.record, fields) == values
    ]
    return matches[0] if len(matches) == 1 else None


def _row_rule(
    item: EvaluatedRecord,
    catalog: QualityCatalog,
    rule_id: str,
    processed_at_utc: str,
    reason: str,
    field: str | None = None,
) -> None:
    rule = catalog.rule_for(item.record.source_identity, rule_id)
    if rule.disposition == "block_batch":
        return
    _add_issue(
        item,
        _issue(
            rule,
            processed_at_utc=processed_at_utc,
            record=item.record,
            reason=reason,
            field=field,
        ),
    )


def _apply_reference_semantics(
    evaluated: list[EvaluatedRecord], catalog: QualityCatalog, processed_at_utc: str
) -> None:
    for identity in (item for item in catalog.identities() if item.startswith("reference-data.")):
        contract = catalog.for_identity(identity)
        business_fields = tuple(
            field for field in contract.natural_key if field not in {"source_system", "valid_from"}
        )
        grouped: dict[tuple[str, ...], list[EvaluatedRecord]] = defaultdict(list)
        for item in evaluated:
            if item.record.source_identity == identity and item.disposition != "rejected":
                grouped[_target_key(item.record, business_fields)].append(item)
        for versions in grouped.values():
            ordered = sorted(
                versions,
                key=lambda item: item.record.normalized_payload.get("valid_from", ""),
            )
            for index, left in enumerate(ordered):
                left_start = _parse_date(left.record.normalized_payload.get("valid_from", ""))
                left_end = _parse_date(left.record.normalized_payload.get("valid_to", ""))
                if left_start is None:
                    continue
                for right in ordered[index + 1 :]:
                    right_start = _parse_date(right.record.normalized_payload.get("valid_from", ""))
                    right_end = _parse_date(right.record.normalized_payload.get("valid_to", ""))
                    if right_start is None:
                        continue
                    if (left_end is None or right_start < left_end) and (
                        right_end is None or left_start < right_end
                    ):
                        for overlap in (left, right):
                            _row_rule(
                                overlap,
                                catalog,
                                "DQ-REF-004",
                                processed_at_utc,
                                "effective intervals overlap for the same reference identifier",
                            )
            current = [
                item
                for item in versions
                if item.record.normalized_payload.get("active_flag") == "true"
                and not item.record.normalized_payload.get("valid_to")
            ]
            if len(current) > 1:
                for item in current:
                    _row_rule(
                        item,
                        catalog,
                        "DQ-REF-005",
                        processed_at_utc,
                        "more than one current reference version exists",
                    )

        for item in evaluated:
            if item.record.source_identity != identity or item.disposition == "rejected":
                continue
            row = item.record.normalized_payload
            rate_fields = [field for field in row if field.endswith("_rate") and row[field]]
            window_fields = [field for field in row if field.endswith("_days") and row[field]]
            invalid_rate = any(
                (value := _decimal(row.get(field))) is None
                or not Decimal("0") <= value <= Decimal("1")
                for field in rate_fields
            )
            invalid_window = any(
                (value := _decimal(row.get(field))) is None or value <= 0 for field in window_fields
            )
            if invalid_rate or invalid_window:
                _row_rule(
                    item,
                    catalog,
                    "DQ-REF-007",
                    processed_at_utc,
                    "reference rate or configured day window is outside its governed range",
                )

    for plan in [
        item
        for item in evaluated
        if item.record.source_identity == "reference-data.plans"
        and item.disposition in {"accepted", "accepted_with_warning"}
    ]:
        row = plan.record.normalized_payload
        plan_start = _parse_date(row.get("valid_from", ""))
        plan_end = _parse_date(row.get("valid_to", ""))
        covering = []
        for payer in _active(evaluated, "reference-data.payers"):
            payer_row = payer.record.normalized_payload
            payer_start = _parse_date(payer_row.get("valid_from", ""))
            payer_end = _parse_date(payer_row.get("valid_to", ""))
            if (
                payer_row.get("payer_id") == row.get("payer_id")
                and plan_start is not None
                and payer_start is not None
                and payer_start <= plan_start
                and (payer_end is None or (plan_end is not None and plan_end <= payer_end))
            ):
                covering.append(payer)
        if len(covering) != 1:
            _row_rule(
                plan,
                catalog,
                "DQ-REF-006",
                processed_at_utc,
                "plan validity is not fully covered by exactly one payer version",
            )


def _apply_temporal_and_pair_rules(
    evaluated: list[EvaluatedRecord],
    catalog: QualityCatalog,
    evaluation_time: datetime,
    processed_at_utc: str,
) -> None:
    for item in evaluated:
        if item.disposition == "rejected":
            continue
        row = item.record.normalized_payload
        family = catalog.for_identity(item.record.source_identity).source_family
        if family == "claims":
            service_from = _parse_date(row.get("service_from_date", ""))
            service_to = _parse_date(row.get("service_to_date", ""))
            submitted = _parse_date(row.get("submitted_at", ""))
            if (
                service_from is not None
                and service_to is not None
                and submitted is not None
                and (
                    service_to < service_from or service_from > submitted or service_to > submitted
                )
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-003",
                    processed_at_utc,
                    "claim service dates are reversed or occur after submission",
                )
            if row.get("claim_status") in {
                "submitted",
                "accepted",
                "rejected",
                "denied",
            } and not row.get("filing_deadline_date"):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-009",
                    processed_at_utc,
                    "active claim state is missing its filing deadline",
                    "filing_deadline_date",
                )
            original_pointer = (
                bool(row.get("original_claim_source_system")),
                bool(row.get("original_claim_id")),
                bool(row.get("original_submission_sequence")),
            )
            if len(set(original_pointer)) != 1:
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-010",
                    processed_at_utc,
                    "original-claim pointer is only partially populated",
                )
            has_original_pointer = all(original_pointer)
            submission_type = row.get("submission_type")
            if (submission_type == "original" and any(original_pointer)) or (
                submission_type in {"replacement", "void"} and not has_original_pointer
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-010",
                    processed_at_utc,
                    "claim submission type contradicts its original-claim pointer",
                )
            current_sequence = _decimal(row.get("submission_sequence"))
            original_sequence = _decimal(row.get("original_submission_sequence"))
            if has_original_pointer and (
                row.get("original_claim_source_system") != item.record.source_system
                or row.get("original_claim_id") != row.get("claim_id")
                or current_sequence is None
                or original_sequence is None
                or original_sequence >= current_sequence
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-010",
                    processed_at_utc,
                    "original claim pointer must identify an earlier submission of the same claim",
                )
            first_response_at = _parse_timestamp(row.get("first_response_at", ""))
            first_response_disposition = row.get("first_response_disposition", "")
            has_response_at = bool(row.get("first_response_at"))
            has_response_disposition = bool(first_response_disposition)
            if has_response_at != has_response_disposition or (
                row.get("claim_status") != "submitted"
                and not (has_response_at and has_response_disposition)
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-013",
                    processed_at_utc,
                    "first-response fields contradict the claim lifecycle state",
                )
            submitted_at = _parse_timestamp(row.get("submitted_at", ""))
            adjudicated_at = _parse_timestamp(row.get("adjudicated_at", ""))
            first_pass_expected = first_response_disposition == "accepted"
            if (
                (row.get("first_pass_accepted_flag") == "true") != first_pass_expected
                or (
                    first_response_at is not None
                    and submitted_at is not None
                    and first_response_at < submitted_at
                )
                or (
                    first_response_at is not None
                    and adjudicated_at is not None
                    and first_response_at > adjudicated_at
                )
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLM-014",
                    processed_at_utc,
                    "first-response acceptance or chronology is inconsistent",
                )
        elif family == "claim-lines":
            service_from = _parse_date(row.get("service_from_date", ""))
            service_to = _parse_date(row.get("service_to_date", ""))
            if service_from is not None and service_to is not None and service_to < service_from:
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLN-004",
                    processed_at_utc,
                    "claim-line service dates are reversed",
                )
            if row.get("line_status") == "denied" and not row.get("denial_reason_code"):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLN-008",
                    processed_at_utc,
                    "denied claim line is missing a denial reason",
                    "denial_reason_code",
                )
            place_of_service = row.get("place_of_service_code", "")
            if (place_of_service and re.fullmatch(r"[0-9]{2}", place_of_service) is None) or (
                row.get("revenue_code") and re.fullmatch(r"[0-9]{4}", row["revenue_code"]) is None
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-CLN-005",
                    processed_at_utc,
                    "claim-line place-of-service or revenue-code format is invalid",
                )
        elif family == "payments":
            payment_date = _parse_date(row.get("payment_date", ""))
            posted = _parse_date(row.get("posted_at", ""))
            if payment_date is not None and posted is not None and payment_date > posted:
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-005",
                    processed_at_utc,
                    "payment date occurs after ledger posting",
                )
            pairs = (
                ("remittance_source_system", "remittance_id"),
                ("claim_line_number", "claim_line_id"),
                ("reverses_payment_source_system", "reverses_payment_id"),
            )
            if any(bool(row.get(left)) != bool(row.get(right)) for left, right in pairs):
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-012",
                    processed_at_utc,
                    "optional relationship pointer is only partially populated",
                )
            transaction = row.get("transaction_type")
            if transaction == "payer_payment" and not all(
                row.get(field)
                for field in ("remittance_source_system", "remittance_id", "payer_id")
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-006",
                    processed_at_utc,
                    "payer payment lacks complete remittance and payer evidence",
                )
            if transaction in {
                "contractual_adjustment",
                "write_off",
                "refund",
                "reversal",
            } and not row.get("adjustment_reason_code"):
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-007",
                    processed_at_utc,
                    "financial adjustment lacks a reason code",
                    "adjustment_reason_code",
                )
            posted_at = _parse_timestamp(row.get("posted_at", ""))
            if (
                item.record.source_system == "synthetic_billing_spreadsheet"
                and posted_at is not None
                and evaluation_time.astimezone(UTC) - posted_at
                > _duration(
                    catalog.for_identity(item.record.source_identity).freshness.maximum_source_age
                )
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-010",
                    processed_at_utc,
                    "valid billing-spreadsheet transaction arrived after the hourly target",
                )
        elif family == "denials":
            denial = _parse_date(row.get("denial_date", ""))
            received = _parse_date(row.get("received_at", ""))
            if denial is not None and received is not None and denial > received:
                _row_rule(
                    item,
                    catalog,
                    "DQ-DEN-005",
                    processed_at_utc,
                    "denial effective date occurs after receipt",
                )
            if row.get("documentation_ready_flag") == "true" and row.get("missing_document_codes"):
                _row_rule(
                    item,
                    catalog,
                    "DQ-DEN-008",
                    processed_at_utc,
                    "documentation cannot be ready while required documents are missing",
                )
            if bool(row.get("claim_line_number")) != bool(row.get("claim_line_id")):
                _row_rule(
                    item,
                    catalog,
                    "DQ-DEN-010",
                    processed_at_utc,
                    "claim-line denial pointer is only partially populated",
                )
            filing_deadline = _parse_date(row.get("filing_deadline_date", ""))
            appeal_deadline = _parse_date(row.get("appeal_deadline_date", ""))
            if denial is not None and (
                filing_deadline is None
                or appeal_deadline is None
                or filing_deadline < denial
                or appeal_deadline < denial
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-DEN-007",
                    processed_at_utc,
                    "denial deadlines are missing or precede the denial date",
                )
            if (
                row.get("denial_status") == "open"
                and appeal_deadline is not None
                and 0 <= (appeal_deadline - evaluation_time.astimezone(UTC).date()).days <= 7
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-DEN-009",
                    processed_at_utc,
                    "open denial is within seven days of its appeal deadline",
                )
        elif family == "remittances":
            if bool(row.get("reverses_remittance_source_system")) != bool(
                row.get("reverses_remittance_id")
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-REM-009",
                    processed_at_utc,
                    "remittance reversal pointer is only partially populated",
                )
            remittance_date = _parse_date(row.get("remittance_date", ""))
            received_at = _parse_timestamp(row.get("received_at", ""))
            maximum_age = _duration(
                catalog.for_identity(item.record.source_identity).freshness.maximum_source_age
            )
            if (
                remittance_date is not None
                and received_at is not None
                and (
                    remittance_date > received_at.date()
                    or received_at
                    - datetime.combine(remittance_date, datetime.min.time(), tzinfo=UTC)
                    > maximum_age + timedelta(days=1)
                )
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-REM-005",
                    processed_at_utc,
                    "remittance date is after receipt or outside the governed source window",
                )
        elif family == "appeals":
            created = _parse_timestamp(row.get("created_at", ""))
            filed = _parse_timestamp(row.get("filed_at", "")) if row.get("filed_at") else None
            decision = (
                _parse_date(row.get("decision_date", "")) if row.get("decision_date") else None
            )
            status = row.get("appeal_status")
            decided = status in {"overturned", "partially_overturned", "upheld", "withdrawn"}
            if (
                status
                in {
                    "filed",
                    "pending",
                    "overturned",
                    "partially_overturned",
                    "upheld",
                    "withdrawn",
                }
                and filed is None
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-APL-005",
                    processed_at_utc,
                    "filed or decided appeal state lacks filed_at",
                    "filed_at",
                )
            has_decision = decision is not None
            has_outcome = bool(row.get("outcome"))
            if (decided and not (has_decision and has_outcome)) or (
                not decided and (has_decision or has_outcome)
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-APL-006",
                    processed_at_utc,
                    "appeal decision fields contradict its workflow state",
                )
            if created is not None and (
                (filed is not None and filed < created)
                or (decision is not None and decision < created.date())
                or (filed is not None and decision is not None and decision < filed.date())
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-APL-012",
                    processed_at_utc,
                    "appeal event chronology is invalid",
                )
            if (
                status in {"ready_for_human_review", "filed"}
                and row.get("documentation_ready_flag") != "true"
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-APL-008",
                    processed_at_utc,
                    "appeal cannot advance without documentation readiness",
                )
            deadline = _parse_date(row.get("appeal_deadline_date", ""))
            if (
                status != "expired"
                and deadline is not None
                and (
                    (created is not None and created.date() > deadline)
                    or (filed is not None and filed.date() > deadline)
                )
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-APL-004",
                    processed_at_utc,
                    "appeal creation or filing occurred after the governed deadline",
                )
            if (
                filed is None
                and status != "expired"
                and deadline is not None
                and 0 <= (deadline - evaluation_time.astimezone(UTC).date()).days <= 7
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-APL-009",
                    processed_at_utc,
                    "unfiled appeal is within seven days of its deadline",
                )


def _apply_cross_record_semantics(
    evaluated: list[EvaluatedRecord], catalog: QualityCatalog, processed_at_utc: str
) -> None:
    for item in evaluated:
        if item.disposition not in {"accepted", "accepted_with_warning"}:
            continue
        row = item.record.normalized_payload
        identity = item.record.source_identity
        family = catalog.for_identity(identity).source_family
        if identity == "eligibility":
            plan = _parent(
                evaluated,
                "reference-data.plans",
                ("plan_id",),
                (row.get("plan_id", ""),),
            )
            if plan is not None and plan.record.normalized_payload.get("payer_id") != row.get(
                "payer_id"
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-ELG-004",
                    processed_at_utc,
                    "eligibility plan belongs to a different payer",
                )
            verification = _parse_date(row.get("verification_at", ""))
            coverage_start = _parse_date(row.get("coverage_start_date", ""))
            coverage_end = _parse_date(row.get("coverage_end_date", ""))
            if row.get("coverage_status") == "active" and (
                coverage_start is None
                or verification is None
                or verification < coverage_start
                or (coverage_end is not None and verification >= coverage_end)
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-ELG-006",
                    processed_at_utc,
                    "active eligibility is outside its coverage interval",
                )
        elif identity == "claims":
            if row.get("submission_type") in {"replacement", "void"}:
                original = _parent(
                    evaluated,
                    "claims",
                    ("source_system", "claim_id", "submission_sequence"),
                    (
                        row.get("original_claim_source_system", ""),
                        row.get("original_claim_id", ""),
                        row.get("original_submission_sequence", ""),
                    ),
                )
                current_sequence = _decimal(row.get("submission_sequence"))
                original_sequence = _decimal(row.get("original_submission_sequence"))
                if (
                    original is None
                    or row.get("original_claim_source_system") != item.record.source_system
                    or row.get("original_claim_id") != row.get("claim_id")
                    or current_sequence is None
                    or original_sequence is None
                    or original_sequence >= current_sequence
                ):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-CLM-010",
                        processed_at_utc,
                        "original claim is unresolved or is not an earlier submission of the "
                        "same claim",
                    )
            eligibility = _parent(
                evaluated,
                "eligibility",
                ("source_system", "eligibility_id"),
                (row.get("eligibility_source_system", ""), row.get("eligibility_id", "")),
            )
            if eligibility is not None:
                eligibility_row = eligibility.record.normalized_payload
                service_from = _parse_date(row.get("service_from_date", ""))
                service_to = _parse_date(row.get("service_to_date", ""))
                coverage_start = _parse_date(eligibility_row.get("coverage_start_date", ""))
                coverage_end = _parse_date(eligibility_row.get("coverage_end_date", ""))
                mismatch = (
                    any(
                        eligibility_row.get(field) != row.get(field)
                        for field in ("patient_id", "payer_id", "plan_id")
                    )
                    or eligibility_row.get("response_status") != "confirmed"
                    or eligibility_row.get("coverage_status") != "active"
                )
                if (
                    service_from is not None
                    and service_to is not None
                    and coverage_start is not None
                    and (
                        service_from < coverage_start
                        or (coverage_end is not None and service_to >= coverage_end)
                    )
                ):
                    mismatch = True
                if mismatch:
                    _row_rule(
                        item,
                        catalog,
                        "DQ-CLM-011",
                        processed_at_utc,
                        "linked eligibility does not cover the claim identity and service interval",
                    )
        elif identity == "claim-lines":
            claim = _parent(
                evaluated,
                "claims",
                ("source_system", "claim_id", "submission_sequence"),
                (
                    item.record.source_system,
                    row.get("claim_id", ""),
                    row.get("submission_sequence", ""),
                ),
            )
            if claim is not None:
                claim_row = claim.record.normalized_payload
                line_from = _parse_date(row.get("service_from_date", ""))
                line_to = _parse_date(row.get("service_to_date", ""))
                claim_from = _parse_date(claim_row.get("service_from_date", ""))
                claim_to = _parse_date(claim_row.get("service_to_date", ""))
                if None not in {line_from, line_to, claim_from, claim_to} and (
                    cast(date, line_from) < cast(date, claim_from)
                    or cast(date, line_to) > cast(date, claim_to)
                ):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-CLN-004",
                        processed_at_utc,
                        "claim-line service interval falls outside its parent claim",
                    )
        elif identity == "denials":
            reason = _parent(
                evaluated,
                "reference-data.denial-reasons",
                ("denial_reason_code",),
                (row.get("denial_reason_code", ""),),
            )
            if reason is not None and reason.record.normalized_payload.get(
                "denial_category"
            ) != row.get("denial_category"):
                _row_rule(
                    item,
                    catalog,
                    "DQ-DEN-004",
                    processed_at_utc,
                    "denial category disagrees with the effective reason mapping",
                )
            claim = _parent(
                evaluated,
                "claims",
                ("source_system", "claim_id", "submission_sequence"),
                (
                    row.get("claim_source_system", ""),
                    row.get("claim_id", ""),
                    row.get("claim_submission_sequence", ""),
                ),
            )
            if claim is not None:
                denial_date = _parse_date(row.get("denial_date", ""))
                service_from = _parse_date(
                    claim.record.normalized_payload.get("service_from_date", "")
                )
                submitted_at = _parse_date(claim.record.normalized_payload.get("submitted_at", ""))
                if denial_date is not None and (
                    (service_from is not None and denial_date < service_from)
                    or (submitted_at is not None and denial_date < submitted_at)
                ):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-DEN-005",
                        processed_at_utc,
                        "denial date precedes the related service or submission date",
                    )
                denied = _decimal(row.get("denied_amount"))
                exposure = _decimal(claim.record.normalized_payload.get("outstanding_balance"))
                if denied is None or denied <= 0 or (exposure is not None and denied > exposure):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-DEN-006",
                        processed_at_utc,
                        "denied amount exceeds the related outstanding exposure",
                    )
            if row.get("claim_line_id"):
                line = _parent(
                    evaluated,
                    "claim-lines",
                    ("source_system", "claim_id", "submission_sequence", "line_number"),
                    (
                        row.get("claim_source_system", ""),
                        row.get("claim_id", ""),
                        row.get("claim_submission_sequence", ""),
                        row.get("claim_line_number", ""),
                    ),
                )
                if line is not None and line.record.normalized_payload.get(
                    "claim_line_id"
                ) != row.get("claim_line_id"):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-DEN-003",
                        processed_at_utc,
                        "denial claim_line_id disagrees with the resolved claim line",
                    )
        elif identity == "appeals":
            denial = _parent(
                evaluated,
                "denials",
                ("source_system", "denial_id"),
                (row.get("denial_source_system", ""), row.get("denial_id", "")),
            )
            if denial is not None:
                denial_row = denial.record.normalized_payload
                if any(
                    denial_row.get(denial_field) != row.get(appeal_field)
                    for denial_field, appeal_field in (
                        ("claim_source_system", "claim_source_system"),
                        ("claim_id", "claim_id"),
                        ("claim_submission_sequence", "claim_submission_sequence"),
                    )
                ):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-APL-003",
                        processed_at_utc,
                        "resolved denial belongs to a different complete claim key",
                    )
                if denial_row.get("appeal_deadline_date") != row.get("appeal_deadline_date"):
                    _row_rule(
                        item,
                        catalog,
                        "DQ-APL-011",
                        processed_at_utc,
                        "appeal deadline disagrees with the parent denial",
                    )
                requested = _decimal(row.get("requested_amount"))
                denied = _decimal(denial_row.get("denied_amount"))
                if requested is not None and denied is not None and requested > denied:
                    _row_rule(
                        item,
                        catalog,
                        "DQ-APL-007",
                        processed_at_utc,
                        "appeal request exceeds the parent denied amount",
                    )
        elif family == "payments" and row.get("claim_line_id"):
            line = _parent(
                evaluated,
                "claim-lines",
                ("source_system", "claim_id", "submission_sequence", "line_number"),
                (
                    row.get("claim_source_system", ""),
                    row.get("claim_id", ""),
                    row.get("claim_submission_sequence", ""),
                    row.get("claim_line_number", ""),
                ),
            )
            if line is not None and line.record.normalized_payload.get("claim_line_id") != row.get(
                "claim_line_id"
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-003",
                    processed_at_utc,
                    "payment claim_line_id disagrees with the resolved line",
                )

        if identity == "eligibility" and (
            row.get("response_status") == "unknown" or row.get("coverage_status") == "unknown"
        ):
            dependent_claim = any(
                claim.disposition in {"accepted", "accepted_with_warning"}
                and claim.record.normalized_payload.get("eligibility_source_system")
                == item.record.source_system
                and claim.record.normalized_payload.get("eligibility_id")
                == row.get("eligibility_id")
                for claim in evaluated
                if claim.record.source_identity == "claims"
            )
            if not dependent_claim:
                _row_rule(
                    item,
                    catalog,
                    "DQ-ELG-008",
                    processed_at_utc,
                    "unknown eligibility response has no active dependent claim",
                )


def _payment_parent(
    evaluated: list[EvaluatedRecord], item: EvaluatedRecord
) -> EvaluatedRecord | None:
    row = item.record.normalized_payload
    return _parent(
        evaluated,
        "payments",
        ("source_system", "payment_id"),
        (row.get("reverses_payment_source_system", ""), row.get("reverses_payment_id", "")),
    )


def _same_payment_target(left: dict[str, str], right: dict[str, str]) -> bool:
    return all(
        left.get(field) == right.get(field)
        for field in (
            "claim_source_system",
            "claim_id",
            "claim_submission_sequence",
            "claim_line_number",
            "claim_line_id",
        )
    )


def _apply_payment_semantics(
    evaluated: list[EvaluatedRecord], catalog: QualityCatalog, processed_at_utc: str
) -> None:
    payment_records = [item for item in evaluated if item.record.source_identity == "payments"]
    for item in payment_records:
        if item.disposition not in {"accepted", "accepted_with_warning"}:
            continue
        row = item.record.normalized_payload
        transaction = row.get("transaction_type")
        has_pointer = bool(row.get("reverses_payment_source_system")) and bool(
            row.get("reverses_payment_id")
        )
        if transaction not in {"refund", "reversal"} and has_pointer:
            _row_rule(
                item,
                catalog,
                "DQ-PAY-008",
                processed_at_utc,
                "non-refund transaction contains an original-payment pointer",
            )
            continue
        if transaction in {"refund", "reversal"}:
            parent = _payment_parent(evaluated, item) if has_pointer else None
            parent_row = None if parent is None else parent.record.normalized_payload
            if (
                parent_row is None
                or parent is item
                or parent_row.get("direction") != "credit"
                or parent_row.get("transaction_type") in {"refund", "reversal"}
                or not _same_payment_target(row, parent_row)
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-008",
                    processed_at_utc,
                    "refund or reversal does not resolve to a compatible credit transaction",
                )

    reversals: dict[tuple[str, str], list[EvaluatedRecord]] = defaultdict(list)
    for item in _active(evaluated, "payments"):
        row = item.record.normalized_payload
        if row.get("transaction_type") in {"refund", "reversal"} and row.get("reverses_payment_id"):
            reversals[
                (
                    row.get("reverses_payment_source_system", ""),
                    row.get("reverses_payment_id", ""),
                )
            ].append(item)
    for key, children in reversals.items():
        parent = _parent(evaluated, "payments", ("source_system", "payment_id"), key)
        original_amount = (
            None if parent is None else _decimal(parent.record.normalized_payload.get("amount"))
        )
        reversed_amount = _money_sum(children, "amount")
        if original_amount is None or reversed_amount > original_amount:
            for child in children:
                _row_rule(
                    child,
                    catalog,
                    "DQ-PAY-008",
                    processed_at_utc,
                    "cumulative refund or reversal amount exceeds the original credit",
                )

    category_field = {
        "payer_payment": "payer_paid_amount",
        "patient_payment": "patient_paid_amount",
        "contractual_adjustment": "adjustment_amount",
        "write_off": "adjustment_amount",
    }
    grouped: dict[tuple[str, str, str, str, str], list[tuple[EvaluatedRecord, Decimal]]] = (
        defaultdict(list)
    )
    for item in _active(evaluated, "payments"):
        row = item.record.normalized_payload
        transaction = row.get("transaction_type", "")
        direction = row.get("direction")
        if direction == "debit":
            parent = _payment_parent(evaluated, item)
            if parent is None:
                continue
            transaction = parent.record.normalized_payload.get("transaction_type", "")
        field = category_field.get(transaction)
        amount = _decimal(row.get("amount"))
        if field is None or amount is None:
            continue
        payment_group_key = (
            row.get("claim_source_system", ""),
            row.get("claim_id", ""),
            row.get("claim_submission_sequence", ""),
            row.get("claim_line_number", ""),
            field,
        )
        grouped[payment_group_key].append((item, amount if direction == "credit" else -amount))
    for payment_group_key, values in grouped.items():
        source_system, claim_id, sequence, line_number, field = payment_group_key
        parent = (
            _parent(
                evaluated,
                "claim-lines",
                ("source_system", "claim_id", "submission_sequence", "line_number"),
                (source_system, claim_id, sequence, line_number),
            )
            if line_number
            else _parent(
                evaluated,
                "claims",
                ("source_system", "claim_id", "submission_sequence"),
                (source_system, claim_id, sequence),
            )
        )
        eligible = None if parent is None else _decimal(parent.record.normalized_payload.get(field))
        applied = sum((value for _, value in values), Decimal("0"))
        if eligible is None or applied < 0 or applied > eligible:
            for item, _ in values:
                _row_rule(
                    item,
                    catalog,
                    "DQ-PAY-009",
                    processed_at_utc,
                    "signed financial transactions exceed the eligible claim or line amount",
                )


def _apply_remittance_reversal_semantics(
    evaluated: list[EvaluatedRecord], catalog: QualityCatalog, processed_at_utc: str
) -> None:
    for item in _active(evaluated, "remittances"):
        row = item.record.normalized_payload
        has_pointer = bool(row.get("reverses_remittance_source_system")) and bool(
            row.get("reverses_remittance_id")
        )
        if row.get("remittance_status") != "reversed" and has_pointer:
            _row_rule(
                item,
                catalog,
                "DQ-REM-008",
                processed_at_utc,
                "non-reversed remittance contains an original-remittance pointer",
            )
            continue
        if row.get("remittance_status") == "reversed":
            parent = (
                _parent(
                    evaluated,
                    "remittances",
                    ("source_system", "remittance_id"),
                    (
                        row.get("reverses_remittance_source_system", ""),
                        row.get("reverses_remittance_id", ""),
                    ),
                )
                if has_pointer
                else None
            )
            parent_row = None if parent is None else parent.record.normalized_payload
            if (
                parent_row is None
                or parent is item
                or parent_row.get("direction") != "credit"
                or any(
                    parent_row.get(field) != row.get(field)
                    for field in (
                        "payer_id",
                        "currency_code",
                        "claim_transaction_count",
                        "total_payment_amount",
                    )
                )
            ):
                _row_rule(
                    item,
                    catalog,
                    "DQ-REM-008",
                    processed_at_utc,
                    "reversed remittance does not exactly offset a compatible credit remittance",
                )


def _money_sum(records: list[EvaluatedRecord], field: str) -> Decimal:
    return sum(
        (
            value
            for item in records
            if (value := _decimal(item.record.normalized_payload.get(field))) is not None
        ),
        Decimal("0"),
    )


def _batch_controls(
    evaluated: list[EvaluatedRecord], catalog: QualityCatalog, processed_at_utc: str
) -> list[QualityIssue]:
    findings: list[QualityIssue] = []
    lines_by_claim: dict[tuple[str, str, str], list[EvaluatedRecord]] = defaultdict(list)
    for line in _active(evaluated, "claim-lines"):
        row = line.record.normalized_payload
        lines_by_claim[
            (line.record.source_system, row.get("claim_id", ""), row.get("submission_sequence", ""))
        ].append(line)
    amount_fields = (
        "billed_amount",
        "payer_paid_amount",
        "patient_paid_amount",
        "adjustment_amount",
        "outstanding_balance",
    )
    for claim in _active(evaluated, "claims"):
        row = claim.record.normalized_payload
        key = (
            claim.record.source_system,
            row.get("claim_id", ""),
            row.get("submission_sequence", ""),
        )
        lines = lines_by_claim.get(key, [])
        if lines and any(
            _decimal(row.get(field)) != _money_sum(lines, field) for field in amount_fields
        ):
            findings.append(
                _issue(
                    catalog.batch_rules["reconciliation"],
                    processed_at_utc=processed_at_utc,
                    source_identity="claim-lines",
                    reason=(
                        "claim-line financial rollup does not reconcile for claim "
                        f"{claim.record.source_record_id}"
                    ),
                )
            )

    payments_by_remit: dict[tuple[str, str], list[EvaluatedRecord]] = defaultdict(list)
    for payment in _active(evaluated, "payments"):
        row = payment.record.normalized_payload
        if row.get("remittance_source_system") and row.get("remittance_id"):
            payments_by_remit[(row["remittance_source_system"], row["remittance_id"])].append(
                payment
            )
    remittance_rule = catalog.rule_for("remittances", "DQ-REM-006")
    for remittance in _active(evaluated, "remittances"):
        row = remittance.record.normalized_payload
        remittance_key = (remittance.record.source_system, row.get("remittance_id", ""))
        payments = payments_by_remit.get(remittance_key, [])
        signed_total = sum(
            (
                cast(Decimal, _decimal(item.record.normalized_payload.get("amount")))
                * (
                    Decimal("1")
                    if item.record.normalized_payload.get("direction") == "credit"
                    else Decimal("-1")
                )
                for item in payments
                if _decimal(item.record.normalized_payload.get("amount")) is not None
            ),
            Decimal("0"),
        )
        expected = _decimal(row.get("total_payment_amount"))
        if row.get("direction") == "debit" and expected is not None:
            expected = -expected
        expected_count = int(row.get("claim_transaction_count", "-1"))
        if expected is None or signed_total != expected or len(payments) != expected_count:
            findings.append(
                _issue(
                    remittance_rule,
                    processed_at_utc=processed_at_utc,
                    source_identity="remittances",
                    reason=(
                        "accepted payment count or signed amount does not reconcile to "
                        f"remittance {remittance.record.source_record_id}"
                    ),
                )
            )
    return findings


def _freshness(
    evaluated: list[EvaluatedRecord],
    catalog: QualityCatalog,
    present_identities: set[str],
    evaluation_time: datetime,
    batch_generated_at: datetime,
    processed_at_utc: str,
) -> tuple[list[QualityIssue], dict[str, tuple[FreshnessStatus, int | None]]]:
    findings: list[QualityIssue] = []
    evidence: dict[str, tuple[FreshnessStatus, int | None]] = {}
    for identity in sorted(present_identities):
        contract = catalog.for_identity(identity)
        event_times = [
            parsed
            for item in evaluated
            if item.record.source_identity == identity
            and (
                parsed := _parse_timestamp(
                    item.record.normalized_payload.get(contract.freshness.event_field, "")
                )
            )
            is not None
        ]
        latest = max(event_times, default=batch_generated_at)
        age = max(evaluation_time - latest, timedelta(0))
        observed = int(age.total_seconds())
        status: FreshnessStatus = (
            "late" if age > _duration(contract.freshness.maximum_source_age) else "current"
        )
        evidence[identity] = (status, observed)
        if status == "late":
            findings.append(
                _issue(
                    catalog.freshness_rule,
                    processed_at_utc=processed_at_utc,
                    source_identity=identity,
                    reason=(
                        f"source age {observed}s exceeds {contract.freshness.maximum_source_age}"
                    ),
                )
            )
    return findings, evidence


def evaluate_quality(
    records: tuple[QualityRecord, ...],
    catalog: QualityCatalog,
    *,
    present_identities: set[str],
    evaluation_time: datetime,
    batch_generated_at: datetime,
) -> QualityEvaluation:
    """Apply Phase 3 rules and produce one reconciled, fail-closed gate decision."""

    if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
        raise ValueError("quality evaluation time must be timezone-aware")
    if batch_generated_at.tzinfo is None or batch_generated_at.utcoffset() is None:
        raise ValueError("batch generated time must be timezone-aware")
    processed_at_utc = evaluation_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
    evaluated = [_initial(record, processed_at_utc) for record in records]
    _apply_reference_semantics(evaluated, catalog, processed_at_utc)
    _apply_temporal_and_pair_rules(evaluated, catalog, evaluation_time, processed_at_utc)
    _apply_relationships(evaluated, catalog, processed_at_utc)
    _apply_cross_record_semantics(evaluated, catalog, processed_at_utc)
    _apply_payment_semantics(evaluated, catalog, processed_at_utc)
    _apply_remittance_reversal_semantics(evaluated, catalog, processed_at_utc)
    _apply_relationships(evaluated, catalog, processed_at_utc)

    missing = set(catalog.identities()) - present_identities
    batch_findings = [
        _issue(
            catalog.batch_rules["missing_source"],
            processed_at_utc=processed_at_utc,
            reason=f"required source identity is absent: {identity}",
            source_identity=identity,
        )
        for identity in sorted(missing)
    ]
    unknown = present_identities - set(catalog.identities())
    if unknown:
        batch_findings.append(
            _issue(
                catalog.batch_rules["missing_source"],
                processed_at_utc=processed_at_utc,
                reason=f"unapproved source identities are present: {sorted(unknown)}",
            )
        )
    batch_findings.extend(_batch_controls(evaluated, catalog, processed_at_utc))
    if any(item.disposition == "rejected" for item in evaluated):
        batch_findings.append(
            _issue(
                catalog.batch_rules["critical_outcome"],
                processed_at_utc=processed_at_utc,
                reason="one or more source rows has a critical rejected disposition",
            )
        )

    source_findings, freshness = _freshness(
        evaluated,
        catalog,
        present_identities & set(catalog.identities()),
        evaluation_time.astimezone(UTC),
        batch_generated_at.astimezone(UTC),
        processed_at_utc,
    )
    summaries: list[SourceQualitySummary] = []
    for identity in sorted(present_identities & set(catalog.identities())):
        source_records = [item for item in evaluated if item.record.source_identity == identity]
        counts = Counter(item.disposition for item in source_records)
        status, observed = freshness.get(identity, ("not_evaluable", None))
        summary = SourceQualitySummary(
            source_identity=identity,
            raw_rows=len(source_records),
            accepted=counts["accepted"],
            warned=counts["accepted_with_warning"],
            quarantined=counts["quarantined"],
            rejected=counts["rejected"],
            issue_count=sum(len(item.issues) for item in source_records),
            freshness_status=status,
            maximum_source_age=catalog.for_identity(identity).freshness.maximum_source_age,
            observed_source_age_seconds=observed,
        )
        summaries.append(summary)
        if summary.disposition_rows != summary.raw_rows:
            batch_findings.append(
                _issue(
                    catalog.batch_rules["reconciliation"],
                    processed_at_utc=processed_at_utc,
                    source_identity=identity,
                    reason="source disposition counts do not reconcile to raw rows",
                )
            )
    reconciled = sum(summary.raw_rows for summary in summaries) == len(evaluated) and all(
        summary.disposition_rows == summary.raw_rows for summary in summaries
    )
    if not reconciled:
        batch_findings.append(
            _issue(
                catalog.batch_rules["reconciliation"],
                processed_at_utc=processed_at_utc,
                reason="batch disposition counts do not reconcile to immutable raw rows",
            )
        )
    return QualityEvaluation(
        records=tuple(evaluated),
        source_summaries=tuple(summaries),
        source_findings=tuple(source_findings),
        batch_findings=tuple(batch_findings),
        reconciled=reconciled,
    )
