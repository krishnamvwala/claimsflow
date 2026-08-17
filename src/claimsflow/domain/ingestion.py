"""Typed records for the local ingestion trust boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Disposition = Literal["accepted", "accepted_with_warning", "quarantined", "rejected"]
DeliveryDecision = Literal["processed", "duplicate_no_op"]


class RegistryCollisionError(RuntimeError):
    """Raised when an immutable source version reappears with different content."""

    def __init__(
        self,
        *,
        source_identity: str,
        natural_key: str,
        version_discriminator: str,
        existing_payload_sha256: str,
        incoming_payload_sha256: str,
        existing_batch_id: str,
    ) -> None:
        super().__init__(
            "DQ-CMN-011: immutable source version collides with different payload "
            f"from batch {existing_batch_id}"
        )
        self.details: dict[str, object] = {
            "rule_id": "DQ-CMN-011",
            "source_identity": source_identity,
            "natural_key": natural_key,
            "version_discriminator": version_discriminator,
            "existing_payload_sha256": existing_payload_sha256,
            "incoming_payload_sha256": incoming_payload_sha256,
            "existing_batch_id": existing_batch_id,
        }


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One stable validation or normalization outcome for a source row."""

    rule_id: str
    severity: Literal["warning", "error", "critical"]
    disposition: Disposition
    reason: str
    field: str | None = None
    normalized_value: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe evidence without exposing values unless normalized."""

        result: dict[str, object] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "disposition": self.disposition,
            "reason": self.reason,
        }
        if self.field is not None:
            result["field"] = self.field
        if self.normalized_value is not None:
            result["normalized_value"] = self.normalized_value
        return result


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    """Immutable source payload plus its ingestion-added lineage and disposition."""

    source_identity: str
    source_record_id: str
    natural_key: str
    version_discriminator: str
    payload_sha256: str
    disposition: Disposition
    original_payload: dict[str, str]
    normalized_payload: dict[str, str]
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class FileIngestionSummary:
    """Reconciled evidence for one file in the delivery manifest."""

    source_identity: str
    source_family: str
    dataset: str | None
    source_system: str
    file_name: str
    checksum_sha256: str
    contract_id: str
    contract_version: str
    declared_rows: int
    decision: DeliveryDecision
    raw_rows: int
    accepted: int
    warned: int
    quarantined: int
    rejected: int
    duplicate_of_batch_id: str | None
    landing_path: str | None
    raw_path: str | None
    quality_path: str | None
    quarantine_path: str | None
    rejected_path: str | None

    @property
    def disposition_rows(self) -> int:
        return self.accepted + self.warned + self.quarantined + self.rejected


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Safe CLI-facing summary for one attempted delivery ingestion."""

    batch_id: str
    decision: DeliveryDecision
    workspace: Path
    artifact_directory: Path
    report_path: Path
    report_sha256: str
    manifest_sha256: str
    file_count: int
    processed_files: int
    duplicate_files: int
    declared_rows: int
    raw_rows: int
    duplicate_no_op_rows: int
    accepted: int
    warned: int
    quarantined: int
    rejected: int
    reconciled: bool


@dataclass(frozen=True, slots=True)
class IngestionIntent:
    """Durable publication intent used to recover an interrupted ingestion."""

    batch_id: str
    manifest_sha256: str
    staging_directory: Path
    final_directory: Path
    report_sha256: str
    occurred_at_utc: str
