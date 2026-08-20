"""Typed cloud-publication records for synthetic ingestion evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CloudPublicationDecision = Literal["published", "duplicate_no_op"]


@dataclass(frozen=True, slots=True)
class LandingObjectRequest:
    """One immutable local artifact to publish to the landing bucket."""

    source_path: Path
    object_name: str
    checksum_sha256: str
    byte_size: int
    content_type: str
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class LandingObjectReceipt:
    """Generation-pinned evidence returned by the landing object store."""

    bucket: str
    object_name: str
    generation: int
    checksum_sha256: str
    byte_size: int

    @property
    def uri(self) -> str:
        """Return the stable object URI without pretending GCS supports URI generations."""

        return f"gs://{self.bucket}/{self.object_name}"

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe audit evidence."""

        return {
            "uri": self.uri,
            "generation": self.generation,
            "checksum_sha256": self.checksum_sha256,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True, slots=True)
class RawLoadRequest:
    """One verified JSON Lines artifact to append to a raw BigQuery table."""

    source_path: Path
    destination_table: str
    job_id: str
    checksum_sha256: str
    byte_size: int
    expected_rows: int
    batch_id: str
    source_identity: str


@dataclass(frozen=True, slots=True)
class AuditWriteRequest:
    """One immutable cloud-publication audit event."""

    destination_table: str
    job_id: str
    event_id: str
    record: dict[str, object]


@dataclass(frozen=True, slots=True)
class BigQueryLoadReceipt:
    """Completed deterministic BigQuery load-job evidence."""

    destination_table: str
    job_id: str
    output_rows: int

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe audit evidence."""

        return {
            "destination_table": self.destination_table,
            "job_id": self.job_id,
            "output_rows": self.output_rows,
        }


@dataclass(frozen=True, slots=True)
class CloudPublicationResult:
    """Control-plane summary for one cloud publication attempt."""

    batch_id: str
    decision: CloudPublicationDecision
    landing_objects: tuple[LandingObjectReceipt, ...]
    raw_loads: tuple[BigQueryLoadReceipt, ...]
    audit_load: BigQueryLoadReceipt | None
    raw_rows: int
    reconciled: bool
