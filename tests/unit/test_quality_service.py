from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from claimsflow.adapters.local_registry import SqliteIngestionRegistry
from claimsflow.domain.ingestion import IngestionResult
from claimsflow.domain.quality import QualityCorrection
from claimsflow.generator import GenerationConfig, generate_delivery
from claimsflow.ingestion import ingest_delivery
from claimsflow.quality import QualityValidationError, validate_ingestion_quality

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/source-data"
POLICY = ROOT / "config/data-quality-policy.yml"


def _ingested_batch(tmp_path: Path) -> tuple[GenerationConfig, IngestionResult]:
    config = GenerationConfig.from_values(seed=42, claim_count=8, service_month="2026-07")
    delivery = generate_delivery(config, tmp_path / "delivery")
    result = ingest_delivery(
        delivery.manifest_path,
        tmp_path / "workspace",
        CONTRACTS,
        clock=lambda: config.generated_at + timedelta(minutes=30),
    )
    return config, result


def _report(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _first_raw_record(result: Any, source_identity: str) -> tuple[Path, dict[str, Any]]:
    ingestion_report = _report(result.report_path)
    file_item = next(
        item for item in ingestion_report["files"] if item["source_identity"] == source_identity
    )
    raw_path = result.artifact_directory / file_item["artifacts"]["raw"]
    first_line = raw_path.read_text(encoding="utf-8").splitlines()[0]
    return raw_path, cast(dict[str, Any], json.loads(first_line))


def test_complete_synthetic_batch_produces_reconciled_quality_evidence(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)

    result = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        clock=lambda: config.generated_at + timedelta(hours=1),
    )

    report = _report(result.report_path)
    assert result.decision == "approved"
    assert result.publication_allowed is True
    assert result.raw_rows == ingestion.raw_rows
    assert result.accepted + result.warned == result.raw_rows
    assert result.quarantined == result.rejected == 0
    assert result.reconciled is True
    assert report["rule_version"] == "1.0.0"
    assert report["rule_execution_manifest"]["cross_source_relationship"] == "executed"
    assert report["artifact_inventory"]
    inventory = report["rule_execution_manifest"]["source_rule_inventory"]
    identity_rule_pairs = {pair for pairs in inventory.values() for pair in pairs}
    assert len(identity_rule_pairs) == 131
    assert len({pair.split("|", 1)[1] for pair in identity_rule_pairs}) == 83
    assert "reference-data.denial-reasons|DQ-REF-007" in inventory["phase3_semantic"]
    assert "reference-data.facilities|DQ-REF-007" in inventory["not_applicable"]
    assert len(report["configuration"]["contracts"]) == 14
    assert len(report["configuration"]["implementation"]) == 4
    receipt = SqliteIngestionRegistry(ingestion.workspace).get_quality_run(result.validation_id)
    assert receipt is not None
    assert receipt.report_sha256 == result.report_sha256


def test_exact_replay_returns_verified_duplicate_no_op(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    evaluation_time = config.generated_at + timedelta(hours=1)
    first = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        clock=lambda: evaluation_time,
    )

    replay = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        clock=lambda: evaluation_time,
    )

    assert replay.decision == "duplicate_no_op"
    assert replay.validation_id == first.validation_id
    assert replay.report_sha256 == first.report_sha256


def test_later_evaluation_window_creates_updated_freshness_evidence(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    first = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        clock=lambda: config.generated_at + timedelta(hours=1),
    )

    later = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        clock=lambda: config.generated_at + timedelta(days=2),
    )

    later_report = _report(later.report_path)
    assert later.validation_id != first.validation_id
    assert later.decision == "approved"
    assert (
        later_report["evaluation_window_started_at_utc"]
        != _report(first.report_path)["evaluation_window_started_at_utc"]
    )
    assert any(source["freshness"]["status"] == "late" for source in later_report["sources"])


def test_tampered_raw_evidence_is_rejected_before_quality_output(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    raw_path, _ = _first_raw_record(ingestion, "claims")
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(QualityValidationError, match="inventory"):
        validate_ingestion_quality(
            ingestion,
            CONTRACTS,
            POLICY,
            clock=lambda: config.generated_at,
        )

    assert not (ingestion.workspace / "quality-runs").exists()


def test_correction_preserves_original_and_revised_synthetic_evidence(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    _, raw_record = _first_raw_record(ingestion, "claims")
    revised_payload = dict(cast(dict[str, str], raw_record["raw_payload"]))
    revised_payload["payer_id"] = "SYN-PAYER-99"
    correction = QualityCorrection(
        correction_id="SYN-CORRECTION-001",
        source_identity="claims",
        source_record_id=cast(str, raw_record["source_record_id"]),
        expected_payload_sha256=cast(str, raw_record["payload_sha256"]),
        revised_payload=revised_payload,
        actor_source="synthetic_reviewer",
        reason="Synthetic payer mapping correction scenario",
        corrected_at_utc=(config.generated_at + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )

    result = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        corrections=(correction,),
        clock=lambda: config.generated_at + timedelta(hours=2),
    )

    history_path = result.output_directory / "corrections/history.jsonl"
    history = json.loads(history_path.read_text(encoding="utf-8").splitlines()[0])
    assert result.correction_count == 1
    assert result.quarantined > 0
    assert result.decision == "blocked"
    assert result.publication_allowed is False
    assert result.issue_count >= result.blocking_issue_count > 0
    assert history["original_payload"]["payer_id"] != history["revised_payload"]["payer_id"]
    assert history["actor_source"] == "synthetic_reviewer"


def test_quality_output_cannot_be_written_inside_immutable_batch(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)

    with pytest.raises(QualityValidationError, match="must not modify"):
        validate_ingestion_quality(
            ingestion,
            CONTRACTS,
            POLICY,
            output_root=ingestion.artifact_directory / "quality",
            clock=lambda: config.generated_at,
        )


def test_intermediate_output_symlink_to_external_directory_is_rejected(
    tmp_path: Path,
) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "external-alias"
    alias.symlink_to(external, target_is_directory=True)

    with pytest.raises(QualityValidationError, match="symlink component"):
        validate_ingestion_quality(
            ingestion,
            CONTRACTS,
            POLICY,
            output_root=alias / "quality-runs",
            clock=lambda: config.generated_at,
        )

    assert list(external.iterdir()) == []


def test_symlinked_output_parent_cannot_route_writes_into_immutable_batch(
    tmp_path: Path,
) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    alias = tmp_path / "batch-alias"
    alias.symlink_to(ingestion.artifact_directory, target_is_directory=True)

    with pytest.raises(QualityValidationError, match="symlink component"):
        validate_ingestion_quality(
            ingestion,
            CONTRACTS,
            POLICY,
            output_root=alias / "quality",
            clock=lambda: config.generated_at,
        )


def test_inconsistent_ingestion_result_cannot_claim_a_complete_batch(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    inconsistent = replace(ingestion, duplicate_files=1)

    with pytest.raises(QualityValidationError, match="fully processed"):
        validate_ingestion_quality(
            inconsistent,
            CONTRACTS,
            POLICY,
            clock=lambda: config.generated_at,
        )


def test_two_corrections_cannot_compete_for_the_same_raw_record(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    _, raw_record = _first_raw_record(ingestion, "claims")
    revised_payload = dict(cast(dict[str, str], raw_record["raw_payload"]))
    revised_payload["payer_id"] = "SYN-PAYER-99"
    first = QualityCorrection(
        correction_id="SYN-CORRECTION-001",
        source_identity="claims",
        source_record_id=cast(str, raw_record["source_record_id"]),
        expected_payload_sha256=cast(str, raw_record["payload_sha256"]),
        revised_payload=revised_payload,
        actor_source="synthetic_reviewer",
        reason="Synthetic payer mapping correction scenario",
        corrected_at_utc=(config.generated_at + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    second = replace(first, correction_id="SYN-CORRECTION-002")

    with pytest.raises(QualityValidationError, match="at most once"):
        validate_ingestion_quality(
            ingestion,
            CONTRACTS,
            POLICY,
            corrections=(first, second),
            clock=lambda: config.generated_at + timedelta(hours=2),
        )


def test_blocked_report_cannot_be_changed_to_approved_on_replay(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    _, raw_record = _first_raw_record(ingestion, "claims")
    revised_payload = dict(cast(dict[str, str], raw_record["raw_payload"]))
    revised_payload["payer_id"] = "SYN-PAYER-99"
    correction = QualityCorrection(
        correction_id="SYN-CORRECTION-TAMPER",
        source_identity="claims",
        source_record_id=cast(str, raw_record["source_record_id"]),
        expected_payload_sha256=cast(str, raw_record["payload_sha256"]),
        revised_payload=revised_payload,
        actor_source="synthetic_reviewer",
        reason="Synthetic blocked-report tamper scenario",
        corrected_at_utc=(config.generated_at + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    evaluation_time = config.generated_at + timedelta(hours=2)
    result = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        corrections=(correction,),
        clock=lambda: evaluation_time,
    )
    assert result.publication_allowed is False
    report = _report(result.report_path)
    report["decision"] = "approved"
    report["publication_allowed"] = True
    result.report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(QualityValidationError, match="checksum changed"):
        validate_ingestion_quality(
            ingestion,
            CONTRACTS,
            POLICY,
            corrections=(correction,),
            clock=lambda: evaluation_time,
        )


def test_policy_bytes_change_validation_identity_without_version_change(
    tmp_path: Path,
) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    policy = tmp_path / "quality-policy.yml"
    shutil.copy2(POLICY, policy)
    evaluation_time = config.generated_at + timedelta(hours=1)
    first = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        policy,
        clock=lambda: evaluation_time,
    )
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            "Source evidence exceeded", "Synthetic source evidence exceeded"
        ),
        encoding="utf-8",
    )

    second = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        policy,
        clock=lambda: evaluation_time,
    )

    assert second.validation_id != first.validation_id
    assert (
        _report(second.report_path)["configuration"]["policy_sha256"]
        != _report(first.report_path)["configuration"]["policy_sha256"]
    )


def test_contract_bytes_change_validation_identity_without_version_change(
    tmp_path: Path,
) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, contracts)
    evaluation_time = config.generated_at + timedelta(hours=1)
    first = validate_ingestion_quality(
        ingestion,
        contracts,
        POLICY,
        clock=lambda: evaluation_time,
    )
    claims_contract = contracts / "claims.yml"
    claims_contract.write_text(
        claims_contract.read_text(encoding="utf-8").replace(
            "Source claim headers from synthetic EHR and clearinghouse extracts.",
            "Source claim headers from governed synthetic portfolio extracts.",
        ),
        encoding="utf-8",
    )

    second = validate_ingestion_quality(
        ingestion,
        contracts,
        POLICY,
        clock=lambda: evaluation_time,
    )

    first_contracts = {
        item["source_identity"]: item["sha256"]
        for item in _report(first.report_path)["configuration"]["contracts"]
    }
    second_contracts = {
        item["source_identity"]: item["sha256"]
        for item in _report(second.report_path)["configuration"]["contracts"]
    }
    assert second.validation_id != first.validation_id
    assert second_contracts["claims"] != first_contracts["claims"]


def test_correction_that_creates_duplicate_claim_key_is_rejected(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    raw_path, _ = _first_raw_record(ingestion, "claims")
    raw_records = [
        cast(dict[str, Any], json.loads(line))
        for line in raw_path.read_text(encoding="utf-8").splitlines()
    ]
    first, second = raw_records[:2]
    revised_payload = dict(cast(dict[str, str], second["raw_payload"]))
    first_payload = cast(dict[str, str], first["raw_payload"])
    revised_payload["claim_id"] = first_payload["claim_id"]
    revised_payload["submission_sequence"] = first_payload["submission_sequence"]
    correction = QualityCorrection(
        correction_id="SYN-CORRECTION-DUPLICATE",
        source_identity="claims",
        source_record_id=cast(str, second["source_record_id"]),
        expected_payload_sha256=cast(str, second["payload_sha256"]),
        revised_payload=revised_payload,
        actor_source="synthetic_reviewer",
        reason="Synthetic duplicate claim-key scenario",
        corrected_at_utc=(config.generated_at + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )

    result = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        corrections=(correction,),
        clock=lambda: config.generated_at + timedelta(hours=2),
    )

    rejected = [
        json.loads(line)
        for line in (result.output_directory / "rejected/records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    corrected = next(item for item in rejected if item["correction_id"] == correction.correction_id)
    assert "DQ-CLM-002" in {issue["rule_id"] for issue in corrected["issues"]}
    assert result.publication_allowed is False


def test_payment_correction_cannot_create_self_reversal(tmp_path: Path) -> None:
    config, ingestion = _ingested_batch(tmp_path)
    _, raw_record = _first_raw_record(ingestion, "payments")
    revised_payload = dict(cast(dict[str, str], raw_record["raw_payload"]))
    lineage = cast(dict[str, Any], raw_record["lineage"])
    revised_payload.update(
        {
            "transaction_type": "reversal",
            "direction": "debit",
            "adjustment_reason_code": "SYN-ADJUSTMENT-SELF-REVERSAL",
            "reverses_payment_source_system": cast(str, lineage["source_system"]),
            "reverses_payment_id": revised_payload["payment_id"],
            "posting_status": "reversed",
        }
    )
    correction = QualityCorrection(
        correction_id="SYN-CORRECTION-SELF-REVERSAL",
        source_identity="payments",
        source_record_id=cast(str, raw_record["source_record_id"]),
        expected_payload_sha256=cast(str, raw_record["payload_sha256"]),
        revised_payload=revised_payload,
        actor_source="synthetic_reviewer",
        reason="Synthetic payment self-reversal scenario",
        corrected_at_utc=(config.generated_at + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )

    result = validate_ingestion_quality(
        ingestion,
        CONTRACTS,
        POLICY,
        corrections=(correction,),
        clock=lambda: config.generated_at + timedelta(hours=2),
    )

    quarantined = [
        json.loads(line)
        for line in (result.output_directory / "quarantine/records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    corrected = next(
        item for item in quarantined if item["correction_id"] == correction.correction_id
    )
    assert "DQ-PAY-008" in {issue["rule_id"] for issue in corrected["issues"]}
    assert result.publication_allowed is False
