"""Value objects for bounded, repeatable synthetic generation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

GENERATOR_NAME = "claimsflow-synthetic-source-generator"
GENERATOR_VERSION = "1.0.1"
MANIFEST_SCHEMA_VERSION = "1.0.0"
MAX_CLAIM_COUNT = 100_000
MAX_SEED = 2_147_483_647
MIN_SERVICE_YEAR = 2000
MAX_SERVICE_YEAR = 9998


class GenerationError(ValueError):
    """Raised when generation would violate a deterministic or safety boundary."""


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """Inputs that completely determine a synthetic delivery."""

    seed: int
    claim_count: int
    service_month: date
    generator_version: str = GENERATOR_VERSION

    def __post_init__(self) -> None:
        if not 0 <= self.seed <= MAX_SEED:
            raise GenerationError(f"seed must be between 0 and {MAX_SEED}")
        if not 1 <= self.claim_count <= MAX_CLAIM_COUNT:
            raise GenerationError(f"claim count must be between 1 and {MAX_CLAIM_COUNT}")
        if self.service_month.day != 1:
            raise GenerationError("service month must be the first day of a month")
        if not MIN_SERVICE_YEAR <= self.service_month.year <= MAX_SERVICE_YEAR:
            raise GenerationError(
                f"service month year must be between {MIN_SERVICE_YEAR} and {MAX_SERVICE_YEAR}"
            )
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.generator_version) is None:
            raise GenerationError("generator version must use semantic version format")

    @classmethod
    def from_values(
        cls,
        *,
        seed: int,
        claim_count: int,
        service_month: str,
        generator_version: str = GENERATOR_VERSION,
    ) -> GenerationConfig:
        """Parse CLI-friendly values without using the wall clock."""

        match = re.fullmatch(r"([0-9]{4})-(0[1-9]|1[0-2])", service_month)
        if match is None:
            raise GenerationError("service month must use exact YYYY-MM format")
        year, month = (int(value) for value in match.groups())
        if not MIN_SERVICE_YEAR <= year <= MAX_SERVICE_YEAR:
            raise GenerationError(
                f"service month year must be between {MIN_SERVICE_YEAR} and {MAX_SERVICE_YEAR}"
            )
        return cls(
            seed=seed,
            claim_count=claim_count,
            service_month=date(year, month, 1),
            generator_version=generator_version,
        )

    @property
    def generated_at(self) -> datetime:
        """Return a stable logical generation time after the service period closes."""

        following_month = _next_month(self.service_month)
        return datetime(
            following_month.year,
            following_month.month,
            16,
            tzinfo=UTC,
        )

    @property
    def canonical_values(self) -> dict[str, object]:
        return {
            "claim_count": self.claim_count,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "service_month": self.service_month.strftime("%Y-%m"),
        }

    @property
    def fingerprint_sha256(self) -> str:
        payload = json.dumps(
            self.canonical_values,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @property
    def batch_id(self) -> str:
        month = self.service_month.strftime("%Y%m")
        return f"CF-{month}-{self.fingerprint_sha256[:12].upper()}"

    @property
    def delivery_namespace(self) -> str:
        """Prefix delivery-scoped natural keys so separate batches never collide."""

        month = self.service_month.strftime("%Y%m")
        return f"{month}-{self.fingerprint_sha256.upper()}"


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Safe control-plane summary returned after an atomic local generation."""

    batch_id: str
    output_directory: Path
    manifest_path: Path
    file_count: int
    total_rows: int
