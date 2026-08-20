"""Verified synthetic-delivery ingestion boundary."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from claimsflow.domain.ingestion import IngestionResult
from claimsflow.ingestion.cloud_publication import (
    CloudPublicationError,
    publish_ingestion_to_cloud,
)
from claimsflow.ingestion.contracts import ContractCatalog, ContractLoadError
from claimsflow.ingestion.service import IngestionError
from claimsflow.ingestion.service import ingest_delivery as _ingest_delivery
from claimsflow.ports.ingestion import RegistryFactory


def ingest_delivery(
    manifest_path: Path,
    workspace: Path,
    contracts_directory: Path,
    *,
    clock: Callable[[], datetime] | None = None,
    registry_factory: RegistryFactory | None = None,
) -> IngestionResult:
    """Compose the ingestion service with SQLite unless another registry is injected."""

    if registry_factory is None:
        from claimsflow.adapters.local_registry import SqliteIngestionRegistry

        registry_factory = SqliteIngestionRegistry
    return _ingest_delivery(
        manifest_path,
        workspace,
        contracts_directory,
        clock=clock,
        registry_factory=registry_factory,
    )


__all__ = [
    "CloudPublicationError",
    "ContractCatalog",
    "ContractLoadError",
    "IngestionError",
    "ingest_delivery",
    "publish_ingestion_to_cloud",
]
