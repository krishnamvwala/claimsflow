from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

import pytest

from claimsflow.adapters.bigquery_raw import (
    BigQueryRawAuditError,
    GoogleBigQueryRawAuditAdapter,
)
from claimsflow.adapters.gcs_landing import (
    GoogleCloudStorageLandingAdapter,
    LandingStorageError,
)
from claimsflow.domain.cloud import AuditWriteRequest, LandingObjectRequest, RawLoadRequest


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakePreconditionError(RuntimeError):
    pass


class FakeBlob:
    def __init__(
        self,
        bucket: FakeBucket,
        name: str,
        requested_generation: int | None,
    ) -> None:
        self._bucket = bucket
        self._name = name
        self._requested_generation = requested_generation
        self.generation: int | None = None
        self.size: int | None = None
        self.metadata: dict[str, str] | None = None

    def _record(self) -> tuple[bytes, int, dict[str, str]]:
        record = self._bucket.records.get(self._name)
        if record is None:
            raise FakePreconditionError("object does not exist")
        data, generation, metadata = record
        if self._requested_generation is not None and generation != self._requested_generation:
            raise FakePreconditionError("requested generation does not exist")
        return data, generation, metadata

    def upload_from_filename(
        self,
        filename: str,
        *,
        content_type: str,
        if_generation_match: int,
        checksum: str,
    ) -> None:
        assert content_type
        assert if_generation_match == 0
        assert checksum == "auto"
        self._bucket.upload_attempts.append((self._name, if_generation_match))
        if self._name in self._bucket.records:
            raise FakePreconditionError("live object already exists")
        data = Path(filename).read_bytes()
        generation = self._bucket.next_generation
        self._bucket.next_generation += 1
        metadata = dict(self.metadata or {})
        self._bucket.records[self._name] = (data, generation, metadata)
        self.generation = generation
        self.size = len(data)
        self.metadata = metadata

    def reload(self, *, if_generation_match: int | None = None) -> None:
        data, generation, metadata = self._record()
        if if_generation_match is not None and generation != if_generation_match:
            raise FakePreconditionError("generation precondition failed")
        self.generation = generation
        self.size = len(data)
        self.metadata = dict(metadata)

    def download_to_file(
        self,
        file_obj: BinaryIO,
        *,
        if_generation_match: int,
        checksum: str,
    ) -> None:
        assert checksum == "auto"
        data, generation, _ = self._record()
        if generation != if_generation_match:
            raise FakePreconditionError("download generation precondition failed")
        file_obj.write(data)


class FakeBucket:
    def __init__(self) -> None:
        self.records: dict[str, tuple[bytes, int, dict[str, str]]] = {}
        self.upload_attempts: list[tuple[str, int]] = []
        self.next_generation = 1

    def blob(self, blob_name: str, generation: int | None = None) -> FakeBlob:
        return FakeBlob(self, blob_name, generation)


class FakeStorageClient:
    def __init__(self) -> None:
        self.fake_bucket = FakeBucket()

    def bucket(self, bucket_name: str) -> FakeBucket:
        assert bucket_name == "claimsflow-synthetic-landing"
        return self.fake_bucket


def _landing_request(path: Path) -> LandingObjectRequest:
    data = path.read_bytes()
    return LandingObjectRequest(
        source_path=path,
        object_name="source=claims/delivery_date=2026-08-20/batch_id=batch-1/claims.csv",
        checksum_sha256=_checksum(data),
        byte_size=len(data),
        content_type="text/csv",
        metadata={
            "synthetic_only": "true",
            "artifact_kind": "source_file",
            "batch_id": "batch-1",
        },
    )


def test_gcs_upload_is_create_only_and_generation_verified(tmp_path: Path) -> None:
    source = tmp_path / "claims.csv"
    source.write_bytes(b"claim_id,amount\nSYN-1,100.00\n")
    client = FakeStorageClient()
    adapter = GoogleCloudStorageLandingAdapter(
        client,
        "claimsflow-synthetic-landing",
        precondition_error_types=(FakePreconditionError,),
    )

    receipt = adapter.upload(_landing_request(source))
    adapter.verify(receipt)

    assert receipt.generation == 1
    assert receipt.uri.startswith("gs://claimsflow-synthetic-landing/source=claims/")
    assert client.fake_bucket.upload_attempts == [(receipt.object_name, 0)]


def test_gcs_exact_replay_proves_existing_object_instead_of_overwriting(tmp_path: Path) -> None:
    source = tmp_path / "claims.csv"
    source.write_bytes(b"claim_id\nSYN-1\n")
    client = FakeStorageClient()
    adapter = GoogleCloudStorageLandingAdapter(
        client,
        "claimsflow-synthetic-landing",
        precondition_error_types=(FakePreconditionError,),
    )
    request = _landing_request(source)

    first = adapter.upload(request)
    second = adapter.upload(request)

    assert second == first
    assert len(client.fake_bucket.records) == 1
    assert client.fake_bucket.upload_attempts == [(request.object_name, 0)] * 2


def test_gcs_verification_detects_changed_content_at_same_generation(tmp_path: Path) -> None:
    source = tmp_path / "claims.csv"
    source.write_bytes(b"claim_id\nSYN-1\n")
    client = FakeStorageClient()
    adapter = GoogleCloudStorageLandingAdapter(
        client,
        "claimsflow-synthetic-landing",
        precondition_error_types=(FakePreconditionError,),
    )
    receipt = adapter.upload(_landing_request(source))
    _, generation, metadata = client.fake_bucket.records[receipt.object_name]
    client.fake_bucket.records[receipt.object_name] = (b"changed-content", generation, metadata)

    with pytest.raises(
        LandingStorageError,
        match=r"byte size changed|checksum verification",
    ):
        adapter.verify(receipt)


def test_gcs_rejects_non_synthetic_or_mutated_local_input(tmp_path: Path) -> None:
    source = tmp_path / "claims.csv"
    source.write_bytes(b"claim_id\nSYN-1\n")
    client = FakeStorageClient()
    adapter = GoogleCloudStorageLandingAdapter(client, "claimsflow-synthetic-landing")
    request = _landing_request(source)
    source.write_bytes(b"claim_id\nSYN-2\n")

    with pytest.raises(LandingStorageError, match="checksum changed"):
        adapter.upload(request)

    unsafe = LandingObjectRequest(
        source_path=source,
        object_name="../claims.csv",
        checksum_sha256=_checksum(source.read_bytes()),
        byte_size=source.stat().st_size,
        content_type="text/csv",
        metadata={"synthetic_only": "false"},
    )
    with pytest.raises(LandingStorageError):
        adapter.upload(unsafe)


class FakeBigQueryConflict(RuntimeError):
    pass


class FakeLoadJob:
    def __init__(
        self,
        job_id: str,
        destination: str,
        output_rows: int,
        *,
        error_result: object | None = None,
    ) -> None:
        self.job_id = job_id
        self.destination: object | None = destination
        self.output_rows: int | None = output_rows
        self.error_result = error_result
        self.errors: Sequence[object] | None = None

    def result(self, *, timeout: float | None = None) -> FakeLoadJob:
        assert timeout is not None and timeout > 0
        return self


class FakeBigQueryClient:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeLoadJob] = {}
        self.raw_starts = 0
        self.audit_starts = 0
        self.configs: list[object] = []
        self.force_output_rows: int | None = None

    def load_table_from_file(
        self,
        file_obj: BinaryIO,
        destination: str,
        *,
        rewind: bool,
        size: int,
        job_id: str,
        location: str,
        job_config: object,
    ) -> FakeLoadJob:
        assert rewind is False
        assert location == "US"
        data = file_obj.read()
        assert len(data) == size
        self.raw_starts += 1
        self.configs.append(job_config)
        if job_id in self.jobs:
            raise FakeBigQueryConflict("job exists")
        output_rows = (
            data.count(b"\n") if self.force_output_rows is None else self.force_output_rows
        )
        job = FakeLoadJob(job_id, destination, output_rows)
        self.jobs[job_id] = job
        return job

    def load_table_from_json(
        self,
        json_rows: Sequence[dict[str, object]],
        destination: str,
        *,
        job_id: str,
        location: str,
        job_config: object,
    ) -> FakeLoadJob:
        assert location == "US"
        self.audit_starts += 1
        self.configs.append(job_config)
        if job_id in self.jobs:
            raise FakeBigQueryConflict("job exists")
        job = FakeLoadJob(job_id, destination, len(json_rows))
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str, *, location: str, project: str) -> FakeLoadJob:
        assert location == "US"
        assert project == "claimsflow-demo-synthetic"
        return self.jobs[job_id]


def _raw_request(path: Path) -> RawLoadRequest:
    data = path.read_bytes()
    return RawLoadRequest(
        source_path=path,
        destination_table="claimsflow-demo-synthetic.claimsflow_raw.claims",
        job_id="claimsflow_raw_abc123",
        checksum_sha256=_checksum(data),
        byte_size=len(data),
        expected_rows=data.count(b"\n"),
        batch_id="batch-1",
        source_identity="claims",
    )


def _bigquery_adapter(client: FakeBigQueryClient) -> GoogleBigQueryRawAuditAdapter:
    return GoogleBigQueryRawAuditAdapter(
        client,
        project="claimsflow-demo-synthetic",
        location="US",
        conflict_error_types=(FakeBigQueryConflict,),
        raw_config_factory=lambda: {"kind": "raw"},
        audit_config_factory=lambda: {"kind": "audit"},
    )


def test_bigquery_raw_load_is_append_only_reconciled_and_replay_safe(tmp_path: Path) -> None:
    source = tmp_path / "claims.jsonl"
    source.write_bytes(b'{"synthetic_only":true}\n{"synthetic_only":true}\n')
    client = FakeBigQueryClient()
    adapter = _bigquery_adapter(client)
    request = _raw_request(source)

    first = adapter.load_raw(request)
    second = adapter.load_raw(request)

    assert first == second
    assert first.output_rows == 2
    assert client.raw_starts == 2
    assert len(client.jobs) == 1
    assert client.configs == [{"kind": "raw"}, {"kind": "raw"}]


def test_bigquery_raw_load_blocks_tamper_and_row_count_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "claims.jsonl"
    source.write_bytes(b'{"synthetic_only":true}\n')
    request = _raw_request(source)
    source.write_bytes(b'{"synthetic_only":false}\n')

    with pytest.raises(
        BigQueryRawAuditError,
        match=r"byte size changed|checksum changed",
    ):
        _bigquery_adapter(FakeBigQueryClient()).load_raw(request)

    source.write_bytes(b'{"synthetic_only":true}\n')
    mismatch_client = FakeBigQueryClient()
    mismatch_client.force_output_rows = 0
    with pytest.raises(BigQueryRawAuditError, match="row count does not reconcile"):
        _bigquery_adapter(mismatch_client).load_raw(_raw_request(source))


def test_bigquery_audit_write_is_deterministic_and_synthetic_only() -> None:
    client = FakeBigQueryClient()
    adapter = _bigquery_adapter(client)
    record: dict[str, object] = {
        "event_id": "cloud-publication-batch-1",
        "synthetic_only": True,
    }
    request = AuditWriteRequest(
        destination_table=("claimsflow-demo-synthetic.claimsflow_audit.ingestion_publications"),
        job_id="claimsflow_audit_abc123",
        event_id="cloud-publication-batch-1",
        record=record,
    )

    first = adapter.write_audit(request)
    second = adapter.write_audit(request)

    assert first == second
    assert first.output_rows == 1
    assert client.audit_starts == 2
    assert len(client.jobs) == 1

    record["synthetic_only"] = False
    with pytest.raises(BigQueryRawAuditError, match="synthetic_only"):
        adapter.write_audit(request)
