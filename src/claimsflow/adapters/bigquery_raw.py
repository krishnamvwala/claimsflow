"""Deterministic BigQuery raw and audit load adapter."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from claimsflow.domain.cloud import AuditWriteRequest, BigQueryLoadReceipt, RawLoadRequest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_RELATION_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


class BigQueryRawAuditError(RuntimeError):
    """Raised when a raw or audit append cannot be proven complete."""


class _LoadJob(Protocol):
    job_id: str
    output_rows: int | None
    error_result: object | None
    errors: Sequence[object] | None
    destination: object | None

    def result(self, *, timeout: float | None = None) -> object: ...


class _BigQueryClient(Protocol):
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
    ) -> _LoadJob: ...

    def load_table_from_json(
        self,
        json_rows: Sequence[dict[str, object]],
        destination: str,
        *,
        job_id: str,
        location: str,
        job_config: object,
    ) -> _LoadJob: ...

    def get_job(self, job_id: str, *, location: str, project: str) -> _LoadJob: ...


type LoadConfigFactory = Callable[[], object]


def _raw_load_config() -> object:
    bigquery = import_module("google.cloud.bigquery")

    lineage_fields = (
        bigquery.SchemaField("batch_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source_identity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source_family", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("dataset", "STRING"),
        bigquery.SchemaField("source_system", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source_file", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source_checksum_sha256", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source_row_number", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("contract_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("contract_version", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("ingested_at_utc", "TIMESTAMP", mode="REQUIRED"),
    )
    return cast(
        object,
        bigquery.LoadJobConfig(
            schema=(
                bigquery.SchemaField("synthetic_only", "BOOL", mode="REQUIRED"),
                bigquery.SchemaField("lineage", "RECORD", mode="REQUIRED", fields=lineage_fields),
                bigquery.SchemaField("source_record_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("natural_key", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("version_discriminator", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("payload_sha256", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("processing_status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("disposition", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("issues", "JSON"),
                bigquery.SchemaField("raw_payload", "JSON", mode="REQUIRED"),
                bigquery.SchemaField("normalized_payload", "JSON", mode="REQUIRED"),
            ),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            autodetect=False,
            ignore_unknown_values=False,
            max_bad_records=0,
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
            ),
            clustering_fields=["source_record_id", "natural_key", "processing_status"],
        ),
    )


def _audit_load_config() -> object:
    bigquery = import_module("google.cloud.bigquery")

    return cast(
        object,
        bigquery.LoadJobConfig(
            schema=(
                bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("event_at_utc", "TIMESTAMP", mode="REQUIRED"),
                bigquery.SchemaField("batch_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("event_type", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("decision", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("synthetic_only", "BOOL", mode="REQUIRED"),
                bigquery.SchemaField("manifest_sha256", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("report_sha256", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("landing_object_count", "INT64", mode="REQUIRED"),
                bigquery.SchemaField("raw_load_count", "INT64", mode="REQUIRED"),
                bigquery.SchemaField("raw_rows", "INT64", mode="REQUIRED"),
                bigquery.SchemaField("reconciled", "BOOL", mode="REQUIRED"),
                bigquery.SchemaField("evidence", "JSON", mode="REQUIRED"),
            ),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            autodetect=False,
            ignore_unknown_values=False,
            max_bad_records=0,
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="event_at_utc",
            ),
            clustering_fields=["batch_id", "event_type", "decision"],
        ),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_table_id(value: str, project: str) -> str:
    parts = value.split(".")
    if (
        len(parts) != 3
        or parts[0] != project
        or _PROJECT_ID.fullmatch(parts[0]) is None
        or any(_RELATION_ID.fullmatch(part) is None for part in parts[1:])
    ):
        raise BigQueryRawAuditError("destination table must be project.dataset.table")
    return value


class GoogleBigQueryRawAuditAdapter:
    """Append-only loader using deterministic job IDs for safe task replay."""

    def __init__(
        self,
        client: _BigQueryClient,
        *,
        project: str,
        location: str,
        conflict_error_types: tuple[type[BaseException], ...] = (),
        raw_config_factory: LoadConfigFactory = _raw_load_config,
        audit_config_factory: LoadConfigFactory = _audit_load_config,
        job_timeout_seconds: float = 300.0,
    ) -> None:
        if _PROJECT_ID.fullmatch(project) is None:
            raise ValueError("project must be a valid lowercase Google Cloud project ID")
        if not location.strip():
            raise ValueError("location cannot be blank")
        if job_timeout_seconds <= 0:
            raise ValueError("job_timeout_seconds must be positive")
        self._client = client
        self.project = project
        self.location = location
        self._conflict_error_types = conflict_error_types
        self._raw_config_factory = raw_config_factory
        self._audit_config_factory = audit_config_factory
        self._job_timeout_seconds = job_timeout_seconds

    @classmethod
    def from_default_credentials(
        cls,
        *,
        project: str,
        location: str,
    ) -> GoogleBigQueryRawAuditAdapter:
        """Compose the adapter with Application Default Credentials only when requested."""

        exceptions = import_module("google.api_core.exceptions")
        bigquery = import_module("google.cloud.bigquery")
        conflict = cast(type[BaseException], exceptions.Conflict)
        client = cast(_BigQueryClient, bigquery.Client(project=project, location=location))
        return cls(
            client,
            project=project,
            location=location,
            conflict_error_types=(conflict,),
        )

    def _completed_receipt(
        self,
        job: _LoadJob,
        *,
        destination_table: str,
        job_id: str,
        expected_rows: int,
    ) -> BigQueryLoadReceipt:
        completed = cast(_LoadJob, job.result(timeout=self._job_timeout_seconds))
        if completed.error_result is not None or completed.errors:
            raise BigQueryRawAuditError(f"BigQuery load job {job_id} completed with errors")
        if completed.job_id != job_id:
            raise BigQueryRawAuditError("BigQuery returned a different job ID")
        if completed.destination is not None and str(completed.destination) != destination_table:
            raise BigQueryRawAuditError("BigQuery job destination does not match requested table")
        if completed.output_rows is None or int(completed.output_rows) != expected_rows:
            raise BigQueryRawAuditError(f"BigQuery load job {job_id} row count does not reconcile")
        return BigQueryLoadReceipt(
            destination_table=destination_table,
            job_id=job_id,
            output_rows=expected_rows,
        )

    def _existing_job(self, job_id: str) -> _LoadJob:
        return self._client.get_job(
            job_id,
            location=self.location,
            project=self.project,
        )

    def load_raw(self, request: RawLoadRequest) -> BigQueryLoadReceipt:
        """Append one verified JSON Lines file, or reattach to its prior load job."""

        destination = _validate_table_id(request.destination_table, self.project)
        if _JOB_ID.fullmatch(request.job_id) is None:
            raise BigQueryRawAuditError("raw load job ID is unsafe")
        if request.expected_rows < 0:
            raise BigQueryRawAuditError("raw expected row count cannot be negative")
        if not request.batch_id or not request.source_identity:
            raise BigQueryRawAuditError("raw load requires batch and source identities")
        if _SHA256.fullmatch(request.checksum_sha256) is None:
            raise BigQueryRawAuditError("raw checksum must be lowercase SHA-256")
        path = request.source_path
        if path.is_symlink() or not path.is_file():
            raise BigQueryRawAuditError(f"raw source is missing or unsafe: {path}")
        if path.stat().st_size != request.byte_size:
            raise BigQueryRawAuditError("raw source byte size changed before load")
        if _sha256(path) != request.checksum_sha256:
            raise BigQueryRawAuditError("raw source checksum changed before load")

        with path.open("rb") as source:
            try:
                job = self._client.load_table_from_file(
                    source,
                    destination,
                    rewind=False,
                    size=request.byte_size,
                    job_id=request.job_id,
                    location=self.location,
                    job_config=self._raw_config_factory(),
                )
            except self._conflict_error_types:
                job = self._existing_job(request.job_id)
        return self._completed_receipt(
            job,
            destination_table=destination,
            job_id=request.job_id,
            expected_rows=request.expected_rows,
        )

    def write_audit(self, request: AuditWriteRequest) -> BigQueryLoadReceipt:
        """Append one audit event, or reattach to its deterministic prior load job."""

        destination = _validate_table_id(request.destination_table, self.project)
        if _JOB_ID.fullmatch(request.job_id) is None:
            raise BigQueryRawAuditError("audit load job ID is unsafe")
        if not request.event_id or request.record.get("event_id") != request.event_id:
            raise BigQueryRawAuditError("audit event ID is missing or inconsistent")
        if request.record.get("synthetic_only") is not True:
            raise BigQueryRawAuditError("audit write requires synthetic_only=true")
        try:
            job = self._client.load_table_from_json(
                [request.record],
                destination,
                job_id=request.job_id,
                location=self.location,
                job_config=self._audit_config_factory(),
            )
        except self._conflict_error_types:
            job = self._existing_job(request.job_id)
        return self._completed_receipt(
            job,
            destination_table=destination,
            job_id=request.job_id,
            expected_rows=1,
        )
