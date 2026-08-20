"""Cloud publication service for one verified local synthetic ingestion result."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from claimsflow.domain.cloud import (
    AuditWriteRequest,
    CloudPublicationResult,
    LandingObjectRequest,
    RawLoadRequest,
)
from claimsflow.domain.ingestion import IngestionResult
from claimsflow.ports.cloud import LandingObjectStore, RawAuditWarehouse

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_RELATION_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_REPORT_RELATIVE = Path("audit/ingestion-report.json")


class CloudPublicationError(RuntimeError):
    """Raised when local or cloud evidence cannot be reconciled safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_relative_file(root: Path, raw_relative: str) -> Path:
    relative = PurePosixPath(raw_relative)
    if (
        relative.is_absolute()
        or relative.as_posix() != raw_relative
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise CloudPublicationError("artifact report contains an unsafe relative path")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CloudPublicationError(f"artifact is missing or unsafe: {raw_relative}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise CloudPublicationError(f"artifact escapes its batch directory: {raw_relative}")
    return candidate


def _actual_inventory(root: Path) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise CloudPublicationError(f"artifact inventory contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise CloudPublicationError(f"artifact inventory contains an unsafe file: {path}")
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


def _verified_report(
    result: IngestionResult,
) -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    root = result.artifact_directory
    if root.is_symlink() or not root.is_dir():
        raise CloudPublicationError("local ingestion artifact directory is missing or unsafe")
    expected_report = root / _REPORT_RELATIVE
    if result.report_path != expected_report:
        raise CloudPublicationError("local ingestion report path is not canonical")
    if expected_report.is_symlink() or not expected_report.is_file():
        raise CloudPublicationError("local ingestion report is missing or unsafe")
    if _sha256(expected_report) != result.report_sha256:
        raise CloudPublicationError("local ingestion report checksum changed")
    try:
        value = json.loads(expected_report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CloudPublicationError(f"local ingestion report is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise CloudPublicationError("local ingestion report root must be an object")
    report = cast(dict[str, Any], value)
    if report.get("synthetic_only") is not True:
        raise CloudPublicationError("cloud publication requires synthetic-only report evidence")
    if report.get("batch_id") != result.batch_id:
        raise CloudPublicationError("local report batch ID contradicts the ingestion result")
    if report.get("source_manifest_sha256") != result.manifest_sha256:
        raise CloudPublicationError(
            "local report manifest checksum contradicts the ingestion result"
        )
    if _SHA256.fullmatch(result.report_sha256) is None:
        raise CloudPublicationError("local report checksum must be lowercase SHA-256")
    if _SHA256.fullmatch(result.manifest_sha256) is None:
        raise CloudPublicationError("manifest checksum must be lowercase SHA-256")

    declared_inventory = report.get("artifact_inventory")
    if not isinstance(declared_inventory, list):
        raise CloudPublicationError("local report artifact inventory is missing")
    actual_inventory = _actual_inventory(root)
    if declared_inventory != actual_inventory:
        raise CloudPublicationError("local artifact inventory no longer matches its report")
    inventory_by_path: dict[str, dict[str, object]] = {}
    for raw_item in actual_inventory:
        item = raw_item
        path = item.get("path")
        if not isinstance(path, str) or path in inventory_by_path:
            raise CloudPublicationError("local artifact inventory paths are invalid or duplicated")
        inventory_by_path[path] = item

    reconciliation = report.get("reconciliation")
    files = report.get("files")
    if not isinstance(reconciliation, dict) or not isinstance(files, list):
        raise CloudPublicationError("local report reconciliation evidence is missing")
    if reconciliation.get("reconciled") is not True or result.reconciled is not True:
        raise CloudPublicationError("local ingestion must reconcile before cloud publication")
    if len(files) != result.file_count:
        raise CloudPublicationError("local report file count contradicts the ingestion result")
    if result.decision == "processed":
        expected_counts = {
            "declared_rows": result.declared_rows,
            "raw_rows": result.raw_rows,
            "duplicate_no_op_rows": result.duplicate_no_op_rows,
            "accepted": result.accepted,
            "warned": result.warned,
            "quarantined": result.quarantined,
            "rejected": result.rejected,
        }
        if any(reconciliation.get(key) != expected for key, expected in expected_counts.items()):
            raise CloudPublicationError("local report counts contradict the ingestion result")
    return report, inventory_by_path


def _safe_segment(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
        raise CloudPublicationError(f"{label} is unsafe for a cloud identity")
    return value


def _table_name(source_identity: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", source_identity).strip("_").lower()
    if not value or value[0].isdigit():
        value = f"source_{value}"
    if _RELATION_ID.fullmatch(value) is None:
        raise CloudPublicationError("source identity cannot form a safe raw table name")
    return value


def _event_date(value: object) -> str:
    if not isinstance(value, str):
        raise CloudPublicationError("ingestion timestamp is missing from local report")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CloudPublicationError("ingestion timestamp is invalid") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CloudPublicationError("ingestion timestamp must be timezone-aware")
    return timestamp.date().isoformat()


def _job_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:40]
    return f"claimsflow_{kind}_{digest}"


def _content_evidence(
    inventory: dict[str, dict[str, object]],
    relative_path: str,
) -> tuple[str, int]:
    item = inventory.get(relative_path)
    if item is None:
        raise CloudPublicationError(f"artifact is absent from hashed inventory: {relative_path}")
    checksum = item.get("sha256")
    byte_size = item.get("byte_size")
    if (
        not isinstance(checksum, str)
        or _SHA256.fullmatch(checksum) is None
        or not isinstance(byte_size, int)
        or byte_size < 0
    ):
        raise CloudPublicationError("artifact inventory hash or size evidence is invalid")
    return checksum, byte_size


def publish_ingestion_to_cloud(
    result: IngestionResult,
    landing_store: LandingObjectStore,
    warehouse: RawAuditWarehouse,
    *,
    project: str,
    raw_dataset: str = "claimsflow_raw",
    audit_dataset: str = "claimsflow_audit",
) -> CloudPublicationResult:
    """Publish verified local evidence through generation and load-job gates."""

    if _PROJECT_ID.fullmatch(project) is None:
        raise CloudPublicationError("project must be a valid lowercase Google Cloud project ID")
    if _RELATION_ID.fullmatch(raw_dataset) is None:
        raise CloudPublicationError("raw_dataset is not a safe BigQuery dataset ID")
    if _RELATION_ID.fullmatch(audit_dataset) is None:
        raise CloudPublicationError("audit_dataset is not a safe BigQuery dataset ID")

    report, inventory = _verified_report(result)
    if result.decision == "duplicate_no_op":
        return CloudPublicationResult(
            batch_id=result.batch_id,
            decision="duplicate_no_op",
            landing_objects=(),
            raw_loads=(),
            audit_load=None,
            raw_rows=0,
            reconciled=True,
        )

    batch_id = _safe_segment(result.batch_id, "batch_id")
    delivery_date = _event_date(report.get("ingested_at_utc"))
    manifest_relative = "landing/manifest.json"
    manifest_path = _verified_relative_file(result.artifact_directory, manifest_relative)
    manifest_checksum, manifest_size = _content_evidence(inventory, manifest_relative)
    upload_requests = [
        LandingObjectRequest(
            source_path=manifest_path,
            object_name=(
                f"source=manifest/delivery_date={delivery_date}/batch_id={batch_id}/manifest.json"
            ),
            checksum_sha256=manifest_checksum,
            byte_size=manifest_size,
            content_type="application/json",
            metadata={
                "synthetic_only": "true",
                "artifact_kind": "source_manifest",
                "batch_id": batch_id,
                "manifest_sha256": result.manifest_sha256,
            },
        )
    ]
    raw_requests: list[RawLoadRequest] = []
    table_sources: dict[str, str] = {}

    raw_files = cast(list[object], report["files"])
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            raise CloudPublicationError("local report contains an invalid file entry")
        file_item = cast(dict[str, Any], raw_file)
        decision = file_item.get("decision")
        if decision == "duplicate_no_op":
            continue
        if decision != "processed":
            raise CloudPublicationError("local report contains an unsupported file decision")
        source_identity = _safe_segment(file_item.get("source_identity"), "source_identity")
        source_system = _safe_segment(file_item.get("source_system"), "source_system")
        contract_id = _safe_segment(file_item.get("contract_id"), "contract_id")
        contract_version = _safe_segment(file_item.get("contract_version"), "contract_version")
        file_name = _safe_segment(file_item.get("file_name"), "file_name")
        if Path(file_name).name != file_name:
            raise CloudPublicationError("source file name must not contain a path")
        table_name = _table_name(source_identity)
        prior_source = table_sources.setdefault(table_name, source_identity)
        if prior_source != source_identity:
            raise CloudPublicationError("source identities collide on one raw table name")

        artifacts = file_item.get("artifacts")
        counts = file_item.get("counts")
        if not isinstance(artifacts, dict) or not isinstance(counts, dict):
            raise CloudPublicationError("local report file evidence is incomplete")
        landing_relative = artifacts.get("landing")
        raw_relative = artifacts.get("raw")
        raw_rows = counts.get("raw")
        declared_rows = file_item.get("declared_rows")
        source_checksum = file_item.get("checksum_sha256")
        if (
            not isinstance(landing_relative, str)
            or not isinstance(raw_relative, str)
            or not isinstance(raw_rows, int)
            or raw_rows < 0
            or raw_rows != declared_rows
            or not isinstance(source_checksum, str)
            or _SHA256.fullmatch(source_checksum) is None
        ):
            raise CloudPublicationError("processed file paths, counts, or checksum are invalid")
        landing_path = _verified_relative_file(result.artifact_directory, landing_relative)
        landing_checksum, landing_size = _content_evidence(inventory, landing_relative)
        if landing_checksum != source_checksum:
            raise CloudPublicationError("landed file checksum contradicts the file report")
        upload_requests.append(
            LandingObjectRequest(
                source_path=landing_path,
                object_name=(
                    f"source={source_identity}/delivery_date={delivery_date}/"
                    f"batch_id={batch_id}/{file_name}"
                ),
                checksum_sha256=landing_checksum,
                byte_size=landing_size,
                content_type="text/csv",
                metadata={
                    "synthetic_only": "true",
                    "artifact_kind": "source_file",
                    "batch_id": batch_id,
                    "source_identity": source_identity,
                    "source_system": source_system,
                    "contract_id": contract_id,
                    "contract_version": contract_version,
                    "source_checksum_sha256": source_checksum,
                    "declared_rows": str(declared_rows),
                },
            )
        )

        raw_path = _verified_relative_file(result.artifact_directory, raw_relative)
        raw_checksum, raw_size = _content_evidence(inventory, raw_relative)
        raw_requests.append(
            RawLoadRequest(
                source_path=raw_path,
                destination_table=f"{project}.{raw_dataset}.{table_name}",
                job_id=_job_id("raw", batch_id, source_identity, raw_checksum),
                checksum_sha256=raw_checksum,
                byte_size=raw_size,
                expected_rows=raw_rows,
                batch_id=batch_id,
                source_identity=source_identity,
            )
        )

    if len(upload_requests) != result.processed_files + 1:
        raise CloudPublicationError("processed file count does not match the cloud upload plan")
    if len(raw_requests) != result.processed_files:
        raise CloudPublicationError("processed file count does not match the raw load plan")
    if sum(request.expected_rows for request in raw_requests) != result.raw_rows:
        raise CloudPublicationError("raw load plan does not reconcile to the local result")

    landing_receipts = tuple(landing_store.upload(request) for request in upload_requests)
    for receipt in landing_receipts:
        landing_store.verify(receipt)

    raw_receipts = tuple(warehouse.load_raw(request) for request in raw_requests)
    raw_output_rows = sum(receipt.output_rows for receipt in raw_receipts)
    if raw_output_rows != result.raw_rows:
        raise CloudPublicationError("completed BigQuery raw loads do not reconcile")

    event_id = f"cloud-publication-{batch_id}-{result.report_sha256[:16]}"
    audit_record: dict[str, object] = {
        "event_id": event_id,
        "event_at_utc": report["ingested_at_utc"],
        "batch_id": batch_id,
        "event_type": "cloud_raw_publication",
        "decision": "published",
        "synthetic_only": True,
        "manifest_sha256": result.manifest_sha256,
        "report_sha256": result.report_sha256,
        "landing_object_count": len(landing_receipts),
        "raw_load_count": len(raw_receipts),
        "raw_rows": raw_output_rows,
        "reconciled": True,
        "evidence": {
            "landing_objects": [receipt.as_dict() for receipt in landing_receipts],
            "raw_loads": [receipt.as_dict() for receipt in raw_receipts],
            "local_reconciliation": report["reconciliation"],
        },
    }
    audit_request = AuditWriteRequest(
        destination_table=f"{project}.{audit_dataset}.ingestion_publications",
        job_id=_job_id("audit", batch_id, result.report_sha256),
        event_id=event_id,
        record=audit_record,
    )
    audit_receipt = warehouse.write_audit(audit_request)
    return CloudPublicationResult(
        batch_id=batch_id,
        decision="published",
        landing_objects=landing_receipts,
        raw_loads=raw_receipts,
        audit_load=audit_receipt,
        raw_rows=raw_output_rows,
        reconciled=True,
    )
