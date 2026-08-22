"""Opt-in live proof of BigQuery publication reservation and genesis CAS serialization."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from claimsflow.adapters.bigquery_publication import (
    BigQueryPublicationError,
    GoogleBigQueryPublicationRepository,
)
from claimsflow.domain.publication import (
    ActivationEvent,
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

RUN_LIVE = os.getenv("CLAIMSFLOW_RUN_BIGQUERY_CONCURRENCY") == "1"
PROJECT = os.getenv("CLAIMSFLOW_BIGQUERY_TEST_PROJECT", "")

pytestmark = [
    pytest.mark.gcp_integration,
    pytest.mark.skipif(
        not RUN_LIVE or not PROJECT,
        reason=(
            "set CLAIMSFLOW_RUN_BIGQUERY_CONCURRENCY=1 and "
            "CLAIMSFLOW_BIGQUERY_TEST_PROJECT for the authorized live synthetic gate"
        ),
    ),
]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _candidate(publication_id: str, content: str) -> PublicationCandidate:
    selection_fingerprint = "1" * 32
    code_commit = "a" * 40
    build_fingerprint = hashlib.md5(
        (f"candidate-build-v1\n{publication_id}\n{selection_fingerprint}\n{code_commit}").encode(),
        usedforsecurity=False,
    ).hexdigest()
    physical_relation = (
        f"{PROJECT}.claimsflow_curated.fact_claim"
        f"__{publication_id}__{selection_fingerprint}__{build_fingerprint}"
    )
    inventory = (CandidateInventoryEntry("fact_claim", "claim-1", _sha(content)),)
    manifest = PublicationManifest(
        publication_id=publication_id,
        parent_publication_id=None,
        membership_delta_chain=(publication_id,),
        membership_mode="delta",
        environment="dev-demo",
        code_commit=code_commit,
        dbt_validation_selection_fingerprint=selection_fingerprint,
        dbt_candidate_build_fingerprint=build_fingerprint,
        dbt_artifact_version="1.12.2",
        dbt_artifact_sha256=_sha(f"artifact:{content}"),
        included_batch_ids=("synthetic-batch-001",),
        contract_version="1.0.0",
        dictionary_version="1.0.0",
        warehouse_partition_ranges=(
            PartitionRange("fact_claim", date(2026, 8, 1), date(2026, 8, 1)),
        ),
        bi_partition_ranges=(PartitionRange("fact_claim", date(2026, 8, 1), date(2026, 8, 1)),),
        impact_bounded=True,
        gate_results=tuple(
            GateResult(name, "passed", f"synthetic/{name}.json", _sha(name))
            for name in (
                "validation",
                "dbt_build",
                "freshness",
                "row_reconciliation",
                "financial_reconciliation",
            )
        ),
        published_relations=(PublishedRelation("fact_claim", "claim_fact_id", physical_relation),),
        relation_inventories=(
            RelationInventory("fact_claim", 1, relation_inventory_sha256(inventory)),
        ),
        row_reconciliations=(RowReconciliation("fact_claim", 1, 1),),
        financial_reconciliations=(
            FinancialReconciliation(
                "fact_claim",
                "total_billed_amount",
                Decimal("1.00"),
                Decimal("1.00"),
                Decimal("0.00"),
            ),
        ),
        created_at_utc=datetime.now(UTC),
    )
    result = ResultVersionReference(
        _sha(f"{publication_id}:{content}"),
        publication_id,
        "fact_claim",
        "claim-1",
        _sha(content),
        physical_relation,
    )
    return PublicationCandidate(
        manifest=manifest,
        membership_delta=(
            MembershipDeltaEntry(0, "fact_claim", "claim-1", result.result_version_id, False),
        ),
        result_versions=(result,),
        inventory=inventory,
    )


def _event(publication_id: str) -> ActivationEvent:
    now = datetime.now(UTC)
    return ActivationEvent(
        event_id=_sha(f"activate:{publication_id}:{now.isoformat()}"),
        kind="publish",
        environment="dev-demo",
        from_publication_id=None,
        to_publication_id=publication_id,
        from_revision=0,
        to_revision=1,
        reason="authorized synthetic BigQuery concurrency integration test",
        activated_at_utc=now,
    )


def test_live_bigquery_serializes_identity_reservation_and_first_activation() -> None:
    from google.cloud import bigquery

    dataset = f"claimsflow_pub_it_{uuid4().hex[:12]}"
    client = bigquery.Client(project=PROJECT)
    dataset_ref = bigquery.Dataset(f"{PROJECT}.{dataset}")
    dataset_ref.location = "US"
    client.create_dataset(dataset_ref)
    repository = GoogleBigQueryPublicationRepository(
        client,
        project=PROJECT,
        dataset=dataset,
        query_timeout_seconds=180.0,
    )
    peer_repository = GoogleBigQueryPublicationRepository(
        client,
        project=PROJECT,
        dataset=dataset,
        query_timeout_seconds=180.0,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            bootstrap_futures = [
                executor.submit(candidate_repository.ensure_schema)
                for candidate_repository in (repository, peer_repository)
            ]
            for future in bootstrap_futures:
                assert future.result() is None

        collision_a = _candidate("collision_001", "first")
        collision_b = replace(
            collision_a,
            manifest=replace(
                collision_a.manifest,
                dbt_artifact_sha256=_sha("different-artifact"),
            ),
        )
        reservation_outcomes: list[object] = []
        reservation_failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(repository.append_candidate, candidate)
                for candidate in (collision_a, collision_b)
            ]
            for future in futures:
                try:
                    reservation_outcomes.append(future.result())
                except Exception as error:
                    reservation_failures.append(error)

        assert len(reservation_outcomes) == 1
        assert len(reservation_failures) == 1
        assert isinstance(reservation_failures[0], BigQueryPublicationError)
        manifest_count = next(
            iter(
                client.query(
                    f"SELECT COUNT(*) AS count FROM `{PROJECT}.{dataset}.publication_manifests` "
                    "WHERE publication_id = 'collision_001'"
                ).result()
            )
        )["count"]
        assert manifest_count == 1

        first = _candidate("genesis_001", "first")
        second = _candidate("genesis_002", "second")
        repository.append_candidate(first)
        repository.append_candidate(second)

        def activate(candidate: PublicationCandidate) -> object:
            return repository.compare_and_swap_active(
                _event(candidate.manifest.publication_id),
                expected_publication_id=None,
                expected_revision=0,
            )

        outcomes: list[object] = []
        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(activate, candidate) for candidate in (first, second)]
            for future in futures:
                try:
                    outcomes.append(future.result())
                except Exception as error:
                    failures.append(error)

        assert len(outcomes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], BigQueryPublicationError)
        pointer_rows = tuple(
            client.query(
                f"SELECT publication_id, revision FROM `{PROJECT}.{dataset}.active_publications` "
                "WHERE environment = 'dev-demo'"
            ).result()
        )
        assert len(pointer_rows) == 1
        assert pointer_rows[0]["revision"] == 1
        activation_count = next(
            iter(
                client.query(
                    f"SELECT COUNT(*) AS count FROM `{PROJECT}.{dataset}.publication_activations`"
                ).result()
            )
        )["count"]
        assert activation_count == 1
    finally:
        client.delete_dataset(
            f"{PROJECT}.{dataset}",
            delete_contents=True,
            not_found_ok=True,
        )
