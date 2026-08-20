"""Immutable local service for Phase 3 quality, quarantine, and gate evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast

from claimsflow.adapters.local_registry import SqliteIngestionRegistry
from claimsflow.domain.ingestion import IngestionResult, ValidationIssue
from claimsflow.domain.quality import (
    QualityCorrection,
    QualityReceiptCollisionError,
    QualityRunReceipt,
    QualityRunResult,
)
from claimsflow.ingestion.contracts import ContractCatalog, ContractLoadError
from claimsflow.ingestion.validation import (
    INGESTION_SOURCE_RULE_IDS,
    ProvenanceViolation,
    classify_row,
    payload_sha256,
    verify_reserved_synthetic_values,
)
from claimsflow.quality.catalog import QualityCatalog, QualityCatalogError
from claimsflow.quality.engine import (
    PHASE3_SEMANTIC_RULE_IDS,
    EvaluatedRecord,
    QualityEvaluation,
    QualityRecord,
    evaluate_quality,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_INGESTION_REPORT = Path("audit/ingestion-report.json")
_QUALITY_REPORT = Path("audit/quality-report.json")
_IMPLEMENTATION_FILES = (
    ("quality/service.py", Path(__file__)),
    ("quality/engine.py", Path(__file__).with_name("engine.py")),
    ("quality/catalog.py", Path(__file__).with_name("catalog.py")),
    ("domain/quality.py", Path(__file__).parents[1] / "domain/quality.py"),
)


class QualityValidationError(RuntimeError):
    """Raised when Phase 3 evidence cannot be produced without ambiguity."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _duration(value: str) -> timedelta:
    match = re.fullmatch(r"PT(?:(?P<hours>[0-9]+)H)?(?:(?P<minutes>[0-9]+)M)?", value)
    if match is None:
        raise QualityValidationError(f"unsupported evaluation interval: {value}")
    duration = timedelta(
        hours=int(match.group("hours") or 0), minutes=int(match.group("minutes") or 0)
    )
    if duration <= timedelta(0):
        raise QualityValidationError("evaluation interval must be positive")
    return duration


def _evaluation_window(value: datetime, interval: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QualityValidationError("quality clock must return a timezone-aware timestamp")
    seconds = int(_duration(interval).total_seconds())
    epoch = int(value.astimezone(UTC).timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


def _configuration_evidence(catalog: QualityCatalog) -> dict[str, object]:
    implementation = [
        {"component": component, "sha256": _sha256(path)}
        for component, path in _IMPLEMENTATION_FILES
    ]
    evidence: dict[str, object] = {
        "rule_version": catalog.rule_version,
        "policy_sha256": catalog.policy_sha256,
        "contracts": list(catalog.contract_inventory()),
        "implementation": implementation,
    }
    evidence["configuration_sha256"] = _canonical_hash(evidence)
    return evidence


def _rule_execution_inventory(catalog: QualityCatalog) -> dict[str, list[str]]:
    identities = catalog.identities()
    governed = {
        (identity, rule.rule_id)
        for identity in identities
        for rule in catalog.for_identity(identity).rules
    }

    inherited = {
        (identity, rule.rule_id)
        for identity in identities
        for rule in catalog.for_identity(identity).rules
        if rule.rule_id in INGESTION_SOURCE_RULE_IDS
        or rule.rule_id
        in {
            catalog.for_identity(identity).required_rule_id,
            catalog.for_identity(identity).duplicate_rule_id,
        }
    }
    relationships = {
        (identity, relationship.rule.rule_id)
        for identity in identities
        for relationship in catalog.for_identity(identity).relationships
    }
    semantics = {pair for pair in governed if pair[1] in PHASE3_SEMANTIC_RULE_IDS}
    batch_rule_ids = {rule.rule_id for rule in catalog.batch_rules.values()}
    batch = {pair for pair in governed if pair[1] in batch_rule_ids}
    boundary = {("appeals", "DQ-APL-010")}
    reference_identities = {
        identity for identity in identities if identity.startswith("reference-data.")
    }
    not_applicable = {
        (identity, "DQ-REF-006") for identity in reference_identities - {"reference-data.plans"}
    } | {
        (identity, "DQ-REF-007")
        for identity in reference_identities
        - {"reference-data.payers", "reference-data.denial-reasons"}
    }

    semantics -= not_applicable
    relationships -= semantics | not_applicable
    batch -= semantics | relationships | not_applicable
    boundary -= semantics | relationships | batch | not_applicable
    inherited -= semantics | relationships | batch | boundary | not_applicable
    covered = inherited | relationships | semantics | batch | boundary | not_applicable
    missing = governed - covered
    unexpected = covered - governed
    implementation_rule_ids = (
        set(INGESTION_SOURCE_RULE_IDS)
        | set(PHASE3_SEMANTIC_RULE_IDS)
        | batch_rule_ids
        | {"DQ-APL-010"}
    )
    unknown = (
        implementation_rule_ids
        - set(catalog.all_rule_ids())
        - {
            "DQ-CMN-006",
            "DQ-CMN-016",
        }
    )
    if missing or unexpected or unknown:
        raise QualityValidationError(
            f"quality source-rule execution inventory is incomplete: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)} "
            f"unknown={sorted(unknown)}"
        )

    def evidence(pairs: set[tuple[str, str]]) -> list[str]:
        return [f"{identity}|{rule_id}" for identity, rule_id in sorted(pairs)]

    return {
        "ingestion_reverified": evidence(inherited),
        "phase3_relationship": evidence(relationships),
        "phase3_semantic": evidence(semantics),
        "phase3_batch": evidence(batch),
        "closed_schema_boundary": evidence(boundary),
        "not_applicable": evidence(not_applicable),
    }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QualityValidationError("quality clock must return a timezone-aware timestamp")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise QualityValidationError(f"{label} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise QualityValidationError(f"{label} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualityValidationError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _verified_relative_file(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise QualityValidationError("ingestion artifact path must be a string")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise QualityValidationError("ingestion report contains an unsafe artifact path")
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise QualityValidationError(f"ingestion artifact is missing or unsafe: {value}")
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise QualityValidationError(f"ingestion artifact escapes its batch directory: {value}")
    return path


def _inventory(root: Path, excluded_report: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise QualityValidationError(f"artifact inventory contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise QualityValidationError(f"artifact inventory contains an unsafe file: {path}")
        relative = path.relative_to(root)
        if relative == excluded_report:
            continue
        items.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256(path),
                "byte_size": path.stat().st_size,
            }
        )
    return items


def _verified_ingestion_report(result: IngestionResult) -> dict[str, Any]:
    root = result.artifact_directory
    if root.is_symlink() or not root.is_dir():
        raise QualityValidationError("ingestion artifact directory is missing or unsafe")
    expected_report = root / _INGESTION_REPORT
    if (
        result.report_path != expected_report
        or expected_report.is_symlink()
        or not expected_report.is_file()
    ):
        raise QualityValidationError("ingestion report path is missing or non-canonical")
    if (
        _SHA256.fullmatch(result.report_sha256) is None
        or _sha256(expected_report) != result.report_sha256
    ):
        raise QualityValidationError("ingestion report checksum changed")
    try:
        value = json.loads(expected_report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualityValidationError("ingestion report cannot be read") from error
    if not isinstance(value, dict):
        raise QualityValidationError("ingestion report root must be an object")
    report = cast(dict[str, Any], value)
    if (
        report.get("synthetic_only") is not True
        or report.get("batch_id") != result.batch_id
        or report.get("source_manifest_sha256") != result.manifest_sha256
    ):
        raise QualityValidationError("ingestion report contradicts the synthetic batch identity")
    if report.get("artifact_inventory") != _inventory(root, _INGESTION_REPORT):
        raise QualityValidationError("ingestion artifact inventory no longer matches its report")
    reconciliation = report.get("reconciliation")
    if not isinstance(reconciliation, dict) or reconciliation.get("reconciled") is not True:
        raise QualityValidationError("ingestion must reconcile before Phase 3 validation")
    if (
        result.decision != "processed"
        or result.reconciled is not True
        or result.processed_files != result.file_count
        or result.duplicate_files != 0
        or result.duplicate_no_op_rows != 0
        or result.raw_rows != result.declared_rows
        or reconciliation.get("raw_rows") != result.raw_rows
    ):
        raise QualityValidationError(
            "Phase 3 requires a fully processed batch with no duplicate-only files"
        )
    return report


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise QualityValidationError(
                        f"raw evidence line {line_number} is not an object: {path.name}"
                    )
                values.append(cast(dict[str, Any], value))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualityValidationError(f"raw evidence cannot be read: {path.name}") from error
    return values


def _validation_issue(value: object) -> ValidationIssue:
    if not isinstance(value, dict):
        raise QualityValidationError("raw issue evidence must be an object")
    item = cast(dict[str, Any], value)
    try:
        return ValidationIssue(
            rule_id=cast(str, item["rule_id"]),
            severity=cast(Any, item["severity"]),
            disposition=cast(Any, item["disposition"]),
            reason=cast(str, item["reason"]),
            field=cast(str | None, item.get("field")),
            normalized_value=cast(str | None, item.get("normalized_value")),
        )
    except KeyError as error:
        raise QualityValidationError("raw issue evidence is incomplete") from error


def _quality_record(value: dict[str, Any], expected_identity: str, batch_id: str) -> QualityRecord:
    lineage = value.get("lineage")
    original = value.get("raw_payload")
    normalized = value.get("normalized_payload")
    issues = value.get("issues")
    if (
        value.get("synthetic_only") is not True
        or not isinstance(lineage, dict)
        or not isinstance(original, dict)
        or not isinstance(normalized, dict)
        or not isinstance(issues, list)
        or lineage.get("batch_id") != batch_id
        or lineage.get("source_identity") != expected_identity
    ):
        raise QualityValidationError("raw envelope is incomplete or contradicts its file evidence")
    source_system = lineage.get("source_system")
    required_strings = {
        "source_system": source_system,
        "source_record_id": value.get("source_record_id"),
        "natural_key": value.get("natural_key"),
        "payload_sha256": value.get("payload_sha256"),
        "disposition": value.get("disposition"),
    }
    if any(not isinstance(item, str) for item in required_strings.values()):
        raise QualityValidationError("raw envelope identity evidence is incomplete")
    if _SHA256.fullmatch(cast(str, required_strings["payload_sha256"])) is None:
        raise QualityValidationError("raw envelope payload checksum is invalid")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in original.items()):
        raise QualityValidationError("raw payload must contain only string values")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in normalized.items()):
        raise QualityValidationError("normalized payload must contain only string values")
    if payload_sha256(cast(dict[str, str], original)) != required_strings["payload_sha256"]:
        raise QualityValidationError("raw envelope payload checksum does not match its payload")
    disposition = cast(str, required_strings["disposition"])
    if disposition not in {"accepted", "accepted_with_warning", "quarantined", "rejected"}:
        raise QualityValidationError("raw envelope disposition is unsupported")
    return QualityRecord(
        source_identity=expected_identity,
        source_system=cast(str, source_system),
        source_record_id=cast(str, value["source_record_id"]),
        natural_key=cast(str, value["natural_key"]),
        payload_sha256=cast(str, value["payload_sha256"]),
        original_payload=cast(dict[str, str], original),
        normalized_payload=cast(dict[str, str], normalized),
        preliminary_disposition=cast(Any, disposition),
        preliminary_issues=tuple(_validation_issue(item) for item in issues),
        lineage=cast(dict[str, object], lineage),
    )


def _load_records(
    result: IngestionResult, report: dict[str, Any], catalog: QualityCatalog
) -> tuple[tuple[QualityRecord, ...], set[str]]:
    files = report.get("files")
    if not isinstance(files, list) or len(files) != result.file_count:
        raise QualityValidationError("ingestion report files are missing")
    records: list[QualityRecord] = []
    identities: set[str] = set()
    for raw_file in files:
        if not isinstance(raw_file, dict):
            raise QualityValidationError("ingestion report contains an invalid file entry")
        file_item = cast(dict[str, Any], raw_file)
        identity = file_item.get("source_identity")
        artifacts = file_item.get("artifacts")
        counts = file_item.get("counts")
        if (
            not isinstance(identity, str)
            or identity in identities
            or not isinstance(artifacts, dict)
            or not isinstance(counts, dict)
            or file_item.get("decision") != "processed"
        ):
            raise QualityValidationError("Phase 3 requires one processed file per source identity")
        source_contract = catalog.for_identity(identity)
        if (
            file_item.get("contract_id") != source_contract.contract_id
            or file_item.get("contract_version") != source_contract.contract_version
        ):
            raise QualityValidationError(
                f"ingestion contract evidence contradicts current configuration for {identity}"
            )
        identities.add(identity)
        raw_path = _verified_relative_file(result.artifact_directory, artifacts.get("raw"))
        source_records = [
            _quality_record(value, identity, result.batch_id)
            for value in _read_json_lines(raw_path)
        ]
        if counts.get("raw") != len(source_records):
            raise QualityValidationError(f"raw evidence count does not reconcile for {identity}")
        records.extend(source_records)
    if len(records) != result.raw_rows:
        raise QualityValidationError(
            "loaded raw evidence does not reconcile to the ingestion result"
        )
    return tuple(records), identities


def _validate_correction(correction: QualityCorrection) -> None:
    for label, value in (
        ("correction_id", correction.correction_id),
        ("source_identity", correction.source_identity),
        ("actor_source", correction.actor_source),
    ):
        if _SAFE_ID.fullmatch(value) is None:
            raise QualityValidationError(f"correction {label} is unsafe")
    if not correction.source_record_id or len(correction.source_record_id) > 4096:
        raise QualityValidationError("correction source_record_id is invalid")
    if not correction.actor_source.startswith("synthetic_"):
        raise QualityValidationError("correction actor_source must remain explicitly synthetic")
    if _SHA256.fullmatch(correction.expected_payload_sha256) is None:
        raise QualityValidationError("correction expected payload checksum is invalid")
    if not correction.reason.strip():
        raise QualityValidationError("correction reason must not be blank")
    _parse_timestamp(correction.corrected_at_utc, "correction corrected_at_utc")


def _apply_corrections(
    records: tuple[QualityRecord, ...],
    corrections: tuple[QualityCorrection, ...],
    contracts_directory: Path,
) -> tuple[tuple[QualityRecord, ...], list[dict[str, object]]]:
    if not corrections:
        return records, []
    try:
        catalog = ContractCatalog.load(contracts_directory)
    except ContractLoadError as error:
        raise QualityValidationError(str(error)) from error
    target_counts = Counter((item.source_identity, item.source_record_id) for item in records)
    by_key = {(item.source_identity, item.source_record_id): item for item in records}
    revised = list(records)
    positions = {
        (item.source_identity, item.source_record_id): index for index, item in enumerate(records)
    }
    correction_ids: set[str] = set()
    correction_targets: set[tuple[str, str]] = set()
    history: list[dict[str, object]] = []
    for correction in corrections:
        _validate_correction(correction)
        if correction.correction_id in correction_ids:
            raise QualityValidationError("correction IDs must be unique")
        correction_ids.add(correction.correction_id)
        key = (correction.source_identity, correction.source_record_id)
        if key in correction_targets:
            raise QualityValidationError("corrections may target each raw record at most once")
        correction_targets.add(key)
        original = by_key.get(key)
        if original is None or target_counts[key] != 1:
            raise QualityValidationError("correction does not identify exactly one raw record")
        if original.payload_sha256 != correction.expected_payload_sha256:
            raise QualityValidationError("correction expected checksum does not match raw evidence")
        contract = catalog.for_identity(correction.source_identity)
        if set(correction.revised_payload) != set(contract.columns):
            raise QualityValidationError(
                "correction revised payload must contain the exact source schema"
            )
        try:
            verify_reserved_synthetic_values(
                contract,
                correction.revised_payload,
                original.source_system,
                cast(int, original.lineage.get("source_row_number", 0)),
            )
        except ProvenanceViolation as error:
            raise QualityValidationError(str(error)) from error
        classified = classify_row(
            contract, correction.revised_payload, original.source_system, False
        )
        revised_record = QualityRecord(
            source_identity=original.source_identity,
            source_system=original.source_system,
            source_record_id=classified.source_record_id,
            natural_key=classified.natural_key,
            payload_sha256=classified.payload_sha256,
            original_payload=original.original_payload,
            normalized_payload=classified.normalized_payload,
            preliminary_disposition=classified.disposition,
            preliminary_issues=classified.issues,
            lineage=original.lineage,
            correction_id=correction.correction_id,
        )
        revised[positions[key]] = revised_record
        history.append(
            {
                "correction_id": correction.correction_id,
                "source_identity": correction.source_identity,
                "original_source_record_id": correction.source_record_id,
                "revised_source_record_id": classified.source_record_id,
                "original_payload_sha256": original.payload_sha256,
                "revised_payload_sha256": classified.payload_sha256,
                "actor_source": correction.actor_source,
                "reason": correction.reason,
                "corrected_at_utc": correction.corrected_at_utc,
                "original_payload": original.original_payload,
                "revised_payload": correction.revised_payload,
            }
        )
    return _enforce_post_correction_uniqueness(tuple(revised), catalog), history


def _enforce_post_correction_uniqueness(
    records: tuple[QualityRecord, ...], catalog: ContractCatalog
) -> tuple[QualityRecord, ...]:
    natural_counts = Counter((item.source_identity, item.natural_key) for item in records)
    record_id_counts = Counter(
        (item.source_identity, item.source_system, item.source_record_id) for item in records
    )
    claim_line_counts = Counter(
        (item.source_system, item.normalized_payload.get("claim_line_id", ""))
        for item in records
        if item.source_identity == "claim-lines" and item.normalized_payload.get("claim_line_id")
    )
    remittance_control_counts = Counter(
        (item.source_system, item.normalized_payload.get("source_control_number", ""))
        for item in records
        if item.source_identity == "remittances"
        and item.normalized_payload.get("remittance_status") != "reversed"
        and item.normalized_payload.get("source_control_number")
    )
    remittance_trace_counts = Counter(
        (item.source_system, item.normalized_payload.get("payment_trace_number", ""))
        for item in records
        if item.source_identity == "remittances"
        and item.normalized_payload.get("remittance_status") != "reversed"
        and item.normalized_payload.get("payment_trace_number")
    )
    result: list[QualityRecord] = []
    for item in records:
        duplicate = (
            natural_counts[(item.source_identity, item.natural_key)] > 1
            or record_id_counts[(item.source_identity, item.source_system, item.source_record_id)]
            > 1
        )
        if item.source_identity == "claim-lines" and item.normalized_payload.get("claim_line_id"):
            duplicate = (
                duplicate
                or claim_line_counts[(item.source_system, item.normalized_payload["claim_line_id"])]
                > 1
            )
        if (
            item.source_identity == "remittances"
            and item.normalized_payload.get("remittance_status") != "reversed"
        ):
            duplicate = (
                duplicate
                or remittance_control_counts[
                    (item.source_system, item.normalized_payload.get("source_control_number", ""))
                ]
                > 1
                or remittance_trace_counts[
                    (item.source_system, item.normalized_payload.get("payment_trace_number", ""))
                ]
                > 1
            )
        if not duplicate:
            result.append(item)
            continue
        contract = catalog.for_identity(item.source_identity)
        if any(issue.rule_id == contract.duplicate_rule_id for issue in item.preliminary_issues):
            result.append(item)
            continue
        duplicate_issue = ValidationIssue(
            rule_id=contract.duplicate_rule_id,
            severity="critical",
            disposition="rejected",
            reason="duplicate key exists after applying the complete correction set",
        )
        result.append(
            replace(
                item,
                preliminary_disposition="rejected",
                preliminary_issues=(*item.preliminary_issues, duplicate_issue),
            )
        )
    return tuple(result)


def _record_output(item: EvaluatedRecord) -> dict[str, object]:
    return {
        "synthetic_only": True,
        "lineage": item.record.lineage,
        "source_record_id": item.record.source_record_id,
        "natural_key": item.record.natural_key,
        "evaluated_payload_sha256": item.record.payload_sha256,
        "correction_id": item.record.correction_id,
        "disposition": item.disposition,
        "issues": [issue.as_dict() for issue in item.issues],
        "original_payload": item.record.original_payload,
        "normalized_payload": item.record.normalized_payload,
    }


def _json_lines_bytes(values: list[dict[str, object]]) -> bytes:
    return "".join(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n" for value in values
    ).encode("utf-8")


def _write_json_lines(path: Path, values: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_lines_bytes(values))


def _artifact_values(
    evaluation: QualityEvaluation, correction_history: list[dict[str, object]]
) -> dict[Path, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {
        "validated": [],
        "quarantine": [],
        "rejected": [],
    }
    for item in evaluation.records:
        destination = (
            "validated"
            if item.disposition in {"accepted", "accepted_with_warning"}
            else "quarantine"
            if item.disposition == "quarantined"
            else "rejected"
        )
        grouped[destination].append(_record_output(item))
    all_issues = [issue.as_dict() for item in evaluation.records for issue in item.issues]
    all_issues.extend(issue.as_dict() for issue in evaluation.source_findings)
    all_issues.extend(issue.as_dict() for issue in evaluation.batch_findings)
    return {
        Path("validated/records.jsonl"): grouped["validated"],
        Path("quarantine/records.jsonl"): grouped["quarantine"],
        Path("rejected/records.jsonl"): grouped["rejected"],
        Path("quality/issues.jsonl"): all_issues,
        Path("corrections/history.jsonl"): correction_history,
    }


def _expected_inventory(
    artifacts: dict[Path, list[dict[str, object]]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted(artifacts):
        content = _json_lines_bytes(artifacts[path])
        result.append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
            }
        )
    return result


def _report_value(
    *,
    result: IngestionResult,
    validation_id: str,
    catalog: QualityCatalog,
    evaluation: QualityEvaluation,
    evaluated_at_utc: str,
    evaluation_interval: str,
    configuration: dict[str, object],
    rule_inventory: dict[str, list[str]],
    corrections_sha256: str,
    correction_count: int,
    artifact_inventory: list[dict[str, object]],
) -> dict[str, object]:
    counts = Counter(item.disposition for item in evaluation.records)
    blocking = len(evaluation.batch_findings)
    publication_allowed = evaluation.reconciled and blocking == 0
    failed_rules = Counter(issue.rule_id for item in evaluation.records for issue in item.issues)
    failed_rules.update(issue.rule_id for issue in evaluation.source_findings)
    failed_rules.update(issue.rule_id for issue in evaluation.batch_findings)
    return {
        "schema_version": "1.0.0",
        "validation_id": validation_id,
        "rule_version": catalog.rule_version,
        "batch_id": result.batch_id,
        "synthetic_only": True,
        "evaluated_at_utc": evaluated_at_utc,
        "evaluation_interval": evaluation_interval,
        "evaluation_window_started_at_utc": evaluated_at_utc,
        "input_ingestion_report_sha256": result.report_sha256,
        "configuration": configuration,
        "corrections_sha256": corrections_sha256,
        "correction_count": correction_count,
        "decision": "approved" if publication_allowed else "blocked",
        "publication_allowed": publication_allowed,
        "rule_execution_manifest": {
            "structural_and_type": "inherited_and_verified",
            "temporal_and_pair": "executed",
            "cross_source_relationship": "executed",
            "effective_reference": "executed",
            "financial_reconciliation": "executed",
            "freshness": "executed",
            "correction_history": "executed",
            "publication_gate": "executed",
            "source_rule_inventory": rule_inventory,
        },
        "sources": [
            {
                "source_identity": source.source_identity,
                "counts": {
                    "raw": source.raw_rows,
                    "accepted": source.accepted,
                    "warned": source.warned,
                    "quarantined": source.quarantined,
                    "rejected": source.rejected,
                    "reconciled": source.raw_rows == source.disposition_rows,
                },
                "issue_count": source.issue_count,
                "freshness": {
                    "status": source.freshness_status,
                    "maximum_source_age": source.maximum_source_age,
                    "observed_source_age_seconds": source.observed_source_age_seconds,
                },
            }
            for source in evaluation.source_summaries
        ],
        "reconciliation": {
            "raw_rows": len(evaluation.records),
            "accepted": counts["accepted"],
            "warned": counts["accepted_with_warning"],
            "quarantined": counts["quarantined"],
            "rejected": counts["rejected"],
            "disposition_rows": sum(counts.values()),
            "reconciled": evaluation.reconciled,
        },
        "quality_summary": {
            "row_issue_count": sum(len(item.issues) for item in evaluation.records),
            "source_finding_count": len(evaluation.source_findings),
            "blocking_issue_count": blocking,
            "failed_rule_distribution": dict(sorted(failed_rules.items())),
        },
        "artifact_inventory": artifact_inventory,
        "limitations": [
            "Synthetic portfolio evidence only; never approved for clinical or billing use.",
            "Phase 3 validates one complete local batch and does not mutate raw evidence.",
            "Trusted dbt publication, dashboards, and automated claim or appeal actions "
            "remain disabled.",
        ],
    }


def _result_from_report(
    root: Path, report: dict[str, Any], report_sha256: str, *, duplicate: bool
) -> QualityRunResult:
    reconciliation = cast(dict[str, Any], report["reconciliation"])
    summary = cast(dict[str, Any], report["quality_summary"])
    decision = "duplicate_no_op" if duplicate else cast(str, report["decision"])
    return QualityRunResult(
        validation_id=cast(str, report["validation_id"]),
        rule_version=cast(str, report["rule_version"]),
        batch_id=cast(str, report["batch_id"]),
        decision=cast(Any, decision),
        publication_allowed=cast(bool, report["publication_allowed"]),
        output_directory=root,
        report_path=root / _QUALITY_REPORT,
        report_sha256=report_sha256,
        raw_rows=cast(int, reconciliation["raw_rows"]),
        accepted=cast(int, reconciliation["accepted"]),
        warned=cast(int, reconciliation["warned"]),
        quarantined=cast(int, reconciliation["quarantined"]),
        rejected=cast(int, reconciliation["rejected"]),
        correction_count=cast(int, report["correction_count"]),
        issue_count=(
            cast(int, summary["row_issue_count"])
            + cast(int, summary["source_finding_count"])
            + cast(int, summary["blocking_issue_count"])
        ),
        blocking_issue_count=cast(int, summary["blocking_issue_count"]),
        reconciled=cast(bool, reconciliation["reconciled"]),
    )


def _report_bytes(report: dict[str, object]) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _quality_receipt(
    root: Path, report: dict[str, object], report_sha256: str
) -> QualityRunReceipt:
    configuration = cast(dict[str, object], report["configuration"])
    evaluated_at_utc = cast(str, report["evaluation_window_started_at_utc"])
    return QualityRunReceipt(
        validation_id=cast(str, report["validation_id"]),
        batch_id=cast(str, report["batch_id"]),
        configuration_sha256=cast(str, configuration["configuration_sha256"]),
        evaluation_window_started_at_utc=evaluated_at_utc,
        corrections_sha256=cast(str, report["corrections_sha256"]),
        report_path=root / _QUALITY_REPORT,
        report_sha256=report_sha256,
        registered_at_utc=evaluated_at_utc,
    )


def _reject_existing_symlink_components(path: Path) -> None:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise QualityValidationError(
                f"quality output path contains a symlink component: {current}"
            )
        if not current.exists():
            break


def _verified_existing_run(
    root: Path,
    *,
    expected_report: dict[str, object],
    expected_artifacts: dict[Path, list[dict[str, object]]],
    registry: SqliteIngestionRegistry,
) -> QualityRunResult:
    report_path = root / _QUALITY_REPORT
    if (
        root.is_symlink()
        or not root.is_dir()
        or report_path.is_symlink()
        or not report_path.is_file()
    ):
        raise QualityValidationError("existing quality run path is unsafe or incomplete")
    actual_report_sha256 = _sha256(report_path)
    expected_report_sha256 = hashlib.sha256(_report_bytes(expected_report)).hexdigest()
    expected_receipt = _quality_receipt(root, expected_report, expected_report_sha256)
    registered_receipt = registry.get_quality_run(expected_receipt.validation_id)
    if registered_receipt is not None and registered_receipt != expected_receipt:
        raise QualityValidationError("durable quality receipt contradicts expected evidence")
    if registered_receipt is not None and actual_report_sha256 != registered_receipt.report_sha256:
        raise QualityValidationError("quality report checksum changed after durable registration")
    try:
        value = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualityValidationError("existing quality report cannot be read") from error
    if not isinstance(value, dict):
        raise QualityValidationError("existing quality report root must be an object")
    report = cast(dict[str, Any], value)
    expected_inventory = _expected_inventory(expected_artifacts)
    if (
        report != expected_report
        or actual_report_sha256 != expected_report_sha256
        or _inventory(root, _QUALITY_REPORT) != expected_inventory
    ):
        raise QualityValidationError(
            "existing quality run failed deterministic semantic reconstruction"
        )
    if registered_receipt is None:
        try:
            registry.register_quality_run(expected_receipt)
        except QualityReceiptCollisionError as error:
            raise QualityValidationError(str(error)) from error
    return _result_from_report(root, report, actual_report_sha256, duplicate=True)


def validate_ingestion_quality(
    result: IngestionResult,
    contracts_directory: Path,
    policy_path: Path,
    *,
    output_root: Path | None = None,
    corrections: tuple[QualityCorrection, ...] = (),
    clock: Callable[[], datetime] | None = None,
) -> QualityRunResult:
    """Validate one complete synthetic ingestion and publish immutable local evidence."""

    ingestion_report = _verified_ingestion_report(result)
    try:
        catalog = QualityCatalog.load(contracts_directory, policy_path)
    except QualityCatalogError as error:
        raise QualityValidationError(str(error)) from error
    rule_inventory = _rule_execution_inventory(catalog)
    configuration = _configuration_evidence(catalog)
    records, identities = _load_records(result, ingestion_report, catalog)
    revised_records, correction_history = _apply_corrections(
        records, corrections, contracts_directory
    )
    corrections_sha256 = _canonical_hash(correction_history)
    requested_at = (clock or (lambda: datetime.now(UTC)))()
    evaluated_at = _evaluation_window(requested_at, catalog.evaluation_interval)
    evaluated_at_utc = _timestamp(evaluated_at)
    manifest_path = _verified_relative_file(result.artifact_directory, "landing/manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualityValidationError("landed source manifest cannot be read") from error
    if not isinstance(manifest, dict) or manifest.get("synthetic_only") is not True:
        raise QualityValidationError("landed source manifest is not synthetic-only evidence")
    generated_at = _parse_timestamp(manifest.get("generated_at_utc"), "batch generated time")
    evaluation = evaluate_quality(
        revised_records,
        catalog,
        present_identities=identities,
        evaluation_time=evaluated_at,
        batch_generated_at=generated_at,
    )
    artifacts = _artifact_values(evaluation, correction_history)
    artifact_inventory = _expected_inventory(artifacts)
    validation_digest = _canonical_hash(
        {
            "batch_id": result.batch_id,
            "input_report_sha256": result.report_sha256,
            "configuration_sha256": configuration["configuration_sha256"],
            "evaluation_window_started_at_utc": evaluated_at_utc,
            "corrections_sha256": corrections_sha256,
        }
    )
    validation_id = f"quality-{result.batch_id}-{validation_digest[:16]}"
    report_value = _report_value(
        result=result,
        validation_id=validation_id,
        catalog=catalog,
        evaluation=evaluation,
        evaluated_at_utc=evaluated_at_utc,
        evaluation_interval=catalog.evaluation_interval,
        configuration=configuration,
        rule_inventory=rule_inventory,
        corrections_sha256=corrections_sha256,
        correction_count=len(correction_history),
        artifact_inventory=artifact_inventory,
    )
    requested_root = (
        (result.workspace / "quality-runs" if output_root is None else output_root)
        .expanduser()
        .absolute()
    )
    _reject_existing_symlink_components(requested_root)
    source_root = result.artifact_directory.resolve(strict=True)
    root = requested_root.resolve(strict=False)
    if root == source_root or root.is_relative_to(source_root):
        raise QualityValidationError("quality output must not modify immutable ingestion artifacts")
    if root.exists() and not root.is_dir():
        raise QualityValidationError("quality output root is unsafe")
    root.mkdir(parents=True, exist_ok=True)
    _reject_existing_symlink_components(root)
    registry = SqliteIngestionRegistry(result.workspace)
    target = root / validation_id
    if target.exists() or target.is_symlink():
        return _verified_existing_run(
            target,
            expected_report=report_value,
            expected_artifacts=artifacts,
            registry=registry,
        )

    staging = Path(tempfile.mkdtemp(prefix=f".{validation_id}-", dir=root))
    try:
        for relative, values in artifacts.items():
            _write_json_lines(staging / relative, values)
        if _inventory(staging, _QUALITY_REPORT) != artifact_inventory:
            raise QualityValidationError("staged quality artifacts are not deterministic")
        report_path = staging / _QUALITY_REPORT
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(_report_bytes(report_value))
        report_sha256 = _sha256(report_path)
        if target.exists() or target.is_symlink():
            raise QualityValidationError("quality run target appeared during validation")
        staging.rename(target)
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    try:
        registry.register_quality_run(_quality_receipt(target, report_value, report_sha256))
    except QualityReceiptCollisionError as error:
        raise QualityValidationError(str(error)) from error
    return _result_from_report(
        target, cast(dict[str, Any], report_value), report_sha256, duplicate=False
    )
