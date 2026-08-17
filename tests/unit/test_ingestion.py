from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from claimsflow.adapters.local_registry import SqliteIngestionRegistry
from claimsflow.domain.ingestion import IngestionResult, RegistryCollisionError
from claimsflow.generator import GenerationConfig, generate_delivery
from claimsflow.ingestion import ContractCatalog, IngestionError, ingest_delivery
from claimsflow.ingestion.validation import classify_row

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/source-data"
REPORT_SCHEMA = json.loads((ROOT / "config/local-ingestion-report.schema.json").read_text())
FIRST_INGESTED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
SECOND_INGESTED_AT = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)


def _delivery(tmp_path: Path, name: str = "delivery", seed: int = 42) -> Path:
    config = GenerationConfig.from_values(seed=seed, claim_count=8, service_month="2026-07")
    return generate_delivery(config, tmp_path / name).output_directory


def _manifest(delivery: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((delivery / "manifest.json").read_text()))


def _write_manifest(delivery: Path, manifest: dict[str, Any]) -> None:
    (delivery / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _entry(manifest: dict[str, Any], family: str) -> dict[str, Any]:
    return next(item for item in manifest["files"] if item["source_family"] == family)


def _rewrite_rows(delivery: Path, family: str, mutate: object) -> None:
    manifest = _manifest(delivery)
    entry = _entry(manifest, family)
    path = delivery / entry["path"]
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = cast(list[str], reader.fieldnames)
    assert callable(mutate)
    mutate(rows)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    entry["row_count"] = len(rows)
    manifest["row_count_reconciliation"]["generated_rows"] = sum(
        item["row_count"] for item in manifest["files"]
    )
    manifest["row_count_reconciliation"]["written_rows"] = manifest["row_count_reconciliation"][
        "generated_rows"
    ]
    _write_manifest(delivery, manifest)


def _json_lines(path: Path) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], json.loads(line)) for line in path.read_text().splitlines()]


def _source_file_rows(delivery: Path, family: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    manifest = _manifest(delivery)
    entry = _entry(manifest, family)
    with (delivery / entry["path"]).open(newline="", encoding="utf-8") as source:
        return entry, list(csv.DictReader(source))


def test_contract_catalog_loads_exact_fourteen_file_inventory() -> None:
    catalog = ContractCatalog.load(CONTRACTS)

    assert len(catalog.identities()) == 14
    assert catalog.identities() == (
        "appeals",
        "claim-lines",
        "claims",
        "denials",
        "eligibility",
        "payments",
        "reference-data.denial-reasons",
        "reference-data.diagnoses",
        "reference-data.facilities",
        "reference-data.payers",
        "reference-data.plans",
        "reference-data.procedures",
        "reference-data.providers",
        "remittances",
    )


def test_valid_delivery_is_landed_classified_and_fully_auditable(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    result = ingest_delivery(
        delivery / "manifest.json",
        workspace,
        CONTRACTS,
        clock=lambda: FIRST_INGESTED_AT,
    )

    assert result.decision == "processed"
    assert result.file_count == result.processed_files == 14
    assert result.duplicate_files == result.duplicate_no_op_rows == 0
    assert result.raw_rows == result.declared_rows
    assert result.accepted == result.raw_rows
    assert result.warned == result.quarantined == result.rejected == 0
    assert result.reconciled is True

    report = cast(dict[str, Any], json.loads(result.report_path.read_text()))
    validator = Draft202012Validator(REPORT_SCHEMA, format_checker=FormatChecker())
    assert list(validator.iter_errors(report)) == []
    assert report["reconciliation"]["disposition_rows"] == result.raw_rows
    assert (result.artifact_directory / "landing/manifest.json").is_file()

    raw_files = sorted((result.artifact_directory / "raw").glob("*.jsonl"))
    assert len(raw_files) == 14
    raw_rows = [row for path in raw_files for row in _json_lines(path)]
    assert len(raw_rows) == result.raw_rows
    assert all(row["synthetic_only"] is True for row in raw_rows)
    assert all(row["lineage"]["batch_id"] == result.batch_id for row in raw_rows)
    assert all(row["lineage"]["source_row_number"] >= 1 for row in raw_rows)
    assert all(row["source_record_id"] and row["payload_sha256"] for row in raw_rows)

    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 14
        assert (
            connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] == result.raw_rows
        )


def test_identical_batch_replay_is_an_audited_no_op(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    first = ingest_delivery(
        delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )
    report_before = first.report_path.read_bytes()

    replay = ingest_delivery(
        delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
    )

    assert replay.decision == "duplicate_no_op"
    assert replay.processed_files == replay.raw_rows == 0
    assert replay.duplicate_files == 14
    assert replay.duplicate_no_op_rows == replay.declared_rows
    assert replay.report_path.read_bytes() == report_before
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] == first.raw_rows
        )
        decisions = [
            row[0]
            for row in connection.execute("SELECT decision FROM ingestion_events ORDER BY event_id")
        ]
    assert decisions == ["processed", "duplicate_no_op"]


def test_changed_file_is_rejected_before_workspace_creation(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    manifest = _manifest(delivery)
    claims = delivery / _entry(manifest, "claims")["path"]
    claims.write_bytes(claims.read_bytes() + b"\n")
    workspace = tmp_path / "must-not-exist"

    with pytest.raises(IngestionError, match="checksum"):
        ingest_delivery(delivery / "manifest.json", workspace, CONTRACTS)

    assert not workspace.exists()


def test_invalid_utf8_is_reported_without_creating_payload_storage(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    manifest = _manifest(delivery)
    entry = _entry(manifest, "claims")
    claims = delivery / entry["path"]
    claims.write_bytes(claims.read_bytes() + b"\xff")
    entry["sha256"] = hashlib.sha256(claims.read_bytes()).hexdigest()
    _write_manifest(delivery, manifest)
    workspace = tmp_path / "must-not-exist"

    with pytest.raises(IngestionError, match=r"decode|UTF-8|codec"):
        ingest_delivery(delivery / "manifest.json", workspace, CONTRACTS)

    assert not workspace.exists()


def test_unapproved_generator_is_rejected_before_workspace_creation(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    manifest = _manifest(delivery)
    manifest["generator"]["name"] = "unknown-generator"
    _write_manifest(delivery, manifest)
    workspace = tmp_path / "must-not-exist"

    with pytest.raises(IngestionError, match=r"generator\.name"):
        ingest_delivery(delivery / "manifest.json", workspace, CONTRACTS)

    assert not workspace.exists()


def test_rows_receive_all_four_dispositions_from_contract_policy(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    entry, rows = _source_file_rows(delivery, "payments")
    contract = ContractCatalog.load(CONTRACTS).for_manifest_entry(entry)
    rows[0]["transaction_type"] = " payer_payment "
    rows[1]["amount"] = "-1.00"
    rows[2]["payment_id"] = ""
    classified = [
        classify_row(
            contract,
            row,
            cast(str, entry["source_system"]),
            duplicate_natural_key=index == 3,
        )
        for index, row in enumerate(rows[:4])
    ]

    assert [row.disposition for row in classified] == [
        "accepted_with_warning",
        "quarantined",
        "rejected",
        "rejected",
    ]
    assert classified[0].original_payload["transaction_type"] == " payer_payment "
    assert classified[0].normalized_payload["transaction_type"] == "payer_payment"
    rule_ids = {issue.rule_id for row in classified for issue in row.issues}
    assert {"NORM-CMN-001", "DQ-PAY-001", "DQ-PAY-002", "DQ-PAY-004"} <= rule_ids


def test_registered_batch_cannot_be_replayed_with_forged_evidence(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    ingest_delivery(
        delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )

    def mutate(rows: list[dict[str, str]]) -> None:
        rows[0]["transaction_type"] = " patient_payment "

    _rewrite_rows(delivery, "payments", mutate)

    with pytest.raises(IngestionError, match="approved deterministic output"):
        ingest_delivery(
            delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
        )

    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        decisions = [
            row[0]
            for row in connection.execute("SELECT decision FROM ingestion_events ORDER BY event_id")
        ]
    assert decisions == ["processed"]


def test_repeated_reference_files_are_no_ops_inside_a_new_batch(tmp_path: Path) -> None:
    first_delivery = _delivery(tmp_path, "first", seed=1)
    second_delivery = _delivery(tmp_path, "second", seed=2)
    workspace = tmp_path / "workspace"
    ingest_delivery(
        first_delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )

    second = ingest_delivery(
        second_delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
    )

    assert second.decision == "processed"
    assert second.duplicate_files == 7
    assert second.processed_files == 7
    assert second.raw_rows + second.duplicate_no_op_rows == second.declared_rows
    report = cast(dict[str, Any], json.loads(second.report_path.read_text()))
    duplicates = [item for item in report["files"] if item["decision"] == "duplicate_no_op"]
    assert {item["source_family"] for item in duplicates} == {"reference-data"}
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        repeated_processed = connection.execute(
            """
            SELECT COUNT(*)
            FROM deliveries
            WHERE decision = 'processed'
            GROUP BY source_identity, source_system, checksum_sha256
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    assert repeated_processed == []


def test_registry_failure_rolls_back_published_batch_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"

    def fail_registration(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("safe injected registry failure")

    monkeypatch.setattr(SqliteIngestionRegistry, "register_batch", fail_registration)

    with pytest.raises(IngestionError, match="failed atomically"):
        ingest_delivery(
            delivery / "manifest.json",
            workspace,
            CONTRACTS,
            clock=lambda: FIRST_INGESTED_AT,
        )

    assert list((workspace / "batches").iterdir()) == []
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0


def test_commit_acknowledgement_loss_keeps_committed_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    original_register = SqliteIngestionRegistry.register_batch

    def commit_then_raise(registry: SqliteIngestionRegistry, *args: Any, **kwargs: Any) -> None:
        original_register(registry, *args, **kwargs)
        raise sqlite3.OperationalError("simulated lost commit acknowledgement")

    monkeypatch.setattr(SqliteIngestionRegistry, "register_batch", commit_then_raise)
    result = ingest_delivery(
        delivery / "manifest.json",
        workspace,
        CONTRACTS,
        clock=lambda: FIRST_INGESTED_AT,
    )

    assert result.artifact_directory.is_dir()
    assert result.report_path.is_file()
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ingestion_intents").fetchone()[0] == 0


def test_recomputed_manifest_cannot_forge_approved_generator_provenance(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    manifest = _manifest(delivery)
    provider_entry = next(
        item
        for item in manifest["files"]
        if item["source_family"] == "reference-data" and item["dataset"] == "providers"
    )
    provider_path = delivery / provider_entry["path"]
    with provider_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = cast(list[str], reader.fieldnames)
    rows[0]["provider_name"] = "UNAPPROVED CUSTOMER PROVIDER NAME"
    with provider_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    provider_entry["sha256"] = hashlib.sha256(provider_path.read_bytes()).hexdigest()
    _write_manifest(delivery, manifest)
    workspace = tmp_path / "must-not-exist"

    with pytest.raises(IngestionError, match="approved deterministic output"):
        ingest_delivery(delivery / "manifest.json", workspace, CONTRACTS)

    assert not workspace.exists()


def test_financial_contract_rules_execute_for_claims_and_lines(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    catalog = ContractCatalog.load(CONTRACTS)
    found: set[str] = set()
    for family, expected in (
        ("claims", {"DQ-CLM-007", "DQ-CLM-012"}),
        ("claim-lines", {"DQ-CLN-009", "DQ-CLN-010"}),
    ):
        entry, rows = _source_file_rows(delivery, family)
        contract = catalog.for_manifest_entry(entry)
        row = rows[0]
        row["allowed_amount"] = "0.00"
        row["patient_responsibility_amount"] = "0.00"
        row["patient_paid_amount"] = "1.00"
        row["payer_paid_amount"] = "1.00"
        classified = classify_row(contract, row, cast(str, entry["source_system"]), False)
        rule_ids = {issue.rule_id for issue in classified.issues}
        assert expected <= rule_ids
        assert classified.disposition == "quarantined"
        found.update(rule_ids)
    assert {"DQ-CLM-007", "DQ-CLM-012", "DQ-CLN-009", "DQ-CLN-010"} <= found


def test_numeric_boolean_and_whitespace_policy_is_exact(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    catalog = ContractCatalog.load(CONTRACTS)
    payment_entry, payment_rows = _source_file_rows(delivery, "payments")
    payment_contract = catalog.for_manifest_entry(payment_entry)

    too_precise = dict(payment_rows[0], amount="1.001")
    invalid = classify_row(
        payment_contract,
        too_precise,
        cast(str, payment_entry["source_system"]),
        False,
    )
    assert invalid.disposition == "rejected"
    assert "DQ-CMN-013" in {issue.rule_id for issue in invalid.issues}

    short_scale = dict(payment_rows[0], amount="1.0")
    normalized = classify_row(
        payment_contract,
        short_scale,
        cast(str, payment_entry["source_system"]),
        False,
    )
    assert normalized.normalized_payload["amount"] == "1.00"
    assert "NORM-CMN-005" in {issue.rule_id for issue in normalized.issues}

    padded_numeric = dict(payment_rows[0], amount=" 1.00 ")
    whitespace = classify_row(
        payment_contract,
        padded_numeric,
        cast(str, payment_entry["source_system"]),
        False,
    )
    assert whitespace.disposition == "rejected"
    assert "NORM-CMN-001" not in {issue.rule_id for issue in whitespace.issues}

    eligibility_entry, eligibility_rows = _source_file_rows(delivery, "eligibility")
    eligibility_contract = catalog.for_manifest_entry(eligibility_entry)
    uppercase_boolean = dict(eligibility_rows[0], primary_coverage_flag="TRUE")
    boolean = classify_row(
        eligibility_contract,
        uppercase_boolean,
        cast(str, eligibility_entry["source_system"]),
        False,
    )
    assert boolean.normalized_payload["primary_coverage_flag"] == "true"
    assert "NORM-CMN-004" in {issue.rule_id for issue in boolean.issues}


def test_processing_reads_verified_landing_copy_not_mutable_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery = _delivery(tmp_path)
    claims_entry = _entry(_manifest(delivery), "claims")
    claims_source = delivery / claims_entry["path"]
    original_copy2 = __import__("shutil").copy2

    def mutate_after_copy(
        source: object, target: object, *args: object, **kwargs: object
    ) -> object:
        result = original_copy2(source, target, *args, **kwargs)
        if Path(cast(str, source)) == claims_source:
            claims_source.write_bytes(claims_source.read_bytes().replace(b",paid,", b",void,", 1))
        return result

    monkeypatch.setattr("claimsflow.ingestion.service.shutil.copy2", mutate_after_copy)
    ingested = ingest_delivery(
        delivery / "manifest.json",
        tmp_path / "workspace",
        CONTRACTS,
        clock=lambda: FIRST_INGESTED_AT,
    )

    landing = ingested.artifact_directory / "landing/files" / claims_entry["file_name"]
    assert hashlib.sha256(landing.read_bytes()).hexdigest() == claims_entry["sha256"]
    raw_claims = _json_lines(ingested.artifact_directory / "raw/claims.jsonl")
    assert all(row["raw_payload"]["claim_status"] != "void" for row in raw_claims)


def test_replay_blocks_when_any_registered_artifact_is_tampered(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    first = ingest_delivery(
        delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )
    (first.artifact_directory / "raw/claims.jsonl").write_text(
        '{"tampered":true}\n', encoding="utf-8"
    )

    with pytest.raises(IngestionError, match="artifact inventory"):
        ingest_delivery(
            delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
        )

    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT decision FROM ingestion_events ORDER BY event_id DESC LIMIT 1"
            ).fetchone()[0]
            == "blocked"
        )


def test_replay_blocks_when_persisted_summary_contradicts_hashed_report(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    ingest_delivery(
        delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        connection.execute("UPDATE batches SET file_count = 99, declared_rows = 999999")

    with pytest.raises(IngestionError, match="persisted batch summary contradicts"):
        ingest_delivery(
            delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
        )


def test_partial_duplicate_rejects_tampered_original_evidence(tmp_path: Path) -> None:
    first_delivery = _delivery(tmp_path, "first", 801)
    second_delivery = _delivery(tmp_path, "second", 802)
    workspace = tmp_path / "workspace"
    first = ingest_delivery(
        first_delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )
    (first.artifact_directory / "raw/reference_data_providers.jsonl").write_text(
        '{"tampered":true}\n', encoding="utf-8"
    )

    with pytest.raises(IngestionError, match="artifact inventory"):
        ingest_delivery(
            second_delivery / "manifest.json",
            workspace,
            CONTRACTS,
            clock=lambda: SECOND_INGESTED_AT,
        )

    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1


def test_replay_revalidates_duplicate_dependencies(tmp_path: Path) -> None:
    first_delivery = _delivery(tmp_path, "first", 811)
    second_delivery = _delivery(tmp_path, "second", 812)
    workspace = tmp_path / "workspace"
    first = ingest_delivery(
        first_delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
    )
    second = ingest_delivery(
        second_delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
    )
    assert second.duplicate_files == 7
    (first.artifact_directory / "raw/reference_data_providers.jsonl").write_text(
        '{"tampered":true}\n', encoding="utf-8"
    )

    with pytest.raises(IngestionError, match="artifact inventory"):
        ingest_delivery(
            second_delivery / "manifest.json",
            workspace,
            CONTRACTS,
            clock=lambda: SECOND_INGESTED_AT,
        )


def test_fresh_registry_initialization_is_concurrency_safe(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    with ThreadPoolExecutor(max_workers=6) as executor:
        registries = list(executor.map(lambda _: SqliteIngestionRegistry(workspace), range(12)))

    assert len(registries) == 12
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.parametrize(
    ("managed_name", "directory"),
    [
        ("batches", True),
        ("collisions", True),
        ("ingestion-registry.sqlite3", False),
        ("ingestion-registry.sqlite3-wal", False),
        ("ingestion-registry.sqlite3-shm", False),
        ("ingestion-registry.sqlite3-journal", False),
        (".registry-init.lock", False),
        (".ingestion.lock", False),
    ],
)
def test_managed_workspace_symlinks_cannot_escape_boundary(
    tmp_path: Path, managed_name: str, directory: bool
) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    target = outside / "target"
    if directory:
        target.mkdir()
    else:
        target.write_text("sentinel", encoding="utf-8")
    (workspace / managed_name).symlink_to(target, target_is_directory=directory)

    with pytest.raises(IngestionError, match=r"registry is unavailable|unsafe"):
        ingest_delivery(delivery / "manifest.json", workspace, CONTRACTS)

    if directory:
        assert list(target.iterdir()) == []
    else:
        assert target.read_text(encoding="utf-8") == "sentinel"


def test_concurrent_batches_do_not_double_process_identical_reference_files(
    tmp_path: Path,
) -> None:
    deliveries = [_delivery(tmp_path, "first", 101), _delivery(tmp_path, "second", 102)]
    workspace = tmp_path / "workspace"

    def ingest(delivery: Path) -> IngestionResult:
        return ingest_delivery(
            delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(ingest, deliveries))

    assert sorted(result.processed_files for result in results) == [7, 14]
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        repeated = connection.execute(
            """
            SELECT source_identity, source_system, checksum_sha256
            FROM deliveries
            WHERE decision = 'processed'
            GROUP BY source_identity, source_system, checksum_sha256
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    assert repeated == []


def test_interrupted_publication_is_recovered_from_durable_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"
    original_register = SqliteIngestionRegistry.register_batch

    def terminate_after_publish(*args: object, **kwargs: object) -> None:
        raise SystemExit("simulated abrupt termination")

    monkeypatch.setattr(SqliteIngestionRegistry, "register_batch", terminate_after_publish)
    with pytest.raises(SystemExit, match="abrupt termination"):
        ingest_delivery(
            delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
        )
    monkeypatch.setattr(SqliteIngestionRegistry, "register_batch", original_register)

    recovered = ingest_delivery(
        delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: SECOND_INGESTED_AT
    )

    assert recovered.decision == "processed"
    assert recovered.artifact_directory.is_dir()
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingestion_intents").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1


def test_version_collision_preserves_incoming_payload_and_structured_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery = _delivery(tmp_path)
    workspace = tmp_path / "workspace"

    def collision(*args: object, **kwargs: object) -> None:
        raise RegistryCollisionError(
            source_identity="claims",
            natural_key='["synthetic_claims","SYN-CLM-EXAMPLE","1"]',
            version_discriminator="2026-08-01T00:00:00Z",
            existing_payload_sha256="a" * 64,
            incoming_payload_sha256="b" * 64,
            existing_batch_id="CF-202607-000000000001",
        )

    monkeypatch.setattr(SqliteIngestionRegistry, "register_batch", collision)
    with pytest.raises(IngestionError, match="DQ-CMN-011"):
        ingest_delivery(
            delivery / "manifest.json", workspace, CONTRACTS, clock=lambda: FIRST_INGESTED_AT
        )

    collision_directories = list((workspace / "collisions").iterdir())
    assert len(collision_directories) == 1
    evidence = collision_directories[0]
    assert (evidence / "raw/claims.jsonl").is_file()
    details = json.loads((evidence / "audit/collision.json").read_text())
    assert details["incoming_payload_sha256"] == "b" * 64
    with sqlite3.connect(workspace / "ingestion-registry.sqlite3") as connection:
        event = connection.execute(
            "SELECT decision, details_json FROM ingestion_events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
    assert event[0] == "blocked"
    assert json.loads(event[1])["incoming_artifact_directory"] == str(evidence)


def test_report_schema_rejects_contradictory_duplicate_evidence(tmp_path: Path) -> None:
    delivery = _delivery(tmp_path)
    result = ingest_delivery(
        delivery / "manifest.json",
        tmp_path / "workspace",
        CONTRACTS,
        clock=lambda: FIRST_INGESTED_AT,
    )
    report = cast(dict[str, Any], json.loads(result.report_path.read_text()))
    report["decision"] = "duplicate_no_op"
    report["files"][0]["decision"] = "duplicate_no_op"

    validator = Draft202012Validator(REPORT_SCHEMA, format_checker=FormatChecker())
    assert list(validator.iter_errors(report))
