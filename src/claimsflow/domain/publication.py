"""Immutable publication-control records for governed warehouse snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, Self, cast

PublicationEnvironment = Literal["local", "dev-demo"]
GateStatus = Literal["passed", "failed"]
MembershipMode = Literal["delta", "base"]
ActivationKind = Literal["publish", "rollback"]
PublicationDecision = Literal["published", "blocked", "already_active", "rolled_back"]

_PUBLICATION_ID = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,159}$")
_LOGICAL_RELATION = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_PHYSICAL_RELATION = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]{0,1023}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,1023}){1,2}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MD5 = re.compile(r"^[0-9a-f]{32}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_SUPPORTED_ENVIRONMENTS = frozenset({"local", "dev-demo"})


def _require_non_blank(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} cannot be blank")


def _require_match(value: str, pattern: re.Pattern[str], label: str) -> None:
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{label} must be timezone-aware UTC")


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


@dataclass(frozen=True, slots=True)
class GateResult:
    """One required release gate and its immutable evidence reference."""

    name: str
    status: GateStatus
    evidence_ref: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_match(self.name, _LOGICAL_RELATION, "gate name")
        if self.status not in {"passed", "failed"}:
            raise ValueError("gate status must be passed or failed")
        _require_non_blank(self.evidence_ref, "gate evidence_ref")
        _require_match(self.evidence_sha256, _SHA256, "gate evidence_sha256")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "evidence_ref": self.evidence_ref,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class RowReconciliation:
    """Expected and actual row totals for one published relation."""

    logical_relation: str
    expected_rows: int
    actual_rows: int

    def __post_init__(self) -> None:
        _require_match(self.logical_relation, _LOGICAL_RELATION, "row relation")
        if self.expected_rows < 0 or self.actual_rows < 0:
            raise ValueError("row reconciliation counts cannot be negative")

    @property
    def reconciled(self) -> bool:
        return self.expected_rows == self.actual_rows

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_relation": self.logical_relation,
            "expected_rows": self.expected_rows,
            "actual_rows": self.actual_rows,
            "reconciled": self.reconciled,
        }


@dataclass(frozen=True, slots=True)
class FinancialReconciliation:
    """Expected and actual governed financial totals with an explicit tolerance."""

    logical_relation: str
    measure: str
    expected_amount: Decimal
    actual_amount: Decimal
    tolerance: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        _require_match(self.logical_relation, _LOGICAL_RELATION, "financial relation")
        _require_match(self.measure, _LOGICAL_RELATION, "financial measure")
        if self.tolerance < Decimal(0):
            raise ValueError("financial tolerance cannot be negative")
        if self.currency != "USD":
            raise ValueError("the synthetic portfolio baseline supports USD only")

    @property
    def variance(self) -> Decimal:
        return self.actual_amount - self.expected_amount

    @property
    def reconciled(self) -> bool:
        return abs(self.variance) <= self.tolerance

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_relation": self.logical_relation,
            "measure": self.measure,
            "expected_amount": str(self.expected_amount),
            "actual_amount": str(self.actual_amount),
            "tolerance": str(self.tolerance),
            "variance": str(self.variance),
            "currency": self.currency,
            "reconciled": self.reconciled,
        }


@dataclass(frozen=True, slots=True)
class PartitionRange:
    """Inclusive affected partition range declared by the candidate."""

    relation: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        _require_match(self.relation, _LOGICAL_RELATION, "partition relation")
        if self.end_date < self.start_date:
            raise ValueError("partition range end_date cannot precede start_date")

    def as_dict(self) -> dict[str, object]:
        return {
            "relation": self.relation,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PublishedRelation:
    """A governed logical relation and its isolated candidate table."""

    logical_name: str
    business_key_column: str
    candidate_relation: str

    def __post_init__(self) -> None:
        _require_match(self.logical_name, _LOGICAL_RELATION, "logical relation")
        _require_match(self.business_key_column, _COLUMN, "business key column")
        _require_match(self.candidate_relation, _PHYSICAL_RELATION, "candidate relation")

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_name": self.logical_name,
            "business_key_column": self.business_key_column,
            "candidate_relation": self.candidate_relation,
        }


@dataclass(frozen=True, slots=True)
class CandidateInventoryEntry:
    """One business key and content hash in the candidate's complete final snapshot."""

    logical_relation: str
    business_key: str
    result_sha256: str

    def __post_init__(self) -> None:
        _require_match(self.logical_relation, _LOGICAL_RELATION, "inventory logical relation")
        _require_non_blank(self.business_key, "inventory business_key")
        _require_match(self.result_sha256, _SHA256, "inventory result_sha256")

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_relation": self.logical_relation,
            "business_key": self.business_key,
            "result_sha256": self.result_sha256,
        }


def relation_inventory_sha256(entries: tuple[CandidateInventoryEntry, ...]) -> str:
    """Hash one relation's complete, key-sorted key/content inventory."""

    canonical = b"".join(
        (
            f"{len(entry.business_key.encode('utf-8')):08x}:"
            f"{entry.business_key}:{entry.result_sha256}"
        ).encode()
        for entry in sorted(entries, key=lambda item: item.business_key)
    )
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class RelationInventory:
    """Manifest commitment to one relation's complete business-key/hash inventory."""

    logical_relation: str
    row_count: int
    inventory_sha256: str

    def __post_init__(self) -> None:
        _require_match(self.logical_relation, _LOGICAL_RELATION, "inventory relation")
        if self.row_count < 0:
            raise ValueError("inventory row_count cannot be negative")
        _require_match(self.inventory_sha256, _SHA256, "inventory_sha256")

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_relation": self.logical_relation,
            "row_count": self.row_count,
            "inventory_sha256": self.inventory_sha256,
        }


@dataclass(frozen=True, slots=True)
class ResultVersionReference:
    """Immutable address and content fingerprint for one candidate result row."""

    result_version_id: str
    source_publication_id: str
    logical_relation: str
    business_key: str
    result_sha256: str
    physical_relation: str

    def __post_init__(self) -> None:
        _require_match(self.result_version_id, _SHA256, "result_version_id")
        _require_match(self.source_publication_id, _PUBLICATION_ID, "source publication_id")
        _require_match(self.logical_relation, _LOGICAL_RELATION, "result logical relation")
        _require_non_blank(self.business_key, "result business_key")
        _require_match(self.result_sha256, _SHA256, "result_sha256")
        _require_match(self.physical_relation, _PHYSICAL_RELATION, "result physical relation")

    def as_dict(self) -> dict[str, object]:
        return {
            "result_version_id": self.result_version_id,
            "source_publication_id": self.source_publication_id,
            "logical_relation": self.logical_relation,
            "business_key": self.business_key,
            "result_sha256": self.result_sha256,
            "physical_relation": self.physical_relation,
        }


@dataclass(frozen=True, slots=True)
class MembershipDeltaEntry:
    """A changed business-key mapping or explicit deletion tombstone."""

    sequence: int
    logical_relation: str
    business_key: str
    result_version_id: str | None
    tombstone: bool

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("membership sequence cannot be negative")
        _require_match(self.logical_relation, _LOGICAL_RELATION, "membership logical relation")
        _require_non_blank(self.business_key, "membership business_key")
        if self.tombstone and self.result_version_id is not None:
            raise ValueError("a membership tombstone cannot reference a result version")
        if not self.tombstone and self.result_version_id is None:
            raise ValueError("a membership upsert requires a result version")
        if self.result_version_id is not None:
            _require_match(self.result_version_id, _SHA256, "membership result_version_id")

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "logical_relation": self.logical_relation,
            "business_key": self.business_key,
            "result_version_id": self.result_version_id,
            "tombstone": self.tombstone,
        }


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    """Complete immutable evidence needed to activate one logical snapshot."""

    publication_id: str
    parent_publication_id: str | None
    membership_delta_chain: tuple[str, ...]
    membership_mode: MembershipMode
    environment: PublicationEnvironment
    code_commit: str
    dbt_validation_selection_fingerprint: str
    dbt_candidate_build_fingerprint: str
    dbt_artifact_version: str
    dbt_artifact_sha256: str
    included_batch_ids: tuple[str, ...]
    contract_version: str
    dictionary_version: str
    warehouse_partition_ranges: tuple[PartitionRange, ...]
    bi_partition_ranges: tuple[PartitionRange, ...]
    impact_bounded: bool
    gate_results: tuple[GateResult, ...]
    published_relations: tuple[PublishedRelation, ...]
    relation_inventories: tuple[RelationInventory, ...]
    row_reconciliations: tuple[RowReconciliation, ...]
    financial_reconciliations: tuple[FinancialReconciliation, ...]
    created_at_utc: datetime
    synthetic_only: bool = True
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        _require_match(self.publication_id, _PUBLICATION_ID, "publication_id")
        if self.parent_publication_id is not None:
            _require_match(
                self.parent_publication_id,
                _PUBLICATION_ID,
                "parent_publication_id",
            )
            if self.parent_publication_id == self.publication_id:
                raise ValueError("a publication cannot be its own parent")
        if self.membership_mode not in {"delta", "base"}:
            raise ValueError("membership_mode must be delta or base")
        if (
            not self.membership_delta_chain
            or self.membership_delta_chain[-1] != self.publication_id
        ):
            raise ValueError("membership_delta_chain must end with this publication")
        _require_unique(self.membership_delta_chain, "membership_delta_chain")
        if self.membership_mode == "base" and self.membership_delta_chain != (self.publication_id,):
            raise ValueError("a base manifest must start a new one-entry membership chain")
        if self.membership_mode == "delta":
            if self.parent_publication_id is None and self.membership_delta_chain != (
                self.publication_id,
            ):
                raise ValueError("a genesis delta must have a one-entry membership chain")
            if self.parent_publication_id is not None and (
                len(self.membership_delta_chain) < 2
                or self.membership_delta_chain[-2] != self.parent_publication_id
            ):
                raise ValueError("a delta chain must inherit and end with its parent")
        if self.environment not in _SUPPORTED_ENVIRONMENTS:
            raise ValueError("publication environment is unsupported")
        _require_match(self.code_commit, _GIT_COMMIT, "code_commit")
        _require_match(
            self.dbt_validation_selection_fingerprint,
            _MD5,
            "dbt_validation_selection_fingerprint",
        )
        _require_match(
            self.dbt_candidate_build_fingerprint,
            _MD5,
            "dbt_candidate_build_fingerprint",
        )
        canonical_build = (
            "candidate-build-v1\n"
            f"{self.publication_id}\n"
            f"{self.dbt_validation_selection_fingerprint}\n"
            f"{self.code_commit}"
        ).encode()
        expected_build_fingerprint = hashlib.md5(
            canonical_build,
            usedforsecurity=False,
        ).hexdigest()
        if self.dbt_candidate_build_fingerprint != expected_build_fingerprint:
            raise ValueError(
                "dbt_candidate_build_fingerprint contradicts publication, selection, or code"
            )
        _require_match(
            self.dbt_artifact_version,
            _SEMANTIC_VERSION,
            "dbt_artifact_version",
        )
        _require_match(self.dbt_artifact_sha256, _SHA256, "dbt_artifact_sha256")
        if not self.included_batch_ids:
            raise ValueError("included_batch_ids cannot be empty")
        for batch_id in self.included_batch_ids:
            _require_match(batch_id, _SAFE_ID, "included batch_id")
        _require_unique(self.included_batch_ids, "included_batch_ids")
        _require_match(self.contract_version, _SEMANTIC_VERSION, "contract_version")
        _require_match(self.dictionary_version, _SEMANTIC_VERSION, "dictionary_version")
        if not isinstance(self.impact_bounded, bool):
            raise ValueError("impact_bounded must be boolean")
        if not self.gate_results:
            raise ValueError("gate_results cannot be empty")
        _require_unique(tuple(gate.name for gate in self.gate_results), "gate names")
        if not self.published_relations:
            raise ValueError("published_relations cannot be empty")
        relation_names = tuple(relation.logical_name for relation in self.published_relations)
        _require_unique(relation_names, "published relation names")
        _require_unique(
            tuple(relation.candidate_relation for relation in self.published_relations),
            "candidate relations",
        )
        required_relation_suffix = (
            f"__{self.publication_id}"
            f"__{self.dbt_validation_selection_fingerprint}"
            f"__{self.dbt_candidate_build_fingerprint}"
        )
        if any(
            not relation.candidate_relation.endswith(required_relation_suffix)
            for relation in self.published_relations
        ):
            raise ValueError(
                "candidate relations must be bound to the manifest selection and code build"
            )
        _require_unique(
            tuple(item.logical_relation for item in self.row_reconciliations),
            "row reconciliation relations",
        )
        relation_set = set(relation_names)
        inventory_relations = tuple(
            inventory.logical_relation for inventory in self.relation_inventories
        )
        _require_unique(inventory_relations, "relation inventory relations")
        if set(inventory_relations) != relation_set:
            raise ValueError("relation inventories must cover every published relation")
        if any(item.logical_relation not in relation_set for item in self.row_reconciliations):
            raise ValueError("row reconciliation references an unpublished relation")
        if any(
            item.logical_relation not in relation_set for item in self.financial_reconciliations
        ):
            raise ValueError("financial reconciliation references an unpublished relation")
        if any(item.relation not in relation_set for item in self.warehouse_partition_ranges):
            raise ValueError("warehouse partition range references an unpublished relation")
        if any(item.relation not in relation_set for item in self.bi_partition_ranges):
            raise ValueError("BI partition range references an unpublished relation")
        _require_utc(self.created_at_utc, "created_at_utc")
        if self.synthetic_only is not True:
            raise ValueError("publication manifests require synthetic_only=true")
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported publication manifest schema_version")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "publication_id": self.publication_id,
            "parent_publication_id": self.parent_publication_id,
            "membership_delta_chain": list(self.membership_delta_chain),
            "membership_mode": self.membership_mode,
            "environment": self.environment,
            "code_commit": self.code_commit,
            "dbt_validation_selection_fingerprint": (self.dbt_validation_selection_fingerprint),
            "dbt_candidate_build_fingerprint": self.dbt_candidate_build_fingerprint,
            "dbt_artifact_version": self.dbt_artifact_version,
            "dbt_artifact_sha256": self.dbt_artifact_sha256,
            "included_batch_ids": list(self.included_batch_ids),
            "contract_version": self.contract_version,
            "dictionary_version": self.dictionary_version,
            "warehouse_partition_ranges": [
                item.as_dict() for item in self.warehouse_partition_ranges
            ],
            "bi_partition_ranges": [item.as_dict() for item in self.bi_partition_ranges],
            "impact_bounded": self.impact_bounded,
            "full_bi_refresh_required": not self.impact_bounded,
            "gate_results": [item.as_dict() for item in self.gate_results],
            "published_relations": [item.as_dict() for item in self.published_relations],
            "relation_inventories": [item.as_dict() for item in self.relation_inventories],
            "row_reconciliations": [item.as_dict() for item in self.row_reconciliations],
            "financial_reconciliations": [
                item.as_dict() for item in self.financial_reconciliations
            ],
            "created_at_utc": self.created_at_utc.isoformat().replace("+00:00", "Z"),
            "synthetic_only": self.synthetic_only,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> Self:
        """Reconstruct a manifest from its persisted canonical JSON representation."""

        def items(name: str) -> list[dict[str, object]]:
            raw = value[name]
            if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
                raise ValueError(f"{name} must be a list of objects")
            return cast(list[dict[str, object]], raw)

        created = datetime.fromisoformat(str(value["created_at_utc"]).replace("Z", "+00:00"))
        return cls(
            publication_id=str(value["publication_id"]),
            parent_publication_id=(
                str(value["parent_publication_id"])
                if value.get("parent_publication_id") is not None
                else None
            ),
            membership_delta_chain=tuple(
                str(item) for item in cast(list[object], value["membership_delta_chain"])
            ),
            membership_mode=cast(MembershipMode, value["membership_mode"]),
            environment=cast(PublicationEnvironment, value["environment"]),
            code_commit=str(value["code_commit"]),
            dbt_validation_selection_fingerprint=str(value["dbt_validation_selection_fingerprint"]),
            dbt_candidate_build_fingerprint=str(value["dbt_candidate_build_fingerprint"]),
            dbt_artifact_version=str(value["dbt_artifact_version"]),
            dbt_artifact_sha256=str(value["dbt_artifact_sha256"]),
            included_batch_ids=tuple(
                str(item) for item in cast(list[object], value["included_batch_ids"])
            ),
            contract_version=str(value["contract_version"]),
            dictionary_version=str(value["dictionary_version"]),
            warehouse_partition_ranges=tuple(
                PartitionRange(
                    relation=str(item["relation"]),
                    start_date=date.fromisoformat(str(item["start_date"])),
                    end_date=date.fromisoformat(str(item["end_date"])),
                )
                for item in items("warehouse_partition_ranges")
            ),
            bi_partition_ranges=tuple(
                PartitionRange(
                    relation=str(item["relation"]),
                    start_date=date.fromisoformat(str(item["start_date"])),
                    end_date=date.fromisoformat(str(item["end_date"])),
                )
                for item in items("bi_partition_ranges")
            ),
            impact_bounded=bool(value["impact_bounded"]),
            gate_results=tuple(
                GateResult(
                    name=str(item["name"]),
                    status=cast(GateStatus, item["status"]),
                    evidence_ref=str(item["evidence_ref"]),
                    evidence_sha256=str(item["evidence_sha256"]),
                )
                for item in items("gate_results")
            ),
            published_relations=tuple(
                PublishedRelation(
                    logical_name=str(item["logical_name"]),
                    business_key_column=str(item["business_key_column"]),
                    candidate_relation=str(item["candidate_relation"]),
                )
                for item in items("published_relations")
            ),
            relation_inventories=tuple(
                RelationInventory(
                    logical_relation=str(item["logical_relation"]),
                    row_count=int(cast(int, item["row_count"])),
                    inventory_sha256=str(item["inventory_sha256"]),
                )
                for item in items("relation_inventories")
            ),
            row_reconciliations=tuple(
                RowReconciliation(
                    logical_relation=str(item["logical_relation"]),
                    expected_rows=int(cast(int, item["expected_rows"])),
                    actual_rows=int(cast(int, item["actual_rows"])),
                )
                for item in items("row_reconciliations")
            ),
            financial_reconciliations=tuple(
                FinancialReconciliation(
                    logical_relation=str(item["logical_relation"]),
                    measure=str(item["measure"]),
                    expected_amount=Decimal(str(item["expected_amount"])),
                    actual_amount=Decimal(str(item["actual_amount"])),
                    tolerance=Decimal(str(item["tolerance"])),
                    currency=str(item["currency"]),
                )
                for item in items("financial_reconciliations")
            ),
            created_at_utc=created,
            synthetic_only=bool(value["synthetic_only"]),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class PublicationCandidate:
    """One manifest plus its append-only result references and membership delta."""

    manifest: PublicationManifest
    membership_delta: tuple[MembershipDeltaEntry, ...]
    result_versions: tuple[ResultVersionReference, ...]
    inventory: tuple[CandidateInventoryEntry, ...]

    def __post_init__(self) -> None:
        sequences = tuple(item.sequence for item in self.membership_delta)
        if len(sequences) != len(set(sequences)):
            raise ValueError("membership delta sequences must be unique")
        identities = tuple(
            (item.logical_relation, item.business_key) for item in self.membership_delta
        )
        if len(identities) != len(set(identities)):
            raise ValueError("membership delta business keys must be unique per relation")
        version_ids = tuple(item.result_version_id for item in self.result_versions)
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("candidate result_version_ids must be unique")
        inventory_identities = tuple(
            (item.logical_relation, item.business_key) for item in self.inventory
        )
        if len(inventory_identities) != len(set(inventory_identities)):
            raise ValueError("candidate inventory business keys must be unique per relation")
        if inventory_identities != tuple(sorted(inventory_identities)):
            raise ValueError("candidate inventory must use canonical relation/business-key order")


@dataclass(frozen=True, slots=True)
class ActivePublication:
    """The sole mutable environment pointer, protected by a monotonic revision."""

    environment: PublicationEnvironment
    publication_id: str
    revision: int
    updated_at_utc: datetime

    def __post_init__(self) -> None:
        if self.environment not in _SUPPORTED_ENVIRONMENTS:
            raise ValueError("active publication environment is unsupported")
        _require_match(self.publication_id, _PUBLICATION_ID, "active publication_id")
        if self.revision <= 0:
            raise ValueError("active publication revision must be positive")
        _require_utc(self.updated_at_utc, "active updated_at_utc")


@dataclass(frozen=True, slots=True)
class ActivationEvent:
    """Append-only evidence for publication or rollback pointer movement."""

    event_id: str
    kind: ActivationKind
    environment: PublicationEnvironment
    from_publication_id: str | None
    to_publication_id: str
    from_revision: int
    to_revision: int
    reason: str
    activated_at_utc: datetime

    def __post_init__(self) -> None:
        _require_match(self.event_id, _SHA256, "activation event_id")
        if self.kind not in {"publish", "rollback"}:
            raise ValueError("activation kind must be publish or rollback")
        if self.environment not in _SUPPORTED_ENVIRONMENTS:
            raise ValueError("activation environment is unsupported")
        if self.from_publication_id is not None:
            _require_match(
                self.from_publication_id,
                _PUBLICATION_ID,
                "activation from_publication_id",
            )
        _require_match(self.to_publication_id, _PUBLICATION_ID, "activation to_publication_id")
        if self.from_revision < 0 or self.to_revision != self.from_revision + 1:
            raise ValueError("activation revisions must advance exactly once")
        _require_non_blank(self.reason, "activation reason")
        _require_utc(self.activated_at_utc, "activated_at_utc")


@dataclass(frozen=True, slots=True)
class ResolvedMembership:
    """Latest non-tombstoned result mapping for one business key."""

    active_publication_id: str
    logical_relation: str
    business_key: str
    result_version_id: str
    mapping_publication_id: str


@dataclass(frozen=True, slots=True)
class PublicationOutcome:
    """Safe control-plane result for a publication or rollback request."""

    decision: PublicationDecision
    publication_id: str
    active_publication: ActivePublication | None
    failed_gates: tuple[str, ...] = ()
