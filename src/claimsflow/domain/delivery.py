"""Delivery identities used at the synthetic pre-ingress boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DeliveryManifest:
    """Verified control-plane metadata; never contains a claim payload."""

    batch_id: str
    source_family: str
    source_system: str
    file_name: str
    checksum_sha256: str
    contract_id: str
    contract_version: str
    generator_version: str
    generated_at: datetime
