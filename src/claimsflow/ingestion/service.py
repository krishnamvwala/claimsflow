"""Atomic local ingestion service for verified synthetic deliveries."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

from claimsflow.domain.ingestion import (
    ClassifiedRow,
    DeliveryDecision,
    FileIngestionSummary,
    IngestionIntent,
    IngestionResult,
    RegistryCollisionError,
)
from claimsflow.generator.manifest import ManifestValidationError, validate_manifest
from claimsflow.generator.models import GENERATOR_VERSION, GenerationConfig, GenerationError
from claimsflow.generator.service import expected_manifest
from claimsflow.ingestion.contracts import ContractCatalog, ContractLoadError, SourceFileContract
from claimsflow.ingestion.validation import (
    ProvenanceViolation,
    classify_row,
    stable_key,
    verify_reserved_synthetic_values,
)
from claimsflow.ports.ingestion import IngestionRegistry, RegistryFactory


class IngestionError(RuntimeError):
    """Raised when a delivery fails closed at the local ingestion boundary."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise IngestionError(f"manifest is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IngestionError(f"manifest cannot be read as UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise IngestionError("manifest root must be an object")
    return cast(dict[str, Any], value)


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    files = manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise IngestionError("manifest files must be an array of objects")
    return cast(list[dict[str, Any]], files)


def _source_rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        for row_number, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise IngestionError(f"CSV row {row_number} does not match its header: {path.name}")
            yield row_number, cast(dict[str, str], row)


def _verify_pre_ingress_provenance(
    delivery_directory: Path,
    entries: list[dict[str, Any]],
    catalog: ContractCatalog,
) -> None:
    """Scan reserved identities before creating any project-managed payload storage."""

    for entry in entries:
        contract = catalog.for_manifest_entry(entry)
        path = delivery_directory / cast(str, entry["path"])
        if path.is_symlink() or not path.is_file():
            raise IngestionError(f"delivery file is missing or unsafe: {entry['path']}")
        source_system = cast(str, entry["source_system"])
        for row_number, row in _source_rows(path):
            verify_reserved_synthetic_values(contract, row, source_system, row_number)


def _verify_deterministic_provenance(manifest: dict[str, Any]) -> None:
    """Bind the delivery to exact output from the approved deterministic generator."""

    generator = cast(dict[str, Any], manifest["generator"])
    version = cast(str, generator["version"])
    if version != GENERATOR_VERSION:
        raise ProvenanceViolation(
            "DQ-CMN-001: generator.version is not the currently approved generator"
        )
    try:
        config = GenerationConfig.from_values(
            seed=cast(int, generator["seed"]),
            claim_count=cast(int, generator["claim_count"]),
            service_month=cast(str, generator["service_month"]),
            generator_version=version,
        )
        approved = expected_manifest(config)
    except GenerationError as error:
        raise ProvenanceViolation(f"DQ-CMN-001: invalid generator evidence: {error}") from error
    if manifest != approved:
        raise ProvenanceViolation(
            "DQ-CMN-001: delivery evidence does not match exact approved deterministic output"
        )


def _safe_workspace(manifest_path: Path, workspace: Path) -> Path:
    target = workspace.expanduser().absolute()
    delivery_directory = manifest_path.parent.absolute()
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise IngestionError(f"workspace is not a safe directory: {target}")
    if target == delivery_directory or target.is_relative_to(delivery_directory):
        raise IngestionError("workspace must not be inside the untrusted delivery directory")
    return target


def _managed_directory(workspace: Path, name: str) -> Path:
    path = workspace / name
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise IngestionError(f"managed ingestion directory is unsafe: {path}")
    path.mkdir(exist_ok=True)
    if path.is_symlink() or path.resolve(strict=True).parent != workspace.resolve(strict=True):
        raise IngestionError(f"managed ingestion directory escapes workspace: {path}")
    return path


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise IngestionError("ingestion clock must return a timezone-aware timestamp")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _identity_file_name(source_identity: str) -> str:
    return source_identity.replace(".", "_").replace("-", "_") + ".jsonl"


def _envelope(
    classified: ClassifiedRow,
    *,
    batch_id: str,
    source_family: str,
    dataset: str | None,
    source_system: str,
    source_file: str,
    source_checksum: str,
    source_row_number: int,
    contract_id: str,
    contract_version: str,
    ingested_at_utc: str,
) -> dict[str, object]:
    return {
        "synthetic_only": True,
        "lineage": {
            "batch_id": batch_id,
            "source_identity": classified.source_identity,
            "source_family": source_family,
            "dataset": dataset,
            "source_system": source_system,
            "source_file": source_file,
            "source_checksum_sha256": source_checksum,
            "source_row_number": source_row_number,
            "contract_id": contract_id,
            "contract_version": contract_version,
            "ingested_at_utc": ingested_at_utc,
        },
        "source_record_id": classified.source_record_id,
        "natural_key": classified.natural_key,
        "version_discriminator": classified.version_discriminator,
        "payload_sha256": classified.payload_sha256,
        "processing_status": classified.disposition,
        "disposition": classified.disposition,
        "issues": [issue.as_dict() for issue in classified.issues],
        "raw_payload": classified.original_payload,
        "normalized_payload": classified.normalized_payload,
    }


def _write_json_line(output: TextIO, value: object) -> None:
    output.write(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")


def _is_duplicate_key(
    connection: sqlite3.Connection,
    source_identity: str,
    natural_key: str,
) -> bool:
    try:
        connection.execute(
            "INSERT INTO seen_keys(source_identity, natural_key) VALUES (?, ?)",
            (source_identity, natural_key),
        )
    except sqlite3.IntegrityError:
        return True
    return False


def _process_file(
    entry: dict[str, Any],
    contract: SourceFileContract,
    delivery_directory: Path,
    staging: Path,
    seen: sqlite3.Connection,
    batch_id: str,
    ingested_at_utc: str,
) -> FileIngestionSummary:
    file_name = cast(str, entry["file_name"])
    checksum = cast(str, entry["sha256"])
    source_system = cast(str, entry["source_system"])
    source_path = delivery_directory / cast(str, entry["path"])
    landing_relative = Path("landing/files") / file_name
    landing_path = staging / landing_relative
    landing_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, landing_path)
    if _sha256(landing_path) != checksum:
        raise IngestionError(f"DQ-CMN-006: landing copy checksum changed for {file_name}")

    evidence_name = _identity_file_name(contract.source_identity)
    raw_relative = Path("raw") / evidence_name
    quality_relative = Path("quality") / evidence_name
    quarantine_relative = Path("quarantine") / evidence_name
    rejected_relative = Path("rejected") / evidence_name
    for relative in (raw_relative, quality_relative, quarantine_relative, rejected_relative):
        (staging / relative).parent.mkdir(parents=True, exist_ok=True)

    counts: Counter[str] = Counter()
    with (
        (staging / raw_relative).open("w", encoding="utf-8") as raw_output,
        (staging / quality_relative).open("w", encoding="utf-8") as quality_output,
        (staging / quarantine_relative).open("w", encoding="utf-8") as quarantine_output,
        (staging / rejected_relative).open("w", encoding="utf-8") as rejected_output,
    ):
        for row_number, row in _source_rows(landing_path):
            natural_key = stable_key(contract.natural_key, row, source_system)
            duplicate = _is_duplicate_key(seen, contract.source_identity, natural_key)
            classified = classify_row(contract, row, source_system, duplicate)
            envelope = _envelope(
                classified,
                batch_id=batch_id,
                source_family=contract.source_family,
                dataset=contract.dataset,
                source_system=source_system,
                source_file=file_name,
                source_checksum=checksum,
                source_row_number=row_number,
                contract_id=contract.contract_id,
                contract_version=contract.contract_version,
                ingested_at_utc=ingested_at_utc,
            )
            _write_json_line(raw_output, envelope)
            for issue in classified.issues:
                _write_json_line(
                    quality_output,
                    {
                        "batch_id": batch_id,
                        "source_identity": contract.source_identity,
                        "source_file": file_name,
                        "source_row_number": row_number,
                        **issue.as_dict(),
                        "processed_at_utc": ingested_at_utc,
                    },
                )
            if classified.disposition == "quarantined":
                _write_json_line(quarantine_output, envelope)
            elif classified.disposition == "rejected":
                _write_json_line(rejected_output, envelope)
            counts[classified.disposition] += 1

    raw_rows = sum(counts.values())
    declared_rows = cast(int, entry["row_count"])
    if raw_rows != declared_rows:
        raise IngestionError(f"DQ-CMN-006: parsed rows do not match manifest for {file_name}")
    return FileIngestionSummary(
        source_identity=contract.source_identity,
        source_family=contract.source_family,
        dataset=contract.dataset,
        source_system=source_system,
        file_name=file_name,
        checksum_sha256=checksum,
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        declared_rows=declared_rows,
        decision="processed",
        raw_rows=raw_rows,
        accepted=counts["accepted"],
        warned=counts["accepted_with_warning"],
        quarantined=counts["quarantined"],
        rejected=counts["rejected"],
        duplicate_of_batch_id=None,
        landing_path=str(landing_relative),
        raw_path=str(raw_relative),
        quality_path=str(quality_relative),
        quarantine_path=str(quarantine_relative),
        rejected_path=str(rejected_relative),
    )


def _duplicate_summary(
    entry: dict[str, Any], contract: SourceFileContract, original_batch_id: str
) -> FileIngestionSummary:
    return FileIngestionSummary(
        source_identity=contract.source_identity,
        source_family=contract.source_family,
        dataset=contract.dataset,
        source_system=cast(str, entry["source_system"]),
        file_name=cast(str, entry["file_name"]),
        checksum_sha256=cast(str, entry["sha256"]),
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        declared_rows=cast(int, entry["row_count"]),
        decision="duplicate_no_op",
        raw_rows=0,
        accepted=0,
        warned=0,
        quarantined=0,
        rejected=0,
        duplicate_of_batch_id=original_batch_id,
        landing_path=None,
        raw_path=None,
        quality_path=None,
        quarantine_path=None,
        rejected_path=None,
    )


def _file_report(summary: FileIngestionSummary) -> dict[str, object]:
    return {
        "source_identity": summary.source_identity,
        "source_family": summary.source_family,
        "dataset": summary.dataset,
        "source_system": summary.source_system,
        "file_name": summary.file_name,
        "checksum_sha256": summary.checksum_sha256,
        "contract_id": summary.contract_id,
        "contract_version": summary.contract_version,
        "declared_rows": summary.declared_rows,
        "decision": summary.decision,
        "duplicate_of_batch_id": summary.duplicate_of_batch_id,
        "counts": {
            "raw": summary.raw_rows,
            "accepted": summary.accepted,
            "warned": summary.warned,
            "quarantined": summary.quarantined,
            "rejected": summary.rejected,
            "reconciled": summary.raw_rows == summary.disposition_rows,
        },
        "artifacts": {
            "landing": summary.landing_path,
            "raw": summary.raw_path,
            "quality": summary.quality_path,
            "quarantine": summary.quarantine_path,
            "rejected": summary.rejected_path,
        },
    }


def _report(
    batch_id: str,
    manifest_sha256: str,
    ingested_at_utc: str,
    decision: str,
    summaries: list[FileIngestionSummary],
    artifact_inventory: list[dict[str, object]],
) -> dict[str, object]:
    declared_rows = sum(item.declared_rows for item in summaries)
    raw_rows = sum(item.raw_rows for item in summaries)
    duplicate_rows = sum(
        item.declared_rows for item in summaries if item.decision == "duplicate_no_op"
    )
    accepted = sum(item.accepted for item in summaries)
    warned = sum(item.warned for item in summaries)
    quarantined = sum(item.quarantined for item in summaries)
    rejected = sum(item.rejected for item in summaries)
    disposition_rows = accepted + warned + quarantined + rejected
    reconciled = raw_rows == disposition_rows and raw_rows + duplicate_rows == declared_rows
    return {
        "schema_version": "1.0.0",
        "batch_id": batch_id,
        "synthetic_only": True,
        "decision": decision,
        "ingested_at_utc": ingested_at_utc,
        "source_manifest_sha256": manifest_sha256,
        "files": [_file_report(item) for item in summaries],
        "artifact_inventory": artifact_inventory,
        "reconciliation": {
            "declared_rows": declared_rows,
            "raw_rows": raw_rows,
            "duplicate_no_op_rows": duplicate_rows,
            "accepted": accepted,
            "warned": warned,
            "quarantined": quarantined,
            "rejected": rejected,
            "disposition_rows": disposition_rows,
            "reconciled": reconciled,
        },
        "limitations": [
            "Local synthetic portfolio evidence only; no production or billing use.",
            "This slice performs structural, type, bounded financial, and provenance checks.",
            (
                "Cross-family relationship and freshness rule execution remains a later "
                "validation slice."
            ),
            (
                "No trusted publication, cloud upload, dbt model, dashboard, or automated "
                "appeal action occurs."
            ),
        ],
    }


_REPORT_RELATIVE = Path("audit/ingestion-report.json")


def _artifact_inventory(root: Path) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise IngestionError(f"artifact contains unsafe symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise IngestionError(f"artifact contains unsafe file type: {path}")
        relative = path.relative_to(root)
        if relative == _REPORT_RELATIVE:
            continue
        inventory.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256(path),
                "byte_size": path.stat().st_size,
            }
        )
    return inventory


def _validate_report_semantics(report: dict[str, Any]) -> None:
    files = report.get("files")
    reconciliation = report.get("reconciliation")
    if not isinstance(files, list) or not isinstance(reconciliation, dict):
        raise IngestionError("stored ingestion report has an invalid semantic shape")

    computed = Counter[str]()
    processed_files = 0
    for raw_item in files:
        if not isinstance(raw_item, dict):
            raise IngestionError("stored ingestion report has an invalid file entry")
        item = cast(dict[str, Any], raw_item)
        counts = item.get("counts")
        artifacts = item.get("artifacts")
        if not isinstance(counts, dict) or not isinstance(artifacts, dict):
            raise IngestionError("stored ingestion report has invalid file evidence")
        declared = item.get("declared_rows")
        if not isinstance(declared, int):
            raise IngestionError("stored ingestion report has invalid declared row evidence")
        decision = item.get("decision")
        count_values = {
            key: counts.get(key) for key in ("raw", "accepted", "warned", "quarantined", "rejected")
        }
        if any(not isinstance(value, int) or value < 0 for value in count_values.values()):
            raise IngestionError("stored ingestion report has invalid disposition counts")
        raw_rows = cast(int, count_values["raw"])
        disposition_rows = sum(
            cast(int, count_values[key])
            for key in ("accepted", "warned", "quarantined", "rejected")
        )
        if counts.get("reconciled") is not True or raw_rows != disposition_rows:
            raise IngestionError("stored ingestion report file counts do not reconcile")
        if decision == "processed":
            processed_files += 1
            if item.get("duplicate_of_batch_id") is not None or raw_rows != declared:
                raise IngestionError("processed report file has contradictory evidence")
            if any(not isinstance(value, str) for value in artifacts.values()):
                raise IngestionError("processed report file is missing artifact paths")
        elif decision == "duplicate_no_op":
            if not isinstance(item.get("duplicate_of_batch_id"), str):
                raise IngestionError("duplicate report file is missing its original batch")
            if any(cast(int, value) != 0 for value in count_values.values()) or any(
                value is not None for value in artifacts.values()
            ):
                raise IngestionError("duplicate report file has contradictory evidence")
            computed["duplicate_no_op_rows"] += declared
        else:
            raise IngestionError("stored ingestion report has an invalid decision")
        computed["declared_rows"] += declared
        computed["raw_rows"] += raw_rows
        for key in ("accepted", "warned", "quarantined", "rejected"):
            computed[key] += cast(int, count_values[key])

    computed["disposition_rows"] = sum(
        computed[key] for key in ("accepted", "warned", "quarantined", "rejected")
    )
    expected_decision = "processed" if processed_files else "duplicate_no_op"
    if report.get("decision") != expected_decision:
        raise IngestionError("stored ingestion report has a contradictory batch decision")
    for key, value in computed.items():
        if reconciliation.get(key) != value:
            raise IngestionError(f"stored ingestion report does not reconcile {key}")
    if (
        reconciliation.get("reconciled") is not True
        or computed["raw_rows"] != computed["disposition_rows"]
        or computed["raw_rows"] + computed["duplicate_no_op_rows"] != computed["declared_rows"]
    ):
        raise IngestionError("stored ingestion report batch counts do not reconcile")


def _verified_report(
    artifact_directory: Path,
    report_path: Path,
    expected_report_sha256: str,
) -> dict[str, Any]:
    expected_path = artifact_directory / _REPORT_RELATIVE
    if report_path != expected_path:
        raise IngestionError("registered ingestion report path is inconsistent")
    if (
        artifact_directory.is_symlink()
        or not artifact_directory.is_dir()
        or report_path.is_symlink()
        or not report_path.is_file()
    ):
        raise IngestionError("registered batch artifacts are missing or unsafe")
    if _sha256(report_path) != expected_report_sha256:
        raise IngestionError("registered ingestion report checksum does not match")
    try:
        value = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IngestionError("registered ingestion report cannot be read") from error
    if not isinstance(value, dict):
        raise IngestionError("registered ingestion report root must be an object")
    report = cast(dict[str, Any], value)
    _validate_report_semantics(report)
    inventory = report.get("artifact_inventory")
    if not isinstance(inventory, list) or inventory != _artifact_inventory(artifact_directory):
        raise IngestionError("registered batch artifact inventory does not match")
    return report


def _summaries_from_report(report: dict[str, Any]) -> list[FileIngestionSummary]:
    summaries: list[FileIngestionSummary] = []
    for raw_item in cast(list[dict[str, Any]], report["files"]):
        counts = cast(dict[str, Any], raw_item["counts"])
        artifacts = cast(dict[str, Any], raw_item["artifacts"])
        summaries.append(
            FileIngestionSummary(
                source_identity=cast(str, raw_item["source_identity"]),
                source_family=cast(str, raw_item["source_family"]),
                dataset=cast(str | None, raw_item["dataset"]),
                source_system=cast(str, raw_item["source_system"]),
                file_name=cast(str, raw_item["file_name"]),
                checksum_sha256=cast(str, raw_item["checksum_sha256"]),
                contract_id=cast(str, raw_item["contract_id"]),
                contract_version=cast(str, raw_item["contract_version"]),
                declared_rows=cast(int, raw_item["declared_rows"]),
                decision=cast(DeliveryDecision, raw_item["decision"]),
                raw_rows=cast(int, counts["raw"]),
                accepted=cast(int, counts["accepted"]),
                warned=cast(int, counts["warned"]),
                quarantined=cast(int, counts["quarantined"]),
                rejected=cast(int, counts["rejected"]),
                duplicate_of_batch_id=cast(str | None, raw_item["duplicate_of_batch_id"]),
                landing_path=cast(str | None, artifacts["landing"]),
                raw_path=cast(str | None, artifacts["raw"]),
                quality_path=cast(str | None, artifacts["quality"]),
                quarantine_path=cast(str | None, artifacts["quarantine"]),
                rejected_path=cast(str | None, artifacts["rejected"]),
            )
        )
    return summaries


def _result_from_report(
    report: dict[str, Any],
    workspace: Path,
    artifact_directory: Path,
    report_sha256: str,
) -> IngestionResult:
    reconciliation = cast(dict[str, Any], report["reconciliation"])
    summaries = _summaries_from_report(report)
    return IngestionResult(
        batch_id=cast(str, report["batch_id"]),
        decision=cast(DeliveryDecision, report["decision"]),
        workspace=workspace,
        artifact_directory=artifact_directory,
        report_path=artifact_directory / _REPORT_RELATIVE,
        report_sha256=report_sha256,
        manifest_sha256=cast(str, report["source_manifest_sha256"]),
        file_count=len(summaries),
        processed_files=sum(item.decision == "processed" for item in summaries),
        duplicate_files=sum(item.decision == "duplicate_no_op" for item in summaries),
        declared_rows=cast(int, reconciliation["declared_rows"]),
        raw_rows=cast(int, reconciliation["raw_rows"]),
        duplicate_no_op_rows=cast(int, reconciliation["duplicate_no_op_rows"]),
        accepted=cast(int, reconciliation["accepted"]),
        warned=cast(int, reconciliation["warned"]),
        quarantined=cast(int, reconciliation["quarantined"]),
        rejected=cast(int, reconciliation["rejected"]),
        reconciled=True,
    )


def _verified_registered_batch(
    existing: IngestionResult,
    workspace: Path,
    batches_directory: Path,
) -> tuple[IngestionResult, dict[str, Any]]:
    expected_directory = batches_directory / existing.batch_id
    if existing.artifact_directory != expected_directory:
        raise IngestionError("registered batch artifact directory is not canonical")
    report = _verified_report(
        existing.artifact_directory,
        existing.report_path,
        existing.report_sha256,
    )
    verified = _result_from_report(
        report,
        workspace,
        existing.artifact_directory,
        existing.report_sha256,
    )
    if existing != verified:
        raise IngestionError("persisted batch summary contradicts its verified report")
    return verified, report


def _verify_duplicate_lineage(
    registry: IngestionRegistry,
    cache: dict[str, dict[str, Any]],
    *,
    original_batch_id: str,
    workspace: Path,
    batches_directory: Path,
    expected: dict[str, Any],
) -> None:
    report = cache.get(original_batch_id)
    if report is None:
        existing = registry.get_batch(original_batch_id)
        if existing is None:
            raise IngestionError("duplicate lineage references an unregistered original batch")
        _, report = _verified_registered_batch(existing, workspace, batches_directory)
        cache[original_batch_id] = report
    matches = [
        item
        for item in cast(list[dict[str, Any]], report["files"])
        if all(
            item.get(key) == expected[key]
            for key in (
                "source_identity",
                "source_family",
                "dataset",
                "source_system",
                "file_name",
                "checksum_sha256",
                "contract_id",
                "contract_version",
                "declared_rows",
            )
        )
        and item.get("decision") == "processed"
    ]
    if len(matches) != 1:
        raise IngestionError(
            "duplicate lineage does not match one verified processed original file"
        )


def _verify_report_duplicate_dependencies(
    registry: IngestionRegistry,
    report: dict[str, Any],
    workspace: Path,
    batches_directory: Path,
) -> None:
    cache: dict[str, dict[str, Any]] = {}
    for item in cast(list[dict[str, Any]], report["files"]):
        if item.get("decision") != "duplicate_no_op":
            continue
        original_batch_id = item.get("duplicate_of_batch_id")
        if not isinstance(original_batch_id, str):
            raise IngestionError("duplicate report file is missing its original batch")
        _verify_duplicate_lineage(
            registry,
            cache,
            original_batch_id=original_batch_id,
            workspace=workspace,
            batches_directory=batches_directory,
            expected=item,
        )


def _preserve_collision(
    registry: IngestionRegistry,
    result: IngestionResult,
    error: RegistryCollisionError,
    occurred_at_utc: str,
) -> None:
    collision_root = _managed_directory(result.workspace, "collisions")
    collision_directory = collision_root / (
        f"{result.batch_id}-{result.manifest_sha256[:12]}-{result.report_sha256[:12]}"
    )
    if collision_directory.exists() or collision_directory.is_symlink():
        raise IngestionError("collision evidence path already exists; refusing to overwrite it")
    result.artifact_directory.rename(collision_directory)
    details = {
        **error.details,
        "incoming_batch_id": result.batch_id,
        "incoming_manifest_sha256": result.manifest_sha256,
        "incoming_report_sha256": result.report_sha256,
        "incoming_artifact_directory": str(collision_directory),
    }
    collision_report = collision_directory / "audit/collision.json"
    collision_report.write_text(
        json.dumps(details, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    registry.clear_intent(result.batch_id)
    registry.record_event(
        result.batch_id,
        result.manifest_sha256,
        "blocked",
        occurred_at_utc,
        str(error),
        details,
    )
    raise IngestionError(str(error)) from error


def _recover_intent(
    registry: IngestionRegistry,
    intent: IngestionIntent,
    *,
    workspace: Path,
    expected_final_directory: Path,
    manifest_sha256: str,
) -> IngestionResult | None:
    if intent.manifest_sha256 != manifest_sha256:
        raise IngestionError("interrupted batch intent has different manifest evidence")
    if (
        intent.final_directory != expected_final_directory
        or intent.staging_directory.parent != workspace
        or not intent.staging_directory.name.startswith(f".{intent.batch_id}-")
    ):
        raise IngestionError("interrupted batch intent contains unsafe artifact paths")

    staging_exists = intent.staging_directory.exists() or intent.staging_directory.is_symlink()
    final_exists = intent.final_directory.exists() or intent.final_directory.is_symlink()
    if staging_exists and final_exists:
        raise IngestionError("interrupted batch has both staging and final artifacts")
    if final_exists:
        report_path = intent.final_directory / _REPORT_RELATIVE
        report = _verified_report(
            intent.final_directory,
            report_path,
            intent.report_sha256,
        )
        if (
            report.get("batch_id") != intent.batch_id
            or report.get("source_manifest_sha256") != manifest_sha256
        ):
            raise IngestionError("interrupted batch report does not match its intent")
        _verify_report_duplicate_dependencies(
            registry,
            report,
            workspace,
            expected_final_directory.parent,
        )
        result = _result_from_report(
            report,
            workspace,
            intent.final_directory,
            intent.report_sha256,
        )
        summaries = _summaries_from_report(report)
        raw_paths = [
            intent.final_directory / item.raw_path
            for item in summaries
            if item.raw_path is not None
        ]
        try:
            registry.register_batch(
                result,
                summaries,
                raw_paths,
                intent.occurred_at_utc,
            )
        except RegistryCollisionError as error:
            _preserve_collision(registry, result, error, intent.occurred_at_utc)
        return result
    if staging_exists:
        if intent.staging_directory.is_symlink() or not intent.staging_directory.is_dir():
            raise IngestionError("interrupted staging path is unsafe")
        shutil.rmtree(intent.staging_directory)
    registry.clear_intent(intent.batch_id)
    return None


def _ingest_locked(
    *,
    source_manifest: Path,
    delivery_directory: Path,
    target_workspace: Path,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
    catalog: ContractCatalog,
    registry: IngestionRegistry,
    now: str,
) -> IngestionResult:
    batch_id = cast(str, manifest["batch_id"])
    manifest_sha256 = _canonical_manifest_hash(manifest)
    batches = _managed_directory(target_workspace, "batches")
    existing = registry.get_batch(batch_id)
    if existing is not None:
        if existing.manifest_sha256 != manifest_sha256:
            reason = "batch ID was previously registered with different manifest evidence"
            registry.record_event(batch_id, manifest_sha256, "blocked", now, reason)
            raise IngestionError(f"batch identity collision: {reason}")
        try:
            verified, report = _verified_registered_batch(
                existing,
                target_workspace,
                batches,
            )
            _verify_report_duplicate_dependencies(
                registry,
                report,
                target_workspace,
                batches,
            )
        except IngestionError as error:
            registry.record_event(batch_id, manifest_sha256, "blocked", now, str(error))
            raise
        if (
            report.get("batch_id") != batch_id
            or report.get("source_manifest_sha256") != manifest_sha256
        ):
            reason = "registered ingestion report does not match batch identity"
            registry.record_event(batch_id, manifest_sha256, "blocked", now, reason)
            raise IngestionError(reason)
        registry.record_event(batch_id, manifest_sha256, "duplicate_no_op", now)
        return replace(
            verified,
            decision="duplicate_no_op",
            processed_files=0,
            duplicate_files=existing.file_count,
            raw_rows=0,
            duplicate_no_op_rows=existing.declared_rows,
            accepted=0,
            warned=0,
            quarantined=0,
            rejected=0,
            reconciled=True,
        )

    final_directory = batches / batch_id
    intent = registry.get_intent(batch_id)
    if intent is not None:
        try:
            recovered = _recover_intent(
                registry,
                intent,
                workspace=target_workspace,
                expected_final_directory=final_directory,
                manifest_sha256=manifest_sha256,
            )
        except IngestionError as error:
            registry.record_event(batch_id, manifest_sha256, "blocked", now, str(error))
            raise
        if recovered is not None:
            return recovered
    if final_directory.exists() or final_directory.is_symlink():
        reason = f"unregistered batch artifact path already exists: {final_directory}"
        registry.record_event(batch_id, manifest_sha256, "blocked", now, reason)
        raise IngestionError(reason)

    staging = Path(tempfile.mkdtemp(prefix=f".{batch_id}-", dir=target_workspace))
    summaries: list[FileIngestionSummary] = []
    stage_database = staging / "seen-keys.sqlite3"
    published = False
    registered = False
    intent_prepared = False
    retain_for_recovery = False
    duplicate_report_cache: dict[str, dict[str, Any]] = {}
    try:
        (staging / "landing").mkdir()
        shutil.copy2(source_manifest, staging / "landing/manifest.json")
        landed_manifest = _load_manifest(staging / "landing/manifest.json")
        if _canonical_manifest_hash(landed_manifest) != manifest_sha256:
            raise IngestionError("DQ-CMN-006: landing manifest changed during ingestion")
        with sqlite3.connect(stage_database) as seen:
            seen.execute(
                """
                CREATE TABLE seen_keys (
                    source_identity TEXT NOT NULL,
                    natural_key TEXT NOT NULL,
                    PRIMARY KEY (source_identity, natural_key)
                )
                """
            )
            for entry in entries:
                contract = catalog.for_manifest_entry(entry)
                duplicate_batch = registry.find_duplicate_delivery(
                    contract.source_identity,
                    cast(str, entry["source_system"]),
                    cast(str, entry["sha256"]),
                )
                if duplicate_batch is not None:
                    _verify_duplicate_lineage(
                        registry,
                        duplicate_report_cache,
                        original_batch_id=duplicate_batch,
                        workspace=target_workspace,
                        batches_directory=batches,
                        expected={
                            "source_identity": contract.source_identity,
                            "source_family": contract.source_family,
                            "dataset": contract.dataset,
                            "source_system": entry["source_system"],
                            "file_name": entry["file_name"],
                            "checksum_sha256": entry["sha256"],
                            "contract_id": contract.contract_id,
                            "contract_version": contract.contract_version,
                            "declared_rows": entry["row_count"],
                        },
                    )
                    summaries.append(_duplicate_summary(entry, contract, duplicate_batch))
                else:
                    summaries.append(
                        _process_file(
                            entry,
                            contract,
                            delivery_directory,
                            staging,
                            seen,
                            batch_id,
                            now,
                        )
                    )
        stage_database.unlink()

        decision: DeliveryDecision = (
            "processed"
            if any(item.decision == "processed" for item in summaries)
            else "duplicate_no_op"
        )
        report = _report(
            batch_id,
            manifest_sha256,
            now,
            decision,
            summaries,
            _artifact_inventory(staging),
        )
        _validate_report_semantics(cast(dict[str, Any], report))
        _verify_report_duplicate_dependencies(
            registry,
            cast(dict[str, Any], report),
            target_workspace,
            batches,
        )
        reconciliation = cast(dict[str, Any], report["reconciliation"])
        report_path = staging / _REPORT_RELATIVE
        report_path.parent.mkdir(parents=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        report_sha256 = _sha256(report_path)
        result = IngestionResult(
            batch_id=batch_id,
            decision=decision,
            workspace=target_workspace,
            artifact_directory=final_directory,
            report_path=final_directory / _REPORT_RELATIVE,
            report_sha256=report_sha256,
            manifest_sha256=manifest_sha256,
            file_count=len(summaries),
            processed_files=sum(item.decision == "processed" for item in summaries),
            duplicate_files=sum(item.decision == "duplicate_no_op" for item in summaries),
            declared_rows=cast(int, reconciliation["declared_rows"]),
            raw_rows=cast(int, reconciliation["raw_rows"]),
            duplicate_no_op_rows=cast(int, reconciliation["duplicate_no_op_rows"]),
            accepted=cast(int, reconciliation["accepted"]),
            warned=cast(int, reconciliation["warned"]),
            quarantined=cast(int, reconciliation["quarantined"]),
            rejected=cast(int, reconciliation["rejected"]),
            reconciled=True,
        )
        registry.prepare_intent(
            IngestionIntent(
                batch_id=batch_id,
                manifest_sha256=manifest_sha256,
                staging_directory=staging,
                final_directory=final_directory,
                report_sha256=report_sha256,
                occurred_at_utc=now,
            )
        )
        intent_prepared = True
        staging.rename(final_directory)
        published = True

        raw_paths = [
            final_directory / item.raw_path for item in summaries if item.raw_path is not None
        ]
        try:
            registry.register_batch(result, summaries, raw_paths, now)
        except RegistryCollisionError as error:
            _preserve_collision(registry, result, error, now)
        except Exception as registration_error:
            try:
                committed = registry.get_batch(batch_id)
            except Exception as reconciliation_error:
                retain_for_recovery = True
                raise IngestionError(
                    "registration outcome is uncertain; durable artifacts were retained for retry"
                ) from reconciliation_error
            if committed is not None:
                retain_for_recovery = True
                if (
                    committed.manifest_sha256 != manifest_sha256
                    or committed.report_sha256 != report_sha256
                    or committed.artifact_directory != final_directory
                ):
                    raise IngestionError(
                        "registration committed contradictory evidence; artifacts were retained"
                    ) from registration_error
                _verified_report(
                    committed.artifact_directory,
                    committed.report_path,
                    committed.report_sha256,
                )
                registered = True
                return result
            raise
        registered = True
        return result
    except Exception as error:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        if published and not registered and not retain_for_recovery and final_directory.exists():
            shutil.rmtree(final_directory)
        if intent_prepared and not retain_for_recovery:
            with suppress(Exception):
                registry.clear_intent(batch_id)
        if isinstance(error, IngestionError):
            raise
        raise IngestionError(
            "local ingestion failed atomically; unregistered batch artifacts were rolled back"
        ) from error


def ingest_delivery(
    manifest_path: Path,
    workspace: Path,
    contracts_directory: Path,
    *,
    registry_factory: RegistryFactory,
    clock: Callable[[], datetime] | None = None,
) -> IngestionResult:
    """Verify, classify, reconcile, land, and idempotently register one delivery."""

    source_manifest = manifest_path.expanduser().absolute()
    delivery_directory = source_manifest.parent
    target_workspace = _safe_workspace(source_manifest, workspace)
    manifest = _load_manifest(source_manifest)
    entries = _manifest_entries(manifest)
    try:
        validate_manifest(manifest, delivery_directory)
        catalog = ContractCatalog.load(contracts_directory)
        if sorted(catalog.identities()) != sorted(
            catalog.for_manifest_entry(entry).source_identity for entry in entries
        ):
            raise ContractLoadError("manifest does not contain the exact contract catalog")
        _verify_pre_ingress_provenance(delivery_directory, entries, catalog)
        _verify_deterministic_provenance(manifest)
    except (
        ManifestValidationError,
        ContractLoadError,
        ProvenanceViolation,
        OSError,
        UnicodeError,
        csv.Error,
    ) as error:
        raise IngestionError(str(error)) from error

    now = _timestamp(clock or (lambda: datetime.now(UTC)))
    try:
        registry = registry_factory(target_workspace)
        with registry.exclusive_ingestion():
            return _ingest_locked(
                source_manifest=source_manifest,
                delivery_directory=delivery_directory,
                target_workspace=target_workspace,
                manifest=manifest,
                entries=entries,
                catalog=catalog,
                registry=registry,
                now=now,
            )
    except IngestionError:
        raise
    except (sqlite3.Error, OSError) as error:
        raise IngestionError("local ingestion registry is unavailable") from error
