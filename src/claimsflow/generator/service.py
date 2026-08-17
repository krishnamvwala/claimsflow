"""Atomic CSV and provenance-manifest writer for synthetic deliveries."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from claimsflow.generator.catalog import SourceDefinition, render_file_name
from claimsflow.generator.manifest import validate_manifest
from claimsflow.generator.models import (
    GENERATOR_NAME,
    MANIFEST_SCHEMA_VERSION,
    GenerationConfig,
    GenerationError,
    GenerationResult,
)
from claimsflow.generator.records import Row, source_rows


class _Sha256TextSink:
    """Minimal text writer used to reproduce exact CSV hashes without disk output."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        self._digest.update(encoded)
        return len(value)

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _write_rows(output: TextIO, definition: SourceDefinition, rows: Iterable[Row]) -> int:
    count = 0
    writer = csv.DictWriter(
        output,
        fieldnames=definition.columns,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        if set(row) != set(definition.columns):
            missing = sorted(set(definition.columns) - set(row))
            extra = sorted(set(row) - set(definition.columns))
            raise GenerationError(
                f"{definition.source_family} row/header mismatch; missing={missing}, extra={extra}"
            )
        writer.writerow(row)
        count += 1
    return count


def _write_csv(path: Path, definition: SourceDefinition, rows: Iterable[Row]) -> int:
    with path.open("w", encoding="utf-8", newline="") as output:
        return _write_rows(output, definition, rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(
    config: GenerationConfig,
    files: list[dict[str, Any]],
    total_rows: int,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "batch_id": config.batch_id,
        "synthetic_only": True,
        "generated_at_utc": config.generated_at.isoformat().replace("+00:00", "Z"),
        "generator": {
            "name": GENERATOR_NAME,
            "version": config.generator_version,
            "seed": config.seed,
            "claim_count": config.claim_count,
            "service_month": config.service_month.strftime("%Y-%m"),
            "config_sha256": config.fingerprint_sha256,
        },
        "source_families": sorted({str(item["source_family"]) for item in files}),
        "files": files,
        "row_count_reconciliation": {
            "generated_rows": total_rows,
            "written_rows": total_rows,
            "reconciled": True,
        },
        "limitations": [
            "Fictional portfolio data only; never approved for clinical or billing use.",
            "CSV fixtures are simplified source extracts and are not X12 EDI certification data.",
            "Generation creates local delivery evidence only and performs no cloud upload.",
        ],
    }


def expected_manifest(config: GenerationConfig) -> dict[str, Any]:
    """Reproduce exact approved delivery evidence without creating payload files."""

    file_evidence: list[dict[str, Any]] = []
    total_rows = 0
    for source in source_rows(config):
        file_name = render_file_name(source.definition, config)
        sink = _Sha256TextSink()
        row_count = _write_rows(sink, source.definition, source.rows)  # type: ignore[arg-type]
        total_rows += row_count
        evidence: dict[str, Any] = {
            "path": f"files/{file_name}",
            "file_name": file_name,
            "source_family": source.definition.source_family,
            "source_system": source.definition.source_system,
            "contract_id": source.definition.contract_id,
            "contract_version": source.definition.contract_version,
            "row_count": row_count,
            "sha256": sink.hexdigest,
        }
        if source.definition.dataset is not None:
            evidence["dataset"] = source.definition.dataset
        file_evidence.append(evidence)
    return _manifest(config, file_evidence, total_rows)


def generate_delivery(config: GenerationConfig, output_directory: Path) -> GenerationResult:
    """Generate a complete delivery without overwriting or partially publishing a target."""

    target = output_directory.expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise GenerationError(f"output directory already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        files_directory = temporary / "files"
        files_directory.mkdir()
        file_evidence: list[dict[str, Any]] = []
        total_rows = 0
        for source in source_rows(config):
            file_name = render_file_name(source.definition, config)
            path = files_directory / file_name
            row_count = _write_csv(path, source.definition, source.rows)
            total_rows += row_count
            evidence: dict[str, Any] = {
                "path": f"files/{file_name}",
                "file_name": file_name,
                "source_family": source.definition.source_family,
                "source_system": source.definition.source_system,
                "contract_id": source.definition.contract_id,
                "contract_version": source.definition.contract_version,
                "row_count": row_count,
                "sha256": _sha256(path),
            }
            if source.definition.dataset is not None:
                evidence["dataset"] = source.definition.dataset
            file_evidence.append(evidence)

        manifest = _manifest(config, file_evidence, total_rows)
        validate_manifest(manifest, temporary)
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if target.exists() or target.is_symlink():
            raise GenerationError(f"output directory appeared during generation: {target}")
        temporary.rename(target)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    return GenerationResult(
        batch_id=config.batch_id,
        output_directory=target,
        manifest_path=target / "manifest.json",
        file_count=len(file_evidence),
        total_rows=total_rows,
    )
