from __future__ import annotations

import copy
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator, FormatChecker

from claimsflow.generator import (
    GenerationConfig,
    GenerationError,
    ManifestValidationError,
    generate_delivery,
    validate_manifest,
)
from claimsflow.generator.catalog import PAYMENTS, SourceDefinition, source_definitions
from claimsflow.generator.models import MAX_CLAIM_COUNT

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA = json.loads((ROOT / "config/synthetic-delivery-manifest.schema.json").read_text())


def load_manifest(directory: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((directory / "manifest.json").read_text()))


def rows_for(directory: Path, manifest: dict[str, Any], family: str) -> list[dict[str, str]]:
    entries = [entry for entry in manifest["files"] if entry["source_family"] == family]
    assert len(entries) == 1
    with (directory / entries[0]["path"]).open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def test_config_is_bounded_and_has_stable_identity() -> None:
    config = GenerationConfig.from_values(
        seed=20_260_815,
        claim_count=100_000,
        service_month="2026-07",
    )

    assert config.claim_count == MAX_CLAIM_COUNT
    assert config.batch_id == "CF-202607-FD231BC1E260"
    assert config.generated_at.isoformat() == "2026-08-16T00:00:00+00:00"


def test_generator_version_is_part_of_batch_identity() -> None:
    config = GenerationConfig.from_values(seed=42, claim_count=20, service_month="2026-07")
    next_version = replace(config, generator_version="1.0.1")

    assert config.batch_id != next_version.batch_id
    assert config.delivery_namespace != next_version.delivery_namespace
    assert config.delivery_namespace.endswith(config.fingerprint_sha256.upper())


def test_delivery_namespace_does_not_truncate_colliding_hash_prefixes() -> None:
    first = GenerationConfig.from_values(seed=85_151, claim_count=100, service_month="2026-07")
    second = GenerationConfig.from_values(seed=90_394, claim_count=100, service_month="2026-07")

    assert first.fingerprint_sha256[:8] == second.fingerprint_sha256[:8]
    assert first.fingerprint_sha256 != second.fingerprint_sha256
    assert first.delivery_namespace != second.delivery_namespace


@pytest.mark.parametrize(
    ("seed", "claim_count", "service_month", "message"),
    [
        (-1, 1, "2026-07", "seed"),
        (2_147_483_648, 1, "2026-07", "seed"),
        (1, 0, "2026-07", "claim count"),
        (1, 100_001, "2026-07", "claim count"),
        (1, 1, "07-2026", "YYYY-MM"),
        (1, 1, "2026-7", "exact YYYY-MM"),
        (1, 1, "0001-01", "year"),
        (1, 1, "9999-12", "year"),
    ],
)
def test_config_rejects_unbounded_or_ambiguous_inputs(
    seed: int,
    claim_count: int,
    service_month: str,
    message: str,
) -> None:
    with pytest.raises(GenerationError, match=message):
        GenerationConfig.from_values(
            seed=seed,
            claim_count=claim_count,
            service_month=service_month,
        )


def test_delivery_is_byte_identical_for_the_same_configuration(tmp_path: Path) -> None:
    config = GenerationConfig.from_values(seed=42, claim_count=32, service_month="2026-07")
    first = generate_delivery(config, tmp_path / "first")
    second = generate_delivery(config, tmp_path / "second")

    first_files = {
        path.relative_to(first.output_directory): path.read_bytes()
        for path in first.output_directory.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.output_directory): path.read_bytes()
        for path in second.output_directory.rglob("*")
        if path.is_file()
    }

    assert first.batch_id == second.batch_id
    assert first_files == second_files


def test_delivery_scoped_identifiers_are_disjoint_across_batches(tmp_path: Path) -> None:
    first = generate_delivery(
        GenerationConfig.from_values(seed=1, claim_count=64, service_month="2026-07"),
        tmp_path / "first",
    )
    second = generate_delivery(
        GenerationConfig.from_values(seed=2, claim_count=64, service_month="2026-08"),
        tmp_path / "second",
    )
    first_manifest = load_manifest(first.output_directory)
    second_manifest = load_manifest(second.output_directory)

    identity_fields = {
        "claims": "claim_id",
        "claim-lines": "claim_line_id",
        "eligibility": "eligibility_id",
        "remittances": "remittance_id",
        "payments": "payment_id",
        "denials": "denial_id",
        "appeals": "appeal_id",
    }
    for family, field in identity_fields.items():
        first_ids = {row[field] for row in rows_for(first.output_directory, first_manifest, family)}
        second_ids = {
            row[field] for row in rows_for(second.output_directory, second_manifest, family)
        }
        assert first_ids.isdisjoint(second_ids)

    first_patients = {
        row["patient_id"] for row in rows_for(first.output_directory, first_manifest, "claims")
    }
    second_patients = {
        row["patient_id"] for row in rows_for(second.output_directory, second_manifest, "claims")
    }
    assert first_patients.isdisjoint(second_patients)


def test_manifest_proves_contracts_hashes_and_reconciliation(tmp_path: Path) -> None:
    config = GenerationConfig.from_values(seed=7, claim_count=40, service_month="2026-07")
    result = generate_delivery(config, tmp_path / "delivery")
    manifest = load_manifest(result.output_directory)

    validator = Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker())
    assert list(validator.iter_errors(manifest)) == []
    assert result.file_count == 14
    assert manifest["source_families"] == [
        "appeals",
        "claim-lines",
        "claims",
        "denials",
        "eligibility",
        "payments",
        "reference-data",
        "remittances",
    ]

    counted_rows = 0
    for entry in manifest["files"]:
        path = result.output_directory / entry["path"]
        assert path.name == entry["file_name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        with path.open(newline="", encoding="utf-8") as source:
            rows = list(csv.reader(source))
        assert len(rows) - 1 == entry["row_count"]
        counted_rows += entry["row_count"]

    reconciliation = manifest["row_count_reconciliation"]
    assert result.total_rows == counted_rows == reconciliation["generated_rows"]
    assert reconciliation["written_rows"] == reconciliation["generated_rows"]
    validate_manifest(manifest, result.output_directory)


def test_semantic_manifest_validation_rejects_false_evidence(tmp_path: Path) -> None:
    config = GenerationConfig.from_values(seed=7, claim_count=20, service_month="2026-07")
    result = generate_delivery(config, tmp_path / "delivery")
    manifest = load_manifest(result.output_directory)

    duplicate_inventory = copy.deepcopy(manifest)
    duplicate_inventory["files"] = [copy.deepcopy(manifest["files"][0]) for _ in range(14)]
    with pytest.raises(ManifestValidationError, match=r"inventory|unique"):
        validate_manifest(duplicate_inventory)

    false_count = copy.deepcopy(manifest)
    false_count["row_count_reconciliation"]["written_rows"] += 1
    with pytest.raises(ManifestValidationError, match="row-count reconciliation"):
        validate_manifest(false_count)

    false_identity = copy.deepcopy(manifest)
    false_identity["batch_id"] = "CF-202607-000000000000"
    with pytest.raises(ManifestValidationError, match="batch_id"):
        validate_manifest(false_identity)

    false_generator = copy.deepcopy(manifest)
    false_generator["generator"]["name"] = "unapproved-generator"
    with pytest.raises(ManifestValidationError, match=r"generator\.name"):
        validate_manifest(false_generator)


def test_generated_relationships_and_financial_controls_reconcile(tmp_path: Path) -> None:
    config = GenerationConfig.from_values(seed=20_260_815, claim_count=80, service_month="2026-07")
    result = generate_delivery(config, tmp_path / "delivery")
    manifest = load_manifest(result.output_directory)
    claims = rows_for(result.output_directory, manifest, "claims")
    claim_lines = rows_for(result.output_directory, manifest, "claim-lines")
    eligibility = rows_for(result.output_directory, manifest, "eligibility")
    remittances = rows_for(result.output_directory, manifest, "remittances")
    payments = rows_for(result.output_directory, manifest, "payments")
    denials = rows_for(result.output_directory, manifest, "denials")
    appeals = rows_for(result.output_directory, manifest, "appeals")

    claim_ids = {row["claim_id"] for row in claims}
    eligibility_ids = {row["eligibility_id"] for row in eligibility}
    denial_ids = {row["denial_id"] for row in denials}
    remittance_ids = {row["remittance_id"] for row in remittances}
    assert len(claim_ids) == len(claims) == 80
    assert len(eligibility_ids) == len(eligibility) == 80
    assert all(row["eligibility_id"] in eligibility_ids for row in claims)
    assert all(row["claim_id"] in claim_ids for row in claim_lines)
    assert all(row["claim_id"] in claim_ids for row in denials)
    assert all(row["denial_id"] in denial_ids for row in appeals)
    assert all(row["remittance_id"] in remittance_ids for row in payments if row["remittance_id"])

    line_totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    money_fields = (
        "billed_amount",
        "payer_paid_amount",
        "patient_paid_amount",
        "adjustment_amount",
        "outstanding_balance",
    )
    for row in claim_lines:
        for field in money_fields:
            line_totals[row["claim_id"]][field] += Decimal(row[field])
    for claim in claims:
        for field in money_fields:
            assert line_totals[claim["claim_id"]][field] == Decimal(claim[field])
        assert Decimal(claim["billed_amount"]) == sum(
            Decimal(claim[field])
            for field in (
                "payer_paid_amount",
                "patient_paid_amount",
                "adjustment_amount",
                "outstanding_balance",
            )
        )

    payment_totals: dict[str, Decimal] = defaultdict(Decimal)
    payment_counts: dict[str, int] = defaultdict(int)
    for payment in payments:
        if payment["remittance_id"]:
            assert payment["transaction_type"] == "payer_payment"
            payment_totals[payment["remittance_id"]] += Decimal(payment["amount"])
            payment_counts[payment["remittance_id"]] += 1
    for remittance in remittances:
        remittance_id = remittance["remittance_id"]
        assert payment_totals[remittance_id] == Decimal(remittance["total_payment_amount"])
        assert payment_counts[remittance_id] == int(remittance["claim_transaction_count"])

    transactions: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for payment in payments:
        transactions[(payment["claim_id"], payment["transaction_type"])] += Decimal(
            payment["amount"]
        )
    for claim in claims:
        claim_id = claim["claim_id"]
        if claim["claim_status"] == "paid":
            assert transactions[(claim_id, "payer_payment")] == Decimal(claim["payer_paid_amount"])
            assert transactions[(claim_id, "patient_payment")] == Decimal(
                claim["patient_paid_amount"]
            )
            assert transactions[(claim_id, "contractual_adjustment")] == Decimal(
                claim["adjustment_amount"]
            )
        else:
            assert not any(key[0] == claim_id for key in transactions)


def _assert_definition_matches_contract(
    definition: SourceDefinition,
    contract: dict[str, Any],
) -> None:
    assert definition.contract_id == contract["contract_id"]
    assert definition.contract_version == str(contract["contract_version"])
    assert definition.file_pattern == contract["delivery"]["file_pattern"]
    if definition.dataset is None:
        expected_columns = tuple(field["name"] for field in contract["schema"])
    else:
        dataset = next(item for item in contract["datasets"] if item["name"] == definition.dataset)
        expected_columns = tuple(field["name"] for field in dataset["schema"])
    assert definition.columns == expected_columns


def test_generator_catalog_matches_governed_yaml_contracts() -> None:
    contracts = {
        contract["source_family"]: contract
        for path in (ROOT / "contracts/source-data").glob("*.yml")
        if isinstance((contract := cast(dict[str, Any], yaml.safe_load(path.read_text()))), dict)
    }

    for definition in source_definitions():
        _assert_definition_matches_contract(definition, contracts[definition.source_family])


def test_contract_comparison_detects_catalog_drift() -> None:
    contract = cast(
        dict[str, Any],
        yaml.safe_load((ROOT / "contracts/source-data/payments.yml").read_text()),
    )
    drifted = replace(PAYMENTS, file_pattern="{source_system}_payments_{extract_at_utc}.csv")

    with pytest.raises(AssertionError):
        _assert_definition_matches_contract(drifted, contract)


def test_generated_identity_values_are_reserved_as_synthetic(tmp_path: Path) -> None:
    config = GenerationConfig.from_values(seed=19, claim_count=20, service_month="2026-07")
    result = generate_delivery(config, tmp_path / "delivery")
    manifest = load_manifest(result.output_directory)

    claims = rows_for(result.output_directory, manifest, "claims")
    eligibility = rows_for(result.output_directory, manifest, "eligibility")
    marker = f"-{config.delivery_namespace}-"
    assert all(row["patient_id"].startswith("SYN-PAT-") for row in claims)
    assert all(row["patient_id"].startswith("SYN-PAT-") for row in eligibility)
    assert all(row["member_reference"].startswith("SYN-MBR-") for row in eligibility)
    for family, fields in {
        "claims": ("claim_id", "patient_id"),
        "claim-lines": ("claim_line_id",),
        "eligibility": ("eligibility_id", "patient_id", "member_reference"),
        "remittances": ("remittance_id",),
        "payments": ("payment_id",),
        "denials": ("denial_id",),
        "appeals": ("appeal_id",),
    }.items():
        for row in rows_for(result.output_directory, manifest, family):
            assert all(marker in row[field] for field in fields)
    assert manifest["synthetic_only"] is True


def test_generator_never_overwrites_an_existing_path(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("user-owned")
    config = GenerationConfig.from_values(seed=1, claim_count=1, service_month="2026-07")

    with pytest.raises(GenerationError, match="already exists"):
        generate_delivery(config, output)

    assert sentinel.read_text() == "user-owned"
