"""Semantic validation for synthetic delivery evidence and local artifacts."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from claimsflow.generator.catalog import render_file_name, source_definitions
from claimsflow.generator.models import GENERATOR_NAME, GenerationConfig, GenerationError


class ManifestValidationError(GenerationError):
    """Raised when delivery evidence is incomplete or internally inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ManifestValidationError(f"{field} must be an integer")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ManifestValidationError(
            f"{field} keys do not match; missing={missing}, extra={extra}"
        )


def validate_manifest(
    manifest: dict[str, Any],
    delivery_directory: Path | None = None,
) -> None:
    """Validate cross-field inventory, identity, row-count, and optional file evidence."""

    try:
        generator_value = manifest["generator"]
        files_value = manifest["files"]
        reconciliation_value = manifest["row_count_reconciliation"]
    except KeyError as error:
        raise ManifestValidationError(f"manifest is missing {error.args[0]}") from error
    if not isinstance(generator_value, dict):
        raise ManifestValidationError("generator must be an object")
    if not isinstance(files_value, list) or not all(isinstance(item, dict) for item in files_value):
        raise ManifestValidationError("files must be an array of objects")
    if not isinstance(reconciliation_value, dict):
        raise ManifestValidationError("row_count_reconciliation must be an object")

    generator: dict[str, Any] = generator_value
    files: list[dict[str, Any]] = files_value
    reconciliation: dict[str, Any] = reconciliation_value
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "batch_id",
            "synthetic_only",
            "generated_at_utc",
            "generator",
            "source_families",
            "files",
            "row_count_reconciliation",
            "limitations",
        },
        "manifest",
    )
    _require_exact_keys(
        generator,
        {"name", "version", "seed", "claim_count", "service_month", "config_sha256"},
        "generator",
    )
    _require_exact_keys(
        reconciliation,
        {"generated_rows", "written_rows", "reconciled"},
        "row_count_reconciliation",
    )
    try:
        config = GenerationConfig.from_values(
            seed=_integer(generator["seed"], "generator.seed"),
            claim_count=_integer(generator["claim_count"], "generator.claim_count"),
            service_month=generator["service_month"],
            generator_version=generator["version"],
        )
    except KeyError as error:
        raise ManifestValidationError(f"generator is missing {error.args[0]}") from error
    except TypeError as error:
        raise ManifestValidationError("generator values have invalid types") from error
    if generator.get("name") != GENERATOR_NAME:
        raise ManifestValidationError("generator.name is not approved")

    expected_definitions = {
        (definition.source_family, definition.dataset): definition
        for definition in source_definitions()
    }
    actual_inventory: list[tuple[str, str | None]] = []
    paths: list[str] = []
    file_names: list[str] = []
    row_total = 0
    for index, entry in enumerate(files):
        source_family = entry.get("source_family")
        dataset = entry.get("dataset")
        if not isinstance(source_family, str) or not (dataset is None or isinstance(dataset, str)):
            raise ManifestValidationError(f"files[{index}] has an invalid inventory key")
        key = (source_family, dataset)
        actual_inventory.append(key)
        definition = expected_definitions.get(key)
        if definition is None:
            raise ManifestValidationError(f"files[{index}] has an unapproved inventory key: {key}")
        expected_entry_keys = {
            "path",
            "file_name",
            "source_family",
            "source_system",
            "contract_id",
            "contract_version",
            "row_count",
            "sha256",
        }
        if definition.dataset is not None:
            expected_entry_keys.add("dataset")
        _require_exact_keys(entry, expected_entry_keys, f"files[{index}]")
        file_name = entry.get("file_name")
        path = entry.get("path")
        if not isinstance(file_name, str) or not isinstance(path, str):
            raise ManifestValidationError(f"files[{index}] path values must be strings")
        expected_file_name = render_file_name(definition, config)
        if file_name != expected_file_name:
            raise ManifestValidationError(
                f"files[{index}].file_name does not match the governed delivery pattern"
            )
        if path != f"files/{file_name}":
            raise ManifestValidationError(f"files[{index}].path must equal files/<file_name>")
        paths.append(path)
        file_names.append(file_name)
        for field, expected in (
            ("source_system", definition.source_system),
            ("contract_id", definition.contract_id),
            ("contract_version", definition.contract_version),
        ):
            if entry.get(field) != expected:
                raise ManifestValidationError(f"files[{index}].{field} does not match the catalog")
        row_count = _integer(entry.get("row_count"), f"files[{index}].row_count")
        if row_count < 0:
            raise ManifestValidationError(f"files[{index}].row_count cannot be negative")
        row_total += row_count

        if delivery_directory is not None:
            file_path = delivery_directory / str(path)
            if not file_path.is_file():
                raise ManifestValidationError(f"delivery file is missing: {path}")
            if entry.get("sha256") != _sha256(file_path):
                raise ManifestValidationError(f"delivery checksum does not match: {path}")
            with file_path.open(newline="", encoding="utf-8") as source:
                reader = csv.reader(source)
                try:
                    header = tuple(next(reader))
                except StopIteration as error:
                    raise ManifestValidationError(f"delivery file has no header: {path}") from error
                if header != definition.columns:
                    raise ManifestValidationError(
                        f"delivery header does not match contract: {path}"
                    )
                actual_rows = sum(1 for _ in reader)
            if actual_rows != entry["row_count"]:
                raise ManifestValidationError(f"delivery row count does not match: {path}")

    if Counter(actual_inventory) != Counter(expected_definitions.keys()):
        raise ManifestValidationError("files must contain the exact governed 14-file inventory")
    if len(paths) != len(set(paths)) or len(file_names) != len(set(file_names)):
        raise ManifestValidationError("delivery paths and file names must be unique")

    expected_families = sorted({definition.source_family for definition in source_definitions()})
    if manifest.get("source_families") != expected_families:
        raise ManifestValidationError("source_families must contain the exact governed inventory")
    if manifest.get("schema_version") != "1.0.0":
        raise ManifestValidationError("schema_version must be 1.0.0")
    if manifest.get("synthetic_only") is not True:
        raise ManifestValidationError("synthetic_only must remain true")
    limitations = manifest.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(item, str) and item for item in limitations)
        or len(limitations) != len(set(limitations))
    ):
        raise ManifestValidationError("limitations must contain unique non-empty strings")
    if manifest.get("batch_id") != config.batch_id:
        raise ManifestValidationError("batch_id does not match the canonical generator inputs")
    if generator.get("config_sha256") != config.fingerprint_sha256:
        raise ManifestValidationError("config_sha256 does not match the canonical generator inputs")
    expected_generated_at = config.generated_at.isoformat().replace("+00:00", "Z")
    if manifest.get("generated_at_utc") != expected_generated_at:
        raise ManifestValidationError("generated_at_utc does not match the logical extract time")

    generated_rows = _integer(
        reconciliation.get("generated_rows"),
        "row_count_reconciliation.generated_rows",
    )
    written_rows = _integer(
        reconciliation.get("written_rows"),
        "row_count_reconciliation.written_rows",
    )
    if generated_rows != row_total or written_rows != row_total:
        raise ManifestValidationError("row-count reconciliation does not equal file row counts")
    if reconciliation.get("reconciled") is not True:
        raise ManifestValidationError("row-count reconciliation must be true")
