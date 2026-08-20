from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from claimsflow.domain.cloud import (
    AuditWriteRequest,
    BigQueryLoadReceipt,
    LandingObjectReceipt,
    LandingObjectRequest,
    RawLoadRequest,
)
from claimsflow.domain.ingestion import IngestionResult
from claimsflow.generator import GenerationConfig, generate_delivery
from claimsflow.ingestion import ingest_delivery
from claimsflow.ingestion.cloud_publication import (
    CloudPublicationError,
    publish_ingestion_to_cloud,
)

ROOT = Path(__file__).resolve().parents[2]


class RecordingLandingStore:
    def __init__(self, events: list[str], *, fail_verification: bool = False) -> None:
        self.events = events
        self.fail_verification = fail_verification
        self.requests: list[LandingObjectRequest] = []

    def upload(self, request: LandingObjectRequest) -> LandingObjectReceipt:
        self.events.append(f"upload:{request.object_name}")
        self.requests.append(request)
        assert request.metadata["synthetic_only"] == "true"
        assert hashlib.sha256(request.source_path.read_bytes()).hexdigest() == (
            request.checksum_sha256
        )
        return LandingObjectReceipt(
            bucket="claimsflow-synthetic-landing",
            object_name=request.object_name,
            generation=len(self.requests),
            checksum_sha256=request.checksum_sha256,
            byte_size=request.byte_size,
        )

    def verify(self, receipt: LandingObjectReceipt) -> None:
        self.events.append(f"verify:{receipt.object_name}")
        if self.fail_verification:
            raise RuntimeError("injected cloud checksum mismatch")


class RecordingWarehouse:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.raw_requests: list[RawLoadRequest] = []
        self.audit_requests: list[AuditWriteRequest] = []

    def load_raw(self, request: RawLoadRequest) -> BigQueryLoadReceipt:
        self.events.append(f"raw:{request.source_identity}")
        self.raw_requests.append(request)
        return BigQueryLoadReceipt(
            destination_table=request.destination_table,
            job_id=request.job_id,
            output_rows=request.expected_rows,
        )

    def write_audit(self, request: AuditWriteRequest) -> BigQueryLoadReceipt:
        self.events.append(f"audit:{request.event_id}")
        self.audit_requests.append(request)
        return BigQueryLoadReceipt(
            destination_table=request.destination_table,
            job_id=request.job_id,
            output_rows=1,
        )


def _ingested(tmp_path: Path) -> tuple[Path, IngestionResult]:
    delivery = generate_delivery(
        GenerationConfig.from_values(seed=42, claim_count=2, service_month="2026-07"),
        tmp_path / "delivery",
    )
    result = ingest_delivery(
        delivery.manifest_path,
        tmp_path / "workspace",
        ROOT / "contracts/source-data",
    )
    return delivery.manifest_path, result


def test_cloud_publication_orders_generation_gate_before_raw_and_audit(tmp_path: Path) -> None:
    _, raw_result = _ingested(tmp_path)
    result = raw_result
    events: list[str] = []
    landing = RecordingLandingStore(events)
    warehouse = RecordingWarehouse(events)

    publication = publish_ingestion_to_cloud(
        result,
        landing,
        warehouse,
        project="claimsflow-demo-synthetic",
    )

    assert publication.decision == "published"
    assert publication.reconciled is True
    assert len(publication.landing_objects) == 15
    assert len(publication.raw_loads) == 14
    assert publication.raw_rows == result.raw_rows
    assert len(warehouse.audit_requests) == 1
    assert all(event.startswith("upload:") for event in events[:15])
    assert all(event.startswith("verify:") for event in events[15:30])
    assert all(event.startswith("raw:") for event in events[30:44])
    assert events[44].startswith("audit:")
    assert landing.requests[0].object_name.startswith("source=manifest/delivery_date=")
    assert all(
        request.destination_table.startswith("claimsflow-demo-synthetic.claimsflow_raw.")
        for request in warehouse.raw_requests
    )
    audit = warehouse.audit_requests[0].record
    assert audit["landing_object_count"] == 15
    assert audit["raw_load_count"] == 14
    assert audit["raw_rows"] == result.raw_rows


def test_cloud_publication_detects_local_tamper_before_any_external_write(tmp_path: Path) -> None:
    _, raw_result = _ingested(tmp_path)
    result = raw_result
    claims = next((result.artifact_directory / "landing/files").glob("synthetic_ehr_claims_*.csv"))
    claims.write_text(claims.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    events: list[str] = []

    with pytest.raises(CloudPublicationError, match="artifact inventory"):
        publish_ingestion_to_cloud(
            result,
            RecordingLandingStore(events),
            RecordingWarehouse(events),
            project="claimsflow-demo-synthetic",
        )

    assert events == []


def test_cloud_checksum_failure_blocks_every_bigquery_write(tmp_path: Path) -> None:
    _, raw_result = _ingested(tmp_path)
    events: list[str] = []
    warehouse = RecordingWarehouse(events)

    with pytest.raises(RuntimeError, match="injected cloud checksum mismatch"):
        publish_ingestion_to_cloud(
            raw_result,
            RecordingLandingStore(events, fail_verification=True),
            warehouse,
            project="claimsflow-demo-synthetic",
        )

    assert warehouse.raw_requests == []
    assert warehouse.audit_requests == []
    assert sum(event.startswith("upload:") for event in events) == 15


def test_local_duplicate_is_a_cloud_no_op(tmp_path: Path) -> None:
    manifest, first_result = _ingested(tmp_path)
    duplicate = ingest_delivery(
        manifest,
        first_result.workspace,
        ROOT / "contracts/source-data",
    )
    events: list[str] = []

    publication = publish_ingestion_to_cloud(
        duplicate,
        RecordingLandingStore(events),
        RecordingWarehouse(events),
        project="claimsflow-demo-synthetic",
    )

    assert publication.decision == "duplicate_no_op"
    assert publication.raw_rows == 0
    assert events == []
