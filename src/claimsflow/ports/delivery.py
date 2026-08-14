"""Ports for verified landing and audit persistence."""

from __future__ import annotations

from typing import Protocol

from claimsflow.domain.delivery import DeliveryManifest


class LandingRepository(Protocol):
    """Persists only deliveries that passed the source-side provenance gate."""

    def register(self, manifest: DeliveryManifest) -> str:
        """Return the immutable landing object generation identifier."""
        ...


class AuditRepository(Protocol):
    """Persists control-plane outcomes without claim payloads."""

    def record_delivery(self, manifest: DeliveryManifest, decision: str) -> None:
        """Record the delivery decision under its stable batch identity."""
        ...
