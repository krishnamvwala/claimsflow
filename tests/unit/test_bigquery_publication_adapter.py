from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

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

NOW = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _candidate() -> PublicationCandidate:
    publication_id = "pub_001"
    selection_fingerprint = "1" * 32
    code_commit = "a" * 40
    build_fingerprint = hashlib.md5(
        (f"candidate-build-v1\n{publication_id}\n{selection_fingerprint}\n{code_commit}").encode(),
        usedforsecurity=False,
    ).hexdigest()
    relation = PublishedRelation(
        logical_name="fact_claim",
        business_key_column="claim_fact_id",
        candidate_relation=(
            "demo.claimsflow_curated.fact_claim"
            f"__{publication_id}__{selection_fingerprint}__{build_fingerprint}"
        ),
    )
    affected = PartitionRange(
        relation="fact_claim",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )
    gates = tuple(
        GateResult(
            name=name,
            status="passed",
            evidence_ref=f"artifacts/{name}.json",
            evidence_sha256=_sha(name),
        )
        for name in (
            "validation",
            "dbt_build",
            "freshness",
            "row_reconciliation",
            "financial_reconciliation",
        )
    )
    inventory = (
        CandidateInventoryEntry(
            logical_relation="fact_claim",
            business_key="claim-1'; DROP TABLE unsafe; --",
            result_sha256=_sha("first"),
        ),
    )
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
        dbt_artifact_sha256=_sha("artifact"),
        included_batch_ids=("batch-20260822-001",),
        contract_version="1.0.0",
        dictionary_version="1.0.0",
        warehouse_partition_ranges=(affected,),
        bi_partition_ranges=(affected,),
        impact_bounded=True,
        gate_results=gates,
        published_relations=(relation,),
        relation_inventories=(
            RelationInventory(
                logical_relation="fact_claim",
                row_count=1,
                inventory_sha256=relation_inventory_sha256(inventory),
            ),
        ),
        row_reconciliations=(
            RowReconciliation(
                logical_relation="fact_claim",
                expected_rows=1,
                actual_rows=1,
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
    result_version_id = _sha("pub_001:claim-1:first")
    reference = ResultVersionReference(
        result_version_id=result_version_id,
        source_publication_id=publication_id,
        logical_relation="fact_claim",
        business_key="claim-1'; DROP TABLE unsafe; --",
        result_sha256=_sha("first"),
        physical_relation=relation.candidate_relation,
    )
    delta = MembershipDeltaEntry(
        sequence=0,
        logical_relation="fact_claim",
        business_key=reference.business_key,
        result_version_id=result_version_id,
        tombstone=False,
    )
    return PublicationCandidate(
        manifest=manifest,
        membership_delta=(delta,),
        result_versions=(reference,),
        inventory=inventory,
    )


class FakeJob:
    def __init__(self, rows: Iterable[Mapping[str, object]]) -> None:
        self.rows = tuple(rows)

    def result(self, *, timeout: float | None = None) -> Iterable[Mapping[str, object]]:
        assert timeout == 30.0
        return self.rows


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, tuple[str, object]]]] = []
        self.responses: dict[str, tuple[Mapping[str, object], ...]] = {}

    def query(self, query: str, *, location: str, job_config: object) -> FakeJob:
        assert location == "US"
        assert isinstance(job_config, dict)
        self.calls.append((query, cast(dict[str, tuple[str, object]], job_config)))
        marker = query.splitlines()[0]
        return FakeJob(self.responses.get(marker, ()))


def _repository(client: RecordingClient) -> GoogleBigQueryPublicationRepository:
    return GoogleBigQueryPublicationRepository(
        client,
        project="claimsflow-demo-synthetic",
        query_config_factory=lambda parameters: dict(parameters),
        query_timeout_seconds=30.0,
    )


def test_schema_and_candidate_append_use_create_only_transactional_control_tables() -> None:
    client = RecordingClient()
    repository = _repository(client)
    candidate = _candidate()

    repository.ensure_schema()
    repository.append_candidate(candidate)

    schema_sql = client.calls[0][0]
    assert schema_sql.count("CREATE TABLE IF NOT EXISTS") == 7
    assert "publication_manifests" in schema_sql
    assert "publication_membership_deltas" in schema_sql
    assert "publication_result_versions" in schema_sql
    assert "publication_candidate_inventory" in schema_sql
    assert "inventory_sequence INT64 NOT NULL" in schema_sql
    assert "active_publications" in schema_sql
    assert "publication_activations" in schema_sql
    assert "publication_reservation_locks" in schema_sql
    assert "MERGE" not in schema_sql
    assert "CLUSTER BY environment AS" in schema_sql
    assert "CLUSTER BY lock_bucket AS" in schema_sql
    assert "UNNEST(['local', 'dev-demo'])" in schema_sql
    assert "GENERATE_ARRAY(0, 63)" in schema_sql
    assert "control rows are not exactly preseeded" in schema_sql
    assert "reservation locks are not exactly preseeded" in schema_sql
    append_sql, raw_parameters = client.calls[1]
    parameters = dict(raw_parameters)
    assert "BEGIN TRANSACTION" in append_sql
    assert "UPDATE" in append_sql and "publication_reservation_locks" in append_sql
    assert "WITH OFFSET AS inventory_sequence" in append_sql
    assert "ASSERT @@row_count = 1" in append_sql
    assert append_sql.count("ASSERT") >= 4
    assert "COMMIT TRANSACTION" in append_sql
    assert candidate.membership_delta[0].business_key not in append_sql
    persisted_delta = json.loads(str(parameters["membership_delta_json"][1]))
    assert persisted_delta[0]["business_key"] == candidate.membership_delta[0].business_key
    assert parameters["manifest_fingerprint"][1] == candidate.manifest.fingerprint
    persisted_inventory = json.loads(str(parameters["inventory_json"][1]))
    assert persisted_inventory == [candidate.inventory[0].as_dict()]
    assert parameters["reservation_bucket"][0] == "INT64"


def test_repository_rehydrates_manifest_delta_result_and_active_pointer() -> None:
    client = RecordingClient()
    repository = _repository(client)
    candidate = _candidate()
    reference = candidate.result_versions[0]
    delta = candidate.membership_delta[0]
    client.responses = {
        "-- claimsflow:get_publication_manifest": (
            {"manifest_json": candidate.manifest.as_dict()},
        ),
        "-- claimsflow:get_membership_delta": (delta.as_dict(),),
        "-- claimsflow:get_result_version": (reference.as_dict(),),
        "-- claimsflow:get_candidate_inventory": (candidate.inventory[0].as_dict(),),
        "-- claimsflow:get_active_publication": (
            {
                "environment": "dev-demo",
                "publication_id": "pub_001",
                "revision": 1,
                "updated_at_utc": NOW,
            },
        ),
        "-- claimsflow:was_publication_activated": ({"was_activated": True},),
    }

    assert repository.get_manifest("pub_001") == candidate.manifest
    assert repository.get_membership_delta("pub_001") == (delta,)
    assert repository.get_result_version(reference.result_version_id) == reference
    assert repository.get_candidate_inventory("pub_001") == candidate.inventory
    assert repository.get_active("dev-demo").publication_id == "pub_001"  # type: ignore[union-attr]
    assert repository.was_activated("dev-demo", "pub_001") is True


def test_active_pointer_compare_and_swap_is_single_transaction_with_revision_guard() -> None:
    client = RecordingClient()
    repository = _repository(client)
    client.responses["-- claimsflow:compare_and_swap_active_publication"] = (
        {
            "environment": "dev-demo",
            "publication_id": "pub_001",
            "revision": 1,
            "updated_at_utc": NOW,
        },
    )
    event = ActivationEvent(
        event_id=_sha("activation"),
        kind="publish",
        environment="dev-demo",
        from_publication_id=None,
        to_publication_id="pub_001",
        from_revision=0,
        to_revision=1,
        reason="all gates passed",
        activated_at_utc=NOW,
    )

    active = repository.compare_and_swap_active(
        event,
        expected_publication_id=None,
        expected_revision=0,
    )

    assert active.publication_id == "pub_001"
    sql, raw_parameters = client.calls[0]
    parameters = dict(raw_parameters)
    assert "BEGIN TRANSACTION" in sql
    assert "IS NOT DISTINCT FROM @expected_publication_id" in sql
    assert "current_revision = @expected_revision" in sql
    assert "active publication control row is missing or not unique" in sql
    assert "IS DISTINCT FROM 'passed'" in sql
    assert "physical relations are not bound to exact selection and code" in sql
    assert sql.count("REGEXP_CONTAINS(") >= 3
    assert "ENDS_WITH(" in sql and ") IS DISTINCT FROM TRUE" in sql
    assert "manifest chain shape is invalid" in sql
    assert "ASSERT COALESCE((" in sql
    assert "BETWEEN 1 AND @max_membership_chain_depth" in sql
    assert "missing or failed publication gates" in sql
    assert "unreconciled control" in sql
    assert "missing, duplicate, or broken manifest chain" in sql
    assert "complete inventory" in sql
    assert "manifest commitment" in sql
    assert "duplicate sequence values" in sql
    assert "untrusted result-version source" in sql
    assert "rollback target was never previously active" in sql
    assert "IF current_count = 0" not in sql
    assert "ASSERT @@row_count = 1 AS 'active publication compare-and-swap conflict'" in sql
    assert "INSERT INTO" in sql and "publication_activations" in sql
    assert parameters["expected_publication_id"] == ("STRING", None)
    assert parameters["expected_revision"] == ("INT64", 0)
    assert parameters["max_membership_chain_depth"] == ("INT64", 8)


def test_active_pointer_rejects_an_event_that_contradicts_expected_state() -> None:
    client = RecordingClient()
    repository = _repository(client)
    event = ActivationEvent(
        event_id=_sha("contradictory-activation"),
        kind="publish",
        environment="dev-demo",
        from_publication_id="pub_001",
        to_publication_id="pub_002",
        from_revision=1,
        to_revision=2,
        reason="all gates passed",
        activated_at_utc=NOW,
    )

    with pytest.raises(BigQueryPublicationError, match="contradicts"):
        repository.compare_and_swap_active(
            event,
            expected_publication_id=None,
            expected_revision=0,
        )

    assert client.calls == []
