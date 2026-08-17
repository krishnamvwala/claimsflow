"""Persistence boundary for idempotent local or cloud ingestion registries."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from claimsflow.domain.ingestion import FileIngestionSummary, IngestionIntent, IngestionResult


class IngestionRegistry(Protocol):
    """Stores only control-plane, lineage, hash, and disposition evidence."""

    def exclusive_ingestion(self) -> AbstractContextManager[None]:
        """Serialize delivery decisions and registration within one workspace."""
        ...

    def get_batch(self, batch_id: str) -> IngestionResult | None:
        """Return a previously registered batch, when present."""
        ...

    def get_intent(self, batch_id: str) -> IngestionIntent | None:
        """Return an interrupted publication intent, when present."""
        ...

    def prepare_intent(self, intent: IngestionIntent) -> None:
        """Durably record an artifact publication before its atomic rename."""
        ...

    def clear_intent(self, batch_id: str) -> None:
        """Remove a completed or safely discarded publication intent."""
        ...

    def find_duplicate_delivery(
        self, source_identity: str, source_system: str, checksum_sha256: str
    ) -> str | None:
        """Return the original batch for a previously processed identical file."""
        ...

    def register_batch(
        self,
        result: IngestionResult,
        files: Sequence[FileIngestionSummary],
        raw_evidence_paths: Iterable[Path],
        occurred_at_utc: str,
    ) -> None:
        """Atomically register one reconciled batch and its lineage evidence."""
        ...

    def record_event(
        self,
        batch_id: str,
        manifest_sha256: str,
        decision: str,
        occurred_at_utc: str,
        reason: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Persist a control-plane event without payload values."""
        ...


type RegistryFactory = Callable[[Path], IngestionRegistry]
