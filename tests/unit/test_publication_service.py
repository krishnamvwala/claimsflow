from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from claimsflow.adapters.in_memory_publication import InMemoryPublicationRepository
from claimsflow.domain.publication import (
    CandidateInventoryEntry,
    FinancialReconciliation,
    GateResult,
    MembershipDeltaEntry,
    PartitionRange,
    PublicationCandidate,
    PublicationManifest,
    PublishedRelation,
    RelationInventory,
    ResultVersionReference,
    RowReconciliation,
    relation_inventory_sha256,
)
from claimsflow.publication import (
    CandidateCollisionError,
    CompactionRequiredError,
    PublicationConflictError,
    PublicationService,
    PublicationValidationError,
)

NOW = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_fingerprint(publication_id: str, selection: str, code_commit: str) -> str:
    canonical = f"candidate-build-v1\n{publication_id}\n{selection}\n{code_commit}"
    return hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def _gates(failed: str | None = None) -> tuple[GateResult, ...]:
    names = (
        "validation",
        "dbt_build",
        "freshness",
        "row_reconciliation",
        "financial_reconciliation",
    )
    return tuple(
        GateResult(
            name=name,
            status="failed" if name == failed else "passed",
            evidence_ref=f"artifacts/{name}.json",
            evidence_sha256=_sha(name),
        )
        for name in names
    )


def _manifest(
    publication_id: str,
    *,
    parent: str | None = None,
    chain: tuple[str, ...] | None = None,
    membership_mode: str = "delta",
    failed_gate: str | None = None,
    impact_bounded: bool = True,
    row_count: int = 1,
) -> PublicationManifest:
    selection_fingerprint = "1" * 32
    code_commit = "a" * 40
    build_fingerprint = _build_fingerprint(
        publication_id,
        selection_fingerprint,
        code_commit,
    )
    relation = PublishedRelation(
        logical_name="fact_claim",
        business_key_column="claim_fact_id",
        candidate_relation=(
            "demo.claimsflow_curated.fact_claim"
            f"__{publication_id}__{selection_fingerprint}__{build_fingerprint}"
        ),
    )
    ranges = (
        PartitionRange(
            relation="fact_claim",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        ),
    )
    return PublicationManifest(
        publication_id=publication_id,
        parent_publication_id=parent,
        membership_delta_chain=chain or (publication_id,),
        membership_mode=membership_mode,  # type: ignore[arg-type]
        environment="dev-demo",
        code_commit=code_commit,
        dbt_validation_selection_fingerprint=selection_fingerprint,
        dbt_candidate_build_fingerprint=build_fingerprint,
        dbt_artifact_version="1.12.2",
        dbt_artifact_sha256=_sha(f"artifact:{publication_id}"),
        included_batch_ids=("batch-20260822-001",),
        contract_version="1.0.0",
        dictionary_version="1.0.0",
        warehouse_partition_ranges=ranges,
        bi_partition_ranges=ranges if impact_bounded else (),
        impact_bounded=impact_bounded,
        gate_results=_gates(failed_gate),
        published_relations=(relation,),
        relation_inventories=(
            RelationInventory(
                logical_relation="fact_claim",
                row_count=row_count,
                inventory_sha256="0" * 64,
            ),
        ),
        row_reconciliations=(
            RowReconciliation(
                logical_relation="fact_claim",
                expected_rows=row_count,
                actual_rows=row_count,
            ),
        ),
        financial_reconciliations=(
            FinancialReconciliation(
                logical_relation="fact_claim",
                measure="total_billed_amount",
                expected_amount=Decimal("100.00"),
                actual_amount=Decimal("100.00"),
                tolerance=Decimal("0.00"),
            ),
        ),
        created_at_utc=NOW,
    )


def _upsert(
    manifest: PublicationManifest,
    business_key: str,
    payload: str,
    *,
    sequence: int = 0,
) -> tuple[MembershipDeltaEntry, ResultVersionReference]:
    result_version_id = _sha(f"{manifest.publication_id}:{business_key}:{payload}")
    reference = ResultVersionReference(
        result_version_id=result_version_id,
        source_publication_id=manifest.publication_id,
        logical_relation="fact_claim",
        business_key=business_key,
        result_sha256=_sha(payload),
        physical_relation=manifest.published_relations[0].candidate_relation,
    )
    return (
        MembershipDeltaEntry(
            sequence=sequence,
            logical_relation="fact_claim",
            business_key=business_key,
            result_version_id=result_version_id,
            tombstone=False,
        ),
        reference,
    )


def _candidate(
    manifest: PublicationManifest,
    *changes: tuple[MembershipDeltaEntry, ResultVersionReference],
    inventory: tuple[CandidateInventoryEntry, ...] | None = None,
) -> PublicationCandidate:
    final_inventory = (
        inventory
        if inventory is not None
        else tuple(
            CandidateInventoryEntry(
                logical_relation=change[1].logical_relation,
                business_key=change[1].business_key,
                result_sha256=change[1].result_sha256,
            )
            for change in changes
        )
    )
    committed_manifest = _commit_inventory(manifest, final_inventory)
    return PublicationCandidate(
        manifest=committed_manifest,
        membership_delta=tuple(change[0] for change in changes),
        result_versions=tuple(change[1] for change in changes),
        inventory=final_inventory,
    )


def _commit_inventory(
    manifest: PublicationManifest,
    inventory: tuple[CandidateInventoryEntry, ...],
) -> PublicationManifest:
    return replace(
        manifest,
        relation_inventories=(
            RelationInventory(
                logical_relation="fact_claim",
                row_count=len(inventory),
                inventory_sha256=relation_inventory_sha256(inventory),
            ),
        ),
    )


def test_passing_candidate_activates_atomically_and_identical_retry_is_no_op() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    manifest = _manifest("pub_001")
    candidate = _candidate(manifest, _upsert(manifest, "claim-1", "first"))

    first = service.publish(candidate)
    replay = service.publish(candidate)

    assert first.decision == "published"
    assert replay.decision == "already_active"
    assert replay.active_publication == first.active_publication
    assert len(repository.activations) == 1
    membership = service.resolve_active("dev-demo")
    assert [(item.business_key, item.mapping_publication_id) for item in membership] == [
        ("claim-1", "pub_001")
    ]


def test_failed_candidate_is_retained_but_cannot_change_active_membership() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first_manifest = _manifest("pub_001")
    service.publish(_candidate(first_manifest, _upsert(first_manifest, "claim-1", "first")))
    failed_manifest = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
        failed_gate="dbt_build",
    )

    failed_candidate = _candidate(
        failed_manifest,
        _upsert(failed_manifest, "claim-1", "partial"),
    )
    result = service.publish(failed_candidate)

    assert result.decision == "blocked"
    assert result.failed_gates == ("dbt_build",)
    assert repository.get_manifest("pub_002") == failed_candidate.manifest
    assert repository.get_active("dev-demo").publication_id == "pub_001"  # type: ignore[union-attr]
    assert service.resolve_active("dev-demo")[0].mapping_publication_id == "pub_001"


def test_failed_or_cross_environment_result_versions_cannot_be_reused() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first = _manifest("pub_001")
    service.publish(_candidate(first, _upsert(first, "claim-1", "first")))

    failed = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
        failed_gate="dbt_build",
    )
    failed_change = _upsert(failed, "claim-1", "blocked-content")
    service.publish(_candidate(failed, failed_change))

    passing = _manifest(
        "pub_003",
        parent="pub_001",
        chain=("pub_001", "pub_003"),
    )
    reused_delta = replace(
        failed_change[0],
        sequence=0,
    )
    passing_inventory = (
        CandidateInventoryEntry(
            "fact_claim",
            "claim-1",
            failed_change[1].result_sha256,
        ),
    )
    with pytest.raises(PublicationValidationError, match="untrusted candidate"):
        service.publish(
            PublicationCandidate(
                manifest=_commit_inventory(passing, passing_inventory),
                membership_delta=(reused_delta,),
                result_versions=(),
                inventory=passing_inventory,
            )
        )

    local = replace(
        _manifest("local_001"),
        environment="local",
    )
    with pytest.raises(PublicationValidationError, match="untrusted candidate"):
        service.publish(
            PublicationCandidate(
                manifest=_commit_inventory(local, passing_inventory),
                membership_delta=(reused_delta,),
                result_versions=(),
                inventory=passing_inventory,
            )
        )


def test_complete_inventory_detects_omitted_update_and_equal_count_delete_add() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first = _manifest("pub_001")
    service.publish(_candidate(first, _upsert(first, "claim-1", "first")))

    omitted_update = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
    )
    changed_inventory = (CandidateInventoryEntry("fact_claim", "claim-1", _sha("changed")),)
    with pytest.raises(PublicationValidationError, match="exactly represent"):
        service.publish(
            PublicationCandidate(
                manifest=_commit_inventory(omitted_update, changed_inventory),
                membership_delta=(),
                result_versions=(),
                inventory=changed_inventory,
            )
        )

    delete_add = _manifest(
        "pub_003",
        parent="pub_001",
        chain=("pub_001", "pub_003"),
    )
    replacement_inventory = (CandidateInventoryEntry("fact_claim", "claim-2", _sha("replacement")),)
    with pytest.raises(PublicationValidationError, match="exactly represent"):
        service.publish(
            PublicationCandidate(
                manifest=_commit_inventory(delete_add, replacement_inventory),
                membership_delta=(),
                result_versions=(),
                inventory=replacement_inventory,
            )
        )


def test_changed_mapping_and_tombstone_create_complete_next_snapshot() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first = _manifest("pub_001", row_count=2)
    service.publish(
        _candidate(
            first,
            _upsert(first, "claim-1", "first", sequence=0),
            _upsert(first, "claim-2", "second", sequence=1),
        )
    )
    second = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
    )
    changed = _upsert(second, "claim-1", "corrected", sequence=0)
    tombstone = MembershipDeltaEntry(
        sequence=1,
        logical_relation="fact_claim",
        business_key="claim-2",
        result_version_id=None,
        tombstone=True,
    )

    final_inventory = (CandidateInventoryEntry("fact_claim", "claim-1", changed[1].result_sha256),)
    service.publish(
        PublicationCandidate(
            manifest=_commit_inventory(second, final_inventory),
            membership_delta=(changed[0], tombstone),
            result_versions=(changed[1],),
            inventory=final_inventory,
        )
    )

    membership = service.resolve_active("dev-demo")
    assert [(item.business_key, item.mapping_publication_id) for item in membership] == [
        ("claim-1", "pub_002")
    ]


def test_rollback_selects_exact_previously_active_snapshot() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first = _manifest("pub_001")
    first_result = _upsert(first, "claim-1", "first")
    service.publish(_candidate(first, first_result))
    second = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
    )
    service.publish(_candidate(second, _upsert(second, "claim-1", "corrected")))

    result = service.rollback(
        "dev-demo",
        expected_active_publication_id="pub_002",
        target_publication_id="pub_001",
        reason="operator-confirmed reconciliation regression",
    )

    assert result.decision == "rolled_back"
    assert result.active_publication is not None
    assert result.active_publication.publication_id == "pub_001"
    assert result.active_publication.revision == 3
    assert (
        service.resolve_active("dev-demo")[0].result_version_id == first_result[0].result_version_id
    )
    assert repository.activations[-1].kind == "rollback"


def test_concurrent_parent_and_identity_conflicts_fail_closed() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first = _manifest("pub_001")
    service.publish(_candidate(first, _upsert(first, "claim-1", "first")))
    winner = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
    )
    stale = _manifest(
        "pub_003",
        parent="pub_001",
        chain=("pub_001", "pub_003"),
    )
    winner_candidate = _candidate(winner, _upsert(winner, "claim-1", "winner"))
    service.publish(winner_candidate)

    with pytest.raises(PublicationConflictError, match="parent"):
        service.publish(_candidate(stale, _upsert(stale, "claim-1", "stale")))

    collision = replace(winner, dbt_artifact_sha256=_sha("different-artifact"))
    with pytest.raises(CandidateCollisionError):
        service.publish(_candidate(collision, _upsert(collision, "claim-1", "winner")))

    with pytest.raises(CandidateCollisionError, match="candidate evidence"):
        service.publish(
            replace(
                winner_candidate,
                membership_delta=(replace(winner_candidate.membership_delta[0], sequence=1),),
            )
        )


def test_redundant_delta_unknown_tombstone_and_missing_gate_are_rejected() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(repository, clock=lambda: NOW)
    first = _manifest("pub_001")
    service.publish(_candidate(first, _upsert(first, "claim-1", "same")))
    second = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
    )

    with pytest.raises(PublicationValidationError, match="exactly represent"):
        service.publish(_candidate(second, _upsert(second, "claim-1", "same")))

    unknown_tombstone = MembershipDeltaEntry(
        sequence=0,
        logical_relation="fact_claim",
        business_key="missing",
        result_version_id=None,
        tombstone=True,
    )
    with pytest.raises(PublicationValidationError, match="exactly represent"):
        service.publish(
            PublicationCandidate(
                manifest=_commit_inventory(
                    second,
                    (CandidateInventoryEntry("fact_claim", "claim-1", _sha("same")),),
                ),
                membership_delta=(unknown_tombstone,),
                result_versions=(),
                inventory=(CandidateInventoryEntry("fact_claim", "claim-1", _sha("same")),),
            )
        )

    missing_gate = replace(
        second,
        gate_results=tuple(gate for gate in second.gate_results if gate.name != "freshness"),
    )
    with pytest.raises(PublicationValidationError, match="missing required gates"):
        service.publish(_candidate(missing_gate, _upsert(missing_gate, "claim-1", "changed")))


def test_chain_cap_requires_isolated_base_compaction() -> None:
    repository = InMemoryPublicationRepository()
    service = PublicationService(
        repository,
        max_membership_chain_depth=2,
        clock=lambda: NOW,
    )
    first = _manifest("pub_001")
    first_result = _upsert(first, "claim-1", "first")
    service.publish(_candidate(first, first_result))
    second = _manifest(
        "pub_002",
        parent="pub_001",
        chain=("pub_001", "pub_002"),
    )
    second_result = _upsert(second, "claim-1", "second")
    service.publish(_candidate(second, second_result))
    too_deep = _manifest(
        "pub_003",
        parent="pub_002",
        chain=("pub_001", "pub_002", "pub_003"),
    )

    with pytest.raises(CompactionRequiredError):
        service.publish(_candidate(too_deep, _upsert(too_deep, "claim-1", "third")))

    compacted = _manifest(
        "pub_003",
        parent="pub_002",
        chain=("pub_003",),
        membership_mode="base",
    )
    base_mapping = MembershipDeltaEntry(
        sequence=0,
        logical_relation="fact_claim",
        business_key="claim-1",
        result_version_id=second_result[0].result_version_id,
        tombstone=False,
    )
    result = service.publish(
        PublicationCandidate(
            manifest=_commit_inventory(
                compacted,
                (CandidateInventoryEntry("fact_claim", "claim-1", _sha("second")),),
            ),
            membership_delta=(base_mapping,),
            result_versions=(),
            inventory=(CandidateInventoryEntry("fact_claim", "claim-1", _sha("second")),),
        )
    )

    assert result.decision == "published"
    assert service.resolve_active("dev-demo")[0].mapping_publication_id == "pub_003"


def test_manifest_canonical_round_trip_preserves_fingerprint() -> None:
    manifest = _manifest("pub_001")

    restored = PublicationManifest.from_dict(manifest.as_dict())

    assert restored == manifest
    assert restored.fingerprint == manifest.fingerprint


def test_manifest_rejects_code_fingerprint_or_relation_alias_drift() -> None:
    manifest = _manifest("pub_001")

    with pytest.raises(ValueError, match="contradicts publication"):
        replace(manifest, dbt_candidate_build_fingerprint="f" * 32)

    with pytest.raises(ValueError, match="bound to the manifest"):
        replace(
            manifest,
            published_relations=(
                replace(
                    manifest.published_relations[0],
                    candidate_relation="demo.claimsflow_curated.fact_claim__shared",
                ),
            ),
        )


def test_candidate_inventory_requires_canonical_key_order() -> None:
    manifest = _manifest("pub_001", row_count=2)
    claim_two = _upsert(manifest, "claim-2", "second", sequence=0)
    claim_one = _upsert(manifest, "claim-1", "first", sequence=1)

    with pytest.raises(ValueError, match="canonical relation/business-key order"):
        _candidate(manifest, claim_two, claim_one)
