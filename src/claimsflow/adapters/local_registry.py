"""SQLite control-plane registry for the local ingestion adapter."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, closing, contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, cast

from claimsflow.domain.ingestion import (
    FileIngestionSummary,
    IngestionIntent,
    IngestionResult,
    RegistryCollisionError,
)
from claimsflow.domain.quality import QualityReceiptCollisionError, QualityRunReceipt

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    manifest_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('processed', 'duplicate_no_op')),
    artifact_directory TEXT NOT NULL,
    report_path TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    processed_files INTEGER NOT NULL,
    duplicate_files INTEGER NOT NULL,
    declared_rows INTEGER NOT NULL,
    raw_rows INTEGER NOT NULL,
    duplicate_no_op_rows INTEGER NOT NULL,
    accepted INTEGER NOT NULL,
    warned INTEGER NOT NULL,
    quarantined INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    reconciled INTEGER NOT NULL CHECK (reconciled IN (0, 1)),
    registered_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    source_identity TEXT NOT NULL,
    source_family TEXT NOT NULL,
    dataset TEXT,
    source_system TEXT NOT NULL,
    file_name TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    declared_rows INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('processed', 'duplicate_no_op')),
    duplicate_of_batch_id TEXT,
    PRIMARY KEY (batch_id, source_identity)
);

CREATE INDEX IF NOT EXISTS deliveries_identity_checksum
ON deliveries(source_identity, checksum_sha256, decision);

CREATE UNIQUE INDEX IF NOT EXISTS one_processed_delivery_per_source_checksum
ON deliveries(source_identity, source_system, checksum_sha256)
WHERE decision = 'processed';

CREATE TABLE IF NOT EXISTS ingestion_intents (
    batch_id TEXT PRIMARY KEY,
    manifest_sha256 TEXT NOT NULL,
    staging_directory TEXT NOT NULL,
    final_directory TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_rows (
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    source_identity TEXT NOT NULL,
    file_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_record_id TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    version_discriminator TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    disposition TEXT NOT NULL,
    rule_ids_json TEXT NOT NULL,
    PRIMARY KEY (batch_id, file_name, source_row_number)
);

CREATE TABLE IF NOT EXISTS source_versions (
    source_identity TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    version_discriminator TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    first_batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    PRIMARY KEY (source_identity, natural_key, version_discriminator)
);

CREATE TABLE IF NOT EXISTS ingestion_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    reason TEXT,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS quality_runs (
    validation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    configuration_sha256 TEXT NOT NULL,
    evaluation_window_started_at_utc TEXT NOT NULL,
    corrections_sha256 TEXT NOT NULL,
    report_path TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    registered_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS quality_runs_batch_id
ON quality_runs(batch_id, evaluation_window_started_at_utc);
"""


class SqliteIngestionRegistry:
    """Persistent idempotency, lineage, and audit evidence for local runs."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().absolute()
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.workspace.is_symlink() or not self.workspace.is_dir():
            raise OSError(f"ingestion workspace is unsafe: {self.workspace}")
        self._resolved_workspace = self.workspace.resolve(strict=True)
        self.path = self.workspace / "ingestion-registry.sqlite3"
        self._validate_managed_children()
        with self._file_lock(self.workspace / ".registry-init.lock"):
            for attempt in range(5):
                try:
                    with closing(self._connect()) as connection, connection:
                        journal_mode = cast(
                            str, connection.execute("PRAGMA journal_mode").fetchone()[0]
                        )
                        if journal_mode.lower() != "wal":
                            connection.execute("PRAGMA journal_mode = WAL")
                        connection.executescript(_SCHEMA)
                    break
                except sqlite3.OperationalError as error:
                    if attempt == 4 or not any(
                        token in str(error).lower() for token in ("locked", "busy")
                    ):
                        raise
                    time.sleep(0.02 * (2**attempt))

    def _validate_managed_children(self) -> None:
        for name in ("batches", "collisions"):
            path = self.workspace / name
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise OSError(f"managed ingestion directory is unsafe: {path}")
            if path.exists() and path.resolve(strict=True).parent != self._resolved_workspace:
                raise OSError(f"managed ingestion directory escapes workspace: {path}")
        for name in (
            "ingestion-registry.sqlite3",
            "ingestion-registry.sqlite3-wal",
            "ingestion-registry.sqlite3-shm",
            "ingestion-registry.sqlite3-journal",
            ".registry-init.lock",
            ".ingestion.lock",
        ):
            path = self.workspace / name
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise OSError(f"managed ingestion file is unsafe: {path}")
            if path.exists() and path.resolve(strict=True).parent != self._resolved_workspace:
                raise OSError(f"managed ingestion file escapes workspace: {path}")

    @contextmanager
    def _file_lock(self, path: Path) -> Iterator[None]:
        if path.parent.resolve(strict=True) != self._resolved_workspace:
            raise OSError(f"managed lock escapes ingestion workspace: {path}")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError(f"managed ingestion lock is not a regular file: {path}")
            lock_file = os.fdopen(descriptor, "a+", encoding="utf-8")
        except Exception:
            os.close(descriptor)
            raise
        with lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(lock_file.fileno(), LOCK_UN)

    def exclusive_ingestion(self) -> AbstractContextManager[None]:
        """Serialize duplicate decisions through registration for this workspace."""

        return self._file_lock(self.workspace / ".ingestion.lock")

    def _connect(self) -> sqlite3.Connection:
        self._validate_managed_children()
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise OSError(f"managed ingestion registry is unsafe: {self.path}")
        if self.path.exists() and self.path.resolve(strict=True).parent != self._resolved_workspace:
            raise OSError(f"managed ingestion registry escapes workspace: {self.path}")
        connection = sqlite3.connect(self.path, timeout=30)
        if (
            self.path.is_symlink()
            or self.path.resolve(strict=True).parent != self._resolved_workspace
        ):
            connection.close()
            raise OSError(f"managed ingestion registry became unsafe: {self.path}")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def get_batch(self, batch_id: str) -> IngestionResult | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        if row is None:
            return None
        return IngestionResult(
            batch_id=cast(str, row["batch_id"]),
            decision=cast(Any, row["decision"]),
            workspace=self.workspace,
            artifact_directory=Path(cast(str, row["artifact_directory"])),
            report_path=Path(cast(str, row["report_path"])),
            report_sha256=cast(str, row["report_sha256"]),
            manifest_sha256=cast(str, row["manifest_sha256"]),
            file_count=cast(int, row["file_count"]),
            processed_files=cast(int, row["processed_files"]),
            duplicate_files=cast(int, row["duplicate_files"]),
            declared_rows=cast(int, row["declared_rows"]),
            raw_rows=cast(int, row["raw_rows"]),
            duplicate_no_op_rows=cast(int, row["duplicate_no_op_rows"]),
            accepted=cast(int, row["accepted"]),
            warned=cast(int, row["warned"]),
            quarantined=cast(int, row["quarantined"]),
            rejected=cast(int, row["rejected"]),
            reconciled=bool(row["reconciled"]),
        )

    def get_intent(self, batch_id: str) -> IngestionIntent | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_intents WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        if row is None:
            return None
        return IngestionIntent(
            batch_id=cast(str, row["batch_id"]),
            manifest_sha256=cast(str, row["manifest_sha256"]),
            staging_directory=Path(cast(str, row["staging_directory"])),
            final_directory=Path(cast(str, row["final_directory"])),
            report_sha256=cast(str, row["report_sha256"]),
            occurred_at_utc=cast(str, row["occurred_at_utc"]),
        )

    def get_quality_run(self, validation_id: str) -> QualityRunReceipt | None:
        """Return the durable report-hash receipt for one quality run."""

        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM quality_runs WHERE validation_id = ?", (validation_id,)
            ).fetchone()
        if row is None:
            return None
        return QualityRunReceipt(
            validation_id=cast(str, row["validation_id"]),
            batch_id=cast(str, row["batch_id"]),
            configuration_sha256=cast(str, row["configuration_sha256"]),
            evaluation_window_started_at_utc=cast(str, row["evaluation_window_started_at_utc"]),
            corrections_sha256=cast(str, row["corrections_sha256"]),
            report_path=Path(cast(str, row["report_path"])),
            report_sha256=cast(str, row["report_sha256"]),
            registered_at_utc=cast(str, row["registered_at_utc"]),
        )

    def register_quality_run(self, receipt: QualityRunReceipt) -> None:
        """Atomically register an immutable quality report hash or reject a collision."""

        values = (
            receipt.validation_id,
            receipt.batch_id,
            receipt.configuration_sha256,
            receipt.evaluation_window_started_at_utc,
            receipt.corrections_sha256,
            str(receipt.report_path),
            receipt.report_sha256,
            receipt.registered_at_utc,
        )
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM quality_runs WHERE validation_id = ?",
                    (receipt.validation_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO quality_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values
                    )
                else:
                    registered = (
                        cast(str, existing["validation_id"]),
                        cast(str, existing["batch_id"]),
                        cast(str, existing["configuration_sha256"]),
                        cast(str, existing["evaluation_window_started_at_utc"]),
                        cast(str, existing["corrections_sha256"]),
                        cast(str, existing["report_path"]),
                        cast(str, existing["report_sha256"]),
                        cast(str, existing["registered_at_utc"]),
                    )
                    if registered != values:
                        raise QualityReceiptCollisionError(
                            f"quality receipt collision for {receipt.validation_id}"
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def prepare_intent(self, intent: IngestionIntent) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO ingestion_intents VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.batch_id,
                    intent.manifest_sha256,
                    str(intent.staging_directory),
                    str(intent.final_directory),
                    intent.report_sha256,
                    intent.occurred_at_utc,
                ),
            )

    def clear_intent(self, batch_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM ingestion_intents WHERE batch_id = ?", (batch_id,))

    def find_duplicate_delivery(
        self, source_identity: str, source_system: str, checksum_sha256: str
    ) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT batch_id
                FROM deliveries
                WHERE source_identity = ?
                  AND source_system = ?
                  AND checksum_sha256 = ?
                  AND decision = 'processed'
                ORDER BY rowid
                LIMIT 1
                """,
                (source_identity, source_system, checksum_sha256),
            ).fetchone()
        return None if row is None else cast(str, row["batch_id"])

    def register_batch(
        self,
        result: IngestionResult,
        files: Sequence[FileIngestionSummary],
        raw_evidence_paths: Iterable[Path],
        occurred_at_utc: str,
    ) -> None:
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO batches (
                        batch_id, manifest_sha256, decision, artifact_directory, report_path,
                        report_sha256, file_count, processed_files, duplicate_files,
                        declared_rows, raw_rows, duplicate_no_op_rows, accepted, warned,
                        quarantined, rejected, reconciled, registered_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.batch_id,
                        result.manifest_sha256,
                        result.decision,
                        str(result.artifact_directory),
                        str(result.report_path),
                        result.report_sha256,
                        result.file_count,
                        result.processed_files,
                        result.duplicate_files,
                        result.declared_rows,
                        result.raw_rows,
                        result.duplicate_no_op_rows,
                        result.accepted,
                        result.warned,
                        result.quarantined,
                        result.rejected,
                        int(result.reconciled),
                        occurred_at_utc,
                    ),
                )
                for item in files:
                    connection.execute(
                        """
                        INSERT INTO deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result.batch_id,
                            item.source_identity,
                            item.source_family,
                            item.dataset,
                            item.source_system,
                            item.file_name,
                            item.checksum_sha256,
                            item.contract_id,
                            item.contract_version,
                            item.declared_rows,
                            item.decision,
                            item.duplicate_of_batch_id,
                        ),
                    )
                for path in raw_evidence_paths:
                    self._register_rows(connection, result.batch_id, path)
                connection.execute(
                    """
                    INSERT INTO ingestion_events
                        (batch_id, manifest_sha256, decision, occurred_at_utc, reason, details_json)
                    VALUES (?, ?, ?, ?, NULL, NULL)
                    """,
                    (result.batch_id, result.manifest_sha256, result.decision, occurred_at_utc),
                )
                connection.execute(
                    "DELETE FROM ingestion_intents WHERE batch_id = ?", (result.batch_id,)
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _register_rows(self, connection: sqlite3.Connection, batch_id: str, path: Path) -> None:
        with path.open(encoding="utf-8") as source:
            for line in source:
                envelope = cast(dict[str, Any], json.loads(line))
                lineage = cast(dict[str, Any], envelope["lineage"])
                issues = cast(list[dict[str, Any]], envelope["issues"])
                disposition = cast(str, envelope["disposition"])
                values = (
                    batch_id,
                    cast(str, lineage["source_identity"]),
                    cast(str, lineage["source_file"]),
                    cast(int, lineage["source_row_number"]),
                    cast(str, envelope["source_record_id"]),
                    cast(str, envelope["natural_key"]),
                    cast(str, envelope["version_discriminator"]),
                    cast(str, envelope["payload_sha256"]),
                    disposition,
                    json.dumps(sorted(cast(str, issue["rule_id"]) for issue in issues)),
                )
                connection.execute(
                    """
                    INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                if disposition not in {"accepted", "accepted_with_warning"}:
                    continue
                existing = connection.execute(
                    """
                    SELECT payload_sha256, first_batch_id
                    FROM source_versions
                    WHERE source_identity = ? AND natural_key = ? AND version_discriminator = ?
                    """,
                    (values[1], values[5], values[6]),
                ).fetchone()
                if existing is not None and existing["payload_sha256"] != values[7]:
                    raise RegistryCollisionError(
                        source_identity=values[1],
                        natural_key=values[5],
                        version_discriminator=values[6],
                        existing_payload_sha256=cast(str, existing["payload_sha256"]),
                        incoming_payload_sha256=values[7],
                        existing_batch_id=cast(str, existing["first_batch_id"]),
                    )
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO source_versions VALUES (?, ?, ?, ?, ?)
                        """,
                        (values[1], values[5], values[6], values[7], batch_id),
                    )

    def record_event(
        self,
        batch_id: str,
        manifest_sha256: str,
        decision: str,
        occurred_at_utc: str,
        reason: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO ingestion_events
                    (batch_id, manifest_sha256, decision, occurred_at_utc, reason, details_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    manifest_sha256,
                    decision,
                    occurred_at_utc,
                    reason,
                    None if details is None else json.dumps(details, sort_keys=True),
                ),
            )
