"""Thread-safe reference repository for publication tests and local demonstrations."""

from __future__ import annotations

from threading import RLock

from claimsflow.domain.publication import (
    ActivationEvent,
    ActivePublication,
    CandidateInventoryEntry,
    MembershipDeltaEntry,
    PublicationCandidate,
    PublicationEnvironment,
    PublicationManifest,
    ResultVersionReference,
)


class InMemoryPublicationRepository:
    """Implements create-only evidence and compare-and-swap pointer semantics in memory."""

    def __init__(self) -> None:
        self._manifests: dict[str, PublicationManifest] = {}
        self._deltas: dict[str, tuple[MembershipDeltaEntry, ...]] = {}
        self._result_versions: dict[str, ResultVersionReference] = {}
        self._candidate_result_versions: dict[
            str,
            tuple[ResultVersionReference, ...],
        ] = {}
        self._inventories: dict[str, tuple[CandidateInventoryEntry, ...]] = {}
        self._active: dict[PublicationEnvironment, ActivePublication] = {}
        self._activations: list[ActivationEvent] = []
        self._lock = RLock()

    @property
    def activations(self) -> tuple[ActivationEvent, ...]:
        with self._lock:
            return tuple(self._activations)

    def get_manifest(self, publication_id: str) -> PublicationManifest | None:
        with self._lock:
            return self._manifests.get(publication_id)

    def get_membership_delta(
        self,
        publication_id: str,
    ) -> tuple[MembershipDeltaEntry, ...]:
        with self._lock:
            return self._deltas.get(publication_id, ())

    def get_result_version(self, result_version_id: str) -> ResultVersionReference | None:
        with self._lock:
            return self._result_versions.get(result_version_id)

    def get_candidate_inventory(
        self,
        publication_id: str,
    ) -> tuple[CandidateInventoryEntry, ...]:
        with self._lock:
            return self._inventories.get(publication_id, ())

    def append_candidate(self, candidate: PublicationCandidate) -> None:
        with self._lock:
            publication_id = candidate.manifest.publication_id
            existing = self._manifests.get(publication_id)
            if existing is not None:
                if (
                    existing.fingerprint != candidate.manifest.fingerprint
                    or self._deltas[publication_id] != candidate.membership_delta
                    or self._candidate_result_versions[publication_id] != candidate.result_versions
                    or self._inventories[publication_id] != candidate.inventory
                ):
                    raise RuntimeError("publication candidate identity collision")
                return
            for reference in candidate.result_versions:
                prior = self._result_versions.get(reference.result_version_id)
                if prior is not None and prior != reference:
                    raise RuntimeError("result version identity collision")
            available = {
                *self._result_versions,
                *(reference.result_version_id for reference in candidate.result_versions),
            }
            if any(
                not entry.tombstone and entry.result_version_id not in available
                for entry in candidate.membership_delta
            ):
                raise RuntimeError("membership references an unavailable result version")
            self._manifests[publication_id] = candidate.manifest
            self._deltas[publication_id] = tuple(
                sorted(candidate.membership_delta, key=lambda item: item.sequence)
            )
            self._result_versions.update(
                {item.result_version_id: item for item in candidate.result_versions}
            )
            self._candidate_result_versions[publication_id] = candidate.result_versions
            self._inventories[publication_id] = candidate.inventory

    def get_active(
        self,
        environment: PublicationEnvironment,
    ) -> ActivePublication | None:
        with self._lock:
            return self._active.get(environment)

    def compare_and_swap_active(
        self,
        event: ActivationEvent,
        *,
        expected_publication_id: str | None,
        expected_revision: int,
    ) -> ActivePublication:
        with self._lock:
            current = self._active.get(event.environment)
            current_id = current.publication_id if current is not None else None
            current_revision = current.revision if current is not None else 0
            if (
                current_id != expected_publication_id
                or current_revision != expected_revision
                or event.from_publication_id != expected_publication_id
                or event.from_revision != expected_revision
            ):
                raise RuntimeError("active publication compare-and-swap conflict")
            if event.to_publication_id not in self._manifests:
                raise RuntimeError("activation target manifest does not exist")
            active = ActivePublication(
                environment=event.environment,
                publication_id=event.to_publication_id,
                revision=event.to_revision,
                updated_at_utc=event.activated_at_utc,
            )
            self._active[event.environment] = active
            self._activations.append(event)
            return active

    def was_activated(
        self,
        environment: PublicationEnvironment,
        publication_id: str,
    ) -> bool:
        with self._lock:
            return any(
                event.environment == environment and event.to_publication_id == publication_id
                for event in self._activations
            )
