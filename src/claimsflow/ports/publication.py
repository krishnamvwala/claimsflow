"""Infrastructure-independent persistence contract for safe warehouse publication."""

from __future__ import annotations

from typing import Protocol

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


class PublicationRepository(Protocol):
    """Stores immutable candidate evidence and atomically advances one active pointer."""

    def get_manifest(self, publication_id: str) -> PublicationManifest | None:
        """Return one immutable manifest, if it has been staged."""
        ...

    def get_membership_delta(
        self,
        publication_id: str,
    ) -> tuple[MembershipDeltaEntry, ...]:
        """Return one immutable candidate membership delta in sequence order."""
        ...

    def get_result_version(self, result_version_id: str) -> ResultVersionReference | None:
        """Return immutable result-version evidence, if it exists."""
        ...

    def get_candidate_inventory(
        self,
        publication_id: str,
    ) -> tuple[CandidateInventoryEntry, ...]:
        """Return one candidate's immutable complete business-key/hash inventory."""
        ...

    def append_candidate(self, candidate: PublicationCandidate) -> None:
        """Atomically create candidate evidence or prove an identical retry."""
        ...

    def get_active(
        self,
        environment: PublicationEnvironment,
    ) -> ActivePublication | None:
        """Return the currently active pointer for an environment."""
        ...

    def compare_and_swap_active(
        self,
        event: ActivationEvent,
        *,
        expected_publication_id: str | None,
        expected_revision: int,
    ) -> ActivePublication:
        """Advance exactly once only when both expected pointer values still match."""
        ...

    def was_activated(
        self,
        environment: PublicationEnvironment,
        publication_id: str,
    ) -> bool:
        """Return whether the target was previously selected by an activation event."""
        ...
