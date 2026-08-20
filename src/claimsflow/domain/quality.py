"""Typed evidence for Phase 3 data-quality and quarantine runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from claimsflow.domain.ingestion import Disposition

QualitySeverity = Literal["warning", "error", "critical"]
QualityRunDecision = Literal["approved", "blocked", "duplicate_no_op"]


class QualityReceiptCollisionError(RuntimeError):
    """Raised when durable quality-run identity conflicts with registered evidence."""


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One auditable row, source, or batch validation outcome."""

    rule_id: str
    severity: QualitySeverity
    disposition: Disposition | None
    reason: str
    processed_at_utc: str
    source_identity: str | None = None
    source_record_id: str | None = None
    natural_key: str | None = None
    field: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Return deterministic JSON-safe evidence without source payload values."""

        result: dict[str, object] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "disposition": self.disposition,
            "reason": self.reason,
            "processed_at_utc": self.processed_at_utc,
        }
        for name, value in (
            ("source_identity", self.source_identity),
            ("source_record_id", self.source_record_id),
            ("natural_key", self.natural_key),
            ("field", self.field),
        ):
            if value is not None:
                result[name] = value
        return result


@dataclass(frozen=True, slots=True)
class QualityCorrection:
    """A complete synthetic revision that never overwrites original raw evidence."""

    correction_id: str
    source_identity: str
    source_record_id: str
    expected_payload_sha256: str
    revised_payload: dict[str, str]
    actor_source: str
    reason: str
    corrected_at_utc: str


@dataclass(frozen=True, slots=True)
class QualityRunReceipt:
    """Durable control-plane hash for one semantically verified quality run."""

    validation_id: str
    batch_id: str
    configuration_sha256: str
    evaluation_window_started_at_utc: str
    corrections_sha256: str
    report_path: Path
    report_sha256: str
    registered_at_utc: str


@dataclass(frozen=True, slots=True)
class SourceQualitySummary:
    """Final disposition and freshness evidence for one source identity."""

    source_identity: str
    raw_rows: int
    accepted: int
    warned: int
    quarantined: int
    rejected: int
    issue_count: int
    freshness_status: Literal["current", "late", "not_evaluable"]
    maximum_source_age: str
    observed_source_age_seconds: int | None

    @property
    def disposition_rows(self) -> int:
        """Return the count required to reconcile to raw input."""

        return self.accepted + self.warned + self.quarantined + self.rejected


@dataclass(frozen=True, slots=True)
class QualityRunResult:
    """Safe control-plane summary for one immutable Phase 3 validation run."""

    validation_id: str
    rule_version: str
    batch_id: str
    decision: QualityRunDecision
    publication_allowed: bool
    output_directory: Path
    report_path: Path
    report_sha256: str
    raw_rows: int
    accepted: int
    warned: int
    quarantined: int
    rejected: int
    correction_count: int
    issue_count: int
    blocking_issue_count: int
    reconciled: bool
