"""Fail-closed manifest activation and exact rollback orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from claimsflow.domain.publication import (
    ActivationEvent,
    ActivePublication,
    PublicationCandidate,
    PublicationEnvironment,
    PublicationManifest,
    PublicationOutcome,
    ResolvedMembership,
    relation_inventory_sha256,
)
from claimsflow.ports.publication import PublicationRepository

REQUIRED_PUBLICATION_GATES = frozenset(
    {
        "validation",
        "dbt_build",
        "freshness",
        "row_reconciliation",
        "financial_reconciliation",
    }
)


class PublicationError(RuntimeError):
    """Base error for safe publication control-plane failures."""


class PublicationValidationError(PublicationError):
    """Raised when candidate evidence is incomplete or contradictory."""


class CandidateCollisionError(PublicationError):
    """Raised when a publication identity is reused with different evidence."""


class PublicationConflictError(PublicationError):
    """Raised when the active pointer changed after the candidate chose its parent."""


class CompactionRequiredError(PublicationError):
    """Raised when a delta would exceed the approved membership-chain depth."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PublicationService:
    """Stages immutable evidence before performing one guarded pointer mutation."""

    def __init__(
        self,
        repository: PublicationRepository,
        *,
        max_membership_chain_depth: int = 8,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_membership_chain_depth <= 0:
            raise ValueError("max_membership_chain_depth must be positive")
        self._repository = repository
        self._max_membership_chain_depth = max_membership_chain_depth
        self._clock = clock

    def _resolve_manifest(
        self,
        manifest: PublicationManifest,
    ) -> dict[tuple[str, str], ResolvedMembership]:
        resolved: dict[tuple[str, str], ResolvedMembership] = {}
        previous_publication_id: str | None = None
        for chain_position, chain_publication_id in enumerate(manifest.membership_delta_chain):
            chain_manifest = self._repository.get_manifest(chain_publication_id)
            if chain_manifest is None:
                raise PublicationValidationError("membership chain references a missing manifest")
            if chain_manifest.environment != manifest.environment:
                raise PublicationValidationError(
                    "membership chain crosses publication environments"
                )
            if (
                chain_position > 0
                and chain_manifest.parent_publication_id != previous_publication_id
            ):
                raise PublicationValidationError("membership chain contains a broken parent link")
            for entry in self._repository.get_membership_delta(chain_publication_id):
                identity = (entry.logical_relation, entry.business_key)
                if entry.tombstone:
                    resolved.pop(identity, None)
                    continue
                if entry.result_version_id is None:
                    raise PublicationValidationError(
                        "persisted non-tombstone membership is missing its result version"
                    )
                resolved[identity] = ResolvedMembership(
                    active_publication_id=manifest.publication_id,
                    logical_relation=entry.logical_relation,
                    business_key=entry.business_key,
                    result_version_id=entry.result_version_id,
                    mapping_publication_id=chain_publication_id,
                )
            previous_publication_id = chain_publication_id
        return resolved

    def resolve_active(
        self,
        environment: PublicationEnvironment,
    ) -> tuple[ResolvedMembership, ...]:
        """Resolve only the manifest selected by the active pointer."""

        active = self._repository.get_active(environment)
        if active is None:
            return ()
        manifest = self._repository.get_manifest(active.publication_id)
        if manifest is None:
            raise PublicationValidationError("active pointer references a missing manifest")
        resolved = self._resolve_manifest(manifest)
        return tuple(
            resolved[identity] for identity in sorted(resolved, key=lambda item: (item[0], item[1]))
        )

    def _parent_membership(
        self,
        manifest: PublicationManifest,
    ) -> dict[tuple[str, str], ResolvedMembership]:
        if manifest.parent_publication_id is None:
            return {}
        parent = self._repository.get_manifest(manifest.parent_publication_id)
        if parent is None:
            raise PublicationValidationError("candidate parent manifest does not exist")
        if parent.environment != manifest.environment:
            raise PublicationValidationError("candidate parent belongs to another environment")
        parent_relations = {relation.logical_name for relation in parent.published_relations}
        candidate_relations = {relation.logical_name for relation in manifest.published_relations}
        if not parent_relations <= candidate_relations:
            raise PublicationValidationError(
                "candidate must continue declaring every inherited logical relation"
            )
        expected_chain = (
            (manifest.publication_id,)
            if manifest.membership_mode == "base"
            else (*parent.membership_delta_chain, manifest.publication_id)
        )
        if manifest.membership_delta_chain != expected_chain:
            raise PublicationValidationError(
                "candidate membership chain does not exactly inherit its parent"
            )
        return self._resolve_manifest(parent)

    def _validate_pointer_parent(
        self,
        manifest: PublicationManifest,
        active: ActivePublication | None,
    ) -> None:
        active_id = active.publication_id if active is not None else None
        if manifest.parent_publication_id != active_id:
            raise PublicationConflictError(
                "candidate parent no longer matches the active publication"
            )

    def _validate_manifest_evidence(self, manifest: PublicationManifest) -> tuple[str, ...]:
        gate_status = {gate.name: gate.status for gate in manifest.gate_results}
        missing_gates = sorted(REQUIRED_PUBLICATION_GATES - set(gate_status))
        if missing_gates:
            raise PublicationValidationError(
                "candidate is missing required gates: " + ", ".join(missing_gates)
            )
        relation_names = {relation.logical_name for relation in manifest.published_relations}
        reconciled_relations = {item.logical_relation for item in manifest.row_reconciliations}
        if reconciled_relations != relation_names:
            raise PublicationValidationError(
                "row reconciliations must cover every published relation exactly once"
            )
        if manifest.impact_bounded:
            if not manifest.warehouse_partition_ranges or not manifest.bi_partition_ranges:
                raise PublicationValidationError(
                    "bounded impact requires warehouse and BI partition ranges"
                )
        elif manifest.bi_partition_ranges:
            raise PublicationValidationError(
                "unbounded impact must request a full BI refresh without incremental ranges"
            )
        failed = {name for name, status in gate_status.items() if status != "passed"}
        if any(not item.reconciled for item in manifest.row_reconciliations):
            failed.add("row_reconciliation")
        if any(not item.reconciled for item in manifest.financial_reconciliations):
            failed.add("financial_reconciliation")
        return tuple(sorted(failed))

    def _validate_membership(
        self,
        candidate: PublicationCandidate,
        parent_membership: dict[tuple[str, str], ResolvedMembership],
    ) -> None:
        manifest = candidate.manifest
        relation_names = {relation.logical_name for relation in manifest.published_relations}
        new_versions = {item.result_version_id: item for item in candidate.result_versions}
        referenced_new_versions: set[str] = set()
        resolved_candidate = {} if manifest.membership_mode == "base" else dict(parent_membership)

        inventory = {
            (entry.logical_relation, entry.business_key): entry.result_sha256
            for entry in candidate.inventory
        }
        if any(logical_relation not in relation_names for logical_relation, _ in inventory):
            raise PublicationValidationError(
                "candidate inventory references an unpublished relation"
            )
        declared_inventories = {
            item.logical_relation: item for item in manifest.relation_inventories
        }
        for relation_name in relation_names:
            relation_entries = tuple(
                entry for entry in candidate.inventory if entry.logical_relation == relation_name
            )
            declared = declared_inventories[relation_name]
            if declared.row_count != len(
                relation_entries
            ) or declared.inventory_sha256 != relation_inventory_sha256(relation_entries):
                raise PublicationValidationError(
                    "candidate inventory does not match its manifest commitment"
                )

        parent_hashes: dict[tuple[str, str], str] = {}
        for identity, membership in parent_membership.items():
            reference = self._repository.get_result_version(membership.result_version_id)
            if reference is None:
                raise PublicationValidationError(
                    "active membership references a missing result version"
                )
            parent_hashes[identity] = reference.result_sha256

        expected_delta_identities = (
            set(inventory)
            if manifest.membership_mode == "base"
            else {
                identity
                for identity in set(parent_hashes) | set(inventory)
                if parent_hashes.get(identity) != inventory.get(identity)
            }
        )
        actual_delta_identities = {
            (entry.logical_relation, entry.business_key) for entry in candidate.membership_delta
        }
        if actual_delta_identities != expected_delta_identities:
            raise PublicationValidationError(
                "membership delta must exactly represent every inventory addition, update, "
                "and deletion"
            )

        if manifest.membership_mode == "base" and any(
            entry.tombstone for entry in candidate.membership_delta
        ):
            raise PublicationValidationError("a compacted base map cannot contain tombstones")

        for entry in candidate.membership_delta:
            if entry.logical_relation not in relation_names:
                raise PublicationValidationError(
                    "membership delta references an unpublished relation"
                )
            identity = (entry.logical_relation, entry.business_key)
            previous = parent_membership.get(identity)
            if entry.tombstone:
                if manifest.membership_mode != "delta" or previous is None or identity in inventory:
                    raise PublicationValidationError(
                        "a delta tombstone must remove an active business key"
                    )
                resolved_candidate.pop(identity, None)
                continue
            if entry.result_version_id is None:
                raise PublicationValidationError("membership upsert lacks a result version")
            reference = new_versions.get(entry.result_version_id)
            if reference is not None:
                referenced_new_versions.add(reference.result_version_id)
            else:
                if (
                    manifest.membership_mode != "base"
                    or previous is None
                    or previous.result_version_id != entry.result_version_id
                ):
                    raise PublicationValidationError(
                        "membership upserts may not reuse untrusted candidate result versions"
                    )
                reference = self._repository.get_result_version(entry.result_version_id)
            if reference is None:
                raise PublicationValidationError(
                    "membership upsert references an unknown result version"
                )
            if (
                reference.logical_relation != entry.logical_relation
                or reference.business_key != entry.business_key
            ):
                raise PublicationValidationError(
                    "result-version identity contradicts its membership mapping"
                )
            if inventory.get(identity) != reference.result_sha256:
                raise PublicationValidationError(
                    "membership result hash contradicts the complete candidate inventory"
                )
            if manifest.membership_mode == "delta" and previous is not None:
                previous_reference = self._repository.get_result_version(previous.result_version_id)
                if previous_reference is None:
                    raise PublicationValidationError(
                        "active membership references a missing result version"
                    )
                if (
                    entry.result_version_id == previous.result_version_id
                    or previous_reference.result_sha256 == reference.result_sha256
                ):
                    raise PublicationValidationError(
                        "membership deltas may contain changed business keys only"
                    )
            resolved_candidate[identity] = ResolvedMembership(
                active_publication_id=manifest.publication_id,
                logical_relation=entry.logical_relation,
                business_key=entry.business_key,
                result_version_id=entry.result_version_id,
                mapping_publication_id=manifest.publication_id,
            )

        if referenced_new_versions != set(new_versions):
            raise PublicationValidationError(
                "every new result version must be reachable from this candidate delta"
            )
        for reference in candidate.result_versions:
            if reference.source_publication_id != manifest.publication_id:
                raise PublicationValidationError(
                    "new result versions must belong to the candidate publication"
                )
            published = next(
                (
                    relation
                    for relation in manifest.published_relations
                    if relation.logical_name == reference.logical_relation
                ),
                None,
            )
            if published is None or reference.physical_relation != published.candidate_relation:
                raise PublicationValidationError(
                    "result version must reference its declared isolated candidate relation"
                )

        resolved_counts = {
            relation: sum(
                1 for logical_relation, _ in resolved_candidate if logical_relation == relation
            )
            for relation in relation_names
        }
        reconciled_counts = {
            item.logical_relation: item.actual_rows for item in manifest.row_reconciliations
        }
        if resolved_counts != reconciled_counts:
            raise PublicationValidationError(
                "resolved membership counts must equal the candidate row reconciliations"
            )
        if set(resolved_candidate) != set(inventory):
            raise PublicationValidationError(
                "resolved membership must exactly equal the candidate inventory"
            )

    def _activation_event(
        self,
        *,
        kind: str,
        environment: PublicationEnvironment,
        from_publication_id: str | None,
        to_publication_id: str,
        from_revision: int,
        reason: str,
    ) -> ActivationEvent:
        activated_at = self._clock()
        identity = "\x1f".join(
            (
                kind,
                environment,
                from_publication_id or "genesis",
                to_publication_id,
                str(from_revision),
                reason,
                activated_at.isoformat(),
            )
        )
        return ActivationEvent(
            event_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            kind="publish" if kind == "publish" else "rollback",
            environment=environment,
            from_publication_id=from_publication_id,
            to_publication_id=to_publication_id,
            from_revision=from_revision,
            to_revision=from_revision + 1,
            reason=reason,
            activated_at_utc=activated_at,
        )

    def publish(self, candidate: PublicationCandidate) -> PublicationOutcome:
        """Persist all evidence, then activate only a fully passing candidate."""

        manifest = candidate.manifest
        existing = self._repository.get_manifest(manifest.publication_id)
        if existing is not None and existing.fingerprint != manifest.fingerprint:
            raise CandidateCollisionError(
                "publication_id is already bound to different immutable evidence"
            )

        active = self._repository.get_active(manifest.environment)
        if existing is not None:
            try:
                self._repository.append_candidate(candidate)
            except RuntimeError as error:
                raise CandidateCollisionError(
                    "publication_id is already bound to different candidate evidence"
                ) from error
            if active is not None and active.publication_id == manifest.publication_id:
                return PublicationOutcome(
                    decision="already_active",
                    publication_id=manifest.publication_id,
                    active_publication=active,
                )

        self._validate_pointer_parent(manifest, active)
        parent_membership = self._parent_membership(manifest)
        if (
            manifest.membership_mode == "delta"
            and len(manifest.membership_delta_chain) > self._max_membership_chain_depth
        ):
            raise CompactionRequiredError(
                "membership chain reached its cap; publish an approved base compaction"
            )
        self._validate_membership(candidate, parent_membership)
        failed_gates = self._validate_manifest_evidence(manifest)

        self._repository.append_candidate(candidate)
        if failed_gates:
            return PublicationOutcome(
                decision="blocked",
                publication_id=manifest.publication_id,
                active_publication=active,
                failed_gates=failed_gates,
            )

        expected_revision = active.revision if active is not None else 0
        expected_publication_id = active.publication_id if active is not None else None
        event = self._activation_event(
            kind="publish",
            environment=manifest.environment,
            from_publication_id=expected_publication_id,
            to_publication_id=manifest.publication_id,
            from_revision=expected_revision,
            reason="all required candidate publication gates passed",
        )
        try:
            activated = self._repository.compare_and_swap_active(
                event,
                expected_publication_id=expected_publication_id,
                expected_revision=expected_revision,
            )
        except RuntimeError as error:
            raise PublicationConflictError(
                "active publication changed before candidate activation"
            ) from error
        return PublicationOutcome(
            decision="published",
            publication_id=manifest.publication_id,
            active_publication=activated,
        )

    def rollback(
        self,
        environment: PublicationEnvironment,
        *,
        expected_active_publication_id: str,
        target_publication_id: str,
        reason: str,
    ) -> PublicationOutcome:
        """Select one previously activated complete manifest without rewriting data."""

        active = self._repository.get_active(environment)
        if active is None or active.publication_id != expected_active_publication_id:
            raise PublicationConflictError("rollback expected active publication does not match")
        if target_publication_id == active.publication_id:
            return PublicationOutcome(
                decision="already_active",
                publication_id=target_publication_id,
                active_publication=active,
            )
        target = self._repository.get_manifest(target_publication_id)
        if target is None or target.environment != environment:
            raise PublicationValidationError("rollback target manifest is unavailable")
        if not self._repository.was_activated(environment, target_publication_id):
            raise PublicationValidationError(
                "rollback target was never a successfully active publication"
            )
        event = self._activation_event(
            kind="rollback",
            environment=environment,
            from_publication_id=active.publication_id,
            to_publication_id=target_publication_id,
            from_revision=active.revision,
            reason=reason,
        )
        try:
            rolled_back = self._repository.compare_and_swap_active(
                event,
                expected_publication_id=active.publication_id,
                expected_revision=active.revision,
            )
        except RuntimeError as error:
            raise PublicationConflictError("active publication changed before rollback") from error
        return PublicationOutcome(
            decision="rolled_back",
            publication_id=target_publication_id,
            active_publication=rolled_back,
        )
