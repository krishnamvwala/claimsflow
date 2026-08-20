"""Infrastructure-independent ports for synthetic cloud publication."""

from __future__ import annotations

from typing import Protocol

from claimsflow.domain.cloud import (
    AuditWriteRequest,
    BigQueryLoadReceipt,
    LandingObjectReceipt,
    LandingObjectRequest,
    RawLoadRequest,
)


class LandingObjectStore(Protocol):
    """Publishes and re-verifies immutable landing objects."""

    def upload(self, request: LandingObjectRequest) -> LandingObjectReceipt:
        """Create an object or prove an identical object already exists."""
        ...

    def verify(self, receipt: LandingObjectReceipt) -> None:
        """Re-read the exact generation and verify its full SHA-256 checksum."""
        ...


class RawAuditWarehouse(Protocol):
    """Appends raw JSON Lines and cloud-publication audit evidence."""

    def load_raw(self, request: RawLoadRequest) -> BigQueryLoadReceipt:
        """Run or reattach to one deterministic raw load job."""
        ...

    def write_audit(self, request: AuditWriteRequest) -> BigQueryLoadReceipt:
        """Run or reattach to one deterministic audit load job."""
        ...
